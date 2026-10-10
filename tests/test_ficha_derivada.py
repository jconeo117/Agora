"""Pruebas de la derivación de fichas mecánicas del mundo (unidad 11, §B.3)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from agora.engine.ontology import AgentId, NeedId, TraitId
from agora.engine.pack import load_pack
from agora.engine.state import Bond, WorldState
from agora.engine.world import Simulation
from agora.rules.binding import BindingSpec, load_binding
from agora.rules.derive import census, derive, duel, signal
from agora.rules.encounter import attack_approach
from agora.rules.scene import (
    CombatantSpec,
    CombatStyle,
    FinishOff,
    ScenarioSpec,
    SideSpec,
    TargetChoice,
    WeaponSpec,
    check_scenario,
)
from agora.rules.system import Ruleset, load_ruleset
from tests.test_reanudar import foto

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
CONFLUENCIA_BINDING = Path("packs/confluencia/reglas/base.yaml")


@pytest.fixture
def base_setup() -> tuple[WorldState, Simulation, Ruleset, BindingSpec]:
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(CONFLUENCIA_BINDING, pack, ruleset)
    return sim.state, sim, ruleset, binding


def test_el_potencial_sale_del_rasgo(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # fuerza: base 4 + 16 * rasgo
    a.traits[TraitId("fuerza")] = 0.5
    sheet_05 = derive(world, aid, ruleset, binding)
    assert sheet_05.potentials["fuerza"] == 12

    a.traits[TraitId("fuerza")] = 1.0
    sheet_10 = derive(world, aid, ruleset, binding)
    assert sheet_10.potentials["fuerza"] == 20

    # resonancia: base -4 + 24 * rasgo, mínimo del atributo es 0
    a.traits[TraitId("resonancia")] = 0.1
    sheet_res = derive(world, aid, ruleset, binding)
    assert sheet_res.potentials["resonancia"] == 0


def test_el_valor_crece_con_la_experiencia_hasta_el_techo(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Potencial 12, inicio 4, mitad 4
    # progreso = rango / (rango + mitad)
    # valor = inicio + (potencial - inicio) * progreso
    a.traits[TraitId("fuerza")] = 0.5  # potencial 12
    need_dominio = NeedId("dominio")

    # rango 0: progreso 0 -> valor 4
    a.rango[need_dominio] = 0
    sheet_r0 = derive(world, aid, ruleset, binding)
    assert sheet_r0.combatant.attributes["fuerza"] == 4

    # rango 4: progreso 4/(4+4) = 0.5 -> valor 4 + 8*0.5 = 8 (cubre M4)
    a.rango[need_dominio] = 4
    sheet_r4 = derive(world, aid, ruleset, binding)
    assert sheet_r4.combatant.attributes["fuerza"] == 8

    # rango 12: progreso 12/(12+4) = 0.75 -> valor 4 + 8*0.75 = 10
    a.rango[need_dominio] = 12
    sheet_r12 = derive(world, aid, ruleset, binding)
    assert sheet_r12.combatant.attributes["fuerza"] == 10

    # Techo de tier (cubre M2):
    # Con rango 3 -> nivel 1 + 3 = 4 (Tier 1: attribute_cap = 10)
    # Potencial 20 (rasgo 1.0): sin techo daría 4 + 16*(3/7) = 11. Con techo de tier 1 da 10.
    a.traits[TraitId("fuerza")] = 1.0
    a.rango[need_dominio] = 3
    sheet_cap = derive(world, aid, ruleset, binding)
    assert sheet_cap.combatant.tier == 1
    assert sheet_cap.combatant.attributes["fuerza"] == 10


def test_por_debajo_del_inicio_el_valor_es_el_potencial(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M3
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Potencial 2 (< inicio 4): con fórmula -4 + 24*t en resonancia
    # Si rasgo:resonancia = 0.25 -> potencial = -4 + 6 = 2
    a.traits[TraitId("resonancia")] = 0.25
    a.rango[NeedId("dominio")] = 4
    sheet = derive(world, aid, ruleset, binding)
    assert sheet.potentials["resonancia"] == 2
    assert sheet.combatant.attributes["resonancia"] == 2


def test_nivel_y_tier(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]
    need_dominio = NeedId("dominio")

    # rango 0 -> nivel 1, tier 1
    a.rango[need_dominio] = 0
    s0 = derive(world, aid, ruleset, binding)
    assert s0.level == 1
    assert s0.combatant.tier == 1

    # rango 4 -> nivel 5, tier 2
    a.rango[need_dominio] = 4
    s4 = derive(world, aid, ruleset, binding)
    assert s4.level == 5
    assert s4.combatant.tier == 2

    # rango 40 -> nivel 20 (recortado a max_level)
    a.rango[need_dominio] = 40
    s40 = derive(world, aid, ruleset, binding)
    assert s40.level == 20
    assert s40.combatant.tier == 5


def test_las_clases_no_cuentan(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    sheet_antes = derive(world, aid, ruleset, binding)
    a.traits[TraitId("guerrero")] = 1.0
    sheet_despues = derive(world, aid, ruleset, binding)

    assert sheet_antes.combatant == sheet_despues.combatant
    assert sheet_antes.role == sheet_despues.role


def test_el_equipo_por_ajuste(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M5 y M6
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Caso 1: Fuerza alta (grado 3, valor 7) y dinero alto (0.8):
    # Hacha pide fuerza 3, da base 6, piercing 1. Es accesible y rinde más que maza.
    a.rango[NeedId("dominio")] = 0
    a.traits[TraitId("fuerza")] = 0.5  # potencial 12, con rango 0 da valor 4
    a.rango[NeedId("dominio")] = 8  # progreso 8/12 = 0.667 -> 4 + 8*0.667 = 9.3 (grado 3)
    a.needs[NeedId("dinero")] = 0.8
    s_fuerte = derive(world, aid, ruleset, binding)
    assert ruleset.grade(s_fuerte.combatant.attributes["fuerza"]) >= 3
    assert s_fuerte.weapon.id == "hacha"

    # Caso 2: Dinero alto (0.8) pero fuerza baja (grado 2, valor 4).
    # Hacha requiere fuerza 3, por lo que _fits(hacha) es False.
    # Debe equipar maza (cubre M5: si _fits fuera siempre True, equiparía hacha).
    a.rango[NeedId("dominio")] = 0  # valor de fuerza = 4 (grado 2)
    s_baja_fuerza = derive(world, aid, ruleset, binding)
    assert ruleset.grade(s_baja_fuerza.combatant.attributes["fuerza"]) == 2
    assert s_baja_fuerza.weapon.id == "maza"

    # Caso 3: Sin dinero (0.0). No puede acceder a armas que piden dinero (> 0).
    # Debe equipar baston (cubre M6: si _accessible fuera siempre True, equiparía maza).
    a.needs[NeedId("dinero")] = 0.0
    s_sin_dinero = derive(world, aid, ruleset, binding)
    assert s_sin_dinero.weapon.id == "baston"


def test_el_enfoque_es_el_del_encuentro(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M7
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Agilidad grado 3 (valor 7), Fuerza grado 2 (valor 4)
    # Dinero 0.5 (acceso a espada corta y maza)

    # Con attack_approach: espada_corta (ágil) ataca con agilidad (grado 3):
    #   golpe = damage(4, 3, STANDARD, 1, 0) = 6; dados = 3; rinde = 18.
    #   maza (no ágil) ataca con fuerza (grado 2):
    #   golpe = damage(5, 2, STANDARD, 1, 3) = 7; dados = 2; rinde = 14.
    #   18 > 14 -> equipa espada_corta.
    # Si rinde usara el atributo por defecto (fuerza grado 2) para espada_corta:
    #   espada_corta rendiría golpe=6 * dados=2 = 12 < 14, y equiparía maza.
    a.rango[NeedId("dominio")] = 4  # mitad 4 -> progreso = 0.5
    a.traits[TraitId("fuerza")] = 0.0  # potencial 4, inicio 4 -> valor 4 (grado 2)
    a.traits[TraitId("instinto")] = 0.0  # potencial 4, inicio 4 -> valor 4 (grado 2)
    # agilidad: 4 + 16 * t. Queremos valor 7: 4 + (pot - 4)*0.5 = 7 -> pot = 10
    # 4 + 16*t = 10 -> 16*t = 6 -> t = 6/16 = 0.375
    a.traits[TraitId("agilidad")] = 0.375
    a.needs[NeedId("dinero")] = 0.5

    sheet = derive(world, aid, ruleset, binding)
    assert ruleset.grade(sheet.combatant.attributes["fuerza"]) == 2
    assert ruleset.grade(sheet.combatant.attributes["agilidad"]) == 3
    approach = attack_approach(
        ruleset, sheet.combatant.attributes, "armas_cuerpo_a_cuerpo", sheet.weapon
    )
    assert approach == "agilidad"
    assert sheet.weapon.id == "espada_corta"


def test_los_recursos_actuales(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M8 y M9
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # 1. salud = 0.5 -> mitad de la vitalidad
    a.needs[NeedId("salud")] = 0.5
    s_mitad = derive(world, aid, ruleset, binding)
    assert s_mitad.combatant.start_vitality == round(0.5 * s_mitad.combatant.vitality)

    # 2. salud = 0.0 -> mínimo 1 (cubre M8)
    a.needs[NeedId("salud")] = 0.0
    s_cero = derive(world, aid, ruleset, binding)
    assert s_cero.combatant.start_vitality == 1

    # 3. descanso = 0.25 -> fatiga actual es (1 - 0.25) * fat_max = 0.75 * fat_max (cubre M9)
    a.needs[NeedId("descanso")] = 0.25
    s_fat = derive(world, aid, ruleset, binding)
    assert s_fat.combatant.start_fatigue == round(0.75 * s_fat.combatant.fatigue)

    # 4. strain al tope (1.0) -> start_stress por debajo de la capacidad (stress - 1)
    a.strain = 1.0
    s_estres = derive(world, aid, ruleset, binding)
    assert s_estres.combatant.start_stress == s_estres.combatant.stress - 1


def test_el_estilo_por_disposicion(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M10 y M11
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Valores estándar fuera de los umbrales
    a.traits[TraitId("arrojo")] = 0.8
    a.traits[TraitId("piedad")] = 0.2
    s1 = derive(world, aid, ruleset, binding)
    assert s1.combatant.style.target == TargetChoice.STRONGEST
    assert s1.combatant.style.finish_off == FinishOff.ALWAYS

    a.traits[TraitId("arrojo")] = 0.2
    a.traits[TraitId("piedad")] = 0.8
    s2 = derive(world, aid, ruleset, binding)
    assert s2.combatant.style.target == TargetChoice.WEAKEST
    assert s2.combatant.style.finish_off == FinishOff.NEVER

    a.traits[TraitId("arrojo")] = 0.5
    a.traits[TraitId("piedad")] = 0.5
    s3 = derive(world, aid, ruleset, binding)
    assert s3.combatant.style.target == TargetChoice.HATED
    assert s3.combatant.style.finish_off == FinishOff.HATED

    # Fronteras exactas low=0.35 y high=0.65 (cubre M10: <= / >= vs < / >)
    a.traits[TraitId("arrojo")] = 0.35
    a.traits[TraitId("piedad")] = 0.35
    s_low = derive(world, aid, ruleset, binding)
    assert s_low.combatant.style.target == TargetChoice.WEAKEST
    assert s_low.combatant.style.finish_off == FinishOff.ALWAYS

    a.traits[TraitId("arrojo")] = 0.65
    a.traits[TraitId("piedad")] = 0.65
    s_high = derive(world, aid, ruleset, binding)
    assert s_high.combatant.style.target == TargetChoice.STRONGEST
    assert s_high.combatant.style.finish_off == FinishOff.NEVER


def test_el_aprecio_hacia_el_rival(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    rival_id = AgentId("isla_cenizal")
    a = world.agents[aid]

    # Con un vínculo explícito hacia el rival
    a.bonds[rival_id] = Bond(
        regard=0.8,
        encounters=5,
        last_seen=world.tick,
    )
    regard_calc = a.regard_for(
        rival_id, world.tick, a.temperament.bond_fade, a.relation_floor(world.pack, rival_id)
    )
    sheet = derive(world, aid, ruleset, binding, rivals=(rival_id,))
    assert sheet.combatant.regard[str(rival_id)] == round(regard_calc * 100)


def test_el_rol(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M12
    world, _sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    # Sin experiencia (rango=0), todos los valores empatan en el inicio (4).
    # Sin embargo, si ingenio y voluntad tienen mayor potencial, el desempate por potencial
    # selecciona ingenio y voluntad -> "erudito".
    # (Si no desempatara por potencial, caería en la primera pareja por orden del sistema:
    # fuerza y agilidad -> luchador).
    a.rango[NeedId("dominio")] = 0
    for attr in ruleset.attributes:
        a.traits[TraitId(attr.id)] = 0.0  # potencial mínimo
    a.traits[TraitId("ingenio")] = 0.9  # potencial alto
    a.traits[TraitId("voluntad")] = 0.8  # potencial alto

    sheet = derive(world, aid, ruleset, binding)
    assert sheet.role == "erudito"


def test_derivar_no_cambia_el_mundo(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, sim, ruleset, binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    rival_id = AgentId("isla_cenizal")

    foto_antes = foto(sim)
    _ = derive(world, aid, ruleset, binding, rivals=(rival_id,))
    _ = duel(world, aid, rival_id, ruleset, binding)
    _ = census(world, ruleset, binding)
    foto_despues = foto(sim)

    assert foto_antes == foto_despues


def test_un_muerto_no_tiene_ficha(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    world, _sim, ruleset, binding = base_setup
    with pytest.raises(KeyError):
        derive(world, AgentId("nadie_en_el_mundo"), ruleset, binding)


def test_signal_temperamento_divide_por_el_pack(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M15
    world, _sim, _ruleset, _binding = base_setup
    aid = AgentId("xan_fuegolento_67")
    a = world.agents[aid]

    base_val = world.pack.tuning.temperature
    a.temperament = dataclasses.replace(a.temperament, temperature=2.0 * base_val)

    s_val = signal(world, a, "temperamento:temperature")
    assert s_val == pytest.approx(2.0)


def test_check_scenario_comprueba_requires(
    base_setup: tuple[WorldState, Simulation, Ruleset, BindingSpec],
) -> None:
    # Cubre M18
    _world, _sim, ruleset, _binding = base_setup
    w_pesada = WeaponSpec(id="pesada", label="Pesada", base=5, requires={"fuerza": 3})
    c = CombatantSpec(
        id="novato",
        label="Novato",
        tier=1,
        attributes={"fuerza": 4},  # grado 2 < 3
        attack_skill="armas_cuerpo_a_cuerpo",
        weapon="pesada",
        vitality=10,
        fatigue=4,
        stress=6,
        impetus=3,
        style=CombatStyle(),
    )
    c2 = CombatantSpec(
        id="rival",
        label="Rival",
        tier=1,
        attributes={"fuerza": 4},
        attack_skill="armas_cuerpo_a_cuerpo",
        weapon="pesada",
        vitality=10,
        fatigue=4,
        stress=6,
        impetus=3,
        style=CombatStyle(),
    )
    escenario = ScenarioSpec(
        id="test_req",
        label="Test Req",
        weapons=(w_pesada,),
        sides=(
            SideSpec(id="s1", label="Side 1", combatants=(c,)),
            SideSpec(id="s2", label="Side 2", combatants=(c2,)),
        ),
    )
    problems = check_scenario(escenario, ruleset)
    assert any("pesada pide fuerza de grado 3" in p for p in problems)
