"""Pruebas de la unidad 16a: armas, armaduras y herramientas (§B.1 y §B.2)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agora.agents.decide import options
from agora.cognition.narrador import Sighting, Table, briefing, scene_of, world_moment
from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    ItemQuery,
    ItemSlot,
    NeedId,
    PlaceId,
    PropertyId,
    PropertyKind,
    RelationId,
    SocialAct,
    Tone,
)
from agora.engine.pack import ContentPack, PackError, load_pack
from agora.engine.social import Conversation
from agora.engine.state import Bond, Propiedad
from agora.engine.world import Simulation
from agora.rules.binding import BindingError, load_binding
from agora.rules.derive import derive
from agora.rules.system import load_ruleset
from tests.test_reanudar import foto

ISLA_PACK = Path("packs/isla/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
ISLA_BINDING = Path("packs/isla/reglas/base.yaml")


# ==============================================================================
# B.1 — Objetos y aptitud
# ==============================================================================


def test_b1_1_arma_multiplica_aptitud_y_armadura_reduce_costes() -> None:
    """B.1.1: Un arma equipada multiplica la aptitud y una armadura reduce lo que
    cuesta un golpe; quitárselas lo devuelve; sin objetos, gains is aptitud_base
    y costs como hoy.

    Sensible a mutaciones M1 y M1b.
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    agente.refresh_state(sim.state.pack)

    # Sin objetos: gains es exactamente aptitud_base (identidad)
    assert agente.gains is agente.aptitud_base
    base_combate = agente.aptitud_base.get(NeedId("combate"), 1.0)
    base_salud_cost = agente.costs.get(NeedId("salud"), 1.0)

    # Creamos un arma (lanza_corta: combate x 1.5) y armadura (cota: salud x 0.7)
    arma = Propiedad(
        id=PropertyId("prop:arma:test"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        dueño=agente_id,
    )
    armadura = Propiedad(
        id=PropertyId("prop:armadura:test"),
        tipo=PropertyKind.OBJETO,
        objeto="cota",
        renta={},
        tributo={},
        dueño=agente_id,
    )
    sim.state.alta_objeto(arma)
    sim.state.alta_objeto(armadura)

    # Equipamos arma y armadura
    sim.equipar(agente_id, arma.id)
    sim.equipar(agente_id, armadura.id)

    # B.1.1 & M1: El arma equipada multiplica la aptitud en combate
    assert agente.gains[NeedId("combate")] == pytest.approx(base_combate * 1.5)

    # B.1.1 & M1b: La armadura reduce el coste en salud
    assert agente.costs[NeedId("salud")] == pytest.approx(base_salud_cost * 0.7)

    # Quitárselas lo devuelve al estado base
    arma.equipado = False
    armadura.equipado = False
    sim.state.recalcular_equipo(agente)

    assert agente.gains is agente.aptitud_base
    assert agente.gains[NeedId("combate")] == pytest.approx(base_combate)
    assert agente.costs[NeedId("salud")] == pytest.approx(base_salud_cost)


def test_b1_2_takes_item_coge_el_mejor_y_equipa_si_procede() -> None:
    """B.1.2: `takes_item` coge el mejor (producto de `gains`, desempate por id)
    y equipa si el hueco está vacío o es peor.

    Sensible a mutación M2 («mejor»: el primero por id en vez del mayor producto).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    donde = agente.at

    # Colocamos dos armas en el suelo de donde está el agente:
    # prop_peor: cuchillo (gains combate 1.3), con id lexicográficamente MENOR
    # prop_mejor: hacha (gains combate 1.8), con id lexicográficamente MAYOR
    prop_peor = Propiedad(
        id=PropertyId("obj:suelo:cuchillo:001"),
        tipo=PropertyKind.OBJETO,
        objeto="cuchillo",
        renta={},
        tributo={},
        lugar=donde,
    )
    prop_mejor = Propiedad(
        id=PropertyId("obj:suelo:hacha:999"),
        tipo=PropertyKind.OBJETO,
        objeto="hacha",
        renta={},
        tributo={},
        lugar=donde,
    )
    sim.state.propiedades[prop_peor.id] = prop_peor
    sim.state.propiedades[prop_mejor.id] = prop_mejor

    # Consulta genérica de arma: takes_item debe elegir prop_mejor a pesar de tener mayor id
    elegido = sim._mejor(ItemQuery(slot=ItemSlot.ARMA), [prop_peor, prop_mejor])
    assert elegido is not None
    # Sensible a M2: si M2 usa el primero por id, elegiría prop_peor
    assert elegido.id == prop_mejor.id

    # Prueba de equipamiento automático al coger con hueco vacío:
    sim._mover_objeto(prop_mejor, actor=agente_id, dueño=agente_id, lugar=None, donde=donde)
    sim._equipar_si_procede(agente, prop_mejor)
    assert prop_mejor.dueño == agente_id
    assert prop_mejor.equipado is True

    # Coger un arma peor no desbanca a la mejor equipada:
    sim._mover_objeto(prop_peor, actor=agente_id, dueño=agente_id, lugar=None, donde=donde)
    sim._equipar_si_procede(agente, prop_peor)
    assert prop_peor.dueño == agente_id
    assert prop_peor.equipado is False
    assert prop_mejor.equipado is True

    # Desempate por id: dos armas con idéntico valor
    lanza_a = Propiedad(
        id=PropertyId("obj:suelo:lanza:001"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        lugar=donde,
    )
    lanza_b = Propiedad(
        id=PropertyId("obj:suelo:lanza:002"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        lugar=donde,
    )
    sim.state.propiedades[lanza_a.id] = lanza_a
    sim.state.propiedades[lanza_b.id] = lanza_b
    elegido_empate = sim._mejor(ItemQuery(slot=ItemSlot.ARMA), [lanza_b, lanza_a])
    assert elegido_empate is not None
    assert elegido_empate.id == lanza_a.id


def test_b1_3_requires_item_puerta_dura() -> None:
    """B.1.3: `requires_item`: sin objeto que cumpla, la acción no está en `options()`.

    Sensible a mutación M3 (`is_available`: ignorar `requires_item`).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    lugar_vacio = PlaceId("playa_1_1")
    agente.at = lugar_vacio
    assert len(sim.state.objetos_en(lugar_vacio)) == 0

    # Sin objeto en el suelo de lugar_vacio, 'registrar' en lugar_vacio NO debe estar en options()
    # Sensible a M3: si M3 ignora requires_item, registrar en lugar_vacio estará presente
    assert not any(
        opt.action == ActionId("registrar") and opt.place == lugar_vacio
        for opt in options(sim.state, agente)
    )

    # Ponemos un objeto en el suelo del lugar
    objeto_suelo = Propiedad(
        id=PropertyId("obj:suelo:playa:1"),
        tipo=PropertyKind.OBJETO,
        objeto="cuchillo",
        renta={},
        tributo={},
        lugar=lugar_vacio,
    )
    sim.state.alta_objeto(objeto_suelo)

    # Ahora 'registrar' SÍ debe estar disponible en ese lugar
    assert any(
        opt.action == ActionId("registrar") and opt.place == lugar_vacio
        for opt in options(sim.state, agente)
    )


def test_b1_4_al_morir_objetos_quedan_en_el_suelo_sin_equipar() -> None:
    """B.1.4: Al morir, lo que llevaba queda en el suelo del sitio, sin equipar;
    lo demás se hereda como antes.

    Sensible a mutación M4 (muerte: heredar los objetos en vez de dejarlos en el suelo).
    """
    raw = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    for r in raw["relations"]:
        if r["id"] == "del_distrito":
            r["hereda"] = True
    pack = ContentPack.model_validate(raw)
    sim = Simulation(pack, seed=1312)

    muerto_id = AgentId("coka_d1")
    heredero_id = AgentId("dandri_d1")
    muerto = sim.state.agents[muerto_id]
    heredero = sim.state.agents[heredero_id]

    sitio_muerte = PlaceId("cornucopia")
    muerto.at = sitio_muerte

    # Establecemos relación de herencia con aprecio positivo
    heredero.relations[RelationId("del_distrito")] = {muerto_id}
    heredero.bonds[muerto_id] = Bond(regard=0.8, encounters=1)

    # Propiedad ordinaria (deuda)
    deuda = Propiedad(
        id=PropertyId("prop:deuda:1"),
        tipo=PropertyKind.DEUDA,
        objeto="50",
        renta={},
        tributo={},
        dueño=muerto_id,
    )
    sim.state.propiedades[deuda.id] = deuda

    # Objeto equipado (lanza corta)
    lanza = Propiedad(
        id=PropertyId("prop:lanza:muerto"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        dueño=muerto_id,
    )
    sim.state.alta_objeto(lanza)
    sim.equipar(muerto_id, lanza.id)
    assert sim.state.propiedades[lanza.id].equipado

    # El agente muere
    sim.morir(muerto_id)

    # B.1.4 & M4: El objeto queda en el suelo donde murió, sin dueño y sin equipar
    lanza_muerto = sim.state.propiedades[lanza.id]
    assert lanza_muerto.lugar == sitio_muerte
    assert lanza_muerto.dueño is None
    assert not lanza_muerto.equipado

    # La propiedad ordinaria sí pasa al heredero
    assert sim.state.propiedades[deuda.id].dueño == heredero_id


def test_b1_5_item_moved_en_cada_movimiento_con_su_data() -> None:
    """B.1.5: `ITEM_MOVED` en cada movimiento, con su `data` completa:
    propiedad, item, de, a, puesto.
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    donde = sim.state.agents[agente_id].at

    objeto = Propiedad(
        id=PropertyId("obj:test:item_moved"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        lugar=donde,
    )
    sim.state.propiedades[objeto.id] = objeto

    conteo_inicial = len([e for e in sim.log._events if e.kind is EventKind.ITEM_MOVED])

    # 1. Mover del suelo al agente
    sim._mover_objeto(objeto, actor=agente_id, dueño=agente_id, lugar=None, donde=donde)
    eventos_coger = [e for e in sim.log._events if e.kind is EventKind.ITEM_MOVED]
    assert len(eventos_coger) == conteo_inicial + 1
    ev_coger = eventos_coger[-1]
    assert ev_coger.data == {
        "propiedad": str(objeto.id),
        "item": objeto.objeto,
        "de": f"lugar:{donde}",
        "a": f"agente:{agente_id}",
        "puesto": False,
    }

    # 2. Equipar
    sim.equipar(agente_id, objeto.id)
    eventos_equipar = [e for e in sim.log._events if e.kind is EventKind.ITEM_MOVED]
    assert len(eventos_equipar) == conteo_inicial + 2
    ev_equipar = eventos_equipar[-1]
    assert ev_equipar.data["puesto"] is True
    assert ev_equipar.data["propiedad"] == str(objeto.id)
    assert ev_equipar.data["de"] == f"agente:{agente_id}"
    assert ev_equipar.data["a"] == f"agente:{agente_id}"


def test_b1_6_persistencia_guardar_y_reanudar_con_objetos(tmp_path: Path) -> None:
    """B.1.6: Persistencia: guardar y reanudar con objetos da el mismo log que no parar,
    y preserva el campo lugar de los objetos del suelo.

    Sensible a mutación M5 (`persistence`: no guardar `lugar`).
    """
    pack = load_pack(ISLA_PACK)

    # 1. Simulación continuada
    seguida = Simulation(pack, seed=1312)
    seguida.run(96)

    # 2. Simulación que se guarda y se reanuda
    partida = Simulation(pack, seed=1312)
    partida.run(96)

    fichero = tmp_path / "partida_isla.json"
    partida.save(fichero)

    reanudada = Simulation.resume(fichero, pack)

    # Sensible a M5: todos los objetos que estaban en el suelo deben conservar su lugar
    objetos_suelo_partida = [
        p for p in partida.state.propiedades.values()
        if partida.state.es_objeto(p) and p.lugar is not None
    ]
    assert len(objetos_suelo_partida) > 0
    for p_orig in objetos_suelo_partida:
        p_rest = reanudada.state.propiedades[p_orig.id]
        assert p_rest.lugar == p_orig.lugar, f"El objeto {p_orig.id} perdió su lugar al reanudar"
        assert p_rest.equipado == p_orig.equipado

    # Ambas continúan y sus estados son idénticos
    log_seg = io.StringIO()
    log_rean = io.StringIO()
    seguida.log._sink = log_seg
    reanudada.log._sink = log_rean

    seguida.run(12)
    reanudada.run(12)
    assert foto(seguida) == foto(reanudada)
    assert log_seg.getvalue() == log_rean.getvalue()


# ==============================================================================
# B.2 — Ficha, conversación, escena
# ==============================================================================


def test_b2_1_derive_usa_arma_equipada_y_fallback_suministros() -> None:
    """B.2.1: `derive` usa el arma equipada mapeada; sin ella, el camino de suministros.

    Sensible a mutación M6 (`derive`: ignorar lo equipado).
    """
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, pack, ruleset)
    sim = Simulation(pack, seed=1312)

    agente_id = AgentId("coka_d1")
    agente = sim.state.agents[agente_id]
    agente.needs[NeedId("suministros")] = 0.0

    # 1. Sin arma equipada y con suministros en 0.0:
    # El camino por suministros deriva sin_armas o baston (daga exige suministros >= 0.15)
    ficha_sin_arma = derive(sim.state, agente_id, ruleset, binding)
    assert ficha_sin_arma.weapon.id in ("sin_armas", "baston")

    # 2. Con arma equipada mapeada:
    # En ISLA_BINDING, 'lanza_corta' mapea a 'espada_corta'
    lanza = Propiedad(
        id=PropertyId("obj:lanza:derivada"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        dueño=agente_id,
        equipado=True,
    )
    sim.state.alta_objeto(lanza)
    sim.state.recalcular_equipo(agente)

    ficha_con_arma = derive(sim.state, agente_id, ruleset, binding)
    # Sensible a M6: si M6 ignora lo equipado, derivaría sin_armas o baston
    assert ficha_con_arma.weapon.id == "espada_corta"


def test_b2_2_dar_y_pedir_en_conversacion() -> None:
    """B.2.2: Dar transfiere y sube el aprecio; pedir con aprecio bajo se niega,
    con alto transfiere, y nunca lo equipado.

    Sensible a mutación M7 (pedir: transferir lo equipado).
    """
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    speaker = AgentId("coka_d1")
    listener = AgentId("belna_d3")  # De distinto distrito: relation_floor es 0.0
    donde = PlaceId("cornucopia")
    sim.state.agents[speaker].at = donde
    sim.state.agents[listener].at = donde

    # 1. Dar transfiere y sube el aprecio
    regalo = Propiedad(
        id=PropertyId("obj:regalo:1"),
        tipo=PropertyKind.OBJETO,
        objeto="cuchillo",
        renta={},
        tributo={},
        dueño=speaker,
    )
    sim.state.propiedades[regalo.id] = regalo
    talk = Conversation(listener=listener)
    aprecio_antes = sim.state.agents[listener].regard_for(speaker, sim.state.tick, 1.0, 0.0)
    sim.apply_social(speaker, listener, SocialAct.GIVE, None, talk, item=regalo.id)

    assert regalo.dueño == listener
    aprecio_despues = sim.state.agents[listener].regard_for(speaker, sim.state.tick, 1.0, 0.0)
    assert aprecio_despues > aprecio_antes

    # 2. Pedir con aprecio bajo (< give_above = 0.15): se niega (seco), nada cambia
    objeto_oyente = Propiedad(
        id=PropertyId("obj:oyente:1"),
        tipo=PropertyKind.OBJETO,
        objeto="cuchillo",
        renta={},
        tributo={},
        dueño=listener,
        equipado=False,
    )
    sim.state.propiedades[objeto_oyente.id] = objeto_oyente
    sim.state.agents[listener].bonds[speaker] = Bond(regard=0.05, encounters=1)  # 0.05 < 0.15

    talk2 = Conversation(listener=listener)
    r_bajo = sim.apply_social(
        speaker, listener, SocialAct.ASK_FOR, None, talk2, item=objeto_oyente.id
    )
    assert r_bajo.tone is Tone.CURT
    assert objeto_oyente.dueño == listener

    # 3. Pedir con aprecio alto (>= give_above): transfiere el objeto no equipado
    sim.state.agents[listener].bonds[speaker] = Bond(regard=0.50, encounters=1)  # 0.50 >= 0.15

    talk3 = Conversation(listener=listener)
    sim.apply_social(speaker, listener, SocialAct.ASK_FOR, None, talk3, item=objeto_oyente.id)
    assert objeto_oyente.dueño == speaker

    # 4. Pedir objeto EQUIPADO: NUNCA transfiere lo equipado, incluso con aprecio alto
    arma_equipada = Propiedad(
        id=PropertyId("obj:equipada:listener"),
        tipo=PropertyKind.OBJETO,
        objeto="lanza_corta",
        renta={},
        tributo={},
        dueño=listener,
        equipado=True,
    )
    sim.state.propiedades[arma_equipada.id] = arma_equipada

    talk4 = Conversation(listener=listener)
    r_equipada = sim.apply_social(
        speaker, listener, SocialAct.ASK_FOR, None, talk4, item=arma_equipada.id
    )

    # Sensible a M7: si M7 transfiere lo equipado, arma_equipada pasaría a speaker
    assert r_equipada.tone is Tone.CURT
    assert arma_equipada.dueño == listener
    assert arma_equipada.equipado is True


def test_b2_3_escena_nombra_arma_notable_y_suelo() -> None:
    """B.2.3: La escena nombra el arma de un notable y lo que hay en el suelo."""
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)

    jugador_id = AgentId("coka_d1")
    notable_id = AgentId("dandri_d1")
    donde = PlaceId("cornucopia")

    sim.set_player(jugador_id)
    sim.state.agents[jugador_id].at = donde
    sim.state.agents[notable_id].at = donde

    # Limpiamos las propiedades del sitio para tener contenido controlado
    for p in list(sim.state.propiedades.values()):
        if p.lugar == donde or p.dueño == notable_id:
            sim.state.baja_objeto(p)

    # Ponemos en el suelo 1 lanza corta y 2 cuchillos
    sim.state.alta_objeto(Propiedad(
        id=PropertyId("obj:suelo:1"), tipo=PropertyKind.OBJETO, objeto="lanza_corta",
        renta={}, tributo={}, lugar=donde,
    ))
    sim.state.alta_objeto(Propiedad(
        id=PropertyId("obj:suelo:2"), tipo=PropertyKind.OBJETO, objeto="cuchillo",
        renta={}, tributo={}, lugar=donde,
    ))
    sim.state.alta_objeto(Propiedad(
        id=PropertyId("obj:suelo:3"), tipo=PropertyKind.OBJETO, objeto="cuchillo",
        renta={}, tributo={}, lugar=donde,
    ))

    # El notable tiene equipada un hacha (narration: "un hacha de batalla")
    hacha = Propiedad(
        id=PropertyId("obj:notable:hacha"), tipo=PropertyKind.OBJETO, objeto="hacha",
        renta={}, tributo={}, dueño=notable_id, equipado=True,
    )
    sim.state.alta_objeto(hacha)
    sim.state.recalcular_equipo(sim.state.agents[notable_id])

    # Generamos la escena
    escena = scene_of(
        sim.state,
        str(jugador_id),
        seen=Sighting(),
        involved=frozenset(),
        last_was_fight=False,
        elapsed=0,
    )

    # Lo que hay en el suelo está listado y agrupado
    assert "una lanza corta" in escena.floor
    assert "un cuchillo (x2)" in escena.floor

    # El notable lleva su arma
    notable = next(n for n in escena.notables if n.name == "Dandri")
    assert notable.carries == "un hacha de batalla"

    # Briefing incluye ambos elementos en el texto presentado
    momento = world_moment(sim.state, str(jugador_id), facts=(), table=Table(), scene=escena)
    texto = briefing(momento)
    assert "lleva un hacha de batalla" in texto
    assert "en el suelo: un cuchillo (x2), una lanza corta" in texto


def test_b2_4_pack_o_enlace_con_item_inexistente_no_carga() -> None:
    """B.2.4: Un pack con un items o un mapeo a un id inexistente no carga."""
    # 1. PlaceSpec.items hace referencia a un id de objeto inexistente
    raw_bad_place = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    raw_bad_place["places"][0]["items"] = {"objeto_fantasma": 1}
    with pytest.raises((PackError, ValidationError), match="objeto_fantasma"):
        ContentPack.model_validate(raw_bad_place)

    # 2. ItemSpec con necesidad inexistente en gains
    raw_bad_item = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    raw_bad_item["items"][0]["gains"] = {"necesidad_inexistente": 1.5}
    with pytest.raises((PackError, ValidationError), match="necesidad_inexistente"):
        ContentPack.model_validate(raw_bad_item)

    # 3. ActionSpec con gives_item sin target
    raw_bad_action = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    raw_bad_action["actions"][0]["gives_item"] = {}
    raw_bad_action["actions"][0]["target"] = None
    with pytest.raises((PackError, ValidationError), match="gives_item sin target"):
        ContentPack.model_validate(raw_bad_action)

    # 4. BindingSpec con item del pack inexistente
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)

    raw_bad_binding = yaml.safe_load(ISLA_BINDING.read_text(encoding="utf-8"))
    raw_bad_binding["items"]["item_que_no_existe"] = "daga"

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as tmp:
        yaml.safe_dump(raw_bad_binding, tmp)
        tmp.flush()
        with pytest.raises(BindingError, match="item_que_no_existe"):
            load_binding(Path(tmp.name), pack, ruleset)

    # 5. BindingSpec con mapeo a pieza inexistente en weapons ni armors
    raw_bad_piece = yaml.safe_load(ISLA_BINDING.read_text(encoding="utf-8"))
    raw_bad_piece["items"]["cuchillo"] = "arma_espacial_laser"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as tmp:
        yaml.safe_dump(raw_bad_piece, tmp)
        tmp.flush()
        with pytest.raises(BindingError, match="arma_espacial_laser"):
            load_binding(Path(tmp.name), pack, ruleset)

    # 6. BindingSpec con slot mismatch: arma asignada a pieza de armadura
    raw_mismatch = yaml.safe_load(ISLA_BINDING.read_text(encoding="utf-8"))
    raw_mismatch["items"]["cuchillo"] = "cuero"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as tmp:
        yaml.safe_dump(raw_mismatch, tmp)
        tmp.flush()
        with pytest.raises(BindingError, match=r"cuero.*es una armadura y el objeto no lo es"):
            load_binding(Path(tmp.name), pack, ruleset)

