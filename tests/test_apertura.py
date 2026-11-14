"""Pruebas de la apertura y el texto del mundo (unidad 22, §B).

Verifica:
- B.1: mundo.yaml (opcional, validación de lugares/duplicados, determinismo del log).
- B.2: Apertura (vecinos reales, condición personal como estado, filtro y tope de
  hechos notables, validación de lugares y personas por el narrador, plantillas en
  los 6 packs, contar la apertura una sola vez y no al reanudar).
- B.3: Borrador y mundo guardado (el borrador nunca escribe mundo.yaml ni inventa
  lugares; la pantalla lista guardados y empezar desde uno cuenta hechos de su log).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml

from agora.cognition.borrador import (
    BorradorError,
    LoreDraft,
    PlacesDraft,
    escribir_borrador,
    pedir_borrador,
)
from agora.cognition.narrador import (
    Narrator,
    Table,
    Told,
    fallback,
    narrate,
    opening_moment,
)
from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    AgentId,
    PlaceId,
    SituationId,
    WorldLore,
)
from agora.engine.pack import PackError, load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.state import Condicion
from agora.engine.world import Simulation
from agora.play import Terminal
from agora.present import TextPresenter
from agora.ui.session import NUEVO, guardados

ISLA_PACK = Path("packs/isla/pack.yaml")
CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")


class DummyProvider(CognitionProvider):
    """Proveedor ficticio para pruebas de cognición."""

    def __init__(self, answer: object) -> None:
        self.answer = answer

    def think(self, briefing: str, schema: type, semilla: int) -> object:
        if callable(self.answer):
            return self.answer(briefing, schema, semilla)
        return self.answer


class CapturingPresenter(TextPresenter):
    """Presentador para capturar llamadas a opening()."""

    def __init__(self) -> None:
        super().__init__(io.StringIO("salir\n"), io.StringIO())
        self.aperturas: list[Told] = []

    def opening(self, told: Told, chain: bool) -> None:
        self.aperturas.append(told)
        super().opening(told, chain)


# =============================================================================
# B.1 — mundo.yaml
# =============================================================================


def test_b1_1_sin_mundo_yaml_world_es_none_y_pack_carga_igual(tmp_path: Path) -> None:
    # 1. Sin el archivo, world es None y el pack carga igual.
    pack = load_pack(ISLA_PACK)
    assert pack.world is None
    assert len(pack.places) > 0
    assert len(pack.agents) > 0

    # En una carpeta aislada con solo pack.yaml
    carpeta = tmp_path / "sin_mundo"
    carpeta.mkdir()
    pack_yaml = carpeta / "pack.yaml"
    pack_yaml.write_text(ISLA_PACK.read_text(encoding="utf-8"), encoding="utf-8")

    cargado = load_pack(pack_yaml)
    assert cargado.world is None
    assert cargado.id == pack.id
    assert len(cargado.places) == len(pack.places)


def test_b1_2_con_mundo_yaml_aplica_descripciones_o_falla_si_invalido(
    tmp_path: Path,
) -> None:
    # 2. Con él, se aplican las descripciones; un id de lugar inexistente o una
    # descripción duplicada (pack y mundo.yaml) no carga.

    # Caso A: válido. Tomamos isla, quitamos la descripción de pedestal_1 en pack.yaml
    # y la ponemos en mundo.yaml.
    datos = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    for p in datos["places"]:
        if p["id"] == "pedestal_1":
            p.pop("description", None)
            break

    dir_valido = tmp_path / "valido"
    dir_valido.mkdir()
    (dir_valido / "pack.yaml").write_text(yaml.safe_dump(datos), encoding="utf-8")
    (dir_valido / "mundo.yaml").write_text(
        yaml.safe_dump(
            {
                "premise": "Un archipiélago olvidado entre la bruma.",
                "tone": "Crudo y directo.",
                "known": ["El agua de lluvia es la única potable."],
                "places": {
                    "pedestal_1": "Un bloque de piedra agrietado cubierto de musgo húmedo.",
                },
            }
        ),
        encoding="utf-8",
    )

    pack_con = load_pack(dir_valido / "pack.yaml")
    assert pack_con.world is not None
    assert pack_con.world.premise == "Un archipiélago olvidado entre la bruma."
    assert pack_con.world.tone == "Crudo y directo."
    assert pack_con.world.known == ("El agua de lluvia es la única potable.",)
    assert (
        pack_con.place_by_id[PlaceId("pedestal_1")].description
        == "Un bloque de piedra agrietado cubierto de musgo húmedo."
    )

    # Caso B: id de lugar inexistente en mundo.yaml.
    dir_inexistente = tmp_path / "inexistente"
    dir_inexistente.mkdir()
    (dir_inexistente / "pack.yaml").write_text(
        ISLA_PACK.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (dir_inexistente / "mundo.yaml").write_text(
        yaml.safe_dump(
            {
                "premise": "Un mundo con lugar fantasma.",
                "tone": "Misterioso.",
                "places": {
                    "lugar_inexistente_xyz": "No existe en el mapa.",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PackError) as exc_inexistente:
        load_pack(dir_inexistente / "pack.yaml")
    assert "no existe ese lugar en el pack" in str(exc_inexistente.value)

    # Caso C: descripción duplicada (el pack ya la tiene y mundo.yaml también).
    dir_duplicado = tmp_path / "duplicado"
    dir_duplicado.mkdir()
    (dir_duplicado / "pack.yaml").write_text(
        ISLA_PACK.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (dir_duplicado / "mundo.yaml").write_text(
        yaml.safe_dump(
            {
                "premise": "Un mundo con duplicado.",
                "tone": "Confuso.",
                "places": {
                    "cornucopia": "Redescripción prohibida porque ya tiene una.",
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PackError) as exc_duplicado:
        load_pack(dir_duplicado / "pack.yaml")
    assert "el pack ya describe ese lugar" in str(exc_duplicado.value)


def test_b1_3_con_y_sin_mundo_yaml_el_log_de_la_corrida_es_identico(
    tmp_path: Path,
) -> None:
    # 3. Con y sin mundo.yaml, el log de una corrida es idéntico.
    datos = yaml.safe_load(ISLA_PACK.read_text(encoding="utf-8"))
    for p in datos["places"]:
        if p["id"] == "pedestal_1":
            p.pop("description", None)
            break

    dir_sin = tmp_path / "sin"
    dir_sin.mkdir()
    pack_sin_path = dir_sin / "pack.yaml"
    pack_sin_path.write_text(yaml.safe_dump(datos), encoding="utf-8")

    dir_con = tmp_path / "con"
    dir_con.mkdir()
    pack_con_path = dir_con / "pack.yaml"
    pack_con_path.write_text(yaml.safe_dump(datos), encoding="utf-8")
    (dir_con / "mundo.yaml").write_text(
        yaml.safe_dump(
            {
                "premise": "Texto que solo lee el narrador.",
                "tone": "Inerte para el motor.",
                "known": ["Nada de esto afecta a las decisiones del motor."],
                "places": {
                    "pedestal_1": "Descripción externa para el pedestal.",
                },
            }
        ),
        encoding="utf-8",
    )

    pack_sin = load_pack(pack_sin_path)
    pack_con = load_pack(pack_con_path)

    sim_sin = Simulation(pack_sin, seed=42)
    sim_con = Simulation(pack_con, seed=42)

    sim_sin.run(25)
    sim_con.run(25)

    assert [e.to_json() for e in sim_sin.log] == [e.to_json() for e in sim_con.log]


# =============================================================================
# B.2 — Apertura
# =============================================================================


def test_b2_1_el_momento_lleva_los_vecinos_reales_del_lugar_de_llegada_y_ningun_otro() -> None:
    # 1. El momento lleva los vecinos reales del lugar de llegada y ningún otro lugar.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    player = "elor_d1"
    yo = sim.state.agents[AgentId(player)]
    lugar = pack.place_by_id[yo.at]

    m = opening_moment(sim.state, player, (), Table())

    # Vecinos contiguos esperados
    minutos_per_tick = pack.clock.minutes_per_tick
    vecinos_esperados = {
        f"{pack.place_by_id[n].label} (a {t * minutos_per_tick} minutos)"
        for n, t in lugar.neighbors.items()
    }

    assert set(m.neighbors) == vecinos_esperados
    assert len(m.neighbors) == len(lugar.neighbors)

    # Lugares lejanos de la isla que NO son vecinos no deben figurar en neighbors
    no_vecinos = [
        p.label
        for p in pack.places
        if p.id != yo.at and p.id not in lugar.neighbors
    ]
    assert len(no_vecinos) > 0
    for lejano in no_vecinos:
        assert not any(lejano in n for n in m.neighbors)


def test_b2_2_condicion_personal_activa_sale_como_estado_no_como_suceso() -> None:
    # 2. Una condición personal activa sale como estado, no como suceso.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    player = "elor_d1"
    yo = sim.state.agents[AgentId(player)]

    # En isla, 'herida' tiene personal: true
    herida_spec = pack.situation_by_id[SituationId("herida")]
    assert herida_spec.personal is True

    # Le asignamos la condición personal al jugador
    yo.condiciones.append(Condicion(situacion=SituationId("herida")))

    m = opening_moment(sim.state, player, (), Table())

    # Sale como estado
    assert f"eres {herida_spec.label}" in m.state

    # No sale como suceso en facts ni en moving
    assert not any("herida" in str(f) for f in m.facts)
    assert not any("herida" in h for h in m.moving)

    # En la plantilla sale como "Eres herida." dentro de quién eres, no "empieza para ti"
    prosa = fallback(m)
    assert f"Eres {herida_spec.label}." in prosa
    assert "empieza para ti" not in prosa.lower()


def test_b2_3_lo_que_se_mueve_muertes_dolientes_un_solo_hecho_maximo_7_dias_maximo_5() -> None:
    # 3. «Lo que se mueve»: una muerte con varios dolientes es un solo hecho;
    # hechos de hace más de 7 días no entran; como mucho 5.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    por_dia = pack.clock.ticks_per_day
    sim.state.tick = 10 * por_dia

    victima = "elor_d1"
    eventos: list[Event] = [
        # Muerte emitida con 3 dolientes distintos (3 eventos AGENT_DIED para la misma víctima)
        Event(seq=1, tick=9 * por_dia, kind=EventKind.AGENT_DIED, actor=AgentId("d1"),
              subject=AgentId(victima), data={"victim": victima}),
        Event(seq=2, tick=9 * por_dia, kind=EventKind.AGENT_DIED, actor=AgentId("d2"),
              subject=AgentId(victima), data={"victim": victima}),
        Event(seq=3, tick=9 * por_dia, kind=EventKind.AGENT_DIED, actor=AgentId("d3"),
              subject=AgentId(victima), data={"victim": victima}),
        # Hecho antiguo (hace 8 días, fuera de los 7 días de ventana)
        Event(seq=4, tick=sim.state.tick - 8 * por_dia, kind=EventKind.AGENT_BORN,
              actor=AgentId("mira_d1"), subject=None, data={}),
        # 6 hechos recientes para probar el tope de 5
        Event(seq=10, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("zevi_d12"),
              subject=None, data={"need": str(pack.needs[0].id)}),
        Event(seq=11, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("orlo_d2"),
              subject=None, data={"need": str(pack.needs[0].id)}),
        Event(seq=12, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("bruno_d2"),
              subject=None, data={"need": str(pack.needs[0].id)}),
        Event(seq=13, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("tiber_d3"),
              subject=None, data={"need": str(pack.needs[0].id)}),
        Event(seq=14, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("fausto_d4"),
              subject=None, data={"need": str(pack.needs[0].id)}),
        Event(seq=15, tick=9 * por_dia, kind=EventKind.RANK_UP, actor=AgentId("vane_d5"),
              subject=None, data={"need": str(pack.needs[0].id)}),
    ]

    m = opening_moment(sim.state, "zevi_d12", eventos, Table())

    # Una muerte con varios dolientes es un solo hecho
    assert sum(1 for h in m.moving if "ha muerto Elor" in h) == 1

    # Hecho de hace más de 7 días no entra
    assert not any("ha nacido Mira" in h for h in m.moving)

    # Como mucho 5
    assert len(m.moving) == 5


def test_b2_4_proveedor_falso_comprobacion_lugares_y_personas() -> None:
    # 4. Proveedor falso con prosa que nombra un lugar del pack no dado -> plantilla;
    # con un lugar dado -> se acepta; con un nombre de persona no dado -> plantilla.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    player = "elor_d1"
    m = opening_moment(sim.state, player, (), Table())

    # Encontrar un lugar del pack que no está en el briefing de la apertura
    lugar_no_dado = next(
        p.label
        for p in pack.places
        if p.label != m.place and not any(p.label in n for n in m.neighbors)
    )

    # Encontrar un nombre de persona del censo que no está en el briefing
    told_briefing = fallback(m)
    persona_no_dada = next(
        nombre
        for nombre in m.everyone
        if nombre != m.player and nombre not in told_briefing
    )

    # Subcaso 1: prosa que nombra un lugar del pack no dado -> descartada, va a plantilla
    prosa_lugar_no_dado = (
        f"A lo lejos divisas {lugar_no_dado} cubierto por la densa niebla matutina. "
        "El viento sopla con fuerza y todo permanece en calma."
    )
    p1 = DummyProvider(prosa_lugar_no_dado)
    told1 = narrate(m, [p1], seed=1)
    assert told1.by is None
    assert told1.text == fallback(m)

    # Subcaso 2: prosa con un lugar dado (el lugar de llegada) -> aceptada
    prosa_lugar_dado = (
        f"Llegas a {m.place} con el viento azotando las ramas de los árboles. "
        "El silencio de la mañana envuelve tus pasos solitarios."
    )
    p2 = DummyProvider(prosa_lugar_dado)
    told2 = narrate(m, [p2], seed=1)
    assert told2.by == 0
    assert told2.text == prosa_lugar_dado

    # Subcaso 3: prosa con un nombre de persona no dado -> descartada, va a plantilla
    prosa_persona_no_dada = (
        f"Llegas a {m.place} y crees ver a {persona_no_dada} cruzando entre los matorrales. "
        "El aire huele a salitre y peligro inminente."
    )
    p3 = DummyProvider(prosa_persona_no_dada)
    told3 = narrate(m, [p3], seed=1)
    assert told3.by is None
    assert told3.text == fallback(m)


def test_b2_5_plantilla_en_los_6_packs_sin_errores_y_sin_mundo_yaml_empieza_por_llegada() -> None:
    # 5. Plantilla en los 6 packs sin errores; sin mundo.yaml, empieza por la llegada.
    packs = ["confluencia", "ciudad", "aldea", "barrio", "dark_fantasy", "isla"]
    for nombre in packs:
        pack = load_pack(Path(f"packs/{nombre}/pack.yaml"))
        sim = Simulation(pack, seed=1)
        player = str(pack.agents[0].id)
        m = opening_moment(sim.state, player, (), Table())
        prosa = fallback(m)

        assert isinstance(prosa, str)
        assert len(prosa) > 0
        # Sin mundo.yaml (ninguno de los 6 tiene mundo.yaml de serie), empieza por la llegada
        assert pack.world is None
        assert prosa.startswith(f"Llegas a {m.place}.")


def test_b2_6_la_apertura_sale_una_vez_antes_del_primer_turno_al_reanudar_no() -> None:
    # 6. La apertura sale una vez, antes del primer turno; al reanudar, no.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    yo = sim.state.agents[AgentId("elor_d1")]

    # Partida nueva: apertura=True
    presenter_nueva = CapturingPresenter()
    terminal_nueva = Terminal(
        sim,
        io.StringIO("salir\n"),
        io.StringIO(),
        presenter=presenter_nueva,
        narrator=Narrator((), Table()),
        apertura=True,
    )

    # Primer turno: se cuenta la apertura antes de la decisión
    terminal_nueva.choose(sim.state, yo, ())
    assert len(presenter_nueva.aperturas) == 1

    # Segundo turno: la apertura NO se repite
    terminal_nueva.choose(sim.state, yo, ())
    assert len(presenter_nueva.aperturas) == 1

    # Partida reanudada: apertura=False
    presenter_reanudar = CapturingPresenter()
    terminal_reanudar = Terminal(
        sim,
        io.StringIO("salir\n"),
        io.StringIO(),
        presenter=presenter_reanudar,
        narrator=Narrator((), Table()),
        apertura=False,
    )

    terminal_reanudar.choose(sim.state, yo, ())
    assert len(presenter_reanudar.aperturas) == 0


# =============================================================================
# B.3 — Borrador y mundo guardado
# =============================================================================


def test_b3_1_borrador_nunca_escribe_mundo_yaml_y_con_id_inventado_no_escribe_nada(
    tmp_path: Path,
) -> None:
    # 1. El borrador (proveedor falso) nunca escribe mundo.yaml; con un id de
    # lugar inventado, no escribe nada y lo dice.

    lore = WorldLore(
        premise="Premisa de prueba.",
        tone="Serio.",
        known=("Dato 1",),
    )

    # Intentar escribir mundo.yaml explícitamente lanza BorradorError y no escribe
    destino_prohibido = tmp_path / "mundo.yaml"
    with pytest.raises(BorradorError) as exc_mundo:
        escribir_borrador(destino_prohibido, lore, {})
    assert "el borrador no escribe mundo.yaml" in str(exc_mundo.value)
    assert not destino_prohibido.exists()

    # Si se pide borrador y el modelo inventa un id de lugar inexistente
    pack = load_pack(CONFLUENCIA_PACK)

    # Un dummy que responde a LoreDraft con éxito y a PlacesDraft
    # con los lugares pedidos más uno inventado
    faltan = [p for p in pack.places if not p.description]
    assert len(faltan) > 0

    def responder_con_inventado(briefing: str, schema: type, semilla: int) -> object:
        if schema is LoreDraft:
            return LoreDraft(
                premise="Premisa del modelo ficticio.",
                tone="Tranquilo.",
                known=["Rumor 1"],
            )
        if schema is PlacesDraft:
            # Describimos los lugares del lote (los primeros 15 que faltan) y añadimos uno inventado
            desc = {str(p.id): "Una descripción válida de la plaza." for p in faltan[:15]}
            desc["lugar_fantasma_inventado"] = "Una descripción falsa."
            return PlacesDraft(places=desc)
        return None

    dummy = DummyProvider(responder_con_inventado)

    with pytest.raises(BorradorError) as exc_inventado:
        pedir_borrador(pack, dummy, seed=42)
    assert "el modelo inventó el lugar «lugar_fantasma_inventado»" in str(exc_inventado.value)


def test_b3_2_pantalla_lista_mundos_guardados_y_empezar_desde_uno_da_apertura_con_hechos_del_log(
    tmp_path: Path,
) -> None:
    # 2. La pantalla lista los mundos guardados; empezar desde uno da la apertura
    # con hechos del log de esa partida.

    # Lista de guardados de confluencia (trae 'tras-90-dias')
    lista = guardados("confluencia")
    assert any(g["id"] == NUEVO for g in lista)
    assert any(g["id"] == "tras-90-dias" for g in lista)

    # Crear una partida guardada con eventos en el log
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    sim.state.tick = 20 * pack.clock.ticks_per_day

    # Añadir al log la muerte de un personaje
    sim.log.emit(
        tick=sim.state.tick - 10,
        kind=EventKind.AGENT_DIED,
        actor=AgentId("zevi_d12"),
        subject=AgentId("elor_d1"),
        data={"victim": "elor_d1"},
    )

    ruta_guardado = tmp_path / "partida_guardada.json"
    sim.save(ruta_guardado)

    # Reanudar desde el guardado
    sim_resumida = Simulation.resume(ruta_guardado, pack)
    assert len(sim_resumida.log.previos) > 0
    assert any(e.kind is EventKind.AGENT_DIED for e in sim_resumida.log.previos)

    # Al empezar desde ese guardado (apertura=True para la llegada), la apertura cuenta
    # los hechos del log previo de esa partida
    presenter = CapturingPresenter()
    yo = sim_resumida.state.agents[AgentId("zevi_d12")]

    terminal = Terminal(
        sim_resumida,
        io.StringIO("salir\n"),
        io.StringIO(),
        presenter=presenter,
        narrator=Narrator((), Table()),
        apertura=True,
    )
    terminal.choose(sim_resumida.state, yo, ())

    assert len(presenter.aperturas) == 1
    texto_apertura = presenter.aperturas[0].text
    assert "ha muerto Elor" in texto_apertura
