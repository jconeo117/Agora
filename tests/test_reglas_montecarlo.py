"""Pruebas del instrumento Monte Carlo y probabilidades de tirada (unidad 08)."""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import pytest

import agora.run
from agora.rules.montecarlo import expected, pool_table
from agora.rules.pool import PoolResolver
from agora.rules.system import load_ruleset

R = PoolResolver.from_ruleset(load_ruleset(Path("rules/base/rules.yaml")))


def test_lo_exacto_es_lo_del_borrador() -> None:
    # expected(n, 6) para n = 0..6 da exactamente Fraction(1, 9) y luego 1 - (2/3)**n como Fraction;
    # el pleno de 3 dados es Fraction(7, 27) y el crítico de 6, 1 - (5/6)**6 - 6 * (1/6) * (5/6)**5.
    any_0, full_0, crit_0 = expected(0, 6)
    assert any_0 == Fraction(1, 9)
    assert full_0 == Fraction(0)
    assert crit_0 == Fraction(0)

    for n in range(1, 7):
        any_n, _, _ = expected(n, 6)
        assert any_n == 1 - Fraction(2, 3) ** n

    _, full_3, _ = expected(3, 6)
    assert full_3 == Fraction(7, 27)

    _, _, crit_6 = expected(6, 6)
    esperado_crit_6 = 1 - Fraction(5, 6) ** 6 - 6 * Fraction(1, 6) * Fraction(5, 6) ** 5
    assert crit_6 == esperado_crit_6


def test_lo_medido_se_acerca_a_lo_exacto() -> None:
    # pool_table(R, 20_000, 1312): cada celda a menos de 1.5 pp de su exacta.
    filas = pool_table(R, 20_000, 1312)
    assert len(filas) == 7
    for row in filas:
        assert abs(row.any_success - float(row.expected_any)) < 0.015
        assert abs(row.full_success - float(row.expected_full)) < 0.015
        assert abs(row.critical - float(row.expected_critical)) < 0.015


def test_la_tabla_es_reproducible() -> None:
    # Dos pool_table con la misma semilla son iguales; con otra semilla, no.
    filas1 = pool_table(R, 1000, 1312)
    filas2 = pool_table(R, 1000, 1312)
    filas3 = pool_table(R, 1000, 9999)
    assert filas1 == filas2
    assert filas1 != filas3


def test_medir_una_reserva_mas_no_cambia_las_otras() -> None:
    # La fila de la reserva 3 sale igual con pools=(3,) que con pools=(0, 3, 6).
    fila_sola = pool_table(R, 1000, 1312, pools=(3,))[0]
    fila_con_otras = pool_table(R, 1000, 1312, pools=(0, 3, 6))[1]
    assert fila_sola == fila_con_otras


def test_montecarlo_por_la_linea_de_ordenes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # main() con --montecarlo 500 imprime cabecera y siete filas, y no carga ningún pack
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--montecarlo",
            "500",
            "--pack",
            "/no/existe.yaml",
        ],
    )
    agora.run.main()
    out = capsys.readouterr().out
    assert "reserva" in out.lower()
    assert "éxito" in out.lower() or "exito" in out.lower()

    filas = [
        line
        for line in out.strip().splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    assert len(filas) == 7
