"""Tests de la deliberación."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import (
    benefit,
    candidates,
    cost,
    critical_need,
    current_intent,
    decide,
    urgency,
)
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState

N1 = NeedId("n1")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
CON_AFF = ActionId("act_con_aff")
LIBRE = ActionId("act_libre")


def world_pack(**overrides: Any) -> ContentPack:
    """Pack de dos lugares: `aff` solo se ofrece en p1, a 1 tick de p2."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01, "urgency_exponent": 2.0}],
        "traits": [{"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 2.0}}],
        "actions": [
            {
                "id": "act_con_aff",
                "label": "act_con_aff",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.8},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p2"}],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def world_at(place: PlaceId, need: float, **overrides: Any) -> WorldState:
    world = WorldState.new(world_pack(**overrides), seed=7)
    agent = world.agents[AG1]
    agent.at = place
    agent.needs[N1] = need
    return world


# --- curva de urgencia -------------------------------------------------------


def test_urgency_is_zero_when_the_need_is_full() -> None:
    assert urgency(1.0, 2.0) == 0.0


def test_urgency_curve_is_convex_not_linear() -> None:
    """Con exponente > 1, media necesidad apremia MENOS de la mitad. Es lo que
    impide que el agente atienda cinco cosas a medias."""
    assert urgency(0.5, 2.0) == pytest.approx(0.25)
    assert urgency(0.5, 1.0) == pytest.approx(0.5)


# --- candidatos --------------------------------------------------------------


def test_candidates_include_remote_places() -> None:
    """El agente está en p2; la acción con affordance solo existe en p1."""
    world = world_at(P2, need=0.2)
    options = candidates(world, world.agents[AG1])
    assert any(d.action == CON_AFF and d.place == P1 and d.travel_ticks == 1 for d in options)


def test_candidates_exclude_actions_whose_affordance_is_absent() -> None:
    world = world_at(P2, need=0.2)
    options = candidates(world, world.agents[AG1])
    assert not any(d.action == CON_AFF and d.place == P2 for d in options)


def test_travel_discount_lowers_the_utility_of_distant_options() -> None:
    """Misma acción, mismo estado interno: solo cambia dónde está el agente."""
    here = world_at(P1, need=0.2)
    away = world_at(P2, need=0.2)

    def utility_of_target(world: WorldState) -> float:
        return next(
            d.utility
            for d in candidates(world, world.agents[AG1])
            if d.action == CON_AFF and d.place == P1
        )

    assert utility_of_target(away) < utility_of_target(here)
    assert utility_of_target(away) == pytest.approx(utility_of_target(here) * 0.95)


def test_taste_multiplies_the_final_utility() -> None:
    neutral = world_at(P1, need=0.2)
    liked = world_at(
        P1,
        need=0.2,
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "tastes": [{"target": "act_con_aff", "multiplier": 2.0}],
            }
        ],
    )

    def utility_of_target(world: WorldState) -> float:
        return next(
            d.utility for d in candidates(world, world.agents[AG1]) if d.action == CON_AFF
        )

    assert utility_of_target(liked) == pytest.approx(utility_of_target(neutral) * 2.0)


def test_benefit_is_zero_when_the_need_is_satisfied() -> None:
    world = world_at(P1, need=1.0)
    agent = world.agents[AG1]
    action = world.pack.action_by_id[CON_AFF]
    assert benefit(world.pack, agent, action, agent.need_weights) == 0.0


# --- costes ------------------------------------------------------------------


def costly_pack(**overrides: Any) -> dict[str, Any]:
    """`act_con_aff` gana n1 pero gasta n2. `act_libre` no hace ni una cosa
    ni la otra."""
    return {
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "urgency_exponent": 2.0},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.01, "urgency_exponent": 2.0},
        ],
        "traits": [],
        "actions": [
            {
                "id": "act_con_aff",
                "label": "act_con_aff",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "costs": {"n2": 0.8},
                "effects": {"n1": 0.8, "n2": -0.2},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        **overrides,
    }


def test_cost_grows_as_the_spent_need_runs_out() -> None:
    """Gastar duele más cuando queda poco. Es lo que hace que un agente sin
    dinero deje de salir sin ninguna regla que se lo diga."""
    world = WorldState.new(world_pack(**costly_pack()), seed=7)
    pack, agent = world.pack, world.agents[AG1]
    action = pack.action_by_id[CON_AFF]

    agent.needs[NeedId("n2")] = 0.9
    holgado = cost(pack, agent, action, agent.need_weights)
    agent.needs[NeedId("n2")] = 0.1
    apurado = cost(pack, agent, action, agent.need_weights)

    assert apurado > holgado * 3


def test_an_expensive_action_can_reach_negative_utility() -> None:
    """La necesidad que gana está llena y la que gasta, vacía: mala idea."""
    world = WorldState.new(world_pack(**costly_pack()), seed=7)
    agent = world.agents[AG1]
    agent.needs[N1] = 1.0
    agent.needs[NeedId("n2")] = 0.05

    chosen = next(d for d in candidates(world, agent) if d.action == CON_AFF)
    assert chosen.utility < 0.0


def test_the_free_fallback_wins_when_everything_costs_too_much() -> None:
    world = WorldState.new(world_pack(**costly_pack()), seed=7)
    agent = world.agents[AG1]
    agent.needs[N1] = 0.9
    agent.needs[NeedId("n2")] = 0.02

    chosen = decide(world, agent)
    assert chosen is not None
    assert chosen.action == LIBRE


def test_loss_aversion_scales_the_cost_term() -> None:
    def utility_with(aversion: float) -> float:
        world = WorldState.new(
            world_pack(**costly_pack(tuning={"loss_aversion": aversion})), seed=7
        )
        agent = world.agents[AG1]
        agent.needs[N1] = 0.4
        agent.needs[NeedId("n2")] = 0.3
        return next(d for d in candidates(world, agent) if d.action == CON_AFF).utility

    assert utility_with(0.0) > utility_with(1.0) > utility_with(2.0)


def test_travel_discount_does_not_soften_the_cost() -> None:
    """Si el descuento se aplicara al neto, una opción cara y lejana parecería
    menos cara. El precio se paga entero al llegar."""
    pack = world_pack(**costly_pack())
    action = pack.action_by_id[CON_AFF]

    near = WorldState.new(pack, seed=7)
    near.agents[AG1].needs[N1] = 0.3
    near.agents[AG1].needs[NeedId("n2")] = 0.3

    far = WorldState.new(pack, seed=7)
    far.agents[AG1].at = P2
    far.agents[AG1].needs[N1] = 0.3
    far.agents[AG1].needs[NeedId("n2")] = 0.3

    price = cost(pack, near.agents[AG1], action, near.agents[AG1].need_weights)
    near_utility = next(d for d in candidates(near, near.agents[AG1]) if d.action == CON_AFF)
    far_utility = next(d for d in candidates(far, far.agents[AG1]) if d.action == CON_AFF)

    # El beneficio se descuenta; el coste no. La diferencia entre ambas
    # utilidades es exactamente la parte descontada del beneficio.
    assert far_utility.utility < near_utility.utility
    assert (near_utility.utility + price) * 0.95 == pytest.approx(far_utility.utility + price)


# --- elección ----------------------------------------------------------------


def test_decide_targets_the_place_that_solves_the_need() -> None:
    world = world_at(P2, need=0.05)
    chosen = decide(world, world.agents[AG1])
    assert chosen is not None
    assert chosen.action == CON_AFF
    assert chosen.place == P1
    assert chosen.travel_ticks == 1


def test_decide_is_reproducible_with_the_same_seed() -> None:
    def run() -> list[tuple[ActionId, PlaceId]]:
        world = world_at(P2, need=0.4)
        chosen: list[tuple[ActionId, PlaceId]] = []
        for tick in range(30):
            world.tick = tick
            d = decide(world, world.agents[AG1])
            if d is not None:
                chosen.append((d.action, d.place))
        return chosen

    assert run() == run()


def test_deliberating_twice_in_the_same_tick_gives_the_same_answer() -> None:
    """El sorteo es función pura de (semilla, agente, tick).

    No es un efecto secundario: es la propiedad que permite avanzar una parte
    del mundo sin haber avanzado el resto. Un agente decide una vez por tick, y
    preguntarle otra vez no le hace cambiar de idea.
    """
    world = world_at(P1, need=1.0, tuning={"candidate_pool": 3, "temperature": 1.0})
    agent = world.agents[AG1]
    assert len({decide(world, agent) for _ in range(20)}) == 1


def test_the_draw_does_not_depend_on_who_deliberated_before() -> None:
    """Con un generador único consumido en orden, la decisión de un agente
    dependería de cuántos sorteos hubo antes en el mismo tick. Aquí no."""
    solo = world_at(P1, need=1.0, tuning={"candidate_pool": 3, "temperature": 1.0})
    acompanado = world_at(P1, need=1.0, tuning={"candidate_pool": 3, "temperature": 1.0})

    # Alguien consume aleatoriedad antes, en el mismo tick y el mismo mundo.
    acompanado.rng.stream("decide", "otro", acompanado.tick).random()

    assert decide(solo, solo.agents[AG1]) == decide(acompanado, acompanado.agents[AG1])


def test_pool_of_one_is_pure_argmax() -> None:
    """candidate_pool = 1 desactiva el azar: siempre la mejor opción."""
    world = world_at(P2, need=0.05, tuning={"candidate_pool": 1})
    picks = {decide(world, world.agents[AG1]) for _ in range(20)}
    assert len(picks) == 1


def test_larger_pool_produces_variety_across_ticks() -> None:
    """Con necesidades llenas todo empata, y el sorteo debe notarse.

    La variedad se mide entre ticks distintos, no repitiendo la pregunta: dentro
    de un mismo tick la decisión está fijada por construcción.
    """
    world = world_at(P1, need=1.0, tuning={"candidate_pool": 3, "temperature": 1.0})
    picks = set()
    for tick in range(40):
        world.tick = tick
        picks.add(decide(world, world.agents[AG1]))
    assert len(picks) > 1


def test_ties_break_towards_the_closer_option() -> None:
    """Todo empatado a 0: el agente hace algo aquí en vez de irse de viaje."""
    world = world_at(P1, need=1.0, tuning={"candidate_pool": 1})
    chosen = decide(world, world.agents[AG1])
    assert chosen is not None
    assert chosen.travel_ticks == 0


# --- temperamento: dos personas ante la misma situación ----------------------


def tempered_pack(**overrides: Any) -> dict[str, Any]:
    """`act_con_aff` gana n1 pero gasta n2. Tres rasgos de temperamento puro."""
    data = costly_pack()
    data["traits"] = [
        {
            "id": "impulsividad",
            "label": "impulsividad",
            "temperament_multipliers": {"temperature": 3.0, "loss_aversion": 0.3},
        },
        {
            "id": "aguante",
            "label": "aguante",
            "temperament_multipliers": {"critical_need_threshold": 0.3},
        },
        {
            "id": "arraigo",
            "label": "arraigo",
            "temperament_multipliers": {"travel_discount": 0.6},
        },
    ]
    data.update(overrides)
    return data


def agent_with(traits: dict[str, float], **overrides: Any) -> WorldState:
    data = tempered_pack(**overrides)
    data["agents"] = [
        {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1", "traits": traits}
    ]
    return WorldState.new(world_pack(**data), seed=7)


def test_the_thrifty_and_the_impulsive_price_the_same_action_differently() -> None:
    """Misma acción, mismo estado, distinta persona. Es lo que el paso existe
    para permitir: hoy los diez residentes compartían temperamento."""

    def utility(traits: dict[str, float]) -> float:
        world = agent_with(traits)
        agent = world.agents[AG1]
        agent.needs[N1] = 0.4
        agent.needs[NeedId("n2")] = 0.2  # lo que la acción gasta, escaso
        return next(d for d in candidates(world, agent) if d.action == CON_AFF).utility

    impulsivo = utility({"impulsividad": 1.0})
    calculador = utility({"impulsividad": -1.0})

    assert impulsivo > calculador, "al impulsivo el precio le pesa menos"


def test_the_rooted_agent_discounts_distance_harder() -> None:
    def utility(traits: dict[str, float]) -> float:
        world = agent_with(traits)
        agent = world.agents[AG1]
        agent.at = P2  # la acción útil está en p1, a 1 tick
        agent.needs[N1] = 0.3
        agent.needs[NeedId("n2")] = 0.9
        return next(
            d for d in candidates(world, agent) if d.action == CON_AFF and d.place == P1
        ).utility

    assert utility({"arraigo": 1.0}) < utility({"arraigo": -1.0})


def test_the_stoic_holds_out_longer_before_panicking() -> None:
    """Mismo estado de necesidad; uno lo considera una emergencia y el otro no."""

    def is_urgent(traits: dict[str, float]) -> bool:
        world = agent_with(traits, tuning={"critical_need_threshold": 0.3})
        agent = world.agents[AG1]
        agent.needs[N1] = 0.12
        agent.busy = PerformingAction(action=LIBRE, ticks_remaining=5)
        return critical_need(world, agent) is not None

    assert is_urgent({"aguante": -1.0}) is True
    assert is_urgent({"aguante": 1.0}) is False


def test_the_methodical_agent_wavers_less_than_the_impulsive_one() -> None:
    """La temperatura solo actúa cuando hay diferencias que ignorar.

    Con las necesidades llenas todas las utilidades valen exactamente 0.0, y el
    softmax de valores idénticos es uniforme por baja que sea la temperatura.
    Por eso la prueba usa un estado donde las opciones SÍ se distinguen: ahí es
    donde el carácter decide si se respeta el criterio o no.
    """

    def variety(traits: dict[str, float]) -> int:
        world = agent_with(traits, tuning={"candidate_pool": 3})
        agent = world.agents[AG1]
        # Un ganador claro que ignorar: lo que la acción da escasea y lo que
        # gasta sobra. Con las opciones casi empatadas, la temperatura no
        # distingue a nadie.
        agent.needs[N1] = 0.1
        agent.needs[NeedId("n2")] = 0.9

        picks = set()
        for tick in range(60):
            world.tick = tick
            picks.add(decide(world, agent))
        return len(picks)

    assert variety({"impulsividad": -1.0}) == 1, "el metódico siempre elige lo mejor"
    assert variety({"impulsividad": 1.0}) > 1, "el impulsivo se desvía"


def test_drift_updates_the_temperament_too() -> None:
    """`temperament` es derivado igual que `need_weights`: si `drift_trait` no
    lo recompusiera, el agente seguiría decidiendo con el carácter de antes."""
    world = agent_with({"impulsividad": 0.0})
    agent = world.agents[AG1]
    antes = agent.temperament.temperature

    agent.drift_trait(world.pack, TraitId("impulsividad"), +1.0)
    assert agent.temperament.temperature > antes


# --- interrupción ------------------------------------------------------------


def test_current_intent_reads_through_both_union_cases() -> None:
    idle = AgentState(spec_id=AG1, at=P1, needs={N1: 0.5})
    assert current_intent(idle) is None

    acting = AgentState(
        spec_id=AG1, at=P1, needs={N1: 0.5},
        busy=PerformingAction(action=LIBRE, ticks_remaining=2),
    )
    assert current_intent(acting) == LIBRE

    traveling = AgentState(
        spec_id=AG1, at=P2, needs={N1: 0.5},
        busy=Traveling(destination=P1, intent=CON_AFF, next_hop=P1, ticks_remaining=1),
    )
    assert current_intent(traveling) == CON_AFF


def test_critical_need_fires_when_below_threshold() -> None:
    world = world_at(P1, need=0.05)
    world.agents[AG1].busy = PerformingAction(action=LIBRE, ticks_remaining=5)
    assert critical_need(world, world.agents[AG1]) == N1


def test_no_interruption_while_already_addressing_the_need() -> None:
    """Nadie abandona la comida por hambre."""
    world = world_at(P1, need=0.05)
    world.agents[AG1].busy = PerformingAction(action=CON_AFF, ticks_remaining=2)
    assert critical_need(world, world.agents[AG1]) is None


def test_no_interruption_while_travelling_towards_the_solution() -> None:
    """El caso que justifica el campo `intent` en Traveling."""
    world = world_at(P2, need=0.05)
    world.agents[AG1].busy = Traveling(
        destination=P1, intent=CON_AFF, next_hop=P1, ticks_remaining=1
    )
    assert critical_need(world, world.agents[AG1]) is None


def test_no_interruption_when_the_action_covers_any_emergency() -> None:
    """Con dos necesidades críticas, ninguna acción puede cubrir las dos.

    Si la regla fuera "interrumpe si esta necesidad concreta no está atendida",
    siempre quedaría una fuera y el agente abandonaría lo que hiciera en cada
    tick. La regla es "interrumpe solo si no atiende NINGUNA".
    """
    world = world_at(
        P1,
        need=0.05,
        needs=[
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.01},
        ],
        traits=[],
        agents=[{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
    )
    agent = world.agents[AG1]
    agent.needs[NeedId("n2")] = 0.02  # también crítica, y CON_AFF no la atiende
    agent.busy = PerformingAction(action=CON_AFF, ticks_remaining=2)

    assert critical_need(world, agent) is None


def test_must_address_restricts_the_choice_to_the_urgent_need() -> None:
    world = world_at(P2, need=0.05)
    chosen = decide(world, world.agents[AG1], must_address=N1)
    assert chosen is not None
    assert world.pack.action_by_id[chosen.action].satisfies.get(N1, 0.0) > 0.0


def test_must_address_falls_back_when_nothing_can_help() -> None:
    """Si ninguna acción atiende la urgencia, decidir libremente es mejor que
    quedarse bloqueado."""
    world = world_at(P1, need=0.05)
    chosen = decide(world, world.agents[AG1], must_address=NeedId("inexistente"))
    assert chosen is not None


def test_threshold_zero_disables_interruptions() -> None:
    world = world_at(P1, need=0.0, tuning={"critical_need_threshold": 0.0})
    world.agents[AG1].busy = PerformingAction(action=LIBRE, ticks_remaining=5)
    assert critical_need(world, world.agents[AG1]) is None
