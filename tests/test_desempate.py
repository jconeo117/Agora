"""Tests para el desempate neutral entre destinatarios (I-007)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from agora.engine.ontology import AgentId, PlaceId, TargetSpec
from agora.engine.pack import load_pack
from agora.engine.state import AgentState
from agora.engine.world import Simulation


def test_entre_iguales_no_gana_siempre_el_mismo_nombre() -> None:
    """Un agente ante diez desconocidos a aprecio 0 y la misma atracción;
    sobre 200 ticks, el elegido cambia, y cada uno de los diez sale entre
    el 4 % y el 18 % de las veces. Antes de la unidad salía siempre el id mayor.
    """
    pack = load_pack(Path("packs/dark_fantasy/pack.yaml"))
    sim = Simulation(pack, seed=1312)
    quien = AgentState(spec_id=AgentId("agente"), at=PlaceId("p"), needs={})
    candidatos = [
        AgentState(spec_id=AgentId(f"candidato_{i:02d}"), at=PlaceId("p"), needs={})
        for i in range(10)
    ]
    spec = TargetSpec(min_regard=0.0)

    conteo: Counter[AgentId] = Counter()
    elegidos_por_tick: list[AgentId] = []
    total_ticks = 200
    for tick in range(total_ticks):
        elegido = quien.elegir_destinatario(candidatos, spec, tick=tick, world=sim.state)
        assert elegido is not None
        conteo[elegido.spec_id] += 1
        elegidos_por_tick.append(elegido.spec_id)

    # El elegido cambia en el tiempo (M2)
    assert len(set(elegidos_por_tick)) == 10

    # Cada uno de los diez sale entre el 4 % y el 18 % de las veces (M1, M2)
    for c in candidatos:
        proporcion = conteo[c.spec_id] / total_ticks
        assert 0.04 <= proporcion <= 0.18, (
            f"{c.spec_id} fue elegido {proporcion:.1%}, fuera del rango [4%, 18%]"
        )


HIJO_DESEMPATE = """
from pathlib import Path
from agora.engine.ontology import AgentId, PlaceId, TargetSpec
from agora.engine.pack import load_pack
from agora.engine.state import AgentState
from agora.engine.world import Simulation

pack = load_pack(Path("packs/dark_fantasy/pack.yaml"))
sim = Simulation(pack, seed=1312)
quien = AgentState(spec_id=AgentId("agente"), at=PlaceId("p"), needs={})
candidatos = [
    AgentState(spec_id=AgentId(f"candidato_{i:02d}"), at=PlaceId("p"), needs={})
    for i in range(10)
]
spec = TargetSpec(min_regard=0.0)
elegidos = [
    str(quien.elegir_destinatario(candidatos, spec, tick=t, world=sim.state).spec_id)
    for t in range(50)
]
print(",".join(elegidos))
"""


def test_el_desempate_es_reproducible() -> None:
    """Misma semilla, mismo tick, mismos presentes -> mismo elegido, también
    en otro proceso (con PYTHONHASHSEED distinto).
    """
    salidas = [
        subprocess.run(
            [sys.executable, "-c", HIJO_DESEMPATE],
            env={**os.environ, "PYTHONHASHSEED": semilla},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for semilla in ("0", "1")
    ]
    assert salidas[0] == salidas[1]


def test_el_orden_de_los_presentes_no_importa() -> None:
    """La misma lista en dos órdenes da el mismo elegido."""
    pack = load_pack(Path("packs/dark_fantasy/pack.yaml"))
    sim = Simulation(pack, seed=1312)
    quien = AgentState(spec_id=AgentId("agente"), at=PlaceId("p"), needs={})
    candidatos_orden_a = [
        AgentState(spec_id=AgentId(f"candidato_{i:02d}"), at=PlaceId("p"), needs={})
        for i in range(10)
    ]
    candidatos_orden_b = list(reversed(candidatos_orden_a))
    spec = TargetSpec(min_regard=0.0)

    for tick in range(50):
        elegido_a = quien.elegir_destinatario(
            candidatos_orden_a, spec, tick=tick, world=sim.state
        )
        elegido_b = quien.elegir_destinatario(
            candidatos_orden_b, spec, tick=tick, world=sim.state
        )
        assert elegido_a is not None and elegido_b is not None
        assert elegido_a.spec_id == elegido_b.spec_id


def test_el_desempate_no_pisa_al_aprecio() -> None:
    """Con uno a aprecio 0.4 y otro a 0.1 (modo por defecto), gana el de 0.4 siempre;
    en por_desconocido, el de menos aprecio siempre; a igual aprecio y distinta atracción,
    la atracción.
    """
    pack = load_pack(Path("packs/dark_fantasy/pack.yaml"))
    sim = Simulation(pack, seed=1312)

    id_a = AgentId("amigo_a")
    id_b = AgentId("amigo_b")

    # 1. Modo por defecto: gana el de mayor aprecio (0.4 sobre 0.1)
    quien_def = AgentState(spec_id=AgentId("quien"), at=PlaceId("p"), needs={})
    quien_def.meet(id_a, tick=0)
    quien_def.bonds[id_a].regard = 0.4
    quien_def.meet(id_b, tick=0)
    quien_def.bonds[id_b].regard = 0.1

    candidatos_amigos = [
        AgentState(spec_id=id_a, at=PlaceId("p"), needs={}),
        AgentState(spec_id=id_b, at=PlaceId("p"), needs={}),
    ]
    spec_def = TargetSpec(min_regard=0.0)

    for tick in range(50):
        elegido = quien_def.elegir_destinatario(
            candidatos_amigos, spec_def, tick=tick, world=sim.state
        )
        assert elegido is not None and elegido.spec_id == id_a

    # 2. Modo por_desconocido: gana el de menor aprecio (0.1 sobre 0.4)
    spec_desc = TargetSpec(por_desconocido=True, max_regard=0.5)
    for tick in range(50):
        elegido = quien_def.elegir_destinatario(
            candidatos_amigos, spec_desc, tick=tick, world=sim.state
        )
        assert elegido is not None and elegido.spec_id == id_b

    # 3. A igual aprecio y distinta atracción: gana la atracción
    quien_atr = AgentState(
        spec_id=AgentId("quien_atr"),
        at=PlaceId("p"),
        needs={},
        tastes={str(id_a): 2.0},
    )
    for tick in range(50):
        elegido = quien_atr.elegir_destinatario(
            candidatos_amigos, spec_def, tick=tick, world=sim.state
        )
        assert elegido is not None and elegido.spec_id == id_a


def test_otra_semilla_otro_desempate() -> None:
    """Con otra semilla, el reparto del caso 1 cambia."""
    pack = load_pack(Path("packs/dark_fantasy/pack.yaml"))
    sim_1 = Simulation(pack, seed=1312)
    sim_2 = Simulation(pack, seed=7)

    quien = AgentState(spec_id=AgentId("agente"), at=PlaceId("p"), needs={})
    candidatos = [
        AgentState(spec_id=AgentId(f"candidato_{i:02d}"), at=PlaceId("p"), needs={})
        for i in range(10)
    ]
    spec = TargetSpec(min_regard=0.0)

    serie_1 = [
        quien.elegir_destinatario(candidatos, spec, tick=t, world=sim_1.state).spec_id  # type: ignore[union-attr]
        for t in range(50)
    ]
    serie_2 = [
        quien.elegir_destinatario(candidatos, spec, tick=t, world=sim_2.state).spec_id  # type: ignore[union-attr]
        for t in range(50)
    ]
    assert serie_1 != serie_2
