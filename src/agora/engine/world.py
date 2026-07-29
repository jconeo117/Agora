"""El tick loop: donde el mundo avanza.

Todo lo demás del motor son piezas; esto es lo que las hace correr. El orden de
las operaciones dentro de un tick no es arbitrario, y cambiarlo cambia el
comportamiento del mundo, así que está documentado paso a paso más abajo.

Dos invariantes que sostienen el determinismo:

1. **Orden fijo de agentes.** Siempre `agents_in_order()`, nunca la iteración
   de un set. El mismo seed debe producir el mismo log byte a byte.
2. **Nada muta el estado sin emitir un evento.** Para las capas de arriba
   (memoria en F1, narrador en F5), lo que no está en el log no ocurrió.
"""

from __future__ import annotations

from typing import assert_never

from agora.agents.decide import Decision, critical_need, current_intent, decide, is_available
from agora.engine.events import EventKind, EventLog, Payload
from agora.engine.ontology import ActionId, AgentId, NeedId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Busy, PerformingAction, Traveling, WorldState


class Simulation:
    """Un mundo corriendo. Estado mutable + su registro de eventos."""

    __slots__ = ("_together", "log", "state")

    def __init__(self, pack: ContentPack, seed: int) -> None:
        self.state = WorldState.new(pack, seed)
        self.log = EventLog()
        self._together: set[tuple[AgentId, AgentId]] = set()
        """Quién estaba con quién el tick pasado. Sirve para emitir un
        encuentro cuando se produce y no en cada uno de los ticks que dos
        agentes pasan en la misma sala."""

    @property
    def pack(self) -> ContentPack:
        return self.state.pack

    # -------------------------------------------------------------------------
    # Bucle
    # -------------------------------------------------------------------------

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.tick()

    def tick(self) -> None:
        """Un paso del mundo.

        El orden importa:

        1. **Avanza el reloj.** Todo lo que ocurra lleva ya el tick nuevo.
        2. **Decae todo el mundo a la vez.** Antes de que nadie actúe, para que
           todos los agentes decidan sobre el mismo instante. Si el decaimiento
           se intercalara con las acciones, el primer agente de la lista
           decidiría con información medio tick más vieja que el último.
        3. **Cada agente resuelve su ocupación**, en orden fijo.
        4. **Se detectan los encuentros**, ya con todos en su sitio final. Si se
           hiciera durante el paso 3, un agente que aún no se ha movido
           generaría un encuentro en un lugar que está a punto de abandonar.
        """
        self.state.tick += 1
        self._decay_everyone()
        for agent in self.state.agents_in_order():
            self._resolve(agent)
        self._detect_encounters()

    # -------------------------------------------------------------------------
    # Fases
    # -------------------------------------------------------------------------

    def _decay_everyone(self) -> None:
        """Baja las necesidades y avisa de las que cruzan el umbral crítico.

        El evento se emite en la TRANSICIÓN, no mientras la necesidad sigue
        baja. Si se emitiera cada tick, un agente hambriento llenaría el log con
        cientos de líneas idénticas y, en F1, su memoria con cientos de
        recuerdos del mismo hecho.
        """
        specs = self.pack.need_by_id
        # La ocupación se mide ANTES de que nadie se mueva este tick, así que
        # todos los agentes ven la misma foto. Calcularla dentro del bucle haría
        # que el primero de la lista decidiera sobre un mundo distinto al último.
        occupancy = self.state.occupancy()

        for agent in self.state.agents_in_order():
            # El umbral es de cada cual: quien aguanta más tarda más en alarmarse.
            threshold = agent.temperament.critical_need_threshold
            before = dict(agent.needs)
            agent.decay(specs, company=occupancy.get(agent.at, 0) - 1)
            agent.recover_novelty(self.pack.tuning.saturation_recovery)
            for need_id, value in agent.needs.items():
                if before[need_id] >= threshold > value:
                    self._emit(
                        EventKind.NEED_CRITICAL,
                        agent,
                        data={"need": str(need_id), "value": round(value, 4)},
                    )

    def _resolve(self, agent: AgentState) -> None:
        """Consume un tick de lo que el agente esté haciendo y reacciona."""
        agent.advance()

        forced: NeedId | None = None
        busy = agent.busy
        if busy is not None and busy.ticks_remaining == 0:
            self._complete(agent, busy)
        elif busy is not None:
            urgent = critical_need(self.state, agent)
            if urgent is not None:
                self._abort(agent, urgent)
                forced = urgent

        # Deliberar al final: cubre tanto al que ya estaba ocioso como al que
        # acaba de terminar o abandonar. Así nunca se desperdicia un tick.
        #
        # `forced` se arrastra hasta aquí a propósito: quien acaba de abandonar
        # por una emergencia tiene que elegir algo que la atienda. Si no, vuelve
        # a elegir lo mismo que estaba haciendo y el ciclo no termina nunca.
        if agent.busy is None:
            self._begin(agent, forced)

    def _complete(self, agent: AgentState, busy: Busy) -> None:
        match busy:
            case PerformingAction():
                spec = self.pack.action_by_id[busy.action]
                agent.apply(spec.effects)
                agent.saturate(busy.action, spec.saturation_gain)
                self._emit(EventKind.ACTION_COMPLETED, agent, action=busy.action)
                agent.busy = None
            case Traveling():
                self._arrive(agent, busy)
            case _:
                assert_never(busy)

    def _arrive(self, agent: AgentState, busy: Traveling) -> None:
        """Llegada a un nodo: fin de trayecto o siguiente tramo."""
        agent.at = busy.next_hop

        if agent.at != busy.destination:
            self._next_leg(agent, busy)
            return

        self._emit(EventKind.TRAVEL_ARRIVED, agent, action=busy.intent)

        # Honrar el compromiso: se viajó A POR ALGO, así que se hace, sin
        # volver a deliberar. Redeliberar aquí desperdiciaría el viaje cada vez
        # que otra necesidad hubiera subido un poco durante el trayecto, y el
        # agente parecería incapaz de terminar nada.
        action = self.pack.action_by_id[busy.intent]
        company = len(self.state.others_at(agent))
        if is_available(action, self.pack.place_by_id[agent.at], company, agent.needs):
            self._start_action(agent, busy.intent, utility=None)
        else:
            # El mundo cambió durante el viaje: normalmente, que la gente por la
            # que venías ya no está. Es el "fui a la plaza y no había nadie", y
            # se registra para que se pueda leer en el log.
            self._emit(
                EventKind.ACTION_ABORTED,
                agent,
                action=busy.intent,
                data={"reason": "condiciones", "company": company},
            )
            agent.busy = None

    def _next_leg(self, agent: AgentState, busy: Traveling) -> None:
        hop = self.state.travel.first_hop(agent.at, busy.destination)
        if hop is None:  # pragma: no cover - un pack validado lo impide
            agent.busy = None
            return
        agent.busy = Traveling(
            destination=busy.destination,
            intent=busy.intent,
            next_hop=hop,
            ticks_remaining=self.state.travel.distance(agent.at, hop),
            total_ticks=busy.total_ticks,  # el trayecto no se reinicia en cada cruce
        )

    def _abort(self, agent: AgentState, urgent: NeedId) -> None:
        self._emit(
            EventKind.ACTION_ABORTED,
            agent,
            action=current_intent(agent),
            data={"need": str(urgent), "value": round(agent.needs[urgent], 4)},
        )
        agent.busy = None

    def _begin(self, agent: AgentState, must_address: NeedId | None = None) -> None:
        choice = decide(self.state, agent, must_address)
        if choice is None:  # pragma: no cover - un pack validado lo impide
            self._emit(EventKind.IDLE_STALLED, agent)
            return
        if choice.travel_ticks == 0:
            self._start_action(agent, choice.action, choice.utility)
        else:
            self._start_travel(agent, choice)

    def _start_action(self, agent: AgentState, action: ActionId, utility: float | None) -> None:
        spec = self.pack.action_by_id[action]
        agent.busy = PerformingAction(action=action, ticks_remaining=spec.duration_ticks)
        data: Payload = {} if utility is None else {"utility": round(utility, 4)}
        self._emit(EventKind.ACTION_STARTED, agent, action=action, data=data)

    def _start_travel(self, agent: AgentState, choice: Decision) -> None:
        hop = self.state.travel.first_hop(agent.at, choice.place)
        if hop is None:  # pragma: no cover - un pack validado lo impide
            self._emit(EventKind.IDLE_STALLED, agent)
            return
        agent.busy = Traveling(
            destination=choice.place,
            intent=choice.action,
            next_hop=hop,
            ticks_remaining=self.state.travel.distance(agent.at, hop),
            total_ticks=choice.travel_ticks,
        )
        self._emit(
            EventKind.TRAVEL_STARTED,
            agent,
            action=choice.action,
            data={
                "to": str(choice.place),
                "ticks": choice.travel_ticks,
                "utility": round(choice.utility, 4),
            },
        )

    def _detect_encounters(self) -> None:
        """Emite un encuentro cuando dos agentes coinciden, una sola vez.

        Se compara con la compañía del tick anterior en vez de emitir mientras
        dure la coincidencia. Sin eso, dos agentes trabajando juntos siete horas
        generarían 28 eventos idénticos.
        """
        agents = self.state.agents_in_order()
        current: set[tuple[AgentId, AgentId]] = {
            (first.spec_id, second.spec_id)
            for index, first in enumerate(agents)
            for second in agents[index + 1 :]
            if first.at == second.at
        }

        # `sorted` para que el orden de los eventos no dependa del de un set.
        for actor, subject in sorted(current - self._together):
            self.log.emit(
                tick=self.state.tick,
                kind=EventKind.ENCOUNTER,
                actor=actor,
                subject=subject,
                place=self.state.agents[actor].at,
            )

        self._together = current

    # -------------------------------------------------------------------------

    def _emit(
        self,
        kind: EventKind,
        agent: AgentState,
        *,
        action: ActionId | None = None,
        data: Payload | None = None,
    ) -> None:
        """Atajo: casi todos los eventos son "este agente, aquí, ahora"."""
        self.log.emit(
            tick=self.state.tick,
            kind=kind,
            actor=agent.spec_id,
            place=agent.at,
            action=action,
            data=data,
        )
