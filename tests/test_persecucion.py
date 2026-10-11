"""Pruebas de persecución, huida y rendición (D-165, unidad 13)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from agora.engine.ports import Outcome
from agora.engine.rng import RngSource
from agora.rules.encounter import (
    Action,
    ActionKind,
    Encounter,
    Fighter,
    Status,
)
from agora.rules.policy import StylePolicy
from agora.rules.scene import (
    CombatStyle,
    FinishOff,
    load_scenario,
)
from agora.rules.system import Ruleset, load_ruleset
from tests.test_reglas_tirada import Dados

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


class DummyPolicy:
    """Política de prueba que permite prefijar respuestas."""

    def __init__(
        self,
        action: Action | None = None,
        pursues_val: bool = True,
        finishes_val: bool = False,
    ) -> None:
        self.action = action
        self.pursues_val = pursues_val
        self.finishes_val = finishes_val

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        assert self.action is not None
        return self.action

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        return False

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        return self.finishes_val

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        return self.pursues_val


def test_nadie_persigue_y_se_va() -> None:
    """Con un perseguidor cuyo estilo no persigue, huir sale sin tirar
    (FLED, nota «nadie le persigue»).
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    lobo = enc.fighters["lobo"]
    policy = DummyPolicy(pursues_val=False)

    enc._flee(lobo, Dados(), policy)

    assert lobo.status is Status.FLED
    assert any("nadie le persigue" in (b.note or "") for b in enc.beats)


def test_los_relojes_de_la_persecucion() -> None:
    """Con dados escritos, un pleno suma 2 a escapar; un con coste suma 1 y 1
    y trae un golpe de oportunidad; un fallo suma 2 a alcanzar y trae el golpe.
    Escapar lleno -> FLED.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    policy = DummyPolicy(pursues_val=True)

    # 1. Pleno: lobo 2 éxitos (5,5,1), aria 0 (1,1,1) -> diff 2 -> SUCCESS (+2 escape)
    enc1 = Encounter(esc, ruleset, RngSource(1312), "test1")
    lobo1 = enc1.fighters["lobo"]
    enc1._flee(lobo1, Dados(5, 5, 1, 1, 1, 1), policy)
    assert lobo1.escape == 2
    assert lobo1.caught == 0
    assert lobo1.status == Status.ACTIVE

    # Segundo pleno llena el reloj (chase_clock = 3) -> Status.FLED
    enc1._flee(lobo1, Dados(5, 5, 1, 1, 1, 1), policy)
    lobo_fled = enc1.fighters["lobo"]
    assert lobo_fled.escape == 4
    assert lobo_fled.status == Status.FLED

    # 2. Con coste: lobo 1 éxito (5,1,1), aria 0 (1,1,1) -> diff 1 -> SUCCESS_AT_COST
    # (+1 escape, +1 caught, golpe de oportunidad: aria 5 dados, lobo 4 defensa)
    enc2 = Encounter(esc, ruleset, RngSource(1312), "test2")
    lobo2 = enc2.fighters["lobo"]
    dados_coste = Dados(5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    enc2._flee(lobo2, dados_coste, policy)
    assert lobo2.escape == 1
    assert lobo2.caught == 1
    assert any("golpe de oportunidad" in b.note for b in enc2.beats)

    # 3. Fallo: lobo 0 éxitos (1,1,1), aria 1 éxito (5,1,1) -> diff -1 -> FAILURE
    # (+0 escape, +2 caught, golpe de oportunidad)
    enc3 = Encounter(esc, ruleset, RngSource(1312), "test3")
    lobo3 = enc3.fighters["lobo"]
    dados_fallo = Dados(1, 1, 1, 5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    enc3._flee(lobo3, dados_fallo, policy)
    assert lobo3.escape == 0
    assert lobo3.caught == 2
    assert any("golpe de oportunidad" in b.note for b in enc3.beats)


def test_alcanzado_no_puede_huir() -> None:
    """Con alcanzar lleno, FLEE no está en legal_actions, y pedirlo es ValueError."""
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    lobo = enc.fighters["lobo"]
    lobo.caught = enc.combat.chase_clock

    assert Action(ActionKind.FLEE) not in enc.legal_actions(lobo)
    with pytest.raises(ValueError, match="acción ilegal"):
        enc._turn(lobo, DummyPolicy(Action(ActionKind.FLEE)), Dados())


def test_el_golpe_de_oportunidad_se_llama_asi() -> None:
    """El Beat lleva la nota «golpe de oportunidad» y no abre otro contraataque."""
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    lobo = enc.fighters["lobo"]
    policy = DummyPolicy(pursues_val=True)

    # Tirada con fallo en huida para provocar golpe de oportunidad de Aria
    # Aria tira 5 dados con un éxito (5,1,1,1,1), lobo tira 4 dados con 0 (1,1,1,1)
    dados = Dados(1, 1, 1, 5, 1, 1, 5, 1, 1, 1, 1, 1, 1, 1, 1)
    enc._flee(lobo, dados, policy)

    notas_golpe = [b.note for b in enc.beats if b.note and "golpe de oportunidad" in b.note]
    assert len(notas_golpe) == 1


def test_sin_competencia_de_persecucion_huir_es_gratis() -> None:
    """Un sistema sin chase_skill se comporta como en la 09."""
    ruleset_dict = load_ruleset(BASE_RULES).model_dump()
    ruleset_dict["combat"]["chase_skill"] = None
    ruleset_sin_chase = Ruleset.model_validate(ruleset_dict)

    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset_sin_chase)
    enc = Encounter(esc, ruleset_sin_chase, RngSource(1312), "test")
    lobo = enc.fighters["lobo"]
    policy = DummyPolicy(pursues_val=True)

    enc._flee(lobo, Dados(), policy)
    assert lobo.status is Status.FLED
    assert any("nadie le persigue" in (b.note or "") for b in enc.beats)


def test_rendirse_exige_que_lo_acepten() -> None:
    """Si un rival remataría (finish_off: siempre), la rendición se rechaza (nota)
    y el que se rinde sigue ACTIVE con refused; si nadie remataría, SURRENDERED.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)

    # 1. Rival rechaza rendición
    enc1 = Encounter(esc, ruleset, RngSource(1312), "test1")
    lobo1 = enc1.fighters["lobo"]
    policy_rechaza = DummyPolicy(finishes_val=True)
    enc1._surrender(lobo1, policy_rechaza)
    assert lobo1.status is Status.ACTIVE
    assert lobo1.refused is True
    assert any("rechazada por aria" in (b.note or "") for b in enc1.beats)

    # 2. Rival acepta rendición
    enc2 = Encounter(esc, ruleset, RngSource(1312), "test2")
    lobo2 = enc2.fighters["lobo"]
    policy_acepta = DummyPolicy(finishes_val=False)
    enc2._surrender(lobo2, policy_acepta)
    assert lobo2.status is Status.SURRENDERED
    assert lobo2.refused is False


def test_el_estilo_huye_se_rinde_y_luego_pelea() -> None:
    """Por debajo de su umbral, el estilo huye; alcanzado, se rinde;
    rechazado, ataca.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    lobo = enc.fighters["lobo"]
    policy = StylePolicy()

    # Umbral de huida: forzamos vitalidad baja (vitality = 1)
    lobo.vitality = 1

    # Caso 1: puede huir y no está alcanzado -> huye
    lobo.caught = 0
    lobo.refused = False
    assert policy.choose(enc, lobo) == Action(ActionKind.FLEE)

    # Caso 2: alcanzado (caught lleno) -> no puede huir, se rinde
    lobo.caught = enc.combat.chase_clock
    lobo.refused = False
    assert policy.choose(enc, lobo) == Action(ActionKind.SURRENDER)

    # Caso 3: alcanzado y rendición ya rechazada -> pelea por su vida (ataca)
    lobo.refused = True
    accion = policy.choose(enc, lobo)
    assert accion.kind is ActionKind.ATTACK


def test_quien_persigue() -> None:
    """Agresivo, quien remata siempre o quien odia al que huye, persigue;
    los demás no.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    policy = StylePolicy()

    def fabricar_aria(
        aggression: int = 30,
        finish_off: FinishOff = FinishOff.NEVER,
        regard: int = 0,
    ) -> Fighter:
        f = copy.copy(aria)
        f.spec = aria.spec.model_copy(
            update={
                "style": CombatStyle(aggression=aggression, finish_off=finish_off),
                "regard": {lobo.id: regard},
            }
        )
        return f

    # 1. Agresivo persigue
    assert policy.pursues(enc, fabricar_aria(aggression=60), lobo) is True

    # 2. Quien remata siempre persigue
    assert policy.pursues(enc, fabricar_aria(finish_off=FinishOff.ALWAYS), lobo) is True

    # 3. Quien odia persigue
    assert policy.pursues(enc, fabricar_aria(regard=-10), lobo) is True

    # 4. Pacífico sin odio ni rematar no persigue
    assert (
        policy.pursues(enc, fabricar_aria(aggression=20, finish_off=FinishOff.NEVER), lobo)
        is False
    )
