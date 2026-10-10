"""Pruebas de las fórmulas de recursos y capacidades del sistema (unidad 11, §B.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.rules.system import (
    FormulaSpec,
    RulesetError,
    TermSource,
    TermSpec,
    load_ruleset,
)

BASE_RULES = Path("rules/base/rules.yaml")



def test_las_formulas_del_borrador() -> None:
    # Aria (§21.1): F 6, V 5, Aguante 1
    # Ren (§22): F 22, V 26, Aguante 3
    ruleset = load_ruleset(BASE_RULES)
    assert ruleset.resources is not None

    aria_vals = {"fuerza": 6, "voluntad": 5}
    aria_skills = {"aguante": 1}
    assert ruleset.evaluate(ruleset.resources.vitality, aria_vals, aria_skills) == 18
    assert ruleset.evaluate(ruleset.resources.fatigue, aria_vals, aria_skills) == 7
    assert ruleset.evaluate(ruleset.resources.stress, aria_vals, aria_skills) == 8
    assert ruleset.evaluate(ruleset.resources.impetus, aria_vals, aria_skills) == 5

    ren_vals = {"fuerza": 22, "voluntad": 26}
    ren_skills = {"aguante": 3}
    assert ruleset.evaluate(ruleset.resources.vitality, ren_vals, ren_skills) == 45
    assert ruleset.evaluate(ruleset.resources.fatigue, ren_vals, ren_skills) == 13
    assert ruleset.evaluate(ruleset.resources.stress, ren_vals, ren_skills) == 12
    assert ruleset.evaluate(ruleset.resources.impetus, ren_vals, ren_skills) == 9


def test_el_suelo_es_por_termino() -> None:
    ruleset = load_ruleset(BASE_RULES)
    # 10 + ⌊5/2⌋ da 12, no 12.5 ni 13
    formula_simple = FormulaSpec(
        base=10,
        terms=(TermSpec(source=TermSource.VALUE, id="voluntad", num=1, den=2),),
    )
    assert ruleset.evaluate(formula_simple, {"voluntad": 5}, {}) == 12

    # El suelo es por término: si hay dos términos fraccionarios de 5/2,
    # ⌊5/2⌋ + ⌊5/2⌋ = 2 + 2 = 4 (total 14).
    # Si se dividiera la suma: (5 + 5) // 2 = 5 (total 15).
    # Esta aserción garantiza que M1 enrojece.
    formula_doble = FormulaSpec(
        base=10,
        terms=(
            TermSpec(source=TermSource.VALUE, id="fuerza", num=1, den=2),
            TermSpec(source=TermSource.VALUE, id="voluntad", num=1, den=2),
        ),
    )
    assert ruleset.evaluate(formula_doble, {"fuerza": 5, "voluntad": 5}, {}) == 14


def test_una_formula_con_un_id_desconocido_no_carga(tmp_path: Path) -> None:
    raw = yaml.safe_load(BASE_RULES.read_text(encoding="utf-8"))

    def cargar(data: dict[str, Any]) -> None:
        p = tmp_path / "rules.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        load_ruleset(p)

    # 1. Atributo desconocido en valor
    raw_attr = yaml.safe_load(yaml.safe_dump(raw))
    raw_attr["resources"]["vitality"]["terms"].append(
        {"source": "valor", "id": "fantasma"}
    )
    with pytest.raises(RulesetError, match="valor desconocido 'fantasma'"):
        cargar(raw_attr)

    # 2. Atributo desconocido en grado
    raw_grado = yaml.safe_load(yaml.safe_dump(raw))
    raw_grado["resources"]["fatigue"]["terms"].append(
        {"source": "grado", "id": "fantasma"}
    )
    with pytest.raises(RulesetError, match="grado desconocido 'fantasma'"):
        cargar(raw_grado)

    # 3. Competencia desconocida
    raw_comp = yaml.safe_load(yaml.safe_dump(raw))
    raw_comp["resources"]["fatigue"]["terms"].append(
        {"source": "competencia", "id": "hechiceria"}
    )
    with pytest.raises(RulesetError, match="competencia desconocido 'hechiceria'"):
        cargar(raw_comp)

