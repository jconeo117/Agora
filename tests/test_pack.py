"""Contrato de `pack.py`. Cada test rojo es un PASO pendiente en el archivo.

Ejecuta:
    uv run pytest tests/test_pack.py -v

y ve poniéndolos en verde de arriba abajo. Los tests están en el mismo orden
que los PASOS del andamiaje.

Nota de estilo: los packs de prueba usan nombres neutros (`n1`, `p1`, `a1`).
Un test del motor que necesita nombrar una posada está probando el pack, no el
motor.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack


def base_pack() -> dict[str, Any]:
    """Pack mínimo VÁLIDO. Cada test lo copia y le rompe una cosa."""
    return {
        "id": "test",
        "label": "pack de pruebas",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01},
        ],
        "traits": [
            {"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 1.5}},
        ],
        "actions": [
            {
                "id": "act_con_aff",
                "label": "act_con_aff",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.5},
            },
            # La red de seguridad: sin affordance, válida en cualquier sitio.
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "traits": {"t1": 0.5},
                "tastes": [{"target": "p2", "multiplier": 1.2}],
                "initial_needs": {"n1": 0.9},
            },
        ],
    }


def build(**overrides: Any) -> ContentPack:
    data = base_pack()
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def expect_rejection(fragment: str, **overrides: Any) -> None:
    """El pack debe ser rechazado, y el mensaje debe decir por qué.

    Comprobar el mensaje no es exceso de celo: una validación que rechaza sin
    explicar obliga a depurar a ciegas un fichero de datos.
    """
    with pytest.raises(ValidationError) as caught:
        build(**overrides)
    assert fragment in str(caught.value), (
        f"rechazado, pero el mensaje no menciona {fragment!r}:\n{caught.value}"
    )


# --- el pack de ejemplo debe seguir siendo válido siempre --------------------


def test_minimal_pack_is_valid() -> None:
    pack = build()
    assert pack.id == "test"


def test_shipped_dark_fantasy_pack_loads() -> None:
    """El pack real del repo tiene que pasar todas las validaciones."""
    from pathlib import Path

    from agora.engine.pack import load_pack

    root = Path(__file__).resolve().parents[1]
    pack = load_pack(root / "packs" / "dark_fantasy" / "pack.yaml")
    assert len(pack.agents) == 2
    assert len(pack.places) == 5


# --- PASO 1: índices --------------------------------------------------------


def test_indices_map_id_to_spec() -> None:
    pack = build()
    assert pack.need_by_id[NeedId("n1")].decay_per_tick == 0.01
    assert pack.action_by_id[ActionId("act_libre")].duration_ticks == 1
    assert pack.place_by_id[PlaceId("p1")].label == "p1"
    assert pack.agent_by_id[AgentId("ag1")].home == PlaceId("p1")
    assert set(pack.trait_by_id) == {"t1"}


def test_indices_are_cached_not_rebuilt() -> None:
    """`@cached_property` = `Lazy<T>`: la segunda llamada devuelve el MISMO
    objeto, no uno equivalente."""
    pack = build()
    assert pack.need_by_id is pack.need_by_id


# --- PASO 2: ids duplicados -------------------------------------------------


def test_duplicate_need_id_is_rejected() -> None:
    expect_rejection(
        "n1",
        needs=[
            {"id": "n1", "label": "a", "decay_per_tick": 0.01},
            {"id": "n1", "label": "b", "decay_per_tick": 0.02},
        ],
    )


def test_duplicate_place_id_is_rejected() -> None:
    expect_rejection(
        "p1",
        places=[
            {"id": "p1", "label": "a", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p1", "label": "b", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
    )


# --- PASO 3: colisión entre espacios de id ----------------------------------


def test_action_and_place_sharing_id_is_rejected() -> None:
    """Un gusto que apunte a "p1" sería ambiguo: ¿la acción o el lugar?"""
    expect_rejection(
        "p1",
        actions=[
            {"id": "p1", "label": "choca con el lugar", "duration_ticks": 1},
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
    )


# --- PASO 4: referencias a necesidades --------------------------------------


def test_action_referencing_unknown_need_is_rejected() -> None:
    expect_rejection(
        "fantasma",
        actions=[
            {
                "id": "act_con_aff",
                "label": "x",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "effects": {"fantasma": 0.5},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
    )


def test_trait_referencing_unknown_need_is_rejected() -> None:
    expect_rejection(
        "fantasma",
        traits=[{"id": "t1", "label": "t1", "need_weight_multipliers": {"fantasma": 2.0}}],
    )


def test_agent_initial_need_unknown_is_rejected() -> None:
    expect_rejection(
        "fantasma",
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "initial_needs": {"fantasma": 0.5},
            }
        ],
    )


# --- PASO 5: referencias a rasgos -------------------------------------------


def test_agent_with_unknown_trait_is_rejected() -> None:
    expect_rejection(
        "inventado",
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "traits": {"inventado": 0.5},
            }
        ],
    )


# --- PASO 6: referencias a lugares ------------------------------------------


def test_neighbor_pointing_nowhere_is_rejected() -> None:
    expect_rejection(
        "ninguna_parte",
        places=[
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"ninguna_parte": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
    )


def test_agent_home_pointing_nowhere_is_rejected() -> None:
    expect_rejection(
        "limbo",
        agents=[{"id": "ag1", "label": "ag1", "home": "limbo", "start_at": "p1"}],
    )


# --- PASO 7: referencias de gustos ------------------------------------------


def test_taste_targeting_nothing_is_rejected() -> None:
    expect_rejection(
        "no_existe",
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "tastes": [{"target": "no_existe", "multiplier": 1.5}],
            }
        ],
    )


def test_taste_may_target_an_action_a_place_or_an_agent() -> None:
    pack = build(
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "tastes": [
                    {"target": "act_libre", "multiplier": 1.5},
                    {"target": "p2", "multiplier": 0.5},
                    {"target": "ag2", "multiplier": 2.0},
                ],
            },
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ]
    )
    assert len(pack.agents) == 2


# --- PASO 8: acciones alcanzables -------------------------------------------


def test_action_requiring_an_affordance_nobody_offers_is_rejected() -> None:
    """La acción existiría en el YAML y jamás sería ejecutable. Silencioso."""
    expect_rejection(
        "huerfana",
        actions=[
            {
                "id": "act_con_aff",
                "label": "x",
                "duration_ticks": 1,
                "requires_affordance": "huerfana",
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
    )


# --- costes declarados ------------------------------------------------------


def test_negative_effect_without_a_declared_cost_is_rejected() -> None:
    """Si no, añadir un efecto negativo cambia el mundo sin cambiar ninguna
    decisión, y el síntoma es que un rasgo económico no hace nada."""
    expect_rejection(
        "coste",
        actions=[
            {
                "id": "act_con_aff",
                "label": "x",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "effects": {"n1": -0.4},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
    )


def test_explicit_zero_cost_models_someone_who_does_not_see_it_coming() -> None:
    pack = build(
        actions=[
            {
                "id": "act_con_aff",
                "label": "x",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "costs": {"n1": 0.0},
                "effects": {"n1": -0.4},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ]
    )
    assert pack.action_by_id[ActionId("act_con_aff")].costs == {NeedId("n1"): 0.0}


def test_negative_cost_is_rejected() -> None:
    """Un coste negativo sería un beneficio, y para eso está `satisfies`."""
    with pytest.raises(ValidationError):
        build(
            actions=[
                {
                    "id": "act_con_aff",
                    "label": "x",
                    "duration_ticks": 1,
                    "requires_affordance": "aff",
                    "costs": {"n1": -0.3},
                },
                {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
            ]
        )


# --- PASO 9: red de seguridad -----------------------------------------------


def test_pack_without_a_fallback_action_is_rejected() -> None:
    """Sin acción libre, un agente puede quedarse sin opciones legales."""
    expect_rejection(
        "affordance",
        actions=[
            {
                "id": "act_con_aff",
                "label": "x",
                "duration_ticks": 1,
                "requires_affordance": "aff",
            }
        ],
    )


# --- PASO 10: mundo navegable -----------------------------------------------


def test_place_with_no_way_out_is_rejected() -> None:
    """p3 tiene entrada y no tiene salida: trampa permanente."""
    expect_rejection(
        "conex",
        places=[
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1, "p3": 1}},
            {"id": "p3", "label": "p3"},
        ],
    )
