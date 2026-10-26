"""Pruebas de que reanudar una simulación es exactamente idéntico a no haber parado."""

from __future__ import annotations

import dataclasses
import enum
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agora.engine.events import EventKind
from agora.engine.memory import Recuerdo
from agora.engine.ontology import AgentId, NeedId, PropertyId, PropertyKind
from agora.engine.pack import load_pack
from agora.engine.persistence import (
    _agente_a_dict,
    _bond_a_dict,
    _propiedad_a_dict,
    _recuerdo_a_lista,
    save,
)
from agora.engine.state import (
    AgentState,
    Bond,
    Condicion,
    Faccion,
    Propiedad,
)
from agora.engine.world import Simulation
from tests.test_condiciones import AG1, HERIDA, cond_pack
from tests.test_facciones import gremio_pack


def plano(x: Any) -> Any:
    """Cualquier estado del motor como algo comparable y ordenado. Los floats a
    12 decimales: son los mismos números, no aproximaciones."""
    if isinstance(x, float):
        return round(x, 12)
    if isinstance(x, str | int | bool) or x is None:
        return x
    if isinstance(x, enum.Enum):
        return x.value
    if isinstance(x, BaseModel):
        return plano(x.model_dump())
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return tuple((f.name, plano(getattr(x, f.name))) for f in dataclasses.fields(x))
    if isinstance(x, dict):
        return tuple(sorted((plano(k), plano(v)) for k, v in x.items()))
    if isinstance(x, set | frozenset):
        return tuple(sorted(plano(v) for v in x))
    if isinstance(x, list | tuple):
        return tuple(plano(v) for v in x)
    raise TypeError(f"la foto no sabe aplanar {type(x).__name__}")


def foto(sim: Simulation) -> dict[str, object]:
    w = sim.state
    salida: dict[str, object] = {
        "focus": w.focus,
        "tick": w.tick,
        "censo": tuple(sorted(map(str, w.censo))),
        "facciones": plano(w.facciones),
        "propiedades": plano(w.propiedades),
        "situations": plano(w.situations),
        "last_trigger": plano(w.last_trigger),
    }
    for a in w.agents_in_order():
        for f in dataclasses.fields(a):
            valor = getattr(a, f.name)
            if f.name == "relations":
                # Una relación vacía y una ausente son lo mismo para el motor
                # (`world.py:529-533` pregunta `quien in ()`), y `save` descarta
                # las vacías. Sin esto la foto vería una diferencia que no existe.
                valor = {k: v for k, v in valor.items() if v}
            salida[f"{a.spec_id}.{f.name}"] = plano(valor)
        salida[f"{a.spec_id}.memoria"] = plano(w.memoria.de(a.spec_id))
    return salida


def test_reanudar_confluencia_es_no_haber_parado(tmp_path: Path) -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml")
    seguida = Simulation(pack, seed=1312)
    seguida.run(96)

    partida = Simulation(pack, seed=1312)
    partida.run(96)
    fichero = tmp_path / "partida.json"
    partida.save(fichero)
    reanudada = Simulation.resume(fichero, pack)

    foto_seg = foto(seguida)
    foto_rean = foto(reanudada)
    diff = {k: (foto_seg[k], foto_rean[k]) for k in foto_seg if foto_seg[k] != foto_rean.get(k)}
    assert foto_seg == foto_rean, f"Diferencias a 96 ticks: {list(diff.keys())}"

    seguida.run(12)
    reanudada.run(12)
    foto_seg_12 = foto(seguida)
    foto_rean_12 = foto(reanudada)
    diff_12 = {
        k: (foto_seg_12[k], foto_rean_12[k])
        for k in foto_seg_12
        if foto_seg_12[k] != foto_rean_12.get(k)
    }
    assert foto_seg_12 == foto_rean_12, f"Diferencias a 96+12 ticks: {list(diff_12.keys())}"


def test_reanudar_con_lod_es_no_haber_parado(tmp_path: Path) -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml")
    foco = AgentId("eris_cenizal")
    seguida = Simulation(pack, seed=1312)
    seguida.state.focus = foco
    seguida.run(96)

    partida = Simulation(pack, seed=1312)
    partida.state.focus = foco
    partida.run(96)
    fichero = tmp_path / "partida_lod.json"
    partida.save(fichero)
    reanudada = Simulation.resume(fichero, pack)

    foto_seg = foto(seguida)
    foto_rean = foto(reanudada)
    diff = {k: (foto_seg[k], foto_rean[k]) for k in foto_seg if foto_seg[k] != foto_rean.get(k)}
    assert foto_seg == foto_rean, f"Diferencias a 96 ticks con LOD: {list(diff.keys())}"

    seguida.run(12)
    reanudada.run(12)
    foto_seg_12 = foto(seguida)
    foto_rean_12 = foto(reanudada)
    diff_12 = {
        k: (foto_seg_12[k], foto_rean_12[k])
        for k in foto_seg_12
        if foto_seg_12[k] != foto_rean_12.get(k)
    }
    assert foto_seg_12 == foto_rean_12, f"Diferencias a 96+12 ticks con LOD: {list(diff_12.keys())}"


def test_las_facciones_viajan_enteras(tmp_path: Path) -> None:
    pack = gremio_pack()
    sim = Simulation(pack, seed=1)
    sim.run(6)

    facciones = sorted(sim.state.facciones.values(), key=lambda f: f.id)
    assert len(facciones) >= 2
    for f in facciones:
        f.prestigio = 0.37
    facciones[0].enemigas.add(facciones[1].id)

    fichero = tmp_path / "facciones.json"
    sim.save(fichero)
    otra = Simulation.resume(fichero, pack)
    assert plano(sim.state.facciones) == plano(otra.state.facciones)


def test_cada_campo_se_guarda_o_se_deriva(tmp_path: Path) -> None:
    pack = load_pack(Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml")
    sim = Simulation(pack, seed=1312)
    agente = sim.state.agents_in_order()[0]

    guardados = set(_agente_a_dict(agente, ())) - {"memorias"}
    derivados = {
        "need_weights",
        "phase_shift",
        "aptitud_base",
        "gains",
        "caps",
        "costs",
        "strain",
        "temperament",
        "metas",
        "ledger",
        "equipado_gains",
        "equipado_costs",
    }
    campos_agente = {f.name for f in dataclasses.fields(AgentState)}
    assert campos_agente == guardados | derivados, (
        f"Campos sin clasificar en AgentState: {campos_agente ^ (guardados | derivados)}. "
        "Guárdalo en _agente_a_dict o añádelo a DERIVADOS y al docstring de persistence.py:107."
    )
    assert not (guardados & derivados), f"Campos en ambos: {guardados & derivados}"

    r = Recuerdo(seq=1, tick=0, kind=EventKind.ACTION_COMPLETED)
    assert len(_recuerdo_a_lista(r)) == len(dataclasses.fields(Recuerdo))

    assert set(_bond_a_dict(Bond(regard=0.1, encounters=1))) == {
        f.name for f in dataclasses.fields(Bond)
    }

    # Condicion: comprobando un guardado con una condicion
    c_pack = cond_pack()
    c_sim = Simulation(c_pack, seed=1)
    c_sim.afligir(AG1, HERIDA, marca="brazo")
    c_fichero = tmp_path / "cond.json"
    save(c_sim.state, set(), c_fichero)
    c_datos = json.loads(c_fichero.read_text(encoding="utf-8"))
    c_ag_datos = next(a for a in c_datos["agents"] if a["spec_id"] == str(AG1))
    assert len(c_ag_datos["condiciones"]) > 0
    assert len(c_ag_datos["condiciones"][0]) == len(dataclasses.fields(Condicion))

    # Faccion
    f_pack = gremio_pack()
    f_sim = Simulation(f_pack, seed=1)
    f_sim.run(6)
    f_fichero = tmp_path / "facciones_check.json"
    f_sim.save(f_fichero)
    f_datos = json.loads(f_fichero.read_text(encoding="utf-8"))
    assert len(f_datos["facciones"]) > 0
    assert set(f_datos["facciones"][0].keys()) == {f.name for f in dataclasses.fields(Faccion)}

    # Propiedad
    prop = Propiedad(
        id=PropertyId("p1"),
        tipo=PropertyKind.DEUDA,
        objeto="d1",
        renta={NeedId("oro"): 1.0},
        tributo={},
    )
    assert set(_propiedad_a_dict(prop, del_pack=False, objeto=True)) == (
        {f.name for f in dataclasses.fields(Propiedad)} - {"tributo"}
    )
    assert set(_propiedad_a_dict(prop, del_pack=False, objeto=False)) == (
        {f.name for f in dataclasses.fields(Propiedad)} - {"tributo", "lugar", "equipado"}
    )
