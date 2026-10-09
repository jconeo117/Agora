"""Pruebas de los ejemplos de resolución del Borrador 1 del TTRPG (§21)."""

from __future__ import annotations

from pathlib import Path

from agora.engine.ports import Challenge, Effect, Outcome
from agora.rules.damage import VitalityBand, damage, vitality_band
from agora.rules.pool import PoolResolver
from agora.rules.system import load_ruleset
from tests.test_reglas_tirada import Dados

ruleset = load_ruleset(Path("rules/base/rules.yaml"))
R = PoolResolver.from_ruleset(ruleset)


def test_aria_contra_el_lobo() -> None:
    # §21.1: Aria contra un lobo, paso a paso
    # Grados desde el sistema:
    grado_aria = ruleset.grade(8)  # 3
    reserva_ataque_aria = grado_aria + 2  # 5
    reserva_defensa_aria = grado_aria + 1  # 4

    grado_lobo = ruleset.grade(9)  # 3
    reserva_ataque_lobo = grado_lobo + 3  # 6
    reserva_defensa_lobo = grado_lobo + 1  # 4

    assert reserva_ataque_aria == 5
    assert reserva_defensa_aria == 4
    assert reserva_ataque_lobo == 6
    assert reserva_defensa_lobo == 4

    # Ronda 1: Aria ataca (5 dados) vs lobo defiende (4 dados)
    # Aria tira primero y lobo después
    res1 = R.resolve(
        Challenge(pool=reserva_ataque_aria, opposing_pool=reserva_defensa_lobo),
        Dados(6, 5, 3, 2, 1, 5, 4, 2, 1),
    )
    assert res1.outcome is Outcome.SUCCESS_AT_COST
    assert res1.effect == Effect.STANDARD
    dano_lobo1 = damage(4, grado_aria, res1.effect, 0, 0)
    assert dano_lobo1 == 7
    vitalidad_lobo = 17 - dano_lobo1
    assert vitalidad_lobo == 10

    # Lobo contrataca con 6 dados vs Aria con 4 dados
    res_lobo = R.resolve(
        Challenge(pool=reserva_ataque_lobo, opposing_pool=reserva_defensa_aria),
        Dados(6, 6, 5, 3, 2, 1, 5, 3, 2, 2),
    )
    assert res_lobo.outcome is Outcome.CRITICAL
    assert res_lobo.effect == Effect.GREAT
    assert damage(3, grado_lobo, res_lobo.effect, 1, 0) == 8

    # Aria resiste con grade(6) + 1 = 3 dados
    res_resiste = R.resist(ruleset.grade(6) + 1, res_lobo.effect, Dados(5, 2, 1))
    assert res_resiste.effect == Effect.STANDARD
    assert res_resiste.stress == 2
    dano_aria = damage(3, grado_lobo, res_resiste.effect, 1, 0)
    assert dano_aria == 5
    vitalidad_aria = 18 - dano_aria
    assert vitalidad_aria == 13

    # Ronda 2: dos FAILURE
    res_r2_aria = R.resolve(
        Challenge(pool=reserva_ataque_aria, opposing_pool=reserva_defensa_lobo),
        Dados(5, 4, 3, 2, 1, 6, 4, 3, 2),
    )
    assert res_r2_aria.outcome is Outcome.FAILURE

    res_r2_lobo = R.resolve(
        Challenge(pool=reserva_ataque_lobo, opposing_pool=reserva_defensa_aria),
        Dados(5, 4, 3, 2, 1, 1, 5, 6, 2, 1),
    )
    assert res_r2_lobo.outcome is Outcome.FAILURE

    # Ronda 3: Aria con 6 dados vs lobo con 4 dados
    res_r3 = R.resolve(
        Challenge(pool=6, opposing_pool=reserva_defensa_lobo),
        Dados(6, 5, 5, 4, 2, 1, 4, 3, 2, 1),
    )
    assert res_r3.outcome is Outcome.SUCCESS
    assert res_r3.effect == Effect.STANDARD
    dano_lobo2 = damage(4, grado_aria, res_r3.effect, 0, 0)
    assert dano_lobo2 == 7
    vitalidad_lobo -= dano_lobo2
    assert vitalidad_lobo == 3
    assert vitality_band(vitalidad_lobo, 17, ruleset.vitality) is VitalityBand.GRAVE
    assert vitality_band(vitalidad_aria, 18, ruleset.vitality) is VitalityBand.HEALTHY


def test_aria_contra_el_oso() -> None:
    # §21.3: tier_gap=1 → LIMITED; con Agilidad damage(4, 3, LIMITED, 2, 0) == 1;
    # con Fuerza damage(4, 2, LIMITED, 2, 1) == 2; con preparación (effect=GREAT) → STANDARD y 5.
    res = R.resolve(Challenge(pool=5, tier_gap=1), Dados(5, 5, 1, 1, 1))
    assert res.outcome is Outcome.SUCCESS
    assert res.effect == Effect.LIMITED

    assert damage(4, 3, Effect.LIMITED, 2, 0) == 1
    assert damage(4, 2, Effect.LIMITED, 2, 1) == 2

    res_prep = R.resolve(Challenge(pool=5, effect=Effect.GREAT, tier_gap=1), Dados(5, 5, 1, 1, 1))
    assert res_prep.outcome is Outcome.SUCCESS
    assert res_prep.effect == Effect.STANDARD
    assert damage(4, 3, res_prep.effect, 2, 0) == 5


def test_ren_contra_seis_lobos() -> None:
    # §21.4: un lobo con tier_gap=4 y crítico → efecto NONE, daño 0.
    # Ren con pool=11 contra 6: tira 6 dados, overflow == 2, efecto EXTREME sin crítico,
    # damage(6, 6, EXTREME, 0, 1) == 24.
    res_lobo = R.resolve(Challenge(pool=6, tier_gap=4), Dados(6, 6, 1, 1, 1, 1))
    assert res_lobo.outcome is Outcome.CRITICAL
    assert res_lobo.effect == Effect.NONE
    assert damage(3, 3, res_lobo.effect, 2, 0) == 0

    res_ren = R.resolve(
        Challenge(pool=11, opposing_pool=6),
        Dados(5, 5, 5, 1, 1, 1, 5, 1, 1, 1, 1, 1),
    )
    assert len(res_ren.dice) == 6
    assert res_ren.overflow == 2
    assert res_ren.outcome is Outcome.SUCCESS
    assert res_ren.effect == Effect.EXTREME
    assert damage(6, 6, res_ren.effect, 0, 1) == 24


def test_los_grados_del_borrador() -> None:
    # grade(v) para v = 0, 1, 3, 4, 6, 7, 10, 11, 15, 16, 21, 22, 30
    # da 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6
    valores = (0, 1, 3, 4, 6, 7, 10, 11, 15, 16, 21, 22, 30)
    esperados = (0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6)
    for v, esperado in zip(valores, esperados, strict=True):
        assert ruleset.grade(v) == esperado
