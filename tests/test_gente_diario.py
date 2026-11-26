"""Pruebas de la unidad 25b (§B): Tu gente y tu diario.

Verifica:
1. `people_view` no expone nada privado de otro (ni su aprecio hacia ti, ni sus
   necesidades, ni sus marcas); cada umbral de la tabla da su palabra (en el
   borde, la de arriba: 0.6 -> le quieres mucho; 0.3 -> le aprecias; 0.1 -> te cae bien;
   -0.1 -> te es indiferente o apenas le conoces; -0.3 -> te cae mal; <= -0.3 -> le detestas);
   rencor desde 0.3 («le guardas rencor», >= 0.6 «no se lo perdonas»).
2. Entran quien tiene relación con nombre, quien supera los umbrales (|aprecio| >= 0.1,
   agravio >= 0.2) y quien viste en 14 días; nadie más; como mucho 40; los muertos,
   aparte con fecha.
3. «Lo último que te hizo» sale de tu memoria (`por_quien`), no de la de otro.
4. Diario: un día con trama propia tiene entrada; un día sin nada no;
   prosa con nombre desconocido usa plantilla.
5. Guardar y continuar: las entradas son las mismas, sin regenerarse al reanudar/cargar.
6. Las órdenes `gente` y `diario` no pasan tiempo (tick no avanza); terminal sin ellas sale igual.
"""

from __future__ import annotations

import dataclasses
import io
from pathlib import Path
from typing import Any

import pytest

from agora.cognition.narrador import (
    Diario,
    DiaryEntry,
    Narrator,
    Table,
    _diario_plantilla,
    diary_moment,
)
from agora.engine.chronicle import Entrada
from agora.engine.events import Event, EventKind
from agora.engine.memory import Recuerdo
from agora.engine.ontology import ActionId, AgentId, MarkId, PlaceId, RelationId
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.state import Bond
from agora.engine.world import Simulation
from agora.play import Terminal
from agora.present import (
    PersonRow,
    palabra_de_aprecio,
    people_view,
)
from agora.run import build_parser
from agora.ui.session import Game, Partidas

CONFLUENCIA = Path("packs/confluencia/pack.yaml")


# ---------------------------------------------------------------------------
# 1. Privacidad de otro, umbrales de aprecio y rencor (§B.1, M1, M2)
# ---------------------------------------------------------------------------


def test_people_view_privacidad_y_umbrales_aprecio_y_rencor() -> None:
    """1. people_view no expone nada privado de otro (ni su aprecio hacia ti, ni sus
    necesidades, ni sus marcas); cada umbral de la tabla da su palabra (en el
    borde, la de arriba); el rencor se añade desde 0.3 (M1, M2)."""
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=1)
    yo_id = AgentId("cyra_nieblalta")
    otro_id = AgentId("adze_piedraparda")
    sim.set_player(yo_id)
    yo = sim.state.agents[yo_id]
    otro = sim.state.agents[otro_id]

    # Datos privados de otro:
    # - otro tiene aprecio alto hacia ti (0.8 -> le quieres mucho si fuera propio)
    # - pero tú sientes aprecio negativo hacia otro (-0.2 -> te cae mal)
    otro.bonds[yo_id] = Bond(regard=0.8, last_seen=sim.state.tick)
    yo.bonds[otro_id] = Bond(regard=-0.2, last_seen=sim.state.tick)

    # - otro tiene marcas ocultas y necesidades
    sim.state.marcas[otro_id] = {MarkId("secreto"): 7}

    vista = people_view(sim.state, yo_id)
    assert len(vista.vivos) > 0
    row = next(r for r in vista.vivos if r.nombre == sim.state.censo[otro_id].label)

    # La fila lleva lo que TÚ sientes por otro, NO lo que otro siente por ti (M1)
    assert row.sientes == "te cae mal"
    assert row.sientes != "le quieres mucho"

    # Verificación estricta de campos de PersonRow: ningún campo privado de otro
    nombres_campos = {f.name for f in dataclasses.fields(PersonRow)}
    assert nombres_campos == {
        "nombre", "vivo", "relaciones", "publico", "sientes", "rencor", "ultimo", "visto", "murio",
    }
    assert not hasattr(row, "necesidades")
    assert not hasattr(row, "marcas")
    assert not hasattr(row, "aprecio_ajeno")

    # Nada de marcas privadas o necesidades ajenas en lo público
    texto_publico = " ".join(row.publico)
    assert "secreto" not in texto_publico
    assert "7" not in texto_publico

    # Umbrales fijos y bordes (en el borde, la palabra de arriba) (M2)
    # >= 0.6: le quieres mucho
    assert palabra_de_aprecio(0.9, True) == "le quieres mucho"
    assert palabra_de_aprecio(0.6, True) == "le quieres mucho"
    assert palabra_de_aprecio(0.6, False) == "le quieres mucho"

    # 0.3 - 0.6: le aprecias
    assert palabra_de_aprecio(0.59, True) == "le aprecias"
    assert palabra_de_aprecio(0.3, True) == "le aprecias"
    assert palabra_de_aprecio(0.3, False) == "le aprecias"

    # 0.1 - 0.3: te cae bien
    assert palabra_de_aprecio(0.29, True) == "te cae bien"
    assert palabra_de_aprecio(0.1, True) == "te cae bien"
    assert palabra_de_aprecio(0.1, False) == "te cae bien"

    # -0.1 - 0.1: te es indiferente (con vínculo) o apenas le conoces (sin vínculo)
    assert palabra_de_aprecio(0.09, True) == "te es indiferente"
    assert palabra_de_aprecio(0.0, True) == "te es indiferente"
    assert palabra_de_aprecio(-0.1, True) == "te es indiferente"
    assert palabra_de_aprecio(0.09, False) == "apenas le conoces"
    assert palabra_de_aprecio(0.0, False) == "apenas le conoces"
    assert palabra_de_aprecio(-0.1, False) == "apenas le conoces"

    # -0.3 - -0.1: te cae mal
    assert palabra_de_aprecio(-0.11, True) == "te cae mal"
    assert palabra_de_aprecio(-0.3, True) == "te cae mal"
    assert palabra_de_aprecio(-0.3, False) == "te cae mal"

    # <= -0.3: le detestas
    assert palabra_de_aprecio(-0.31, True) == "le detestas"
    assert palabra_de_aprecio(-0.7, True) == "le detestas"
    assert palabra_de_aprecio(-0.31, False) == "le detestas"

    # Rencor desde 0.3: «le guardas rencor», >= 0.6: «no se lo perdonas»
    # Con agravio bajo (< 0.3) -> None
    escala = pack.tuning.grief_scale
    # valencia negativa suave -> agravio < 0.3
    sim.state.memoria.cargar(yo_id, [
        Recuerdo(
            seq=1, tick=sim.state.tick, kind=EventKind.ACTION_COMPLETED,
            por_quien=otro_id, valencia=-0.1, importancia=0.1,
        ),
    ])
    vista_rencor0 = people_view(sim.state, yo_id)
    r0 = next(r for r in vista_rencor0.vivos if r.nombre == sim.state.censo[otro_id].label)
    assert r0.rencor is None

    # Agravio moderado: 0.3 <= agravio < 0.6 -> «le guardas rencor»
    # Para agravio = 0.4: v = 0.4 * escala / 0.6 = 0.66 * escala
    sim.state.memoria.cargar(yo_id, [
        Recuerdo(
            seq=2, tick=sim.state.tick, kind=EventKind.ACTION_COMPLETED,
            por_quien=otro_id, valencia=-1.0, importancia=0.7 * escala,
        ),
    ])
    vista_rencor1 = people_view(sim.state, yo_id)
    r1 = next(r for r in vista_rencor1.vivos if r.nombre == sim.state.censo[otro_id].label)
    assert r1.rencor == "le guardas rencor"

    # Agravio hondo: agravio >= 0.6 -> «no se lo perdonas»
    # Para agravio >= 0.6: v >= 1.5 * escala
    sim.state.memoria.cargar(yo_id, [
        Recuerdo(
            seq=3, tick=sim.state.tick, kind=EventKind.ACTION_COMPLETED,
            por_quien=otro_id, valencia=-1.0, importancia=2.0 * escala,
        ),
    ])
    vista_rencor2 = people_view(sim.state, yo_id)
    r2 = next(r for r in vista_rencor2.vivos if r.nombre == sim.state.censo[otro_id].label)
    assert r2.rencor == "no se lo perdonas"


# ---------------------------------------------------------------------------
# 2. Quién entra, umbrales de entrada, tope 40 y muertos aparte (§B.2)
# ---------------------------------------------------------------------------


def test_quien_entra_quien_no_tope_40_y_muertos_aparte() -> None:
    """2. Entran quien tiene relación con nombre, quien supera los umbrales (|aprecio| >= 0.1,
    agravio >= 0.2) y quien viste en 14 días; nadie más; como mucho 40; los muertos, aparte."""
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=2)
    yo_id = AgentId("cyra_nieblalta")
    sim.set_player(yo_id)
    yo = sim.state.agents[yo_id]
    tpd = pack.clock.ticks_per_day
    escala = pack.tuning.grief_scale

    # Limpiamos relaciones, vínculos y avistamientos previos de yo para control total
    yo.bonds.clear()
    yo.relations.clear()
    yo.sightings.clear()
    sim.state.memoria.borrar(yo_id)

    todos = [a for a in sim.state.agents_in_order() if a.spec_id != yo_id]
    assert len(todos) >= 6

    # 1. A1: Relación con nombre (sin aprecio, sin agravio, sin avistamiento reciente)
    a1 = todos[0].spec_id
    yo.relations[RelationId("pareja")] = {a1}

    # 2. A2: Aprecio >= 0.1 (sin relación con nombre, sin avistamiento)
    a2 = todos[1].spec_id
    yo.bonds[a2] = Bond(regard=0.15, last_seen=sim.state.tick)

    # 3. A3: Aprecio negativo |aprecio| >= 0.1 (-0.25)
    a3 = todos[2].spec_id
    yo.bonds[a3] = Bond(regard=-0.25, last_seen=sim.state.tick)

    # 4. A4: Agravio >= 0.2 (sin relación, sin aprecio, sin avistamiento)
    # v = 0.3 * escala
    a4 = todos[3].spec_id
    sim.state.memoria.cargar(yo_id, [
        Recuerdo(
            seq=10, tick=sim.state.tick, kind=EventKind.ACTION_COMPLETED,
            por_quien=a4, valencia=-1.0, importancia=0.3 * escala,
        ),
    ])

    # 5. A5: Visto hace <= 14 días (p. ej. 5 días atrás)
    a5 = todos[4].spec_id
    lugar = PlaceId("plaza_mayor")
    yo.sightings[lugar] = (sim.state.tick - 5 * tpd, frozenset({a5}))

    # 6. A6: NADIE MÁS - Visto hace 20 días (> 14 días), |aprecio| < 0.1, sin agravio, sin relación
    a6 = todos[5].spec_id
    yo.bonds[a6] = Bond(regard=0.05, last_seen=sim.state.tick - 20 * tpd)
    yo.sightings[PlaceId("mercado_central")] = (sim.state.tick - 20 * tpd, frozenset({a6}))

    vista = people_view(sim.state, yo_id)
    nombres_vivos = {f.nombre for f in vista.vivos}

    # Deben entrar A1, A2, A3, A4, A5
    assert sim.state.censo[a1].label in nombres_vivos
    assert sim.state.censo[a2].label in nombres_vivos
    assert sim.state.censo[a3].label in nombres_vivos
    assert sim.state.censo[a4].label in nombres_vivos
    assert sim.state.censo[a5].label in nombres_vivos

    # NO debe entrar A6
    assert sim.state.censo[a6].label not in nombres_vivos

    # Muertos aparte: sacamos un agente de world.agents pero lo dejamos en censo
    muerto_id = a1
    sim.state.cronica.anotar(
        Entrada(
            tick=10 * tpd, tipo="muerte", quienes=(muerto_id,),
            lugar=None, grupo=None, texto_clave=f"{muerto_id} cayó",
        )
    )
    del sim.state.agents[muerto_id]

    vista_con_muerto = people_view(sim.state, yo_id)
    nombres_muertos = {f.nombre for f in vista_con_muerto.muertos}
    nombres_vivos_actual = {f.nombre for f in vista_con_muerto.vivos}

    assert sim.state.censo[muerto_id].label in nombres_muertos
    assert sim.state.censo[muerto_id].label not in nombres_vivos_actual
    nombre_esperado = sim.state.censo[muerto_id].label
    fila_muerto = next(f for f in vista_con_muerto.muertos if f.nombre == nombre_esperado)
    assert fila_muerto.vivo is False
    assert fila_muerto.murio is not None
    assert "murió el día 10" in fila_muerto.murio

    # Tope de gente: máximo 40
    assert len(vista_con_muerto.vivos) + len(vista_con_muerto.muertos) <= 40


# ---------------------------------------------------------------------------
# 3. Lo último que te hizo sale de tu memoria, no de la de otro (§B.3, M5)
# ---------------------------------------------------------------------------


def test_ultimo_que_te_hizo_sale_de_tu_memoria_no_de_otro() -> None:
    """3. «Lo último que te hizo» sale de tu memoria (`por_quien`), no de la de otro (M5)."""
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=3)
    yo_id = AgentId("cyra_nieblalta")
    sim.set_player(yo_id)
    yo = sim.state.agents[yo_id]

    todos = [a for a in sim.state.agents_in_order() if a.spec_id != yo_id]
    otro_id = todos[0].spec_id
    tercero_id = todos[1].spec_id

    # Vínculos para que aparezcan en gente
    yo.bonds[otro_id] = Bond(regard=0.5, last_seen=sim.state.tick)
    yo.bonds[tercero_id] = Bond(regard=0.5, last_seen=sim.state.tick)

    # En TU memoria: `otro` te hizo "charlar" hace 2 ticks
    sim.state.memoria.cargar(yo_id, [
        Recuerdo(
            seq=101, tick=sim.state.tick - 2, kind=EventKind.ACTION_COMPLETED,
            action=ActionId("charlar"), por_quien=otro_id, importancia=0.5,
        ),
    ])

    # En la memoria de `otro`: tiene un recuerdo de "convidar"
    sim.state.memoria.cargar(otro_id, [
        Recuerdo(
            seq=102, tick=sim.state.tick - 1, kind=EventKind.ACTION_COMPLETED,
            action=ActionId("convidar"), por_quien=yo_id, importancia=0.9,
        ),
    ])

    # En la memoria de `tercero`: tiene recuerdos propios, pero en TU memoria NO hay nada de él
    sim.state.memoria.cargar(tercero_id, [
        Recuerdo(
            seq=103, tick=sim.state.tick - 1, kind=EventKind.ACTION_COMPLETED,
            action=ActionId("charlar"), por_quien=yo_id, importancia=0.8,
        ),
    ])

    vista = people_view(sim.state, yo_id)
    fila_otro = next(r for r in vista.vivos if r.nombre == sim.state.censo[otro_id].label)
    fila_tercero = next(r for r in vista.vivos if r.nombre == sim.state.censo[tercero_id].label)

    # Sale de tu memoria: charlar
    assert fila_otro.ultimo is not None
    assert "charlar" in fila_otro.ultimo.lower()
    # No sale de la memoria ajena (M5)
    assert "convidar" not in fila_otro.ultimo.lower()

    # Tercero no te ha hecho nada según tu memoria: debe ser None (M5 leería la de tercero)
    assert fila_tercero.ultimo is None


# ---------------------------------------------------------------------------
# 4. Diario: trama propia tiene entrada, día vacío no, desconocido → plantilla (§B.4, M3)
# ---------------------------------------------------------------------------


class _CognitionConDesconocido(CognitionProvider):
    """Proveedor que devuelve un nombre del censo ajeno al briefing (fallback)."""

    def think(self, prompt: str, schema: Any, seed: int) -> str:
        return "Hoy hablé con Adze Piedraparda y todo cambió por completo."


def test_diario_trama_propia_vacio_y_plantilla_con_desconocido() -> None:
    """4. Diario: un día con trama propia tiene entrada; un día sin nada no;
    prosa con nombre desconocido usa plantilla (M3)."""
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=4)
    yo_id = AgentId("cyra_nieblalta")
    sim.set_player(yo_id)
    tpd = pack.clock.ticks_per_day
    narrador = Narrator((), Table())

    # Día 0: tiene una trama del jugador
    assert pack.plots is not None
    trama = pack.plots.plots[0]
    evento_trama = Event(
        seq=1, tick=5, kind=EventKind.PLOT_BEGAN, actor=yo_id,
        data={"plot": trama.id},
    )

    m0 = diary_moment(sim.state, str(yo_id), 0, [evento_trama], narrador.table)
    assert m0 is not None
    assert len(m0.moving) > 0
    entrada0 = narrador.diary(sim.state, str(yo_id), 0, [evento_trama])
    assert entrada0 is not None
    assert entrada0.dia == 0
    assert len(entrada0.texto) > 0

    # Día 1: día completamente vacío (sin tramas, sin recuerdos, sin crónicas ni combates) (M3)
    m1 = diary_moment(sim.state, str(yo_id), 1, [], narrador.table)
    assert m1 is None  # M3 haría que no fuera None
    entrada1 = narrador.diary(sim.state, str(yo_id), 1, [])
    assert entrada1 is None

    # Cerrar días en un Diario(): solo añade el día con hechos
    diario = Diario()
    diario.cerrado = -1
    sim.state.tick = 2 * tpd + 1  # han pasado día 0 y día 1
    nuevas = diario.cerrar_dias(sim.state, [evento_trama], narrador, str(yo_id))
    assert len(nuevas) == 1
    assert nuevas[0].dia == 0
    assert len(diario.entradas) == 1
    assert diario.entradas[0].dia == 0

    # Prosa con nombre del censo no dado en el briefing -> plantilla
    narrador_desconocido = Narrator((_CognitionConDesconocido(),), Table())
    entrada_desconocido = narrador_desconocido.diary(sim.state, str(yo_id), 0, [evento_trama])
    assert entrada_desconocido is not None
    # Cayó a plantilla: de_modelo es False y coincide con la plantilla
    assert entrada_desconocido.de_modelo is False
    assert "Adze Piedraparda" not in entrada_desconocido.texto
    assert entrada_desconocido.texto == _diario_plantilla(m0)


# ---------------------------------------------------------------------------
# 5. Guardar y continuar: las entradas son las mismas, sin regenerarse (§B.5, M4)
# ---------------------------------------------------------------------------


def test_guardar_y_continuar_entradas_no_se_regeneran(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5. Guardar y continuar: las entradas son las mismas, sin regenerarse (M4)."""
    pack = load_pack(CONFLUENCIA)
    args = build_parser().parse_args(["--pack", str(CONFLUENCIA), "--seed", "5", "--sin-llm"])
    sim = Simulation(pack, seed=5)
    yo_id = AgentId("cyra_nieblalta")
    sim.set_player(yo_id)

    partida_dir = tmp_path / "partida_test"
    partida_dir.mkdir(parents=True)
    guion_path = partida_dir / "guion.jsonl"
    guion_path.write_text("", encoding="utf-8")

    meta: dict[str, Any] = {
        "id": "partida_test",
        "mundo": "confluencia",
        "personaje": "Cyra",
        "semilla": 5,
        "lineas_por_guardado": {},
        "modelo": False,
    }

    partida = Game(args, sim, guion_path, carpeta=partida_dir, meta=meta)

    # Fijamos una entrada de diario previa en la partida
    texto_original = "Día 0: Hoy tomé una decisión que no podrá deshacerse jamás."
    entrada_original = DiaryEntry(dia=0, texto=texto_original, de_modelo=False)
    partida.diario.entradas.append(entrada_original)
    partida.diario.cerrado = 0

    # Guardamos la partida
    partida._guardar("manual", "prueba_diario")
    ruta_diario = partida_dir / "diario" / "manual.json"
    assert ruta_diario.is_file()

    # Reanudamos/continuamos desde el guardado a través de Partidas.continuar
    monkeypatch.setattr("agora.ui.session._carpeta_de_partidas", lambda: tmp_path)
    gestor = Partidas()
    continuada = gestor.continuar({"id": "partida_test", "cual": "manual"})

    try:
        # Las entradas deben ser exactamente las mismas (M4 las regeneraría o vaciaría)
        assert len(continuada.diario.entradas) == 1
        assert continuada.diario.entradas[0].dia == 0
        assert continuada.diario.entradas[0].texto == texto_original
        assert continuada.diario.entradas[0].de_modelo is False
        assert continuada.diario.cerrado == 0

        # Al volver a ejecutar _cerrar_dias en el mismo punto, no se duplican ni regeneran
        continuada._cerrar_dias(continuada.sim)
        assert len(continuada.diario.entradas) == 1
        assert continuada.diario.entradas[0] == entrada_original
    finally:
        continuada.cerrar()


# ---------------------------------------------------------------------------
# 6. Órdenes 'gente' y 'diario' no pasan tiempo (§B.6)
# ---------------------------------------------------------------------------


def test_ordenes_gente_y_diario_no_pasan_tiempo() -> None:
    """6. Las órdenes `gente` y `diario` no pasan tiempo; terminal sin ellas sale igual."""
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=6)
    yo_id = AgentId("cyra_nieblalta")
    sim.set_player(yo_id)
    yo = sim.state.agents[yo_id]

    diario = Diario(entradas=[
        DiaryEntry(dia=0, texto="He llegado a la confluencia.", de_modelo=False),
    ])

    out = io.StringIO()
    term = Terminal(sim, io.StringIO(), out, diario=diario)

    tick_inicial = sim.state.tick

    # Orden 'gente'
    res_gente = term._orden_directa(sim.state, yo, "gente")
    assert res_gente == (False, None)
    assert sim.state.tick == tick_inicial
    salida_gente = out.getvalue()
    assert len(salida_gente) > 0

    out.truncate(0)
    out.seek(0)

    # Orden 'diario'
    res_diario = term._orden_directa(sim.state, yo, "diario")
    assert res_diario == (False, None)
    assert sim.state.tick == tick_inicial
    salida_diario = out.getvalue()
    assert "día 0: He llegado a la confluencia." in salida_diario

    # Terminal con diario=None (sin diario)
    out_sin = io.StringIO()
    term_sin = Terminal(sim, io.StringIO(), out_sin, diario=None)
    res_sin = term_sin._orden_directa(sim.state, yo, "diario")
    assert res_sin == (False, None)
    assert sim.state.tick == tick_inicial
    assert "todavía no hay nada en tu diario" in out_sin.getvalue()

    # Terminal sin esas órdenes: _orden_directa devuelve None para otras órdenes ordinarias
    res_otra = term._orden_directa(sim.state, yo, "mirar")
    assert res_otra is None
    assert sim.state.tick == tick_inicial
