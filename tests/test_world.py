"""Tests del tick loop."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import PerformingAction, Traveling
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
P3 = PlaceId("p3")
CON_AFF = ActionId("act_con_aff")
LIBRE = ActionId("act_libre")


def line_pack(**overrides: Any) -> ContentPack:
    """Tres lugares en línea: p3 -- p2 -- p1. La affordance solo está en p1."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01}],
        "actions": [
            {
                "id": "act_con_aff",
                "label": "act_con_aff",
                "duration_ticks": 3,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.9},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 2},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 2}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 2, "p3": 1}},
            {"id": "p3", "label": "p3", "neighbors": {"p2": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"candidate_pool": 1, "critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def sim_with(need: float, **overrides: Any) -> Simulation:
    sim = Simulation(line_pack(**overrides), seed=5)
    sim.state.agents[AG1].needs[N1] = need
    return sim


def kinds(sim: Simulation) -> list[EventKind]:
    return [event.kind for event in sim.log]


# --- acciones ----------------------------------------------------------------


def test_action_completes_after_exactly_its_duration() -> None:
    """`act_con_aff` dura 3 ticks. Empieza en el tick 1, termina en el 4."""
    sim = sim_with(need=0.1)
    sim.tick()
    assert isinstance(sim.state.agents[AG1].busy, PerformingAction)

    for _ in range(2):
        sim.tick()
    assert not any(e.kind is EventKind.ACTION_COMPLETED for e in sim.log)

    sim.tick()
    completed = [e for e in sim.log if e.kind is EventKind.ACTION_COMPLETED]
    assert len(completed) == 1
    assert completed[0].tick == 4


def test_effects_are_applied_on_completion() -> None:
    sim = sim_with(need=0.1)
    sim.run(4)
    # 0.1 + 0.9 de efecto, menos 0.01 de decay por cada uno de los 4 ticks.
    assert sim.state.agents[AG1].needs[N1] == pytest.approx(0.96)


def test_agent_starts_something_new_the_same_tick_it_finishes() -> None:
    """Sin esto se perdería un tick por acción, y con acciones cortas el agente
    pasaría la mitad de su vida ocioso."""
    sim = sim_with(need=0.1)
    sim.run(4)
    assert sim.state.agents[AG1].busy is not None


# --- viaje -------------------------------------------------------------------


FAR_AWAY: dict[str, Any] = {
    "agents": [{"id": "ag1", "label": "ag1", "home": "p3", "start_at": "p3"}]
}


def test_travel_reaches_destination_in_the_expected_ticks() -> None:
    """Desde p3, la comida está en p1: 1 tick hasta p2 y 2 más hasta p1."""
    sim = sim_with(need=0.05, **FAR_AWAY)
    sim.tick()
    busy = sim.state.agents[AG1].busy
    assert isinstance(busy, Traveling)
    assert busy.destination == P1

    sim.run(3)
    assert sim.state.agents[AG1].at == P1


def test_multi_leg_travel_emits_one_arrival_at_the_destination() -> None:
    sim = sim_with(need=0.05, **FAR_AWAY)
    sim.run(4)
    arrivals = [e for e in sim.log if e.kind is EventKind.TRAVEL_ARRIVED]
    assert len(arrivals) == 1
    assert arrivals[0].place == P1


def test_arriving_honours_the_intent_without_redeliberating() -> None:
    """Se viajó A POR ALGO. Al llegar se hace, no se vuelve a pensar."""
    sim = sim_with(need=0.05, **FAR_AWAY)
    sim.run(4)
    busy = sim.state.agents[AG1].busy
    assert isinstance(busy, PerformingAction)
    assert busy.action == CON_AFF


# --- interrupción ------------------------------------------------------------


def test_critical_need_aborts_an_unrelated_action() -> None:
    """Se fuerza la ocupación en vez de dejar que el agente la elija.

    El test trata sobre la interrupción, no sobre la selección. Montarlo sobre
    lo que el agente decidiría lo ata a los desempates de `decide`, y entonces
    falla cada vez que se toca la calibración por motivos que no tienen nada
    que ver con lo que se quiere comprobar.
    """
    sim = sim_with(need=1.0, tuning={"candidate_pool": 1, "critical_need_threshold": 0.5})

    agent = sim.state.agents[AG1]
    agent.busy = PerformingAction(action=LIBRE, ticks_remaining=40)
    agent.needs[N1] = 0.2  # cae en picado y `act_libre` no lo atiende
    sim.tick()

    aborted = [e for e in sim.log if e.kind is EventKind.ACTION_ABORTED]
    assert len(aborted) == 1
    assert aborted[0].action == LIBRE


def test_interruption_forces_a_different_action() -> None:
    """Una interrupción tiene que CAMBIAR lo que se hace.

    Sin `must_address`, el agente abandona por hambre, vuelve a deliberar, y
    elige otra vez lo mismo porque seguía siendo lo mejor puntuado. Abandona y
    reinicia idéntico cada tick, para siempre.
    """
    sim = sim_with(need=1.0, tuning={"candidate_pool": 1, "critical_need_threshold": 0.5})
    agent = sim.state.agents[AG1]
    agent.busy = PerformingAction(action=LIBRE, ticks_remaining=40)
    agent.needs[N1] = 0.2
    sim.tick()

    busy = agent.busy
    assert isinstance(busy, PerformingAction | Traveling)
    started = busy.action if isinstance(busy, PerformingAction) else busy.intent
    assert started == CON_AFF, "tras abandonar debe elegir algo que atienda la urgencia"


def test_agents_complete_far_more_than_they_abort() -> None:
    """Prueba de humo contra el dithering, sobre una corrida larga.

    Es el test que habría cazado el bucle abandonar/reiniciar de un vistazo: un
    agente atrapado en él genera cientos de abandonos y cero finalizaciones.
    """
    sim = sim_with(need=0.5, tuning={"candidate_pool": 1, "critical_need_threshold": 0.3})
    sim.run(500)
    completed = len([e for e in sim.log if e.kind is EventKind.ACTION_COMPLETED])
    aborted = len([e for e in sim.log if e.kind is EventKind.ACTION_ABORTED])
    assert completed > 20
    assert aborted <= completed


def test_need_critical_is_emitted_once_on_crossing_not_every_tick() -> None:
    sim = sim_with(need=0.16, tuning={"candidate_pool": 1, "critical_need_threshold": 0.15})
    sim.run(10)
    assert len([e for e in sim.log if e.kind is EventKind.NEED_CRITICAL]) == 1


# --- encuentros --------------------------------------------------------------


def two_agents_pack() -> dict[str, Any]:
    return {
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1"},
        ]
    }


def test_encounter_is_emitted_once_while_agents_stay_together() -> None:
    sim = Simulation(line_pack(**two_agents_pack()), seed=5)
    sim.run(20)
    encounters = [e for e in sim.log if e.kind is EventKind.ENCOUNTER]
    assert len(encounters) == 1
    assert {encounters[0].actor, encounters[0].subject} == {AG1, AG2}


def test_encounter_is_indexed_for_both_participants() -> None:
    sim = Simulation(line_pack(**two_agents_pack()), seed=5)
    sim.run(5)
    assert any(e.kind is EventKind.ENCOUNTER for e in sim.log.by_actor(AG1))
    assert any(e.kind is EventKind.ENCOUNTER for e in sim.log.by_actor(AG2))


# --- salud general -----------------------------------------------------------


def test_nobody_ever_stalls_with_a_validated_pack() -> None:
    sim = sim_with(need=0.5)
    sim.run(400)
    assert EventKind.IDLE_STALLED not in kinds(sim)


def test_needs_stay_within_bounds_over_a_long_run() -> None:
    sim = sim_with(need=0.5)
    sim.run(400)
    assert all(0.0 <= value <= 1.0 for value in sim.state.agents[AG1].needs.values())
