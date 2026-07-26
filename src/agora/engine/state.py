"""Estado mutable de una partida.

`ontology.py` define cómo ES el mundo (inmutable, viene del pack).
Este archivo define cómo ESTÁ el mundo ahora mismo (mutable, cambia por tick).

Nota de rendimiento que explica una decisión: aquí NO se usa pydantic para el
estado caliente. Pydantic valida en cada construcción, y esto se toca 672 veces
por semana simulada por cada agente. Regla general: **pydantic en las fronteras
(datos externos), dataclass en el interior (datos ya confiables)**. Es el mismo
criterio que en C# separa un DTO validado de un struct interno.

--- CÓMO TRABAJAR ESTE ARCHIVO -------------------------------------------------
Los PASOS están numerados. `tests/test_state.py` te dice cuál falta.
    uv run pytest tests/test_state.py -v
--------------------------------------------------------------------------------
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from agora.engine.ontology import ActionId, AgentId, NeedId, NeedSpec, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.topology import TravelMap

# -----------------------------------------------------------------------------
# Qué está haciendo un agente: unión, no un flag.
#
# Estos dos SÍ son pydantic y SÍ son frozen. Son pequeños, se crean pocas veces
# y ser inmutables elimina de raíz los bugs de aliasing (dos agentes acabando
# con el mismo objeto `Busy` y decrementándolo dos veces). En un motor
# determinista ese bug es de los más difíciles de encontrar.
#
# Para "avanzar un tick" no se muta: se crea uno nuevo con `model_copy`.
# -----------------------------------------------------------------------------


class PerformingAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: ActionId
    ticks_remaining: int = Field(ge=0)


class Traveling(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: PlaceId
    """A dónde quiere llegar al final."""

    next_hop: PlaceId
    """El tramo actual. Un viaje largo son varios `Traveling` encadenados.

    Por qué guardar el tramo y no la ruta entera: al llegar a cada nodo se
    vuelve a preguntar `TravelMap.first_hop`, así que un cambio en el mundo
    (un camino cortado, un lugar cerrado de noche) se absorbe solo, sin
    invalidar viajes en curso.
    """

    ticks_remaining: int = Field(ge=0)


type Busy = PerformingAction | Traveling
"""Unión discriminada. Consúmela siempre con `match` + `assert_never`:

    match busy:
        case PerformingAction(): ...
        case Traveling():        ...
        case _:                  assert_never(busy)

Cuando en F1 añadas un tercer caso (huir, por ejemplo), mypy te señalará cada
sitio que falta actualizar. Eso es lo que en C# tendrías que confiar a un
`default:` que revienta en runtime.
"""


# -----------------------------------------------------------------------------
# Estado de un agente
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class AgentState:
    """Dónde está, cómo está y qué está haciendo un agente.

    `slots=True` es el equivalente aproximado de un `struct` de C#: sin `__dict__`,
    menos memoria y acceso a atributos más rápido. A cambio no puedes añadir
    atributos al vuelo, que es justo lo que quieres aquí.
    """

    spec_id: AgentId
    """Solo el id, no el `AgentSpec` entero.

    Decisión deliberada: mantiene el estado serializable. En F4 vas a querer
    guardar partidas, y un estado que arrastra specs se convierte en un
    problema de identidad al recargar. El spec se busca en `pack.agent_by_id`.
    """

    at: PlaceId
    needs: dict[NeedId, float]
    busy: Busy | None = None
    """`None` = ocioso. Este agente delibera en el tick actual."""

    # -- PASO 1 ---------------------------------------------------------------
    def decay(self, need_specs: Mapping[NeedId, NeedSpec]) -> None:
        """Baja cada necesidad según su `decay_per_tick`. Resultado en [0, 1].

        Recorre `self.needs` y resta. Usa `_clamp` — no repartas el clamp por
        el archivo (ver PASO 3).
        """
        raise NotImplementedError("PASO 1")

    # -- PASO 2 ---------------------------------------------------------------
    def apply(self, effects: Mapping[NeedId, float]) -> None:
        """Suma los deltas de una acción completada. Resultado en [0, 1].

        Los deltas pueden ser negativos: trabajar da moneda y quita descanso.
        Una necesidad que la acción no menciona no se toca.
        """
        raise NotImplementedError("PASO 2")

    # -- PASO 3 ---------------------------------------------------------------
    @staticmethod
    def _clamp(value: float) -> float:
        """El ÚNICO sitio donde se fuerza el rango [0, 1].

        Si el clamp se dispersa por el código, un día una necesidad vale 1.4 y
        pasas dos horas buscando quién la dejó así. Una sola puerta.
        """
        raise NotImplementedError("PASO 3")

    # -- PASO 4 ---------------------------------------------------------------
    def advance(self) -> None:
        """Consume un tick de lo que esté haciendo.

        Si `busy` es `None`, no hace nada.
        Si le quedaba 1 tick, queda en 0 (NO lo pongas en `None`: quien llama
        necesita ver que terminó para aplicar efectos o registrar la llegada).

        Recuerda: `Busy` es inmutable. No hagas `self.busy.ticks_remaining -= 1`;
        crea uno nuevo con `self.busy.model_copy(update={...})`.
        """
        raise NotImplementedError("PASO 4")

    # -- PASO 5 ---------------------------------------------------------------
    @property
    def is_idle(self) -> bool:
        """Ocioso = sin nada que hacer, o con algo que ya se agotó.

        Es la condición que usará el tick loop para saber a quién toca deliberar.
        """
        raise NotImplementedError("PASO 5")


# -----------------------------------------------------------------------------
# Estado del mundo
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class WorldState:
    pack: ContentPack
    travel: TravelMap
    """Construido UNA vez aquí. No lo recalcules por tick."""

    tick: int = 0
    agents: dict[AgentId, AgentState] = field(default_factory=dict)
    """`dict` y no `list` ni `set`. Necesitas dos cosas a la vez: búsqueda O(1)
    por id, y orden estable. `dict` da ambas desde Python 3.7. Un `set` te
    rompe el determinismo en silencio y sin aviso."""

    rng: random.Random = field(default_factory=random.Random)
    """El generador vive AQUÍ, sembrado, y se pasa explícitamente a quien lo
    necesite. Nunca `import random; random.choice(...)` a nivel de módulo: eso
    usa un generador global compartido y ahí se muere la reproducibilidad."""

    seed: int = 0
    """Se escribe en la primera línea del log. Un bug se reproduce corriendo el
    mismo seed; sin esto, un fallo raro en el día 5 no se investiga."""

    # -- PASO 6 ---------------------------------------------------------------
    @classmethod
    def new(cls, pack: ContentPack, seed: int) -> WorldState:
        """Construye el estado inicial desde un pack.

        Qué hacer:
          1. `TravelMap(pack.places)`
          2. `random.Random(seed)`
          3. un `AgentState` por cada `AgentSpec`, EN EL ORDEN DEL PACK:
             - `at` = `spec.start_at`
             - `needs` = el `initial` de cada `NeedSpec`, sobrescrito por
               lo que diga `spec.initial_needs`
             - `busy` = None (todos deliberan en el tick 0)

        Toda necesidad del pack debe aparecer en el dict de todo agente, aunque
        el agente no la mencione. Un dict de necesidades incompleto obliga a
        cada consumidor a hacer `.get(need, default)`, y ese default acabará
        siendo distinto en dos sitios.
        """
        raise NotImplementedError("PASO 6")

    # -- PASO 7 ---------------------------------------------------------------
    def agents_in_order(self) -> list[AgentState]:
        """Los agentes en orden fijo y reproducible.

        Existe como método propio para que el orden se decida en UN sitio. El
        día que quieras aleatorizar el orden por tick (para que el mismo agente
        no gane siempre los empates), se cambia aquí y en ningún otro lado.
        """
        raise NotImplementedError("PASO 7")
