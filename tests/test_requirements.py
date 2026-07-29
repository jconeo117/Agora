"""Tests de precondiciones de recurso: el "no puedo permitírmelo".

Sin esto, un agente con la despensa a cero cocina igual y el efecto negativo
simplemente se recorta: el ritmo sale plausible pero la restricción no existe,
y ninguna decisión cambia por estar arruinado.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, decide, is_available
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import Traveling, WorldState
from agora.engine.world import Simulation

DINERO = NeedId("dinero")
HAMBRE = NeedId("hambre_test")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
CARA = ActionId("act_cara")
GRATIS = ActionId("act_gratis")


def market_pack(**overrides: Any) -> ContentPack:
    """`act_cara` cuesta dinero y exige tenerlo; `act_gratis` no."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "hambre_test", "label": "h", "decay_per_tick": 0.01},
            {"id": "dinero", "label": "d", "decay_per_tick": 0.001},
        ],
        "actions": [
            {
                "id": "act_cara",
                "label": "act_cara",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "requires": {"dinero": 0.30},
                "satisfies": {"hambre_test": 1.0},
                "costs": {"dinero": 0.5},
                "effects": {"hambre_test": 0.8, "dinero": -0.30},
            },
            {"id": "act_gratis", "label": "act_gratis", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"candidate_pool": 1, "critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def world_with(dinero: float, hambre: float = 0.2) -> WorldState:
    world = WorldState.new(market_pack(), seed=1)
    world.agents[AG1].needs[DINERO] = dinero
    world.agents[AG1].needs[HAMBRE] = hambre
    return world


# --- la puerta ---------------------------------------------------------------


def test_without_the_resource_the_action_is_unavailable() -> None:
    pack = market_pack()
    action, place = pack.action_by_id[CARA], pack.place_by_id[P1]
    assert not is_available(action, place, company=0, needs={DINERO: 0.10})
    assert is_available(action, place, company=0, needs={DINERO: 0.50})


def test_exactly_at_the_threshold_is_enough() -> None:
    pack = market_pack()
    assert is_available(
        pack.action_by_id[CARA], pack.place_by_id[P1], company=0, needs={DINERO: 0.30}
    )


def test_deliberation_does_not_offer_what_cannot_be_paid() -> None:
    pobre = world_with(dinero=0.05)
    assert not any(d.action == CARA for d in candidates(pobre, pobre.agents[AG1]))

    rico = world_with(dinero=0.80)
    assert any(d.action == CARA for d in candidates(rico, rico.agents[AG1]))


def test_the_broke_agent_falls_back_instead_of_stalling() -> None:
    """Sin blanca y con hambre: no se bloquea, hace otra cosa."""
    pobre = world_with(dinero=0.05, hambre=0.05)
    chosen = decide(pobre, pobre.agents[AG1])
    assert chosen is not None
    assert chosen.action == GRATIS


def test_an_urgent_need_does_not_open_the_gate() -> None:
    """La urgencia sube el atractivo, no da crédito. Es una puerta dura, no un
    descuento."""
    desesperado = world_with(dinero=0.05, hambre=0.0)
    assert not any(d.action == CARA for d in candidates(desesperado, desesperado.agents[AG1]))


# --- al llegar ---------------------------------------------------------------


def test_running_out_of_money_in_transit_aborts_on_arrival() -> None:
    """Entre decidir y llegar el dinero se gasta. La puerta se comprueba otra
    vez al llegar, igual que la compañía."""
    sim = Simulation(market_pack(), seed=1)
    agent = sim.state.agents[AG1]
    agent.at = P2
    agent.needs[HAMBRE] = 0.1
    agent.needs[DINERO] = 0.05  # ya no llega
    agent.busy = Traveling(
        destination=P1, intent=CARA, next_hop=P1, ticks_remaining=1, total_ticks=1
    )

    sim.tick()

    abortados = [e for e in sim.log if e.kind is EventKind.ACTION_ABORTED]
    assert len(abortados) == 1
    assert abortados[0].action == CARA


# --- validación --------------------------------------------------------------


def test_a_requirement_below_what_it_spends_is_rejected() -> None:
    """Exigir 0.10 y gastar 0.30 deja pasar a quien tiene 0.15, y el efecto se
    trunca igual. La puerta existiría, dejaría pasar, y el problema seguiría
    ahí disfrazado de resuelto."""
    with pytest.raises(ValidationError, match="consume"):
        market_pack(
            actions=[
                {
                    "id": "act_cara",
                    "label": "x",
                    "duration_ticks": 2,
                    "requires_affordance": "aff",
                    "requires": {"dinero": 0.10},
                    "costs": {"dinero": 0.5},
                    "effects": {"dinero": -0.30},
                },
                {"id": "act_gratis", "label": "act_gratis", "duration_ticks": 1},
            ]
        )


def test_no_requirement_at_all_is_allowed() -> None:
    """Quien no quiera la puerta, que no la declare. El motor no la impone."""
    pack = market_pack(
        actions=[
            {
                "id": "act_cara",
                "label": "x",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "costs": {"dinero": 0.5},
                "effects": {"dinero": -0.30},
            },
            {"id": "act_gratis", "label": "act_gratis", "duration_ticks": 1},
        ]
    )
    assert pack.action_by_id[CARA].requires == {}


def test_a_requirement_on_an_unknown_need_is_rejected() -> None:
    with pytest.raises(ValidationError, match="fantasma"):
        market_pack(
            actions=[
                {
                    "id": "act_cara",
                    "label": "x",
                    "duration_ticks": 2,
                    "requires_affordance": "aff",
                    "requires": {"fantasma": 0.5},
                },
                {"id": "act_gratis", "label": "act_gratis", "duration_ticks": 1},
            ]
        )
