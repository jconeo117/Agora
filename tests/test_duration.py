"""Tests del coste de oportunidad por comprometer tiempo.

La ceguera que cubre: quien se mete en algo de treinta ticks no puede atender
nada más durante treinta ticks, y eso no aparecía en ninguna parte de la
fórmula.

Lo que NO cubre, y conviene tenerlo escrito porque se diagnosticó mal durante
mucho tiempo: que la siesta le ganara al sueño era aritmética del pack —0.30 en
8 ticks rinde más por tick que 0.95 en 30— y meter la duración lo habría
EMPEORADO, castigando más a la acción larga. Aquello se arregla en el YAML.
"""

from __future__ import annotations

from typing import Any

import pytest

from agora.agents.decide import candidates
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState

N1 = NeedId("n1")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
LARGA = ActionId("act_larga")
CORTA = ActionId("act_corta")


def timed_pack(**tuning: float) -> ContentPack:
    """Dos acciones que dan lo mismo y solo difieren en cuánto atan."""
    base: dict[str, Any] = {"critical_need_threshold": 0.0, "candidate_pool": 1}
    base.update(tuning)
    return ContentPack.model_validate(
        {
            "id": "test",
            "label": "test",
            "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.3}],
            "actions": [
                {
                    "id": "act_larga",
                    "label": "act_larga",
                    "duration_ticks": 30,
                    "satisfies": {"n1": 1.0},
                    "effects": {"n1": 0.5},
                },
                {
                    "id": "act_corta",
                    "label": "act_corta",
                    "duration_ticks": 5,
                    "satisfies": {"n1": 1.0},
                    "effects": {"n1": 0.5},
                },
            ],
            "places": [
                {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
                {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
            ],
            "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
            "tuning": base,
        }
    )


def utilities(**tuning: float) -> dict[ActionId, float]:
    world = WorldState.new(timed_pack(**tuning), seed=1)
    return {
        d.action: d.utility
        for d in candidates(world, world.agents[AG1])
        if d.place == P1
    }


def test_without_the_discount_duration_is_invisible() -> None:
    """El estado de partida: dos acciones idénticas salvo en lo que atan valen
    exactamente lo mismo."""
    u = utilities(duration_discount=1.0)
    assert u[LARGA] == pytest.approx(u[CORTA])


def test_the_discount_favours_the_shorter_commitment() -> None:
    u = utilities(duration_discount=0.99)
    assert u[CORTA] > u[LARGA]


def test_the_penalty_scales_with_the_time_committed() -> None:
    """`descuento ** duración`: treinta ticks pagan seis veces lo que cinco."""
    u = utilities(duration_discount=0.99)
    sin = utilities(duration_discount=1.0)
    assert u[LARGA] / sin[LARGA] == pytest.approx(0.99**30)
    assert u[CORTA] / sin[CORTA] == pytest.approx(0.99**5)


def test_one_disables_it() -> None:
    u = utilities(duration_discount=1.0)
    assert u[LARGA] == pytest.approx(u[CORTA])


def test_the_discount_touches_the_benefit_not_the_net() -> None:
    """Como el descuento por viaje. Sobre el neto, una opción mala y larga
    parecería menos mala por durar."""
    pack = ContentPack.model_validate(
        {
            "id": "test",
            "label": "test",
            "needs": [
                {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 1.0},
                {"id": "n2", "label": "n2", "decay_per_tick": 0.01, "initial": 0.2},
            ],
            "actions": [
                {
                    "id": "act_larga",
                    "label": "act_larga",
                    "duration_ticks": 30,
                    "satisfies": {"n1": 1.0},
                    "costs": {"n2": 0.8},
                    "effects": {"n1": 0.5, "n2": -0.1},
                },
                {"id": "act_corta", "label": "act_corta", "duration_ticks": 5},
            ],
            "places": [
                {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
                {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
            ],
            "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
            "tuning": {"critical_need_threshold": 0.0, "duration_discount": 0.99},
        }
    )
    world = WorldState.new(pack, seed=1)
    mala = next(
        d for d in candidates(world, world.agents[AG1]) if d.action == LARGA and d.place == P1
    )
    # Sin beneficio posible (n1 llena) y con coste: la utilidad es negativa, y
    # el descuento no la ha suavizado.
    assert mala.utility < 0.0
