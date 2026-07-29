"""Tests de presencia: compañía como requisito y como alivio.

El bug que motiva el módulo: sin esto, un agente "charla" solo en una plaza
vacía. Medido en el barrio antes del arreglo: el 68 % de las conversaciones no
tenían a nadie delante.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, is_available
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, NeedSpec, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Traveling, WorldState
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
SOCIAL = ActionId("act_social")
LIBRE = ActionId("act_libre")


def social_pack(**overrides: Any) -> ContentPack:
    """`act_social` exige un acompañante y solo se puede en p1."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01}],
        "actions": [
            {
                "id": "act_social",
                "label": "act_social",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "requires_company": 1,
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.8},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {"candidate_pool": 1, "critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- disponibilidad ----------------------------------------------------------


def test_a_social_action_is_unavailable_alone() -> None:
    pack = social_pack()
    action, place = pack.action_by_id[SOCIAL], pack.place_by_id[P1]
    assert not is_available(action, place, company=0)
    assert is_available(action, place, company=1)


def test_company_does_not_replace_the_affordance() -> None:
    """Las dos condiciones son necesarias, no alternativas."""
    pack = social_pack()
    assert not is_available(pack.action_by_id[SOCIAL], pack.place_by_id[P2], company=5)


def test_deliberation_ignores_a_place_without_company() -> None:
    world = WorldState.new(social_pack(), seed=1)
    world.agents[AG1].needs[N1] = 0.1
    # ag2 está en p2, así que p1 está vacío para ag1.
    assert not any(d.action == SOCIAL for d in candidates(world, world.agents[AG1]))


def test_deliberation_sees_a_place_with_company() -> None:
    world = WorldState.new(social_pack(), seed=1)
    world.agents[AG2].at = P1  # ahora hay alguien
    world.agents[AG1].at = P2
    world.agents[AG1].needs[N1] = 0.1

    opciones = [d for d in candidates(world, world.agents[AG1]) if d.action == SOCIAL]
    assert opciones and opciones[0].place == P1


def test_an_agent_does_not_count_as_its_own_company() -> None:
    """Estar en un sitio no te hace compañía a ti mismo."""
    world = WorldState.new(social_pack(), seed=1)
    world.agents[AG2].at = P2
    world.agents[AG1].at = P1
    world.agents[AG1].needs[N1] = 0.1
    assert not any(d.action == SOCIAL for d in candidates(world, world.agents[AG1]))


# --- al llegar ---------------------------------------------------------------


def test_arriving_to_an_empty_place_aborts_the_intent() -> None:
    """"Fui a la plaza y no había nadie". Entre decidir y llegar, la gente se
    mueve, y la intención social se queda sin interlocutor."""
    sim = Simulation(social_pack(), seed=1)
    agent = sim.state.agents[AG1]
    agent.at = P2
    agent.needs[N1] = 0.1
    agent.busy = Traveling(destination=P1, intent=SOCIAL, next_hop=P1, ticks_remaining=1)
    sim.state.agents[AG2].at = P2  # el motivo del viaje ya no está en p1

    sim.tick()

    abortados = [e for e in sim.log if e.kind is EventKind.ACTION_ABORTED]
    assert len(abortados) == 1
    assert abortados[0].action == SOCIAL
    assert abortados[0].data.get("reason") == "condiciones"


# --- alivio por compañía -----------------------------------------------------


def need_with(relief: float) -> dict[NeedId, NeedSpec]:
    return {N1: NeedSpec(id=N1, label="n1", decay_per_tick=0.10, company_relief=relief)}


def agent_at(value: float) -> AgentState:
    return AgentState(spec_id=AG1, at=P1, needs={N1: value})


def test_company_slows_the_decay() -> None:
    solo, acompanado = agent_at(0.5), agent_at(0.5)
    solo.decay(need_with(0.10), company=0)
    acompanado.decay(need_with(0.10), company=1)
    assert acompanado.needs[N1] > solo.needs[N1]


def test_relief_saturates_with_the_crowd() -> None:
    """n/(n+1): uno da la mitad, tres tres cuartos, una multitud nunca más que
    el tope. Sin saturar, una sala llena volvería la necesidad irrelevante."""
    specs = need_with(0.10)

    def tras(company: int) -> float:
        a = agent_at(0.5)
        a.decay(specs, company=company)
        return a.needs[N1]

    assert tras(1) == pytest.approx(0.45)  # 0.5 - (0.10 - 0.10*0.5)
    assert tras(3) == pytest.approx(0.475)  # 0.5 - (0.10 - 0.10*0.75)
    assert tras(99) < 0.5, "el alivio nunca llena la necesidad, solo frena la caída"


def test_relief_equal_to_decay_never_refills() -> None:
    """Rodeado de gente la soledad deja de crecer, pero no se cura: para eso hay
    que hablar con alguien."""
    a = agent_at(0.5)
    for _ in range(50):
        a.decay(need_with(0.10), company=999)
    assert a.needs[N1] <= 0.5


def test_a_need_without_relief_ignores_company() -> None:
    a = agent_at(0.5)
    a.decay(need_with(0.0), company=10)
    assert a.needs[N1] == pytest.approx(0.4)


# --- validación --------------------------------------------------------------


def test_an_action_needing_more_company_than_the_world_has_is_rejected() -> None:
    """Con 2 agentes el máximo alcanzable es 1: `requires_company` cuenta a los
    OTROS. Es el mismo fallo silencioso que la acción huérfana."""
    with pytest.raises(ValidationError, match="acompañantes"):
        social_pack(
            actions=[
                {
                    "id": "act_social",
                    "label": "x",
                    "duration_ticks": 1,
                    "requires_affordance": "aff",
                    "requires_company": 2,
                },
                {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
            ]
        )
