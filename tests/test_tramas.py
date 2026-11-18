"""Pruebas de tramas personales subjetivas (unidad 23a, D-178, §B)."""

from __future__ import annotations

import copy
import io
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    Choice,
    EffectSpec,
    MarkId,
    NeedId,
    PlaceId,
    PlotCondition,
    PlotId,
    PropertyKind,
    Step,
    StepId,
    TraitId,
)
from agora.engine.ontology import (
    TestUse as OntologyTestUse,
)
from agora.engine.pack import ContentPack, PackError, load_pack
from agora.engine.persistence import load, save
from agora.engine.plots import (
    _del_protagonista as _cumple_protagonista,
)
from agora.engine.plots import (
    _elige_npc,
    _papeles,
    _probar,
    _sembrar,
    inclinacion,
    pasar_dia,
)
from agora.engine.ports import Contest, Outcome, PlotView, Resolution
from agora.engine.state import Intencion, PlotRun, WorldState
from agora.engine.world import Simulation
from agora.play import Recorder, Script
from agora.present import sheet_view

CONFLUENCIA_PACK_PATH = Path("packs/confluencia/pack.yaml")
CIUDAD_PACK_PATH = Path("packs/ciudad/pack.yaml")


def pack_tramas_base() -> dict[str, Any]:
    """Diccionario base para construir ContentPack válido con soporte de tramas."""
    return {
        "id": "pack_test",
        "label": "Pack de prueba de tramas",
        "clock": {"ticks_per_day": 24, "phases": [{"id": "dia", "label": "Día", "starts_at": 0}]},
        "needs": [{"id": "n1", "label": "Necesidad 1", "decay_per_tick": 0.01, "initial": 0.5}],
        "traits": [
            {"id": "valor", "label": "Valor"},
            {"id": "prudencia", "label": "Prudencia"},
            {"id": "fuerza", "label": "Fuerza"},
        ],
        "places": [
            {"id": "plaza", "label": "Plaza", "affordances": ["plaza"], "neighbors": {"bosque": 1}},
            {"id": "bosque", "label": "Bosque", "neighbors": {"plaza": 1}},
        ],
        "actions": [
            {
                "id": "charlar",
                "label": "Charlar",
                "duration_ticks": 1,
                "requires_affordance": "plaza",
                "requires_company": 1,
                "target": {"gives": {"n1": 0.05}},
            },
            {
                "id": "descansar",
                "label": "Descansar",
                "duration_ticks": 1,
            },
            {
                "id": "prestar",
                "label": "Prestar",
                "duration_ticks": 1,
                "requires_company": 1,
                "target": {"crea_deuda": {"saldo": {"n1": 0.1}, "renta": {"n1": 0.01}}},
            },
            {
                "id": "desafiar",
                "label": "Desafiar",
                "duration_ticks": 1,
                "requires_company": 1,
                "target": {"gives": {"n1": 0.01}},
            },
        ],
        "agents": [
            {
                "id": "yo",
                "label": "Protagonista",
                "home": "plaza",
                "start_at": "plaza",
                "traits": {"valor": 0.9, "prudencia": 0.1, "fuerza": 0.8},
            },
            {
                "id": "agente_a",
                "label": "Agente A",
                "home": "plaza",
                "start_at": "plaza",
                "traits": {"valor": 0.5},
            },
            {
                "id": "agente_b",
                "label": "Agente B",
                "home": "plaza",
                "start_at": "plaza",
                "traits": {"valor": 0.5},
            },
            {
                "id": "agente_c",
                "label": "Agente C",
                "home": "plaza",
                "start_at": "plaza",
                "traits": {"valor": 0.5},
            },
            {
                "id": "rival",
                "label": "Rival",
                "home": "bosque",
                "start_at": "bosque",
                "traits": {"fuerza": 0.2},
            },
        ],
        "relations": [
            {"id": "amigo", "label": "amigo"},
            {"id": "pareja", "label": "pareja"},
        ],
        "situations": [],
        "items": [
            {"id": "daga", "label": "Daga", "slot": "arma"},
        ],
        "tuning": {
            "memory_capacity": 50,
            "perception_days": 14,
            "perception_max": 300,
            "plot_lean_max": 2.0,
            "grief_scale": 0.5,
        },
        "plots": {
            "marks": [
                {"id": "secreto", "label": "Secreto", "hidden": True, "max": 9},
                {"id": "fama_local", "label": "Fama Local", "hidden": False, "max": 5},
            ],
            "fame": {
                "label": "Fama",
                "decay_per_day": 0.01,
                "on": {"rank_up": 0.05, "action": {}},
            },
            "tests": {
                "combate": {"label": "Combate", "actor": "fuerza", "against": "fuerza"},
            },
            "plots": [
                {
                    "id": "t1",
                    "label": "Trama 1",
                    "category": "test",
                    "chance": 1.0,
                    "cooldown_days": 10,
                    "protagonist": [],
                    "refs": [
                        {"name": "otro", "when": [{"alive": True}]},
                    ],
                    "steps": [
                        {
                            "id": "s1",
                            "choices": [
                                {
                                    "label": "Opcion 1",
                                    "appeal": {"valor": 1.0},
                                    "effects": [{"mark": "fama_local", "delta": 1}],
                                    "next": None,
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }


def make_pack(**overrides: Any) -> ContentPack:
    raw = pack_tramas_base()
    raw.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(raw)


# ==============================================================================
# B.1 — Formato y carga
# ==============================================================================


def test_b1_1_condicion_sobre_referencia_privada_no_carga() -> None:
    """1. Una condición sobre una referencia que lee aprecio, agravio, necesidad o
    marca ajena no carga (B.1.1, M9)."""
    raw_base = pack_tramas_base()

    for privada in ("regard_to", "grudge_to", "need", "mark"):
        raw = copy.deepcopy(raw_base)
        plots_list = raw["plots"]["plots"]
        assert isinstance(plots_list, list)
        cond_dict: dict[str, Any]
        if privada == "regard_to":
            cond_dict = {"regard_to": "otro", "min": 0.5}
        elif privada == "grudge_to":
            cond_dict = {"grudge_to": "otro", "min": 0.5}
        elif privada == "need":
            cond_dict = {"need": "n1", "min": 0.5}
        else:
            cond_dict = {"mark": "secreto", "min": 1}

        plots_list[0]["refs"] = [
            {"name": "otro", "when": [cond_dict]},
        ]

        with pytest.raises((PackError, ValueError)) as exc:
            ContentPack.model_validate(raw)
        msg = str(exc.value)
        assert f"«{privada}» no se puede leer de una referencia" in msg, (
            f"Condición privada {privada} debería haber sido rechazada: {msg}"
        )


def test_b1_2_next_con_ciclo_no_carga() -> None:
    """2. next con ciclo: no carga (B.1.2)."""
    raw = pack_tramas_base()
    plots_list = raw["plots"]["plots"]
    assert isinstance(plots_list, list)
    plots_list[0]["steps"] = [
        {
            "id": "paso_a",
            "choices": [{"label": "O1", "appeal": {}, "effects": [], "next": "paso_b"}],
        },
        {
            "id": "paso_b",
            "choices": [{"label": "O2", "appeal": {}, "effects": [], "next": "paso_a"}],
        },
    ]
    with pytest.raises((PackError, ValueError)) as exc:
        ContentPack.model_validate(raw)
    assert "los pasos forman un ciclo" in str(exc.value)


def test_b1_2_latido_fuera_de_vocabulario_no_carga() -> None:
    """2. latido fuera del vocabulario: no carga (B.1.2)."""
    raw = pack_tramas_base()
    plots_list = raw["plots"]["plots"]
    assert isinstance(plots_list, list)
    plots_list[0]["steps"] = [
        {
            "id": "espera",
            "expects": {"beat": "latido_inventado", "ref": "otro"},
            "within_days": 5,
            "next": None,
        }
    ]
    with pytest.raises((PackError, ValueError)):
        ContentPack.model_validate(raw)


def test_b1_2_on_timeout_invalido_no_carga() -> None:
    """2. on_timeout inválido (a paso inexistente): no carga (B.1.2)."""
    raw = pack_tramas_base()
    plots_list = raw["plots"]["plots"]
    assert isinstance(plots_list, list)
    plots_list[0]["steps"] = [
        {
            "id": "espera",
            "expects": {"beat": "talked_with", "ref": "otro"},
            "within_days": 5,
            "on_timeout": "paso_que_no_existe",
            "next": None,
        }
    ]
    with pytest.raises((PackError, ValueError)) as exc:
        ContentPack.model_validate(raw)
    assert "'paso_que_no_existe' no es un paso" in str(exc.value)


def test_b1_2_act_sin_destinatario_no_carga() -> None:
    """2. act con una acción sin destinatario (sin target): no carga (B.1.2)."""
    raw = pack_tramas_base()
    plots_list = raw["plots"]["plots"]
    assert isinstance(plots_list, list)
    plots_list[0]["steps"] = [
        {
            "id": "decidir",
            "choices": [
                {
                    "label": "Descansar juntos",
                    "appeal": {},
                    "act": {"action": "descansar", "to": "otro", "within_days": 3},
                    "next": None,
                }
            ],
        }
    ]
    with pytest.raises((PackError, ValueError)) as exc:
        ContentPack.model_validate(raw)
    assert "'descansar' no existe o no va a alguien" in str(exc.value)


def test_b1_3_marca_sin_productor_aviso_o_error(tmp_path: Path) -> None:
    """3. Marca consumida sin productor: aviso; con strict_marks, error (B.1.3)."""
    raw_pack = pack_tramas_base()
    # Una marca 'desconocida' que se lee en una opción pero nadie produce
    plots_list = raw_pack["plots"]["plots"]
    assert isinstance(plots_list, list)
    raw_pack["plots"]["marks"].append({"id": "huerfana", "label": "Huerfana"})
    plots_list[0]["steps"][0]["choices"][0]["requires"] = [{"mark": "huerfana", "min": 1}]

    # Con strict_marks = True: debe fallar con error
    raw_strict = copy.deepcopy(raw_pack)
    raw_strict["plots"]["strict_marks"] = True
    with pytest.raises((PackError, ValueError)) as exc:
        ContentPack.model_validate(raw_strict)
    assert "la marca 'huerfana' se lee y nadie la produce" in str(exc.value)

    # Con strict_marks = False: emite UserWarning al cargar con load_pack
    pack_dir = tmp_path / "pack_aviso"
    pack_dir.mkdir()
    pack_file = pack_dir / "pack.yaml"
    tramas_file = pack_dir / "tramas.yaml"

    plots_section = raw_pack.pop("plots")
    pack_file.write_text(yaml.safe_dump(raw_pack), encoding="utf-8")
    tramas_file.write_text(yaml.safe_dump(plots_section), encoding="utf-8")

    with pytest.warns(UserWarning, match="la marca 'huerfana' se lee y nadie la produce"):
        load_pack(pack_file)


def test_b1_4_sin_tramas_yaml_log_identico() -> None:
    """4. Sin tramas.yaml: log idéntico (B.1.4)."""
    pack = load_pack(CIUDAD_PACK_PATH)
    assert pack.plots is None

    sim1 = Simulation(pack, seed=123)
    sim1.run(48)

    sim2 = Simulation(pack, seed=123)
    sim2.run(48)

    assert [e.kind for e in sim1.log] == [e.kind for e in sim2.log]
    assert [e.data for e in sim1.log] == [e.data for e in sim2.log]


# ==============================================================================
# B.2 — Subjetividad
# ==============================================================================


def test_b2_1_referencias_solo_salen_de_quien_el_protagonista_conoce() -> None:
    """1. Las referencias solo salen de quien el protagonista conoce (B.2.1)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo = sim.state.agents[AgentId("yo")]
    trama = pack.plots.plots[0]  # type: ignore[union-attr]

    # Al tick 0, 'yo' no conoce a nadie
    refs = _papeles(sim, yo, trama, dia=0)
    assert refs is None

    # Hacemos que 'yo' conozca únicamente a 'agente_a'
    sim._registrar(
        tick=0,
        kind=EventKind.ACTION_STARTED,
        actor=AgentId("agente_a"),
        place=PlaceId("plaza"),
        action=ActionId("charlar"),
        data={"target": "yo"},
    )
    # Ahora 'yo' conoce a 'agente_a', pero no a 'agente_b' ni 'agente_c'
    refs = _papeles(sim, yo, trama, dia=0)
    assert refs is not None
    assert refs["otro"] == AgentId("agente_a")


def test_b2_1_referencias_deterministas_por_hash_no_por_id() -> None:
    """1. Referencias sorteadas deterministamente por hash de clave, no por id (B.2.1, M1)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo = sim.state.agents[AgentId("yo")]
    trama = pack.plots.plots[0]  # type: ignore[union-attr]

    # 'yo' conoce a agente_a y agente_c
    for quien in ("agente_a", "agente_c"):
        sim._registrar(
            tick=0,
            kind=EventKind.ACTION_STARTED,
            actor=AgentId(quien),
            place=PlaceId("plaza"),
            action=ActionId("charlar"),
            data={"target": "yo"},
        )

    # Con seed=42 y dia=0:
    # stream("trama-papel", yo, "t1", "otro", 0, "agente_c") da ~0.8496
    # stream("trama-papel", yo, "t1", "otro", 0, "agente_a") da ~0.9005
    # Por hash stream gana agente_c. Si fuera por orden de id ganaría agente_a ("a" < "c").
    refs = _papeles(sim, yo, trama, dia=0)
    assert refs is not None
    assert refs["otro"] == AgentId("agente_c"), (
        "El sorteo de referencias debe usar el hash stream con clave, no el id (M1)"
    )


def test_b2_2_paso_espera_avanza_con_hecho_percibido_y_no_fuera_de_su_vista() -> None:
    """2. Un paso de espera avanza con un hecho percibido por el protagonista
    y no fuera de su vista (B.2.2, M14)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"][0]["steps"] = [
        {
            "id": "esperar",
            "expects": {"beat": "seen_with", "ref": "otro"},
            "within_days": 10,
            "next": "siguiente",
        },
        {
            "id": "siguiente",
            "choices": [{"label": "Fin", "appeal": {}, "effects": [], "next": None}],
        },
    ]
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    otro_id = AgentId("agente_a")
    tercero_id = AgentId("agente_b")

    # Protagonista en 'plaza'
    sim.state.agents[yo_id].at = PlaceId("plaza")
    # 'otro' y 'tercero' en 'bosque'
    sim.state.agents[otro_id].at = PlaceId("bosque")
    sim.state.agents[tercero_id].at = PlaceId("bosque")

    sim.state.tramas[yo_id] = PlotRun(
        plot=PlotId("t1"),
        empezo=0,
        refs={"otro": otro_id},
        paso=StepId("esperar"),
        desde=0,
    )

    # Ocurre un hecho en bosque (fuera de la vista de 'yo')
    sim._registrar(
        tick=1,
        kind=EventKind.ACTION_STARTED,
        actor=otro_id,
        place=PlaceId("bosque"),
        action=ActionId("charlar"),
        data={"target": str(tercero_id)},
    )

    # Avanza el día
    sim.state.tick = 24
    pasar_dia(sim)

    # No debe haber avanzado porque 'yo' no lo vio (M14)
    run = sim.state.tramas[yo_id]
    assert run.paso == "esperar", (
        "El paso de espera no debe avanzar si ocurrió fuera de vista (M14)"
    )

    # Ahora ocurre en 'plaza', en presencia de 'yo'
    sim.state.agents[otro_id].at = PlaceId("plaza")
    sim.state.agents[tercero_id].at = PlaceId("plaza")
    sim._registrar(
        tick=25,
        kind=EventKind.ACTION_STARTED,
        actor=otro_id,
        place=PlaceId("plaza"),
        action=ActionId("charlar"),
        data={"target": str(tercero_id)},
    )

    sim.state.tick = 48
    pasar_dia(sim)

    # Ahora sí debe haber avanzado al verlos juntos
    assert sim.state.tramas[yo_id].paso == "siguiente"


def test_b2_3_trama_nunca_cambia_estado_de_referencia_salvo_act() -> None:
    """3. Una trama nunca cambia el estado ni las decisiones de una referencia
    salvo por un act ejecutado por el motor (B.2.3, M11)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")

    yo = sim.state.agents[yo_id]
    ref = sim.state.agents[ref_id]

    yo_need_antes = yo.needs[NeedId("n1")]
    ref_need_antes = ref.needs[NeedId("n1")]

    trama = pack.plots.plots[0]  # type: ignore[union-attr]
    run = PlotRun(plot=PlotId("t1"), empezo=0, refs={"otro": ref_id}, paso=StepId("s1"), desde=0)
    sim.state.tramas[yo_id] = run

    # Elección con efectos sobre necesidad y aprecio
    opcion = Choice(
        label="Efecto",
        appeal={},
        effects=(
            EffectSpec(need=NeedId("n1"), delta=-0.2),
            EffectSpec(regard="otro", delta=0.3),
            EffectSpec(mark=MarkId("fama_local"), delta=1),
        ),
        next=None,
    )

    from agora.engine.plots import _aplicar_opcion
    _aplicar_opcion(sim, yo, run, trama.steps[0], opcion)

    # El protagonista cambió
    assert yo.needs[NeedId("n1")] < yo_need_antes
    assert sim.state.marcas[yo_id][MarkId("fama_local")] == 1
    assert yo.regard_for(ref_id, sim.state.tick, yo.temperament.bond_fade) > 0.0

    # La referencia NO cambió su estado (M11)
    assert ref.needs[NeedId("n1")] == ref_need_antes
    assert sim.state.marcas.get(ref_id, {}).get(MarkId("fama_local"), 0) == 0
    assert ref.regard_for(yo_id, sim.state.tick, ref.temperament.bond_fade) == 0.0


def test_b2_3_inclinaciones_solo_tocan_al_protagonista() -> None:
    """3. Las inclinaciones solo tocan al protagonista, nunca a la referencia (B.2.3, M13)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"][0]["steps"] = [
        {
            "id": "espera",
            "expects": {"beat": "talked_with", "ref": "otro"},
            "within_days": 10,
            "leanings": [{"where_seen": "otro", "multiplier": 1.8}],
            "next": None,
        }
    ]
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")

    yo = sim.state.agents[yo_id]
    ref = sim.state.agents[ref_id]

    sim.state.tramas[yo_id] = PlotRun(
        plot=PlotId("t1"),
        empezo=0,
        refs={"otro": ref_id},
        paso=StepId("espera"),
        desde=0,
    )

    # 'yo' vio a 'ref' en plaza
    yo.sightings[PlaceId("plaza")] = (sim.state.tick, frozenset((ref_id,)))
    ref.sightings[PlaceId("plaza")] = (sim.state.tick, frozenset((yo_id,)))

    from agora.agents.decide import Decision
    opcion_plaza = Decision(
        action=ActionId("descansar"),
        place=PlaceId("plaza"),
        utility=1.0,
        travel_ticks=0,
        target=None,
    )

    # Para el protagonista, la utilidad está inclinada
    inc_yo = inclinacion(sim.state, yo, opcion_plaza)
    assert inc_yo == pytest.approx(1.8)

    # Para la referencia, la inclinación es neutral (1.0) (M13)
    inc_ref = inclinacion(sim.state, ref, opcion_plaza)
    assert inc_ref == pytest.approx(1.0), (
        "La inclinación de la trama del protagonista no debe afectar a la referencia (M13)"
    )


def test_b2_4_jugador_y_npc_misma_probabilidad_disparo() -> None:
    """4. Jugador y NPC con las mismas condiciones: misma probabilidad de disparar (B.2.4, M12)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"][0]["chance"] = 0.60
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    npc_id = AgentId("agente_a")

    sim.set_player(yo_id)

    # Con seed=42 y dia=0, stream("trama", yo_id, "t1", 0).random() es ~0.57548 < 0.60
    # Hacemos que ambos conozcan a alguien para que cumplan papeles
    for sujeto, otro in ((yo_id, AgentId("agente_b")), (npc_id, AgentId("agente_c"))):
        sim._registrar(
            tick=0,
            kind=EventKind.ACTION_STARTED,
            actor=otro,
            place=PlaceId("plaza"),
            action=ActionId("charlar"),
            data={"target": str(sujeto)},
        )

    _sembrar(sim, sim.state.agents[yo_id], dia=0)
    assert yo_id in sim.state.tramas, "El jugador debe disparar la trama con chance 0.60 (M12)"

    _sembrar(sim, sim.state.agents[npc_id], dia=0)
    rnd_npc = sim.state.rng.stream("trama", npc_id, "t1", 0).random()
    assert npc_id in sim.state.tramas or rnd_npc >= 0.60


def test_b2_5_narrador_no_cuenta_plot_ajeno() -> None:
    """5. Ningún briefing del narrador al jugador lleva un PLOT_* ajeno (B.2.5, M10)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"].append(
        {
            "id": "t2",
            "label": "Trama Ajena",
            "category": "test",
            "chance": 1.0,
            "cooldown_days": 10,
            "protagonist": [],
            "refs": [{"name": "otro", "when": [{"alive": True}]}],
            "steps": [
                {"id": "s1", "choices": [{"label": "O", "appeal": {}, "effects": [], "next": None}]}
            ],
        }
    )
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    npc_id = AgentId("agente_a")
    sim.set_player(yo_id)

    # Registramos evento de trama de NPC
    sim._registrar(
        tick=5,
        kind=EventKind.PLOT_BEGAN,
        actor=npc_id,
        place=PlaceId("plaza"),
        data={"plot": "t2"},
    )
    # Y evento de trama propia
    sim._registrar(
        tick=5,
        kind=EventKind.PLOT_BEGAN,
        actor=yo_id,
        place=PlaceId("plaza"),
        data={"plot": "t1"},
    )

    from agora.cognition.narrador import Sighting, Table, select
    items = select(sim.state, sim.log, str(yo_id), Sighting(), Table())

    # El narrador cuenta la trama propia del jugador
    assert any("Trama 1" in it.text for it in items)
    # Pero no debe haber ningún elemento narrado de la trama ajena (M10)
    assert not any("Trama Ajena" in it.text for it in items), (
        "El narrador no debe incluir hechos de tramas ajenas (M10)"
    )


# ==============================================================================
# B.3 — Pasos y efectos
# ==============================================================================


def test_b3_disparo_solo_una_trama_activa_por_protagonista() -> None:
    """Disparo: una persona solo tiene una trama activa a la vez como protagonista (M3)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"].append(
        {
            "id": "t2",
            "label": "Trama 2",
            "category": "test",
            "chance": 1.0,
            "cooldown_days": 10,
            "protagonist": [],
            "refs": [{"name": "otro", "when": [{"alive": True}]}],
            "steps": [
                {"id": "s1", "choices": [{"label": "O", "appeal": {}, "effects": [], "next": None}]}
            ],
        }
    )
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")

    # yo conoce a agente_a para que t2 pueda encontrar referencia
    sim._registrar(
        tick=0,
        kind=EventKind.ACTION_STARTED,
        actor=AgentId("agente_a"),
        place=PlaceId("plaza"),
        action=ActionId("charlar"),
        data={"target": str(yo_id)},
    )

    # Ya tiene t1 activa
    sim.state.tramas[yo_id] = PlotRun(
        plot=PlotId("t1"), empezo=0, refs={"otro": AgentId("agente_a")}, paso=StepId("s1"), desde=0
    )

    # Avanza el día
    sim.state.tick = 24
    pasar_dia(sim)

    # Sigue teniendo t1, no se añade t2 ni se sobreescribe (M3)
    assert sim.state.tramas[yo_id].plot == "t1"
    eventos_began = [e for e in sim.log if e.kind is EventKind.PLOT_BEGAN and e.actor == yo_id]
    assert len(eventos_began) == 0


def test_b3_evaluar_tramas_solo_una_vez_al_dia_no_cada_tick() -> None:
    """Pasar día: las tramas se evalúan una vez al día, no en cada tick (M2)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    sim.state.fama[yo_id] = 0.50

    # Avanzamos 5 ticks (menos de 24 ticks del día)
    for _ in range(5):
        sim.tick()

    # La fama no debe haber decaído en cada tick (M2)
    assert sim.state.fama[yo_id] == 0.50, "La fama y tramas no deben evaluarse cada tick (M2)"

    # Al completar el día (24 ticks), decae exactamente una vez (0.01)
    for _ in range(19):
        sim.tick()
    assert sim.state.fama[yo_id] == pytest.approx(0.49, abs=1e-4)


def test_b3_1_npc_opcion_sale_de_appeal_y_caracter_determinista() -> None:
    """1. NPC: la opción sale de appeal y carácter; misma semilla, misma opción (B.3.1, M4)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    yo = sim.state.agents[yo_id]
    yo.traits[TraitId("valor")] = 1.0
    yo.traits[TraitId("prudencia")] = 0.0

    trama = pack.plots.plots[0]  # type: ignore[union-attr]
    paso = Step(
        id=StepId("p1"),
        choices=(
            Choice(label="Valiente", appeal={TraitId("valor"): 10.0}, effects=(), next=None),
            Choice(label="Prudente", appeal={TraitId("prudencia"): 10.0}, effects=(), next=None),
        ),
    )

    # Con appeal y rasgos, elige "Valiente"
    elegida = _elige_npc(sim, yo, trama, paso, list(paso.choices))
    assert elegida.label == "Valiente", "El NPC debe elegir guiado por appeal y rasgos (M4)"

    # Determinismo: misma llamada da exactamente la misma opción
    elegida2 = _elige_npc(sim, yo, trama, paso, list(paso.choices))
    assert elegida2.label == elegida.label


def test_b3_2_jugador_choose_plot_grabado_y_reproducido() -> None:
    """2. Jugador: choose_plot, grabado y reproducido por Script (B.3.2, M5)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    yo = sim.state.agents[yo_id]
    sim.set_player(yo_id)

    class MockSource:
        def choose(self, *args: Any) -> Any:
            return None
        def interrupt(self, *args: Any) -> bool:
            return False
        def choose_plot(self, world: WorldState, agent: Any, vista: PlotView) -> int | None:
            return 1

    out = io.StringIO()
    rec = Recorder(MockSource(), out, sim=sim)

    vista = PlotView(plot="Trama 1", options=("Opcion 0", "Opcion 1"), defecto=0)
    elegido = rec.choose_plot(sim.state, yo, vista)
    assert elegido == 1

    # Comprobar que Recorder grabó la línea de trama (M5)
    lineas = out.getvalue().splitlines()
    assert any('"trama": 1' in linea for linea in lineas), (
        "Recorder debe grabar choose_plot con 'trama' (M5)"
    )

    # Script reproduce la elección grabada
    script = Script(lineas, sim=sim)
    reproducido = script.choose_plot(sim.state, yo, vista)
    assert reproducido == 1


def test_b3_3_act_presente_ejecuta_inmediato_ausente_intencion_y_timeout() -> None:
    """3. act: presente ejecuta ya; ausente intención y si caduca on_timeout (B.3.3)."""
    raw = pack_tramas_base()
    raw["plots"]["plots"][0]["steps"] = [
        {
            "id": "decidir",
            "choices": [
                {
                    "label": "Charlar ya",
                    "appeal": {},
                    "act": {
                        "action": "charlar",
                        "to": "otro",
                        "within_days": 2,
                        "on_timeout": "caducado",
                    },
                    "next": "exito",
                }
            ],
        },
        {
            "id": "caducado",
            "choices": [{"label": "Fin caducado", "appeal": {}, "effects": [], "next": None}],
        },
        {
            "id": "exito",
            "choices": [{"label": "Fin exito", "appeal": {}, "effects": [], "next": None}],
        },
    ]
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")

    # Caso 1: Ref presente en plaza -> se ejecuta inmediatamente
    sim.state.agents[yo_id].at = PlaceId("plaza")
    sim.state.agents[ref_id].at = PlaceId("plaza")

    run = PlotRun(
        plot=PlotId("t1"), empezo=0, refs={"otro": ref_id}, paso=StepId("decidir"), desde=0
    )
    sim.state.tramas[yo_id] = run

    from agora.engine.plots import al_quedar_ocioso
    ejecuto = al_quedar_ocioso(sim, sim.state.agents[yo_id])
    assert ejecuto is True
    assert run.intencion is None
    assert run.paso == "exito"

    # Caso 2: Ref ausente (en bosque) -> queda como intención y caduca
    sim.state.agents[yo_id].at = PlaceId("plaza")
    sim.state.agents[ref_id].at = PlaceId("bosque")

    run2 = PlotRun(
        plot=PlotId("t1"), empezo=0, refs={"otro": ref_id}, paso=StepId("decidir"), desde=0
    )
    sim.state.tramas[yo_id] = run2

    ejecuto2 = al_quedar_ocioso(sim, sim.state.agents[yo_id])
    assert ejecuto2 is False
    assert run2.intencion is not None
    assert run2.intencion.action == ActionId("charlar")

    # Pasan los 2 días (48 ticks) sin que coincidan
    sim.state.tick = 49 * 24
    pasar_dia(sim)

    # Caducó hacia 'caducado'
    trama_actual = sim.state.tramas[yo_id]
    assert trama_actual.intencion is None
    assert trama_actual.paso == "caducado"


def test_b3_4_forgive_baja_agravio_y_debt_crea_deuda() -> None:
    """4. forgive baja agravio hacia esa ref; debt crea deuda que por_deuda ve (B.3.4, M15)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")

    yo = sim.state.agents[yo_id]

    # Grabamos recuerdo negativo sobre ref_id
    sim._recordar_de_trama(yo_id, ref_id, valencia=-1.0, importancia=1.0, por_quien=ref_id)
    agravio_antes = sim.state.memoria.agravio(
        yo_id, sim.state.tick, pack.tuning.grief_scale, pack.tuning.agravio_de_oidas
    ).get(ref_id, 0.0)
    assert agravio_antes > 0.5

    # Efecto forgive con factor 0.5
    run = PlotRun(plot=PlotId("t1"), empezo=0, refs={"otro": ref_id}, paso=StepId("s1"), desde=0)
    e_forgive = EffectSpec(forgive="otro", factor=0.5)

    from agora.engine.plots import _efecto
    _efecto(sim, yo, run, e_forgive)

    agravio_despues = sim.state.memoria.agravio(
        yo_id, sim.state.tick, pack.tuning.grief_scale, pack.tuning.agravio_de_oidas
    ).get(ref_id, 0.0)
    assert agravio_despues < agravio_antes * 0.7, (
        "forgive debe atenuar el agravio de la memoria (M15)"
    )

    # Efecto debt
    e_debt = EffectSpec(debt="otro", action=ActionId("prestar"), direction="presto")
    _efecto(sim, yo, run, e_debt)

    deudas = [p for p in sim.state.propiedades.values() if p.tipo is PropertyKind.DEUDA]
    assert len(deudas) >= 1
    assert any(d.dueño == yo_id and d.objeto == str(ref_id) for d in deudas)

    # Verificamos que la condición de deuda lo detecta
    c_deuda = PlotCondition(debt="le_deben")
    assert _cumple_protagonista(sim, yo, c_deuda, run.refs) is True


def test_b3_5_fama_decae_y_marcas_acotadas() -> None:
    """5. Fama decae cada día y marcas están acotadas (B.3.5, M6)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")

    sim.state.fama[yo_id] = 0.50
    sim.state.tick = 24
    pasar_dia(sim)

    # Fama decae 0.01 por día (M6)
    assert sim.state.fama[yo_id] == pytest.approx(0.49, abs=1e-4)

    # Marcas acotadas (fama_local tiene max: 5)
    sim._marcar(yo_id, MarkId("fama_local"), 4)
    assert sim.state.marcas[yo_id][MarkId("fama_local")] == 4
    sim._marcar(yo_id, MarkId("fama_local"), 3)  # intenta subir a 7
    assert sim.state.marcas[yo_id][MarkId("fama_local")] == 5, (
        "Las marcas deben respetar el max acotado"
    )


def test_b3_5_tirada_por_puerto_o_respaldo_y_engano_15b() -> None:
    """5. Tirada por puerto o por respaldo; engaño 15b funciona igual (B.3.5)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")
    yo = sim.state.agents[yo_id]

    run = PlotRun(plot=PlotId("t1"), empezo=0, refs={"otro": ref_id}, paso=StepId("s1"), desde=0)
    uso = OntologyTestUse(id="combate", vs="otro")

    # Sin resolver: regla de respaldo por rasgos
    yo.traits[TraitId("fuerza")] = 1.0
    sim.state.agents[ref_id].traits[TraitId("fuerza")] = 0.0
    exito_respaldo = _probar(sim, yo, run, uso)
    assert exito_respaldo is True

    # Con resolver mock
    class MockSocialResolver:
        def contest(
            self, world: Any, actor: AgentId, rival: AgentId | None, prueba: str, key: str
        ) -> Contest | None:
            res = Resolution(
                outcome=Outcome.FAILURE,
                dice=(1,), opposing_dice=(6,), successes=0, opposing_successes=1, sixes=0,
                overflow=0, effect=0,
            )
            return Contest(res, "Fuerza", "Fuerza")

        def deceive(
            self, world: Any, liar: AgentId, listener: AgentId, key: str
        ) -> Contest | None:
            return None

    sim.social_resolver = MockSocialResolver()
    exito_puerto = _probar(sim, yo, run, uso)
    assert exito_puerto is False, "Debe priorizar el SocialResolver si está disponible"


def test_b3_hoja_no_muestra_marcas_ocultas() -> None:
    """Hoja: muestra marcas visibles y fama, pero nunca marcas ocultas (M7)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    yo = sim.state.agents[yo_id]

    sim.state.fama[yo_id] = 0.75
    sim._marcar(yo_id, MarkId("fama_local"), 3)  # visible
    sim._marcar(yo_id, MarkId("secreto"), 2)     # hidden = True

    view = sheet_view(sim.state, yo)
    lineas = view.lineas

    assert any("Fama Local: 3" in linea for linea in lineas)
    assert any("Fama: 0.75" in linea for linea in lineas)
    assert not any("secreto" in linea.lower() for linea in lineas), (
        "Las marcas ocultas no deben aparecer en la hoja (M7)"
    )


def test_b3_6_guardar_y_cargar_con_trama_e_intencion(tmp_path: Path) -> None:
    """6. Guardar y cargar con trama a medias e intención pendiente (B.3.6, M8)."""
    pack = make_pack()
    sim = Simulation(pack, seed=42)
    yo_id = AgentId("yo")
    ref_id = AgentId("agente_a")

    intencion = Intencion(
        action=ActionId("charlar"),
        ref=ref_id,
        vence=100,
        siguiente=StepId("fin"),
        si_caduca=StepId("caducada"),
    )
    run = PlotRun(
        plot=PlotId("t1"),
        empezo=10,
        refs={"otro": ref_id},
        paso=StepId("s1"),
        desde=15,
        intencion=intencion,
    )
    sim.state.tramas[yo_id] = run
    sim.state.tramas_vividas.setdefault(yo_id, {})[PlotId("t1")] = 10
    sim.state.marcas[yo_id] = {MarkId("fama_local"): 2}
    sim.state.fama[yo_id] = 0.40

    save_file = tmp_path / "partida.json"
    save(sim.state, sim._together, save_file)

    # Reanudamos en un estado nuevo cargado
    nuevo_estado, _together, _ = load(save_file, pack)

    assert yo_id in nuevo_estado.tramas, "La trama activa debe persistir al guardar y cargar (M8)"
    run_cargado = nuevo_estado.tramas[yo_id]
    assert run_cargado.plot == "t1"
    assert run_cargado.paso == "s1"
    assert run_cargado.refs == {"otro": ref_id}
    assert run_cargado.intencion is not None
    assert run_cargado.intencion.action == ActionId("charlar")
    assert run_cargado.intencion.ref == ref_id
    assert run_cargado.intencion.vence == 100
    assert nuevo_estado.marcas[yo_id][MarkId("fama_local")] == 2
    assert nuevo_estado.fama[yo_id] == pytest.approx(0.40)
