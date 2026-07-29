"""Tests de hastío y novedad.

El problema que motiva el módulo: nada penalizaba repetir. Linda descansaba en
casa 2.29 veces al día porque la siesta rendía más por tick que dormir y nada
la cansaba.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import candidates, novelty
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, WorldState
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
CANSA = ActionId("act_cansa")
ETERNA = ActionId("act_eterna")


def bored_pack(**overrides: Any) -> ContentPack:
    """`act_cansa` hastía; `act_eterna` no. Ambas dan lo mismo."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01}],
        "actions": [
            {
                "id": "act_cansa",
                "label": "act_cansa",
                "duration_ticks": 2,
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.5},
                "saturation_gain": 0.40,
            },
            {
                "id": "act_eterna",
                "label": "act_eterna",
                "duration_ticks": 2,
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.5},
            },
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"candidate_pool": 1, "critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agent() -> AgentState:
    return AgentState(spec_id=AG1, at=P1, needs={N1: 0.5})


# --- la fórmula --------------------------------------------------------------


def test_something_never_done_is_fully_novel() -> None:
    assert novelty(agent(), CANSA, weight=0.6) == 1.0


def test_novelty_falls_with_saturation() -> None:
    a = agent()
    a.saturation[CANSA] = 0.5
    assert novelty(a, CANSA, weight=0.6) == pytest.approx(0.7)


def test_novelty_never_reaches_zero() -> None:
    """El suelo es `1 - peso`. Sin él, un agente harto de comer se dejaría
    morir de hambre antes que repetir."""
    a = agent()
    a.saturation[CANSA] = 1.0
    assert novelty(a, CANSA, weight=0.6) == pytest.approx(0.4)


def test_weight_zero_disables_the_mechanism() -> None:
    a = agent()
    a.saturation[CANSA] = 1.0
    assert novelty(a, CANSA, weight=0.0) == 1.0


# --- acumulación y olvido ----------------------------------------------------


def test_saturation_accumulates_and_clamps() -> None:
    a = agent()
    for _ in range(5):
        a.saturate(CANSA, 0.4)
    assert a.saturation[CANSA] == 1.0


def test_zero_gain_leaves_no_trace() -> None:
    """Las acciones que no cansan ni siquiera entran en el diccionario."""
    a = agent()
    a.saturate(ETERNA, 0.0)
    assert a.saturation == {}


def test_recovery_forgets_what_reaches_zero() -> None:
    """Mantiene el diccionario del tamaño de lo que hace últimamente, no de
    todo lo que ha hecho nunca."""
    a = agent()
    a.saturate(CANSA, 0.10)
    a.recover_novelty(0.04)
    assert a.saturation[CANSA] == pytest.approx(0.06)
    a.recover_novelty(0.10)
    assert CANSA not in a.saturation


def test_recovery_rate_zero_freezes_the_boredom() -> None:
    a = agent()
    a.saturate(CANSA, 0.4)
    a.recover_novelty(0.0)
    assert a.saturation[CANSA] == pytest.approx(0.4)


# --- efecto en la decisión ---------------------------------------------------


def utility_of(world: WorldState, action: ActionId) -> float:
    return next(d.utility for d in candidates(world, world.agents[AG1]) if d.action == action)


def test_boredom_lowers_the_utility_of_repeating() -> None:
    world = WorldState.new(bored_pack(), seed=1)
    world.agents[AG1].needs[N1] = 0.3
    fresca = utility_of(world, CANSA)

    world.agents[AG1].saturate(CANSA, 0.8)
    assert utility_of(world, CANSA) < fresca


def test_boredom_flips_the_choice_towards_the_alternative() -> None:
    """Dos acciones idénticas: solo las distingue el hastío."""
    world = WorldState.new(bored_pack(), seed=1)
    world.agents[AG1].needs[N1] = 0.3
    assert utility_of(world, CANSA) == pytest.approx(utility_of(world, ETERNA))

    world.agents[AG1].saturate(CANSA, 0.9)
    assert utility_of(world, ETERNA) > utility_of(world, CANSA)


def test_boredom_does_not_touch_the_cost_side() -> None:
    """La novedad multiplica el beneficio, no el neto: el hastío quita ganas de
    hacer algo, no cambia lo que cuesta."""
    pack = bored_pack(
        needs=[
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.01},
        ],
        actions=[
            {
                "id": "act_cansa",
                "label": "act_cansa",
                "duration_ticks": 2,
                "satisfies": {"n1": 1.0},
                "costs": {"n2": 0.5},
                "effects": {"n1": 0.5, "n2": -0.1},
                "saturation_gain": 0.4,
            },
            {"id": "act_eterna", "label": "act_eterna", "duration_ticks": 2},
        ],
    )
    world = WorldState.new(pack, seed=1)
    a = world.agents[AG1]
    a.needs[N1] = 1.0  # sin beneficio posible
    a.needs[NeedId("n2")] = 0.2

    sin_hastio = utility_of(world, CANSA)
    a.saturate(CANSA, 1.0)
    assert utility_of(world, CANSA) == pytest.approx(sin_hastio)


# --- integración -------------------------------------------------------------


def test_boredom_builds_up_over_a_run() -> None:
    sim = Simulation(bored_pack(), seed=1)
    sim.run(60)
    assert sim.state.agents[AG1].saturation.get(CANSA, 0.0) > 0.0


def test_only_completed_actions_leave_boredom() -> None:
    """Uno se cansa de lo que hizo, no de lo que intentó."""
    sim = Simulation(bored_pack(), seed=1)
    sim.run(40)
    completadas = [
        e for e in sim.log.of_kind(EventKind.ACTION_COMPLETED) if str(e.action) == "act_cansa"
    ]
    assert completadas, "el escenario debería completar la acción que cansa"
    assert sim.state.agents[AG1].saturation.get(CANSA, 0.0) > 0.0
