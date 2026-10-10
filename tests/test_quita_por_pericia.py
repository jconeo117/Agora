"""Tests para quita_por_pericia: el daño escala con quien golpea (I-008)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import AgentId, NeedId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

ATACANTE = AgentId("atacante")
DEFENSOR = AgentId("defensor")
SALUD = NeedId("salud")
COMBATE = NeedId("combate")


def combate_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test_combate",
        "label": "test_combate",
        "needs": [
            {
                "id": "salud",
                "label": "salud",
                "decay_per_tick": 0.0,
                "initial": 1.0,
                "lethal_after": 8,
            },
            {
                "id": "combate",
                "label": "combate",
                "decay_per_tick": 0.0,
                "initial": 0.0,
            },
        ],
        "traits": [
            {"id": "fuerza_x1", "label": "fuerza_x1", "gain_multipliers": {"combate": 1.0}},
            {"id": "fuerza_x2", "label": "fuerza_x2", "gain_multipliers": {"combate": 2.0}},
            {"id": "temple_x05", "label": "temple_x05", "cost_multipliers": {"salud": 0.5}},
        ],
        "actions": [
            {
                "id": "atacar",
                "label": "atacar",
                "duration_ticks": 1,
                "requires_company": 1,
                "satisfies": {"combate": 1.0},
                "target": {
                    "gives": {"salud": -0.2},
                    "quita_por_pericia": "combate",
                    "por_desconocido": True,
                },
            },
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [{"id": "arena", "label": "arena", "affordances": ["sitio"]}],
        "agents": [
            {
                "id": "atacante",
                "label": "Atacante",
                "home": "arena",
                "start_at": "arena",
                "traits": {"fuerza_x1": 1.0},
            },
            {
                "id": "defensor",
                "label": "Defensor",
                "home": "arena",
                "start_at": "arena",
            },
        ],
        "tuning": {
            "memory_capacity": 20,
            "memory_scale": 1.0,
            "bond_rate": 0.3,
            "bond_scale": 1.0,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_sin_el_campo_el_dano_no_depende_de_quien_golpea() -> None:
    """Dos atacantes con distinta aptitud en el eje: mismo daño."""

    def golpe_sin_pericia(rasgo_atacante: str) -> float:
        pack = combate_pack(
            actions=[
                {
                    "id": "atacar",
                    "label": "atacar",
                    "duration_ticks": 1,
                    "requires_company": 1,
                    "satisfies": {"combate": 1.0},
                    "target": {
                        "gives": {"salud": -0.2},
                        "por_desconocido": True,
                    },
                },
                {"id": "nada", "label": "nada", "duration_ticks": 1},
            ],
            agents=[
                {
                    "id": "atacante",
                    "label": "Atacante",
                    "home": "arena",
                    "start_at": "arena",
                    "traits": {rasgo_atacante: 1.0},
                },
                {
                    "id": "defensor",
                    "label": "Defensor",
                    "home": "arena",
                    "start_at": "arena",
                },
            ],
        )
        sim = Simulation(pack, seed=1)
        sim.run(2)
        return sim.state.agents[DEFENSOR].needs[SALUD]

    dano_x1 = 1.0 - golpe_sin_pericia("fuerza_x1")
    dano_x2 = 1.0 - golpe_sin_pericia("fuerza_x2")
    assert dano_x1 == pytest.approx(0.2)
    assert dano_x2 == pytest.approx(0.2)
    assert dano_x1 == pytest.approx(dano_x2)


def test_con_el_campo_el_dano_escala_con_la_aptitud() -> None:
    """Con quita_por_pericia, el daño es gives * gains[eje] del atacante
    (antes del temple del que recibe).
    """

    def golpe_con_pericia(rasgo_atacante: str) -> float:
        pack = combate_pack(
            agents=[
                {
                    "id": "atacante",
                    "label": "Atacante",
                    "home": "arena",
                    "start_at": "arena",
                    "traits": {rasgo_atacante: 1.0},
                },
                {
                    "id": "defensor",
                    "label": "Defensor",
                    "home": "arena",
                    "start_at": "arena",
                },
            ],
        )
        sim = Simulation(pack, seed=1)
        sim.run(2)
        return sim.state.agents[DEFENSOR].needs[SALUD]

    dano_x1 = 1.0 - golpe_con_pericia("fuerza_x1")
    dano_x2 = 1.0 - golpe_con_pericia("fuerza_x2")
    assert dano_x1 == pytest.approx(0.20)
    assert dano_x2 == pytest.approx(0.40)
    assert dano_x2 == pytest.approx(dano_x1 * 2.0)


def test_el_temple_del_que_recibe_se_compone() -> None:
    """Con cost_multipliers en salud en el que recibe, el daño final es el
    producto de las dos escalas.
    """
    pack = combate_pack(
        agents=[
            {
                "id": "atacante",
                "label": "Atacante",
                "home": "arena",
                "start_at": "arena",
                "traits": {"fuerza_x2": 1.0},
            },
            {
                "id": "defensor",
                "label": "Defensor",
                "home": "arena",
                "start_at": "arena",
                "traits": {"temple_x05": 1.0},
            },
        ],
    )
    sim = Simulation(pack, seed=1)
    sim.run(2)
    # Daño = 0.2 (base) * 2.0 (atacante) * 0.5 (defensor) = 0.20
    dano = 1.0 - sim.state.agents[DEFENSOR].needs[SALUD]
    assert dano == pytest.approx(0.20)


def test_lo_positivo_no_lo_toca() -> None:
    """Una acción con gives positivo y quita_por_pericia declarado:
    lo positivo no cambia (eso sigue siendo gives_por_pericia).
    """
    pack = combate_pack(
        actions=[
            {
                "id": "atacar",
                "label": "atacar",
                "duration_ticks": 1,
                "requires_company": 1,
                "satisfies": {"combate": 1.0},
                "target": {
                    "gives": {"salud": 0.2},
                    "quita_por_pericia": "combate",
                    "por_desconocido": True,
                },
            },
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        agents=[
            {
                "id": "atacante",
                "label": "Atacante",
                "home": "arena",
                "start_at": "arena",
                "traits": {"fuerza_x2": 1.0},
            },
            {
                "id": "defensor",
                "label": "Defensor",
                "home": "arena",
                "start_at": "arena",
                "initial_needs": {"salud": 0.5},
            },
        ],
    )
    sim = Simulation(pack, seed=1)
    sim.run(2)
    # Recibe exactamente 0.2, no 0.2 * 2.0 = 0.4
    assert sim.state.agents[DEFENSOR].needs[SALUD] == pytest.approx(0.70)


def test_una_pericia_desconocida_no_carga() -> None:
    """quita_por_pericia sobre una necesidad que no existe -> el pack no carga,
    con el mensaje.
    """
    with pytest.raises(ValueError, match="quita_por_pericia"):
        combate_pack(
            actions=[
                {
                    "id": "atacar",
                    "label": "atacar",
                    "duration_ticks": 1,
                    "requires_company": 1,
                    "satisfies": {"combate": 1.0},
                    "target": {
                        "gives": {"salud": -0.2},
                        "quita_por_pericia": "magia_inexistente",
                        "por_desconocido": True,
                    },
                },
                {"id": "nada", "label": "nada", "duration_ticks": 1},
            ],
        )
