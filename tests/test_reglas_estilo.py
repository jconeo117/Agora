"""Pruebas del estilo de combate como política de decisión (unidad 09)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from agora.engine.ports import Outcome
from agora.engine.rng import RngSource
from agora.rules.encounter import (
    ActionKind,
    Encounter,
    Fighter,
    Status,
)
from agora.rules.policy import StylePolicy
from agora.rules.scene import FinishOff, TargetChoice, load_scenario
from agora.rules.system import load_ruleset

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


def _set_style(fighter: Fighter, **kwargs: Any) -> None:
    fighter.spec = fighter.spec.model_copy(
        update={"style": fighter.spec.style.model_copy(update=kwargs)}
    )


def _set_regard(fighter: Fighter, regard: dict[str, int]) -> None:
    fighter.spec = fighter.spec.model_copy(update={"regard": regard})


def test_huye_por_debajo_de_su_umbral() -> None:
    # FLEE; exhausto, SURRENDER; con flee_below: 0, nunca. Con whim: 100 sigue huyendo (el orden).
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    policy = StylePolicy()

    # flee_below: 25% en 18 PV -> 4.5 PV. Con 4 PV huye.
    _set_style(aria, flee_below=25)
    aria.vitality = 4
    act = policy.choose(enc, aria)
    assert act.kind is ActionKind.FLEE

    # Si está exhausto (fatigue 6/7 >= 75%), SURRENDER
    aria.fatigue = 6
    act_surrender = policy.choose(enc, aria)
    assert act_surrender.kind is ActionKind.SURRENDER

    # Con flee_below: 0, nunca huye ni se rinde
    _set_style(aria, flee_below=0)
    aria.fatigue = 0
    aria.vitality = 1
    act_no_flee = policy.choose(enc, aria)
    assert act_no_flee.kind is not ActionKind.FLEE
    assert act_no_flee.kind is not ActionKind.SURRENDER

    # Con whim: 100 y flee_below: 25, si está bajo de PV sigue huyendo (orden 1 antes que 2)
    enc_whim = Encounter(esc, ruleset, RngSource(2), "test")
    aria_w = enc_whim.fighters["aria"]
    _set_style(aria_w, flee_below=25, whim=100)
    aria_w.vitality = 4
    act_whim_flee = policy.choose(enc_whim, aria_w)
    assert act_whim_flee.kind is ActionKind.FLEE


def test_el_capricho() -> None:
    # whim: 100 elige entre las legales, de forma reproducible; whim: 0 no toca style_rng
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc1 = Encounter(esc, ruleset, RngSource(1312), "test_whim")
    aria1 = enc1.fighters["aria"]
    _set_style(aria1, whim=100)
    policy = StylePolicy()

    act1 = policy.choose(enc1, aria1)
    assert act1 in enc1.legal_actions(aria1)

    enc2 = Encounter(esc, ruleset, RngSource(1312), "test_whim")
    aria2 = enc2.fighters["aria"]
    _set_style(aria2, whim=100)
    act2 = policy.choose(enc2, aria2)
    assert act1 == act2


def test_rematar_es_suyo(tmp_path: Path) -> None:
    # siempre remata a un caído; si_le_odia, solo con regard < 0; nunca, jamás.
    # Lo mismo en finishes, al cerrar.
    enc = _scenario_uno_vs_dos(tmp_path)
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    lobo_alfa = enc.fighters["lobo_alfa"]
    lobo.status = Status.DOWN
    lobo_alfa.status = Status.ACTIVE
    policy = StylePolicy()

    # finish_off: SIEMPRE
    _set_style(aria, finish_off=FinishOff.ALWAYS)
    act = policy.choose(enc, aria)
    assert act.kind is ActionKind.FINISH
    assert act.target == "lobo"
    assert policy.finishes(enc, aria, lobo) is True

    # finish_off: NUNCA
    _set_style(aria, finish_off=FinishOff.NEVER)
    act_never = policy.choose(enc, aria)
    assert act_never.kind is not ActionKind.FINISH
    assert act_never.target == "lobo_alfa"
    assert policy.finishes(enc, aria, lobo) is False

    # finish_off: SI_LE_ODIA
    _set_style(aria, finish_off=FinishOff.HATED)
    _set_regard(aria, {"lobo": 0, "lobo_alfa": 0})
    assert policy.finishes(enc, aria, lobo) is False
    assert policy.choose(enc, aria).kind is not ActionKind.FINISH

    _set_regard(aria, {"lobo": -10, "lobo_alfa": 0})
    assert policy.finishes(enc, aria, lobo) is True
    assert policy.choose(enc, aria).kind is ActionKind.FINISH
    assert policy.choose(enc, aria).target == "lobo"

    # Al cerrar: con NEVER no remata; con ALWAYS sí intenta rematar
    enc_cierre = _scenario_uno_vs_dos(tmp_path)
    aria_c = enc_cierre.fighters["aria"]
    lobo_c = enc_cierre.fighters["lobo"]
    enc_cierre.fighters["lobo_alfa"].status = Status.FLED
    lobo_c.status = Status.DOWN
    _set_style(aria_c, finish_off=FinishOff.NEVER)
    enc_cierre._close(policy)
    assert lobo_c.status is Status.DOWN


def _scenario_aliado_caido(tmp_path: Path) -> Encounter:
    ruleset = load_ruleset(BASE_RULES)
    raw = yaml.safe_load((ESCENARIOS_DIR / "aria_lobo.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    data = copy.deepcopy(raw)
    data["sides"][0]["combatants"].append({
        "id": "aliado",
        "label": "Aliado",
        "tier": 1,
        "attributes": {
            "fuerza": 6, "agilidad": 6, "ingenio": 4, "instinto": 6,
            "voluntad": 5, "presencia": 4, "resonancia": 0,
        },
        "skills": {"armas_cuerpo_a_cuerpo": 1, "defensa": 1},
        "attack_skill": "armas_cuerpo_a_cuerpo",
        "weapon": "espada_corta",
        "vitality": 18,
        "fatigue": 7,
        "stress": 8,
        "impetus": 5,
        "style": {"aggression": 50, "flee_below": 0},
    })
    p = tmp_path / "aliado_caido.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    esc = load_scenario(p, ruleset)
    return Encounter(esc, ruleset, RngSource(1312), "test")


def test_la_agresividad(tmp_path: Path) -> None:
    # con 49, socorre a un aliado caído, recupera el aliento exhausto y se cubre grave;
    # con 50, ataca en los tres casos.
    enc = _scenario_aliado_caido(tmp_path)
    aria = enc.fighters["aria"]
    aliado = enc.fighters["aliado"]
    aliado.status = Status.DOWN
    policy = StylePolicy()

    # 1. Aliado caído:
    _set_style(aria, aggression=49)
    act = policy.choose(enc, aria)
    assert act.kind is ActionKind.FIRST_AID
    assert act.target == "aliado"

    _set_style(aria, aggression=50)
    act50 = policy.choose(enc, aria)
    assert act50.kind is ActionKind.ATTACK

    # 2. Exhausto (sin aliado caído):
    aliado.status = Status.ACTIVE
    aria.fatigue = 6
    _set_style(aria, aggression=49)
    assert policy.choose(enc, aria).kind is ActionKind.RECOVER

    _set_style(aria, aggression=50)
    assert policy.choose(enc, aria).kind is ActionKind.ATTACK

    # 3. Grave (sin aliado caído, sin estar exhausto):
    aria.fatigue = 0
    aria.vitality = 4  # VitalityBand.GRAVE
    _set_style(aria, aggression=49)
    assert policy.choose(enc, aria).kind is ActionKind.TOTAL_DEFENSE

    _set_style(aria, aggression=50)
    assert policy.choose(enc, aria).kind is ActionKind.ATTACK


def test_forzarse() -> None:
    # con 70 y sin cansancio, force=True; cansado, no; con 69, no.
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    policy = StylePolicy()

    _set_style(aria, aggression=70)
    aria.fatigue = 0
    act70 = policy.choose(enc, aria)
    assert act70.kind is ActionKind.ATTACK
    assert act70.force is True

    # Cansado (fatigue 4/7 >= 50%): force=False
    aria.fatigue = 4
    act_cansado = policy.choose(enc, aria)
    assert act_cansado.force is False

    # Con 69: force=False
    aria.fatigue = 0
    _set_style(aria, aggression=69)
    act69 = policy.choose(enc, aria)
    assert act69.force is False


def _scenario_uno_vs_dos(tmp_path: Path) -> Encounter:
    ruleset = load_ruleset(BASE_RULES)
    raw = yaml.safe_load((ESCENARIOS_DIR / "aria_lobo.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    data = copy.deepcopy(raw)
    data["sides"][1]["combatants"].append({
        "id": "lobo_alfa",
        "label": "Lobo Alfa",
        "tier": 2,
        "attributes": {
            "fuerza": 8, "agilidad": 10, "ingenio": 3, "instinto": 10,
            "voluntad": 6, "presencia": 4, "resonancia": 0,
        },
        "skills": {"combate_sin_armas": 3, "defensa": 2},
        "attack_skill": "combate_sin_armas",
        "weapon": "mordisco",
        "vitality": 24,
        "fatigue": 8,
        "stress": 10,
        "impetus": 6,
        "style": {"aggression": 60, "flee_below": 25},
    })
    p = tmp_path / "uno_vs_dos.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    esc = load_scenario(p, ruleset)
    return Encounter(esc, ruleset, RngSource(1312), "test")


def test_a_quien_apunta(tmp_path: Path) -> None:
    # mas_debil (menor % de Vitalidad), mas_fuerte (mayor tier) y peor_le_cae (menor regard,
    # a igualdad el más débil), en un escenario de uno contra dos
    enc = _scenario_uno_vs_dos(tmp_path)
    aria = enc.fighters["aria"]
    lobo1 = enc.fighters["lobo"]  # tier 1, vit 17
    alfa = enc.fighters["lobo_alfa"]  # tier 2, vit 24
    policy = StylePolicy()

    # 1. mas_debil:
    lobo1.vitality = 10  # 10/17 = 58%
    alfa.vitality = 20  # 20/24 = 83%
    _set_style(aria, target=TargetChoice.WEAKEST)
    assert policy.choose(enc, aria).target == "lobo"

    lobo1.vitality = 16  # 16/17 = 94%
    alfa.vitality = 10  # 10/24 = 41%
    assert policy.choose(enc, aria).target == "lobo_alfa"

    # 2. mas_fuerte: elige mayor tier (alfa tier 2 vs lobo tier 1)
    _set_style(aria, target=TargetChoice.STRONGEST)
    assert policy.choose(enc, aria).target == "lobo_alfa"

    # 3. peor_le_cae:
    _set_style(aria, target=TargetChoice.HATED)
    _set_regard(aria, {"lobo": 10, "lobo_alfa": -20})
    assert policy.choose(enc, aria).target == "lobo_alfa"

    _set_regard(aria, {"lobo": -30, "lobo_alfa": -20})
    assert policy.choose(enc, aria).target == "lobo"


def test_cuando_resiste() -> None:
    # un crítico, sí; un golpe que lo deja grave o caído, sí; uno leve, no;
    # sin estrés para el peor caso, nunca
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    policy = StylePolicy()

    # Crítico siempre resiste si hay margen de estrés
    aria.vitality = 18
    aria.stress = 0
    assert policy.resists(enc, aria, hit=2, outcome=Outcome.CRITICAL) is True

    # Golpe que deja grave (4 PV o menos): resiste aunque no sea crítico
    assert policy.resists(enc, aria, hit=15, outcome=Outcome.SUCCESS) is True

    # Golpe leve (de 18 a 15 PV -> HEALTHY): no resiste
    assert policy.resists(enc, aria, hit=3, outcome=Outcome.SUCCESS) is False

    # Sin estrés para el peor caso (stress + resist_stress >= spec.stress):
    # resist_stress es 3, spec.stress es 8. Con stress = 5, 5 + 3 >= 8 -> nunca resiste
    aria.stress = 5
    assert policy.resists(enc, aria, hit=15, outcome=Outcome.CRITICAL) is False
