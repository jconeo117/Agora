"""Ontología invariante del motor.

Estas son las ÚNICAS primitivas que el motor conoce. Ninguna sabe qué es una
espada, un hechizo o una nave: solo sabe que existen "necesidades", "acciones"
y "lugares" con ciertos números. La ambientación entra como datos (content
pack), nunca como código.

Distinción central:
    Spec  -> definición inmutable que viene del pack. No cambia en runtime.
    State -> valores mutables de una partida concreta. Vive en `state.py`.

Es la misma separación que en Unity entre un ScriptableObject y la instancia
que corre en escena, o en C# entre una clase de configuración y su objeto.
"""

from __future__ import annotations

from typing import NewType

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Identificadores.
#
# `NewType` da a mypy la misma protección que un tipo fuerte en C#: pasar un
# PlaceId donde se espera un AgentId es un error de compilación, aunque en
# runtime ambos sean `str`. Coste cero en ejecución.
# ---------------------------------------------------------------------------
NeedId = NewType("NeedId", str)
TraitId = NewType("TraitId", str)
ActionId = NewType("ActionId", str)
PlaceId = NewType("PlaceId", str)
AgentId = NewType("AgentId", str)
Affordance = NewType("Affordance", str)
Tag = NewType("Tag", str)


class Spec(BaseModel):
    """Base de toda definición que viene del pack. Inmutable y estricta."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Necesidades
# ---------------------------------------------------------------------------
class NeedSpec(Spec):
    """Un eje de presión interna que decae con el tiempo.

    El motor no sabe si esto es "hambre" o "nivel de oxígeno". Solo sabe que
    baja sola y que ciertas acciones lo suben.
    """

    id: NeedId
    label: str
    """Nombre legible, solo para logs y narración. El motor nunca lo lee."""

    decay_per_tick: float = Field(gt=0.0, le=1.0)
    """Cuánto baja por tick. Calibrar esto ES el trabajo de F0."""

    initial: float = Field(default=1.0, ge=0.0, le=1.0)

    base_weight: float = Field(default=1.0, ge=0.0)
    """Importancia base antes de que la personalidad la modifique."""

    urgency_exponent: float = Field(default=2.0, gt=0.0)
    """Curva de urgencia: urgencia = (1 - valor) ** exponente.

    Exponente 1 = lineal (el NPC oscila, atiende todo a medias).
    Exponente 2 = la necesidad es irrelevante hasta que de pronto es crítica.
    Subir esto por necesidad concreta permite que "dormir" apremie distinto
    que "socializar".
    """


# ---------------------------------------------------------------------------
# Rasgos: multiplicadores estables de personalidad
# ---------------------------------------------------------------------------
class TraitSpec(Spec):
    """Un rasgo no "hace" nada: reescala el peso de ciertas necesidades.

    Ahí está la emergencia. Dos NPCs con reglas idénticas y pesos distintos
    viven vidas distintas sin una sola línea de código específica para ellos.
    """

    id: TraitId
    label: str
    need_weight_multipliers: dict[NeedId, float] = Field(default_factory=dict)
    """Ej: codicia -> {"dinero": 1.8, "social": 0.7}.

    Se interpola según cuánto tiene el agente del rasgo (-1..1), así que un
    valor de 1.0 aquí significa "sin efecto".
    """


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
class ActionSpec(Spec):
    """Algo que un agente puede hacer durante N ticks.

    `effects` y `satisfies` parecen redundantes pero no lo son:
      - satisfies -> se usa ANTES, para puntuar la acción al deliberar.
      - effects   -> se usa DESPUÉS, para aplicar el resultado real.
    Separarlos permite que un NPC se equivoque: puede creer que algo lo va a
    saciar y que el efecto real sea menor. Eso es material narrativo gratis.
    """

    id: ActionId
    label: str
    duration_ticks: int = Field(ge=1)

    requires_affordance: Affordance | None = None
    """Si está puesto, la acción solo es válida en lugares que la ofrezcan."""

    satisfies: dict[NeedId, float] = Field(default_factory=dict)
    """Cuánto CREE el agente que esta acción atiende cada necesidad (0..1)."""

    effects: dict[NeedId, float] = Field(default_factory=dict)
    """Delta real aplicado al completar. Puede ser negativo (trabajar cansa)."""

    tags: frozenset[Tag] = Field(default_factory=frozenset)
    """Válvula de escape para lo que el motor no modela: "violenta", "ilegal",
    "ruidosa". Los packs declaran qué significan; el motor solo las compara."""


# ---------------------------------------------------------------------------
# Lugares: nodos del grafo del mundo
# ---------------------------------------------------------------------------
class PlaceSpec(Spec):
    id: PlaceId
    label: str

    affordances: frozenset[Affordance] = Field(default_factory=frozenset)
    """Qué permite hacer aquí. Es el acoplamiento lugar <-> acción."""

    neighbors: dict[PlaceId, int] = Field(default_factory=dict)
    """Vecino -> ticks de viaje. El grafo es dirigido a propósito: bajar por un
    acantilado puede costar menos que subirlo."""

    tags: frozenset[Tag] = Field(default_factory=frozenset)
    """Atmósfera y control: "sagrado", "vigilado", "ruinoso"."""

    @model_validator(mode="after")
    def _no_self_loop(self) -> PlaceSpec:
        if self.id in self.neighbors:
            raise ValueError(f"lugar {self.id!r} es vecino de sí mismo")
        return self


# ---------------------------------------------------------------------------
# Gustos: modificadores por objetivo concreto
# ---------------------------------------------------------------------------
class TasteSpec(Spec):
    """Preferencia hacia un objetivo específico.

    Rasgos sesgan CATEGORÍAS de necesidad; los gustos sesgan INSTANCIAS.
    "Sociable" es un rasgo. "Odia la taberna del puerto" es un gusto.
    Sin esta capa todos los NPCs sociables se comportan igual.
    """

    target: ActionId | PlaceId | AgentId
    multiplier: float = Field(gt=0.0)
    """<1 aversión, >1 predilección. Multiplica la utilidad final."""


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------
class AgentSpec(Spec):
    id: AgentId
    label: str
    home: PlaceId
    start_at: PlaceId

    traits: dict[TraitId, float] = Field(default_factory=dict)
    """Rasgo -> intensidad en -1..1. Validado abajo."""

    tastes: tuple[TasteSpec, ...] = ()
    initial_needs: dict[NeedId, float] = Field(default_factory=dict)
    """Override del `initial` de cada NeedSpec. Lo que falte usa el default."""

    @model_validator(mode="after")
    def _traits_in_range(self) -> AgentSpec:
        for trait, value in self.traits.items():
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"rasgo {trait!r} = {value}, fuera de [-1, 1]")
        return self
