"""Tests del coste de cambio: lo invertido protege frente a la interrupción.

Antes de esto, el 23 % de lo empezado se abandonaba a medias, y seis veces por
semana alguien tiraba algo que llevaba al 80 %.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import commitment, critical_need
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import PerformingAction, Traveling, WorldState

N1 = NeedId("n1")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
P3 = PlaceId("p3")
LARGA = ActionId("act_larga")
UTIL = ActionId("act_util")


def line_pack(**overrides: Any) -> ContentPack:
    """p1 -- p2 -- p3, dos ticks por tramo. `act_util` solo existe en p3."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01}],
        "actions": [
            {"id": "act_larga", "label": "act_larga", "duration_ticks": 20},
            {
                "id": "act_util",
                "label": "act_util",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.8},
            },
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 2}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 2, "p3": 2}},
            {"id": "p3", "label": "p3", "affordances": ["aff"], "neighbors": {"p2": 2}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"critical_need_threshold": 0.20, "switch_cost": 0.8},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def world_with(**overrides: Any) -> WorldState:
    return WorldState.new(line_pack(**overrides), seed=1)


# --- la medida del compromiso ------------------------------------------------


def test_an_idle_agent_has_nothing_invested() -> None:
    world = world_with()
    assert commitment(world, world.agents[AG1]) == 0.0


def test_action_commitment_is_its_progress() -> None:
    world = world_with()
    agent = world.agents[AG1]

    agent.busy = PerformingAction(action=LARGA, ticks_remaining=20)
    assert commitment(world, agent) == pytest.approx(0.0)
    agent.busy = PerformingAction(action=LARGA, ticks_remaining=10)
    assert commitment(world, agent) == pytest.approx(0.5)
    agent.busy = PerformingAction(action=LARGA, ticks_remaining=1)
    assert commitment(world, agent) == pytest.approx(0.95)


def test_travel_commitment_spans_the_whole_journey_not_the_leg() -> None:
    """De p1 a p3 son 4 ticks. Al llegar a p2 lleva la mitad andada, aunque el
    tramo nuevo esté recién empezado.

    Medir por tramo haría que quien lleva cuatro ticks caminando pareciera
    recién salido de casa cada vez que pisa un cruce.
    """
    world = world_with()
    agent = world.agents[AG1]
    agent.at = P2
    agent.busy = Traveling(
        destination=P3, intent=UTIL, next_hop=P3, ticks_remaining=2, total_ticks=4
    )
    assert commitment(world, agent) == pytest.approx(0.5)

    agent.busy = Traveling(
        destination=P3, intent=UTIL, next_hop=P3, ticks_remaining=1, total_ticks=4
    )
    assert commitment(world, agent) == pytest.approx(0.75)


def test_travel_without_a_recorded_journey_counts_as_uncommitted() -> None:
    world = world_with()
    agent = world.agents[AG1]
    agent.busy = Traveling(destination=P2, intent=UTIL, next_hop=P2, ticks_remaining=1)
    assert commitment(world, agent) == 0.0


# --- efecto sobre la interrupción --------------------------------------------


def interrupts_at(progress_ticks: int, need: float, **tuning: float) -> bool:
    world = world_with(tuning={"critical_need_threshold": 0.20, **tuning})
    agent = world.agents[AG1]
    agent.needs[N1] = need
    agent.busy = PerformingAction(action=LARGA, ticks_remaining=progress_ticks)
    return critical_need(world, agent) is not None


def test_a_barely_started_action_is_interrupted() -> None:
    assert interrupts_at(progress_ticks=20, need=0.15, switch_cost=0.8)


def test_an_almost_finished_action_survives_the_same_urgency() -> None:
    """Mismo estado de necesidad, distinto momento. Al 95 % el umbral efectivo
    es 0.20 * (1 - 0.95*0.8) = 0.048, y 0.15 ya no cuenta como emergencia."""
    assert not interrupts_at(progress_ticks=1, need=0.15, switch_cost=0.8)


def test_a_catastrophe_still_cuts_through_at_the_end() -> None:
    """El compromiso sube el listón, no lo elimina."""
    assert interrupts_at(progress_ticks=1, need=0.01, switch_cost=0.8)


def test_switch_cost_zero_restores_the_old_behaviour() -> None:
    assert interrupts_at(progress_ticks=1, need=0.15, switch_cost=0.0)


def test_more_switch_cost_protects_more() -> None:
    """A medio camino: con coste 0.2 el umbral queda en 0.18 y 0.13 interrumpe;
    con 0.9 queda en 0.11 y ya no."""
    a_medias = 10
    assert interrupts_at(progress_ticks=a_medias, need=0.13, switch_cost=0.2)
    assert not interrupts_at(progress_ticks=a_medias, need=0.13, switch_cost=0.9)
