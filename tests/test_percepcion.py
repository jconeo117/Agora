"""Tests de la percepción: lo que cada uno ha visto delante y lo público de quien conoce
(unidad 23-0, D-178, §B).
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, PlaceId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.perception import (
    PublicFacts,
    knows,
    public_facts,
    saw,
    seen_together,
)
from agora.engine.world import Simulation

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")


def pack_percepcion(**overrides: Any) -> ContentPack:
    """Pack mínimo para probar la percepción con lugares plaza y bosque."""
    data: dict[str, Any] = {
        "id": "pack_test",
        "label": "Pack de prueba de percepción",
        "clock": {"ticks_per_day": 24},
        "needs": [{"id": "n1", "label": "Necesidad", "decay_per_tick": 0.01, "initial": 0.5}],
        "actions": [
            {
                "id": "charlar",
                "label": "Charlar",
                "duration_ticks": 1,
                "requires_affordance": "plaza",
                "effects": {"n1": 0.1},
            },
            {
                "id": "descansar",
                "label": "Descansar",
                "duration_ticks": 1,
            },
        ],
        "places": [
            {"id": "plaza", "label": "Plaza", "affordances": ["plaza"], "neighbors": {"bosque": 1}},
            {"id": "bosque", "label": "Bosque", "neighbors": {"plaza": 1}},
        ],
        "agents": [
            {"id": "a", "label": "Agente A", "home": "plaza", "start_at": "plaza"},
            {"id": "b", "label": "Agente B", "home": "plaza", "start_at": "plaza"},
            {"id": "c", "label": "Agente C", "home": "plaza", "start_at": "plaza"},
            {"id": "d", "label": "Agente D", "home": "bosque", "start_at": "bosque"},
            {"id": "e", "label": "Agente E", "home": "bosque", "start_at": "bosque"},
        ],
        "tuning": {
            "perception_days": 14,
            "perception_max": 300,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# ==============================================================================
# B.1 — Acto dirigido presenciado en el mismo lugar vs otro lugar y actor
# ==============================================================================


def test_b1_acto_dirigido_en_mismo_lugar_lo_anota_c_y_no_d_ni_a() -> None:
    # B.1: Un acto dirigido de A a B en un lugar con C: C lo anota; D en otro lugar, no;
    # A no se lo anota a sí mismo.
    sim = Simulation(pack_percepcion(), seed=42)
    # A, B y C están en 'plaza'. D está en 'bosque'.
    ag_a = AgentId("a")
    ag_b = AgentId("b")
    ag_c = AgentId("c")
    ag_d = AgentId("d")
    plaza = PlaceId("plaza")

    sim._registrar(
        tick=10,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_b)},
    )

    # C estaba en plaza: lo anota
    hechos_c = saw(sim.state, ag_c)
    assert len(hechos_c) == 1
    p = hechos_c[0]
    assert p.actor == ag_a
    assert p.target == ag_b
    assert p.place == plaza
    assert p.action == ActionId("charlar")
    assert p.kind is EventKind.ACTION_STARTED
    assert p.tick == 10

    # B también estaba en plaza y no es el actor: lo anota
    hechos_b = saw(sim.state, ag_b)
    assert len(hechos_b) == 1
    assert hechos_b[0].actor == ag_a
    assert hechos_b[0].target == ag_b

    # D estaba en bosque: no lo anota
    assert len(saw(sim.state, ag_d)) == 0

    # A es el actor: no se lo anota a sí mismo
    assert len(saw(sim.state, ag_a)) == 0
    assert ag_a not in sim.state.percepcion or len(sim.state.percepcion[ag_a]) == 0


# ==============================================================================
# B.2 — Acciones sin destinatario o recoger del suelo no se anotan
# ==============================================================================


def test_b2_accion_sin_destinatario_o_recoger_del_suelo_no_se_anota() -> None:
    # B.2: Una acción sin destinatario o recoger del suelo (ITEM_MOVED sin target de agente)
    # no se anota.
    sim = Simulation(pack_percepcion(), seed=42)
    ag_a = AgentId("a")
    ag_c = AgentId("c")
    plaza = PlaceId("plaza")

    # 1. Acción sin destinatario (descansar sin 'target')
    sim._registrar(
        tick=1,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("descansar"),
        data={},
    )

    # 2. Recoger del suelo: ITEM_MOVED sin subject o donde subject es el mismo actor
    sim._registrar(
        tick=2,
        kind=EventKind.ITEM_MOVED,
        actor=ag_a,
        place=plaza,
        subject=None,
        data={"item": "manzana"},
    )
    sim._registrar(
        tick=3,
        kind=EventKind.ITEM_MOVED,
        actor=ag_a,
        place=plaza,
        subject=ag_a,
        data={"item": "manzana"},
    )

    # C estaba delante pero ninguno de estos hechos es presenciable
    assert len(saw(sim.state, ag_c)) == 0


# ==============================================================================
# B.3 — Búfer respeta 14 días y 300 hechos, y se borra al morir
# ==============================================================================


def test_b3_buffer_respeta_14_dias_y_300_hechos_y_se_borra_al_morir() -> None:
    # B.3: El búfer respeta 14 días y 300 (el más viejo sale primero por seq); al morir,
    # se borra el búfer del agente.
    sim = Simulation(pack_percepcion(), seed=42)
    ag_a = AgentId("a")
    ag_b = AgentId("b")
    ag_c = AgentId("c")
    plaza = PlaceId("plaza")

    # 1. Registro inicial en tick 0
    sim.state.tick = 0
    sim._registrar(
        tick=0,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_b)},
    )
    assert len(sim.state.percepcion[ag_c]) == 1
    assert sim.state.percepcion[ag_c][0].tick == 0
    assert len(saw(sim.state, ag_c)) == 1

    # Avanzamos a más de 14 días (350 ticks > 336 ticks)
    sim.state.tick = 350
    sim._registrar(
        tick=350,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_b)},
    )

    # El hecho de tick 0 debe haber salido por antigüedad (> 14 días)
    buffer_c = sim.state.percepcion[ag_c]
    assert len(buffer_c) == 1
    assert buffer_c[0].tick == 350
    assert not any(p.tick == 0 for p in buffer_c)
    assert not any(p.tick == 0 for p in saw(sim.state, ag_c))

    # 2. Límite de 300 hechos: añadimos 305 hechos en tick 350
    for i in range(1, 306):
        sim._registrar(
            tick=350,
            kind=EventKind.ACTION_STARTED,
            actor=ag_a,
            place=plaza,
            action=ActionId("charlar"),
            data={"target": str(ag_b), "i": i},
        )

    # El búfer no supera 300
    assert len(sim.state.percepcion[ag_c]) == 300
    assert len(saw(sim.state, ag_c)) == 300

    # El más viejo sale primero (orden por seq)
    seqs = [p.seq for p in sim.state.percepcion[ag_c]]
    assert seqs == sorted(seqs)
    # Los últimos 300 permanecen
    assert seqs[0] == sim.state.percepcion[ag_c][-1].seq - 299

    # 3. Al morir, se borra el búfer del agente
    assert ag_c in sim.state.percepcion
    sim.morir(ag_c)
    assert ag_c not in sim.state.percepcion


# ==============================================================================
# B.4 — seen_together cuenta en dos sentidos y knows desconocido vs visto
# ==============================================================================


def test_b4_seen_together_ambos_sentidos_y_knows_desconocido_vs_visto() -> None:
    # B.4: seen_together cuenta en los dos sentidos; knows es falso para un
    # desconocido nunca visto y verdadero tras verle una vez.
    sim = Simulation(pack_percepcion(), seed=42)
    ag_a = AgentId("a")
    ag_b = AgentId("b")
    ag_c = AgentId("c")
    ag_e = AgentId("e")  # En bosque, desconocido para C
    plaza = PlaceId("plaza")

    # C no conoce a E (nunca visto, sin vínculo ni relación)
    assert not knows(sim.state, ag_c, ag_e)
    # Nadie se conoce a sí mismo como tercero
    assert not knows(sim.state, ag_c, ag_c)

    # C ve a A dirigirse a B
    sim._registrar(
        tick=1,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_b)},
    )
    # C ve a B dirigirse a A
    sim._registrar(
        tick=2,
        kind=EventKind.ACTION_STARTED,
        actor=ag_b,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_a)},
    )

    # seen_together cuenta en ambos sentidos
    assert seen_together(sim.state, ag_c, ag_a, ag_b) == 2
    assert seen_together(sim.state, ag_c, ag_b, ag_a) == 2

    # Ahora E aparece en un hecho presenciado por C
    sim._registrar(
        tick=3,
        kind=EventKind.ACTION_STARTED,
        actor=ag_e,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_a)},
    )

    # Tras verle una vez, C ya conoce a E
    assert knows(sim.state, ag_c, ag_e) is True


# ==============================================================================
# B.5 — public_facts: desconocido es None; conocido no trae lo privado
# ==============================================================================


def test_b5_public_facts_desconocido_es_none_y_conocido_no_trae_lo_privado() -> None:
    # B.5: public_facts de un desconocido es None; de un conocido no trae aprecio,
    # necesidades, carácter ni marcas.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=42)
    agentes = sim.state.agents_in_order()
    yo = agentes[0].spec_id

    # Buscar a un desconocido (no conocido por 'yo')
    desconocido = next(
        a.spec_id for a in agentes
        if a.spec_id != yo and not knows(sim.state, yo, a.spec_id)
    )
    assert public_facts(sim.state, yo, desconocido) is None

    # Buscar a un conocido (con vínculo o relación con 'yo')
    conocido = next(
        a.spec_id for a in agentes
        if a.spec_id != yo and knows(sim.state, yo, a.spec_id)
    )

    hechos = public_facts(sim.state, yo, conocido)
    assert hechos is not None
    assert isinstance(hechos, PublicFacts)
    assert hechos.nombre == sim.state.censo[conocido].label
    assert hechos.vivo is True
    assert isinstance(hechos.relaciones, tuple)
    assert isinstance(hechos.grupos, tuple)
    assert isinstance(hechos.rasgos, tuple)
    assert isinstance(hechos.condiciones, tuple)

    # No trae aprecio, agravio, necesidades, carácter, marcas ni metas
    assert not hasattr(hechos, "aprecio")
    assert not hasattr(hechos, "agravio")
    assert not hasattr(hechos, "necesidades")
    assert not hasattr(hechos, "caracter")
    assert not hasattr(hechos, "marcas")
    assert not hasattr(hechos, "metas")

    campos = {f.name for f in dataclasses.fields(PublicFacts)}
    assert "aprecio" not in campos
    assert "agravio" not in campos
    assert "necesidades" not in campos
    assert "caracter" not in campos
    assert "marcas" not in campos
    assert "metas" not in campos


# ==============================================================================
# B.6 — Guardar y cargar conserva búferes; guardado viejo carga vacío
# ==============================================================================


def test_b6_guardar_y_cargar_conserva_buffers_y_guardado_viejo_carga_vacio(
    tmp_path: Path,
) -> None:
    # B.6: Guardar y cargar conserva los búferes; un guardado viejo (sin campo de
    # percepción) carga vacío.
    sim = Simulation(pack_percepcion(), seed=42)
    ag_a = AgentId("a")
    ag_b = AgentId("b")
    ag_c = AgentId("c")
    plaza = PlaceId("plaza")

    sim._registrar(
        tick=10,
        kind=EventKind.ACTION_STARTED,
        actor=ag_a,
        place=plaza,
        action=ActionId("charlar"),
        data={"target": str(ag_b)},
    )
    assert len(sim.state.percepcion[ag_c]) > 0

    # Guardar y reanudar
    ruta_guardado = tmp_path / "partida_percepcion.json"
    sim.save(ruta_guardado)

    sim_resumida = Simulation.resume(ruta_guardado, sim.pack)
    assert sim_resumida.state.percepcion == sim.state.percepcion
    assert len(sim_resumida.state.percepcion[ag_c]) == len(sim.state.percepcion[ag_c])
    assert saw(sim_resumida.state, ag_c) == saw(sim.state, ag_c)

    # Guardado viejo (sin el campo 'percepcion')
    with open(ruta_guardado, encoding="utf-8") as f:
        datos = json.load(f)
    assert "percepcion" in datos
    del datos["percepcion"]

    ruta_vieja = tmp_path / "partida_vieja.json"
    with open(ruta_vieja, "w", encoding="utf-8") as f:
        json.dump(datos, f)

    sim_vieja = Simulation.resume(ruta_vieja, sim.pack)
    assert sim_vieja.state.percepcion == {}
    assert len(saw(sim_vieja.state, ag_c)) == 0


# ==============================================================================
# B.7 — Log idéntico con y sin percepción
# ==============================================================================


def test_b7_log_identico_con_y_sin_percepcion(monkeypatch: pytest.MonkeyPatch) -> None:
    # B.7: Log idéntico con y sin percepción.
    # Corremos dos simulaciones con la misma semilla (Confluencia, 2 días = 48 ticks).
    # Una registra percepciones normalmente; la otra tiene la percepción desactivada.
    pack = load_pack(CONFLUENCIA_PACK)
    sim_con = Simulation(pack, seed=7)
    for _ in range(48):
        sim_con.tick()

    # Comprobar que en sim_con la percepción efectivamente acumuló hechos
    total_percepciones = sum(len(b) for b in sim_con.state.percepcion.values())
    assert total_percepciones > 0

    # Segunda corrida desactivando _percibir a nivel de clase Simulation
    monkeypatch.setattr(Simulation, "_percibir", lambda self, evento: None)
    sim_sin = Simulation(pack, seed=7)
    for _ in range(48):
        sim_sin.tick()

    assert len(sim_sin.state.percepcion) == 0

    # Los logs deben ser exactamente idénticos, evento por evento
    assert len(sim_con.log) == len(sim_sin.log)
    for e1, e2 in zip(sim_con.log, sim_sin.log, strict=True):
        assert e1.seq == e2.seq
        assert e1.tick == e2.tick
        assert e1.kind == e2.kind
        assert e1.actor == e2.actor
        assert e1.place == e2.place
        assert e1.action == e2.action
        assert e1.subject == e2.subject
        assert e1.data == e2.data
