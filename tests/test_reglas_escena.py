"""Pruebas de la escena, armas, armaduras y escenarios de combate (unidad 09)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.rules.scene import (
    ScenarioError,
    ScenarioSpec,
    load_scenario,
)
from agora.rules.system import (
    CalibrationTarget,
    CombatSpec,
    Ruleset,
    RulesetError,
    load_ruleset,
)

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


def _toy_ruleset_data() -> dict[str, Any]:
    return {
        "id": "juguete",
        "label": "Sistema de juguete",
        "attributes": [
            {"id": "a1", "label": "A1", "minimum": 1},
            {"id": "a2", "label": "A2", "minimum": 1},
        ],
        "grades": [
            {"grade": 1, "min_value": 1},
            {"grade": 2, "min_value": 4},
        ],
        "tiers": [
            {"tier": 1, "label": "T1", "min_level": 1, "max_level": 5, "attribute_cap": 3},
            {"tier": 2, "label": "T2", "min_level": 6, "max_level": 10, "attribute_cap": 6},
        ],
        "skills": [
            {"id": "defensa", "label": "Defensa", "attribute": "a1"},
            {"id": "aguante", "label": "Aguante", "attribute": "a1"},
            {"id": "medicina", "label": "Medicina", "attribute": "a1"},
            {"id": "pelea", "label": "Pelea", "attribute": "a2"},
        ],
        "combat": {
            "initiative": ["a1", "a2"],
            "initiative_tiebreak": "a2",
            "defense_skill": "defensa",
            "resist_skill": "aguante",
            "first_aid_skill": "medicina",
            "break_attribute": "a1",
            "strength_attribute": "a1",
            "agile_attribute": "a2",
        },
    }


def _guardar_y_cargar_ruleset(tmp_path: Path, data: dict[str, Any]) -> Ruleset:
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_ruleset(p)


def test_el_sistema_trae_combate_y_calibracion() -> None:
    # rules/base/rules.yaml carga con combat y cinco promesas
    ruleset = load_ruleset(BASE_RULES)
    assert ruleset.combat is not None
    assert isinstance(ruleset.combat, CombatSpec)
    assert len(ruleset.calibration) == 5
    for target in ruleset.calibration:
        assert isinstance(target, CalibrationTarget)


def test_un_papel_de_combate_desconocido_no_carga(tmp_path: Path) -> None:
    # Atributo desconocido en combat
    data = _toy_ruleset_data()
    data["combat"]["strength_attribute"] = "fantasma"
    with pytest.raises(RulesetError, match=r"combat: atributo desconocido 'fantasma'"):
        _guardar_y_cargar_ruleset(tmp_path, data)

    # Competencia desconocida en combat
    data2 = _toy_ruleset_data()
    data2["combat"]["defense_skill"] = "fantasma_skill"
    with pytest.raises(RulesetError, match=r"combat: competencia desconocida 'fantasma_skill'"):
        _guardar_y_cargar_ruleset(tmp_path, data2)


def test_cansado_por_encima_de_exhausto_no_carga(tmp_path: Path) -> None:
    data = _toy_ruleset_data()
    data["combat"]["tired_at"] = 80
    data["combat"]["exhausted_at"] = 75
    with pytest.raises(
        RulesetError, match=r"combat: tired_at tiene que quedar por debajo de exhausted_at"
    ):
        _guardar_y_cargar_ruleset(tmp_path, data)


def test_una_banda_al_reves_no_carga(tmp_path: Path) -> None:
    data = _toy_ruleset_data()
    data["calibration"] = [
        {"scenario": "espejo", "side": "a", "win_min": 60, "win_max": 40}
    ]
    with pytest.raises(
        RulesetError, match=r"calibration\.espejo: win_min \(60\) por encima de win_max \(40\)"
    ):
        _guardar_y_cargar_ruleset(tmp_path, data)


def test_calibrar_sin_combate_no_carga(tmp_path: Path) -> None:
    data = _toy_ruleset_data()
    del data["combat"]
    data["calibration"] = [
        {"scenario": "espejo", "side": "a", "win_min": 40, "win_max": 60}
    ]
    with pytest.raises(
        RulesetError, match=r"calibration: prometer combates exige la sección combat"
    ):
        _guardar_y_cargar_ruleset(tmp_path, data)


def test_los_seis_escenarios_cargan() -> None:
    ruleset = load_ruleset(BASE_RULES)
    escenarios = (
        "aria_lobo",
        "dos_tiers",
        "espejo",
        "tres_tiers",
        "un_tier",
        "un_tier_preparado",
    )
    for nombre in escenarios:
        esc = load_scenario(ESCENARIOS_DIR / f"{nombre}.yaml", ruleset)
        assert isinstance(esc, ScenarioSpec)
        assert esc.id == nombre


def _base_aria_lobo_dict() -> dict[str, Any]:
    raw = yaml.safe_load((ESCENARIOS_DIR / "aria_lobo.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return copy.deepcopy(raw)


def _guardar_y_cargar_escenario(
    tmp_path: Path, data: dict[str, Any], ruleset: Ruleset
) -> ScenarioSpec:
    p = tmp_path / "scenario.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_scenario(p, ruleset)


def test_check_scenario_arma_desconocida(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["weapon"] = "hacha_fantasma"
    with pytest.raises(ScenarioError, match=r"arma desconocida 'hacha_fantasma'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_armadura_desconocida(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["armor"] = "coraza_fantasma"
    with pytest.raises(ScenarioError, match=r"armadura desconocida 'coraza_fantasma'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_atributo_sin_valor(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    del data["sides"][0]["combatants"][0]["attributes"]["fuerza"]
    with pytest.raises(ScenarioError, match=r"atributo 'fuerza' sin valor"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_atributo_desconocido(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["attributes"]["magia_fantasma"] = 5
    with pytest.raises(ScenarioError, match=r"atributo desconocido 'magia_fantasma'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_valor_por_encima_del_techo_tier(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    # Tier 1 tiene attribute_cap = 9 en rules/base/rules.yaml
    data["sides"][0]["combatants"][0]["attributes"]["fuerza"] = 15
    with pytest.raises(ScenarioError, match=r"fuerza = 15 pasa del techo del tier 1"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_tier_desconocido(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["tier"] = 99
    with pytest.raises(ScenarioError, match=r"tier 99 que el sistema no tiene"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_competencia_desconocida(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["attack_skill"] = "hechiceria_fantasma"
    with pytest.raises(ScenarioError, match=r"competencia desconocida 'hechiceria_fantasma'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_nivel_por_encima_de_maximo(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["skills"]["defensa"] = 10
    with pytest.raises(
        ScenarioError, match=rf"nivel 10 de 'defensa' pasa de {ruleset.skill_max_level}"
    ):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_regard_hacia_nadie(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][0]["combatants"][0]["regard"] = {"fantasma": -50}
    with pytest.raises(ScenarioError, match=r"regard hacia 'fantasma', que no está en la escena"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_id_repetido(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][1]["combatants"][0]["id"] = "aria"
    with pytest.raises(ScenarioError, match=r"id repetido 'aria'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)


def test_check_scenario_dos_bandos_con_mismo_id(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    data = _base_aria_lobo_dict()
    data["sides"][1]["id"] = data["sides"][0]["id"]
    with pytest.raises(ScenarioError, match=r"los dos bandos se llaman 'novata'"):
        _guardar_y_cargar_escenario(tmp_path, data, ruleset)
