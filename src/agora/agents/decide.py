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

    utilidad  = beneficio * descuento_viaje * gustos * compañía * hora - aversion * coste

Tres detalles de esa expresión que no son arbitrarios:

**La urgencia pondera también el coste.** Gastar duele más cuando no queda
dinero; perder sueño duele más estando agotado. De ahí sale que el mismo agente
cambie de conducta según su situación, sin una sola regla escrita para ello. Es
también lo que hace operativos los rasgos económicos: subir el peso de una
necesidad hace a la vez que se persiga más y que se gaste menos.

**El descuento, los gustos y la compañía multiplican solo el beneficio.** Si
multiplicaran el neto, una opción mala y lejana parecería menos mala por estar
lejos, y algo que al agente le encanta le repelería más cuando el neto es
negativo. El descuento dice "la recompensa está lejos, vale menos"; el precio
que se paga al llegar no se descuenta.

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

from agora.engine.disposition import urgency
from agora.engine.ontology import (
    ActionId,
    ActionSpec,
    AgentId,
    NeedId,
    PhaseId,
    PlaceId,
    PlaceSpec,
    TraitId,
)
from agora.engine.outcome import company_saturation
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


# `urgency` vive en `disposition.py`: no es deliberación, es "cuánto le importa
# esto a este agente ahora". Desde allí la usa también `outcome.py` para valorar
# lo ocurrido con la misma vara con la que se decidió.


# -----------------------------------------------------------------------------
# Puntuación
# -----------------------------------------------------------------------------


def _weigh(
    pack: ContentPack,
    agent: AgentState,
    weights: dict[NeedId, float],
    terms: Mapping[NeedId, float],
    beliefs: Mapping[NeedId, float],
) -> float:
    """Suma ponderada por importancia, urgencia y experiencia.

    Que beneficio y coste pasen por aquí no es ahorro de líneas: es lo que
    garantiza que ganar y perder se midan con la misma vara. Ponderar el
    beneficio por urgencia y el coste no haría que un agente desesperado
    ignorara los precios; aprender solo de los premios y no de los precios haría
    que nunca escarmentara.

    Lo ausente en `beliefs` vale 1.0: quien no tiene experiencia se cree el pack.
    """
    total = 0.0
    for need_id, amount in terms.items():
        need = pack.need_by_id[need_id]
        pressure = urgency(agent.needs[need_id], need.urgency_exponent)
        total += weights[need_id] * pressure * amount * beliefs.get(need_id, 1.0)
    return total


def benefit(
    pack: ContentPack,
    agent: AgentState,
    action: ActionSpec,
    weights: dict[NeedId, float],
) -> float:
    """Lo que ESTE agente espera ganar.

    Parte de `satisfies` —lo que el pack dice que la acción persigue— y lo
    escala por lo que el agente ha aprendido a esperar de ella. Dos agentes con
    la misma ficha pueden valorar lo mismo de forma distinta porque han vivido
    cosas distintas.

    Lo ausente en `beliefs` vale 1.0: quien no tiene experiencia se cree el pack.
    """
    return _weigh(
        pack, agent, weights, action.satisfies, agent.gain_beliefs.get(action.id, {})
    )


def cost(
    pack: ContentPack,
    agent: AgentState,
    action: ActionSpec,
    weights: dict[NeedId, float],
) -> float:
    """Lo que ESTE agente espera perder. Espejo exacto de `benefit`.

    También se aprende: descubrir que algo sale más caro de lo que creías es
    tan capaz de cambiar una rutina como descubrir que rinde menos.
    """
    return _weigh(pack, agent, weights, action.costs, agent.cost_beliefs.get(action.id, {}))


def novelty(agent: AgentState, action: ActionId, weight: float) -> float:
    """Cuánto atractivo le queda a algo de tanto repetirlo.

        novedad = 1 - saturación * peso

    Multiplica el **beneficio**, nunca el neto: el hastío quita ganas de hacer
    algo, no cambia lo que cuesta.

    El suelo en `1 - peso` es deliberado. Con novedad pura, una acción saturada
    al tope valdría cero, y un agente harto de comer se dejaría morir de hambre
    antes que repetir. El hastío tiene que poder cambiar un plan, no vetarlo.
    """
    return 1.0 - agent.saturation.get(action, 0.0) * weight


def companionship(action: ActionSpec, company: float, weight: float) -> float:
    """Cuánto más (o menos) apetece este plan por la gente que habrá.

        factor = 1 + peso * saturación(compañía_efectiva)

    Cubre un punto ciego real. Hasta ahora la compañía era **solo una puerta
    dura**: `charlar` con una persona delante puntuaba exactamente igual que
    `charlar` con cinco, y nadie prefería la plaza llena a la plaza justa. Al
    entrar los vínculos hace falta además que se prefiera la plaza donde está la
    gente que importa, y las dos cosas son el mismo término.

    El filtro es lo que impide que se desmadre: solo se aplica a las acciones a
    las que el pack dice que la gente les importa. Sin él, un agente preferiría
    dormir rodeado de gente, que es absurdo y además invisible hasta que lees el
    log de una semana.

    Acotado a 0 por abajo: con pesos altos y compañía detestable el factor
    llegaría a negativo, y un beneficio de signo cambiado no significa nada.
    Cero ya dice todo lo que hay que decir — con esa gente, el plan no vale.
    """
    if weight <= 0.0 or (not action.effects_per_company and action.requires_company == 0):
        return 1.0
    return max(0.0, 1.0 + weight * company_saturation(company))


def recovery_rate(action: ActionSpec, agent: AgentState, place: PlaceSpec) -> float:
    """A qué ritmo repone esta acción, para esta persona, en este sitio.

        ritmo = base * su_aptitud * la_calidad_del_sitio

    Las dos modulaciones se componen, y de ahí sale toda la variación: duerme mal
    quien tiene mal sueño, quien duerme en mal sitio, y peor quien las dos cosas.
    Las quince horas del guerrero no son un caso especial — son el ritmo de la
    intemperie aplicado a un déficit grande.
    """
    elastic = action.elastic
    if elastic is None:  # pragma: no cover - quien llama ya lo comprobó
        return 0.0
    return float(
        elastic.per_tick
        * agent.gains.get(elastic.need, 1.0)
        * place.gain_multipliers.get(elastic.need, 1.0)
    )


def planned_duration(action: ActionSpec, agent: AgentState, place: PlaceSpec) -> int:
    """Cuánto va a durar esto de verdad. Para lo no elástico, lo que dice el pack.

        ticks = acotado( déficit / ritmo,  min_ticks,  duration_ticks )

    El déficit incluye la deuda, y ahí está el drama: dos agentes con el descanso
    a cero duermen cosas muy distintas si uno lleva tres días de batalla encima.

    Se calcula al empezar y se guarda en `PerformingAction.total_ticks`, no se
    recalcula por tick. Recalcular haría que el sueño se alargara solo cada vez
    que el agente se repone un poco, y no terminaría nunca.
    """
    elastic = action.elastic
    if elastic is None:
        return action.duration_ticks

    rate = recovery_rate(action, agent, place)
    needed = math.ceil(agent.deficit(elastic.need) / rate) if rate > 0.0 else action.duration_ticks
    return max(elastic.min_ticks, min(action.duration_ticks, needed))


def phase_fit(action: ActionSpec, phase: PhaseId | None) -> float:
    """Cuánto rinde esta acción en esta franja. 1.0 si el mundo no tiene franjas.

    La franja que se pasa aquí es la **subjetiva**: ya viene rotada por el reloj
    interno de quien pregunta (ver `candidates`). Por eso esta función no sabe
    nada de cronotipos — para un ave nocturna, su mañana simplemente cae de
    madrugada, y todo lo demás se lee igual.
    """
    if phase is None:
        return 1.0
    return action.phase_multipliers.get(phase, 1.0)


def is_available(
    action: ActionSpec,
    place: PlaceSpec,
    company: int | None,
    needs: Mapping[NeedId, float],
    phase: PhaseId | None = None,
    traits: Mapping[TraitId, float] | None = None,
) -> bool:
    """¿Se puede ejecutar esta acción aquí y ahora? Cinco puertas duras:

    - **el lugar** la ofrece (affordance)
    - **el lugar está abierto** a esta hora (`open_during`)
    - **hay gente** suficiente (`company` = los OTROS, sin contar a quien pregunta)
    - **alcanzan los recursos** (`requires`)
    - **eres quien hay que ser** (`requires_traits`)

    La última no mira lo que tienes sino quién eres: un conjuro de fuego pide
    afinidad con el fuego, y ninguna cantidad de dinero la sustituye. `traits` a
    `None` la desactiva, para poder preguntar por una acción sin un agente
    delante.

    Cerrar es una puerta y no un descuento por lo mismo que la affordance: la
    herrería cerrada de noche no es menos atractiva, es que no está. Y cierra
    **actividades, no el paso**: un lugar cerrado se sigue cruzando, o el mundo
    dejaría de estar fuertemente conectado a ciertas horas y alguien podría
    quedarse encerrado lejos de su cama.

    `company=None` significa "no lo sé", y se resuelve **a favor**. Un agente que
    no tiene noticia fresca de un sitio va a mirar; suponer vacío haría que nadie
    fuera nunca a donde no acabara de estar. El chasco lo da la comprobación al
    llegar, con la verdad en la mano.

    Ninguna condición lleva valor por defecto a propósito. Un `company=0`
    implícito convertiría en ejecutable una acción social por olvidarse de
    pasarlo, y ese fallo no se nota mirando: se nota siete días después, leyendo
    el log.

    Pública porque el tick loop la necesita al llegar a destino. Entre decidir y
    llegar cambian las tres cosas: la gente se va, el dinero se gasta, y más
    adelante los lugares cerrarán de noche.
    """
    if action.requires_affordance is not None and (
        action.requires_affordance not in place.affordances
    ):
        return False
    if place.open_during and phase is not None and phase not in place.open_during:
        return False
    if traits is not None and any(
        traits.get(trait, 0.0) < minimum for trait, minimum in action.requires_traits.items()
    ):
        return False
    if company is not None and company < action.requires_company:
        return False
    return all(needs[need] >= minimum for need, minimum in action.requires.items())


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

    # La ocupación real solo se usa para el sitio donde ESTÁ: eso lo ve. Del
    # resto tira de lo que recuerda haber visto, y lo que no recuerda lo supone
    # a favor. Con `sighting_horizon` a 0 se vuelve a la omnisciencia.
    occupants = world.occupants()
    tuning = pack.tuning
    horizon = tuning.sighting_horizon

    # DOS relojes, y la distinción es el corazón del cronotipo.
    #
    # El del mundo es objetivo: la herrería cierra a la misma hora para todos, y
    # de él sale `open_during`. El del cuerpo es subjetivo: va rotado por el
    # `phase_shift` del agente, y de él sale lo que apetece hacer. Para un ave
    # nocturna su mañana cae de madrugada — trabaja, come y socializa entonces, y
    # duerme cuando su noche subjetiva coincide con tu tarde.
    #
    # Ambas se resuelven UNA vez por deliberación, no por par (lugar, acción). Y
    # son las del momento de decidir, no las de la llegada: si el sitio ha
    # cerrado cuando llega, se lleva el chasco — igual que con la compañía, y por
    # la misma comprobación.
    clock = pack.clock
    open_phase = clock.phase_at(world.tick)
    felt_phase = clock.phase_at(world.tick + agent.phase_shift)

    found: list[Decision] = []
    for place in pack.places:
        travel = world.travel.distance(agent.at, place.id)
        if travel >= INFINITE:
            continue  # imposible con un pack validado, pero el motor no asume
        discount = temperament.travel_discount**travel
        place_taste = tastes.get(str(place.id), 1.0)

        # Quién cree que hay allí. `None` = no tiene noticia, y se supone a favor.
        crowd: frozenset[AgentId] | None
        if place.id == agent.at:
            crowd = occupants.get(place.id, frozenset()) - {agent.spec_id}
        else:
            crowd = agent.perceived_crowd(place.id, world.tick, horizon)
            if horizon <= 0:
                crowd = occupants.get(place.id, frozenset())

        # Dos lecturas de la misma gente, y no son intercambiables. La puerta
        # dura cuenta cabezas: una fiesta necesita cuerpos, no amigos. El
        # atractivo cuenta personas: cuatro conocidos no son cuatro extraños.
        headcount = None if crowd is None else len(crowd)
        expected = (
            0.0
            if crowd is None
            else agent.effective_company(
                crowd, world.tick, tuning.bond_weight, tuning.bond_fade
            )
        )

        for action in pack.actions:
            if not is_available(
                action, place, headcount, agent.needs, open_phase, agent.traits
            ):
                continue
            reward = benefit(pack, agent, action, weights) * discount * place_taste
            reward *= tastes.get(str(action.id), 1.0)
            reward *= novelty(agent, action.id, tuning.novelty_weight)
            reward *= companionship(action, expected, tuning.companionship_weight)
            reward *= phase_fit(action, felt_phase)
            # Comprometer tiempo tiene coste: mientras dure, no se atiende nada
            # más. Ese era el punto ciego respecto a la duración.
            #
            # Con lo elástico hay que descontar la duración REAL, no la del pack:
            # el tope de una acción elástica es lo que dura en el peor caso, y
            # castigar una cabezada de una hora como si fueran las ocho del tope
            # haría que nadie echara nunca una cabezada.
            reward *= tuning.duration_discount ** planned_duration(action, agent, place)
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

    `must_address` restringe la elección a acciones que atienden esa necesidad,
    y devuelve **None si ninguna disponible lo hace**. No cae a elección libre.

    Esa severidad es deliberada y corrige un traqueteo real. Con fallback, un
    agente sin dinero y sin despensa abandonaba su turno de trabajo cada tick:
    la peor urgencia era la despensa, la única acción que la atiende exige
    dinero que no tenía, `must_address` no encontraba nada, elegía libremente
    —trabajar, que era exactamente lo correcto— y al tick siguiente volvía a
    abandonarlo. El plan era bueno; la interrupción lo destruía.

    Ahora quien llama decide qué hacer con el None. El tick loop lo interpreta
    como "no merece la pena interrumpir"; un agente ocioso vuelve a preguntar
    sin restricción.
    """
    pool = candidates(world, agent)
    if must_address is not None:
        pool = [
            option
            for option in pool
            if world.pack.action_by_id[option.action].satisfies.get(must_address, 0.0) > 0.0
        ]
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


def commitment(world: WorldState, agent: AgentState) -> float:
    """Cuánto lleva invertido en lo que está haciendo, en [0, 1].

    Para una acción es el progreso sobre su duración. Para un viaje es el
    trayecto ENTERO, no el tramo: como los tramos son de uno o dos ticks, medir
    por tramo haría que quien lleva cuatro ticks caminando pareciera recién
    salido de casa cada vez que pisa un cruce.
    """
    busy = agent.busy
    if busy is None:
        return 0.0

    match busy:
        case PerformingAction():
            # De `busy` y no del spec: con lo elástico, la duración la fijó el
            # déficit de este agente al empezar y el pack ya no la sabe.
            total = busy.total_ticks or world.pack.action_by_id[busy.action].duration_ticks
            return 1.0 - busy.ticks_remaining / total
        case Traveling():
            if busy.total_ticks <= 0:
                return 0.0
            queda = world.travel.distance(busy.next_hop, busy.destination)
            if queda >= INFINITE:  # pragma: no cover - pack validado lo impide
                return 0.0
            return max(0.0, 1.0 - (busy.ticks_remaining + queda) / busy.total_ticks)
        case _:
            assert_never(busy)


def critical_needs(world: WorldState, agent: AgentState) -> list[NeedId]:
    """Necesidades bajo el umbral crítico, de la peor a la menos mala.

    El umbral se estrecha con lo ya invertido: a mitad de tarea hace falta una
    urgencia mayor para soltarla, y casi al final solo una catástrofe. Es el
    "ya que estoy, lo termino".

    Desempate por id para que el orden no dependa de la comparación de floats
    cuando dos valores coinciden.
    """
    threshold = agent.temperament.critical_need_threshold * (
        1.0 - commitment(world, agent) * world.pack.tuning.switch_cost
    )
    # Los ejes de progresión quedan fuera: ser novato no es una emergencia. Sin
    # esta guarda, quien empieza abajo pasa toda su escalada bajo el umbral,
    # soltando lo que hiciera para ir a entrenar. Medido con una ganancia
    # realista, el tiempo en crisis del mundo pasa de 0 % a 27.7 %.
    #
    # Solo pierden el poder de INTERRUMPIR. La urgencia se les sigue calculando
    # igual, así que crecer sigue apeteciendo más cuanto menos se ha crecido.
    by_id = world.pack.need_by_id
    urgent = [
        need
        for need, value in agent.needs.items()
        if value < threshold and not by_id[need].progression
    ]
    return sorted(urgent, key=lambda need: (agent.needs[need], str(need)))


def critical_need(world: WorldState, agent: AgentState) -> NeedId | None:
    """La necesidad que justifica abandonar lo que se está haciendo, si la hay.

    La regla es **triaje**: se interrumpe si lo que se está haciendo no atiende
    la PEOR de las emergencias. Quien está resolviendo lo más grave sigue a lo
    suyo; quien atiende lo secundario mientras algo peor arde, cambia.

    Historia de esta línea, porque explica por qué no fue así desde el principio.
    Primero se comprobaba necesidad a necesidad y producía un bucle: con dos
    urgencias a la vez ninguna acción cubre ambas, así que el agente abandonaba
    lo que hiciera en cada tick, indefinidamente. El parche fue exigir que no
    atendiera NINGUNA, y eso mató el bucle pero invirtió el sentido de la
    perilla: con el umbral alto casi todo es emergencia, hagas lo que hagas
    atiendes alguna, y quedas excusado. Un umbral alto no alarmaba — daba
    coartada. Medido: correlación -0.76 entre urgencias simultáneas y abandonos.

    Lo que permite volver al triaje es el **coste de cambio**: el umbral se
    estrecha con lo invertido, así que abandonar algo avanzado exige una
    catástrofe. Eso ataja el traqueteo por donde había que atajarlo, sin
    mentir sobre lo que significa el umbral.

    Como `Traveling` lleva su `intent`, funciona igual para quien ya está
    comiendo y para quien va de camino a comer.
    """
    urgent = critical_needs(world, agent)
    if not urgent:
        return None

    worst = urgent[0]
    intent = current_intent(agent)
    if intent is not None:
        satisfies = world.pack.action_by_id[intent].satisfies
        if satisfies.get(worst, 0.0) > 0.0:
            return None

    return worst
