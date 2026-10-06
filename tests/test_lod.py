"""Tests para el nivel de detalle medio (LOD) y su puerta (D-152, plan 06)."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from agora.agents.decide import candidates
from agora.engine.lod import error_de_lod
from agora.engine.ontology import AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.state import DetailLevel, WorldState
from agora.engine.timeskip import comparar
from agora.engine.world import Simulation
from agora.run import main


def toy_chain_pack(**overrides: Any) -> ContentPack:
    """Pack de juguete en cadena: p0 —1— p1 —1— p2 —1— p3."""
    data: dict[str, Any] = {
        "id": "cadena",
        "label": "Cadena de juguete",
        "clock": {"ticks_per_day": 24, "days_per_year": 1},
        "tuning": {
            "lod_focus_radius": 1,
            "lod_menu_radius": 1,
        },
        "needs": [
            {
                "id": "n1",
                "label": "n1",
                "decay_per_tick": 0.01,
                "urgency_exponent": 2.0,
            }
        ],
        "traits": [],
        "actions": [
            {
                "id": "act_libre",
                "label": "act_libre",
                "duration_ticks": 1,
                "satisfies": {"n1": 0.1},
            },
            {
                "id": "act_remedio",
                "label": "act_remedio",
                "duration_ticks": 1,
                "requires_affordance": "remedio",
                "satisfies": {"n1": 1.0},
            },
        ],
        "places": [
            {"id": "p0", "label": "p0", "affordances": ["remedio"], "neighbors": {"p1": 1}},
            {"id": "p1", "label": "p1", "neighbors": {"p0": 1, "p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1, "p3": 1}},
            {"id": "p3", "label": "p3", "neighbors": {"p2": 1}},
        ],
        "agents": [
            {"id": "foco", "label": "foco", "home": "p0", "start_at": "p0"},
            {"id": "ag_cerca", "label": "ag_cerca", "home": "p1", "start_at": "p1"},
            {"id": "ag_lejos", "label": "ag_lejos", "home": "p3", "start_at": "p2"},
            {"id": "ag_casa_p0", "label": "ag_casa_p0", "home": "p0", "start_at": "p2"},
            {"id": "ag_p3_casa_p0", "label": "ag_p3_casa_p0", "home": "p0", "start_at": "p3"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# -----------------------------------------------------------------------------
# B.1 — La puerta y la deliberación
# -----------------------------------------------------------------------------


def test_cerca_del_foco_se_mira_todo() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("foco")
    agente = world.agents[AgentId("ag_cerca")]
    assert world.detail_level(agente) is DetailLevel.FINE
    assert world.places_to_consider(agente) is world.pack.places


def test_lejos_del_foco_se_mira_lo_cercano_y_la_casa() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("foco")
    agente = world.agents[AgentId("ag_casa_p0")]
    assert world.detail_level(agente) is DetailLevel.MEDIUM
    lugares = world.places_to_consider(agente)
    assert lugares is not world.pack.places
    assert tuple(p.id for p in lugares) == (
        PlaceId("p0"),
        PlaceId("p1"),
        PlaceId("p2"),
        PlaceId("p3"),
    )


def test_la_casa_entra_aunque_quede_lejos() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("foco")
    agente = world.agents[AgentId("ag_p3_casa_p0")]
    assert world.detail_level(agente) is DetailLevel.MEDIUM
    lugares = world.places_to_consider(agente)
    assert tuple(p.id for p in lugares) == (
        PlaceId("p0"),
        PlaceId("p2"),
        PlaceId("p3"),
    )


def test_sin_radio_no_hay_lod() -> None:
    pack = toy_chain_pack(tuning={"lod_focus_radius": None, "lod_menu_radius": 1})
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("foco")
    for a in world.agents.values():
        assert world.detail_level(a) is DetailLevel.FINE
        assert world.places_to_consider(a) is world.pack.places


def test_sin_foco_no_hay_lod() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = None
    for a in world.agents.values():
        assert world.detail_level(a) is DetailLevel.FINE
        assert world.places_to_consider(a) is world.pack.places


def test_si_el_foco_muere_no_hay_lod() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("fantasma_muerto")
    for a in world.agents.values():
        assert world.detail_level(a) is DetailLevel.FINE
        assert world.places_to_consider(a) is world.pack.places


def test_la_deliberacion_solo_mira_su_menu() -> None:
    pack = toy_chain_pack()
    world = WorldState.new(pack, seed=42)
    world.focus = AgentId("foco")
    agente = world.agents[AgentId("ag_lejos")]
    agente.needs[NeedId("n1")] = 0.95

    menu = world.places_to_consider(agente)
    menu_ids = {p.id for p in menu}
    assert PlaceId("p0") not in menu_ids

    decisiones = candidates(world, agente)
    assert len(decisiones) > 0
    assert all(d.place in menu_ids for d in decisiones)
    assert not any(d.place == PlaceId("p0") for d in decisiones)

    world.focus = None
    decisiones_sin_lod = candidates(world, agente)
    assert any(d.place == PlaceId("p0") for d in decisiones_sin_lod)


# -----------------------------------------------------------------------------
# B.2 — Determinismo y persistencia con LOD
# -----------------------------------------------------------------------------


def test_sin_foco_el_mundo_es_el_de_siempre() -> None:
    pack_path = Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml"
    pack_con_radios = load_pack(pack_path)
    sim1 = Simulation(pack_con_radios, seed=1312)
    sim1.run(pack_con_radios.clock.ticks_per_day)
    huella1 = hashlib.md5("\n".join(sim1.log.to_jsonl()).encode()).hexdigest()

    pack_sin_radios = pack_con_radios.model_copy(
        update={"tuning": pack_con_radios.tuning.model_copy(update={"lod_focus_radius": None})}
    )
    sim2 = Simulation(pack_sin_radios, seed=1312)
    sim2.run(pack_sin_radios.clock.ticks_per_day)
    huella2 = hashlib.md5("\n".join(sim2.log.to_jsonl()).encode()).hexdigest()

    assert huella1 == huella2


def test_el_foco_viaja_en_el_guardado(tmp_path: Path) -> None:
    pack = toy_chain_pack()
    foco = AgentId("foco")

    # 1. Guardado con foco vivo:
    sim = Simulation(pack, seed=42)
    sim.state.focus = foco
    ruta1 = tmp_path / "vivo.json"
    sim.save(ruta1)
    rean1 = Simulation.resume(ruta1, pack)
    assert rean1.state.focus == foco

    # 2. Si el foco muere o no está en agents:
    sim_muerto = Simulation(pack, seed=42)
    sim_muerto.state.focus = foco
    del sim_muerto.state.agents[foco]
    ruta2 = tmp_path / "muerto.json"
    sim_muerto.save(ruta2)
    rean2 = Simulation.resume(ruta2, pack)
    assert rean2.state.focus is None

    # 3. Guardado sin clave "focus" (guardado heredado):
    datos = json.loads(ruta1.read_text())
    if "focus" in datos:
        del datos["focus"]
    ruta3 = tmp_path / "sin_clave.json"
    ruta3.write_text(json.dumps(datos))
    rean3 = Simulation.resume(ruta3, pack)
    assert rean3.state.focus is None


# -----------------------------------------------------------------------------
# B.3 — El instrumento (error_de_lod y comparar)
# -----------------------------------------------------------------------------


def test_con_radio_infinito_el_lod_no_se_aparta() -> None:
    pack_path = Path(__file__).resolve().parents[1] / "packs" / "ciudad" / "pack.yaml"
    pack = load_pack(pack_path)
    pack = pack.model_copy(
        update={"tuning": pack.tuning.model_copy(update={"lod_focus_radius": 999})}
    )
    foco = pack.agents[0].id
    sim = Simulation(pack, seed=1312)
    fid = error_de_lod(sim, dias=1, foco=foco)
    assert all(d == 0.0 for d in fid.general.ejes.values())
    assert all(r == a for r, a in fid.general.sucesos().values())
    assert fid.cuantos.get(DetailLevel.MEDIUM, 0) == 0


def test_con_radio_cero_hay_agentes_en_medio() -> None:
    pack_path = Path(__file__).resolve().parents[1] / "packs" / "ciudad" / "pack.yaml"
    pack = load_pack(pack_path)
    pack = pack.model_copy(
        update={"tuning": pack.tuning.model_copy(update={"lod_focus_radius": 0})}
    )
    foco = pack.agents[0].id
    sim = Simulation(pack, seed=1312)
    fid = error_de_lod(sim, dias=1, foco=foco)
    assert fid.cuantos[DetailLevel.MEDIUM] > 0
    assert DetailLevel.MEDIUM in fid.por_nivel


def test_comparar_dos_mundos_iguales_no_desvia_nada() -> None:
    pack_path = Path(__file__).resolve().parents[1] / "packs" / "ciudad" / "pack.yaml"
    pack = load_pack(pack_path)
    sim = Simulation(pack, seed=1312)
    sim.run(24)
    fid = comparar(sim, deepcopy(sim))
    assert all(d == 0.0 for d in fid.ejes.values())
    assert all(r == a for r, a in fid.sucesos().values())


# -----------------------------------------------------------------------------
# B.4 — Línea de órdenes CLI
# -----------------------------------------------------------------------------


def test_error_lod_sin_foco_es_un_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pack_path = str(Path(__file__).resolve().parents[1] / "packs" / "ciudad" / "pack.yaml")
    monkeypatch.setattr(sys, "argv", ["agora", "--pack", pack_path, "--error-lod"])
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_un_foco_que_no_existe_es_un_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pack_path = str(Path(__file__).resolve().parents[1] / "packs" / "ciudad" / "pack.yaml")
    monkeypatch.setattr(
        sys, "argv", ["agora", "--pack", pack_path, "--foco", "fantasma", "--days", "1"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0
