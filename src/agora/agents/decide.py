"""Deliberación: cómo un agente elige qué hacer.

Es el corazón del motor. Todo lo que un NPC "quiere" sale de aquí, y sale sin
LLM: solo aritmética sobre el estado y la personalidad.

Dos decisiones de diseño gobiernan el archivo entero:

**Alcance global.** El agente no puntúa lo que puede hacer donde está, sino
cada par (acción, lugar) del mundo, descontado por el tiempo de viaje. Elige
un objetivo y el viaje es la consecuencia. La alternativa (puntuar solo lo
local) tiene un fallo estructural: viajar no satisface ninguna necesidad, así
que nunca gana, y un agente se queda con hambre a tres ticks de la comida.

**Compromiso con excepción de urgencia.** Se delibera solo al quedar ocioso, y
lo elegido se termina — salvo que una necesidad cruce su umbral crítico y la
acción en curso no la esté atendiendo. Reevaluar cada tick produce *dithering*:
dos opciones casi empatadas y el agente alternando sin completar ninguna.

La fórmula:

    utilidad = suma_necesidades( peso * urgencia * satisface )
               * descuento_viaje
               * gusto(acción) * gusto(lugar)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import assert_never

from agora.engine.ontology import (
    ActionId,
    ActionSpec,
    AgentSpec,
    NeedId,
    PlaceId,
    PlaceSpec,
)
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState
from agora.engine.topology import INFINITE


@dataclass(frozen=True, slots=True)
class Decision:
    """Qué hacer y dónde. `travel_ticks` = 0 significa "aquí mismo"."""

    action: ActionId
    place: PlaceId
    utility: float
    travel_ticks: int


# -----------------------------------------------------------------------------
# Personalidad -> pesos
# -----------------------------------------------------------------------------


def need_weights(pack: ContentPack, spec: AgentSpec) -> dict[NeedId, float]:
    """Cuánto le importa a ESTE agente cada necesidad.

    La intensidad del rasgo entra como exponente, no como interpolación:

        factor = multiplicador ** intensidad

    Con intensidad 0 el rasgo no hace nada (M**0 == 1) y con -1 invierte
    exactamente (M**-1 == 1/M). Es simétrico en escala logarítmica, que es como
    se comporta un multiplicador. La interpolación lineal, en cambio, daría
    factores negativos para multiplicadores mayores que 2.
    """
    weights: dict[NeedId, float] = {need.id: need.base_weight for need in pack.needs}
    for trait_id, intensity in spec.traits.items():
        trait = pack.trait_by_id[trait_id]
        for need_id, multiplier in trait.need_weight_multipliers.items():
            weights[need_id] *= multiplier**intensity
    return weights


def taste_multipliers(spec: AgentSpec) -> dict[str, float]:
    """Predilecciones y aversiones, indexadas por id de objetivo.

    Clave `str` y no `ActionId`/`PlaceId`: un gusto puede apuntar a cualquiera
    de los tres espacios, y `pack.py` ya garantizó que no colisionan entre sí.
    """
    result: dict[str, float] = {}
    for taste in spec.tastes:
        key = str(taste.target)
        result[key] = result.get(key, 1.0) * taste.multiplier
    return result


def urgency(value: float, exponent: float) -> float:
    """Cuánto apremia una necesidad, dado lo llena que está.

    La curva es el motivo de que los agentes no parezcan termostatos. Con
    exponente 1 todo compite linealmente y el agente atiende cinco cosas a
    medias; con exponente 2.5 una necesidad es casi irrelevante hasta que de
    pronto es tiránica, que es como se comporta el hambre de verdad.
    """
    # `float(...)` explícito: para typeshed, `**` puede devolver un complejo
    # (base negativa, exponente fraccionario). El `max` ya lo impide aquí.
    return float(max(0.0, 1.0 - value) ** exponent)


# -----------------------------------------------------------------------------
# Puntuación
# -----------------------------------------------------------------------------


def appeal(
    pack: ContentPack,
    agent: AgentState,
    action: ActionSpec,
    weights: dict[NeedId, float],
) -> float:
    """Atractivo bruto de una acción, sin contar distancia ni gustos.

    Usa `satisfies` (lo que el agente CREE) y no `effects` (lo que realmente
    pasará). Que puedan diferir es intencional: permite que un NPC se equivoque
    y persiga algo que no le da lo que esperaba.
    """
    total = 0.0
    for need_id, satisfaction in action.satisfies.items():
        need = pack.need_by_id[need_id]
        pressure = urgency(agent.needs[need_id], need.urgency_exponent)
        total += weights[need_id] * pressure * satisfaction
    return total


def _is_available(action: ActionSpec, place: PlaceSpec) -> bool:
    return action.requires_affordance is None or action.requires_affordance in place.affordances


def candidates(world: WorldState, agent: AgentState) -> list[Decision]:
    """Todas las opciones del mundo, puntuadas.

    Coste: len(lugares) * len(acciones). Con el pack actual son 25 evaluaciones
    por deliberación, y una deliberación solo ocurre cuando el agente queda
    ocioso — no en cada tick. Si algún día el mundo tuviera cientos de lugares,
    el recorte es acotar por horizonte de viaje, no cachear.

    No se filtran las opciones de utilidad cero. Cuando todas las necesidades
    están llenas, todo vale 0 y el desempate por cercanía (ver `decide`) hace
    que el agente haga algo razonable ahí mismo en vez de quedarse en blanco.
    """
    pack = world.pack
    spec = world.spec_of(agent)
    weights = need_weights(pack, spec)
    tastes = taste_multipliers(spec)

    found: list[Decision] = []
    for place in pack.places:
        travel = world.travel.distance(agent.at, place.id)
        if travel >= INFINITE:
            continue  # imposible con un pack validado, pero el motor no asume
        discount = pack.tuning.travel_discount**travel
        place_taste = tastes.get(str(place.id), 1.0)

        for action in pack.actions:
            if not _is_available(action, place):
                continue
            utility = (
                appeal(pack, agent, action, weights)
                * discount
                * place_taste
                * tastes.get(str(action.id), 1.0)
            )
            found.append(
                Decision(action=action.id, place=place.id, utility=utility, travel_ticks=travel)
            )
    return found


def _rank(decision: Decision) -> tuple[float, int, str, str]:
    """Orden total y estable: mejor utilidad, luego más cerca, luego por id.

    El desempate por id no es cosmético. Sin él, dos opciones con la misma
    utilidad quedarían en el orden en que las produjo el bucle, y cualquier
    reordenación futura del pack cambiaría el comportamiento de una corrida
    con el mismo seed. El determinismo se rompe por sitios así.
    """
    return (-decision.utility, decision.travel_ticks, str(decision.action), str(decision.place))


def decide(world: WorldState, agent: AgentState) -> Decision | None:
    """Elige qué hará el agente a continuación.

    Softmax sobre los `candidate_pool` mejores: da variedad sin renunciar al
    criterio, y sigue siendo reproducible porque consume el RNG sembrado del
    mundo. `None` solo si no hay ninguna opción, algo que un pack validado
    impide (siempre existe la acción sin affordance).
    """
    pool = candidates(world, agent)
    if not pool:
        return None

    pool.sort(key=_rank)
    finalists = pool[: world.pack.tuning.candidate_pool]
    if len(finalists) == 1:
        return finalists[0]

    # Restar el máximo antes de exponenciar evita desbordar con utilidades
    # altas; es el truco estándar de estabilidad numérica del softmax y no
    # cambia el resultado, porque exp(a-m)/Σexp(b-m) == exp(a)/Σexp(b).
    best = finalists[0].utility
    temperature = world.pack.tuning.temperature
    weights = [math.exp((d.utility - best) / temperature) for d in finalists]
    return world.rng.choices(finalists, weights=weights, k=1)[0]


# -----------------------------------------------------------------------------
# Interrupción
# -----------------------------------------------------------------------------


def current_intent(agent: AgentState) -> ActionId | None:
    """Qué acción persigue el agente, esté ejecutándola o viajando hacia ella."""
    busy = agent.busy
    if busy is None:
        return None
    match busy:
        case PerformingAction():
            return busy.action
        case Traveling():
            return busy.intent
        case _:
            assert_never(busy)


def critical_need(world: WorldState, agent: AgentState) -> NeedId | None:
    """La necesidad que justifica abandonar lo que se está haciendo, si la hay.

    Dos condiciones, y la segunda es la que evita el comportamiento absurdo:
      1. la necesidad está por debajo del umbral crítico;
      2. lo que el agente persigue AHORA no la atiende.

    Sin la segunda, un agente hambriento abandonaría la comida por hambre en
    cada tick. Como `Traveling` lleva su `intent`, la comprobación funciona
    igual para quien ya está comiendo y para quien va de camino.
    """
    threshold = world.pack.tuning.critical_need_threshold
    intent = current_intent(agent)
    addressed = world.pack.action_by_id[intent].satisfies if intent is not None else {}

    worst: NeedId | None = None
    worst_value = threshold
    # `agent.needs` conserva el orden del pack, así que el recorrido es estable.
    for need_id, value in agent.needs.items():
        if value < worst_value and addressed.get(need_id, 0.0) <= 0.0:
            worst, worst_value = need_id, value
    return worst
