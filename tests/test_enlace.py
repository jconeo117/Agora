"""Pruebas del enlace entre mundo y sistema de rol (unidad 11, §B.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agora.engine.pack import load_pack
from agora.rules.binding import (
    BindingError,
    BindingSpec,
    SignalKind,
    check_binding,
    load_binding,
    parse_signal,
    role_label,
)
from agora.rules.system import load_ruleset

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
CONFLUENCIA_BINDING = Path("packs/confluencia/reglas/base.yaml")



def test_el_enlace_de_confluencia_carga() -> None:
    pack = load_pack(CONFLUENCIA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(CONFLUENCIA_BINDING, pack, ruleset)
    assert binding.system == "base"
    assert len(binding.potentials) == 7
    assert len(binding.weapons) >= 1
    assert len(binding.roles) >= 1


def test_parse_signal() -> None:
    assert parse_signal("rasgo:audacia") == (SignalKind.TRAIT, "audacia")
    assert parse_signal("rango:dominio") == (SignalKind.RANK, "dominio")
    assert parse_signal("eje:dinero") == (SignalKind.NEED, "dinero")
    assert parse_signal("temperamento:temperature") == (SignalKind.TEMPERAMENT, "temperature")

    with pytest.raises(ValueError):
        parse_signal("desconocido:algo")


def test_check_binding_detecta_incompatibilidades(tmp_path: Path) -> None:
    pack = load_pack(CONFLUENCIA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    raw = yaml.safe_load(CONFLUENCIA_BINDING.read_text(encoding="utf-8"))

    # 1. Sistema que no es el cargado (cubre M14)
    raw_sys = dict(raw)
    raw_sys["system"] = "otro_sistema"
    b_sys = BindingSpec.model_validate(raw_sys)
    probs = check_binding(b_sys, pack, ruleset)
    assert any("enlaza con el sistema 'otro_sistema' y no con 'base'" in p for p in probs)

    # 2. Atributo sin potencial
    raw_attr = yaml.safe_load(yaml.safe_dump(raw))
    del raw_attr["potentials"]["fuerza"]
    b_attr = BindingSpec.model_validate(raw_attr)
    probs = check_binding(b_attr, pack, ruleset)
    assert any("potentials: hacen falta exactamente los atributos" in p for p in probs)

    # 3. Rasgo que no existe en formas lineales (cubre M13)
    raw_trait = yaml.safe_load(yaml.safe_dump(raw))
    raw_trait["potentials"]["fuerza"]["terms"]["rasgo:fantasma"] = 1.0
    b_trait = BindingSpec.model_validate(raw_trait)
    probs = check_binding(b_trait, pack, ruleset)
    assert any("'rasgo:fantasma' no existe en este mundo" in p for p in probs)

    # 4. Eje que no existe
    raw_eje = yaml.safe_load(yaml.safe_dump(raw))
    raw_eje["resources"]["vitality"] = "fantasma"
    b_eje = BindingSpec.model_validate(raw_eje)
    probs = check_binding(b_eje, pack, ruleset)
    assert any("resources: eje desconocido 'fantasma'" in p for p in probs)

    # 5. Perilla de temperamento que no existe
    raw_temp = yaml.safe_load(yaml.safe_dump(raw))
    raw_temp["style"]["whim"]["terms"] = {"temperamento:fantasma": 1.0}
    b_temp = BindingSpec.model_validate(raw_temp)
    probs = check_binding(b_temp, pack, ruleset)
    assert any("'temperamento:fantasma' no existe en este mundo" in p for p in probs)

    # 6. Señal sin tipo conocido
    raw_sintipo = yaml.safe_load(yaml.safe_dump(raw))
    raw_sintipo["level"]["terms"] = {"sintipo_invalido": 1.0}
    b_sintipo = BindingSpec.model_validate(raw_sintipo)
    probs = check_binding(b_sintipo, pack, ruleset)
    assert any("señal 'sintipo_invalido' sin tipo conocido" in p for p in probs)

    # 7. rank_of sobre un eje sin rangos
    raw_rank = yaml.safe_load(yaml.safe_dump(raw))
    raw_rank["growth"]["rank_of"] = "salud"  # salud no tiene rangos
    b_rank = BindingSpec.model_validate(raw_rank)
    probs = check_binding(b_rank, pack, ruleset)
    assert any("growth.rank_of: 'salud' no es un eje con rangos" in p for p in probs)

    # 8. Competencia desconocida en skills y en weapons
    raw_skill = yaml.safe_load(yaml.safe_dump(raw))
    raw_skill["skills"]["hechiceria"] = {"terms": {"rasgo:fuerza": 1.0}}
    b_skill = BindingSpec.model_validate(raw_skill)
    probs = check_binding(b_skill, pack, ruleset)
    assert any("skills: competencia desconocida 'hechiceria'" in p for p in probs)

    raw_wskill = yaml.safe_load(yaml.safe_dump(raw))
    raw_wskill["weapons"][0]["skill"] = "hechiceria"
    b_wskill = BindingSpec.model_validate(raw_wskill)
    probs = check_binding(b_wskill, pack, ruleset)
    assert any("competencia desconocida 'hechiceria'" in p for p in probs)

    # 9. Pieza repetida
    raw_rep = yaml.safe_load(yaml.safe_dump(raw))
    raw_rep["weapons"].append(raw_rep["weapons"][0])
    b_rep = BindingSpec.model_validate(raw_rep)
    probs = check_binding(b_rep, pack, ruleset)
    assert any("pieza repetida" in p for p in probs)

    # 10. requires sobre un atributo desconocido
    raw_req = yaml.safe_load(yaml.safe_dump(raw))
    raw_req["weapons"][0]["requires"] = {"fantasma": 3}
    b_req = BindingSpec.model_validate(raw_req)
    probs = check_binding(b_req, pack, ruleset)
    assert any("requires de un atributo desconocido 'fantasma'" in p for p in probs)

    # 11. Rol con un atributo desconocido
    raw_rol = yaml.safe_load(yaml.safe_dump(raw))
    raw_rol["roles"].append({"attributes": ["fuerza", "fantasma"], "label": "titan"})
    b_rol = BindingSpec.model_validate(raw_rol)
    probs = check_binding(b_rol, pack, ruleset)
    assert any("roles.titan: atributo desconocido 'fantasma'" in p for p in probs)


def test_load_binding_lanza_binding_error(tmp_path: Path) -> None:
    pack = load_pack(CONFLUENCIA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    raw = yaml.safe_load(CONFLUENCIA_BINDING.read_text(encoding="utf-8"))
    raw["system"] = "sistema_incompatible"

    p = tmp_path / "invalido.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(BindingError, match="no casa con 'confluencia' y 'base'"):
        load_binding(p, pack, ruleset)


def test_role_label() -> None:
    pack = load_pack(CONFLUENCIA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(CONFLUENCIA_BINDING, pack, ruleset)
    etiquetas = {a.id: a.label for a in ruleset.attributes}

    # Pareja que existe en la tabla de roles
    assert role_label(binding, "fuerza", "agilidad", etiquetas) == "luchador"
    assert role_label(binding, "agilidad", "fuerza", etiquetas) == "luchador"

    # Pareja hipotética sin entrada específica
    binding_vacio = binding.model_copy(update={"roles": ()})
    assert (
        role_label(binding_vacio, "fuerza", "agilidad", etiquetas)
        == "fuerza y agilidad"
    )
