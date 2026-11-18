"""Pruebas del presentador y la narración en prosa (unidad 20a, §B).

Verifica:
- B.1 Idéntico:
  - B.1.1: Salida de TextPresenter con opciones, diálogo (sangría en options `  N. texto`).
  - B.1.2: Grabador recibe: `turn`, `status`, `told` o `event`, `prompt`, en ese orden.
  - B.1.3: `status` se llama cada turno sin pedir ficha; `TextPresenter.status()` no escribe.
- B.2 Vistas:
  - B.2.1: `SheetView`: necesidades en orden del pack, valores en [0, 1], crítica con umbral.
    Objetos numerados como `equipar N` (1-indexados según inventario equipable).
  - B.2.2: `RollView` -> `dice_line` genera la misma línea para los 4 desenlaces.
  - B.2.3: Construir vistas no muta el WorldState ni AgentState.
- B.3 Narración en prosa:
  - B.3.1: Provider en prosa se usa. Extraño (strangers) recurre a plantilla. Vacío/None avanza.
  - B.3.2: `OpenAICompatibleProvider` con `schema=str` no incluye `response_format` en el JSON.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agora.agents.decide import critical_needs, options
from agora.cognition.narrador import (
    Fact,
    Kind,
    Moment,
    Told,
    briefing,
    fallback,
    narrate,
    strangers,
)
from agora.cognition.openai_compat import OpenAICompatibleProvider
from agora.engine.events import EventKind
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import ActionId, NeedId, PropertyId, PropertyKind
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider, Outcome
from agora.engine.state import Propiedad
from agora.engine.world import Simulation
from agora.play import Terminal
from agora.present import (
    PALABRAS_TIRADA,
    SIN_NARRADOR,
    FighterView,
    Presenter,
    RollView,
    SheetView,
    TextPresenter,
    dice_line,
    fighter_view,
    roll_line,
    sheet_view,
)
from agora.rules.encounter import Encounter
from agora.rules.scene import load_scenario
from agora.rules.system import load_ruleset

ISLA_PACK = Path("packs/isla/pack.yaml")
CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
FORASTERO_SHEET = Path("packs/confluencia/forastero.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


class RecordingPresenter(Presenter):
    """Presentador grabador para verificar el orden y contenido de las llamadas."""

    def __init__(self, ask_input: str = "esperar\n") -> None:
        self.calls: list[tuple[str, Any]] = []
        self.ask_input = ask_input

    def turn(self, nombre: str, tick: int) -> None:
        self.calls.append(("turn", (nombre, tick)))

    def told(self, told: Told, chain: bool) -> None:
        self.calls.append(("told", (told, chain)))

    def event(self, texto: str) -> None:
        self.calls.append(("event", texto))

    def note(self, texto: str) -> None:
        self.calls.append(("note", texto))

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
        return self.ask_input

    def pick(self, pregunta: str, textos: Sequence[str]) -> int | None:
        self.calls.append(("pick", (pregunta, tuple(textos))))
        return None

    def confirm(self, texto: str) -> bool:
        self.calls.append(("confirm", texto))
        return True

    def yes_no(self, pregunta: str, defecto: bool) -> bool:
        self.calls.append(("yes_no", (pregunta, defecto)))
        return defecto


class DummyStrProvider(CognitionProvider):
    """Proveedor que devuelve cadenas directas para probar la narración en prosa."""

    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.last_schema: type | None = None

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        self.last_schema = schema
        return self.answer


# =============================================================================
# B.1 — Idéntico
# =============================================================================


def test_b1_1_text_presenter_options_sangria() -> None:
    """B.1.1: TextPresenter.options genera sangría estricta `  N. texto` (enrojece con M1)."""
    out = io.StringIO()
    tp = TextPresenter(io.StringIO(), out)

    tp.options([(1, "esperar"), (12, "ir a la cornucopia"), (123, "atacar: Renna")])

    lineas = out.getvalue().splitlines()
    assert len(lineas) == 3
    # Cada línea debe tener la sangría de dos espacios antes del número formateado a ancho 3
    assert all(linea.startswith("  ") for linea in lineas)
    assert lineas[0] == "    1. esperar"
    assert lineas[1] == "   12. ir a la cornucopia"
    assert lineas[2] == "  123. atacar: Renna"


def test_b1_1_text_presenter_dialogo_y_salidas() -> None:
    """B.1.1: TextPresenter reproduce exactamente el formato de diálogo y elementos de pantalla."""
    out = io.StringIO()
    tp = TextPresenter(io.StringIO(), out)

    # turn
    tp.turn("Elor", 7)
    assert out.getvalue() == "\n# Elor, tick 7\n"

    # speech sin respaldo y con respaldo
    out.seek(0)
    out.truncate(0)
    tp.speech("Renna", "Vete de aquí.", "seco", respaldo=False)
    assert out.getvalue() == "  Renna: «Vete de aquí.»  [seco]\n"

    out.seek(0)
    out.truncate(0)
    tp.speech("Renna", "Vete de aquí.", "seco", respaldo=True)
    assert out.getvalue() == "  Renna: «Vete de aquí.»  [seco]  (respaldo)\n"

    # told con y sin modelo
    out.seek(0)
    out.truncate(0)
    tp.told(Told("El viento arrecia en la colina.", by=0), chain=True)
    assert out.getvalue() == "  El viento arrecia en la colina.\n"

    out.seek(0)
    out.truncate(0)
    tp.told(Told("El viento arrecia en la colina.", by=None), chain=True)
    assert out.getvalue() == f"  El viento arrecia en la colina.\n{SIN_NARRADOR}\n"

    # event y note
    out.seek(0)
    out.truncate(0)
    tp.event("Ves a Renna llegar.")
    assert out.getvalue() == "  Ves a Renna llegar.\n"

    out.seek(0)
    out.truncate(0)
    tp.note("No te entiendo; escribe una orden o un número.")
    assert out.getvalue() == "No te entiendo; escribe una orden o un número.\n"

    # prompt y people
    out.seek(0)
    out.truncate(0)
    tp.prompt(["esperar", "ficha", "mirar"])
    assert out.getvalue() == "¿Qué haces?\n  atajos: esperar · ficha · mirar\n"

    out.seek(0)
    out.truncate(0)
    tp.people([(1, "Renna", "renna_d4")])
    assert out.getvalue() == "  1. Renna (renna_d4)\n"

    # look
    out.seek(0)
    out.truncate(0)
    tp.look("En el claro:", [("renna_d4", "Renna", "descansa")])
    assert out.getvalue() == "En el claro:\n    renna_d4                 Renna: descansa\n"

    # beat, fighters y ended
    out.seek(0)
    out.truncate(0)
    tp.beat("r1 Elor descarga un golpe")
    assert out.getvalue() == "r1 Elor descarga un golpe\n"

    out.seek(0)
    out.truncate(0)
    fv = FighterView("Elor", 10, 10, 2, 10, 1, 10, "en guardia")
    tp.fighters([fv])
    esperado_f = (
        "    Elor                      10/10 PV  fatiga 2/10  estrés 1/10  en guardia\n"
    )
    assert out.getvalue() == esperado_f

    out.seek(0)
    out.truncate(0)
    tp.ended("victoria", 24, ["Elor sobrevivió.", "El sol amanece."])
    assert out.getvalue() == (
        "\n# fin de la partida: victoria, 24 ticks jugados\n"
        "Elor sobrevivió.\n"
        "El sol amanece.\n"
    )

    # pick, confirm, yes_no
    inp = io.StringIO("b\n\ns\n")
    tp_interactive = TextPresenter(inp, io.StringIO())
    assert tp_interactive.pick("¿Cuál eliges?", ["primera", "segunda"]) == 1
    assert tp_interactive.confirm("atacar a Renna") is True
    assert tp_interactive.yes_no("¿Continuar?", defecto=False) is True


def test_b1_1_guion_terminal_salida_reproducible() -> None:
    """B.1.1: Guion corto con ficha, equipo, mirar, esperar produce salida exacta prefijada."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)

    inp = io.StringIO("ficha\nequipo\nmirar\nesperar\nsalir\n")
    out = io.StringIO()
    term = Terminal(sim, inp, out)
    from agora.play import play
    play(sim, term, max_ticks=5, quitting=term)

    salida = out.getvalue()
    esperada = (
        "\n# el forastero, tick 1\n"
        "  d1 00:00 noche  el forastero LLEGA     al mundo  (la puerta norte)\n"
        "¿Qué haces?\n"
        "  atajos: aprender a forjar · aprender a minar · canalizar la linea ley "
        "· cenar con los tuyos · charlar\n"
        ">   el forastero  (varon, humano)\n"
        "  carácter      curiosidad, audacia\n"
        "  dónde         la puerta norte  [noche]\n"
        "  haciendo      -\n"
        "  le falta      vinculo (mucha), dinero (mucha)\n"
        "  aprecia       -\n"
        "  detesta       -\n"
        "fama: 0.00\n"
        "  no llevas nada\n"
        ">   no llevas nada\n"
        ">   en la puerta norte: 0 más\n"
        "> \n"
        "# el forastero, tick 2\n"
        "¿Qué haces?\n"
        "  atajos: dar clase de comportamiento y cultura · desafiar a duelo · "
        "escoltar a alguien · aprender a forjar · hablar\n"
        "> "
    )
    assert salida == esperada


def test_b1_2_presentador_grabador_orden_llamadas_turno() -> None:
    """B.1.2: Grabador recibe en turno típico: `turn`, `status`, `told`/`event`, `prompt`."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)
    agent = sim.state.agents[spec.id]
    opts = tuple(options(sim.state, agent))

    # Caso A: Con evento en log (sin narrador): turn -> status -> event -> prompt
    rec_event = RecordingPresenter(ask_input="esperar\n")
    term_event = Terminal(sim, io.StringIO(), io.StringIO(), presenter=rec_event, narrator=None)
    # Generar un evento relevante donde el agente es actor
    sim.log.emit(
        tick=1, kind=EventKind.ACTION_COMPLETED, actor=agent.spec_id, action=ActionId("comer")
    )
    term_event._visto = 0

    term_event.choose(sim.state, agent, opts)
    call_names_event = [name for name, _ in rec_event.calls]

    i_turn = call_names_event.index("turn")
    i_status = call_names_event.index("status")
    i_event = call_names_event.index("event")
    i_prompt = call_names_event.index("prompt")
    assert i_turn < i_status < i_event < i_prompt

    # Caso B: Con narrador: turn -> status -> told -> prompt
    class FakeNarrator:
        def __init__(self) -> None:
            self.providers: tuple[CognitionProvider, ...] = (DummyStrProvider("prosa"),)

            class _Table:
                dice = True
            self.table = _Table()

        def world(self, world: Any, events: Any, player: str) -> Told:
            return Told("El viento ruge.", by=0)

    rec_told = RecordingPresenter(ask_input="esperar\n")
    term_told = Terminal(
        sim, io.StringIO(), io.StringIO(), presenter=rec_told, narrator=FakeNarrator()  # type: ignore[arg-type]
    )

    term_told.choose(sim.state, agent, opts)
    call_names_told = [name for name, _ in rec_told.calls]

    t_turn = call_names_told.index("turn")
    t_status = call_names_told.index("status")
    t_told = call_names_told.index("told")
    t_prompt = call_names_told.index("prompt")
    assert t_turn < t_status < t_told < t_prompt


def test_b1_3_status_en_cada_turno_y_text_presenter_no_escribe() -> None:
    """B.1.3: `status` se llama cada turno sin pedir ficha (M2); TextPresenter.status() es mudo."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)
    agent = sim.state.agents[spec.id]
    opts = tuple(options(sim.state, agent))

    # 1. Ejecutar choose con entrada "esperar" (no pide "ficha")
    rec = RecordingPresenter(ask_input="esperar\n")
    term = Terminal(sim, io.StringIO(), io.StringIO(), presenter=rec)

    term.choose(sim.state, agent, opts)

    status_calls = [args for name, args in rec.calls if name == "status"]
    # Debe llamarse exactamente una vez en el turno (enrojece con M2 si se omite)
    assert len(status_calls) == 1
    vista = status_calls[0]
    assert isinstance(vista, SheetView)
    assert vista.nombre == sim.state.censo[agent.spec_id].label

    # 2. TextPresenter.status() no escribe nada en la terminal
    out = io.StringIO()
    tp = TextPresenter(io.StringIO(), out)
    tp.status(vista)
    assert out.getvalue() == ""


# =============================================================================
# B.2 — Vistas
# =============================================================================


def test_b2_1_sheet_view_necesidades_umbrales_y_objetos_indexados() -> None:
    """B.2.1: SheetView: orden del pack (M3), [0, 1], crítica, objetos 1-indexados (M4)."""
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = next(iter(sim.state.agents.values()))

    # Configurar al menos dos objetos en el inventario del agente
    sim.state.alta_objeto(
        Propiedad(
            id=PropertyId("prop:test:1"),
            tipo=PropertyKind.OBJETO,
            objeto="cuchillo",
            renta={},
            tributo={},
            dueño=agent.spec_id,
            equipado=False,
        )
    )
    sim.state.alta_objeto(
        Propiedad(
            id=PropertyId("prop:test:2"),
            tipo=PropertyKind.OBJETO,
            objeto="lanza_corta",
            renta={},
            tributo={},
            dueño=agent.spec_id,
            equipado=True,
        )
    )

    # Configurar una necesidad bajo umbral crítico y otra sobre umbral
    primera_nec = pack.needs[0]
    segunda_nec = pack.needs[1]
    agent.needs[primera_nec.id] = 0.05
    agent.needs[segunda_nec.id] = 0.90

    vista = sheet_view(sim.state, agent)

    # Necesidades en el orden exacto del pack
    etiquetas_vista = [nec[0] for nec in vista.necesidades]
    etiquetas_pack = [s.label for s in pack.needs]
    assert etiquetas_vista == etiquetas_pack

    # El orden del pack no es alfabético; no debe ordenarse por id (enrojece con M3)
    etiquetas_orden_id = [
        pack.need_by_id[NeedId(i)].label for i in sorted(pack.need_by_id.keys())
    ]
    assert etiquetas_vista != etiquetas_orden_id

    # Valores en [0, 1] y coherencia de crítica
    criticas = {str(n) for n in critical_needs(sim.state, agent)}
    for etiqueta, val, es_critica in vista.necesidades:
        assert 0.0 <= val <= 1.0
        spec = next(s for s in pack.needs if s.label == etiqueta)
        assert es_critica == (str(spec.id) in criticas)

    assert vista.necesidades[0][2] is True
    assert vista.necesidades[1][2] is False

    # Objetos 1-indexados para `equipar N` (enrojece con M4 si inicia en 0)
    assert len(vista.objetos) >= 2
    numeros_objetos = [n for n, _, _ in vista.objetos]
    assert numeros_objetos == list(range(1, len(vista.objetos) + 1))
    assert vista.objetos[0][0] == 1
    assert vista.objetos[1][0] == 2

    # Verificar que el número 1 de la vista es el que acepta `equipar N`
    out = io.StringIO()
    term = Terminal(sim, io.StringIO(), out)
    term._equipar(sim.state, agent, str(vista.objetos[0][0]))
    assert "no llevas nada con ese número" not in out.getvalue()

    # Si se intentara equipar 0 (lo que daría M4), falla
    out_cero = io.StringIO()
    term_cero = Terminal(sim, io.StringIO(), out_cero)
    term_cero._equipar(sim.state, agent, "0")
    assert "no llevas nada con ese número" in out_cero.getvalue()


def test_b2_2_roll_view_dice_line_cuatro_desenlaces() -> None:
    """B.2.2: RollView -> dice_line genera exactamente la misma línea para los 4 desenlaces."""
    outcomes = (
        Outcome.FAILURE,
        Outcome.SUCCESS_AT_COST,
        Outcome.SUCCESS,
        Outcome.CRITICAL,
    )

    for oc in outcomes:
        # Tirada enfrentada
        v_opp = RollView(
            actor="Elor",
            pool_label="fuerza",
            dice=(5, 3, 1),
            opposing="Renna",
            opposing_label="la defensa de",
            opposing_dice=(4, 2),
            outcome=oc,
        )
        line_opp = roll_line(v_opp)
        expected_opp = dice_line(
            "Elor", "fuerza", (5, 3, 1), "Renna", "la defensa de", (4, 2), oc
        )
        assert line_opp == expected_opp
        esperado_texto = (
            f"🎲 Elor, fuerza (3) contra la defensa de Renna (2): [5 3 1] contra [4 2] "
            f"→ {PALABRAS_TIRADA[oc]}"
        )
        assert line_opp == esperado_texto

        # Tirada no enfrentada
        v_solo = RollView(
            actor="Elor",
            pool_label="buscar",
            dice=(6,),
            opposing=None,
            opposing_label=None,
            opposing_dice=(),
            outcome=oc,
        )
        line_solo = roll_line(v_solo)
        expected_solo = dice_line("Elor", "buscar", (6,), None, None, (), oc)
        assert line_solo == expected_solo
        assert line_solo == f"🎲 Elor, buscar (1): [6] → {PALABRAS_TIRADA[oc]}"


def test_b2_3_construir_vistas_no_muta_world_ni_agent() -> None:
    """B.2.3: Construir SheetView, FighterView y RollView no muta el WorldState ni AgentState."""
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = next(iter(sim.state.agents.values()))
    other_id = next(aid for aid in sim.state.agents if aid != agent.spec_id)

    # Estado previo
    needs_antes = dict(agent.needs)
    cond_antes = list(agent.condiciones)
    busy_antes = agent.busy
    agents_antes = {
        k: (a.at, dict(a.needs), list(a.condiciones)) for k, a in sim.state.agents.items()
    }
    props_antes = dict(sim.state.propiedades)
    tick_antes = sim.state.tick

    # Construir vistas repetidamente
    _ = sheet_view(sim.state, agent)
    _ = sheet_view(sim.state, agent, otro=other_id)

    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, sim.state.rng, "test")
    fv = fighter_view(enc.fighters["aria"])
    assert fv.label == "Aria"
    assert fv.vitality == 18

    rv = RollView("Elor", "fuerza", (4, 2), None, None, (), Outcome.SUCCESS)
    _ = roll_line(rv)

    # Comprobar que nada mutó
    assert agent.needs == needs_antes
    assert agent.condiciones == cond_antes
    assert agent.busy == busy_antes
    assert {
        k: (a.at, dict(a.needs), list(a.condiciones)) for k, a in sim.state.agents.items()
    } == agents_antes
    assert sim.state.propiedades == props_antes
    assert sim.state.tick == tick_antes


# =============================================================================
# B.3 — Narración en prosa
# =============================================================================


def test_b3_1_narrate_prosa_strangers_y_fallback() -> None:
    """B.3.1: Prosa se usa; extraño recurre a plantilla (M5); vacío pasa al siguiente."""
    m = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="El claro",
        description="Un claro rodeado de hayas.",
        phase="dia",
        present=("Elor", "Renna"),
        state=(),
        facts=(Fact(priority=1, order=1, text="renna descansa junto al fuego", names=("Renna",)),),
        veils=(),
        everyone=("Elor", "Renna", "Vidan", "Kael"),
    )

    # Asegurar que Vidan no está en el briefing para poder actuar como extraño
    assert "Vidan" not in briefing(m)

    # 1. Provider que devuelve prosa válida sin extraños: se usa directamente
    p_ok = DummyStrProvider("Renna descansa en silencio cerca del fuego.")
    told = narrate(m, [p_ok], seed=42)
    assert told.by == 0
    assert told.text == "Renna descansa en silencio cerca del fuego."
    assert p_ok.last_schema is str

    # 2. Provider que devuelve prosa con extraño: recurre a plantilla
    p_stranger = DummyStrProvider("Vidan aparece de pronto entre los árboles.")
    assert "Vidan" in strangers(m, p_stranger.answer or "")
    told_stranger = narrate(m, [p_stranger], seed=42)
    # Debe ser plantilla (by=None) y no p_stranger (enrojece con M5 si no se valida strangers)
    assert told_stranger.by is None
    assert told_stranger.text == fallback(m)

    # 3. Provider que devuelve vacío o None: pasa al siguiente proveedor válido
    p_none = DummyStrProvider(None)
    p_empty = DummyStrProvider("")
    p_whitespace = DummyStrProvider("   \n\t  ")
    p_valid_2 = DummyStrProvider("El fuego chisporrotea con calma.")

    told_chain = narrate(m, [p_none, p_empty, p_whitespace, p_valid_2], seed=42)
    assert told_chain.by == 3
    assert told_chain.text == "El fuego chisporrotea con calma."


def test_b3_2_openai_compat_schema_str_sin_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B.3.2: OpenAICompatibleProvider con schema=str no incluye response_format (M6)."""
    cuerpo_capturado: dict[str, Any] = {}

    class FakeHTTPResponse:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def read(self) -> bytes:
            return self.data

        def __enter__(self) -> FakeHTTPResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def mock_open(req: Any, timeout: float = 6.0) -> FakeHTTPResponse:
        nonlocal cuerpo_capturado
        cuerpo_capturado = json.loads(req.data.decode("utf-8"))
        respuesta = {
            "choices": [{"message": {"content": "   El viento acaricia la hierba alta.   "}}]
        }
        return FakeHTTPResponse(json.dumps(respuesta).encode("utf-8"))

    monkeypatch.setattr("agora.cognition.openai_compat._open", mock_open)
    monkeypatch.setenv("TEST_KEY", "test-key-123")

    provider = OpenAICompatibleProvider("test-model", clave_env="TEST_KEY")

    # Caso schema=str: NO debe incluir "response_format" en el cuerpo (enrojece con M6)
    res_str = provider._ask("Cuéntame qué ves.", str, semilla=123)
    assert res_str == "El viento acaricia la hierba alta."
    assert "response_format" not in cuerpo_capturado

    # Caso schema=BaseModel: SÍ debe incluir response_format con json_schema
    class DummyPayload(BaseModel):
        mensaje: str

    def mock_open_model(req: Any, timeout: float = 6.0) -> FakeHTTPResponse:
        nonlocal cuerpo_capturado
        cuerpo_capturado = json.loads(req.data.decode("utf-8"))
        contenido = json.dumps({"mensaje": "hola"})
        resp = {"choices": [{"message": {"content": contenido}}]}
        return FakeHTTPResponse(json.dumps(resp).encode("utf-8"))

    monkeypatch.setattr("agora.cognition.openai_compat._open", mock_open_model)
    res_model = provider._ask("Dame un esquema.", DummyPayload, semilla=123)
    assert isinstance(res_model, DummyPayload)
    assert res_model.mensaje == "hola"
    assert "response_format" in cuerpo_capturado
    assert cuerpo_capturado["response_format"]["type"] == "json_schema"

    # Caso schema=str con contenido vacío o espacios: devuelve None
    def mock_open_vacio(req: Any, timeout: float = 6.0) -> FakeHTTPResponse:
        return FakeHTTPResponse(
            json.dumps({"choices": [{"message": {"content": "    "}}]}).encode("utf-8")
        )

    monkeypatch.setattr("agora.cognition.openai_compat._open", mock_open_vacio)
    res_vacio = provider._ask("Silencio.", str, semilla=123)
    assert res_vacio is None
