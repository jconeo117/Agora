"""Pruebas de la unidad 16b: consumibles, from_items, regrow e índices (§B.1)."""

from __future__ import annotations

import io
import json
import random
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.agents.decide import options
from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    AgentSpec,
    NeedId,
    PlaceId,
    PropertyId,
    PropertyKind,
)
from agora.engine.pack import ContentPack, PackError, load_pack
from agora.engine.state import PerformingAction, Propiedad, WorldState
from agora.engine.world import Simulation

ISLA_PACK = Path("packs/isla/pack.yaml")


def test_b1_1_eje_from_items_sube_al_coger_baja_al_gastar_cae_al_morir_y_tope_1() -> None:
    """B.1.1: Un eje `from_items`: coger una ración lo sube 0.1 y gastarla lo baja;
    al morir, sus raciones caen al suelo y a quien las coge le sube; tope 1.

    Sensible a mutación M1 (_recalcular_ejes no se llama al mover).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    donde = agente.at
    # Empieza con 2 raciones del starting_items: suministros = 0.2
    assert agente.needs[NeedId("suministros")] == pytest.approx(0.2)

    # 1. Coger una ración del suelo lo sube 0.1
    racion = Propiedad(
        id=PropertyId("obj:test:racion:1"),
        tipo=PropertyKind.OBJETO,
        objeto="racion",
        renta={},
        tributo={},
        lugar=donde,
    )
    sim.state.alta_objeto(racion)
    sim._mover_objeto(racion, actor=agente_id, dueño=agente_id, lugar=None, donde=donde)
    assert agente.needs[NeedId("suministros")] == pytest.approx(0.3)

    # 2. Gastarla lo baja
    sim._gastar(agente, racion)
    assert agente.needs[NeedId("suministros")] == pytest.approx(0.2)

    # 3. Al morir, sus raciones caen al suelo y a quien las coge le sube
    otro_id = AgentId("dandri_d1")
    otro = sim.state.agents[otro_id]
    otro.at = donde
    otro_suministros_inicial = otro.needs[NeedId("suministros")]

    sim.morir(agente_id)
    # Las raciones de coka_d1 ahora están en el suelo de 'donde'
    suelo = sim.state.objetos_en(donde)
    raciones_suelo = [p for p in suelo if p.objeto == "racion"]
    assert len(raciones_suelo) >= 2
    for r in raciones_suelo:
        assert r.dueño is None
        assert r.lugar == donde

    # 'otro' coge una ración del suelo
    rac_caida = raciones_suelo[0]
    sim._mover_objeto(rac_caida, actor=otro_id, dueño=otro_id, lugar=None, donde=donde)
    assert otro.needs[NeedId("suministros")] == pytest.approx(otro_suministros_inicial + 0.1)

    # 4. Tope 1: si se le dan muchas raciones, no supera 1.0
    for i in range(15):
        r_extra = Propiedad(
            id=PropertyId(f"obj:test:tope:{i}"),
            tipo=PropertyKind.OBJETO,
            objeto="racion",
            renta={},
            tributo={},
            lugar=donde,
        )
        sim.state.alta_objeto(r_extra)
        sim._mover_objeto(r_extra, actor=otro_id, dueño=otro_id, lugar=None, donde=donde)
    assert otro.needs[NeedId("suministros")] == pytest.approx(1.0)


def test_b1_2_validacion_eje_from_items_no_decae_ni_en_effects_costs_gives(
    tmp_path: Path,
) -> None:
    """B.1.2: Un pack con un eje `from_items` en `effects`, `costs` o `target.gives`,
    o con `decay_per_tick > 0`, no carga.

    Sensible a mutación M2 (permitir effects en un eje from_items).
    """
    raw = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))

    def cargar(data: dict[str, Any]) -> None:
        p = tmp_path / "pack_test.yaml"
        p.write_text(yaml.safe_dump(data), encoding="utf-8")
        load_pack(p)

    # 1. decay_per_tick > 0 con from_items
    raw1 = yaml.safe_load(yaml.safe_dump(raw))
    for n in raw1["needs"]:
        if n["id"] == "suministros":
            n["decay_per_tick"] = 0.01
    with pytest.raises(PackError, match="con from_items no puede decaer"):
        cargar(raw1)

    # 2. eje from_items en effects de una acción (Sensible a M2)
    raw2 = yaml.safe_load(yaml.safe_dump(raw))
    raw2["actions"][0].setdefault("effects", {})["suministros"] = 0.1
    with pytest.raises(PackError, match=r"sale de los objetos y no puede estar en effects"):
        cargar(raw2)

    # 3. eje from_items en costs de una acción
    raw3 = yaml.safe_load(yaml.safe_dump(raw))
    raw3["actions"][0].setdefault("costs", {})["suministros"] = 0.1
    with pytest.raises(
        PackError, match=r"sale de los objetos y no puede estar en effects, costs ni target\.gives"
    ):
        cargar(raw3)

    # 4. eje from_items en target.gives de una acción
    raw4 = yaml.safe_load(yaml.safe_dump(raw))
    act_target = next(a for a in raw4["actions"] if a.get("target") is not None)
    act_target["target"].setdefault("gives", {})["suministros"] = 0.1
    with pytest.raises(
        PackError, match=r"sale de los objetos y no puede estar en effects, costs ni target\.gives"
    ):
        cargar(raw4)


def test_b1_3_consumes_gasta_id_menor_o_aborta_sin_objeto() -> None:
    """B.1.3: `consumes`: se gasta el de id menor; sin el objeto al completar,
    sin efecto y `ACTION_ABORTED` con `reason: "sin_objeto"`.

    Sensible a mutación M3 (consumes: gastar el de id mayor).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    # Limpiamos raciones previas
    for p in list(sim.state.objetos_de(agente_id)):
        sim.state.baja_objeto(p)
    sim.state.recalcular_ejes(agente)

    # Damos dos raciones con ids explícitos: 'obj:racion:01' y 'obj:racion:02'
    r1 = Propiedad(
        id=PropertyId("obj:racion:01"),
        tipo=PropertyKind.OBJETO,
        objeto="racion",
        renta={},
        tributo={},
        dueño=agente_id,
    )
    r2 = Propiedad(
        id=PropertyId("obj:racion:02"),
        tipo=PropertyKind.OBJETO,
        objeto="racion",
        renta={},
        tributo={},
        dueño=agente_id,
    )
    sim.state.alta_objeto(r1)
    sim.state.alta_objeto(r2)
    sim.state.recalcular_ejes(agente)

    # Ponemos al agente a ejecutar 'comer' (consumes: racion, effects: sustento +0.4)
    # sustento decae 0.006 por tick
    agente.needs[NeedId("sustento")] = 0.5
    agente.busy = PerformingAction(action=ActionId("comer"), ticks_remaining=0)

    sim.tick()

    # M3: debe haberse gastado r1 (id menor: 'obj:racion:01'), NO r2 ('obj:racion:02')
    assert sim.state.propiedades.get(r1.id) is None
    assert sim.state.propiedades.get(r2.id) is not None
    # El efecto de comer se aplicó (+0.4 de sustento, menos decay de 0.006 del tick)
    assert agente.needs[NeedId("sustento")] == pytest.approx(0.5 + 0.4 - 0.006)

    # Caso 2: sin el objeto al completar -> sin efecto y ACTION_ABORTED con reason: "sin_objeto"
    sim.state.baja_objeto(r2)
    sim.state.recalcular_ejes(agente)
    assert len(sim.state.objetos_de(agente_id)) == 0

    agente.needs[NeedId("sustento")] = 0.3
    agente.busy = PerformingAction(action=ActionId("comer"), ticks_remaining=0)

    sim.tick()

    # Sustento no debió aumentar (solo decay del tick)
    assert agente.needs[NeedId("sustento")] == pytest.approx(0.3 - 0.006)
    # Se emitió ACTION_ABORTED con reason "sin_objeto"
    abortos = [
        e for e in sim.log._events
        if e.kind is EventKind.ACTION_ABORTED and e.actor == agente_id
    ]
    assert abortos
    assert abortos[-1].data == {"reason": "sin_objeto"}


def test_b1_4_requires_item_encima_puerta_dura() -> None:
    """B.1.4: `requires_item` `encima`: sin el objeto, la acción no está en `options()`.

    Sensible a mutación M4 (requires_item encima ignorado).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]

    # Vaciamos todos los objetos que lleva encima
    for p in list(sim.state.objetos_de(agente_id)):
        sim.state.baja_objeto(p)
    sim.state.recalcular_ejes(agente)

    assert len(sim.state.objetos_de(agente_id)) == 0

    # 'comer' tiene requires_item {where: encima, tags: [comida]}
    # Sin objeto encima, 'comer' NO debe aparecer en options()
    opts_sin = options(sim.state, agente)
    assert not any(opt.action == ActionId("comer") for opt in opts_sin)

    # Si le damos una ración encima, 'comer' SÍ debe aparecer
    racion = Propiedad(
        id=PropertyId("obj:comida:coka"),
        tipo=PropertyKind.OBJETO,
        objeto="racion",
        renta={},
        tributo={},
        dueño=agente_id,
    )
    sim.state.alta_objeto(racion)
    sim.state.recalcular_ejes(agente)

    opts_con = options(sim.state, agente)
    assert any(opt.action == ActionId("comer") for opt in opts_con)


def test_b1_5_regrow_cada_every_hasta_max_ids_deterministas() -> None:
    """B.1.5: `regrow`: cada `every` ticks aparece uno hasta `max`; ids deterministas.

    Sensible a mutación M5 (regrow sin tope max).
    """
    raw = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    # Creamos un lugar con regrow controlado: every=3, max=2
    lugar_test = next(p for p in raw["places"] if p["id"] == "playa_1_1")
    lugar_test["regrow"] = {"racion": {"max": 2, "every": 3}}
    lugar_test["items"] = {}

    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=1312)
    pid = PlaceId("playa_1_1")

    # Aseguramos suelo vacío al empezar
    for p in list(sim.state.objetos_en(pid)):
        sim.state.baja_objeto(p)

    # Ticks 1 y 2: no regrow (tick % 3 != 0)
    sim.tick()  # tick 1
    assert len(sim.state.objetos_en(pid)) == 0
    sim.tick()  # tick 2
    assert len(sim.state.objetos_en(pid)) == 0

    # Tick 3: aparece 1 ración con id determinista 'obj:playa_1_1:racion:r3'
    sim.tick()  # tick 3
    suelo_t3 = sim.state.objetos_en(pid)
    assert len(suelo_t3) == 1
    assert suelo_t3[0].id == PropertyId("obj:playa_1_1:racion:r3")
    assert suelo_t3[0].objeto == "racion"

    # Ticks 4 y 5: no regrow
    sim.tick()
    sim.tick()
    assert len(sim.state.objetos_en(pid)) == 1

    # Tick 6: aparece la segunda ración 'obj:playa_1_1:racion:r6'
    sim.tick()  # tick 6
    suelo_t6 = sim.state.objetos_en(pid)
    assert len(suelo_t6) == 2
    ids_t6 = {p.id for p in suelo_t6}
    assert ids_t6 == {
        PropertyId("obj:playa_1_1:racion:r3"),
        PropertyId("obj:playa_1_1:racion:r6"),
    }

    # Ticks 7, 8, 9: en tick 9 ya hay 2 (que es max), NO debe aparecer un tercero
    sim.tick()  # tick 7
    sim.tick()  # tick 8
    sim.tick()  # tick 9 (Sensible a M5: si M5 no comprueba max, aquí crecería a 3)
    suelo_t9 = sim.state.objetos_en(pid)
    assert len(suelo_t9) == 2

    sim.tick()  # tick 10
    sim.tick()  # tick 11
    sim.tick()  # tick 12
    assert len(sim.state.objetos_en(pid)) == 2

    # Si se retira una ración, en el siguiente tick múltiplo de 3 vuelve a crecer
    sim.state.baja_objeto(suelo_t9[0])
    assert len(sim.state.objetos_en(pid)) == 1
    sim.tick()  # tick 13
    sim.tick()  # tick 14
    sim.tick()  # tick 15
    suelo_t15 = sim.state.objetos_en(pid)
    assert len(suelo_t15) == 2
    assert any(p.id == PropertyId("obj:playa_1_1:racion:r15") for p in suelo_t15)


def test_b1_6_starting_items_todos_empiezan_y_un_recien_llegado_tambien() -> None:
    """B.1.6: `starting_items`: todos empiezan con lo suyo, y un recién llegado también."""
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    # Todos los agentes del pack tienen starting_items ({racion: 2})
    for agente in sim.state.agents.values():
        raciones = [p for p in sim.state.objetos_de(agente.spec_id) if p.objeto == "racion"]
        assert len(raciones) == 2
        assert agente.needs[NeedId("suministros")] == pytest.approx(0.2)
        assert [p.id for p in raciones] == [
            PropertyId(f"ajuar:{agente.spec_id}:racion:0"),
            PropertyId(f"ajuar:{agente.spec_id}:racion:1"),
        ]

    # Recién llegado
    nuevo_spec = AgentSpec(
        id=AgentId("forastero_test"),
        label="El Forastero",
        home=PlaceId("playa_1_1"),
        start_at=PlaceId("playa_1_1"),
        initial_needs={},
    )
    nuevo_agente = sim.arrive(nuevo_spec)
    raciones_nuevo = [p for p in sim.state.objetos_de(nuevo_agente.spec_id) if p.objeto == "racion"]
    assert len(raciones_nuevo) == 2
    assert nuevo_agente.needs[NeedId("suministros")] == pytest.approx(0.2)
    assert [p.id for p in raciones_nuevo] == [
        PropertyId("ajuar:forastero_test:racion:0"),
        PropertyId("ajuar:forastero_test:racion:1"),
    ]


def test_b1_7_indices_equivalentes_a_recorrido_lento_tras_movimientos() -> None:
    """B.1.7: Índices: `objetos_de`/`objetos_en` dan lo mismo que el recorrido completo
    (comparación contra una versión lenta escrita en el test) tras cien
    movimientos aleatorios con semilla fija.

    Sensible a mutación M6 (índice: no actualizar _por_lugar al mover).
    """
    def objetos_de_lento(world: WorldState, agente: AgentId) -> list[Propiedad]:
        return sorted(
            (p for p in world.propiedades.values()
             if world.es_objeto(p) and p.dueño == agente),
            key=lambda p: p.id,
        )

    def objetos_en_lento(world: WorldState, lugar: PlaceId) -> list[Propiedad]:
        return sorted(
            (p for p in world.propiedades.values()
             if world.es_objeto(p) and p.lugar == lugar),
            key=lambda p: p.id,
        )

    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)
    rng = random.Random(42)

    agentes = list(sim.state.agents.keys())
    lugares = [p.id for p in pack.places]

    for i in range(100):
        objs = [p for p in sim.state.propiedades.values() if sim.state.es_objeto(p)]
        obj = rng.choice(objs)
        accion = rng.choice(["al_suelo", "a_agente", "nuevo", "gastar"])

        if accion == "al_suelo":
            lugar_dest = rng.choice(lugares)
            sim._mover_objeto(
                obj,
                actor=rng.choice(agentes),
                dueño=None,
                lugar=lugar_dest,
                donde=lugar_dest,
            )
        elif accion == "a_agente":
            agente_dest = rng.choice(agentes)
            sim._mover_objeto(
                obj,
                actor=agente_dest,
                dueño=agente_dest,
                lugar=None,
                donde=sim.state.agents[agente_dest].at,
            )
        elif accion == "nuevo":
            nuevo_id = PropertyId(f"obj:test:rnd:{i}")
            lugar_nuevo = rng.choice(lugares)
            nuevo_obj = Propiedad(
                id=nuevo_id,
                tipo=PropertyKind.OBJETO,
                objeto="racion",
                renta={},
                tributo={},
                lugar=lugar_nuevo,
            )
            sim.state.alta_objeto(nuevo_obj)
        elif accion == "gastar":
            if obj.dueño is not None:
                sim._gastar(sim.state.agents[obj.dueño], obj)

    for ag in agentes:
        assert sim.state.objetos_de(ag) == objetos_de_lento(sim.state, ag)

    for lg in lugares:
        assert sim.state.objetos_en(lg) == objetos_en_lento(sim.state, lg)


def test_b1_8_persistencia_guardar_y_reanudar_con_raciones_y_reposicion(tmp_path: Path) -> None:
    """B.1.8: Guardar y reanudar con raciones y reposición da el mismo log que no parar.

    Sensible a mutación M7 (persistence: no reconstruir los índices).
    """
    pack = load_pack(ISLA_PACK)

    # 1. Corrida continua de 20 ticks (cubre consumo, regrow en tick 16, etc.)
    sink_continuo = io.StringIO()
    sim_continuo = Simulation(pack, seed=1312, log_sink=sink_continuo)
    sim_continuo.run(20)

    # 2. Corrida partida: 10 ticks, guardar, reanudar y correr 10 ticks más
    sink_partido = io.StringIO()
    sim_partido = Simulation(pack, seed=1312, log_sink=sink_partido)
    sim_partido.run(10)

    save_file = tmp_path / "save_16b.json"
    sim_partido.save(save_file)

    sim_reanudado = Simulation.resume(save_file, pack, log_sink=sink_partido)
    # Comprobar que los índices están vivos tras resume (Sensible a M7)
    assert len(sim_reanudado.state._por_dueño) > 0
    assert len(sim_reanudado.state._por_lugar) > 0

    sim_reanudado.run(10)

    assert sink_continuo.getvalue() == sink_partido.getvalue()

    # 3. Guardado anterior sin sección 'objetos' (16a): reindexar() reconstruye los índices
    # desde 'propiedades' cargadas (Sensible a M7)
    datos_legacy = json.loads(save_file.read_text(encoding="utf-8"))
    datos_legacy.pop("objetos", None)
    dandri = AgentId("dandri_d1")
    rac_trasladada = PropertyId("ajuar:coka_d1:racion:0")
    datos_legacy["propiedades"].append({
        "id": str(rac_trasladada),
        "tipo": "objeto",
        "objeto": "racion",
        "dueño": str(dandri),
        "lugar": None,
        "equipado": False,
    })
    save_legacy = tmp_path / "save_legacy.json"
    save_legacy.write_text(json.dumps(datos_legacy), encoding="utf-8")

    sim_legacy = Simulation.resume(save_legacy, pack)
    dandri_objs = [p.id for p in sim_legacy.state.objetos_de(dandri)]
    assert rac_trasladada in dandri_objs
