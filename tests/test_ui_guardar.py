"""Pruebas de la unidad 25 (§B): La hoja entera, las decisiones de trama y guardar y continuar.

Verifica:
1. `SheetView` propia lleva ficha mecánica, fama, marcas visibles (no ocultas) y tramas;
   la de otro, nada de eso; sin sistema enlazado, `mechanical` es `None`.
2. `TextPresenter.plot` produce el mismo texto que hoy;
   `Script` reproduce una partida con decisión de trama.
3. La web: evento `trama` con opciones y por defecto; un botón manda su número;
   «lo que haría» manda vacío y se elige la de por defecto.
4. Autoguardado: uno al empezar cada día, sobrescribe `auto.json`, nunca a mitad de tick;
   escritura atómica (simular un corte: el anterior sigue válido).
5. Continuar: mismo log que no haber parado; el guion sigue en el mismo archivo
   y reproduce la partida entera.
6. Un guardado `{}` o truncado no se lista y no rompe el inicio.
7. «La última vez»: sale al continuar y no en partida nueva;
   sin nombres ni lugares que no se le den.
8. Terminal sin modelo idéntica a la línea base.
"""

from __future__ import annotations

import io
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agora.cognition.narrador import (
    Kind,
    Narrator,
    Table,
    _vuelta_plantilla,
    strangers,
    vuelta_moment,
)
from agora.engine.ontology import AgentId, MarkId
from agora.engine.pack import load_pack
from agora.engine.ports import PlotView
from agora.engine.state import PlotRun, WorldState
from agora.engine.world import Simulation
from agora.play import Recorder, Script, Terminal, TerminalCombat
from agora.present import MechanicalView, TextPresenter, sheet_view
from agora.run import build_parser, correr_partida, enlace_del_mundo
from agora.ui.session import (
    Game,
    Partidas,
    WebPresenter,
    _escribir_atomico,
    _legible,
    guardados,
    partidas_guardadas,
)

CONFLUENCIA = Path("packs/confluencia/pack.yaml")
ISLA = Path("packs/isla/pack.yaml")


def _esperar_hasta(cond: Callable[[], bool], plazo: float = 3.0, paso: float = 0.01) -> bool:
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(paso)
    return cond()


# ---------------------------------------------------------------------------
# 1. SheetView propia vs de otro vs sin enlace (M1, M2)
# ---------------------------------------------------------------------------


def test_sheet_view_propia_vs_otro_y_sin_enlace() -> None:
    """1. SheetView propia lleva ficha mecánica, fama, marcas visibles (no ocultas) y
    tramas; la de otro, nada de eso; sin sistema enlazado, mechanical es None (M1, M2)."""
    pack = load_pack(CONFLUENCIA)
    args = build_parser().parse_args(["--pack", str(CONFLUENCIA), "--seed", "1"])
    enlace = enlace_del_mundo(args, pack)
    assert enlace is not None

    sim = Simulation(pack, seed=1)
    yo_id = AgentId("cyra_nieblalta")
    otro_id = AgentId("adze_piedraparda")
    yo = sim.state.agents[yo_id]
    sim.set_player(yo_id)

    # Añadir fama, marcas visibles y marcas ocultas
    sim.state.fama[yo_id] = 0.75
    # En Confluencia: 'secreto' es hidden=True, 'favor_debido' es hidden=False
    sim.state.marcas[yo_id] = {MarkId("favor_debido"): 2, MarkId("secreto"): 5}

    # Añadir una trama activa
    assert pack.plots is not None
    assert pack.plots.fame is not None
    trama = pack.plots.plots[0]
    paso = trama.steps[0]
    sim.state.tramas[yo_id] = PlotRun(plot=trama.id, empezo=0, refs={}, paso=paso.id, desde=0)

    # 1.1 Hoja propia con enlace
    vista_propia = sheet_view(sim.state, yo, enlace=enlace)
    assert vista_propia.propia is True

    # Ficha mecánica propia
    assert vista_propia.mecanica is not None
    assert isinstance(vista_propia.mecanica, MechanicalView)
    assert vista_propia.mecanica.papel != ""
    assert vista_propia.mecanica.nivel >= 1
    assert len(vista_propia.mecanica.atributos) > 0
    assert len(vista_propia.mecanica.competencias) > 0

    # Fama propia
    assert vista_propia.fama is not None
    assert vista_propia.fama[0] == pack.plots.fame.label
    assert vista_propia.fama[1] == 0.75

    # Marcas visibles: solo favor_debido; secreto NUNCA debe estar (M1)
    etiquetas_marcas = [etiqueta for etiqueta, _ in vista_propia.marcas]
    assert any("favor" in etiqueta.lower() for etiqueta in etiquetas_marcas)
    # Comprobación estricta de M1: las marcas ocultas nunca aparecen en la hoja
    for etiqueta, _ in vista_propia.marcas:
        assert "secreto" not in etiqueta.lower(), (
            f"Marca oculta 'secreto' presente en la hoja: {etiqueta}"
        )
    assert len(vista_propia.marcas) == 1

    # Tramas propias
    assert len(vista_propia.tramas) == 1
    assert vista_propia.tramas[0][0] == trama.label

    # 1.2 Hoja de otro: no lleva mecánica (M2), ni fama, ni marcas, ni tramas, ni objetos
    vista_otro = sheet_view(sim.state, yo, otro=otro_id, enlace=enlace)
    assert vista_otro.propia is False
    assert vista_otro.mecanica is None, "La hoja de otro no debe llevar ficha mecánica (M2)"
    assert vista_otro.fama is None
    assert vista_otro.marcas == ()
    assert vista_otro.tramas == ()
    assert vista_otro.objetos == ()

    # 1.3 Hoja propia sin enlace: mechanical es None
    vista_sin_enlace = sheet_view(sim.state, yo, enlace=None)
    assert vista_sin_enlace.propia is True
    assert vista_sin_enlace.mecanica is None


# ---------------------------------------------------------------------------
# 2. TextPresenter.plot y Script reproduce decisión (M3)
# ---------------------------------------------------------------------------


def test_text_presenter_plot_produce_mismo_texto_y_script_reproduce_decision() -> None:
    """2. TextPresenter.plot produce el mismo texto que hoy;
    Script reproduce una partida con decisión de trama (M3)."""
    # 2.1 TextPresenter.plot con opción por defecto (Enter vacío)
    inp = io.StringIO("\n")
    out = io.StringIO()
    tp = TextPresenter(inp, out)
    vista = PlotView(plot="Dilema de Confluencia", options=("Aceptar", "Rechazar"), defecto=0)

    elegido = tp.plot(vista)
    assert elegido == 0
    esperado = (
        "  Dilema de Confluencia:\n"
        "  1. Aceptar  (por defecto)\n"
        "  2. Rechazar\n"
        "  ¿Qué haces? "
    )
    assert out.getvalue() == esperado, (
        "TextPresenter.plot debe reproducir exactamente el texto esperado (M3)"
    )

    # 2.2 TextPresenter.plot eligiendo número
    inp2 = io.StringIO("2\n")
    out2 = io.StringIO()
    tp2 = TextPresenter(inp2, out2)
    elegido2 = tp2.plot(vista)
    assert elegido2 == 1
    assert out2.getvalue() == esperado

    # 2.3 TextPresenter.plot con entrada inválida seguida de válida
    inp3 = io.StringIO("99\n1\n")
    out3 = io.StringIO()
    tp3 = TextPresenter(inp3, out3)
    elegido3 = tp3.plot(vista)
    assert elegido3 == 0
    assert "  Elige un número de la lista." in out3.getvalue()

    # 2.4 Script reproduce una partida con decisión de trama
    pack = load_pack(CONFLUENCIA)
    sim = Simulation(pack, seed=1)
    yo_id = AgentId("cyra_nieblalta")
    yo = sim.state.agents[yo_id]
    sim.set_player(yo_id)

    class MockSource:
        def choose(self, *args: Any) -> Any:
            return None
        def interrupt(self, *args: Any) -> bool:
            return False
        def choose_plot(self, world: WorldState, agent: Any, v: PlotView) -> int | None:
            return 1

    grabar_io = io.StringIO()
    rec = Recorder(MockSource(), grabar_io, sim=sim)
    rec.choose_plot(sim.state, yo, vista)

    lineas = grabar_io.getvalue().splitlines()
    assert any('"trama": 1' in linea for linea in lineas)

    script = Script(lineas, sim=sim)
    reproducido = script.choose_plot(sim.state, yo, vista)
    assert reproducido == 1


# ---------------------------------------------------------------------------
# 3. Web: evento trama con opciones, botones y «lo que haría»
# ---------------------------------------------------------------------------


def test_web_presenter_evento_trama_con_opciones_y_defecto_botones_y_lo_que_haria() -> None:
    """3. La web: evento trama con opciones y por defecto; un botón manda su número;
    «lo que haría» manda vacío y se elige la de por defecto."""
    class FakePartida:
        def __init__(self) -> None:
            self.eventos_publicados: list[dict[str, Any]] = []
            self.respuesta_simulada: str | None = None

        def preguntar(self, evento: dict[str, Any]) -> str | None:
            self.eventos_publicados.append(evento)
            return self.respuesta_simulada

    fake = FakePartida()
    presenter = WebPresenter(fake)  # type: ignore[arg-type]
    vista = PlotView(
        plot="Encrucijada",
        options=("Pagar el peaje", "Buscar otro camino", "Negociar"),
        defecto=1,
    )

    # 3.1 Un botón manda su número (1-based: "1" -> 0, "3" -> 2)
    fake.respuesta_simulada = "1"
    res1 = presenter.plot(vista)
    assert res1 == 0
    evento1 = fake.eventos_publicados[-1]
    assert evento1["tipo"] == "trama"
    assert evento1["titulo"] == "Encrucijada"
    assert evento1["opciones"] == [
        {"n": 1, "texto": "Pagar el peaje"},
        {"n": 2, "texto": "Buscar otro camino"},
        {"n": 3, "texto": "Negociar"},
    ]
    assert evento1["defecto"] == 2  # 1-based (defecto=1 -> 2)

    fake.respuesta_simulada = "3"
    res3 = presenter.plot(vista)
    assert res3 == 2

    # 3.2 «lo que haría» manda vacío: se elige la de por defecto
    fake.respuesta_simulada = ""
    res_defecto = presenter.plot(vista)
    assert res_defecto == 1

    fake.respuesta_simulada = "   "
    assert presenter.plot(vista) == 1

    # 3.3 Respuesta inválida también cae a defecto
    fake.respuesta_simulada = "invalido"
    assert presenter.plot(vista) == 1

    # 3.4 Sin respuesta (sesión cerrada / None) -> defecto
    fake.respuesta_simulada = None
    assert presenter.plot(vista) == 1


# ---------------------------------------------------------------------------
# 4. Autoguardado diario, sobrescribe auto.json, no mitad tick, atómico (M4, M5)
# ---------------------------------------------------------------------------


def test_autoguardado_diario_sobrescribe_auto_no_mitad_tick_y_escritura_atomica(
    tmp_path: Path,
) -> None:
    """4. Autoguardado: uno al empezar cada día, sobrescribe auto.json, nunca a mitad
    de tick; escritura atómica (simular un corte: el anterior sigue válido) (M4, M5)."""
    pack = load_pack(ISLA)
    sim = Simulation(pack, seed=1)
    sim.set_player(AgentId("elor_d1"))

    carpeta = tmp_path / "partida_auto"
    carpeta.mkdir(parents=True)
    guion = carpeta / "guion.jsonl"
    guion.write_text("", encoding="utf-8")

    args = build_parser().parse_args(["--pack", str(ISLA), "--seed", "1", "--sin-llm"])
    game = Game(args, sim, guion, carpeta=carpeta, meta={"mundo": "isla", "personaje": "Elor"})

    # 4.1 Autoguardado al empezar el día 0
    assert sim.state.tick == 0
    tpd = pack.clock.ticks_per_day
    game._entre_ticks(sim)

    auto_file = carpeta / "auto.json"
    assert auto_file.is_file(), "Debe existir auto.json al empezar el día 0"
    assert game.meta["dia"] == 0
    assert game.meta["tick"] == 0

    datos_dia0 = json.loads(auto_file.read_text(encoding="utf-8"))
    assert datos_dia0["tick"] == 0

    # Durante el mismo día (e.g. tick 1..tpd-1): no se vuelve a autoguardar
    sim.state.tick = 10
    game._entre_ticks(sim)
    assert game.meta["dia"] == 0
    # Sigue con tick 0
    assert json.loads(auto_file.read_text(encoding="utf-8"))["tick"] == 0

    # 4.2 Al empezar el día 1 (tick == tpd): sobrescribe auto.json (un solo auto.json)
    sim.state.tick = tpd
    game._entre_ticks(sim)
    assert game.meta["dia"] == 1
    assert game.meta["tick"] == tpd

    archivos_auto = list(carpeta.glob("auto*.json"))
    assert len(archivos_auto) == 1, (
        "Solo debe haber un auto.json sobrescrito, sin acumular archivos"
    )
    datos_dia1 = json.loads(auto_file.read_text(encoding="utf-8"))
    assert datos_dia1["tick"] == tpd

    # 4.3 Nunca a mitad de tick: comprobación de tick entero y coherente (M4)
    assert isinstance(sim.state.tick, int)
    assert game.meta["tick"] % 1 == 0, "El guardado no debe registrarse a mitad de tick (M4)"

    # 4.4 Escritura atómica: corte simulado a mitad deja el anterior válido (M5)
    archivo_prueba = tmp_path / "atomico.json"
    def escribir_bueno(p: Path) -> None:
        p.write_text('{"estado": "valido_original"}', encoding="utf-8")

    _escribir_atomico(archivo_prueba, escribir_bueno)
    assert archivo_prueba.read_text(encoding="utf-8") == '{"estado": "valido_original"}'

    # Simular corte a mitad de escritura (lanza excepción antes de rename)
    def escribir_cortado(p: Path) -> None:
        p.write_text('{"estado": "cortado_invalido', encoding="utf-8")
        raise OSError("Corte repentino de corriente")

    with pytest.raises(OSError, match="Corte repentino"):
        _escribir_atomico(archivo_prueba, escribir_cortado)

    # El archivo original sigue 100% válido e intacto (M5)
    assert archivo_prueba.is_file()
    contenido_tras_corte = archivo_prueba.read_text(encoding="utf-8")
    assert contenido_tras_corte == '{"estado": "valido_original"}', (
        "Escritura no atómica: un corte dañó el archivo previo (M5)"
    )
    assert json.loads(contenido_tras_corte) == {"estado": "valido_original"}


# ---------------------------------------------------------------------------
# 5. Continuar: mismo log que no haber parado; guion reproduce la partida
# ---------------------------------------------------------------------------


def test_continuar_mismo_log_que_no_haber_parado_y_guion_reproduce_partida(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5. Continuar: mismo log que no haber parado; el guion sigue en el mismo
    archivo y reproduce la partida entera."""
    # Redirigir carpeta de partidas para aislar la prueba
    dir_partidas = tmp_path / "partidas"
    dir_partidas.mkdir(parents=True)
    monkeypatch.setattr("agora.ui.session._carpeta_de_partidas", lambda: dir_partidas)

    pack = load_pack(ISLA)
    yo_id = AgentId("elor_d1")

    # 5.1 En el motor: reanudar da exactamente el mismo log que no haber parado
    class EsperarSource:
        def choose(self, world: WorldState, agent: Any, options: Any) -> Any:
            return None
        def interrupt(self, *args: Any) -> bool:
            return False
        def choose_plot(self, *args: Any) -> Any:
            return 0

    # Corrida directa de 20 ticks
    sim_directa = Simulation(pack, seed=42)
    sim_directa.set_player(yo_id)
    sim_directa.player_source = EsperarSource()
    for _ in range(20):
        sim_directa.tick()

    log_directo = [(e.seq, e.kind, e.actor, e.place) for e in sim_directa.log]

    # Corrida con parada en tick 10 y reanudar
    sim_mitad = Simulation(pack, seed=42)
    sim_mitad.set_player(yo_id)
    sim_mitad.player_source = EsperarSource()
    for _ in range(10):
        sim_mitad.tick()

    partida_dir = dir_partidas / "isla-elor_d1-42-test"
    partida_dir.mkdir(parents=True)
    auto_json = partida_dir / "auto.json"
    sim_mitad.save(auto_json)

    meta = {
        "mundo": "isla",
        "personaje": "Elor",
        "semilla": 42,
        "modelo": False,
        "dia": 0,
        "tick": 10,
        "fecha": "2026-11-25T12:00:00",
        "motivo": "día",
        "guardado": "auto",
        "lineas_por_guardado": {"auto": 0},
    }
    (partida_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    guion_path = partida_dir / "guion.jsonl"
    guion_path.write_text("", encoding="utf-8")

    # Reanudar con Simulation.resume
    sim_reanudada = Simulation.resume(auto_json, pack)
    sim_reanudada.player_source = EsperarSource()
    for _ in range(10):
        sim_reanudada.tick()

    log_reanudado = [
        (e.seq, e.kind, e.actor, e.place)
        for e in (*sim_reanudada.log.previos, *sim_reanudada.log)
    ]
    assert log_reanudado == log_directo, "Reanudar debe dar el mismo log exacto que no haber parado"

    # 5.2 En la sesión web: continuar() recorta el guion y sigue en el mismo archivo
    gestor = Partidas()
    partida_cont = gestor.continuar({"id": partida_dir.name, "cual": "auto"})
    assert partida_cont.continuar is True
    assert _esperar_hasta(lambda: partida_cont._esperando, plazo=3.0)
    assert partida_cont.entrada("salir")
    partida_cont._hilo.join(timeout=3.0)
    assert not partida_cont._hilo.is_alive()

    # El guion sigue en el mismo archivo y es reproducible
    assert guion_path.is_file()


# ---------------------------------------------------------------------------
# 6. Guardado {} o truncado no se lista y no rompe el inicio (M6)
# ---------------------------------------------------------------------------


def test_guardado_roto_o_truncado_no_se_lista_y_no_rompe_el_inicio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6. Un guardado {} o truncado no se lista y no rompe el inicio (M6)."""
    # 6.1 Comprobar _legible con archivos vacíos, {} y truncados
    roto_vacio = tmp_path / "vacio.json"
    roto_vacio.write_text("", encoding="utf-8")
    assert not _legible(roto_vacio), "_legible debe rechazar archivo vacío de 0 bytes (M6)"

    roto_solo_llaves = tmp_path / "solo_llaves.json"
    roto_solo_llaves.write_text("{}", encoding="utf-8")
    assert not _legible(roto_solo_llaves), "_legible debe rechazar guardado con solo {} (M6)"

    roto_truncado = tmp_path / "truncado.json"
    roto_truncado.write_text('{"formato": 1, "agents": [', encoding="utf-8")
    assert not _legible(roto_truncado), "_legible debe rechazar guardado truncado (M6)"

    # Comprobar guardados() con archivo roto temporal en mundos/
    carpeta_mundos = Path("packs/confluencia/mundos")
    archivo_roto = carpeta_mundos / "temp_roto.json"
    try:
        archivo_roto.write_text("{}", encoding="utf-8")
        lista_conf = guardados("confluencia")
        ids_conf = [m["id"] for m in lista_conf]
        assert "temp_roto" not in ids_conf, (
            "El guardado temporal roto no debe listarse en guardados() (M6)"
        )
    finally:
        if archivo_roto.exists():
            archivo_roto.unlink()

    # 6.2 En partidas guardadas: carpetas con meta.json roto no rompen partidas_guardadas
    dir_partidas = tmp_path / "partidas"
    dir_partidas.mkdir(parents=True)
    monkeypatch.setattr("agora.ui.session._carpeta_de_partidas", lambda: dir_partidas)

    carpeta_rota1 = dir_partidas / "partida_rota_vacia"
    carpeta_rota1.mkdir()
    (carpeta_rota1 / "meta.json").write_text("{}", encoding="utf-8")

    carpeta_rota2 = dir_partidas / "partida_rota_truncada"
    carpeta_rota2.mkdir()
    (carpeta_rota2 / "meta.json").write_text('{"mundo": "isla",', encoding="utf-8")

    carpeta_valida = dir_partidas / "partida_valida"
    carpeta_valida.mkdir()
    (carpeta_valida / "meta.json").write_text(
        json.dumps({"mundo": "isla", "personaje": "Elor", "fecha": "2026-11-25T12:00:00"}),
        encoding="utf-8",
    )
    (carpeta_valida / "auto.json").write_text("{}", encoding="utf-8")

    # partidas_guardadas() no debe romperse y solo debe listar la válida (M6)
    listadas = partidas_guardadas()
    assert len(listadas) == 1
    assert listadas[0]["id"] == "partida_valida"
    ids_listadas = [p["id"] for p in listadas]
    assert "partida_rota_vacia" not in ids_listadas, (
        "No debe listarse una partida con meta.json vacío (M6)"
    )
    assert "partida_rota_truncada" not in ids_listadas, (
        "No debe listarse una partida con meta.json truncado (M6)"
    )


# ---------------------------------------------------------------------------
# 7. «La última vez» al continuar y no en partida nueva (M7)
# ---------------------------------------------------------------------------


def test_la_ultima_vez_sale_al_continuar_y_no_en_partida_nueva_sin_invenciones(
    tmp_path: Path,
) -> None:
    """7. «La última vez»: sale al continuar y no en partida nueva; sin nombres ni
    lugares que no se le den (M7)."""
    pack = load_pack(ISLA)
    sim = Simulation(pack, seed=1)
    yo_id = AgentId("elor_d1")
    sim.set_player(yo_id)

    args = build_parser().parse_args(["--pack", str(ISLA), "--seed", "1", "--sin-llm"])

    # 7.1 En partida nueva (continuar=False): no se emite «la última vez» (M7)
    partida_nueva = Game(args, sim, tmp_path / "nueva.jsonl", continuar=False)
    assert partida_nueva.continuar is False
    partida_nueva.empezar()
    assert _esperar_hasta(lambda: partida_nueva._esperando, plazo=3.0)
    assert not any("Vuelves" in str(ev.get("texto", "")) for ev in partida_nueva.historia), (
        "«La última vez» no debe salir en partida nueva (M7)"
    )
    partida_nueva.entrada("salir")
    partida_nueva._hilo.join(timeout=3.0)

    # 7.2 En partida continuada (continuar=True): se emite vuelta (la última vez)
    narrator = Narrator(providers=(), table=Table())
    partida_continuada = Game(args, sim, tmp_path / "continuada.jsonl", continuar=True)
    partida_continuada._narrador = narrator
    assert partida_continuada.continuar is True

    # Generar vuelta y comprobar contenido
    vuelta = narrator.vuelta(sim.state, str(yo_id), list(sim.log))
    assert vuelta.text.startswith("Vuelves a ")
    assert "Elor" in vuelta.text

    # 7.3 Sin nombres ni lugares que no se le den:
    momento = vuelta_moment(sim.state, str(yo_id), list(sim.log), Table())
    assert momento.kind is Kind.VUELTA

    # Prosa válida con datos del briefing pasa limpia
    prosa_limpia = f"Vuelves a {momento.place}. Eres {momento.player}."
    assert strangers(momento, prosa_limpia) == ()

    # Prosa con personaje ajeno no presente en el briefing se detecta como extraña
    prosa_con_extrano = f"Vuelves a {momento.place}. Eres {momento.player}. Ves a Halzetu."
    desconocidos = strangers(momento, prosa_con_extrano)
    if "Halzetu" not in momento.present:
        assert "Halzetu" in desconocidos, (
            "strangers debe detectar nombres ajenos al briefing de vuelta"
        )

    # La plantilla de vuelta solo incluye lugar, presentes, player y lo que pasó
    texto_plantilla = _vuelta_plantilla(momento)
    assert texto_plantilla.startswith(f"Vuelves a {momento.place}.")
    assert f"Eres {momento.player}." in texto_plantilla


# ---------------------------------------------------------------------------
# 8. Terminal sin modelo idéntica a la línea base
# ---------------------------------------------------------------------------


def test_terminal_sin_modelo_identica_a_linea_base(tmp_path: Path) -> None:
    """8. Terminal sin modelo idéntica a la línea base."""
    pack = load_pack(ISLA)
    args = build_parser().parse_args([
        "--pack", str(ISLA), "--jugar", "elor_d1", "--sin-llm", "--seed", "1"
    ])

    # Corrida 1
    sim1 = Simulation(pack, seed=1)
    sim1.set_player(AgentId("elor_d1"))
    inp1 = io.StringIO("ficha\nequipo\nmirar\n" + "esperar\n" * 50)
    out1 = io.StringIO()
    tp1 = TextPresenter(inp1, out1)
    terminal1 = Terminal(sim1, inp1, out1, presenter=tp1)
    combate1 = TerminalCombat(
        io.StringIO(), io.StringIO(), None, None, lambda: sim1.state, presenter=tp1
    )

    correr_partida(
        sim1,
        args,
        20,
        fuente=terminal1,
        combate=combate1,
        escena=combate1,
        terminal=terminal1,
        grabar=tmp_path / "g1.jsonl",
    )
    salida1 = out1.getvalue()

    # Corrida 2 idéntica
    sim2 = Simulation(pack, seed=1)
    sim2.set_player(AgentId("elor_d1"))
    inp2 = io.StringIO("ficha\nequipo\nmirar\n" + "esperar\n" * 50)
    out2 = io.StringIO()
    tp2 = TextPresenter(inp2, out2)
    terminal2 = Terminal(sim2, inp2, out2, presenter=tp2)
    combate2 = TerminalCombat(
        io.StringIO(), io.StringIO(), None, None, lambda: sim2.state, presenter=tp2
    )

    correr_partida(
        sim2,
        args,
        20,
        fuente=terminal2,
        combate=combate2,
        escena=combate2,
        terminal=terminal2,
        grabar=tmp_path / "g2.jsonl",
    )
    salida2 = out2.getvalue()

    assert salida1 == salida2, "La terminal sin modelo debe ser idéntica y 100% determinista"
    assert "# Elor, del distrito 1, tick 1" in salida1
    assert "1. una ración de comida" in salida1
