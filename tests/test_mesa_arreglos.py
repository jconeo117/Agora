"""Los arreglos de presentación tras la primera partida de prueba (2026-10-13):
el menú no dice qué te conviene, el destinatario no se lee como compañía, se
agrupa por verbo, y rematar no se pregunta si ya era lo que hacías."""

from __future__ import annotations

import io
import re
from pathlib import Path
from types import SimpleNamespace

from agora.agents.decide import options
from agora.engine.ontology import ActionId, AgentId
from agora.engine.pack import load_pack
from agora.engine.state import PerformingAction
from agora.engine.world import Simulation
from agora.play import POR_VERBO, Terminal, TerminalCombat

ISLA_PACK = Path("packs/isla/pack.yaml")


def _isla_en_el_tick_7() -> tuple[Simulation, AgentId]:
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    while sim.state.tick < 7:
        sim.tick()
    return sim, AgentId("elor_d1")


def test_el_menu_no_dice_que_conviene_ni_usa_con() -> None:
    sim, yo = _isla_en_el_tick_7()
    w = sim.state
    opts = tuple(options(w, w.agents[yo]))
    out = io.StringIO()
    Terminal(sim, io.StringIO("salir\n"), out).choose(w, w.agents[yo], opts)
    texto = out.getvalue()
    assert "conviene" not in texto
    menu = [ln for ln in texto.splitlines() if re.match(r"\s+\d+\. ", ln)]
    dirigidas = [ln for ln in menu if ", del distrito" in ln]
    assert dirigidas, "en el tick 7 Elor tiene acciones dirigidas a alguien"
    # « con » sí puede ir en la etiqueta («atacar con saña»); no delante de un nombre.
    assert all(": " in ln and not re.search(r" con [A-ZÁÉÍÓÚ]", ln) for ln in dirigidas)


def test_el_menu_va_por_verbo_y_el_numero_elige_lo_que_se_ve() -> None:
    sim, yo = _isla_en_el_tick_7()
    w = sim.state
    opts = tuple(options(w, w.agents[yo]))
    terminal = Terminal(sim, io.StringIO("1\n"), io.StringIO())
    vista = terminal._vista(w, opts)
    assert sorted(vista) == list(range(len(opts)))
    pagina = vista[: terminal.page]
    verbos = [w.pack.action_by_id[opts[i].action].label for i in pagina]
    assert verbos == sorted(verbos)
    assert max(verbos.count(v) for v in set(verbos)) <= POR_VERBO
    elegida = terminal.choose(w, w.agents[yo], opts)
    assert elegida == opts[vista[0]]


def test_no_pregunta_si_rematas_cuando_ya_ibas_a_matar() -> None:
    sim, yo = _isla_en_el_tick_7()
    w = sim.state
    escena = TerminalCombat(io.StringIO(""), io.StringIO(), world=lambda: w)
    me = SimpleNamespace(id=str(yo))
    w.agents[yo].busy = PerformingAction(action=ActionId("golpe_mortal"), ticks_remaining=1)
    assert escena._ya_era_matar(me)  # type: ignore[arg-type]
    w.agents[yo].busy = PerformingAction(action=ActionId("atacar"), ticks_remaining=1)
    assert not escena._ya_era_matar(me)  # type: ignore[arg-type]
    w.agents[yo].busy = None
    assert not escena._ya_era_matar(me)  # type: ignore[arg-type]
