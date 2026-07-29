"""Estado mutable de una partida.

`ontology.py` define cómo ES el mundo (inmutable, viene del pack).
Este archivo define cómo ESTÁ el mundo ahora mismo (mutable, cambia por tick).

Regla que explica casi todas las decisiones de aquí: **pydantic en las
fronteras, dataclass en el interior**. Pydantic valida en cada construcción, y
esto se toca 672 veces por semana simulada por cada agente. Es el mismo
criterio que en C# separa un DTO validado en el borde de un struct interno que
ya nadie vuelve a comprobar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from agora.engine.disposition import (
    Temperament,
    compose_need_weights,
    compose_tastes,
    compose_temperament,
    compute_strain,
)
from agora.engine.ontology import (
    ActionId,
    AgentId,
    AgentSpec,
    NeedId,
    NeedSpec,
    PlaceId,
    PlaceSpec,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.rng import RngSource
from agora.engine.topology import TravelMap

# -----------------------------------------------------------------------------
# Qué está haciendo un agente: unión, no un flag.
#
# Estos dos SÍ son pydantic y SÍ son frozen. Son pequeños, se crean pocas veces
# (una por decisión, no una por tick) y ser inmutables elimina de raíz los bugs
# de aliasing: dos referencias al mismo objeto `Busy` decrementándolo dos veces.
# En un motor determinista ese bug es de los más caros de encontrar, porque no
# rompe nada — solo hace que el tiempo pase distinto para un agente.
# -----------------------------------------------------------------------------


class PerformingAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: ActionId
    ticks_remaining: int = Field(ge=0)


class Traveling(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: PlaceId
    """A dónde quiere llegar al final."""

    intent: ActionId
    """Qué piensa hacer al llegar.

    Consecuencia directa de deliberar sobre el mundo entero: si el agente
    elige "comer en la posada", el viaje no es la decisión, es la consecuencia
    de una decisión que hay que recordar.

    Sin este campo, un agente con hambre crítica que ya va camino de la comida
    abortaría el viaje en cada tick — porque "viajar" no satisface nada y la
    comprobación de urgencia no tendría forma de saber que ya está resolviendo
    el problema.
    """

    next_hop: PlaceId
    """El tramo actual. Un viaje largo son varios `Traveling` encadenados.

    Guardar el tramo y no la ruta entera es deliberado: al llegar a cada nodo se
    vuelve a preguntar `TravelMap.first_hop`, así que un cambio en el mundo (un
    camino cortado, un lugar cerrado de noche) se absorbe solo sin invalidar
    viajes en curso.
    """

    ticks_remaining: int = Field(ge=0)

    total_ticks: int = Field(default=0, ge=0)
    """Duración estimada del trayecto ENTERO al decidirlo, no del tramo.

    Se conserva de tramo en tramo para poder saber cuánto se lleva andado. Sin
    esto, el progreso solo se sabría dentro del tramo actual, y como los tramos
    son de uno o dos ticks, un agente que lleva cuatro ticks caminando parecería
    recién salido de casa cada vez que pisa un cruce.
    """


type Busy = PerformingAction | Traveling
"""Unión discriminada. Consúmela siempre con `match` + `assert_never`:

    match busy:
        case PerformingAction(): ...
        case Traveling():        ...
        case _:                  assert_never(busy)

Cuando en F1 añadas un tercer caso (huir, por ejemplo), mypy señalará cada sitio
que falta actualizar. En C# eso lo confiarías a un `default:` que revienta en
runtime; aquí falla antes de ejecutar.
"""


# -----------------------------------------------------------------------------
# Estado de un agente
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class AgentState:
    """Dónde está, cómo está y qué está haciendo un agente.

    `slots=True` se acerca a un `struct` de C#: sin `__dict__`, menos memoria y
    acceso a atributos más rápido. A cambio no puedes añadir atributos al vuelo,
    que es justo lo que quieres en el estado caliente.
    """

    spec_id: AgentId
    """Solo el id, no el `AgentSpec` entero.

    Mantiene el estado serializable. En F4 vas a querer partidas guardadas, y un
    estado que arrastra specs se convierte en un problema de identidad al
    recargar: dos copias del mismo spec que ya no son el mismo objeto.
    """

    at: PlaceId
    needs: dict[NeedId, float]

    # --- disposición: quién es este agente AHORA -----------------------------
    #
    # Vive aquí y no en el spec porque tiene que poder cambiar. Un NPC que no
    # es distinto después de un año de vivir no tiene arco, tiene una ficha.
    # El spec pasa a ser las condiciones iniciales.

    traits: dict[TraitId, float] = field(default_factory=dict)
    """Rasgo -> intensidad actual en [-1, 1]. Se mueve con `drift_trait`."""

    tastes: dict[str, float] = field(default_factory=dict)
    """Objetivo -> multiplicador. Ya compuesto: dos gustos hacia lo mismo se
    multiplicaron al construirlo. Se puede mutar directamente, no tiene nada
    derivado que mantener en sincronía."""

    need_weights: dict[NeedId, float] = field(default_factory=dict)
    """DERIVADO de `traits`. Se recompone en `drift_trait`, que es la única
    puerta para moverlos precisamente por eso.

    Está aquí y no se recalcula en cada deliberación porque los rasgos cambian
    muy rara vez y se consultan miles de veces."""

    strain: float = 0.0
    """Desgaste cognitivo en [0, 1]. DERIVADO de las necesidades, se recalcula
    cada tick. 0 entero, 1 al límite.

    No es una emoción: es lo que hace que el mismo agente decida peor cuando
    está mal. Se guarda además de usarse porque en F2 va a ser una de las
    primeras cosas que el narrador necesite saber."""

    temperament: Temperament = field(default_factory=lambda: Temperament(0.15, 1.0, 0.15, 0.95))
    """DERIVADO de `traits`, del `tuning` del pack y del `strain` actual. Cómo
    decide esta persona hoy: su impulsividad, su aversión al precio, su aguante
    y su arraigo.

    Como depende del estado, se recompone **cada tick** y no solo al derivar un
    rasgo. Cuesta una decena de potencias por agente; a cambio hay una sola
    fuente de verdad y nunca queda desfasado.

    El default solo existe para que construir un `AgentState` suelto en un test
    no reviente; cualquier agente de una partida real pasa por `from_spec`."""

    saturation: dict[ActionId, float] = field(default_factory=dict)
    """Hastío por acción, en [0, 1]. Sube al COMPLETAR, se disipa cada tick.

    Al completar y no al empezar: uno se cansa de lo que hizo, no de lo que
    intentó. Un agente que empieza y abandona no debería aburrirse de algo que
    nunca llegó a hacer.

    Las acciones sin `saturation_gain` nunca entran en este diccionario, así
    que no ocupan nada.
    """

    busy: Busy | None = None
    """`None` = ocioso. Este agente delibera en el tick actual."""

    @classmethod
    def from_spec(cls, pack: ContentPack, spec: AgentSpec) -> AgentState:
        """Estado inicial de un agente a partir de sus condiciones de partida.

        Los diccionarios se **copian**. `AgentSpec` es `frozen`, pero eso solo
        impide reasignar sus atributos: el dict de dentro sigue siendo mutable,
        y compartirlo haría que la deriva de un agente contaminara el pack —y
        con él, a cualquier otro mundo cargado desde el mismo fichero.
        """
        # Todas las necesidades del pack, aunque el agente no las mencione. Un
        # dict incompleto obliga a cada consumidor a inventarse un default, y
        # acabarían siendo distintos en dos sitios.
        needs: dict[NeedId, float] = {need.id: need.initial for need in pack.needs}
        needs.update(spec.initial_needs)

        strain = compute_strain(pack, needs)
        return cls(
            spec_id=spec.id,
            at=spec.start_at,
            needs=needs,
            traits=dict(spec.traits),
            tastes=compose_tastes(spec.tastes),
            need_weights=compose_need_weights(pack, spec.traits),
            strain=strain,
            temperament=compose_temperament(pack, spec.traits, strain),
            busy=None,  # todos deliberan en el tick 0
        )

    def refresh_state(self, pack: ContentPack) -> None:
        """Recalcula el desgaste y con él el temperamento.

        Se llama una vez por tick, después del decaimiento. Todo lo derivado del
        estado se recompone en un solo sitio, así que no puede quedar desfasado
        respecto a las necesidades que lo generan.
        """
        self.strain = compute_strain(pack, self.needs)
        self.temperament = compose_temperament(pack, self.traits, self.strain)

    def drift_trait(self, pack: ContentPack, trait: TraitId, delta: float) -> None:
        """Mueve un rasgo y recompone lo que depende de él.

        Única puerta para cambiar la personalidad, y existe por el invariante:
        `need_weights` es derivado de `traits`, así que tocarlos por separado
        dejaría a un agente decidiendo con los pesos de quien era antes. Ese bug
        no rompe nada visible — solo hace que la deriva no surta efecto.

        El rasgo tiene que existir en el pack, pero NO hace falta que el agente
        lo tuviera declarado: nadie nace con todos los rasgos, y la experiencia
        puede despertar uno que estaba a cero. Lo que no puede es inventarse uno
        —eso sería una errata pasando por capacidad emergente— y por eso falla
        ruidosamente aquí en vez de reventar dentro de la composición.

        Todavía no lo llama nadie. Es la puerta que este paso existe para abrir:
        cicatrices, aprendizaje y rampancia entran por aquí.
        """
        if trait not in pack.trait_by_id:
            raise KeyError(
                f"el rasgo {trait!r} no existe en el pack {pack.id!r}; "
                f"declarados: {sorted(pack.trait_by_id)}"
            )
        self.traits[trait] = max(-1.0, min(1.0, self.traits.get(trait, 0.0) + delta))
        self.need_weights = compose_need_weights(pack, self.traits)
        self.temperament = compose_temperament(pack, self.traits, self.strain)

    # -- necesidades ----------------------------------------------------------

    def decay(self, need_specs: Mapping[NeedId, NeedSpec], company: int = 0) -> None:
        """Baja cada necesidad según su propia tasa. Resultado en [0, 1].

        `company` son los otros agentes presentes. Las necesidades que declaren
        `company_relief` decaen más despacio estando acompañado, con saturación
        `n/(n+1)`: uno da la mitad del alivio, tres tres cuartos, una multitud
        nunca más que el tope.

        Indexa directo en vez de usar `.get(..., default)`: si una necesidad del
        pack no está en el dict del agente, eso es un bug de construcción y
        quiero que reviente aquí, ruidosamente, y no que se propague un default
        inventado. El invariante lo garantiza `WorldState.new`.
        """
        crowd = max(0, company)
        saturation = crowd / (crowd + 1) if crowd else 0.0

        for need_id, spec in need_specs.items():
            drop = spec.decay_per_tick - spec.company_relief * saturation
            self.needs[need_id] = self._clamp(self.needs[need_id] - drop)

    def apply(self, effects: Mapping[NeedId, float]) -> None:
        """Suma los deltas de una acción completada. Resultado en [0, 1].

        Los deltas pueden ser negativos: trabajar da moneda y quita descanso.
        Una necesidad que la acción no menciona no se toca.
        """
        for need_id, delta in effects.items():
            self.needs[need_id] = self._clamp(self.needs[need_id] + delta)

    # -- hastío ---------------------------------------------------------------

    def saturate(self, action: ActionId, gain: float) -> None:
        """Registra que acaba de hacer esto. `gain` 0 no deja rastro."""
        if gain <= 0.0:
            return
        self.saturation[action] = self._clamp(self.saturation.get(action, 0.0) + gain)

    def recover_novelty(self, rate: float) -> None:
        """Disipa el hastío. Lo que llega a cero se olvida.

        Borrar las entradas agotadas mantiene el diccionario del tamaño de lo
        que el agente hace últimamente, no de todo lo que ha hecho nunca.
        """
        if rate <= 0.0:
            return
        for action in list(self.saturation):
            resto = self.saturation[action] - rate
            if resto <= 0.0:
                del self.saturation[action]
            else:
                self.saturation[action] = resto

    @staticmethod
    def _clamp(value: float) -> float:
        """El ÚNICO sitio donde se fuerza el rango [0, 1].

        Si el clamp se dispersa, un día una necesidad vale 1.4 y pasas dos horas
        buscando quién la dejó así. Una sola puerta.
        """
        return max(0.0, min(1.0, value))

    # -- ocupación ------------------------------------------------------------

    def advance(self) -> None:
        """Consume un tick de lo que esté haciendo.

        Se detiene en 0 sin limpiar `busy`: quien llama necesita ver QUÉ acabó,
        para aplicar sus efectos o registrar la llegada. Poner `None` aquí
        destruiría esa información.

        `Busy` es inmutable, así que no se decrementa: se reemplaza. Nota sobre
        `model_copy`: **no revalida**. El `ge=0` del campo no se comprueba en la
        copia, y por eso la guarda de arriba (`ticks_remaining == 0`) es
        obligatoria y no defensiva.
        """
        busy = self.busy
        if busy is None or busy.ticks_remaining == 0:
            return
        self.busy = busy.model_copy(update={"ticks_remaining": busy.ticks_remaining - 1})

    @property
    def is_idle(self) -> bool:
        """Dos formas de estar ocioso: nunca empezó, o ya terminó."""
        return self.busy is None or self.busy.ticks_remaining == 0


# -----------------------------------------------------------------------------
# Estado del mundo
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class WorldState:
    pack: ContentPack
    travel: TravelMap
    """Construido UNA vez en `new`. No lo recalcules por tick."""

    tick: int = 0

    agents: dict[AgentId, AgentState] = field(default_factory=dict)
    """`dict` y no `list` ni `set`. Hacen falta dos cosas a la vez: búsqueda
    O(1) por id, y orden estable. `dict` da ambas desde 3.7. Un `set` rompe el
    determinismo en silencio y sin aviso."""

    rng: RngSource = field(default_factory=lambda: RngSource(0))
    """La fuente de aleatoriedad vive AQUÍ y se pasa explícitamente a quien la
    necesite. Nunca `import random; random.choice(...)` a nivel de módulo: eso
    usa un generador global compartido y ahí muere la reproducibilidad.

    No es un generador, sino una fábrica de generadores por clave. Cada sorteo
    pide el suyo con `rng.stream(...)`, y así el resultado no depende de cuántos
    sorteos hubo antes."""

    @property
    def seed(self) -> int:
        """Se escribe en la primera línea del log. Un bug se reproduce corriendo
        el mismo seed; sin esto, un fallo raro en el día 5 no se investiga."""
        return self.rng.seed

    @classmethod
    def new(cls, pack: ContentPack, seed: int) -> WorldState:
        """Construye el estado inicial desde un pack ya validado."""
        # El orden del pack fija el orden del mundo.
        agents = {spec.id: AgentState.from_spec(pack, spec) for spec in pack.agents}

        return cls(
            pack=pack,
            travel=TravelMap(pack.places),
            tick=0,
            agents=agents,
            rng=RngSource(seed),
        )

    def agents_in_order(self) -> list[AgentState]:
        """Los agentes en orden fijo y reproducible.

        Existe como método propio para que el orden se decida en UN sitio. El
        día que quieras aleatorizarlo por tick (para que el mismo agente no gane
        siempre los empates), se cambia aquí y en ningún otro lado.
        """
        return list(self.agents.values())

    # -- atajos que el tick loop y la deliberación usarán constantemente ------

    def spec_of(self, agent: AgentState) -> AgentSpec:
        """Personalidad y gustos del agente. Vive en el pack, no en el estado."""
        return self.pack.agent_by_id[agent.spec_id]

    def place_of(self, agent: AgentState) -> PlaceSpec:
        """Dónde está, con sus affordances. Decide qué acciones son válidas."""
        return self.pack.place_by_id[agent.at]

    def occupancy(self) -> dict[PlaceId, int]:
        """Cuántos agentes hay en cada lugar. Una pasada, no una por consulta.

        La deliberación pregunta por los 21 lugares del mundo en cada decisión;
        contar por separado cada vez sería cuadrático en el número de agentes.
        """
        counts: dict[PlaceId, int] = {}
        for agent in self.agents.values():
            counts[agent.at] = counts.get(agent.at, 0) + 1
        return counts

    def others_at(self, agent: AgentState) -> list[AgentState]:
        """Los demás agentes en el mismo lugar.

        Base de los eventos de encuentro del tick loop, y en F2 de quién puede
        hablar con quién.
        """
        return [
            other
            for other in self.agents_in_order()
            if other.spec_id != agent.spec_id and other.at == agent.at
        ]
