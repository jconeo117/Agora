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

from agora.engine.ontology import (
    ActionId,
    AgentId,
    AgentSpec,
    NeedId,
    NeedSpec,
    PlaceId,
    PlaceSpec,
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
    busy: Busy | None = None
    """`None` = ocioso. Este agente delibera en el tick actual."""

    # -- necesidades ----------------------------------------------------------

    def decay(self, need_specs: Mapping[NeedId, NeedSpec]) -> None:
        """Baja cada necesidad según su propia tasa. Resultado en [0, 1].

        Indexa directo en vez de usar `.get(..., default)`: si una necesidad del
        pack no está en el dict del agente, eso es un bug de construcción y
        quiero que reviente aquí, ruidosamente, y no que se propague un default
        inventado. El invariante lo garantiza `WorldState.new`.
        """
        for need_id, spec in need_specs.items():
            self.needs[need_id] = self._clamp(self.needs[need_id] - spec.decay_per_tick)

    def apply(self, effects: Mapping[NeedId, float]) -> None:
        """Suma los deltas de una acción completada. Resultado en [0, 1].

        Los deltas pueden ser negativos: trabajar da moneda y quita descanso.
        Una necesidad que la acción no menciona no se toca.
        """
        for need_id, delta in effects.items():
            self.needs[need_id] = self._clamp(self.needs[need_id] + delta)

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
        agents: dict[AgentId, AgentState] = {}
        for spec in pack.agents:  # el orden del pack fija el orden del mundo
            # Todas las necesidades del pack, aunque el agente no las mencione.
            # Un dict incompleto obliga a cada consumidor a inventarse un
            # default, y acabarían siendo distintos en dos sitios.
            needs: dict[NeedId, float] = {need.id: need.initial for need in pack.needs}
            needs.update(spec.initial_needs)

            agents[spec.id] = AgentState(
                spec_id=spec.id,
                at=spec.start_at,
                needs=needs,
                busy=None,  # todos deliberan en el tick 0
            )

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
