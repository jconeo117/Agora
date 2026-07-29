"""Tests del desgaste cognitivo: el mismo agente decide peor cuando está mal.

No es una emoción ni un rasgo. Es una tercera capa sobre el temperamento —
mundo * rasgos * estado — y produce los "días malos" sin tocar la personalidad.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import candidates
from agora.engine.disposition import compose_temperament, compute_strain
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation

CANSA = NeedId("cansa")
NEUTRA = NeedId("neutra")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
LEJOS = ActionId("act_lejos")


def strain_pack(**overrides: Any) -> ContentPack:
    """`cansa` desgasta; `neutra` no. `act_lejos` solo existe en p2, a 4 ticks."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {
                "id": "cansa",
                "label": "cansa",
                "decay_per_tick": 0.01,
                "urgency_exponent": 2.0,
                "strain_weight": 1.0,
            },
            {
                "id": "neutra",
                "label": "neutra",
                "decay_per_tick": 0.01,
                "urgency_exponent": 2.0,
            },
        ],
        "actions": [
            {
                "id": "act_lejos",
                "label": "act_lejos",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"neutra": 1.0},
                "effects": {"neutra": 0.5},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 4}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 4}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {
            "temperature": 0.10,
            "travel_discount": 0.90,
            "critical_need_threshold": 0.0,
            "strain_multipliers": {"temperature": 2.2, "travel_discount": 0.85},
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- la medida ---------------------------------------------------------------


def test_full_needs_mean_no_strain() -> None:
    pack = strain_pack()
    assert compute_strain(pack, {CANSA: 1.0, NEUTRA: 1.0}) == 0.0


def test_empty_needs_mean_maximum_strain() -> None:
    pack = strain_pack()
    assert compute_strain(pack, {CANSA: 0.0, NEUTRA: 0.0}) == pytest.approx(1.0)


def test_only_the_marked_needs_contribute() -> None:
    """El dinero aprieta pero no te vuelve torpe."""
    pack = strain_pack()
    assert compute_strain(pack, {CANSA: 1.0, NEUTRA: 0.0}) == 0.0


def test_strain_reuses_the_urgency_curve() -> None:
    """Convexa, no lineal, y no es cosmético.

    Con desgaste lineal un mundo sano —necesidades en torno a 0.55— daría 0.45:
    todos permanentemente medio rotos y el mecanismo sin recorrido. Con la curva
    da ~0.20, y el desgaste solo aparece cuando algo va mal de verdad.
    """
    pack = strain_pack()
    assert compute_strain(pack, {CANSA: 0.5, NEUTRA: 0.5}) == pytest.approx(0.25)


def test_a_pack_without_strain_weights_disables_the_mechanism() -> None:
    pack = strain_pack(
        needs=[
            {"id": "cansa", "label": "c", "decay_per_tick": 0.01},
            {"id": "neutra", "label": "n", "decay_per_tick": 0.01},
        ]
    )
    assert compute_strain(pack, {CANSA: 0.0, NEUTRA: 0.0}) == 0.0


# --- la tercera capa del temperamento ----------------------------------------


def test_strain_makes_decisions_sloppier() -> None:
    pack = strain_pack()
    entero = compose_temperament(pack, {}, strain=0.0)
    roto = compose_temperament(pack, {}, strain=1.0)

    assert entero.temperature == pytest.approx(0.10)
    assert roto.temperature == pytest.approx(0.22)


def test_strain_makes_distance_weigh_more() -> None:
    pack = strain_pack()
    entero = compose_temperament(pack, {}, strain=0.0)
    roto = compose_temperament(pack, {}, strain=1.0)
    assert roto.travel_discount < entero.travel_discount


def test_the_three_layers_compose() -> None:
    """mundo * rasgos * estado. Un mundo caro, alguien arraigado, y agotado."""
    pack = strain_pack(
        traits=[
            {
                "id": "arraigo",
                "label": "arraigo",
                "temperament_multipliers": {"travel_discount": 0.8},
            }
        ]
    )
    solo_mundo = compose_temperament(pack, {}, strain=0.0)
    arraigado = {TraitId("arraigo"): 1.0}
    con_rasgo = compose_temperament(pack, arraigado, strain=0.0)
    con_todo = compose_temperament(pack, arraigado, strain=1.0)

    assert con_todo.travel_discount < con_rasgo.travel_discount < solo_mundo.travel_discount
    assert con_todo.travel_discount == pytest.approx(0.90 * 0.8 * 0.85)


def test_the_bounds_still_hold_with_strain() -> None:
    """El acotado protege igual venga el factor de un rasgo o del estado."""
    pack = strain_pack(
        tuning={
            "travel_discount": 0.99,
            "critical_need_threshold": 0.9,
            "strain_multipliers": {"travel_discount": 3.0, "critical_need_threshold": 3.0},
        }
    )
    roto = compose_temperament(pack, {}, strain=1.0)
    assert roto.travel_discount == 1.0
    assert roto.critical_need_threshold == 1.0


# --- integración -------------------------------------------------------------


def test_a_worn_out_agent_discounts_the_far_option_harder() -> None:
    """Misma necesidad, mismo sitio, distinto estado."""

    def utility(cansa: float) -> float:
        world = WorldState.new(strain_pack(), seed=1)
        agent = world.agents[AG1]
        agent.needs[CANSA] = cansa
        agent.needs[NEUTRA] = 0.3
        agent.refresh_state(world.pack)
        return next(d for d in candidates(world, agent) if d.action == LEJOS).utility

    assert utility(cansa=0.05) < utility(cansa=1.0)


def test_the_state_is_refreshed_every_tick() -> None:
    """Si `refresh_state` no se llamara, el temperamento reflejaría el estado
    del tick anterior — y el umbral crítico sale de ahí."""
    sim = Simulation(strain_pack(), seed=1)
    agent = sim.state.agents[AG1]
    agent.needs[CANSA] = 1.0
    sim.tick()
    fresco = agent.strain

    agent.needs[CANSA] = 0.05
    sim.tick()
    assert agent.strain > fresco


def test_strain_moves_over_a_run() -> None:
    sim = Simulation(strain_pack(), seed=1)
    visto = set()
    for _ in range(200):
        sim.tick()
        visto.add(round(sim.state.agents[AG1].strain, 3))
    assert len(visto) > 5, "el desgaste debería variar a lo largo de una corrida"
