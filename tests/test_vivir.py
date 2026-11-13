"""Pruebas del piloto automático y lo que devuelve el control (unidad 21b, §B).

Verifica:
- B.1 Elegir:
  - B.1.1: decide y choose_among(options) dan lo mismo para un NPC (muchos ticks).
  - B.1.2: El piloto nunca elige opción con destinatario; sin opciones libres, espera.
  - B.1.3: Misma semilla, mismas elecciones del piloto; con Script, mismo log.
- B.2 Interrupciones:
  - B.2.1: Cada motivo de A.3 quita el piloto con su aviso; desconocido no lo quita.
  - B.2.2: vivir 2 vuelve a las 8 decisiones; vivir hasta mañana, al nuevo día.
  - B.2.3: Necesidad crítica: se quita el piloto y se pregunta como hoy.
  - B.2.4: Mientras se vive, terminal no escribe; status una vez por hora.
- B.3 Web:
  - B.3.1: POST /api/parar durante un vivir quita el piloto en el siguiente choose.
"""

from __future__ import annotations

import http.client
import io
import json
import math
import threading
import time
from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import pytest

from agora.agents.decide import Decision, choose_among, decide, options
from agora.cognition.narrador import Told
from agora.engine.events import EventKind
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import ActionId, AgentId
from agora.engine.pack import load_pack
from agora.engine.state import Bond
from agora.engine.world import Simulation
from agora.play import Piloto, Recorder, Script, Terminal, conoce, play
from agora.present import FighterView, Presenter, RollView, SheetView
from agora.ui.server import Servidor

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
FORASTERO_SHEET = Path("packs/confluencia/forastero.yaml")


def _piloto_de(terminal: Terminal) -> Piloto | None:
    """Acceso al piloto de la terminal evitando estrechamiento de tipos en mypy."""
    return terminal.piloto


class GrabadorPresenter(Presenter):
    """Presentador para capturar llamadas de notas, estados, preguntas y avisos."""

    def __init__(self, ask_input: str = "esperar\n") -> None:
        self.calls: list[tuple[str, Any]] = []
        self.notes: list[str] = []
        self.statuses: list[SheetView] = []
        self.ask_inputs = [ask_input] if isinstance(ask_input, str) else list(ask_input)

    def turn(self, nombre: str, tick: int) -> None:
        self.calls.append(("turn", (nombre, tick)))

    def told(self, told: Told, chain: bool) -> None:
        self.calls.append(("told", (told, chain)))

    def event(self, texto: str) -> None:
        self.calls.append(("event", texto))

    def note(self, texto: str) -> None:
        self.calls.append(("note", texto))
        self.notes.append(texto)

    def prompt(self, atajos: Sequence[str]) -> None:
        self.calls.append(("prompt", tuple(atajos)))

    def options(self, items: Sequence[tuple[int, str]]) -> None:
        self.calls.append(("options", tuple(items)))

    def people(self, items: Sequence[tuple[int, str, str]]) -> None:
        self.calls.append(("people", tuple(items)))

    def look(self, cabecera: str, filas: Sequence[tuple[str, str, str]]) -> None:
        self.calls.append(("look", (cabecera, tuple(filas))))

    def sheet(self, vista: SheetView) -> None:
        self.calls.append(("sheet", vista))

    def status(self, vista: SheetView) -> None:
        self.calls.append(("status", vista))
        self.statuses.append(vista)

    def speech(self, quien: str, dice: str, tono: str, respaldo: bool) -> None:
        self.calls.append(("speech", (quien, dice, tono, respaldo)))

    def roll(self, vista: RollView) -> None:
        self.calls.append(("roll", vista))

    def fighters(self, filas: Sequence[FighterView]) -> None:
        self.calls.append(("fighters", tuple(filas)))

    def beat(self, texto: str) -> None:
        self.calls.append(("beat", texto))

    def ended(self, razon: str, ticks: int, lineas: Sequence[str]) -> None:
        self.calls.append(("ended", (razon, ticks, tuple(lineas))))

    def ask(self, texto: str) -> str:
        self.calls.append(("ask", texto))
        if self.ask_inputs:
            return self.ask_inputs.pop(0)
        return ""

    def pick(self, pregunta: str, textos: Sequence[str]) -> int | None:
        self.calls.append(("pick", (pregunta, tuple(textos))))
        return None

    def confirm(self, texto: str) -> bool:
        self.calls.append(("confirm", texto))
        return True

    def yes_no(self, pregunta: str, defecto: bool) -> bool:
        self.calls.append(("yes_no", (pregunta, defecto)))
        return defecto


@pytest.fixture
def servidor_local() -> Generator[tuple[Servidor, int], None, None]:
    servidor = Servidor(0)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield servidor, puerto
    finally:
        if servidor.partidas.actual is not None:
            servidor.partidas.actual.cerrar()
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=2.0)


# ---------------------------------------------------------------------------
# B.1 — Elegir
# ---------------------------------------------------------------------------


def test_b11_decide_y_choose_among_dan_lo_mismo_para_npc_muchos_ticks() -> None:
    """B.1.1: decide y choose_among(options) dan lo mismo para un NPC (muchos ticks),
    y choose_among consume el stream canónico ('decide', agente, tick)."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=42)
    ticks_probados = 0
    ticks_con_sorteo = 0
    for _ in range(30):
        world = sim.state
        for agent in world.agents_in_order():
            opts = options(world, agent)
            if not opts:
                continue
            ticks_probados += 1
            d_decide = decide(world, agent)
            d_choose = choose_among(world, agent, opts)
            assert d_decide == d_choose, (
                f"Tick {world.tick}, {agent.spec_id}: decide != choose_among"
            )

            # Verificar contra el cálculo exacto usando el stream canónico ("decide", agent, tick)
            finalists = opts[: world.pack.tuning.candidate_pool]
            if len(finalists) > 1:
                ticks_con_sorteo += 1
                best = finalists[0].utility
                temp = agent.temperament.temperature
                weights = [math.exp((d.utility - best) / temp) for d in finalists]
                expected = world.rng.stream("decide", agent.spec_id, world.tick).choices(
                    finalists, weights=weights, k=1
                )[0]
                assert d_choose == expected, (
                    f"choose_among no usó stream canónico: {d_choose} vs {expected}"
                )
        sim.tick()

    assert ticks_probados > 50
    assert ticks_con_sorteo > 20


def test_b12_piloto_nunca_elige_con_destinatario_y_espera_si_no_hay_libres() -> None:
    """B.1.2: El piloto nunca elige una opción con destinatario; sin opciones sin destinatario,
    espera (devuelve None)."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=10)
    agent = sim.state.agents_in_order()[0]
    otro_id = sim.state.agents_in_order()[1].spec_id

    terminal = Terminal(sim, io.StringIO(), io.StringIO())
    terminal.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    # 1. Menú con opción dirigida con utilidad altísima y opción libre con utilidad baja
    act_dirigida = (
        ActionId("atacar")
        if "atacar" in pack.action_by_id
        else next(iter(pack.action_by_id.keys()))
    )
    act_libre = (
        ActionId("descansar")
        if "descansar" in pack.action_by_id
        else next(iter(pack.action_by_id.keys()))
    )
    p1 = agent.at

    opt_dirigida = Decision(act_dirigida, p1, utility=100.0, travel_ticks=0, target=otro_id)
    opt_libre = Decision(act_libre, p1, utility=1.0, travel_ticks=0, target=None)
    opts = (opt_dirigida, opt_libre)

    # El piloto debe descartar la dirigida y elegir la libre
    for _ in range(10):
        activo, elegida = terminal._piloto(sim.state, agent, opts)
        assert activo is True
        assert elegida is not None
        assert elegida.target is None, f"El piloto eligió una opción con destinatario: {elegida}"
        assert elegida.action == act_libre

    # 2. Menú únicamente con opciones dirigidas: debe esperar (devolver None)
    opts_solo_dirigidas = (opt_dirigida,)
    activo, elegida_vacia = terminal._piloto(sim.state, agent, opts_solo_dirigidas)
    assert activo is True
    assert elegida_vacia is None, (
        f"Sin opciones libres el piloto debía esperar (None), pero devolvió {elegida_vacia}"
    )


def test_b13_piloto_reproducible_y_mismo_log_con_script(tmp_path: Path) -> None:
    """B.1.3: Misma semilla, mismas elecciones del piloto; reproducido con Script, mismo log."""
    pack = load_pack(CONFLUENCIA_PACK)
    sheet = load_sheet(FORASTERO_SHEET)

    # 1. Partida con piloto automático grabada con Recorder
    sim1 = Simulation(pack, seed=777)
    spec1 = newcomer_spec(pack, sheet, sim1.state.censo)
    sim1.arrive(spec1)
    sim1.set_player(spec1.id)

    term1 = Terminal(sim1, io.StringIO("vivir\n"), io.StringIO())
    guion_path = tmp_path / "piloto.jsonl"
    with guion_path.open("w", encoding="utf-8") as f:
        rec = Recorder(term1, f, sim=sim1)
        res1 = play(sim1, rec, 48)

    assert res1.ticks == 48
    lineas = guion_path.read_text(encoding="utf-8").splitlines()
    assert len(lineas) > 0, "Recorder debió grabar las decisiones del piloto"

    # 2. Reproducir con Script en una simulación idéntica
    sim2 = Simulation(pack, seed=777)
    spec2 = newcomer_spec(pack, sheet, sim2.state.censo)
    sim2.arrive(spec2)
    sim2.set_player(spec2.id)

    guion = Script(lineas, sim=sim2)
    res2 = play(sim2, guion, 48)

    assert res2.ticks == 48
    assert list(sim1.log) == list(sim2.log), "Reproducir con Script debe dar el mismo log"

    # 3. Otra ejecución con piloto y misma semilla: idéntico log
    sim3 = Simulation(pack, seed=777)
    spec3 = newcomer_spec(pack, sheet, sim3.state.censo)
    sim3.arrive(spec3)
    sim3.set_player(spec3.id)
    term3 = Terminal(sim3, io.StringIO("vivir\n"), io.StringIO())
    res3 = play(sim3, term3, 48)

    assert res3.ticks == 48
    assert list(sim1.log) == list(sim3.log), "Misma semilla debe dar las mismas elecciones y log"


# ---------------------------------------------------------------------------
# B.2 — Interrupciones
# ---------------------------------------------------------------------------


def test_b21_cada_motivo_de_a3_quita_piloto_con_aviso_y_desconocido_no() -> None:
    """B.2.1: Cada motivo de A.3 quita el piloto con su aviso; un evento de un desconocido
    no lo quita. Conocer sin mirar aprecio debe fallar para alguien conocido solo por aprecio."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=123)

    yo_agent = sim.state.agents_in_order()[0]
    yo = yo_agent.spec_id
    sim.set_player(yo)

    amigo = sim.state.agents_in_order()[1].spec_id
    desconocido = sim.state.agents_in_order()[2].spec_id

    # yo siente aprecio 0.5 hacia amigo, 0.0 hacia desconocido
    # Asegurar que no hay relación con nombre entre yo y amigo
    assert not yo_agent.related_to(amigo)
    yo_agent.bonds[amigo] = Bond(regard=0.5, encounters=1)
    yo_agent.bonds[desconocido] = Bond(regard=0.0, encounters=0)

    # Verificar que conoce(world, yo_agent, amigo) es True por aprecio
    assert conoce(sim.state, yo_agent, amigo) is True
    assert conoce(sim.state, yo_agent, desconocido) is False

    nombre_amigo = sim.state.censo[amigo].label
    nombre_desconocido = sim.state.censo[desconocido].label
    rel_id = next(iter(pack.relations)).id
    rel_label = pack.relation_by_id[rel_id].label

    p1 = yo_agent.at
    dummy_opts = (
        Decision(
            next(iter(pack.action_by_id.keys())), p1, utility=1.0, travel_ticks=0, target=None
        ),
    )

    def probar_evento(
        *,
        kind: EventKind,
        actor: AgentId | None = None,
        subject: AgentId | None = None,
        data: dict[str, Any] | None = None,
        debe_interrumpir: bool,
        texto_aviso: str = "",
    ) -> None:
        p = GrabadorPresenter()
        term = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p)
        term.piloto = Piloto(hasta_tick=None, texto_limite="", visto=sim.log.siguiente_seq)
        sim.log.emit(
            tick=sim.state.tick,
            kind=kind,
            actor=actor,
            subject=subject,
            place=p1,
            data={} if data is None else data,
        )
        activo, _ = term._piloto(sim.state, yo_agent, dummy_opts)
        if debe_interrumpir:
            assert activo is False, f"El evento {kind} debía quitar el piloto"
            assert _piloto_de(term) is None, f"El piloto debía quedar None tras {kind}"
            assert any(texto_aviso in nota for nota in p.notes), (
                f"El aviso debía contener '{texto_aviso}', pero se emitió {p.notes}"
            )
        else:
            assert activo is True, f"El evento de desconocido {kind} no debía interrumpir"
            assert _piloto_de(term) is not None, "El piloto debía seguir activo"

    # 1. Se dirigen a ti: ACTION_STARTED con data["target"] == yo
    probar_evento(
        kind=EventKind.ACTION_STARTED,
        actor=amigo,
        data={"target": str(yo)},
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: {nombre_amigo} se dirige a ti.",
    )

    # 2. Se dirigen a ti: SOCIAL_ACT con subject == yo
    probar_evento(
        kind=EventKind.SOCIAL_ACT,
        actor=amigo,
        subject=yo,
        data={"act": "saludar"},
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: {nombre_amigo} te habla.",
    )

    # 3. Llega alguien que conoces: ENCOUNTER con actor == yo, subject == amigo
    # (amigo es conocido SOLO por aprecio: si M3 quita el aprecio, esto falla)
    probar_evento(
        kind=EventKind.ENCOUNTER,
        actor=yo,
        subject=amigo,
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: llega {nombre_amigo}.",
    )

    # 4. Algo de tu gente: AGENT_DIED de alguien que conoces
    probar_evento(
        kind=EventKind.AGENT_DIED,
        subject=amigo,
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: ha muerto {nombre_amigo}.",
    )

    # 5. Algo de tu gente: AGENT_BORN de alguien que conoces
    probar_evento(
        kind=EventKind.AGENT_BORN,
        actor=amigo,
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: ha nacido {nombre_amigo}.",
    )

    # 6. Algo de tu gente: RELATION_BEGAN con alguien que conoces
    probar_evento(
        kind=EventKind.RELATION_BEGAN,
        actor=amigo,
        subject=desconocido,
        data={"relation": str(rel_id)},
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: {nombre_amigo} y {nombre_desconocido} son ahora {rel_label}.",
    )

    # 7. Algo de tu gente: RELATION_ENDED con alguien que conoces
    probar_evento(
        kind=EventKind.RELATION_ENDED,
        actor=amigo,
        subject=desconocido,
        data={"relation": str(rel_id)},
        debe_interrumpir=True,
        texto_aviso=f"Vuelves en ti: {nombre_amigo} y {nombre_desconocido} ya no son {rel_label}.",
    )

    # --- Eventos de desconocido: NO interrumpen ---

    # 8. ENCOUNTER con desconocido
    probar_evento(
        kind=EventKind.ENCOUNTER,
        actor=yo,
        subject=desconocido,
        debe_interrumpir=False,
    )

    # 9. AGENT_DIED de desconocido
    probar_evento(
        kind=EventKind.AGENT_DIED,
        subject=desconocido,
        debe_interrumpir=False,
    )

    # 10. AGENT_BORN de desconocido
    probar_evento(
        kind=EventKind.AGENT_BORN,
        actor=desconocido,
        debe_interrumpir=False,
    )

    # 11. RELATION_BEGAN entre dos desconocidos
    otro_desc = sim.state.agents_in_order()[3].spec_id
    probar_evento(
        kind=EventKind.RELATION_BEGAN,
        actor=desconocido,
        subject=otro_desc,
        data={"relation": str(rel_id)},
        debe_interrumpir=False,
    )


def test_b22_vivir_tiempo_limite_vuelve_a_las_horas_o_manana_o_motivo_antes() -> None:
    """B.2.2: 'vivir 2' vuelve tras 8 decisiones de cuarto de hora (o al primer motivo antes);
    'vivir hasta mañana', al comienzo del día siguiente. Ignorar hasta_tick debe enrojecer."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=42)
    yo_agent = sim.state.agents_in_order()[0]
    yo = yo_agent.spec_id
    sim.set_player(yo)
    p1 = yo_agent.at
    dummy_opts = (
        Decision(
            next(iter(pack.action_by_id.keys())), p1, utility=1.0, travel_ticks=0, target=None
        ),
    )

    # 1. 'vivir 2': 2 horas con ticks de 15 min son 8 ticks
    p_grabador = GrabadorPresenter(ask_input="vivir 2\n")
    term = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p_grabador)
    assert sim.state.tick == 0
    elegida = term.choose(sim.state, yo_agent, dummy_opts)
    assert elegida is not None
    assert term.piloto is not None
    assert term.piloto.hasta_tick == 8
    assert term.piloto.texto_limite == "ya ha pasado el tiempo que pediste"

    # Avanzar los 7 ticks intermedios (tick 1 a 7): el piloto sigue activo
    for t in range(1, 8):
        sim.state.tick = t
        activo, _ = term._piloto(sim.state, yo_agent, dummy_opts)
        assert activo is True, f"En tick {t} (< 8) el piloto debía seguir activo"
        assert term.piloto is not None

    # Al llegar al tick 8: se cumplió hasta_tick, se quita el piloto con su aviso
    sim.state.tick = 8
    activo, _ = term._piloto(sim.state, yo_agent, dummy_opts)
    assert activo is False, "En tick 8 (hasta_tick) el piloto debe devolver el control"
    assert _piloto_de(term) is None
    assert any("ya ha pasado el tiempo que pediste" in n for n in p_grabador.notes)

    # 2. 'vivir 2' pero con interrupción antes (en tick 3)
    p_grabador2 = GrabadorPresenter(ask_input="vivir 2\n")
    term2 = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p_grabador2)
    sim.state.tick = 0
    term2.choose(sim.state, yo_agent, dummy_opts)
    assert term2.piloto is not None
    assert term2.piloto.hasta_tick == 8

    # En tick 3 ocurre un evento que interrumpe (alguien te habla)
    sim.state.tick = 3
    otro = sim.state.agents_in_order()[1].spec_id
    sim.log.emit(
        tick=3, kind=EventKind.SOCIAL_ACT, actor=otro, subject=yo, place=p1, data={"act": "saludar"}
    )
    activo, _ = term2._piloto(sim.state, yo_agent, dummy_opts)
    assert activo is False, "El evento en tick 3 debía interrumpir antes de llegar a las 2 horas"
    assert _piloto_de(term2) is None
    assert any("te habla" in n for n in p_grabador2.notes)

    # 3. 'vivir hasta mañana': se para al comienzo del día siguiente
    p_grabador3 = GrabadorPresenter(ask_input="vivir hasta mañana\n")
    term3 = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p_grabador3)
    sim.state.tick = 10
    siguiente_dia = pack.clock.ticks_per_day  # 96
    term3.choose(sim.state, yo_agent, dummy_opts)
    assert term3.piloto is not None
    assert term3.piloto.hasta_tick == siguiente_dia
    assert term3.piloto.texto_limite == "es de mañana"

    # En tick 95 sigue activo
    sim.state.tick = 95
    activo, _ = term3._piloto(sim.state, yo_agent, dummy_opts)
    assert activo is True
    assert term3.piloto is not None

    # En tick 96 (comienzo del día) se quita con aviso "es de mañana"
    sim.state.tick = 96
    activo, _ = term3._piloto(sim.state, yo_agent, dummy_opts)
    assert activo is False, "En el tick de la mañana el piloto debe devolver el control"
    assert _piloto_de(term3) is None
    assert any("es de mañana" in n for n in p_grabador3.notes)


def test_b23_necesidad_critica_quita_piloto_y_pregunta() -> None:
    """B.2.3: Necesidad crítica: se quita el piloto y se pregunta como hoy."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=42)
    yo_agent = sim.state.agents_in_order()[0]
    yo = yo_agent.spec_id
    sim.set_player(yo)
    need = next(n.id for n in pack.needs if n.can_be_critical)
    etiqueta = pack.need_by_id[need].label

    # Preparar Terminal con piloto activo y entrada para ask ("s")
    p = GrabadorPresenter(ask_input="s\n")
    term = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p)
    term.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    # interrupt se llama al detectar necesidad crítica
    dejar = term.interrupt(sim.state, yo_agent, need)

    assert _piloto_de(term) is None, "interrupt() debe poner term.piloto a None (M5)"
    assert any(
        "te falta" in llamada[1] and etiqueta in llamada[1]
        for llamada in p.calls
        if llamada[0] == "ask"
    )
    assert dejar is True

    # También si la rutina del piloto no tiene acciones que atiendan la necesidad crítica:
    # _motivo_de_vuelta quita el piloto con motivo "te falta <necesidad> de verdad"
    p2 = GrabadorPresenter()
    term2 = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p2)
    term2.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    # Colocar la necesidad en crítico (< threshold, ej. 0.0)
    yo_agent.needs[need] = 0.0
    p1 = yo_agent.at
    # Buscar una acción que NO satisfaga 'need'
    act_sin_satisfacer = next(
        act_id for act_id, act in pack.action_by_id.items() if act.satisfies.get(need, 0.0) == 0.0
    )
    dummy_opts_sin = (Decision(act_sin_satisfacer, p1, utility=1.0, travel_ticks=0, target=None),)

    activo, _ = term2._piloto(sim.state, yo_agent, dummy_opts_sin)
    assert activo is False, "Necesidad crítica sin satisfacción en la rutina debe quitar el piloto"
    assert _piloto_de(term2) is None
    assert any(f"te falta {etiqueta} de verdad" in n for n in p2.notes)


def test_b24_mientras_se_vive_terminal_no_escribe_y_status_por_hora() -> None:
    """B.2.4: Mientras se vive, la terminal no escribe nada; el presentador recibe status
    una vez por hora de juego."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=42)
    yo_agent = sim.state.agents_in_order()[0]
    yo = yo_agent.spec_id
    sim.set_player(yo)

    inp = io.StringIO()
    out = io.StringIO()
    # 1. TextPresenter con out: verificar que la terminal no escribe nada
    term = Terminal(sim, inp, out)
    term.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    p1 = yo_agent.at
    dummy_opts = (
        Decision(
            next(iter(pack.action_by_id.keys())), p1, utility=1.0, travel_ticks=0, target=None
        ),
    )

    for t in range(9):
        sim.state.tick = t
        term.choose(sim.state, yo_agent, dummy_opts)

    assert not out.getvalue(), f"Terminal no debía escribir nada: {out.getvalue()!r}"

    # 2. El presentador recibe status una vez por hora de juego (ticks 0, 4, 8)
    p_grabador = GrabadorPresenter()
    term_grabador = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p_grabador)
    term_grabador.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    for t in range(9):
        sim.state.tick = t
        term_grabador.choose(sim.state, yo_agent, dummy_opts)

    llamadas_status = [call for call in p_grabador.calls if call[0] == "status"]
    assert len(llamadas_status) == 3, (
        f"Debía haber 3 llamadas a status (una por hora), hubo {len(llamadas_status)}"
    )


# ---------------------------------------------------------------------------
# B.3 — Web
# ---------------------------------------------------------------------------


def test_b31_post_api_parar_durante_vivir_quita_piloto_con_motivo_paras(
    servidor_local: tuple[Servidor, int],
) -> None:
    """B.3.1: POST /api/parar durante un vivir quita el piloto en el siguiente choose
    con el motivo 'paras'. Ignorar la bandera de parar debe enrojecer."""
    servidor, puerto = servidor_local

    # 1. Prueba directa sobre Terminal con parada (Event)
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=42)
    yo_agent = sim.state.agents_in_order()[0]
    sim.set_player(yo_agent.spec_id)
    p1 = yo_agent.at
    dummy_opts = (
        Decision(
            next(iter(pack.action_by_id.keys())), p1, utility=1.0, travel_ticks=0, target=None
        ),
    )

    parada = threading.Event()
    p_grabador = GrabadorPresenter()
    term = Terminal(sim, io.StringIO(), io.StringIO(), presenter=p_grabador, parada=parada)
    term.piloto = Piloto(hasta_tick=None, texto_limite="", visto=0)

    # Activar la bandera de parada (como hace POST /api/parar)
    parada.set()

    # En el siguiente choose/_piloto:
    activo, _ = term._piloto(sim.state, yo_agent, dummy_opts)
    assert activo is False, "La bandera de parada debía quitar el piloto en el siguiente choose"
    assert _piloto_de(term) is None, "El piloto debe quedar en None tras parada"
    assert parada.is_set() is False, "La bandera de parada debe quedar limpia tras usarse"
    assert any("Vuelves en ti: paras." in n for n in p_grabador.notes), (
        f"El aviso debía ser 'Vuelves en ti: paras.', se obtuvo: {p_grabador.notes}"
    )

    # 2. Prueba HTTP completa contra el servidor
    # Sin partida: /api/parar devuelve 409
    conn = http.client.HTTPConnection("127.0.0.1", puerto)
    conn.request("POST", "/api/parar", body=b"{}", headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 409
    resp.read()

    # Empezar una partida en la web
    cuerpo_partida = json.dumps({
        "mundo": "isla",
        "personaje": "elor_d1",
        "semilla": 1,
        "modelo": False,
    }).encode("utf-8")
    conn.request(
        "POST", "/api/partida", body=cuerpo_partida, headers={"Content-Type": "application/json"}
    )
    resp = conn.getresponse()
    assert resp.status == 200
    resp.read()

    partida = servidor.partidas.actual
    assert partida is not None

    def esperando(g: Any) -> bool:
        return bool(g._esperando)

    def cerrada(g: Any) -> bool:
        return bool(g.cerrada)

    limite = time.monotonic() + 3.0
    while time.monotonic() < limite and not esperando(partida):
        time.sleep(0.02)
    assert esperando(partida) is True

    # Enviar 'vivir' para que arranque el piloto
    conn.request(
        "POST",
        "/api/entrada",
        body=json.dumps({"texto": "vivir"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    resp.read()

    # Llamar a POST /api/parar
    conn.request("POST", "/api/parar", body=b"{}", headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200
    datos = json.loads(resp.read().decode())
    assert datos.get("ok") is True

    # Verificar que la partida vuelve a pedir entrada y el aviso contiene 'paras'
    limite = time.monotonic() + 10.0
    while time.monotonic() < limite and not esperando(partida) and not cerrada(partida):
        time.sleep(0.05)
    assert esperando(partida) is True, "La partida debió detener el piloto y volver a pedir entrada"

    avisos = [ev.get("texto", "") for ev in partida.historia if ev.get("tipo") == "aviso"]
    assert any("paras" in a for a in avisos), f"Debía haber un aviso con 'paras', avisos: {avisos}"
