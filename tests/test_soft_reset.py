"""Pruebas del script de soft reset y su resultado en confluencia (unidad 11, §B.4)."""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import yaml

from agora.engine.pack import ContentPack, load_pack
from agora.engine.world import Simulation

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")

REINICIAR_SCRIPT = Path("packs/confluencia/reiniciar.py")

POTENCIALES = ("fuerza", "agilidad", "ingenio", "instinto", "voluntad", "presencia", "resonancia")
ESTILO = ("piedad", "arrojo")
NUEVE_RASGOS = (*POTENCIALES, *ESTILO)


def _pre_reset_yaml() -> str:
    res = subprocess.run(
        ["git", "show", "98409e2:packs/confluencia/pack.yaml"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


def test_los_doscientos_tienen_los_nueve() -> None:
    raw = yaml.safe_load(CONFLUENCIA_PACK.read_text(encoding="utf-8"))
    agentes = raw["agents"]
    assert len(agentes) == 200

    trait_ids = {t["id"] for t in raw["traits"]}
    for r in NUEVE_RASGOS:
        assert r in trait_ids, f"rasgo {r} falta en traits del pack"

    for a in agentes:
        traits = a.get("traits", {})
        for r in NUEVE_RASGOS:
            assert r in traits, f"agente {a['id']} no tiene {r}"
            val = traits[r]
            assert 0.0 <= val <= 1.0, f"agente {a['id']} tiene {r}={val} fuera de [0, 1]"

    # Comprobar que en la gestación también se heredan
    situaciones = {s["id"]: s for s in raw.get("situations", [])}
    if "gestacion" in situaciones:
        heredados = situaciones["gestacion"].get("al_expirar", {}).get("hereda_traits", [])
        for r in NUEVE_RASGOS:
            assert r in heredados, f"rasgo {r} falta en hereda_traits de gestación"


def test_el_reset_es_reproducible_e_idempotente(tmp_path: Path) -> None:
    # Correr reiniciar.py sobre una copia del pack.yaml previo da el actual byte a byte
    copia = tmp_path / "pack.yaml"
    copia.write_text(_pre_reset_yaml(), encoding="utf-8")

    # Primera corrida: añade los rasgos
    res1 = subprocess.run(
        [sys.executable, "-I", str(REINICIAR_SCRIPT), str(copia)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "200 agentes reiniciados" in res1.stdout
    assert copia.read_bytes() == CONFLUENCIA_PACK.read_bytes()

    # Segunda corrida: idempotente, no hace nada
    res2 = subprocess.run(
        [sys.executable, "-I", str(REINICIAR_SCRIPT), str(copia)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ya tiene los rasgos; no hago nada" in res2.stdout
    assert copia.read_bytes() == CONFLUENCIA_PACK.read_bytes()


def test_el_sesgo_por_raza(tmp_path: Path) -> None:
    # Cubre M16: si se elimina el sesgo por raza de reiniciar.py, la diferencia
    # entre gigantes y elfos no alcanzará el sesgo esperado (~0.35).
    copia = tmp_path / "pack_sesgo.yaml"
    copia.write_text(_pre_reset_yaml(), encoding="utf-8")

    subprocess.run(
        [sys.executable, "-I", str(REINICIAR_SCRIPT), str(copia)],
        capture_output=True,
        text=True,
        check=True,
    )
    raw = yaml.safe_load(copia.read_text(encoding="utf-8"))
    gigantes = [
        a["traits"]["fuerza"] for a in raw["agents"] if a.get("traits", {}).get("gigante")
    ]
    elfos = [
        a["traits"]["fuerza"] for a in raw["agents"] if a.get("traits", {}).get("elfo")
    ]
    media_gig = sum(gigantes) / len(gigantes)
    media_elf = sum(elfos) / len(elfos)

    assert media_gig > media_elf
    # Sin sesgo, ambos rondan 0.50 y la diferencia sería < 0.10.
    # Con sesgo (+0.25 vs -0.10), la diferencia teórica es 0.35 (medido ~0.31).
    assert media_gig - media_elf > 0.20


def test_el_mundo_no_se_entera() -> None:
    # confluencia a 2 días con y sin los nueve rasgos da el mismo log byte a byte
    p_pre = ContentPack.model_validate(yaml.safe_load(_pre_reset_yaml()))
    p_act = load_pack(CONFLUENCIA_PACK)

    buf_pre = io.StringIO()
    sim_pre = Simulation(p_pre, seed=1312, log_sink=buf_pre)
    sim_pre.run(48)

    buf_act = io.StringIO()
    sim_act = Simulation(p_act, seed=1312, log_sink=buf_act)
    sim_act.run(48)

    assert sim_pre.log.emitidos == sim_act.log.emitidos
    assert buf_pre.getvalue() == buf_act.getvalue()
