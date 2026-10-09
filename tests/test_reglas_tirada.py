"""Pruebas del núcleo de tirada y resolución de acciones (unidad 08)."""

from __future__ import annotations

from pathlib import Path

from agora.engine.ports import (
    Challenge,
    Dice,
    Effect,
    Outcome,
    RuleSystem,
)
from agora.engine.rng import RngSource
from agora.rules.damage import damage
from agora.rules.pool import KeyedDice, PoolResolver, roll_pool
from agora.rules.system import load_ruleset


class Dados:
    """Devuelve los dados en el orden escrito y revienta si se piden más."""

    def __init__(self, *caras: int) -> None:
        self.caras = list(caras)

    def roll(self, n: int) -> tuple[int, ...]:
        salen, self.caras = tuple(self.caras[:n]), self.caras[n:]
        assert len(salen) == n, "el test no escribió dados suficientes"
        return salen


R = PoolResolver.from_ruleset(load_ruleset(Path("rules/base/rules.yaml")))


def test_cinco_y_seis_son_exito() -> None:
    # Una tirada simple de 3 dados con (5, 6, 4) da 2 éxitos y un seis; con (4, 4, 4), cero.
    tirada, exitos, seises = roll_pool(3, R.cap, Dados(5, 6, 4))
    assert tirada == (5, 6, 4)
    assert exitos == 2
    assert seises == 1

    tirada0, exitos0, seises0 = roll_pool(3, R.cap, Dados(4, 4, 4))
    assert tirada0 == (4, 4, 4)
    assert exitos0 == 0
    assert seises0 == 0

    res = R.resolve(Challenge(pool=3), Dados(5, 6, 4))
    assert res.successes == 2
    assert res.sixes == 1


def test_resultado_de_una_tirada_simple() -> None:
    # 0 éxitos → FAILURE; 1 → SUCCESS_AT_COST; 2 sin dos seises → SUCCESS;
    # 2 con dos seises → CRITICAL
    res_fail = R.resolve(Challenge(pool=3), Dados(4, 4, 4))
    assert res_fail.outcome is Outcome.FAILURE

    res_cost = R.resolve(Challenge(pool=3), Dados(5, 4, 4))
    assert res_cost.outcome is Outcome.SUCCESS_AT_COST

    res_success = R.resolve(Challenge(pool=3), Dados(5, 5, 4))
    assert res_success.outcome is Outcome.SUCCESS

    res_crit = R.resolve(Challenge(pool=3), Dados(6, 6, 4))
    assert res_crit.outcome is Outcome.CRITICAL


def test_el_empate_favorece_a_quien_se_opone() -> None:
    # Enfrentada, 2 éxitos contra 2 → FAILURE
    res = R.resolve(Challenge(pool=3, opposing_pool=3), Dados(5, 5, 1, 5, 5, 1))
    assert res.successes == 2
    assert res.opposing_successes == 2
    assert res.outcome is Outcome.FAILURE


def test_dos_seises_con_margen_uno_no_es_critico() -> None:
    # Actor (6, 6, 1) contra (5, 1) → margen 1, SUCCESS_AT_COST, aunque haya dos seises
    res = R.resolve(Challenge(pool=3, opposing_pool=2), Dados(6, 6, 1, 5, 1))
    assert res.successes == 2
    assert res.opposing_successes == 1
    assert res.sixes == 2
    assert res.outcome is Outcome.SUCCESS_AT_COST


def test_los_seises_del_defensor_no_dan_critico() -> None:
    # Actor (6, 5, 5, 5, 1) contra (6, 6) → margen 2, SUCCESS y no CRITICAL
    # aunque haya 3 seises en la mesa; sixes == 1 (los del actor)
    res = R.resolve(Challenge(pool=5, opposing_pool=2), Dados(6, 5, 5, 5, 1, 6, 6))
    assert res.successes == 4
    assert res.opposing_successes == 2
    assert res.sixes == 1
    assert res.outcome is Outcome.SUCCESS


def test_reserva_vacia_tira_dos_y_se_queda_el_peor() -> None:
    # Challenge(pool=0) pide exactamente 2 dados; (5, 6) → 1 éxito (SUCCESS_AT_COST);
    # (6, 4) → FAILURE; con pool=-3 también 2 dados. Nunca SUCCESS ni CRITICAL.
    res_cost = R.resolve(Challenge(pool=0), Dados(5, 6))
    assert len(res_cost.dice) == 2
    assert res_cost.successes == 1
    assert res_cost.outcome is Outcome.SUCCESS_AT_COST

    res_fail = R.resolve(Challenge(pool=0), Dados(6, 4))
    assert len(res_fail.dice) == 2
    assert res_fail.successes == 0
    assert res_fail.outcome is Outcome.FAILURE

    res_neg = R.resolve(Challenge(pool=-3), Dados(5, 5))
    assert len(res_neg.dice) == 2
    assert res_neg.successes == 1
    assert res_neg.outcome is Outcome.SUCCESS_AT_COST

    res_sixes = R.resolve(Challenge(pool=0), Dados(6, 6))
    assert res_sixes.outcome is Outcome.SUCCESS_AT_COST


def test_el_tope_de_la_reserva() -> None:
    # Challenge(pool=9) pide exactamente 6 dados (Dados revienta si se piden más o menos)
    dados = Dados(5, 5, 5, 5, 5, 5)
    res = R.resolve(Challenge(pool=9), dados)
    assert len(res.dice) == 6
    assert len(dados.caras) == 0


def test_el_excedente_y_su_tope() -> None:
    # Con éxito pleno, pool=7 → overflow == 1 y efecto 3; pool=8 → 2 y efecto 4;
    # pool=12 → sigue en 2 y efecto 4
    res7 = R.resolve(Challenge(pool=7), Dados(5, 5, 1, 1, 1, 1))
    assert res7.outcome is Outcome.SUCCESS
    assert res7.overflow == 1
    assert res7.effect == 3

    res8 = R.resolve(Challenge(pool=8), Dados(5, 5, 1, 1, 1, 1))
    assert res8.outcome is Outcome.SUCCESS
    assert res8.overflow == 2
    assert res8.effect == 4

    res12 = R.resolve(Challenge(pool=12), Dados(5, 5, 1, 1, 1, 1))
    assert res12.outcome is Outcome.SUCCESS
    assert res12.overflow == 2
    assert res12.effect == 4


def test_un_fallo_no_tiene_efecto() -> None:
    # FAILURE → effect == Effect.NONE, aunque la reserva traiga excedente
    res = R.resolve(Challenge(pool=8), Dados(1, 2, 3, 4, 1, 2))
    assert res.outcome is Outcome.FAILURE
    assert res.overflow == 2
    assert res.effect == Effect.NONE


def test_la_escala_baja_un_paso_por_tier() -> None:
    # Con SUCCESS, tier_gap=1 → LIMITED; tier_gap=2 → NONE; tier_gap=-2 → STANDARD
    res_gap1 = R.resolve(Challenge(pool=3, tier_gap=1), Dados(5, 5, 1))
    assert res_gap1.outcome is Outcome.SUCCESS
    assert res_gap1.effect == Effect.LIMITED

    res_gap2 = R.resolve(Challenge(pool=3, tier_gap=2), Dados(5, 5, 1))
    assert res_gap2.outcome is Outcome.SUCCESS
    assert res_gap2.effect == Effect.NONE

    res_gap_neg = R.resolve(Challenge(pool=3, tier_gap=-2), Dados(5, 5, 1))
    assert res_gap_neg.outcome is Outcome.SUCCESS
    assert res_gap_neg.effect == Effect.STANDARD


def test_un_critico_compensa_la_escala() -> None:
    # tier_gap=2 y CRITICAL → LIMITED
    res = R.resolve(Challenge(pool=3, tier_gap=2), Dados(6, 6, 1))
    assert res.outcome is Outcome.CRITICAL
    assert res.effect == Effect.LIMITED


def test_desde_tres_tiers_el_efecto_es_nulo_aunque_sea_critico() -> None:
    # tier_gap=3 y pool=8 con CRITICAL (excedente 2) → NONE
    res = R.resolve(Challenge(pool=8, tier_gap=3), Dados(6, 6, 1, 1, 1, 1))
    assert res.outcome is Outcome.CRITICAL
    assert res.overflow == 2
    assert res.effect == Effect.NONE


def test_los_pasos_se_suman_y_se_recortan_al_final() -> None:
    # effect=LIMITED, tier_gap=2, CRITICAL → NONE (1 - 2 + 1 = 0)
    res = R.resolve(
        Challenge(pool=3, effect=Effect.LIMITED, tier_gap=2),
        Dados(6, 6, 1),
    )
    assert res.outcome is Outcome.CRITICAL
    assert res.effect == Effect.NONE


def test_pasar_de_extraordinario() -> None:
    # pool=8, CRITICAL → efecto 5 y damage(6, 6, 5, 0, 0) == 30
    res = R.resolve(Challenge(pool=8), Dados(6, 6, 1, 1, 1, 1))
    assert res.outcome is Outcome.CRITICAL
    assert res.overflow == 2
    assert res.effect == 5
    assert damage(6, 6, res.effect, 0, 0) == 30


def test_los_mismos_dados_por_clave() -> None:
    # dos KeyedDice(RngSource(7).stream("t", "a", 3)) sacan los mismos 6 dados;
    # con ("t", "a", 4), otros
    fuente1 = RngSource(7)
    dados1 = KeyedDice(fuente1.stream("t", "a", 3))
    fuente2 = RngSource(7)
    dados2 = KeyedDice(fuente2.stream("t", "a", 3))
    tirada1 = dados1.roll(6)
    tirada2 = dados2.roll(6)
    assert tirada1 == tirada2

    fuente3 = RngSource(7)
    dados3 = KeyedDice(fuente3.stream("t", "a", 4))
    tirada3 = dados3.roll(6)
    assert tirada1 != tirada3


def test_el_resolutor_cumple_el_puerto() -> None:
    assert isinstance(R, RuleSystem)
    dice = KeyedDice(RngSource(1).stream("test"))
    assert isinstance(dice, Dice)


def test_outcome_tiene_cuatro_valores() -> None:
    assert set(Outcome) == {
        Outcome.FAILURE,
        Outcome.SUCCESS_AT_COST,
        Outcome.SUCCESS,
        Outcome.CRITICAL,
    }
    assert not hasattr(Outcome, "GRAVE_FAILURE")
