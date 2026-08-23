"""Tests de la composición de personalidad."""

from __future__ import annotations

from typing import Any

import pytest

from agora.engine.disposition import (
    compose_need_weights,
    compose_tastes,
    compose_temperament,
)
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


# --- temperamento ------------------------------------------------------------


def temperament_pack(**tuning: float) -> ContentPack:
    base = {"temperature": 0.20, "loss_aversion": 1.0, "critical_need_threshold": 0.20,
            "travel_discount": 0.90}
    base.update(tuning)
    return pack_with(
        tuning=base,
        traits=[
            {
                "id": "impulsividad",
                "label": "impulsividad",
                "temperament_multipliers": {"temperature": 3.0, "loss_aversion": 0.5},
            },
            {
                "id": "aguante",
                "label": "aguante",
                "temperament_multipliers": {"critical_need_threshold": 0.4},
            },
            {
                "id": "arraigo",
                "label": "arraigo",
                "temperament_multipliers": {"travel_discount": 0.8},
            },
            {
                "id": "sociabilidad",
                "label": "sociabilidad",
                "temperament_multipliers": {"companionship_weight": 3.0},
            },
        ],
    )


IMPULSO = TraitId("impulsividad")
AGUANTE = TraitId("aguante")
ARRAIGO = TraitId("arraigo")
SOCIABLE = TraitId("sociabilidad")


# --- cuanto atrae la gente, que era lo unico universal -----------------------


def test_crowd_pull_is_a_character_trait() -> None:
    """Era la unica de las cinco perillas que el mundo fijaba PARA TODOS: una
    taberna llena atraia lo mismo a un juerguista que a un ermitano, y el pack
    no tenia forma de decir lo contrario."""
    mundo = temperament_pack(companionship_weight=0.4)
    assert compose_temperament(mundo, {}).companionship_weight == pytest.approx(0.4)
    assert compose_temperament(mundo, {SOCIABLE: 1.0}).companionship_weight == pytest.approx(1.2)
    ermitano = compose_temperament(mundo, {SOCIABLE: -1.0}).companionship_weight
    assert ermitano == pytest.approx(0.4 / 3.0)


def test_a_world_without_crowd_pull_cannot_be_revived_by_a_trait() -> None:
    """Si el mundo lo puso a 0, ser sociable no lo resucita: un mundo donde la
    gente no atrae no se vuelve gregario porque alguien lo sea."""
    mundo = temperament_pack(companionship_weight=0.0)
    assert compose_temperament(mundo, {SOCIABLE: 1.0}).companionship_weight == 0.0


def test_no_traits_leaves_the_world_values() -> None:
    t = compose_temperament(temperament_pack(), {})
    assert t.temperature == pytest.approx(0.20)
    assert t.loss_aversion == pytest.approx(1.0)
    assert t.critical_need_threshold == pytest.approx(0.20)
    assert t.travel_discount == pytest.approx(0.90)


def test_a_trait_can_touch_several_knobs() -> None:
    t = compose_temperament(temperament_pack(), {IMPULSO: 1.0})
    assert t.temperature == pytest.approx(0.60)      # 0.20 * 3.0
    assert t.loss_aversion == pytest.approx(0.50)    # 1.00 * 0.5


def test_negative_intensity_inverts_the_knob() -> None:
    """El metódico es el impulsivo con el signo cambiado. Un solo eje cubre
    los dos caracteres."""
    t = compose_temperament(temperament_pack(), {IMPULSO: -1.0})
    assert t.temperature == pytest.approx(0.20 / 3.0)
    assert t.loss_aversion == pytest.approx(2.0)


def test_world_and_agent_compose_instead_of_replacing() -> None:
    """Un mundo donde viajar es caro Y alguien que odia salir se acumulan."""
    caro = compose_temperament(temperament_pack(travel_discount=0.70), {ARRAIGO: 1.0})
    assert caro.travel_discount == pytest.approx(0.70 * 0.8)


# --- acotado: cada perilla tiene su rango válido -----------------------------


def test_travel_discount_never_exceeds_one() -> None:
    """Por encima de 1, la distancia AUMENTARÍA el atractivo: un agente al que
    cuanto más lejos, más le apetece."""
    t = compose_temperament(temperament_pack(travel_discount=0.95), {ARRAIGO: -1.0})
    assert t.travel_discount == 1.0


def test_critical_threshold_never_exceeds_one() -> None:
    """Por encima de 1 el agente estaría en pánico permanente, incluso con las
    necesidades llenas."""
    t = compose_temperament(temperament_pack(critical_need_threshold=0.9), {AGUANTE: -1.0})
    assert t.critical_need_threshold == 1.0


def test_temperature_never_reaches_zero() -> None:
    """Sería una división por cero en el softmax. Un valor diminuto es legítimo
    —equivale a elegir siempre lo mejor— pero cero no."""
    t = compose_temperament(temperament_pack(), {IMPULSO: -1.0})
    assert t.temperature > 0.0


def test_a_world_without_costs_cannot_be_overridden_by_a_trait() -> None:
    """`loss_aversion: 0` desactiva los costes en ese mundo. Ningún rasgo debe
    poder resucitarlos."""
    t = compose_temperament(temperament_pack(loss_aversion=0.0), {IMPULSO: -1.0})
    assert t.loss_aversion == 0.0


def test_loss_aversion_has_no_ceiling() -> None:
    """Pesar el precio muchísimo describe a alguien paralizado por el gasto.
    Es un carácter válido, no un valor inválido."""
    pack = pack_with(
        tuning={"loss_aversion": 2.0},
        traits=[
            {
                "id": "avaricia",
                "label": "avaricia",
                "temperament_multipliers": {"loss_aversion": 4.0},
            }
        ],
    )
    t = compose_temperament(pack, {TraitId("avaricia"): 1.0})
    assert t.loss_aversion == pytest.approx(8.0)


def test_unknown_knob_is_rejected_by_the_pack() -> None:
    """El conjunto de perillas es cerrado: lo define el motor, no la
    ambientación."""
    with pytest.raises(Exception, match="temperament_multipliers"):
        pack_with(
            traits=[
                {
                    "id": "t1",
                    "label": "t1",
                    "temperament_multipliers": {"inventada": 2.0},
                }
            ]
        )


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


# --- las cinco que eran del mundo y tenian que ser de la persona -------------
#
# Salieron de pasar el catalogo por la lista OCEAN. Como modelo de personalidad
# no sirve aqui -es descriptivo, no generativo- pero como lista de comprobacion
# es excelente, y dejo dos factores enteros SIN PODER ESCRIBIRSE por la misma
# causa: perillas que deberian ser del individuo se habian quedado del mundo.


def apego_pack(**tuning: float) -> ContentPack:
    """Un mundo con las cinco encendidas y rasgos que las tocan."""
    base: dict[str, Any] = {
        "novelty_weight": 0.5, "switch_cost": 0.5, "learning_rate": 0.2,
        "bond_rate": 0.2, "bond_fade": 0.9,
    }
    base.update(tuning)
    return pack_with(
        tuning=base,
        traits=[
            {"id": "curioso", "label": "curioso",
             "temperament_multipliers": {"novelty_weight": 1.6}},
            {"id": "constante", "label": "constante",
             "temperament_multipliers": {"switch_cost": 1.5}},
            {"id": "dogmatico", "label": "dogmatico",
             "temperament_multipliers": {"learning_rate": 0.3}},
            {"id": "ansioso", "label": "ansioso",
             "temperament_multipliers": {"bond_rate": 2.0, "bond_fade": 1.06}},
            {"id": "evitativo", "label": "evitativo",
             "temperament_multipliers": {"bond_rate": 0.3, "bond_fade": 0.8}},
        ],
    )


def test_the_five_reach_the_agent() -> None:
    pack = apego_pack()
    for rasgo, campo, mas in (
        ("curioso", "novelty_weight", True),
        ("constante", "switch_cost", True),
        ("dogmatico", "learning_rate", False),
    ):
        neutro = getattr(compose_temperament(pack, {}), campo)
        propio = getattr(compose_temperament(pack, {TraitId(rasgo): 1.0}), campo)
        assert (propio > neutro) is mas, f"{rasgo} no movió {campo}"


def test_attachment_styles_fall_out_of_two_knobs() -> None:
    """**Lo que estas dos compran, y sin una sola regla de apego.** El ansioso
    se engancha rapido y no suelta; el evitativo tarda en querer y olvida
    pronto. Son el mismo par de numeros en direcciones opuestas."""
    pack = apego_pack()
    ansioso = compose_temperament(pack, {TraitId("ansioso"): 1.0})
    evitativo = compose_temperament(pack, {TraitId("evitativo"): 1.0})

    assert ansioso.bond_rate > evitativo.bond_rate, "quién se engancha antes"
    assert ansioso.bond_fade > evitativo.bond_fade, "quién tarda más en soltar"


def test_all_five_are_fractions_and_carry_a_ceiling() -> None:
    """La diferencia con `loss_aversion` y `companionship_weight`, que son PESOS
    y pueden dispararse describiendo a alguien valido: estas cinco viven en
    [0, 1] por lo que SIGNIFICAN. Un `bond_fade` por encima de 1 haria que el
    aprecio CRECIERA por no verse."""
    pack = apego_pack(novelty_weight=0.9, switch_cost=0.9, learning_rate=0.9,
                      bond_rate=0.9, bond_fade=0.98)
    t = compose_temperament(pack, {TraitId("curioso"): 1.0,
                                   TraitId("constante"): 1.0,
                                   TraitId("dogmatico"): -1.0,
                                   TraitId("ansioso"): 1.0})
    for campo in ("novelty_weight", "switch_cost", "learning_rate",
                  "bond_rate", "bond_fade"):
        assert getattr(t, campo) <= 1.0, campo


def test_a_world_that_turned_one_off_stays_off() -> None:
    """Multiplicar por cero da cero, y eso es lo correcto: un mundo sin
    aprendizaje no produce a alguien que aprenda porque sea despierto."""
    pack = apego_pack(learning_rate=0.0, bond_rate=0.0)
    t = compose_temperament(pack, {TraitId("ansioso"): 1.0})
    assert t.learning_rate == 0.0
    assert t.bond_rate == 0.0


def test_without_traits_the_five_are_exactly_the_worlds() -> None:
    """La condicion del cambio: un pack que no las toca se comporta igual que
    antes de que fueran del individuo."""
    pack = apego_pack()
    t = compose_temperament(pack, {})
    assert (t.novelty_weight, t.switch_cost, t.learning_rate,
            t.bond_rate, t.bond_fade) == (0.5, 0.5, 0.2, 0.2, 0.9)
