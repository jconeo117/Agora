"""Tests de la composición de personalidad."""

from __future__ import annotations

from typing import Any

import pytest

from agora.engine.disposition import compose_need_weights, compose_tastes
from agora.engine.ontology import NeedId, PlaceId, TasteSpec, TraitId
from agora.engine.pack import ContentPack

N1 = NeedId("n1")
T1 = TraitId("t1")


def pack_with(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01, "base_weight": 1.0}],
        "traits": [{"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 2.0}}],
        "actions": [{"id": "act_libre", "label": "act_libre", "duration_ticks": 1}],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
    }
    data.update(overrides)
    return ContentPack.model_validate(data)


# --- pesos de necesidad ------------------------------------------------------


def test_no_traits_leaves_the_base_weights() -> None:
    assert compose_need_weights(pack_with(), {})[N1] == pytest.approx(1.0)


def test_intensity_acts_as_an_exponent() -> None:
    """0 neutraliza, 1 aplica entero, -1 invierte exactamente.

    Con interpolación lineal, un multiplicador de 2.2 e intensidad -1 daría un
    factor negativo, que no significa nada.
    """
    pack = pack_with()

    def weight(intensity: float) -> float:
        return compose_need_weights(pack, {T1: intensity})[N1]

    assert weight(0.0) == pytest.approx(1.0)
    assert weight(1.0) == pytest.approx(2.0)
    assert weight(-1.0) == pytest.approx(0.5)
    assert weight(0.5) == pytest.approx(2.0**0.5)


def test_traits_compose_multiplicatively() -> None:
    """Componer rasgos es sumar en espacio logarítmico. Por eso encajan sin
    interferirse: dos rasgos que tocan la misma necesidad se acumulan."""
    pack = pack_with(
        traits=[
            {"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 2.0}},
            {"id": "t2", "label": "t2", "need_weight_multipliers": {"n1": 3.0}},
        ]
    )
    weights = compose_need_weights(pack, {T1: 1.0, TraitId("t2"): 1.0})
    assert weights[N1] == pytest.approx(6.0)


def test_composition_is_independent_of_trait_order() -> None:
    """La multiplicación es conmutativa, pero en coma flotante no es asociativa.
    Sin un orden fijo, dos corridas idénticas podrían diferir en el último bit."""
    pack = pack_with(
        traits=[
            {"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 1.7}},
            {"id": "t2", "label": "t2", "need_weight_multipliers": {"n1": 0.3}},
            {"id": "t3", "label": "t3", "need_weight_multipliers": {"n1": 2.9}},
        ]
    )
    intensities = {TraitId("t1"): 0.4, TraitId("t2"): -0.7, TraitId("t3"): 0.9}
    reversed_order = dict(reversed(list(intensities.items())))

    assert compose_need_weights(pack, intensities) == compose_need_weights(pack, reversed_order)


def test_a_trait_only_touches_the_needs_it_declares() -> None:
    pack = pack_with(
        needs=[
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "base_weight": 1.0},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.01, "base_weight": 0.5},
        ]
    )
    assert compose_need_weights(pack, {T1: 1.0})[NeedId("n2")] == pytest.approx(0.5)


# --- gustos ------------------------------------------------------------------


def test_tastes_collapse_by_target() -> None:
    assert compose_tastes([TasteSpec(target=PlaceId("p1"), multiplier=1.5)])["p1"] == 1.5


def test_two_tastes_on_the_same_target_multiply() -> None:
    """Se combinan en vez de pisarse: así una aversión heredada y una
    predilección aprendida conviven, y no gana la última declarada."""
    composed = compose_tastes(
        [
            TasteSpec(target=PlaceId("p1"), multiplier=2.0),
            TasteSpec(target=PlaceId("p1"), multiplier=0.5),
        ]
    )
    assert composed["p1"] == pytest.approx(1.0)


def test_no_tastes_gives_an_empty_map() -> None:
    assert compose_tastes([]) == {}
