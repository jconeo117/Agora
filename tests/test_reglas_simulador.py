"""Pruebas del simulador de combates (unidad 09)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

from agora.rules.encounter import Status
from agora.rules.scene import ScenarioSpec, load_scenario
from agora.rules.simulator import (
    CalibrationCheck,
    account,
    check_calibration,
    fight,
    simulate,
)
from agora.rules.system import CalibrationTarget, load_ruleset
from agora.run import main

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


def test_las_promesas_que_hoy_se_cumplen() -> None:
    # check_calibration(..., 2000, 1312): espejo, dos_tiers y tres_tiers en CUMPLE.
    # Las dos del oso no se afirman en ningún sentido (§3.9).
    ruleset = load_ruleset(BASE_RULES)
    checks = check_calibration(ruleset, ESCENARIOS_DIR, 2000, 1312)
    por_escenario = {c.target.scenario: c for c in checks}

    assert por_escenario["espejo"].ok is True
    assert por_escenario["dos_tiers"].ok is True
    assert por_escenario["tres_tiers"].ok is True


def test_la_banda_de_rondas_cuenta() -> None:
    # una promesa de juguete con rounds_max: 1 sobre espejo da NO CUMPLE aunque la victoria quepa.
    ruleset = load_ruleset(BASE_RULES)
    target_juguete = CalibrationTarget(
        scenario="espejo", side="a", win_min=45, win_max=55, rounds_min=1, rounds_max=1
    )
    ruleset_juguete = ruleset.model_copy(update={"calibration": (target_juguete,)})
    checks = check_calibration(ruleset_juguete, ESCENARIOS_DIR, 100, 1312)
    assert len(checks) == 1
    assert checks[0].ok is False

    # Verificación directa de CalibrationCheck.ok
    check_directo = CalibrationCheck(
        target=CalibrationTarget(scenario="espejo", side="a", win_min=40, win_max=60, rounds_max=1),
        win_rate=0.50,
        median_rounds=4,
    )
    assert check_directo.ok is False


def test_el_informe_cuadra() -> None:
    # victorias + empates = iteraciones; las rondas, ordenadas;
    # dos simulate iguales con la misma semilla.
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)

    rep1 = simulate(esc, ruleset, 100, 1312)
    rep2 = simulate(esc, ruleset, 100, 1312)

    assert sum(n for _, n in rep1.wins) + rep1.draws == rep1.iterations
    assert rep1.rounds == tuple(sorted(rep1.rounds))
    assert rep1 == rep2


def test_rematar_ocurre_al_cerrar(tmp_path: Path) -> None:
    # aria_lobo con el lobo en finish_off: siempre (y en si_le_odia con regard: {aria: -40})
    # tiene muertes y las mismas victorias que con nunca, que no tiene ninguna.
    ruleset = load_ruleset(BASE_RULES)
    raw = yaml.safe_load((ESCENARIOS_DIR / "aria_lobo.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)

    def _scenario_con_estilo_lobo(
        finish: str, regard: dict[str, int] | None = None,
    ) -> ScenarioSpec:
        d = copy.deepcopy(raw)
        lobo_spec = d["sides"][1]["combatants"][0]
        lobo_spec["style"]["finish_off"] = finish
        if regard:
            lobo_spec["regard"] = regard
        p = tmp_path / f"lobo_{finish}_{regard is not None}.yaml"
        p.write_text(yaml.safe_dump(d), encoding="utf-8")
        return load_scenario(p, ruleset)

    esc_nunca = _scenario_con_estilo_lobo("nunca")
    esc_siempre = _scenario_con_estilo_lobo("siempre")
    esc_odia = _scenario_con_estilo_lobo("si_le_odia", {"aria": -40})

    rep_nunca = simulate(esc_nunca, ruleset, 200, 1312)
    rep_siempre = simulate(esc_siempre, ruleset, 200, 1312)
    rep_odia = simulate(esc_odia, ruleset, 200, 1312)

    # Las victorias del lobo son idénticas en los tres
    assert rep_nunca.wins == rep_siempre.wins == rep_odia.wins

    endings_nunca = dict(rep_nunca.endings)
    endings_siempre = dict(rep_siempre.endings)
    endings_odia = dict(rep_odia.endings)

    # Con 'nunca', nadie muere al cerrar
    assert endings_nunca.get(Status.DEAD, 0) == 0

    # Con 'siempre' y 'si_le_odia', hay muertes al cerrar
    assert endings_siempre.get(Status.DEAD, 0) > 0
    assert endings_odia.get(Status.DEAD, 0) > 0


def test_la_linea_de_ordenes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # --combates 200 imprime cinco promesas y la línea contrato: sin cargar ningún pack
    # (con --pack /no/existe.yaml); --escenario ... --relato 0 acaba en «gana Aria»;
    # --relato sin --escenario → SystemExit.

    # 1. --combates sin pack
    monkeypatch.setattr(
        sys,
        "argv",
        ["agora", "--combates", "200", "--pack", "/no/existe.yaml", "--seed", "1312"],
    )
    main()
    cap1 = capsys.readouterr().out
    assert "espejo" in cap1
    assert "dos_tiers" in cap1
    assert "tres_tiers" in cap1
    assert "contrato:" in cap1

    # 2. --escenario con --relato 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--escenario",
            str(ESCENARIOS_DIR / "aria_lobo.yaml"),
            "--relato",
            "0",
            "--seed",
            "1312",
        ],
    )
    main()
    cap2 = capsys.readouterr().out
    assert "gana " in cap2

    # 3. --relato sin --escenario -> SystemExit
    monkeypatch.setattr(sys, "argv", ["agora", "--relato", "0"])
    with pytest.raises(SystemExit):
        main()


def test_el_relato() -> None:
    # account da una línea por Beat más la final.
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    res = fight(esc, ruleset, seed=1312, iteration=0)

    lineas = account(esc, res)
    assert len(lineas) == len(res.beats) + 1
    assert lineas[-1].startswith("  gana ")
    assert " rondas: " in lineas[-1]
