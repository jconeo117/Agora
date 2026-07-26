"""Tests de la deliberación."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import (
    appeal,
    candidates,
    critical_need,
    current_intent,
    decide,
    need_weights,
    taste_multipliers,
    urgency,
)
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TasteSpec
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


# --- pesos de personalidad ---------------------------------------------------


def test_trait_intensity_acts_as_exponent() -> None:
    """Intensidad 0 neutraliza, 1 aplica entero, -1 invierte exactamente."""
    pack = world_pack()

    def weight_for(intensity: float) -> float:
        spec = pack.agent_by_id[AG1].model_copy(update={"traits": {"t1": intensity}})
        return need_weights(pack, spec)[N1]

    base = pack.need_by_id[N1].base_weight
    assert weight_for(0.0) == pytest.approx(base)
    assert weight_for(1.0) == pytest.approx(base * 2.0)
    assert weight_for(-1.0) == pytest.approx(base * 0.5)
    assert weight_for(0.5) == pytest.approx(base * 2.0**0.5)


def test_tastes_compose_by_target() -> None:
    """Ojo: `model_copy(update=...)` NO revalida, así que hay que pasar el
    `TasteSpec` ya construido y no un dict crudo."""
    pack = world_pack()
    spec = pack.agent_by_id[AG1].model_copy(
        update={"tastes": (TasteSpec(target=P1, multiplier=1.5),)}
    )
    assert taste_multipliers(spec)["p1"] == pytest.approx(1.5)


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


def test_appeal_is_zero_when_the_need_is_satisfied() -> None:
    world = world_at(P1, need=1.0)
    pack = world.pack
    weights = need_weights(pack, pack.agent_by_id[AG1])
    assert appeal(pack, world.agents[AG1], pack.action_by_id[CON_AFF], weights) == 0.0


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
        return [
            (d.action, d.place)
            for d in (decide(world, world.agents[AG1]) for _ in range(30))
            if d is not None
        ]

    assert run() == run()


def test_pool_of_one_is_pure_argmax() -> None:
    """candidate_pool = 1 desactiva el azar: siempre la mejor opción."""
    world = world_at(P2, need=0.05, tuning={"candidate_pool": 1})
    picks = {decide(world, world.agents[AG1]) for _ in range(20)}
    assert len(picks) == 1


def test_larger_pool_produces_variety() -> None:
    """Con necesidades llenas todo empata, y el sorteo debe notarse."""
    world = world_at(P1, need=1.0, tuning={"candidate_pool": 3, "temperature": 1.0})
    picks = {decide(world, world.agents[AG1]) for _ in range(40)}
    assert len(picks) > 1


def test_ties_break_towards_the_closer_option() -> None:
    """Todo empatado a 0: el agente hace algo aquí en vez de irse de viaje."""
    world = world_at(P1, need=1.0, tuning={"candidate_pool": 1})
    chosen = decide(world, world.agents[AG1])
    assert chosen is not None
    assert chosen.travel_ticks == 0


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


def test_threshold_zero_disables_interruptions() -> None:
    world = world_at(P1, need=0.0, tuning={"critical_need_threshold": 0.0})
    world.agents[AG1].busy = PerformingAction(action=LIBRE, ticks_remaining=5)
    assert critical_need(world, world.agents[AG1]) is None
