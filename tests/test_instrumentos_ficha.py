"""Pruebas de los instrumentos de línea de órdenes para fichas mecánicas (unidad 11, §B.5)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agora.run import main

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
ALDEA_PACK = Path("packs/aldea/pack.yaml")


def test_fichas_por_la_linea_de_ordenes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # --days 0 --quiet --fichas imprime tiers, los siete atributos, roles, armas,

    # armaduras, estilo y fichas distintas.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--days",
            "0",
            "--quiet",
            "--fichas",
        ],
    )
    main()
    out = capsys.readouterr().out

    assert "# 200 fichas, tick 0" in out
    assert "tiers" in out
    assert "Fuerza" in out
    assert "Agilidad" in out
    assert "Ingenio" in out
    assert "Instinto" in out
    assert "Voluntad" in out
    assert "Presencia" in out
    assert "Resonancia" in out
    assert "roles" in out
    assert "armas" in out
    assert "armaduras" in out
    assert "agresividad" in out
    assert "huye bajo" in out
    assert "capricho" in out
    assert "va a por" in out
    assert "remata" in out
    assert "fichas distintas" in out


def test_duelo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cubre M17: con --duelo y --combates 200, debe correr el duelo y no la
    # calibración de rules.yaml
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--days",
            "0",
            "--quiet",
            "--duelo",
            "xan_fuegolento_67",
            "--contra",
            "isla_cenizal",
            "--combates",
            "200",
        ],
    )
    main()
    out = capsys.readouterr().out

    assert "duelo_xan_fuegolento_67_isla_cenizal" in out
    assert "gana xan_fuegolento_67" in out
    assert "gana isla_cenizal" in out
    assert "combates" in out or "encuentros" in out

    # No debe ejecutar la calibración de rules.yaml
    assert "calibración" not in out
    assert "un_tier_preparado" not in out

    # --duelo sin --contra -> SystemExit
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--days",
            "0",
            "--quiet",
            "--duelo",
            "xan_fuegolento_67",
        ],
    )
    with pytest.raises(SystemExit, match="--duelo necesita --contra"):
        main()


def test_ficha_mecanica_individual(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--days",
            "0",
            "--quiet",
            "--ficha-mecanica",
            "xan_fuegolento_67",
            "--contra",
            "isla_cenizal",
        ],
    )
    main()
    out = capsys.readouterr().out
    assert "# ficha mecánica de xan_fuegolento_67" in out
    assert "coloso" in out
    assert "maza" in out


def test_sin_enlace_no_hay_ficha(monkeypatch: pytest.MonkeyPatch) -> None:
    # un pack sin reglas/base.yaml da un error claro
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(ALDEA_PACK),
            "--days",
            "0",
            "--quiet",
            "--fichas",
        ],
    )
    with pytest.raises(SystemExit, match="este mundo no tiene enlace con el sistema 'base': falta"):
        main()
