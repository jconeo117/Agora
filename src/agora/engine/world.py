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

from agora.agents.decide import (
    Decision,
    critical_need,
    current_intent,
    decide,
    is_available,
    planned_duration,
    recovery_rate,
)
from agora.engine.events import EventKind, EventLog, Payload
from agora.engine.ontology import ActionId, AgentId, GoalStatus, NeedId
from agora.engine.outcome import company_premium, contextual_effects, learn
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
        3. **Se cierran las metas cumplidas o vencidas**, para todos antes de que
           nadie actúe: los pesos recompuestos valen ya en la decisión de este
           tick, y quien logró algo no pasa un tick más empujando hacia ello.
        4. **Cada agente resuelve su ocupación**, en orden fijo.
        5. **Se detectan los encuentros**, ya con todos en su sitio final. Si se
           hiciera durante el paso 4, un agente que aún no se ha movido
           generaría un encuentro en un lugar que está a punto de abandonar.
        """
        self.state.tick += 1
        self._decay_everyone()
        for agent in self.state.agents_in_order():
            self._settle_goals(agent)
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
        tuning = self.pack.tuning
        tick = self.state.tick
        # La ocupación se mide ANTES de que nadie se mueva este tick, así que
        # todos los agentes ven la misma foto. Calcularla dentro del bucle haría
        # que el primero de la lista decidiera sobre un mundo distinto al último.
        occupants = self.state.occupants()

        for agent in self.state.agents_in_order():
            # Ve a quién tiene delante, y solo eso. Se anota antes de que nadie
            # se mueva, así que todos observan la misma foto.
            others = occupants.get(agent.at, frozenset()) - {agent.spec_id}
            agent.observe(tick, others)

            # Olvidar va antes de todo lo demás: quien ya no está en tu vida no
            # debería seguir pesando en el alivio de esta misma ronda.
            agent.forget_bonds(tick, tuning.bond_horizon)

            # El umbral es de cada cual: quien aguanta más tarda más en alarmarse.
            threshold = agent.temperament.critical_need_threshold
            before = dict(agent.needs)
            agent.decay(
                specs,
                company=agent.effective_company(
                    others, tick, tuning.bond_weight, tuning.bond_fade
                ),
            )
            agent.recover_novelty(self.pack.tuning.saturation_recovery)
            # Después del decaimiento: el desgaste y el temperamento que se
            # derivan de él tienen que reflejar el estado de ESTE tick, no del
            # anterior. El umbral crítico que se comprueba justo debajo sale de
            # aquí.
            agent.refresh_state(self.pack)
            for need_id, value in agent.needs.items():
                if before[need_id] >= threshold > value:
                    self._emit(
                        EventKind.NEED_CRITICAL,
                        agent,
                        data={"need": str(need_id), "value": round(value, 4)},
                    )

    def _settle_goals(self, agent: AgentState) -> None:
        """Cierra las metas que se han cumplido o se han quedado sin plazo.

        Se comprueba **después del decaimiento y antes de deliberar**, para que
        los pesos recompuestos valgan ya en la decisión de este mismo tick. Al
        revés, el agente pasaría un tick empujando hacia algo que ya tiene.

        Aquí es donde `drift_trait` se estrena: lleva construido desde F1 y no lo
        llamaba nadie. Es lo que separa un logro de un arco — sin la deriva, el
        personaje llega a su meta y sigue siendo exactamente quien era.
        """
        spec = self.pack.agent_by_id[agent.spec_id]
        for goal in spec.goals:
            if agent.goals.get(goal.id) is not GoalStatus.ACTIVE:
                continue

            if agent.needs[goal.need] >= goal.at_least:
                resultado, derivas = GoalStatus.ACHIEVED, goal.on_success
            elif goal.deadline is not None and self.state.tick >= goal.deadline:
                resultado, derivas = GoalStatus.FAILED, goal.on_failure
            else:
                continue

            agent.goals[goal.id] = resultado
            self._emit(
                EventKind.GOAL_ACHIEVED
                if resultado is GoalStatus.ACHIEVED
                else EventKind.GOAL_FAILED,
                agent,
                data={"goal": str(goal.id), "need": str(goal.need)},
            )
            # Ordenadas por id: `drift_trait` recompone en cada llamada y la
            # multiplicación en coma flotante no es asociativa.
            for trait in sorted(derivas):
                agent.drift_trait(self.pack, trait, derivas[trait])
            # Aunque no hubiera derivas: la meta ha dejado de empujar y el peso
            # que le prestaba a su eje tiene que devolverse.
            agent.recompose(self.pack)

    def _resolve(self, agent: AgentState) -> None:
        """Consume un tick de lo que el agente esté haciendo y reacciona."""
        agent.advance()

        forced: NeedId | None = None
        busy = agent.busy
        if busy is not None and busy.ticks_remaining == 0:
            self._complete(agent, busy)
        elif busy is not None and self._can_drop(busy):
            urgent = critical_need(self.state, agent)
            # Solo se abandona si existe algo que ATIENDA la urgencia. Sin esta
            # comprobación, un agente sin dinero ni despensa reinicia su turno
            # cada tick: la peor urgencia es la despensa, comprarla exige dinero
            # que no tiene, y trabajar —que es justo lo que hay que hacer— no la
            # atiende. Interrumpir para hacer algo que no puedes hacer solo
            # destruye el plan que sí resolvía el problema.
            if urgent is not None and decide(self.state, agent, urgent) is not None:
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

    def _can_drop(self, busy: Busy) -> bool:
        """¿Se puede soltar esto por una urgencia?

        Solo protege lo que se está EJECUTANDO, no el viaje hacia ello: se puede
        dar media vuelta de camino a la batalla, lo que no se puede es abandonarla
        a la mitad para echar una cabezada.

        Y es lo que hace posible la deuda. Mientras todo se pueda soltar, un
        agente se autolimita y nunca llega al agotamiento extremo: la necesidad no
        llega a hundirse y no hay nada que acumular.
        """
        match busy:
            case PerformingAction():
                return self.pack.action_by_id[busy.action].interruptible
            case Traveling():
                return True
            case _:  # pragma: no cover
                assert_never(busy)

    def _complete(self, agent: AgentState, busy: Busy) -> None:
        match busy:
            case PerformingAction():
                self._finish_action(agent, busy.action, busy.total_ticks)
            case Traveling():
                self._arrive(agent, busy)
            case _:
                assert_never(busy)

    def _finish_action(self, agent: AgentState, action_id: ActionId, done: int) -> None:
        """Aplica el resultado real y aprende de la diferencia con lo prometido.

        El orden importa: el estado ANTES de aplicar es lo que permite saber si
        el techo de la necesidad recortó el efecto, y de un efecto recortado no
        se aprende nada — que te recorten la comida por estar lleno no dice nada
        sobre la comida.

        `done` son los ticks realmente cumplidos, y solo importa para lo elástico:
        ahí el efecto es `ritmo * tiempo`, así que soltarlo a medias acredita la
        mitad en vez de no acreditar nada. Sin eso, la elasticidad EMPEORA las
        cosas — comprometer quince horas para no cobrar nada si te levantan es
        peor que comprometer ocho.
        """
        spec = self.pack.action_by_id[action_id]
        tuning = self.pack.tuning
        tick = self.state.tick

        others = [other.spec_id for other in self.state.others_at(agent)]
        company = agent.effective_company(others, tick, tuning.bond_weight, tuning.bond_fade)
        received = contextual_effects(spec, company)

        before = dict(agent.needs)
        agent.apply(received, self.pack.need_by_id)

        if spec.elastic is not None and done > 0:
            rate = recovery_rate(spec, agent, self.pack.place_by_id[agent.at])
            agent.restore(spec.elastic.need, rate * done)

        learn(
            agent.gain_beliefs.setdefault(action_id, {}),
            agent.cost_beliefs.setdefault(action_id, {}),
            spec,
            received,
            before,
            tuning.learning_rate,
        )
        # Y de paso, qué concluye sobre la gente que estaba delante. Se aprende
        # de lo mismo que se acaba de vivir y con el estado de ANTES, igual que
        # las creencias: lo que valió el rato lo decide la necesidad que traías.
        #
        # Solo para lo que el pack declara compartido, y la guarda es necesaria,
        # no cosmética. Sin ella se actualiza el vínculo al terminar CUALQUIER
        # cosa con alguien delante, con premio cero, y un turno de trabajo en la
        # misma sala arrastra el aprecio hacia abajo. Medido: los turnos
        # compartidos son mucho más frecuentes que las comidas compartidas y se
        # comían la señal entera — los aprecios de treinta días se quedaban en
        # 0.05 cuando el equilibrio de una charla está en 0.43. Compartir sala
        # mientras cada uno va a lo suyo no acerca; tampoco tiene por qué alejar.
        if spec.effects_per_company:
            agent.remember_company(
                others,
                company_premium(
                    spec,
                    self.pack.need_by_id,
                    agent.need_weights,
                    before,
                    company,
                    tuning.bond_scale,
                ),
                tuning.bond_rate,
                tick,
            )
        agent.saturate(action_id, spec.saturation_gain)

        data: Payload = {"company": round(company, 4)} if spec.effects_per_company else {}
        self._emit(EventKind.ACTION_COMPLETED, agent, action=action_id, data=data)
        agent.busy = None

    def _arrive(self, agent: AgentState, busy: Traveling) -> None:
        """Llegada a un nodo: fin de trayecto o siguiente tramo."""
        # El peaje se cobra al cruzar, tramo a tramo. Antes de mover al agente,
        # que es cuando `agent.at` todavía dice de dónde viene.
        peaje = self.pack.place_by_id[agent.at].tolls.get(busy.next_hop)
        if peaje:
            agent.apply({need: -amount for need, amount in peaje.items()}, self.pack.need_by_id)
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
        # La franja es la de AHORA, no la de cuando se decidió: un viaje largo
        # puede acabar con el sitio ya cerrado, y eso es un chasco legítimo que
        # se lee igual que llegar y no encontrar a nadie.
        phase = self.pack.clock.phase_at(self.state.tick)
        if is_available(
            action, self.pack.place_by_id[agent.at], company, agent.needs, phase, agent.traits
        ):
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
        # Lo elástico cobra lo que llevaba hecho. Sin esto, quien se levanta a
        # falta de un tick se queda sin absolutamente nada, y comprometer quince
        # horas sería una temeridad en vez de una necesidad.
        busy = agent.busy
        if isinstance(busy, PerformingAction):
            spec = self.pack.action_by_id[busy.action]
            hechos = busy.total_ticks - busy.ticks_remaining
            if spec.elastic is not None and hechos > 0:
                rate = recovery_rate(spec, agent, self.pack.place_by_id[agent.at])
                agent.restore(spec.elastic.need, rate * hechos)
        self._emit(
            EventKind.ACTION_ABORTED,
            agent,
            action=current_intent(agent),
            data={"need": str(urgent), "value": round(agent.needs[urgent], 4)},
        )
        agent.busy = None

    def _begin(self, agent: AgentState, must_address: NeedId | None = None) -> None:
        choice = decide(self.state, agent, must_address)
        if choice is None and must_address is not None:
            # El mundo pudo cambiar entre comprobar que había remedio y llegar
            # aquí. Ocioso es peor que mal atendido: se elige sin restricción.
            choice = decide(self.state, agent)
        if choice is None:  # pragma: no cover - un pack validado lo impide
            self._emit(EventKind.IDLE_STALLED, agent)
            return
        if choice.travel_ticks == 0:
            self._start_action(agent, choice.action, choice.utility)
        else:
            self._start_travel(agent, choice)

    def _start_action(self, agent: AgentState, action: ActionId, utility: float | None) -> None:
        spec = self.pack.action_by_id[action]
        # La duración se fija AQUÍ y se guarda: con lo elástico sale del déficit
        # de este agente en este sitio, y el pack ya no la sabe. Recalcularla por
        # tick alargaría el sueño cada vez que el agente se repone un poco.
        ticks = planned_duration(spec, agent, self.pack.place_by_id[agent.at])
        agent.busy = PerformingAction(action=action, ticks_remaining=ticks, total_ticks=ticks)
        data: Payload = {} if utility is None else {"utility": round(utility, 4)}
        if spec.elastic is not None:
            data = {**data, "ticks": ticks}
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
            # Cruzarse te hace conocer a alguien; compartir algo con él te hace
            # apreciarlo o detestarlo. Aquí solo lo primero, y en ambos sentidos:
            # el vínculo es asimétrico en lo que se siente, no en quién se ve.
            self.state.agents[actor].meet(subject, self.state.tick)
            self.state.agents[subject].meet(actor, self.state.tick)
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
