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

from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from agora.agents.decide import (
    Decision,
    critical_need,
    current_intent,
    decide,
    is_available,
    planned_duration,
    recovery_rate,
)
from agora.engine import persistence
from agora.engine.disposition import urgency
from agora.engine.events import Event, EventKind, EventLog, Payload
from agora.engine.memory import importancia_de
from agora.engine.ontology import (
    ActionId,
    ActionSpec,
    AflictionSpec,
    AgentId,
    GoalStatus,
    NeedId,
    PlaceId,
    RelationId,
    SituationId,
)
from agora.engine.outcome import (
    company_premium,
    contextual_effects,
    learn,
    signed_saturation,
)
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Busy, PerformingAction, Traveling, WorldState

if TYPE_CHECKING:
    from typing import TextIO


class Simulation:
    """Un mundo corriendo. Estado mutable + su registro de eventos."""

    __slots__ = ("_together", "log", "state")

    def __init__(
        self,
        pack: ContentPack,
        seed: int,
        log_window: int | None = None,
        log_sink: TextIO | None = None,
    ) -> None:
        """`log_window` en ticks: el log conserva solo eso y descarta lo viejo.
        `log_sink`: fichero abierto donde verter cada evento según ocurre.

        Por omisión no hay ni una cosa ni la otra y se guarda todo en memoria,
        que es lo que quiere una corrida corta de calibración. Los dos juntos
        son lo que hace posible una carrera de cinco años sin perder nada: la
        historia entera en el fichero, la memoria acotada a la ventana.
        """
        self.state = WorldState.new(pack, seed)
        self.log = EventLog(log_window, log_sink)
        self._together: set[tuple[AgentId, AgentId]] = set()
        """Quién estaba con quién el tick pasado. Sirve para emitir un
        encuentro cuando se produce y no en cada uno de los ticks que dos
        agentes pasan en la misma sala."""

    @property
    def pack(self) -> ContentPack:
        return self.state.pack

    # -------------------------------------------------------------------------
    # Guardar y reanudar
    # -------------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Vuelca la partida. El LOG NO VA: es historia, no estado.

        Un ano de ciento veintisiete agentes son cientos de megas de eventos. Al
        reanudar, el mundo es el mismo pero nadie recuerda como llego ahi.
        """
        persistence.save(self.state, self._together, path)

    @classmethod
    def resume(
        cls,
        path: Path,
        pack: ContentPack,
        log_window: int | None = None,
        log_sink: TextIO | None = None,
    ) -> Simulation:
        """Reanuda sobre el pack dado, que no tiene por que ser el de antes.

        Reanudar en el tick N da EXACTAMENTE lo mismo que no haber parado, y no
        es suerte: `RngSource` sortea con `blake2b(semilla, agente, tick)`, asi
        que ningun sorteo depende de cuantos hubo antes. Se decidio en F0 y esta
        es la primera vez que se cobra.
        """
        state, together = persistence.load(path, pack)
        sim = cls.__new__(cls)
        sim.state = state
        sim.log = EventLog(log_window, log_sink)
        sim._together = together
        return sim

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
        self._expire_situations()
        self._fire_triggers()
        self._decay_everyone()
        self._cobrar_muertes()
        for agent in self.state.agents_in_order():
            self._settle_goals(agent)
        for agent in self.state.agents_in_order():
            self._resolve(agent)
        self._detect_encounters()

    # -------------------------------------------------------------------------
    # Relaciones
    # -------------------------------------------------------------------------

    def begin_relation(self, one: AgentId, other: AgentId, relation: RelationId) -> None:
        """`one` pasa a ser `relation` de `other`. Cierra el otro lado solo.

        Casarse, adoptar un discípulo, declararse enemigo — y más adelante
        nacer, que no es otra cosa que crear dos relaciones de golpe. Por eso
        existe como API y no solo como declaración en el pack.

        Lo exclusivo se comprueba aquí y revienta: dos parejas simultáneas no es
        una regla moral, es un árbol genealógico que deja de poder leerse, y más
        vale que salte al casarse que al tercer hijo.
        """
        spec = self.pack.relation_by_id.get(relation)
        if spec is None:
            raise KeyError(f"relación desconocida {relation!r}")
        if one == other:
            raise ValueError(f"{one!r} no puede ser {relation!r} de sí mismo")
        for quien in (one, other):
            if quien not in self.state.agents:
                raise KeyError(f"agente desconocido {quien!r}")

        suyas = self.state.agents[one].relations.setdefault(relation, set())
        if other in suyas:
            return
        if spec.exclusive and suyas:
            raise ValueError(
                f"{one!r} ya tiene {relation!r} ({', '.join(sorted(suyas))}) y es "
                f"exclusiva; rómpela antes"
            )
        suyas.add(other)

        # El otro lado. Una simétrica se replica con su nombre; una dirigida
        # crea su inversa. Sin esto quedaría un mundo donde A es hermano de B
        # pero B no lo es de A, que no falla en ninguna parte: solo se comporta
        # raro.
        if spec.symmetric:
            self.state.agents[other].relations.setdefault(relation, set()).add(one)
        elif spec.inverse is not None:
            self.state.agents[other].relations.setdefault(spec.inverse, set()).add(one)

        self.log.emit(
            tick=self.state.tick,
            kind=EventKind.RELATION_BEGAN,
            actor=one,
            subject=other,
            data={"relation": str(relation)},
        )

    def end_relation(self, one: AgentId, other: AgentId, relation: RelationId) -> None:
        """Deja de serlo. Silencioso si no lo era. Rompe también el otro lado."""
        spec = self.pack.relation_by_id.get(relation)
        if spec is None:
            raise KeyError(f"relación desconocida {relation!r}")
        suyas = self.state.agents[one].relations.get(relation)
        if suyas is None or other not in suyas:
            return
        suyas.discard(other)

        del_otro = relation if spec.symmetric else spec.inverse
        if del_otro is not None:
            self.state.agents[other].relations.get(del_otro, set()).discard(one)

        self.log.emit(
            tick=self.state.tick,
            kind=EventKind.RELATION_ENDED,
            actor=one,
            subject=other,
            data={"relation": str(relation)},
        )

    # -------------------------------------------------------------------------
    # Situaciones
    # -------------------------------------------------------------------------

    def begin_situation(
        self, situation: SituationId, ticks: int | None = None, porque: str = "a mano"
    ) -> None:
        """Que le empiece a pasar algo al mundo. `ticks` a `None` = hasta que se
        apague.

        Es la puerta por la que entran la guerra, el derrumbe y la oleada: cosas
        que ocurren PORQUE algo las provoca, no porque toque en el calendario. Lo
        que toca en el calendario se declara periódico en el pack y no pasa por
        aquí.

        Encender una periódica se rechaza en vez de ignorarse: querría decir que
        quien llama cree que es eventual, y ese malentendido no se ve en el log.

        `porque` va al log y es el tercer freno de los disparadores: **el log
        tiene que decir por qué se encendió, no solo que se encendió.** Esa línea
        es lo que separa un mundo vivo de uno aleatorio para quien lo lee después,
        y si no está desde el primer commit no se añade nunca. Por defecto dice
        "a mano", que distingue lo que decidió alguien de lo que decidió el mundo.
        """
        spec = self.pack.situation_by_id.get(situation)
        if spec is None:
            raise KeyError(f"situación desconocida {situation!r}")
        if spec.periodic:
            raise ValueError(
                f"situación {situation!r} es periódica (cada {spec.every} ticks): "
                f"va sola y no se enciende a mano"
            )
        if situation in self.state.situations:
            return
        self.state.situations[situation] = (
            None if ticks is None else self.state.tick + ticks
        )
        self.log.emit(
            tick=self.state.tick,
            kind=EventKind.SITUATION_BEGAN,
            data={
                "situation": str(situation),
                "ticks": -1 if ticks is None else ticks,
                "porque": porque,
            },
        )

    def afligir(
        self,
        quien: AgentId,
        situacion: SituationId,
        marca: str = "",
        ticks: int | None = None,
        porque: str = "a mano",
    ) -> None:
        """Le pasa algo a alguien. Herida, infección, veneno, borrachera.

        Hermana de `begin_situation` sobre el otro alcance, y con los mismos
        frenos: rechaza lo que no es personal en vez de ignorarlo, porque
        aplicarle un invierno a una persona es un malentendido que no se ve en el
        log; y `porque` va al log, que es la regla de que el log diga **por qué**.

        `ticks` a `None` = hasta que alguien la quite. Es lo que separa un veneno
        de una infección.
        """
        spec = self.pack.situation_by_id.get(situacion)
        if spec is None:
            raise KeyError(f"situación desconocida {situacion!r}")
        if not spec.personal:
            raise ValueError(
                f"situación {situacion!r} no es personal: le pasa a un lugar, "
                f"no a alguien. Se enciende con `begin_situation`."
            )
        agente = self.state.agents.get(quien)
        if agente is None:
            raise KeyError(f"no está entre los vivos: {quien!r}")

        # Pasa por la misma puerta que lo demás. La primera versión de este
        # método llamaba a `afligir` por su cuenta y se dejaba el `donde`, así
        # que una herida puesta a mano no sabía dónde te la hicieron y el miedo
        # apuntaba a cualquier parte. Dos caminos para lo mismo divergen: es
        # justo lo que `_infligir` existe para impedir.
        self._infligir(
            agente,
            AflictionSpec(
                situation=situacion,
                marca=marca,
                lasts=0 if ticks is None else ticks,
            ),
            porque=porque,
        )

    def aliviar(
        self, quien: AgentId, situacion: SituationId, marca: str | None = None
    ) -> int:
        """Se le quita. Silencioso si no la llevaba. Devuelve cuántas se fueron."""
        agente = self.state.agents.get(quien)
        if agente is None:
            raise KeyError(f"no está entre los vivos: {quien!r}")
        cuantas = agente.aliviar(situacion, marca=marca)
        if cuantas:
            self.log.emit(
                tick=self.state.tick,
                kind=EventKind.SITUATION_ENDED,
                actor=quien,
                place=agente.at,
                data={"situation": str(situacion), "personal": True,
                      "cuantas": cuantas},
            )
        return cuantas

    def _cobrar_muertes(self) -> None:
        """Se muere quien lleve demasiado a cero en algo que el pack declara
        mortal.

        **Va justo después del decaimiento y antes de que nadie actúe**, y las dos
        mitades importan. Después del decaimiento porque es lo que hunde las
        necesidades, así que el reloj de este tick ya está puesto al día. Antes de
        actuar porque un muerto no cierra metas ni delibera: dejarlo resolver su
        ocupación sería darle un turno de más.

        **Y en bloque, nunca a media pasada.** `agents_in_order` devuelve una
        lista nueva, así que borrar del reparto mientras se recorre dejaría al
        muerto siendo procesado en esa misma vuelta y a los `KeyError` apareciendo
        dos fases más adelante. Aquí no hay iteración abierta que romper.

        Ordenado por id: quien muere primero graba antes su recuerdo en los
        demás, y el olvido por capacidad desempata por `seq`. Sin orden fijo, dos
        procesos con la misma semilla acabarían con biografías distintas.
        """
        specs = self.pack.need_by_id
        condenados = [
            (agent.spec_id, need_id)
            for agent in self.state.agents_in_order()
            for need_id, llevan in sorted(agent.agonia.items())
            if llevan >= specs[need_id].lethal_after > 0
        ]
        for quien, need_id in sorted(condenados):
            # Puede haber muerto ya por otro eje en esta misma vuelta: quien se
            # muere de sed y de hambre a la vez se muere una vez.
            if quien in self.state.agents:
                self.morir(quien, porque=str(need_id))

    def morir(self, quien: AgentId, porque: str = "a mano") -> None:
        """Alguien deja de estar. **La primera pérdida que el motor sabe causar.**

        Se llama `morir` y no `matar` a propósito: la muerte es *una* causa de
        pérdida, no la primitiva. La ruptura y la ausencia entrarán por aquí al
        lado el día que el mundo sepa producirlas — hoy no las produce, y eso se
        midió antes de escribir esto: 120 días de la ciudad, 127 agentes, **cero
        vínculos rotos**. El grafo de conocidos se completa (16 002 de 16 002) y
        `forget_bonds` no dispara ni una vez. La muerte es la única causa con
        combustible, así que es con la que se estrena lo general.

        **Lo que se lleva, y lo que deja.** Sale del reparto pero **se queda en el
        censo**: el mundo sigue sabiendo quién fue, que es lo que permite que los
        demás lo recuerden con nombre. Y se le borra la memoria, porque lo que
        una persona sabía y no dejó dicho no hay forma de consultarlo. Es la regla
        más limpia de todo este frente y la que convierte el conocimiento en algo
        que se puede perder de verdad.

        **A quién le duele.** A cada superviviente por separado, en proporción a
        lo que le apreciaba, y ahí está la propiedad que se buscaba: el peso NO
        sale de la relación con nombre sino del afecto. Alguien que admiraba a un
        desconocido tiene el aprecio sin relación ninguna, y se le cae el mundo
        encima. Sin un solo caso especial: son dos campos distintos y siempre lo
        fueron.

        **El aprecio se lee por `regard_for`, no por `Bond.regard` en crudo**, y
        esto era un fallo hasta que se midió: era el único sitio del motor que
        leía el afecto saltándose la función que lo resuelve. Se perdían las dos
        cosas que esa función aporta, y las dos importan aquí más que en ningún
        otro lado:

        - **el suelo de la relación.** Con `regard_floor`, perder a tu pareja
          dolía lo que hubierais cenado juntos últimamente, ignorando que era tu
          pareja. Y el caso contrario sigue escribiéndose igual de bien: un
          `padre` declarado SIN suelo es exactamente el que nunca reconoció a su
          hijo — tiene la relación y no el aprecio, así que apenas se entera. Lo
          decide el pack, que es donde estaba la decisión.
        - **el desdibujado por no verse.** A quien llevabas medio año sin ver le
          lloras menos que a quien viste ayer, y eso ya lo decía `bond_fade` en
          todas partes menos aquí.

        Quien no tenga aprecio no recibe nada — y ahora *no tener vínculo* y *no
        tener aprecio* dejan de ser lo mismo: tu hermana cuenta aunque llevéis
        años sin cruzar palabra. Una muerte que no le duele a nadie no ocurre
        socialmente.

        **Quien estaba delante se lleva además el lugar.** El recuerdo del testigo
        arrastra dónde pasó, así que le entra por `miedo()` y puede acabar
        rodeando ese sitio; el que se entera sin estar solo carga con la persona.
        Es la única distinción que se puede hacer hoy sin rumores: cómo viaja una
        noticia es el paso siguiente, y hasta que exista, *enterarse* es
        instantáneo para todo el que tuviera vínculo.
        """
        difunto = self.state.agents.get(quien)
        if difunto is None:
            raise KeyError(
                f"no está entre los vivos: {quien!r}. "
                f"{'Ya murió' if self.state.existe(quien) else 'Nunca existió'}."
            )
        donde = difunto.at
        memoria = self.state.memoria
        tuning = self.pack.tuning
        # La del APRECIO, no la general: son dos escalas distintas y meterlas
        # por el mismo divisor dejaba el duelo por debajo de lo más barato que
        # hubiera guardado. Ver `TuningSpec.regard_scale`.
        escala = tuning.escala_del_aprecio
        tick = self.state.tick

        # Orden fijo por id: se graban recuerdos y el olvido por capacidad
        # desempata por `seq`, así que un orden que dependiera del hash haría
        # divergir dos procesos con la misma semilla.
        for otro_id in sorted(self.state.agents):
            if otro_id == quien:
                continue
            deudo = self.state.agents[otro_id]
            aprecio = deudo.regard_for(
                quien, tick, tuning.bond_fade,
                deudo.relation_floor(self.pack, quien),
            )
            if aprecio <= 0.0:
                continue
            testigo = deudo.at == donde
            evento = self.log.emit(
                tick=self.state.tick,
                kind=EventKind.AGENT_DIED,
                actor=otro_id,
                # Solo para quien estaba delante. Colgarle el sitio a quien no
                # estaba le haría rodear un lugar en el que no le pasó nada.
                place=donde if testigo else None,
                subject=quien,
                data={"porque": porque, "testigo": testigo},
            )
            memoria.remember(
                otro_id,
                evento,
                # La importancia sale del aprecio y nada más. `valencia` a -1.0
                # fija porque toda muerte es igual de mala en dirección: lo que
                # cambia entre dos duelos es cuánto te marca, no hacia qué lado.
                importancia=signed_saturation(aprecio, escala),
                valencia=-1.0,
            )

        del self.state.agents[quien]
        # Lo que sabía y no compartió, se va con él.
        memoria.borrar(quien)

    def end_situation(self, situation: SituationId) -> None:
        """Que deje de pasar. Silencioso si no estaba pasando."""
        if situation not in self.state.situations:
            return
        del self.state.situations[situation]
        self.log.emit(
            tick=self.state.tick,
            kind=EventKind.SITUATION_ENDED,
            data={"situation": str(situation)},
        )

    def _expire_situations(self) -> None:
        """Apaga las que se les acabó el plazo.

        Va al principio del tick y antes del decaimiento, por lo mismo que el
        reloj: todo lo que ocurra en este tick tiene que ver el mundo en un solo
        estado. Si expirasen a mitad, los agentes del principio de la lista
        decidirían con la guerra puesta y los del final sin ella.

        Se recorre ordenado, que aquí no es por los floats sino por el log: el
        orden de un `dict` es de inserción, así que dos partidas con la misma
        semilla podrían apagar lo mismo en distinto orden si se hubieran
        encendido en distinto orden.
        """
        vencidas = sorted(
            s for s, hasta in self.state.situations.items()
            if hasta is not None and hasta <= self.state.tick
        )
        for situation in vencidas:
            self.end_situation(situation)

    def _fire_triggers(self, span: int = 1) -> None:
        """Deja que al mundo le pase algo que nadie decidió.

        **La primera pieza del motor que crea sucesos por su cuenta**, y por eso
        va rodeada de frenos: probabilidad declarada por año, cooldown validado
        en el pack, y el log diciendo por qué. Ver `TriggerSpec`.

        Va justo después de expirar y antes del decaimiento, por lo mismo que
        aquello: todo lo que ocurra en este tick tiene que ver el mundo en un
        solo estado. Si una ventisca empezara a mitad de la lista de agentes, los
        primeros decidirían sin ella y los últimos con ella.

        Se recorre en el orden del pack, que es el orden del mundo. Y el sorteo
        sale de una clave por (situación, tick), no de un generador consumido en
        orden: así encender la ventisca no desplaza el sorteo de la oleada, y
        reanudar una partida sigue siendo exacto.

        **`span` es la zancada del salto temporal**, y sin ella el mecanismo
        mentiría en la corrida que más importa. `_zancada` avanza el reloj sin
        pasar por el tick loop, así que con `--skip 14` —lo que usa la carrera de
        cinco años— los disparadores se evaluarían una vez cada catorce días y el
        mundo tendría catorce veces menos imprevistos sin que nada lo dijera.

        Con `span` ticks representados, la probabilidad de que ocurriera al menos
        una vez es `1 - (1-p)**span`. Es la forma exacta y no `p * span`, que se
        desborda por encima de 1 con saltos largos.

        La aproximación que sí queda, y conviene tenerla escrita: **como mucho un
        encendido por zancada**. Dos ventiscas dentro de los mismos trece días
        saltados salen como una. Es del mismo tipo que las que el salto ya hace
        —se aproxima lo monótono, no lo que oscila— y del mismo signo: subestima,
        nunca inventa.
        """
        activas = frozenset(self.state.active_situations())
        tick = self.state.tick
        for spec in self.pack.situations:
            trigger = spec.trigger
            if trigger is None or trigger.expected_per_year <= 0.0:
                continue
            if spec.id in self.state.situations:
                continue  # ya está pasando
            ultimo = self.state.last_trigger.get(spec.id)
            if ultimo is not None and tick - ultimo < trigger.cooldown:
                continue
            if not trigger.requires_situations <= activas:
                continue

            rng = self.state.rng.stream("trigger", spec.id, tick)
            por_tick = trigger.expected_per_year / self.pack.clock.ticks_per_year
            umbral = 1.0 - (1.0 - min(1.0, por_tick)) ** span
            if rng.random() >= umbral:
                continue
            # Dos sorteos del MISMO flujo y en orden fijo: el segundo solo se
            # consume cuando el primero pasa, y como el flujo es función de
            # (semilla, situación, tick), la secuencia es la misma siempre.
            dura = rng.randint(trigger.lasts_min, trigger.lasts_max)
            self.state.last_trigger[spec.id] = tick
            self.begin_situation(
                spec.id,
                dura,
                porque=(
                    ",".join(sorted(str(s) for s in trigger.requires_situations))
                    if trigger.requires_situations
                    else "azar"
                ),
            )

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
        by_situation = self.pack.situation_by_id
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
                    others, tick, tuning.bond_weight, tuning.bond_fade, self.pack
                ),
                company_scale=tuning.company_scale,
            )
            # Lo que el mundo te hace por estar donde estás. Va DESPUÉS del
            # decaimiento y ANTES del chequeo crítico, y ese orden es el que hace
            # útil el mecanismo: así una ventisca puede EMPUJARTE por debajo del
            # umbral, la crisis se emite con el lugar puesto, y el recuerdo que
            # deja es atribuible a dónde estabas. Aplicarlo después dejaría el
            # daño invisible hasta el tick siguiente.
            # `culpables` recuerda qué situación hirió qué eje en ESTE tick, y es
            # lo que hace posible el miedo a lugares. Sin él, una crisis solo
            # sabe dónde ocurrió, no si el sitio tuvo algo que ver — y el hambre
            # cruza su umbral donde uno pase más tiempo, que es su propia cama.
            culpables: dict[NeedId, SituationId] = {}
            # Dónde ocurrió lo que va a hundir este eje. Solo lo llenan las
            # CONDICIONES: una situación de lugar hace daño donde estás, y ahí
            # el sitio ya es el correcto. Una herida no — te la hicieron en otra
            # parte y la notas semanas después.
            donde_paso: dict[NeedId, PlaceId] = {}
            for situation in self.state.situations_at(agent.at):
                spec_sit = by_situation[situation]
                # Quinto canal: lo que el mundo te deja encima. Va antes que el
                # daño porque una condición recién puesta ya cobra este tick —
                # al revés, el primero saldría gratis.
                if spec_sit.inflicts is not None:
                    self._infligir(agent, spec_sit.inflicts, porque=str(situation))
                efectos = spec_sit.effects
                if not efectos:
                    continue
                agent.endure(efectos, specs)
                for need_id, delta in efectos.items():
                    if delta < 0.0:
                        culpables[need_id] = situation

            # Lo que lleva encima, después de lo que le pasa al sitio y con el
            # mismo `endure`: una herida no es una decisión suya, así que se
            # archiva como pasivo igual que una ventisca.
            for vencida in agent.expirar_condiciones(self.state.tick):
                self.log.emit(
                    tick=self.state.tick,
                    kind=EventKind.SITUATION_ENDED,
                    actor=agent.spec_id,
                    data={"situation": str(vencida), "personal": True},
                )
            for cond in agent.condiciones:
                efectos = by_situation[cond.situacion].effects
                if not efectos:
                    continue
                # `veces` multiplica: dos tajos en el mismo brazo no duran más,
                # duelen más.
                agent.endure(
                    {n: v * cond.gravedad for n, v in efectos.items()}, specs
                )
                for need_id, delta in efectos.items():
                    if delta < 0.0:
                        culpables[need_id] = cond.situacion
                        if cond.donde is not None:
                            donde_paso[need_id] = cond.donde

            agent.recover_novelty(self.pack.tuning.saturation_recovery)
            # Después del decaimiento: el desgaste y el temperamento que se
            # derivan de él tienen que reflejar el estado de ESTE tick, no del
            # anterior. El umbral crítico que se comprueba justo debajo sale de
            # aquí.
            agent.refresh_state(self.pack)
            for need_id, value in agent.needs.items():
                # Lo que no puede interrumpir tampoco es una alarma. Sin esta
                # guarda el log grita "crisis" por una bolsa vacia o por ser
                # novato, y el narrador se lo cree aunque el triaje no.
                # El reloj de lo mortal va antes que la alarma y aparte de ella:
                # `can_be_critical` decide qué merece interrumpir una rutina, y
                # morirse no pide permiso a esa guarda. Un pack puede declarar
                # letal algo que no considera motivo para soltar lo que estás
                # haciendo —una hemorragia lenta— y sería absurdo que por eso no
                # matara.
                mortal = specs[need_id].lethal_after
                if mortal > 0:
                    if value <= 0.0:
                        agent.agonia[need_id] = agent.agonia.get(need_id, 0) + 1
                    elif need_id in agent.agonia:
                        # Levantar del cero lo borra entero. Comer no salda el
                        # hambre de tres días a plazos como se salda una deuda:
                        # la quita.
                        del agent.agonia[need_id]

                if not specs[need_id].can_be_critical:
                    continue
                if before[need_id] >= threshold > value:
                    culpable = culpables.get(need_id)
                    datos: dict[str, str | float] = {
                        "need": str(need_id),
                        "value": round(value, 4),
                    }
                    if culpable is not None:
                        datos["porque"] = str(culpable)
                    # No pasa por `_emit`, y esa es toda la corrección: `_emit`
                    # sella el evento con `agent.at`, que para una herida es
                    # dónde te diste cuenta y no dónde te la hicieron.
                    event = self.log.emit(
                        tick=self.state.tick,
                        kind=EventKind.NEED_CRITICAL,
                        actor=agent.spec_id,
                        place=donde_paso.get(need_id, agent.at),
                        data=datos,
                    )
                    # *Lo que duele, se recuerda* — la frase con la que se
                    # declaró este evento en F0, cobrada por fin. Sin sorpresa:
                    # hundirse no desmiente ninguna expectativa, duele y ya.
                    self._grabar(
                        agent,
                        event,
                        urgencia=urgency(value, specs[need_id].urgency_exponent),
                        # Hundirse es malo, sin discusión. No lleva `action`
                        # —nadie decidió pasar hambre—, así que no produce rencor
                        # contra nada: los dos índices parten la memoria y este
                        # cae del lado del miedo.
                        valencia=-1.0,
                        # Y solo cuenta como miedo si el mundo tuvo la culpa. Es
                        # la línea por la que este frente se abandonó una vez:
                        # sin ella, el hambre que cruza su umbral en tu cama te
                        # enseña a temer tu cama.
                        culpable=culpable,
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
        spec = self.state.spec_of(agent)
        for goal in spec.goals:
            if agent.goals.get(goal.id) is not GoalStatus.ACTIVE:
                continue

            # Dos formas de medirlo, y el pack declara exactamente una. El rango
            # es el único número de este motor que solo sube: el valor del eje
            # vuelve a cero cada vez que se rompe uno, así que un umbral sobre él
            # se cumpliría con el primero.
            logrado = (
                agent.rango.get(goal.need, 0) >= goal.at_rank
                if goal.at_rank is not None
                else agent.needs[goal.need] >= (goal.at_least or 0.0)
            )
            if logrado:
                resultado, derivas = GoalStatus.ACHIEVED, goal.on_success
            elif goal.deadline is not None and self.state.tick >= goal.deadline:
                resultado, derivas = GoalStatus.FAILED, goal.on_failure
            else:
                continue

            agent.goals[goal.id] = resultado
            event = self._emit(
                EventKind.GOAL_ACHIEVED
                if resultado is GoalStatus.ACHIEVED
                else EventKind.GOAL_FAILED,
                agent,
                data={"goal": str(goal.id), "need": str(goal.need)},
            )
            # Una meta que se cierra marca por lo que EXIGÍA, no por cómo anda
            # ahora ese eje. Medir el eje sería medir lo contrario de lo que se
            # quiere: cumplir una meta lo deja lleno, urgencia cero, y el logro
            # de una vida se grabaría con la misma fuerza que una siesta.
            #
            # `urgency` mide la presión de un déficit, así que se le pasa el
            # déficit que la meta consideraba inaceptable — `1 - at_least`. Una
            # meta que pedía llenar el eje al 90 % pesa mucho; una que se
            # conformaba con el 20 %, poco. La curva es la misma del pack, así
            # que un mundo de necesidades tiránicas también tiene metas tiránicas.
            # Y para una meta de rango, lo que la meta exigía sale de la curva de
            # saturación de siempre sobre el rango pedido: `n/(n+1)`, que marca
            # 0.50 en el rango 1, 0.91 en el 10 y 0.97 en el 30 — crece y nunca
            # se sale de escala, que es lo que hace falta en un eje sin techo. Es
            # la misma curva que el resto del motor, no una nueva.
            #
            # OJO al signo: `urgency` recibe **lo lleno que está el eje**, no el
            # déficit, y por eso la rama de `at_least` pasa `1 - umbral`. Aquí
            # hace falta el mismo giro, o una meta más ambiciosa se grabaría como
            # menos importante — que es exactamente lo que pasó al escribirlo.
            exigia = (
                1.0 - signed_saturation(float(goal.at_rank), 1.0)
                if goal.at_rank is not None
                else 1.0 - (goal.at_least or 0.0)
            )
            self._grabar(
                agent,
                event,
                urgencia=urgency(
                    exigia, self.pack.need_by_id[goal.need].urgency_exponent
                ),
                # La única valencia sin ambigüedad del motor. Una meta que vence
                # sin cumplirse no necesita interpretarse: salió mal, y punto.
                #
                # No lleva `action`, así que no entra en el índice de rencor: una
                # meta fallada no es culpa de ninguna acción concreta, y repartir
                # la culpa entre las que se hicieron mientras tanto sería inventar
                # una atribución que nadie puede sostener. Queda como biografía —
                # y como material del narrador de F5.
                valencia=1.0 if resultado is GoalStatus.ACHIEVED else -1.0,
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
                self._finish_action(agent, busy.action, busy.total_ticks, busy.target)
            case Traveling():
                self._arrive(agent, busy)
            case _:
                assert_never(busy)

    def _finish_action(
        self,
        agent: AgentState,
        action_id: ActionId,
        done: int,
        target: AgentId | None = None,
    ) -> None:
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
        company = agent.effective_company(
            others, tick, tuning.bond_weight, tuning.bond_fade, self.pack
        )
        received = contextual_effects(spec, company, tuning.company_scale)

        before = dict(agent.needs)
        # Lo que el sitio y lo que le pase al mundo hacen rendir. Se resuelve una
        # vez y sirve para las dos vías, la normal y la elástica.
        world_gains = self.state.gains_at(agent.at)
        if agent.ledger is not None:
            self._anotar_lo_incondicional(agent, spec)
        for eje in agent.apply(received, self.pack.need_by_id, world_gains):
            self._emit(
                EventKind.RANK_UP,
                agent,
                action=action_id,
                data={"need": str(eje), "rango": agent.rango[eje]},
            )

        if spec.elastic is not None and done > 0:
            rate = recovery_rate(spec, agent, world_gains)
            agent.gain(spec.elastic.need, rate * done)

        # La sorpresa se cobra aquí y la usa la memoria más abajo. Antes se
        # calculaba dentro de `learn` y se tiraba.
        sorpresa = learn(
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
                    tuning.company_scale,
                ),
                tuning.bond_rate,
                tick,
            )
            self._contar(agent, others, tick)
        agent.saturate(action_id, spec.saturation_gain)

        data: Payload = {"company": round(company, 4)} if spec.effects_per_company else {}
        event = self._emit(EventKind.ACTION_COMPLETED, agent, action=action_id, data=data)
        # Lo que apretaba al empezar, no lo que queda después de saciarlo: es la
        # misma regla que gobierna `learn` y `company_premium`, y por lo mismo —
        # lo que valió el rato lo decide la necesidad que traías.
        apretaba = max(
            (
                urgency(before[need], self.pack.need_by_id[need].urgency_exponent)
                for need in spec.satisfies
            ),
            default=0.0,
        )
        # `testigos` explícito y no recontado: aquí ya se sabe quién estaba, y
        # volver a preguntarlo daría otro número — entre aplicar los efectos y
        # esta línea nadie se ha movido, pero depender de eso sería frágil.
        # La sorpresa lleva el signo normalizado por `learn` —positivo es mejor
        # de lo esperado—, y un mismo número decide las dos mitades del recuerdo:
        # cuánto marcó (su magnitud) y hacia qué lado (su signo).
        #
        # Pero la valencia se SATURA antes de guardarse, y eso salió de medir.
        # El error crudo no está acotado: es un ratio contra la creencia, y en la
        # ciudad llega a 5.06 cuando algo social se hace a solas y rinde una
        # fracción de lo prometido. Con el recorte a [-1, 1] de `remember`, más de
        # la mitad de los arrepentimientos por acción quedaban pegados al tope
        # —la mediana en crudo es 1.09—, así que el signo funcionaba y la
        # magnitud estaba muerta: la misma clase de avería que un eje con oferta
        # 1.3. Saturados, esos mismos van de 0.003 a 0.835 con mediana 0.521.
        #
        # La escala es 1.0 y no una perilla nueva porque el error ya viene en
        # unidades naturales: 1.0 es "no dio nada de lo que yo esperaba".
        self._grabar(
            agent,
            event,
            urgencia=apretaba,
            sorpresa=sorpresa,
            testigos=len(others),
            valencia=signed_saturation(sorpresa),
        )
        if spec.target is not None and target is not None:
            self._entregar(agent, spec, target, event)
        # Lo que hacer esto te hace a TI, y al terminar: media faena no cuenta.
        # Un `costs` se paga una vez; esto sigue sangrando hasta que alguien lo
        # cure, que es lo que separa una consecuencia de un precio.
        if spec.inflicts is not None:
            self._infligir(agent, spec.inflicts, porque=str(spec.id))
        # La mitad *por acción* de cómo se sale de una condición. Al terminar,
        # no al empezar: vendarse a medias no cura.
        for curada, cuanto in sorted(spec.cures.items()):
            if agent.aliviar(curada, cuanto):
                self.log.emit(
                    tick=self.state.tick,
                    kind=EventKind.SITUATION_ENDED,
                    actor=agent.spec_id,
                    place=agent.at,
                    action=spec.id,
                    data={"situation": str(curada), "personal": True},
                )
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
        presentes = [other.spec_id for other in self.state.others_at(agent)]
        company = len(presentes)
        # La franja y la situación son las de AHORA, no las de cuando se decidió:
        # un viaje largo puede acabar con el sitio ya cerrado o con la mina ya
        # derrumbada, y eso es un chasco legítimo que se lee igual que llegar y
        # no encontrar a nadie.
        phase = self.pack.clock.phase_at(self.state.tick)
        if is_available(
            action,
            self.pack.place_by_id[agent.at],
            company,
            agent.needs,
            phase,
            agent.traits,
            self.state.situations_at(agent.at),
            agent.kin_present(presentes),
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
                rate = recovery_rate(spec, agent, self.state.gains_at(agent.at))
                agent.gain(spec.elastic.need, rate * hechos)
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
            self._start_action(agent, choice.action, choice.utility, choice.target)
        else:
            self._start_travel(agent, choice)

    def _start_action(
        self,
        agent: AgentState,
        action: ActionId,
        utility: float | None,
        target: AgentId | None = None,
    ) -> None:
        spec = self.pack.action_by_id[action]
        # La duración se fija AQUÍ y se guarda: con lo elástico sale del déficit
        # de este agente en este sitio, y el pack ya no la sabe. Recalcularla por
        # tick alargaría el sueño cada vez que el agente se repone un poco.
        ticks = planned_duration(spec, agent, self.state.gains_at(agent.at))
        agent.busy = PerformingAction(
            action=action, ticks_remaining=ticks, total_ticks=ticks, target=target
        )
        data: Payload = {} if utility is None else {"utility": round(utility, 4)}
        if target is not None:
            data = {**data, "target": str(target)}
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

    def _anotar_lo_incondicional(self, agent: AgentState, spec: ActionSpec) -> None:
        """Cuánto de lo que se acaba de ganar llegaba igual estando solo.

        Un eje **social** es el que declara `company_relief`: el propio pack dice
        que la compañía lo alivia. Si una acción lo satisface con efectos BASE y
        no exige ni compañía ni relación, ese eje se cubre sin nadie delante, y
        entonces todo lo que el pack escribió alrededor —las acciones sociales,
        los rasgos que las pesan— es decorado.

        Solo se cuenta la parte base. `effects_per_company` ya vale cero a
        solas, que es exactamente la forma correcta de escribir "esto necesita
        gente", y por eso no entra aquí.
        """
        libro = agent.ledger
        if libro is None:  # pragma: no cover - quien llama ya lo comprobó
            return
        if spec.requires_company > 0 or spec.requires_relation is not None:
            return  # está gateado: lo que da, lo da por cumplir la condición
        for need_id, delta in spec.effects.items():
            if delta > 0.0 and self.pack.need_by_id[need_id].company_relief > 0.0:
                libro.anotar(libro.incondicional, need_id, delta)

    def _emit(
        self,
        kind: EventKind,
        agent: AgentState,
        *,
        action: ActionId | None = None,
        data: Payload | None = None,
    ) -> Event:
        """Atajo: casi todos los eventos son "este agente, aquí, ahora".

        Devuelve el evento ya sellado porque la memoria episódica necesita el
        hecho entero, no su id: el recuerdo se lleva una copia de lo saliente
        para sobrevivir a la ventana del log y a un `save`/`load`.
        """
        return self.log.emit(
            tick=self.state.tick,
            kind=kind,
            actor=agent.spec_id,
            place=agent.at,
            action=action,
            data=data,
        )

    # -------------------------------------------------------------------------
    # Memoria episódica
    # -------------------------------------------------------------------------

    def _gravedad_de(self, aflige: AflictionSpec, quien: AgentState) -> float:
        """Cuán grave sale ESTA. Sorteada en el rango que el pack declara.

        Con mínimo y máximo iguales sale fija, que es el caso simple. Con rango,
        el mismo brote reparte fiebres de 0.4 y fiebres de 2.5 — la misma
        enfermedad vivida de dos maneras.
        """
        if aflige.gravedad_max <= aflige.gravedad_min:
            return aflige.gravedad_min
        rng = self.state.rng.stream(
            "gravedad", quien.spec_id, aflige.situation, self.state.tick
        )
        return rng.uniform(aflige.gravedad_min, aflige.gravedad_max)

    def _infligir(
        self, quien: AgentState, aflige: AflictionSpec, porque: str
    ) -> bool:
        """Le pega una condición. `True` si prendió.

        **Puerta única para los tres sitios que infligen** —una acción sobre
        quien la hace, una situación sobre quien alcanza, y una acción dirigida
        sobre el otro—. Repartido, el sorteo acabaría con tres claves distintas y
        dos de ellas mal, que es como se rompe el determinismo sin que nadie se
        entere.

        La clave del sorteo lleva a quién, cuándo y de qué viene: dos procesos
        con la misma semilla hieren exactamente a la misma gente, y el orden en
        que se resuelvan no altera ninguno.
        """
        if aflige.chance < 1.0:
            rng = self.state.rng.stream(
                "aflige", quien.spec_id, aflige.situation, self.state.tick
            )
            if rng.random() >= aflige.chance:
                return False
        cond = quien.afligir(
            aflige.situation,
            aflige.marca,
            None if aflige.lasts <= 0 else self.state.tick + aflige.lasts,
            # Dónde te la hicieron, no dónde la notarás. Es la línea entera de
            # la que depende que el miedo apunte a la mazmorra y no a la cama.
            donde=quien.at,
            # Y cuán grave. Se sortea en el rango que el pack declara, así que un
            # mismo brote reparte fiebres leves y fiebres que matan.
            gravedad=self._gravedad_de(aflige, quien),
        )
        self.log.emit(
            tick=self.state.tick,
            kind=EventKind.SITUATION_BEGAN,
            actor=quien.spec_id,
            place=quien.at,
            data={
                "situation": str(aflige.situation),
                "personal": True,
                "marca": aflige.marca,
                "gravedad": round(cond.gravedad, 3),
                "porque": porque,
            },
        )
        return True

    def _entregar(
        self,
        agent: AgentState,
        spec: ActionSpec,
        a_quien: AgentId,
        event: Event,
    ) -> None:
        """Lo que le llega al otro. **El primer efecto del motor que no cae sobre
        quien actúa.**

        Se comprueba que siga delante y no que siga existiendo: vendar a quien se
        marchó a mitad no cura a nadie, y curarlo desde otro lugar sería
        teletransportar el vendaje. Es la misma verdad-en-la-mano que el chasco de
        llegada, en el otro extremo de la acción.

        El daño se archiva con `endure` y la ayuda con `apply`, y la distinción no
        es cosmética: lo que te hacen no lo decidiste tú, así que no puede
        ensuciar tus creencias sobre lo que rinde cada acción. Es la misma razón
        por la que una ventisca entra como pasivo.

        Y **aquí es donde el motor empieza a producir hechos sociales**. El evento
        lleva `subject`, así que el recuerdo del otro sale con `about` puesto — el
        campo que la medición encontró al 0 % en los dos mundos grandes, y sin el
        cual `duelo()` no tenía de qué alimentarse y los rumores solo podían
        llevar expectativas.
        """
        otro = self.state.agents.get(a_quien)
        if otro is None or otro.at != agent.at:
            return
        destino = spec.target
        assert destino is not None

        recibe = {n: v for n, v in destino.gives.items() if v > 0.0}
        sufre = {n: v for n, v in destino.gives.items() if v < 0.0}
        if recibe:
            otro.apply(recibe, self.pack.need_by_id)
        if sufre:
            otro.endure(sufre, self.pack.need_by_id)
        for curada, cuanto in sorted(destino.cures.items()):
            otro.aliviar(curada, cuanto)
        if destino.inflicts is not None:
            self._infligir(otro, destino.inflicts, porque=str(spec.id))

        # El otro lo recuerda, y lo recuerda CON NOMBRE: `about` sale del
        # `subject` del evento, que es quien actuó.
        suyo = self.log.emit(
            tick=self.state.tick,
            kind=EventKind.ACTION_COMPLETED,
            actor=a_quien,
            place=otro.at,
            action=spec.id,
            subject=agent.spec_id,
            data={"recibido": True},
        )
        self._grabar(
            otro,
            suyo,
            urgencia=max(
                (urgency(otro.needs[n], self.pack.need_by_id[n].urgency_exponent)
                 for n in destino.gives),
                default=0.0,
            ),
            # Que te hagan algo sorprende por definición: no lo habías decidido
            # tú. El signo lo pone qué te hicieron.
            sorpresa=1.0,
            valencia=1.0 if recibe and not sufre else -1.0,
        )
        _ = event

    def _contar(
        self, narrador: AgentState, oyentes: list[AgentId], tick: int
    ) -> None:
        """Alguien cuenta algo. **Un rumor es un recuerdo que se copia.**

        La frase estaba en el plan desde el principio y resultó ser literal: no
        hace falta primitiva nueva, solo mover un `Recuerdo` de una cabeza a otra
        rebajado. Lo que costó decidir no fue el mecanismo sino **qué se cuenta**,
        y eso lo contestó medir — ver `MemoriaEpisodica.contable`.

        **Quién pone el peso.** Aquí está la petición de que la noticia se reciba
        *en base a la imagen que uno tenía de ese individuo*, y es la única regla
        de este método que no es aritmética:

        - si la historia va **sobre alguien**, manda el aprecio de QUIEN ESCUCHA.
          Que a quien te lo cuenta se le caiga el mundo encima no te obliga a ti
          a sentir nada, y al revés tampoco: te enteras de que murió tu ídolo por
          boca de alguien a quien le daba igual, y te destroza igual.
        - si no va sobre nadie —una expectativa, un sitio que decepcionó— manda lo
          que traía, rebajado por la cadena.

        Sin `about`, quien escucha no tiene con qué juzgarlo y hereda el peso del
        que habla; con `about`, tiene lo suyo y no necesita el de nadie.

        El sorteo va por clave —`blake2b(semilla, ...)`— con narrador y oyente
        dentro, así que el orden en que se cuentan las cosas no altera ninguna.
        """
        tuning = self.pack.tuning
        memoria = self.state.memoria
        if tuning.rumor_rate <= 0.0 or memoria.capacidad <= 0 or not oyentes:
            return
        historia = memoria.contable(narrador.spec_id, tick)
        if historia is None:
            return

        # Ordenados: se graban recuerdos y el olvido por capacidad desempata por
        # `seq`, así que un orden que dependiera del hash haría divergir dos
        # procesos con la misma semilla.
        for quien in sorted(oyentes):
            oyente = self.state.agents.get(quien)
            if oyente is None or memoria.sabe(quien, historia.seq):
                continue
            rng = self.state.rng.stream("rumor", narrador.spec_id, quien, tick)
            if rng.random() >= tuning.rumor_rate:
                continue

            if historia.about is not None:
                # Mismo `regard_for` que en `morir`, y por lo mismo: leer el
                # aprecio en crudo se saltaba el suelo de la relación y el
                # desdibujado. Enterarte de algo de tu pareja no puede pesar lo
                # que pesaría de un conocido cualquiera de igual trato.
                aprecio = oyente.regard_for(
                    historia.about, tick, tuning.bond_fade,
                    oyente.relation_floor(self.pack, historia.about),
                )
                if aprecio <= 0.0:
                    # No le suena de nada. Se entera y no le mueve un pelo: no
                    # se guarda, porque un recuerdo de importancia cero no es un
                    # recuerdo, es ocupar sitio.
                    continue
                importancia = signed_saturation(aprecio, tuning.escala_del_aprecio)
            else:
                importancia = historia.importancia * tuning.rumor_decay
            memoria.oir(quien, historia, importancia)

    def _grabar(
        self,
        agent: AgentState,
        event: Event,
        *,
        urgencia: float,
        sorpresa: float = 0.0,
        testigos: int | None = None,
        valencia: float = 0.0,
        culpable: SituationId | None = None,
    ) -> None:
        """Pasa un hecho por la regla de importancia y, si marca, lo graba.

        Existe como un solo sitio y no repartido por los tres emisores porque la
        regla es una: si cada punto de grabación compusiera su propia
        importancia, calibrar `memory_scale` dejaría de significar nada.

        `testigos` a `None` se cuenta aquí — casi siempre es "los que están
        delante", y el único caso que no lo es (el fin de una acción, donde ya se
        computó la compañía) lo pasa explícito.
        """
        memoria = self.state.memoria
        if memoria.capacidad <= 0:
            return
        if testigos is None:
            testigos = len(self.state.others_at(agent))
        tuning = self.pack.tuning
        memoria.remember(
            agent.spec_id,
            event,
            importancia_de(
                urgencia,
                sorpresa,
                testigos,
                peso_urgencia=tuning.memory_urgency_weight,
                peso_sorpresa=tuning.memory_surprise_weight,
                peso_testigos=tuning.memory_witness_weight,
                escala=tuning.memory_scale,
            ),
            valencia,
            culpable,
        )
