"""Pruebas de los arcos del mundo (unidad 23b-1, D-179, §B)."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.cognition.narrador import Sighting, Table, briefing, select, world_moment
from agora.engine import arcs
from agora.engine.arcs import (
    _digest,
    _rama,
    _reconocer,
    comenzar_por_id,
)
from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    ArcId,
    ArcPhaseRef,
    Beat,
    BeatKind,
    CounterId,
    MarkId,
    PhaseId,
    PlaceId,
    PlotCondition,
    Step,
    StepId,
)
from agora.engine.pack import ContentPack, PackError, load_pack
from agora.engine.perception import saw
from agora.engine.plots import _global, _latido_vigente
from agora.engine.state import ArcRun
from agora.engine.world import Simulation

CONFLUENCIA_PACK_PATH = Path("packs/confluencia/pack.yaml")
CIUDAD_PACK_PATH = Path("packs/ciudad/pack.yaml")


def _cargar_confluencia_crudo() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(CONFLUENCIA_PACK_PATH.read_text(encoding="utf-8"))
    arcos_path = CONFLUENCIA_PACK_PATH.parent / "arcos.yaml"
    tramas_path = CONFLUENCIA_PACK_PATH.parent / "tramas.yaml"
    if arcos_path.exists():
        raw["arcs"] = yaml.safe_load(arcos_path.read_text(encoding="utf-8"))
    if tramas_path.exists():
        raw["plots"] = yaml.safe_load(tramas_path.read_text(encoding="utf-8"))
    return raw


# =============================================================================
# B.1 — Formato
# =============================================================================


def test_formato_fase_inalcanzable() -> None:
    """B.1.1: Una fase declarada pero inalcanzable desde la primera no carga."""
    raw = _cargar_confluencia_crudo()
    m = copy.deepcopy(raw)
    m["arcs"]["arcs"][0]["phases"].append({
        "id": "fase_perdida",
        "label": "Fase inalcanzable",
        "days": {"min": 1, "max": 1},
    })
    with pytest.raises((PackError, ValueError), match="inalcanzable"):
        ContentPack.model_validate(m)


def test_formato_plantilla_invalida() -> None:
    """B.1.1: Una llegada con plantilla que no existe no carga."""
    raw = _cargar_confluencia_crudo()
    m = copy.deepcopy(raw)
    m["arcs"]["arcs"][1]["phases"][1]["arrivals"][0]["template"] = "orco_inexistente"
    with pytest.raises((PackError, ValueError), match="plantilla"):
        ContentPack.model_validate(m)


def test_formato_contador_alimentado_pero_nunca_leido() -> None:
    """B.1.1: Un contador que se alimenta pero nadie lee no carga."""
    raw = _cargar_confluencia_crudo()
    m = copy.deepcopy(raw)
    m["arcs"]["arcs"][0].setdefault("counters", []).append({
        "id": "c_nadie_lee",
        "label": "Contador huérfano",
        "feeds": [{"action": "charlar"}],
    })
    with pytest.raises((PackError, ValueError), match="se alimenta y nadie lo lee"):
        ContentPack.model_validate(m)


def test_formato_contador_leido_pero_no_declarado() -> None:
    """B.1.1: Leer un contador que el arco no declara es rechazado al cargar."""
    raw = _cargar_confluencia_crudo()
    m = copy.deepcopy(raw)
    m["arcs"]["arcs"][0]["phases"][0]["next"] = [
        {"if": {"counter": "contador_fantasma", "min": 1}, "to": "festival"},
        {"to": "cierre"},
    ]
    with pytest.raises((PackError, ValueError), match="no declara"):
        ContentPack.model_validate(m)


def test_formato_ciclo_sin_until() -> None:
    """B.1.1: Ramas que forman un ciclo sin fin no cargan."""
    raw = _cargar_confluencia_crudo()
    m = copy.deepcopy(raw)
    # preparacion -> festival -> preparacion
    m["arcs"]["arcs"][0]["phases"][1]["next"] = [{"to": "preparacion"}]
    with pytest.raises((PackError, ValueError), match="las fases forman un ciclo"):
        ContentPack.model_validate(m)


def test_sin_arcos_yaml_log_identico() -> None:
    """B.1.2: Pack sin arcos.yaml carga sin arcos y el log no cambia entre corridas idénticas."""
    pack = load_pack(CIUDAD_PACK_PATH)
    assert pack.arcs is None

    sim1 = Simulation(pack, seed=7)
    sim1.run(48)  # 2 días (ticks_per_day = 24)
    eventos1 = [e.to_json() for e in sim1.log]

    sim2 = Simulation(pack, seed=7)
    sim2.run(48)
    eventos2 = [e.to_json() for e in sim2.log]

    assert eventos1 == eventos2
    assert not any(e.kind.value.startswith("arc_") for e in sim1.log)


# =============================================================================
# B.2 — Fases y llegadas
# =============================================================================


def test_calendario_empieza_dia_declarado_y_no_repite() -> None:
    """B.2.1: El arco por calendario empieza el día declarado.

    Un arco en curso no empieza otra vez.
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=42)
    tpd = pack.clock.ticks_per_day

    # festival empieza el día 22 (start_day: 22, every_days: 360)
    sim.state.tick = 21 * tpd
    arcs.pasar_dia(sim)
    assert ArcId("festival") not in sim.state.arcos

    sim.state.tick = 22 * tpd
    arcs.pasar_dia(sim)
    assert ArcId("festival") in sim.state.arcos
    assert any(
        e.kind is EventKind.ARC_BEGAN and e.data.get("arco") == "festival"
        for e in sim.log
    )

    # Avanzar otro día mientras festival sigue en curso: no empieza duplicado
    sim.state.tick = 23 * tpd
    arcs.pasar_dia(sim)
    cuantos = sum(
        1 for e in sim.log
        if e.kind is EventKind.ARC_BEGAN and e.data.get("arco") == "festival"
    )
    assert cuantos == 1


def test_entrar_fase_activa_situaciones_y_llegadas_por_clave() -> None:
    """B.2.2: Entrar en una fase activa sus situaciones y hace llegadas con ids por clave.

    Misma semilla da mismos ids; determinismo con PYTHONHASHSEED; e independencia de
    contadores o número previo de agentes (cubre M1).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1312)

    # Arrancar incursion forzada
    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run = sim.state.arcos[ArcId("incursion")]
    assert run.fase == PhaseId("senales")
    assert "alarma_frontera" in sim.state.active_situations()

    # Avanzar a fase ataque (que tiene llegadas de orco_incursor)
    arco_spec = arcs._arco(pack, ArcId("incursion"))
    fase_ataque = arcs._fase(arco_spec, PhaseId("ataque"))
    arcs._salir(sim, run, arcs._fase(arco_spec, PhaseId("senales")))
    arcs._entrar(sim, arco_spec, run, fase_ataque)

    assert "incursion_orcos" in sim.state.active_situations()
    assert run.llegados, "deben haber entrado orcos"

    # Los ids están derivados por clave con _digest, nunca por contador
    sello_esperados = {
        f"orco_incursor-{_digest(sim.state.rng.seed, 'incursion', run.empezo, 'ataque', 0, k)}"
        for k in range(len(run.llegados))
    }
    actuales = {str(q) for q in run.llegados}
    assert actuales == sello_esperados

    # Comparar con otra simulación que tenga contador distinto o agente previo:
    # la clave pura no se ve afectada por contadores o cuentas de agentes.
    sim2 = Simulation(pack, seed=1312)
    # Modificar contador o estado en sim2 antes de arrancar
    sim2.state.arcos_terminados[ArcId("festival")] = (PhaseId("cierre"), 10)
    comenzar_por_id(sim2, ArcId("incursion"), "prueba")
    run2 = sim2.state.arcos[ArcId("incursion")]
    arcs._salir(sim2, run2, arcs._fase(arco_spec, PhaseId("senales")))
    arcs._entrar(sim2, arco_spec, run2, fase_ataque)

    assert sorted(run.llegados.keys()) == sorted(run2.llegados.keys())

    # Determinismo entre procesos con PYTHONHASHSEED variable
    script_hijo = (
        "from pathlib import Path\n"
        "from agora.engine.pack import load_pack\n"
        "from agora.engine.world import Simulation\n"
        "from agora.engine.ontology import ArcId, PhaseId\n"
        "from agora.engine import arcs\n"
        "p = load_pack(Path('packs/confluencia/pack.yaml'))\n"
        "s = Simulation(p, seed=1312)\n"
        "arcs.comenzar_por_id(s, ArcId('incursion'), 'test')\n"
        "r = s.state.arcos[ArcId('incursion')]\n"
        "spec = arcs._arco(p, ArcId('incursion'))\n"
        "arcs._salir(s, r, arcs._fase(spec, PhaseId('senales')))\n"
        "arcs._entrar(s, spec, r, arcs._fase(spec, PhaseId('ataque')))\n"
        "print(','.join(sorted(str(q) for q in r.llegados)))\n"
    )
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    salidas = [
        subprocess.run(
            [sys.executable, "-c", script_hijo],
            env={**os.environ, "PYTHONHASHSEED": hseed, "PYTHONPATH": src_dir},
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        for hseed in ("0", "42")
    ]
    assert salidas[0] == salidas[1] == ",".join(sorted(str(q) for q in run.llegados))


def test_llegados_con_depart_dejan_el_mundo_al_salir_o_cerrar() -> None:
    """B.2.3: Al salir de la fase o cerrar el arco, llegados con depart dejan el mundo (AGENT_LEFT)

    siguen en el censo y en la memoria de los demás; ninguno queda al cerrar (cubre M2).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=7)
    arco_spec = arcs._arco(pack, ArcId("incursion"))

    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run = sim.state.arcos[ArcId("incursion")]

    # Entrar a ataque
    fase_ataque = arcs._fase(arco_spec, PhaseId("ataque"))
    arcs._salir(sim, run, arcs._fase(arco_spec, PhaseId("senales")))
    arcs._entrar(sim, arco_spec, run, fase_ataque)

    llegados = list(run.llegados.keys())
    assert llegados
    for q in llegados:
        assert q in sim.state.agents

    # Un residente conoce a un llegado (crea memoria)
    residente = next(a.spec_id for a in sim.state.agents_in_order() if a.spec_id not in llegados)
    orco = llegados[0]
    sim.state.memoria.remember(
        residente,
        Event(
            kind=EventKind.ENCOUNTER,
            tick=sim.state.tick,
            seq=100,
            actor=orco,
            subject=residente,
            place=PlaceId("linde_salvaje"),
        ),
        importancia=1.0,
    )
    assert any(r.about == orco for r in sim.state.memoria.de(residente))

    # Salir de ataque hacia desenlace
    fase_desenlace = arcs._fase(arco_spec, PhaseId("desenlace"))
    arcs._salir(sim, run, fase_ataque)
    arcs._entrar(sim, arco_spec, run, fase_desenlace)

    # Los llegados con depart deben haber partido del mundo
    for q in llegados:
        assert q not in sim.state.agents, f"{q} no debió quedarse en agents"
        assert q in sim.state.censo, f"{q} debe seguir en el censo"
        assert any(
            e.kind is EventKind.AGENT_LEFT and e.actor == q for e in sim.log
        ), f"falta evento AGENT_LEFT para {q}"

    # El residente todavía recuerda al llegado (la memoria no se borra al partir)
    assert any(r.about == orco for r in sim.state.memoria.de(residente))

    # Al cerrar el arco, no queda ningún llegado en el mundo
    arcs._cerrar(sim, arco_spec, run, PhaseId("cae"))
    assert not any(str(q).startswith("orco_incursor-") for q in sim.state.agents)


def test_ramas_segun_contadores_llevan_a_su_fase() -> None:
    """B.2.4: Con los contadores a mano, cada rama lleva a su fase correspondiente (cubre M3)."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    arco_spec = arcs._arco(pack, ArcId("incursion"))
    fase_desenlace = arcs._fase(arco_spec, PhaseId("desenlace"))

    run = ArcRun(arco=ArcId("incursion"), empezo=0, fase=PhaseId("desenlace"), desde=0, hasta=24)

    # Caso 1: defensa > brecha -> rama resiste
    run.aportes[CounterId("defensa")] = {AgentId("agente_a"): 5}
    run.aportes[CounterId("brecha")] = {AgentId("orco"): 2}
    destino1 = _rama(run, fase_desenlace)
    assert destino1 == PhaseId("resiste")

    # Caso 2: defensa <= brecha -> rama cae (por defecto)
    run.aportes[CounterId("defensa")] = {AgentId("agente_a"): 2}
    run.aportes[CounterId("brecha")] = {AgentId("orco"): 5}
    destino2 = _rama(run, fase_desenlace)
    assert destino2 == PhaseId("cae")

    # Caso 3: en epidemia, cuidados >= 5 -> cura, sino catástrofe
    arco_epidemia = arcs._arco(pack, ArcId("epidemia"))
    fase_desenlace_epi = arcs._fase(arco_epidemia, PhaseId("desenlace"))
    run_epi = ArcRun(arco=ArcId("epidemia"), empezo=0, fase=PhaseId("desenlace"), desde=0, hasta=24)

    run_epi.aportes[CounterId("cuidados")] = {AgentId("sanador"): 5}
    assert _rama(run_epi, fase_desenlace_epi) == PhaseId("cura")

    run_epi.aportes[CounterId("cuidados")] = {AgentId("sanador"): 4}
    assert _rama(run_epi, fase_desenlace_epi) == PhaseId("catastrofe")


# =============================================================================
# B.3 — Contadores, siembra, tinte y reconocimiento
# =============================================================================


def test_contador_suma_y_atribuye_a_quien_lo_hizo() -> None:
    """B.3.1: Cada feed suma al contador y se atribuye a quien lo hizo.

    arc_tally funciona igual (cubre M4).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)

    comenzar_por_id(sim, ArcId("epidemia"), "prueba")
    run_epi = sim.state.arcos[ArcId("epidemia")]
    agente = next(a.spec_id for a in sim.state.agents_in_order())

    # Feed por acción: cuidar en la zona de la epidemia (enfermeria)
    sim._registrar(
        tick=sim.state.tick,
        kind=EventKind.ACTION_COMPLETED,
        actor=agente,
        place=PlaceId("enfermeria"),
        action=ActionId("cuidar"),
        data={},
    )

    cuidados = run_epi.aportes.get(CounterId("cuidados"), {})
    assert cuidados.get(agente) == 1

    # arc_tally desde una trama: suma y atribuye al protagonista
    sim._sumar_aporte_de_arco(agente, CounterId("cuidados"), 3)
    assert run_epi.aportes[CounterId("cuidados")][agente] == 4

    # Feed por combate: victoria atribuida al combatiente ganador
    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run_inc = sim.state.arcos[ArcId("incursion")]
    agente_rival = AgentId("orco_prueba")
    sim._anotar_combate(agente, agente_rival, PlaceId("linde_salvaje"), gana_actor=True)

    defensa = run_inc.aportes.get(CounterId("defensa"), {})
    assert defensa.get(agente) == 1


def test_trama_sembrada_solo_empieza_en_su_fase() -> None:
    """B.3.2: Una trama sembrada (arc_phase en when) solo empieza en su fase (cubre M5)."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)
    cond_senales = PlotCondition(
        arc_phase=ArcPhaseRef(arc=ArcId("incursion"), phase=PhaseId("senales"))
    )
    cond_ataque = PlotCondition(
        arc_phase=ArcPhaseRef(arc=ArcId("incursion"), phase=PhaseId("ataque"))
    )

    # Antes de empezar incursion: ninguna fase está activa
    assert not _global(sim, cond_senales)
    assert not _global(sim, cond_ataque)

    # Iniciar incursion: entra en fase senales
    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    assert _global(sim, cond_senales)
    assert not _global(sim, cond_ataque)

    # Avanzar a fase ataque: senales se apaga, ataque se enciende
    run = sim.state.arcos[ArcId("incursion")]
    spec = arcs._arco(pack, ArcId("incursion"))
    arcs._salir(sim, run, arcs._fase(spec, PhaseId("senales")))
    arcs._entrar(sim, spec, run, arcs._fase(spec, PhaseId("ataque")))

    assert not _global(sim, cond_senales)
    assert _global(sim, cond_ataque)

    # Cerrar incursion: ataque se apaga
    arcs._cerrar(sim, spec, run, PhaseId("resiste"))
    assert not _global(sim, cond_ataque)


def test_tinte_latido_fase_y_retorno_al_salir() -> None:
    """B.3.3: Con el tinte, el paso espera el latido de la fase.

    Vuelve al suyo al salir de la fase (cubre M6).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)

    paso = Step(
        id=StepId("paso_con_tinte"),
        within_days=5,
        expects=Beat(kind=BeatKind.TALKED_WITH, ref="amigo"),
        tint={"incursion.ataque": Beat(kind=BeatKind.PROTECTED_BY, ref="amigo")},
    )
    assert paso.expects is not None

    # Sin arco activo: latido base
    assert _latido_vigente(sim, paso, paso.expects).kind == BeatKind.TALKED_WITH

    # Con incursion en fase senales: latido base
    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    assert _latido_vigente(sim, paso, paso.expects).kind == BeatKind.TALKED_WITH

    # Con incursion en fase ataque: latido teñido
    run = sim.state.arcos[ArcId("incursion")]
    spec = arcs._arco(pack, ArcId("incursion"))
    arcs._salir(sim, run, arcs._fase(spec, PhaseId("senales")))
    arcs._entrar(sim, spec, run, arcs._fase(spec, PhaseId("ataque")))
    assert _latido_vigente(sim, paso, paso.expects).kind == BeatKind.PROTECTED_BY

    # Al salir de fase ataque: vuelve automáticamente a su latido base
    arcs._salir(sim, run, arcs._fase(spec, PhaseId("ataque")))
    arcs._entrar(sim, spec, run, arcs._fase(spec, PhaseId("desenlace")))
    assert _latido_vigente(sim, paso, paso.expects).kind == BeatKind.TALKED_WITH


def test_reconocido_es_quien_mas_aporto_y_desempate_por_clave() -> None:
    """B.3.4: Reconocido es quien más aportó.

    Empate por hash con clave, no por id (cubre M7 y M4).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)

    # 1. Quien más aporta gana
    sim = Simulation(pack, seed=1)
    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run = sim.state.arcos[ArcId("incursion")]
    ag_a = AgentId("agente_a")
    ag_b = AgentId("agente_b")
    sim.state.agents[ag_a] = copy.deepcopy(sim.state.agents_in_order()[0])
    sim.state.agents[ag_a].spec_id = ag_a
    sim.state.agents[ag_b] = copy.deepcopy(sim.state.agents_in_order()[1])
    sim.state.agents[ag_b].spec_id = ag_b

    run.aportes[CounterId("defensa")] = {ag_a: 5, ag_b: 2}
    spec = arcs._arco(pack, ArcId("incursion"))
    ganador = _reconocer(sim, spec, run)
    assert ganador == ag_a
    assert sim.state.marcas.get(ag_a, {}).get(MarkId("heroe_de_la_incursion")) == 1

    # 2. Desempate: aportes iguales.
    # Con semilla 0 y tick 0, stream('arco-reconocido', 'incursion', 0, 'agente_b') da 0.3300
    # mientras para 'agente_a' da 0.6202.
    # Por orden de hash, el menor float (agente_b) es el ganador.
    # Si se desempatara por orden de id, 'agente_a' < 'agente_b' elegiría a agente_a.
    sim_empate = Simulation(pack, seed=0)
    comenzar_por_id(sim_empate, ArcId("incursion"), "prueba")
    run_empate = sim_empate.state.arcos[ArcId("incursion")]
    sim_empate.state.agents[ag_a] = copy.deepcopy(sim_empate.state.agents_in_order()[0])
    sim_empate.state.agents[ag_a].spec_id = ag_a
    sim_empate.state.agents[ag_b] = copy.deepcopy(sim_empate.state.agents_in_order()[1])
    sim_empate.state.agents[ag_b].spec_id = ag_b

    run_empate.aportes[CounterId("defensa")] = {ag_a: 3, ag_b: 3}
    reconocido = _reconocer(sim_empate, spec, run_empate)
    assert reconocido == ag_b, (
        "El empate debe resolver por clave hash (agente_b), no por id (agente_a)"
    )


def test_residuos_de_rama_se_aplican() -> None:
    """B.3.5: Los residuos de la rama se aplican al cerrar (marcas, fama y situaciones)."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)
    spec = arcs._arco(pack, ArcId("incursion"))

    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run = sim.state.arcos[ArcId("incursion")]
    agente = sim.state.agents_in_order()[0].spec_id
    run.aportes[CounterId("defensa")] = {agente: 1}

    fama_antes = sim.state.fama.get(agente, 0.0)
    # Rama 'resiste' otorga 0.05 de fama adicional como residuo a aportantes
    arcs._cerrar(sim, spec, run, PhaseId("resiste"))

    fama_despues = sim.state.fama.get(agente, 0.0)
    # 0.05 de residuo + 0.1 de reconocimiento al héroe = 0.15
    assert fama_despues > fama_antes

    # Cerrar con rama 'cae': enciende luto_comun por 5 días
    comenzar_por_id(sim, ArcId("incursion"), "prueba2")
    run2 = sim.state.arcos[ArcId("incursion")]
    run2.aportes[CounterId("defensa")] = {agente: 1}
    arcs._cerrar(sim, spec, run2, PhaseId("cae"))
    assert "luto_comun" in sim.state.situations


# =============================================================================
# B.4 — Percepción y narrador
# =============================================================================


def test_situacion_delante_se_presencia_ausente_solo_rumor() -> None:
    """B.4.1: Situación que empieza delante se presencia; un ausente se entera solo por rumor."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)

    ag_presente = sim.state.agents_in_order()[0]
    ag_ausente = sim.state.agents_in_order()[1]

    # Ubicar al presente en linde_salvaje (zona de incursion.senales)
    # y al ausente en torre_observacion (fuera de la zona)
    ag_presente.at = PlaceId("linde_salvaje")
    ag_ausente.at = PlaceId("torre_observacion")

    comenzar_por_id(sim, ArcId("incursion"), "prueba")

    # El presente tiene el ARC_PHASE en sus recuerdos y percepciones
    vistos_presente = saw(sim.state, ag_presente.spec_id)
    assert any(p.kind is EventKind.ARC_PHASE for p in vistos_presente)
    assert any(r.kind is EventKind.ARC_PHASE for r in sim.state.memoria.de(ag_presente.spec_id))

    # El ausente no lo presenció ni lo tiene en memoria
    vistos_ausente = saw(sim.state, ag_ausente.spec_id)
    assert not any(p.kind is EventKind.ARC_PHASE for p in vistos_ausente)
    assert not any(r.kind is EventKind.ARC_PHASE for r in sim.state.memoria.de(ag_ausente.spec_id))

    # Cuando el presente le cuenta la noticia (rumor), el ausente se entera por oír
    recuerdo = next(
        r for r in sim.state.memoria.de(ag_presente.spec_id)
        if r.kind is EventKind.ARC_PHASE
    )
    sim.state.memoria.oir(ag_ausente.spec_id, recuerdo, importancia=0.5)
    assert any(r.kind is EventKind.ARC_PHASE for r in sim.state.memoria.de(ag_ausente.spec_id))


def test_narrador_no_revela_id_label_ni_contadores_de_arco() -> None:
    """B.4.2: Ningún briefing del narrador lleva id ni label del arco.

    Tampoco lleva sus contadores (cubre M8).
    """
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=1)
    world = sim.state

    ag_jugador = world.agents_in_order()[0]
    lugar = "linde_salvaje"
    ag_jugador.at = PlaceId(lugar)
    sim.set_player(ag_jugador.spec_id)

    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    eventos_fase = [e for e in sim.log if e.kind is EventKind.ARC_PHASE]
    assert eventos_fase

    facts = select(world, eventos_fase, str(ag_jugador.spec_id), Sighting(lugar), Table())
    momento = world_moment(world, str(ag_jugador.spec_id), tuple(facts), Table())
    texto_briefing = briefing(momento)

    # El briefing cuenta lo visible (situación y/o llegados)
    assert "alarma_frontera" in texto_briefing or "empieza para ti" in texto_briefing

    # Pero NUNCA el id ni label del arco, ni sus contadores
    palabras_prohibidas = ["incursion", "incursión", "defensa", "brecha"]
    texto_lower = texto_briefing.lower()
    for palabra in palabras_prohibidas:
        assert palabra not in texto_lower, f"El briefing filtró {palabra!r}: {texto_briefing}"


# =============================================================================
# Guardar y cargar (para M9)
# =============================================================================


def test_guardar_y_cargar_con_arco_en_curso(tmp_path: Path) -> None:
    """Verifica que el estado de los arcos en curso y terminados se guarde y recupere (cubre M9)."""
    pack = load_pack(CONFLUENCIA_PACK_PATH)
    sim = Simulation(pack, seed=10)

    comenzar_por_id(sim, ArcId("incursion"), "prueba")
    run = sim.state.arcos[ArcId("incursion")]
    agente = sim.state.agents_in_order()[0].spec_id
    run.aportes[CounterId("defensa")] = {agente: 4}

    # También registrar un arco terminado
    sim.state.arcos_terminados[ArcId("festival")] = (PhaseId("cierre"), 120)

    archivo = tmp_path / "partida_arcos.json"
    sim.save(archivo)

    resumed = Simulation.resume(archivo, pack)

    # El arco en curso debe haber cargado intacto
    assert ArcId("incursion") in resumed.state.arcos
    run_resumed = resumed.state.arcos[ArcId("incursion")]
    assert run_resumed.fase == run.fase
    assert run_resumed.empezo == run.empezo
    assert run_resumed.aportes == run.aportes

    # El arco terminado debe estar en arcos_terminados
    assert resumed.state.arcos_terminados.get(ArcId("festival")) == (PhaseId("cierre"), 120)
