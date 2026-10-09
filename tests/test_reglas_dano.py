"""Pruebas de daño, resistencia y bandas de vitalidad (unidad 08)."""

from __future__ import annotations

from agora.engine.ports import Effect
from agora.rules.damage import VitalityBand, damage, vitality_band
from agora.rules.system import VitalitySpec
from tests.test_reglas_tirada import Dados, R


def test_el_multiplicador_es_pasos_entre_dos() -> None:
    # damage(4, 3, e, 0, 0) para e = 0..5 da 0, 3, 7, 10, 14, 17
    esperados = (0, 3, 7, 10, 14, 17)
    for e, esperado in enumerate(esperados):
        assert damage(4, 3, e, 0, 0) == esperado


def test_el_dano_minimo_es_uno() -> None:
    # damage(4, 3, LIMITED, 4, 0) == 1 (3 - 4)
    assert damage(4, 3, Effect.LIMITED, 4, 0) == 1


def test_la_perforacion_no_suma() -> None:
    # damage(5, 2, STANDARD, 1, 2) == 7 (la perforación que sobra no añade daño)
    assert damage(5, 2, Effect.STANDARD, 1, 2) == 7


def test_resistir_baja_un_paso_y_cobra_estres() -> None:
    # R.resist(3, GREAT, Dados(5, 2, 1)) → efecto STANDARD, estrés 2.
    # Con Dados(5, 6, 5, 6) y reserva 4 → estrés 0, no -1.
    # Con efecto NONE → sigue NONE.
    res1 = R.resist(3, Effect.GREAT, Dados(5, 2, 1))
    assert res1.effect == Effect.STANDARD
    assert res1.stress == 2

    res2 = R.resist(4, Effect.GREAT, Dados(5, 6, 5, 6))
    assert res2.effect == Effect.STANDARD
    assert res2.stress == 0

    res_none = R.resist(3, Effect.NONE, Dados(5, 2, 1))
    assert res_none.effect == Effect.NONE


def test_bandas_de_vitalidad() -> None:
    # Con máximo 18: 18 y 9 → HEALTHY; 8 → WOUNDED; 4 → GRAVE; 5 → WOUNDED; 0 y -3 → DOWN.
    spec = VitalitySpec(wounded_below=50, grave_below=25)
    assert vitality_band(18, 18, spec) is VitalityBand.HEALTHY
    assert vitality_band(9, 18, spec) is VitalityBand.HEALTHY
    assert vitality_band(8, 18, spec) is VitalityBand.WOUNDED
    assert vitality_band(5, 18, spec) is VitalityBand.WOUNDED
    assert vitality_band(4, 18, spec) is VitalityBand.GRAVE
    assert vitality_band(0, 18, spec) is VitalityBand.DOWN
    assert vitality_band(-3, 18, spec) is VitalityBand.DOWN
