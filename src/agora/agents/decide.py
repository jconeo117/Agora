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

    beneficio = suma_necesidades( peso * urgencia * satisface )
    coste     = suma_necesidades( peso * urgencia * cuesta )

    utilidad  = beneficio * descuento_viaje * gustos - aversion * coste

Tres detalles de esa expresión que no son arbitrarios:

**La urgencia pondera también el coste.** Gastar duele más cuando no queda
dinero; perder sueño duele más estando agotado. De ahí sale que el mismo agente
cambie de conducta según su situación, sin una sola regla escrita para ello. Es
también lo que hace operativos los rasgos económicos: subir el peso de una
necesidad hace a la vez que se persiga más y que se gaste menos.

**El descuento y los gustos multiplican solo el beneficio.** Si multiplicaran el
neto, una opción mala y lejana parecería menos mala por estar lejos, y algo que
al agente le encanta le repelería más cuando el neto es negativo. El descuento
dice "la recompensa está lejos, vale menos"; el precio que se paga al llegar no
se descuenta.

**La utilidad puede ser negativa**, y debe poder serlo: significa "mala idea
ahora mismo". Como la acción de red de seguridad no cuesta nada y vale casi
cero, un agente para el que todo sale negativo se queda quieto. Eso no es un
bloqueo: es alguien que decide que no le compensa moverse.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_never

from agora.engine.ontology import (
    ActionId,
    ActionSpec,
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


def _weigh(
    pack: ContentPack,
    agent: AgentState,
    weights: dict[NeedId, float],
    terms: Mapping[NeedId, float],
) -> float:
    """Suma ponderada por importancia y urgencia. Sirve a beneficio y coste.

    Que ambos pasen por aquí no es ahorro de líneas: es lo que garantiza que
    ganar y perder se midan con la misma vara. Ponderar el beneficio por
    urgencia y el coste no haría que un agente desesperado ignorara los
    precios.
    """
    total = 0.0
    for need_id, amount in terms.items():
        need = pack.need_by_id[need_id]
        pressure = urgency(agent.needs[need_id], need.urgency_exponent)
        total += weights[need_id] * pressure * amount
    return total


def benefit(
    pack: ContentPack,
    agent: AgentState,
    action: ActionSpec,
    weights: dict[NeedId, float],
) -> float:
    """Lo que el agente espera ganar.

    Usa `satisfies` (lo que CREE) y no `effects` (lo que realmente pasará). Que
    puedan diferir es intencional: permite que un NPC se equivoque y persiga
    algo que no le da lo que esperaba.
    """
    return _weigh(pack, agent, weights, action.satisfies)


def cost(
    pack: ContentPack,
    agent: AgentState,
    action: ActionSpec,
    weights: dict[NeedId, float],
) -> float:
    """Lo que el agente espera perder. Espejo exacto de `benefit`."""
    return _weigh(pack, agent, weights, action.costs)


def is_available(action: ActionSpec, place: PlaceSpec, company: int = 0) -> bool:
    """¿Se puede ejecutar esta acción aquí y ahora?

    `company` son los OTROS agentes presentes, sin contar al que pregunta.

    Público porque el tick loop lo necesita al llegar a destino: entre decidir y
    llegar, la gente se mueve, y una intención social puede haberse quedado sin
    interlocutor.
    """
    if action.requires_affordance is not None and (
        action.requires_affordance not in place.affordances
    ):
        return False
    return company >= action.requires_company


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
    # La disposición ya está compuesta en el estado del agente: componerla aquí
    # sería rehacer en cada deliberación algo que cambia una vez cada muchos
    # días. Ver `AgentState.drift_trait`.
    weights = agent.need_weights
    tastes = agent.tastes
    temperament = agent.temperament

    # Una sola pasada para los 21 lugares en vez de una cuenta por consulta.
    # Nota: es la ocupación de AHORA, y el agente puede tardar en llegar. Que se
    # equivoque es correcto —la gente se mueve— y en F1.6, cuando el
    # conocimiento sea limitado, esto pasará a ser una creencia y no un hecho.
    occupancy = world.occupancy()

    found: list[Decision] = []
    for place in pack.places:
        travel = world.travel.distance(agent.at, place.id)
        if travel >= INFINITE:
            continue  # imposible con un pack validado, pero el motor no asume
        discount = temperament.travel_discount**travel
        place_taste = tastes.get(str(place.id), 1.0)
        company = occupancy.get(place.id, 0) - (1 if agent.at == place.id else 0)

        for action in pack.actions:
            if not is_available(action, place, company):
                continue
            reward = benefit(pack, agent, action, weights) * discount * place_taste
            reward *= tastes.get(str(action.id), 1.0)
            price = cost(pack, agent, action, weights) * temperament.loss_aversion
            found.append(
                Decision(
                    action=action.id,
                    place=place.id,
                    utility=reward - price,
                    travel_ticks=travel,
                )
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


def decide(
    world: WorldState, agent: AgentState, must_address: NeedId | None = None
) -> Decision | None:
    """Elige qué hará el agente a continuación.

    Softmax sobre los `candidate_pool` mejores: da variedad sin renunciar al
    criterio, y sigue siendo reproducible porque consume el RNG sembrado del
    mundo. `None` solo si no hay ninguna opción, algo que un pack validado
    impide (siempre existe la acción sin affordance).

    `must_address` restringe la elección a acciones que atienden esa necesidad.
    Lo usa el tick loop justo después de una interrupción, y no es un detalle:
    sin él, el agente abandona por hambre y vuelve a elegir dormir porque
    dormir seguía siendo lo mejor puntuado — abandona y reinicia lo mismo cada
    tick, para siempre. Una interrupción tiene que **cambiar** lo que se hace o
    no sirve de nada.
    """
    pool = candidates(world, agent)
    if must_address is not None:
        forced = [
            option
            for option in pool
            if world.pack.action_by_id[option.action].satisfies.get(must_address, 0.0) > 0.0
        ]
        if forced:  # si nada la atiende, mejor decidir libremente que bloquearse
            pool = forced
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
    temperature = agent.temperament.temperature
    weights = [math.exp((d.utility - best) / temperature) for d in finalists]

    # La clave incluye el tick, y ese detalle es el que importa: el sorteo pasa
    # a ser función pura de (semilla, agente, momento) en vez de depender de
    # cuántos sorteos hubo antes. Sin eso no se puede avanzar una parte del
    # mundo sin avanzar el resto.
    rng = world.rng.stream("decide", agent.spec_id, world.tick)
    return rng.choices(finalists, weights=weights, k=1)[0]


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


def critical_needs(world: WorldState, agent: AgentState) -> list[NeedId]:
    """Necesidades bajo el umbral crítico, de la peor a la menos mala.

    Desempate por id para que el orden no dependa de la comparación de floats
    cuando dos valores coinciden.
    """
    threshold = agent.temperament.critical_need_threshold
    urgent = [need for need, value in agent.needs.items() if value < threshold]
    return sorted(urgent, key=lambda need: (agent.needs[need], str(need)))


def critical_need(world: WorldState, agent: AgentState) -> NeedId | None:
    """La necesidad que justifica abandonar lo que se está haciendo, si la hay.

    La regla es: **se interrumpe solo si lo que se está haciendo no atiende
    NINGUNA de las emergencias**. No "ninguna en concreto" — ninguna en
    absoluto.

    La diferencia decide si el motor funciona. Con dos necesidades críticas a
    la vez, ninguna acción puede atender las dos; si la comprobación fuera por
    necesidad individual, siempre quedaría una sin cubrir y el agente
    abandonaría lo que hiciera, cada tick, indefinidamente. Con la regla de
    "alguna", el que ya está resolviendo una emergencia sigue a lo suyo.

    Como `Traveling` lleva su `intent`, esto funciona igual para quien ya está
    comiendo y para quien va de camino a comer.
    """
    urgent = critical_needs(world, agent)
    if not urgent:
        return None

    intent = current_intent(agent)
    if intent is not None:
        satisfies = world.pack.action_by_id[intent].satisfies
        if any(satisfies.get(need, 0.0) > 0.0 for need in urgent):
            return None

    return urgent[0]
