"""Pruebas del fin de partida (unidad 19, §B).

Verifica:
- B.1 El final: guarda de último vivo, desempates por sorteo y determinismo,
  orden por id fuera de empate total, evento GAME_ENDED, reloj congelado tras
  acabar, persistencia de finished/bajas, y supervivencia única en la isla.
- B.2 Bajas y resumen: registro de autor en combate y por condición de agonía,
  criterio de traición (aprecio >= 0.2), y validación de sin_tregua sin efectos.
- B.3 Jugar: razón «victoria» en play(), avance tras muerte del jugador en run.py,
  narración de «eres el último en pie» con resumen, y reproducción determinista
  de guion que gana.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agora.cognition.narrador import Narrator, Table
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId, SituationId
from agora.engine.pack import load_pack
from agora.engine.persistence import load
from agora.engine.state import Baja, Condicion
from agora.engine.world import Simulation
from agora.play import Recorder, Script, Terminal, play, resumen_del_final
from agora.run import _jugar
from tests.test_muerte import mortal_pack

HAMBRE = NeedId("hambre")
ISLA_PACK = Path("packs/isla/pack.yaml")


# =============================================================================
# B.1 — El final
# =============================================================================


def test_b1_1_morir_del_unico_vivo_no_hace_nada_con_last_standing() -> None:
    """1. Con last_standing, morir del único vivo no hace nada; sin ending, muere."""
    # Con ending: last_standing
    pack_con_final = mortal_pack(
        ending={"last_standing": True},
        agents=[{"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"}],
    )
    sim1 = Simulation(pack_con_final, seed=0)
    assert len(sim1.state.agents) == 1
    sim1.morir(AgentId("ag1"))
    assert AgentId("ag1") in sim1.state.agents
    assert len(sim1.state.agents) == 1
    assert not any(e.kind is EventKind.AGENT_DIED for e in sim1.log)

    # Sin ending
    pack_sin_final = mortal_pack(
        ending=None,
        agents=[{"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"}],
    )
    sim2 = Simulation(pack_sin_final, seed=0)
    assert len(sim2.state.agents) == 1
    sim2.morir(AgentId("ag1"))
    assert AgentId("ag1") not in sim2.state.agents
    assert len(sim2.state.agents) == 0


def test_b1_2_dos_condenados_unicos_vivos_sobrevive_uno_no_siempre_menor_id() -> None:
    """2. Dos condenados, los dos únicos vivos: sobrevive uno, y no siempre el
    de id menor (dos semillas con ganadores de distinto orden alfabético)."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    )

    # Semilla 0: gana ag1 (id alfabéticamente menor)
    sim_s0 = Simulation(pack, seed=0)
    sim_s0.run(20)
    assert sim_s0.state.finished is not None
    ganador_s0 = sim_s0.state.finished[0]
    assert ganador_s0 == AgentId("ag1")
    assert list(sim_s0.state.agents.keys()) == [AgentId("ag1")]

    # Semilla 4: gana ag2 (id alfabéticamente mayor)
    sim_s4 = Simulation(pack, seed=4)
    sim_s4.run(20)
    assert sim_s4.state.finished is not None
    ganador_s4 = sim_s4.state.finished[0]
    assert ganador_s4 == AgentId("ag2")
    assert list(sim_s4.state.agents.keys()) == [AgentId("ag2")]

    # Los dos ganadores tienen distinto orden alfabético respecto al rival
    assert (ganador_s0 == AgentId("ag1")) and (ganador_s4 == AgentId("ag2"))


def test_b1_3_mismo_caso_misma_semilla_mismo_ganador_pythonhashseed_variable() -> None:
    """3. Mismo caso, misma semilla: el mismo ganador, con PYTHONHASHSEED variable."""
    script = (
        "from tests.test_muerte import mortal_pack\n"
        "from agora.engine.world import Simulation\n"
        "pack = mortal_pack(ending={'last_standing': True})\n"
        "sim = Simulation(pack, seed=4)\n"
        "sim.run(20)\n"
        "print(sim.state.finished[0] if sim.state.finished else '')\n"
    )
    env1 = {**os.environ, "PYTHONHASHSEED": "0"}
    env2 = {**os.environ, "PYTHONHASHSEED": "131242"}
    cmd = [sys.executable, "-c", script]

    proc1 = subprocess.run(cmd, env=env1, capture_output=True, text=True, check=True)
    proc2 = subprocess.run(cmd, env=env2, capture_output=True, text=True, check=True)

    assert proc1.stdout.strip() == "ag2"
    assert proc2.stdout.strip() == "ag2"


def test_b1_4_tres_condenados_y_un_cuarto_sano_mueren_en_orden_id() -> None:
    """4. Tres condenados y un cuarto sano: los tres mueren en orden de id, como hoy."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
            {"id": "ag4", "label": "Cuatro", "home": "p1", "start_at": "p1"},
        ],
    )
    # En la semilla 0 y tick 15, el sorteo daría ['ag2', 'ag3', 'ag1'].
    # Pero como ag4 está sano, no es empate de todos los vivos y se cobra en orden de id.
    sim = Simulation(pack, seed=0)
    sim.run(14)

    # Mantener a ag4 sano y con vínculo de aprecio hacia los tres para registrar duelo
    ag4 = sim.state.agents[AgentId("ag4")]
    ag4.needs[HAMBRE] = 1.0
    ag4.agonia.clear()
    for victima in (AgentId("ag1"), AgentId("ag2"), AgentId("ag3")):
        ag4.meet(victima, tick=14)
        ag4.remember_company([victima], premium=1.0, rate=0.5, tick=14)

    sim.tick()

    # Mueren exactamente en orden de id: ag1, ag2, ag3
    muertes = [e.subject for e in sim.log if e.kind is EventKind.AGENT_DIED]
    assert muertes == [AgentId("ag1"), AgentId("ag2"), AgentId("ag3")]
    assert AgentId("ag4") in sim.state.agents


def test_b1_5_game_ended_una_sola_vez_y_tick_no_avanza() -> None:
    """5. GAME_ENDED una sola vez, con el ganador; después tick() no avanza el reloj."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    )
    sim = Simulation(pack, seed=0)
    sim.run(20)

    assert sim.state.finished is not None
    ganador, tick_fin = sim.state.finished
    assert ganador == AgentId("ag1")
    assert tick_fin == 15

    eventos_fin = [e for e in sim.log if e.kind is EventKind.GAME_ENDED]
    assert len(eventos_fin) == 1
    assert eventos_fin[0].actor == ganador
    assert eventos_fin[0].tick == tick_fin

    # tick() tras finished no avanza el reloj ni emite más eventos
    log_antes = len(sim.log)
    sim.tick()
    sim.tick()
    assert sim.state.tick == tick_fin
    assert len(sim.log) == log_antes


def test_b1_6_guardar_y_cargar_con_finished_y_bajas_no_avanza(tmp_path: Path) -> None:
    """6. Guardar y cargar con finished y bajas: siguen; tick() sigue sin avanzar."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    )
    sim = Simulation(pack, seed=0)
    sim.run(20)
    sim.state.bajas[AgentId("ag1")] = [Baja(AgentId("ag2"), 15, 0.45)]

    save_path = tmp_path / "partida.json"
    sim.save(save_path)

    mundo_cargado, _, _ = load(save_path, pack)

    assert mundo_cargado.finished == sim.state.finished
    assert mundo_cargado.finished == (AgentId("ag1"), 15)
    assert mundo_cargado.bajas == {AgentId("ag1"): [Baja(AgentId("ag2"), 15, 0.45)]}

    # Reanudada: tick() sigue sin avanzar
    sim2 = Simulation.resume(save_path, pack)
    assert sim2.state.finished == (AgentId("ag1"), 15)
    assert sim2.state.bajas == {AgentId("ag1"): [Baja(AgentId("ag2"), 15, 0.45)]}
    sim2.tick()
    assert sim2.state.tick == 15


@pytest.mark.slow
def test_b1_7_isla_tres_semillas_un_vivo_desde_d7() -> None:
    """7. Isla, 3 semillas, 10 días: 1 vivo desde el d7."""
    pack = load_pack(ISLA_PACK)
    tpd = pack.clock.ticks_per_day
    dias_10 = 10 * tpd

    for semilla in (1, 2, 3):
        sim = Simulation(pack, seed=semilla)
        sim.run(dias_10)

        assert sim.state.finished is not None, f"semilla {semilla} debió terminar"
        ganador, tick_fin = sim.state.finished
        # Termina durante el día 7 (ticks 576..671)
        dia_fin = tick_fin // tpd + 1
        assert dia_fin == 7, f"semilla {semilla} terminó en día {dia_fin}, esperado 7"
        assert len(sim.state.agents) == 1
        assert ganador in sim.state.agents


# =============================================================================
# B.2 — Bajas y resumen
# =============================================================================


def test_b2_1_bajas_combate_rival_agonia_autor_condicion_sin_autor_ninguna() -> None:
    """1. Muerte en combate: la baja es del rival. Por agonía: del autor de la
    última condición con autor. Sin autor: ninguna."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
            {"id": "ag4", "label": "Cuatro", "home": "p1", "start_at": "p1"},
        ],
    )
    sim = Simulation(pack, seed=0)
    ag1, ag2, ag3, ag4 = AgentId("ag1"), AgentId("ag2"), AgentId("ag3"), AgentId("ag4")

    # Caso combate: por_quien recibido directamente
    sim.morir(ag2, porque="combate", por_quien=ag1)
    assert len(sim.state.bajas.get(ag1, [])) == 1
    assert sim.state.bajas[ag1][0].victima == ag2

    # Caso agonía: autor de la última condición con autor
    c_vieja = Condicion(situacion=SituationId("hambre"), por_quien=ag4)
    c_reciente = Condicion(situacion=SituationId("hambre"), por_quien=ag1)
    c_sin_autor = Condicion(situacion=SituationId("hambre"), por_quien=None)
    sim.state.agents[ag3].condiciones.extend([c_vieja, c_reciente, c_sin_autor])

    sim.morir(ag3, porque="agonía")
    assert len(sim.state.bajas.get(ag1, [])) == 2
    assert sim.state.bajas[ag1][1].victima == ag3
    assert ag4 not in sim.state.bajas

    # Caso sin autor: no se añade baja a nadie
    sim.morir(ag4, porque="hambre")
    assert len(sim.state.bajas.get(ag1, [])) == 2
    assert ag4 not in sim.state.bajas


def test_b2_2_baja_con_aprecio_mayor_igual_02_es_traicion_con_menos_no() -> None:
    """2. Una baja con aprecio >= 0.2 aparece como traición en el resumen; con menos, no."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
        ],
    )
    sim = Simulation(pack, seed=0)
    ag1, ag2, ag3 = AgentId("ag1"), AgentId("ag2"), AgentId("ag3")
    sim.set_player(ag1)
    sim.state.finished = (ag1, 10)

    # ag2 con aprecio 0.15 (< 0.2): es baja pero no traición
    sim.state.bajas[ag1] = [Baja(victima=ag2, tick=5, aprecio=0.15)]
    lineas = resumen_del_final(sim, ag1)
    assert any("# a quién mataste:" in linea and "Dos" in linea for linea in lineas)
    assert not any("# a quién traicionaste:" in linea for linea in lineas)

    # ag3 con aprecio 0.20 (>= 0.2): es baja y traición
    sim.state.bajas[ag1].append(Baja(victima=ag3, tick=8, aprecio=0.20))
    lineas2 = resumen_del_final(sim, ag1)
    assert any(
        "# a quién mataste:" in linea and "Dos" in linea and "Tres" in linea
        for linea in lineas2
    )
    linea_traicion = next(linea for linea in lineas2 if "# a quién traicionaste:" in linea)
    assert "Tres" in linea_traicion
    assert "Dos" not in linea_traicion


def test_b2_3_sin_tregua_carga_sin_effects_y_validador_cuenta_requires_condition() -> None:
    """3. sin_tregua carga sin effects (el validador cuenta requires_condition)."""
    pack = load_pack(ISLA_PACK)
    sit = pack.situation_by_id[SituationId("sin_tregua")]
    assert sit.effects == {}

    # El validador no reporta problemas sobre sin_tregua
    problemas = pack._check_situations_do_something()
    assert not any("sin_tregua" in p for p in problemas)


# =============================================================================
# B.3 — Jugar
# =============================================================================


class _PrimeraOpcionSource:
    def choose(self, world: Any, agent: Any, opts: Any) -> Any:
        return opts[0] if opts else None

    def interrupt(self, world: Any, agent: Any, need: Any) -> bool:
        return False


def test_b3_1_play_devuelve_victoria_si_jugador_es_el_ultimo() -> None:
    """1. play() devuelve victoria si el jugador es el último."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.1}},
        ],
    )
    sim = Simulation(pack, seed=0)
    sim.set_player(AgentId("ag1"))

    resultado = play(sim, _PrimeraOpcionSource(), max_ticks=50)
    assert resultado.reason == "victoria"
    assert sim.state.finished is not None
    assert sim.state.finished[0] == AgentId("ag1")


def test_b3_2_si_jugador_muere_run_avanza_avisa_y_dice_quien_gano_sin_ending_como_hoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """2. Si muere, run.py avanza, avisa y dice quién ganó; sin ending, como hoy."""
    guion_path = tmp_path / "guion_vacio.jsonl"
    guion_path.write_text("", encoding="utf-8")
    reglas_path = Path("rules/base/rules.yaml")

    # Con ending: avanza hasta el final, avisa y dice quién ganó
    pack_con_final = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.1}},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
        ],
    )
    sim1 = Simulation(pack_con_final, seed=0)
    sim1.set_player(AgentId("ag1"))

    args1 = argparse.Namespace(
        guion=guion_path, grabar=None, combates=None, escenas=None, rules=None,
        reglas=reglas_path, pack=Path("packs/no_existo/pack.yaml"),
    )
    _jugar(sim1, args1, ticks=50)
    out1 = capsys.readouterr().out

    assert "# fin de la partida: muerte" in out1
    assert "# el mundo sigue sin ti…" in out1
    assert "# ganó Dos, el día 1" in out1
    assert "# duraste 1 días" in out1

    # Sin ending: se para al morir, como hoy
    pack_sin_final = mortal_pack(
        ending=None,
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.1}},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
        ],
    )
    sim2 = Simulation(pack_sin_final, seed=0)
    sim2.set_player(AgentId("ag1"))

    _jugar(sim2, args1, ticks=50)
    out2 = capsys.readouterr().out

    assert "# fin de la partida: muerte" in out2
    assert "# el mundo sigue sin ti…" not in out2
    assert "# ganó" not in out2


def test_b3_3_con_victoria_se_narra_eres_el_ultimo_en_pie_y_sale_resumen() -> None:
    """3. Con victoria, se narra «eres el último en pie» y sale el resumen."""
    pack = mortal_pack(
        ending={"last_standing": True},
        agents=[
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.9}},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
             "initial_needs": {"hambre": 0.1}},
        ],
    )
    sim = Simulation(pack, seed=0)
    sim.set_player(AgentId("ag1"))

    out_terminal = io.StringIO()
    term = Terminal(sim, io.StringIO(), out_terminal, provider=None, interpreter=None,
                    narrator=Narrator((), Table()))

    res = play(sim, term, max_ticks=50)
    assert res.reason == "victoria"

    term.farewell()
    texto_narrado = out_terminal.getvalue()
    assert "el último en pie" in texto_narrado.lower()

    lineas = resumen_del_final(sim, AgentId("ag1"))
    assert any("# ganó Uno" in linea for linea in lineas)
    assert any("# duraste 1 días" in linea for linea in lineas)


def test_b3_4_guion_que_acaba_en_victoria_se_reproduce_igual(tmp_path: Path) -> None:
    """4. Un guion que acaba en victoria se reproduce igual."""
    def simular() -> Simulation:
        pack = mortal_pack(
            ending={"last_standing": True},
            agents=[
                {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
                 "initial_needs": {"hambre": 0.9}},
                {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
                 "initial_needs": {"hambre": 0.1}},
            ],
        )
        sim = Simulation(pack, seed=42)
        sim.set_player(AgentId("ag1"))
        return sim

    guion_file = tmp_path / "victoria.jsonl"
    sim1 = simular()
    with guion_file.open("w", encoding="utf-8") as f:
        rec = Recorder(_PrimeraOpcionSource(), f, sim1)
        res1 = play(sim1, rec, 50)

    assert res1.reason == "victoria"
    lineas_guion = guion_file.read_text(encoding="utf-8").splitlines()

    sim2 = simular()
    script = Script(lineas_guion, sim2)
    res2 = play(sim2, script, 50)

    assert res2.reason == "victoria"
    assert res1.ticks == res2.ticks
    assert list(sim1.log) == list(sim2.log)
    assert sim1.state.finished == sim2.state.finished
    assert sim1.state.bajas == sim2.state.bajas
