"""Pruebas del encuentro, iniciativa, defensa, ataques y estados de combate (unidad 09)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.engine.ports import Outcome
from agora.engine.rng import RngSource
from agora.rules.encounter import (
    Action,
    ActionKind,
    Encounter,
    EncounterResult,
    Fighter,
    Status,
)
from agora.rules.policy import StylePolicy
from agora.rules.scene import WeaponSpec, load_scenario
from agora.rules.simulator import fight
from agora.rules.system import load_ruleset
from tests.test_reglas_tirada import Dados

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


class DummyPolicy:
    """Política de juguete para devolver una acción prefijada."""

    def __init__(self, action: Action) -> None:
        self.action = action

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        return self.action

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        return False

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        return False

    def pursues(self, encounter: Encounter, me: Fighter, fleeing: Fighter) -> bool:
        return False


def test_las_reservas_de_aria_y_el_lobo() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    # Aria ataca con 5, defiende con 4, resiste con 3 y ataca con agilidad
    assert enc.attack_pool(aria, lobo, False) == 5
    assert enc.defense_pool(aria) == 4
    assert enc.resist_pool(aria) == 3
    assert enc.approach(aria) == "agilidad"

    # El lobo ataca con agilidad (mordisco ágil)
    assert enc.approach(lobo) == "agilidad"

    # En un_tier, el oso ataca con fuerza: la garra no es ágil
    esc_oso = load_scenario(ESCENARIOS_DIR / "un_tier.yaml", ruleset)
    enc_oso = Encounter(esc_oso, ruleset, RngSource(1312), "test_oso")
    oso = enc_oso.fighters["oso"]
    assert enc_oso.approach(oso) == "fuerza"

    # Con combate_sin_armas y un arma no ágil, alguien con más agilidad que fuerza ataca con fuerza
    combatiente_agil = copy.deepcopy(esc_oso.sides[1].combatants[0])
    combatiente_agil.attributes["fuerza"] = 4  # grado 2
    combatiente_agil.attributes["agilidad"] = 8  # grado 3
    fighter_agil = Fighter(
        spec=combatiente_agil,
        side="oso",
        weapon=WeaponSpec(id="garra", label="garra", base=5, agile=False),
        armor=None,
        vitality=20,
    )
    assert enc_oso.approach(fighter_agil) == "fuerza"


def test_la_defensa_decreciente() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    base_def = enc.defense_pool(aria)
    aria.defenses = 2
    assert enc.defense_pool(aria) == base_def - 2

    aria.total_defense = True
    assert enc.defense_pool(aria) == base_def

    # Tras un _attack el defensor lleva una defensa más
    aria.defenses = 0
    aria.total_defense = False
    enc._attack(lobo, aria, False, Dados(5, 4, 3, 2, 1, 1, 5, 4, 3, 2), StylePolicy(), True)
    assert aria.defenses == 1

    # Al empezar su turno vuelve a 0
    enc._turn(aria, DummyPolicy(Action(ActionKind.TOTAL_DEFENSE)), Dados(1, 1))
    assert aria.defenses == 0


def test_penalizaciones_fisicas() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]

    # Aria a 8/18 pierde 1 dado de ataque
    aria.vitality = 8
    assert enc.physical_penalty(aria) == 1

    # A 4/18 pierde 2 dados
    aria.vitality = 4
    assert enc.physical_penalty(aria) == 2

    # Con fatiga 4/7 (tired_at: 50%), pierde 1
    aria.vitality = 18
    aria.fatigue = 4
    assert enc.physical_penalty(aria) == 1

    # Con fatiga 6/7 (exhausted_at: 75%), pierde 2
    aria.fatigue = 6
    assert enc.physical_penalty(aria) == 2

    # Herida y cansada se suman
    aria.vitality = 8
    aria.fatigue = 4
    assert enc.physical_penalty(aria) == 2


def test_aria_hiere_al_lobo_como_en_el_borrador() -> None:
    # §21.1 ronda 1: _attack con Dados(6,5,3,2,1, 5,4,2,1) deja al lobo a 10 y le da edge == 1
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    enc._attack(aria, lobo, False, Dados(6, 5, 3, 2, 1, 5, 4, 2, 1), StylePolicy(), True)
    assert lobo.vitality == 10
    assert lobo.edge.get("aria") == 1


def test_el_lobo_critica_y_aria_resiste() -> None:
    # §21.1: con edge puesto, Dados(6,6,5,3,2,1, 5,3,2,2, 5,2,1) y StylePolicy:
    # Aria a 13, estrés 2, Ímpetu 1 y el edge del lobo gastado
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    lobo.edge["aria"] = 1

    enc._attack(
        lobo, aria, False,
        Dados(6, 6, 5, 3, 2, 1, 5, 3, 2, 2, 5, 2, 1),
        StylePolicy(), True,
    )
    assert aria.vitality == 13
    assert aria.stress == 2
    assert aria.impetus == 1
    assert "aria" not in lobo.edge


def test_la_garra_del_oso_perfora_con_fuerza() -> None:
    # Un golpe estándar del oso a Aria hace 9 ((5 + 4) - max(0, 1 - 1))
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "un_tier.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    oso = enc.fighters["oso"]

    # Golpe con éxito estándar: oso 6 dados (5, 5, 1, 1, 1, 1), Aria 4 dados (1, 1, 1, 1)
    # Margen 2, éxito estándar, daño = (5 + 4) * 2 // 2 - max(0, 1 - 1) = 9
    vit_antes = aria.vitality
    enc._attack(
        oso, aria, False, Dados(5, 5, 1, 1, 1, 1, 1, 1, 1, 1),
        DummyPolicy(Action(ActionKind.ATTACK)), True,
    )
    assert vit_antes - aria.vitality == 9


def test_la_posicion_desesperada_da_un_contraataque_y_solo_uno() -> None:
    # Aria a 4/18 falla; el lobo contraataca en el acto; contraataque no da edge ni abre otro,
    # y Aria gana 1 de Ímpetu por fallar desesperada
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    aria.vitality = 4  # VitalityBand.GRAVE
    impetus_antes = aria.impetus

    # Aria falla con 3 dados (penalización -2): (1, 2, 3), lobo defiende con 4 dados (5, 5, 1, 1)
    # Lobo contraataca con 6 dados (1, 1, 1, 1, 1, 1), Aria defiende con 2 dados (1, 1)
    enc._attack(
        aria, lobo, False,
        Dados(1, 2, 3, 5, 5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
        StylePolicy(), True,
    )
    assert aria.impetus == impetus_antes + 1
    beats_contra = [b for b in enc.beats if "contraataque" in b.note]
    assert len(beats_contra) == 1
    assert "aria" not in lobo.edge


def _scenario_dos_contra_uno_dict() -> dict[str, Any]:
    raw = yaml.safe_load((ESCENARIOS_DIR / "aria_lobo.yaml").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    data = copy.deepcopy(raw)
    data["sides"][0]["combatants"].append({
        "id": "aliado",
        "label": "Aliado de Aria",
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
    return data


def test_caer_pesa_a_los_suyos(tmp_path: Path) -> None:
    ruleset = load_ruleset(BASE_RULES)
    p = tmp_path / "dos_vs_uno.yaml"
    p.write_text(yaml.safe_dump(_scenario_dos_contra_uno_dict()), encoding="utf-8")
    esc = load_scenario(p, ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    aliado = enc.fighters["aliado"]
    lobo = enc.fighters["lobo"]

    estres_antes = aliado.stress
    impetus_antes = aliado.impetus

    # Lobo ataca a Aria y la tumba: daño mortal (18 PV)
    # 6 dados lobo: (6, 6, 5, 5, 5, 5), Aria 4 dados: (1, 1, 1, 1)
    aria.vitality = 1
    enc._attack(
        lobo, aria, False, Dados(6, 6, 5, 5, 5, 5, 1, 1, 1, 1),
        DummyPolicy(Action(ActionKind.ATTACK)), True,
    )
    assert aria.status is Status.DOWN
    assert aliado.stress == estres_antes + 1
    assert aliado.impetus == impetus_antes + 1


def test_el_quiebre() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]

    # Estrés al tope y éxito de voluntad -> ímpetu lleno y estrés a la mitad
    aria.stress = aria.spec.stress - 1
    enc._stress(aria, 1, Dados(6, 5, 1))
    assert aria.impetus == aria.spec.impetus
    assert aria.stress == aria.spec.stress // 2
    assert aria.status.value == Status.ACTIVE.value

    # Con fallo -> BROKEN y trauma
    aria.stress = aria.spec.stress - 1
    enc._stress(aria, 1, Dados(1, 2, 3))
    assert aria.status.value == Status.BROKEN.value
    assert aria.trauma is True


def test_el_reloj_de_muerte() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    aria.status = Status.DOWN

    # Éxito no avanza el reloj
    enc._death_clock(aria, Dados(6, 5, 4))
    assert aria.death_marks == 0

    # 4 fallos llevan a DEAD
    for _ in range(3):
        enc._death_clock(aria, Dados(1, 1, 1))
    assert aria.death_marks == 3
    assert aria.status.value == Status.DOWN.value

    enc._death_clock(aria, Dados(1, 1, 1))
    assert aria.death_marks == 4
    assert aria.status.value == Status.DEAD.value

    # Estabilizado no tira
    lobo = enc.fighters["lobo"]
    lobo.status = Status.DOWN
    lobo.stabilized = True
    enc._death_clock(lobo, Dados(1, 1))
    assert lobo.death_marks == 0


def test_rematar_exige_exito_pleno() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    lobo.status = Status.DOWN

    # Con coste, sigue DOWN
    enc._finish(aria, lobo, Dados(5, 4, 3, 2, 1))
    assert lobo.status.value == Status.DOWN.value

    # Con éxito pleno, DEAD
    enc._finish(aria, lobo, Dados(5, 5, 4, 3, 2))
    assert lobo.status.value == Status.DEAD.value

    # A tres tiers por encima, nunca (efecto nulo)
    esc3 = load_scenario(ESCENARIOS_DIR / "tres_tiers.yaml", ruleset)
    enc3 = Encounter(esc3, ruleset, RngSource(1312), "test")
    novata = enc3.fighters["aria"]
    campeon = enc3.fighters["campeon"]
    campeon.status = Status.DOWN
    # Novata tier 1 vs Campeón tier 4 (tier_gap = 3) con CRITICAL
    enc3._finish(novata, campeon, Dados(6, 6, 1, 1, 1))
    assert campeon.status is Status.DOWN


def test_las_acciones_legales() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    # Sin caídos no hay FINISH ni FIRST_AID
    legales = enc.legal_actions(aria)
    kinds = {a.kind for a in legales}
    assert ActionKind.FINISH not in kinds
    assert ActionKind.FIRST_AID not in kinds

    # Un colapsado solo puede recuperarse
    aria.fatigue = aria.spec.fatigue
    assert enc.legal_actions(aria) == (Action(ActionKind.RECOVER),)

    # FIRST_AID solo hacia aliados caídos sin estabilizar
    aria.fatigue = 0
    lobo.status = Status.DOWN
    # Lobo es enemigo, no aliado: no da FIRST_AID para Aria
    assert ActionKind.FIRST_AID not in {a.kind for a in enc.legal_actions(aria)}


def test_una_sola_puerta() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]

    # Ataque a quien no está
    with pytest.raises(ValueError, match="acción ilegal"):
        enc._turn(aria, DummyPolicy(Action(ActionKind.ATTACK, "fantasma")), Dados(1, 1))

    # Remate sin caído
    with pytest.raises(ValueError, match="acción ilegal"):
        enc._turn(aria, DummyPolicy(Action(ActionKind.FINISH, "lobo")), Dados(1, 1))

    # Forzarse fuera de ataque
    with pytest.raises(ValueError, match="solo se fuerza al atacar"):
        enc._turn(aria, DummyPolicy(Action(ActionKind.TOTAL_DEFENSE, force=True)), Dados(1, 1))

    # Forzarse exhausto (fatigue 6/7 >= 75% -> exhausted, pero sin colapsar)
    aria.fatigue = 6
    with pytest.raises(ValueError, match="solo se fuerza al atacar"):
        enc._turn(aria, DummyPolicy(Action(ActionKind.ATTACK, "lobo", force=True)), Dados(1, 1))


def test_la_iniciativa() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    # En aria_lobo, iniciativa = [agilidad, instinto]
    # Aria: 8 + 7 = 15; Lobo: 9 + 8 = 17.
    # Desempate es instinto: Lobo tiene 8, Aria 7.
    orden = enc._initiative()
    assert isinstance(orden, tuple)
    assert len(orden) == 2


class CoverPolicy:
    """Se cubre mientras pueda; si colapsa por fatiga, recupera el aliento."""

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        if encounter.collapsed(me):
            return Action(ActionKind.RECOVER)
        return Action(ActionKind.TOTAL_DEFENSE)

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        return False

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        return False

    def pursues(self, encounter: Encounter, me: Fighter, fleeing: Fighter) -> bool:
        return False


def test_el_combate_largo_cansa() -> None:
    ruleset = load_ruleset(BASE_RULES)
    assert ruleset.combat is not None
    esc = load_scenario(ESCENARIOS_DIR / "espejo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    # Con una política que siempre se cubre, cada 4 rondas ganan fatiga
    res = enc.run(CoverPolicy())
    assert res.rounds == ruleset.combat.max_rounds
    for f in enc.fighters.values():
        assert f.fatigue > 0


def test_sin_salida_es_empate() -> None:
    ruleset = load_ruleset(BASE_RULES)
    assert ruleset.combat is not None
    esc = load_scenario(ESCENARIOS_DIR / "espejo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    res = enc.run(CoverPolicy())
    assert res.rounds == ruleset.combat.max_rounds
    assert res.winner is None


def test_el_capricho_tiene_su_flujo() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(777), "enc_test")
    aria = enc.fighters["aria"]
    enc.round = 3
    rng1 = enc.style_rng(aria)
    rng2 = RngSource(777).stream("estilo", "enc_test", 3, aria.id)
    assert rng1.getstate() == rng2.getstate()


def test_un_encuentro_es_reproducible() -> None:
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    r1 = fight(esc, ruleset, 1312, 0)
    r2 = fight(esc, ruleset, 1312, 0)
    r3 = fight(esc, ruleset, 1312, 1)

    assert isinstance(r1, EncounterResult)
    assert r1.winner == r2.winner
    assert r1.rounds == r2.rounds
    assert [b.kind for b in r1.beats] == [b.kind for b in r2.beats]
    assert r1.beats != r3.beats
