"""Pruebas de carga, validación y especificación del sistema de reglas (unidad 08)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.engine.ports import Challenge
from agora.rules.pool import PoolResolver
from agora.rules.system import Ruleset, RulesetError, load_ruleset
from tests.test_reglas_tirada import Dados


def toy_ruleset_dict() -> dict[str, Any]:
    return {
        "id": "juguete",
        "label": "Sistema de juguete",
        "attributes": [
            {"id": "a1", "label": "Atributo 1", "minimum": 1},
            {"id": "a2", "label": "Atributo 2", "minimum": 1},
        ],
        "grades": [
            {"grade": 1, "min_value": 1},
            {"grade": 2, "min_value": 4},
        ],
        "tiers": [
            {"tier": 1, "label": "Tier 1", "min_level": 1, "max_level": 5, "attribute_cap": 3},
            {"tier": 2, "label": "Tier 2", "min_level": 6, "max_level": 10, "attribute_cap": 6},
        ],
        "skills": [
            {"id": "c1", "label": "Competencia 1", "attribute": "a1", "approaches": ["a2"]},
        ],
    }


def _guardar_y_cargar(tmp_path: Path, data: dict[str, Any]) -> Ruleset:
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_ruleset(p)


def test_el_sistema_de_la_mesa_carga() -> None:
    # rules/base/rules.yaml carga, con 7 atributos, 6 grados, 5 tiers, 18 competencias
    # y los valores por defecto de pool y vitality.
    ruleset = load_ruleset(Path("rules/base/rules.yaml"))
    assert len(ruleset.attributes) == 7
    assert len(ruleset.grades) == 6
    assert len(ruleset.tiers) == 5
    assert len(ruleset.skills) == 18
    assert ruleset.pool.cap == 6
    assert ruleset.pool.overflow_cap == 2
    assert ruleset.pool.resist_stress == 3
    assert ruleset.vitality.wounded_below == 50
    assert ruleset.vitality.grave_below == 25


def test_un_atributo_desconocido_en_una_competencia_no_carga(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["skills"][0]["attribute"] = "fantasma"
    with pytest.raises(RulesetError, match="atributo desconocido"):
        _guardar_y_cargar(tmp_path, data)


def test_un_enfoque_desconocido_no_carga(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["skills"][0]["approaches"] = ["fantasma"]
    with pytest.raises(RulesetError, match="atributo desconocido"):
        _guardar_y_cargar(tmp_path, data)


def test_el_atributo_por_defecto_como_enfoque_no_carga(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["skills"][0]["approaches"] = ["a1"]
    with pytest.raises(RulesetError, match="es a la vez el atributo y un enfoque"):
        _guardar_y_cargar(tmp_path, data)


def test_ids_repetidos_no_cargan(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["attributes"].append({"id": "a1", "label": "Atributo 1 duplicado", "minimum": 1})
    with pytest.raises(RulesetError, match="id repetido"):
        _guardar_y_cargar(tmp_path, data)


def test_grados_que_no_crecen_no_cargan(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["grades"][1]["min_value"] = 1
    with pytest.raises(RulesetError, match="min_value del grado"):
        _guardar_y_cargar(tmp_path, data)


def test_grados_con_hueco_no_cargan(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["grades"][1]["grade"] = 3
    with pytest.raises(RulesetError, match="grados van de uno en uno"):
        _guardar_y_cargar(tmp_path, data)


def test_tiers_con_hueco_de_niveles_no_cargan(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["tiers"][1]["min_level"] = 7
    with pytest.raises(RulesetError, match="no empieza justo después"):
        _guardar_y_cargar(tmp_path, data)


def test_un_techo_que_baja_no_carga(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["tiers"][1]["attribute_cap"] = 2
    with pytest.raises(RulesetError, match=r"techo del tier .* baja"):
        _guardar_y_cargar(tmp_path, data)


def test_umbrales_de_vitalidad_al_reves_no_cargan(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["vitality"] = {"wounded_below": 25, "grave_below": 50}
    with pytest.raises(
        RulesetError, match=r"grave_below .* tiene que quedar por debajo de wounded_below"
    ):
        _guardar_y_cargar(tmp_path, data)


def test_un_campo_desconocido_no_carga(tmp_path: Path) -> None:
    data = toy_ruleset_dict()
    data["campo_inventado"] = 123
    with pytest.raises(RulesetError, match="Extra inputs are not permitted"):
        _guardar_y_cargar(tmp_path, data)


def test_los_topes_salen_del_sistema(tmp_path: Path) -> None:
    # Un sistema con pool.cap: 4 y overflow_cap: 1 da un PoolResolver que pide 4 dados con pool=9
    # y deja overflow == 1.
    data = toy_ruleset_dict()
    data["pool"] = {"cap": 4, "overflow_cap": 1}
    ruleset = _guardar_y_cargar(tmp_path, data)
    resolver = PoolResolver.from_ruleset(ruleset)

    dados = Dados(5, 5, 5, 5)
    res = resolver.resolve(Challenge(pool=9), dados)
    assert len(res.dice) == 4
    assert res.overflow == 1
    assert len(dados.caras) == 0
