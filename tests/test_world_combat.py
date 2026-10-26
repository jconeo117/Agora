"""Pruebas del resolutor de combate en el mundo y el guion (unidad 13)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.engine.ontology import AgentId, NeedId
from agora.engine.pack import load_pack
from agora.engine.ports import Fate, Outcome
from agora.engine.rng import RngSource
from agora.engine.world import Simulation
from agora.play import (
    CombatRecorder,
    Recorder,
    Script,
    ScriptCombat,
    ScriptError,
    TerminalCombat,
    play,
)
from agora.rules.binding import BindingError, load_binding
from agora.rules.encounter import (
    Action,
    ActionKind,
    Beat,
    Encounter,
)
from agora.rules.policy import StylePolicy
from agora.rules.scene import load_scenario
from agora.rules.system import load_ruleset
from agora.rules.world_combat import MixedPolicy, WorldCombat
from tests.test_persecucion import DummyPolicy

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")
ISLA_PACK = Path("packs/isla/pack.yaml")
ISLA_BINDING = Path("packs/isla/reglas/base.yaml")


def test_solo_vuelve_lo_que_la_escena_cambio() -> None:
    """Quien no recibe un golpe no lleva su Vitalidad en needs."""
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, pack, ruleset)

    # Jugador pelea contra otro tributo
    sim = Simulation(pack, seed=1312)
    jugador_id = AgentId("sami_d9")
    rival_id = AgentId("danfin_d9")
    sim.set_player(jugador_id)

    # Política donde el jugador esquiva/bloquea o el combate se resuelve
    wc = WorldCombat(ruleset, binding, StylePolicy())
    resultado = wc.resolve(sim.state, jugador_id, rival_id, frozenset())
    assert resultado is not None

    danfin = next(c for c in resultado.combatants if c.agent == rival_id)
    needs_danfin = dict(danfin.needs)
    # Danfin no recibió golpes: no lleva su Vitalidad en needs
    assert NeedId("salud") not in needs_danfin
    # Pero sí se cansó: descanso viaja en needs
    assert NeedId("descanso") in needs_danfin


def test_quien_cae_se_lleva_la_herida_del_enlace() -> None:
    """DOWN -> salud 0 y la condición de resources.down."""
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, pack, ruleset)

    sim = Simulation(pack, seed=1312)
    jugador_id = AgentId("sami_d9")
    rival_id = AgentId("danfin_d9")
    sim.set_player(jugador_id)

    wc = WorldCombat(ruleset, binding, StylePolicy())
    resultado = wc.resolve(sim.state, jugador_id, rival_id, frozenset())
    assert resultado is not None

    caidos = [c for c in resultado.combatants if c.fate is Fate.DOWN]
    assert caidos
    caido = caidos[0]
    # Salud a 0
    salud_needs = [v for k, v in caido.needs if k == NeedId("salud")]
    assert salud_needs == [0.0]
    # Se lleva la herida grave de down
    assert caido.inflicts is not None
    assert caido.inflicts.situation == binding.resources.down.situation  # type: ignore[union-attr]


def test_el_jugador_decide_y_los_npcs_por_estilo() -> None:
    """MixedPolicy llama a la política del jugador solo para su luchador."""
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    pol_jugador = DummyPolicy(Action(ActionKind.TOTAL_DEFENSE))
    pol_npc = DummyPolicy(Action(ActionKind.RECOVER))

    mixed = MixedPolicy(player="aria", player_policy=pol_jugador, npc_policy=pol_npc)

    # Para Aria (jugador) llama a pol_jugador
    assert mixed.choose(enc, aria) == Action(ActionKind.TOTAL_DEFENSE)
    # Para Lobo (NPC) llama a pol_npc
    assert mixed.choose(enc, lobo) == Action(ActionKind.RECOVER)


class Agresivo:
    def choose(self, world: Any, agent: Any, options: Any) -> Any:
        for o in options:
            if str(o.action) in ("atacar", "atacar_con_sana", "golpe_mortal"):
                return o
        return options[0] if options else None

    def interrupt(self, world: Any, agent: Any, need: Any) -> bool:
        return True


def test_la_partida_de_la_sonda() -> None:
    """La sonda (sonda_partida.py) como test: reason == "muerte" en el tick 41,
    dos escenas y el guion byte a byte. Eran el 47 y tres escenas hasta la calibración de la
    isla del 2026-10-13 (zona antes, menos agua y comida): el número es de la
    isla, no del combate.
    """
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, pack, ruleset)

    jugador = AgentId("sami_d9")
    guion, log1 = io.StringIO(), io.StringIO()
    escenas: list[tuple[str, ...]] = []
    sim1 = Simulation(pack, seed=1312, log_sink=log1)
    sim1.set_player(jugador)
    sim1.encounter_resolver = WorldCombat(
        ruleset, binding, CombatRecorder(StylePolicy(), guion, lambda: sim1.state.tick),
        report=escenas.append,
    )
    res1 = play(sim1, Recorder(Agresivo(), guion), 96 * 3, None)

    assert res1.ticks == 61
    assert res1.reason == "muerte"
    assert len(escenas) == 3

    log2 = io.StringIO()
    sim2 = Simulation(pack, seed=1312, log_sink=log2)
    sim2.set_player(jugador)
    lineas = guion.getvalue().splitlines()
    sim2.encounter_resolver = WorldCombat(
        ruleset, binding, ScriptCombat(lineas, lambda: sim2.state.tick)
    )
    play(sim2, Script(lineas), 96 * 3, None)

    assert log1.getvalue() == log2.getvalue()


def test_el_guion_de_combate_por_contenido() -> None:
    """ScriptCombat devuelve las acciones en orden por tick;
    uno que se queda sin decisiones -> ScriptError.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]

    lineas = [
        '{"tick": 5, "combate": {"accion": "huir"}}',
        '{"tick": 5, "resistir": true}',
        '{"tick": 5, "rematar": false}',
        '{"tick": 5, "perseguir": true}',
    ]
    sc = ScriptCombat(lineas, lambda: 5)

    assert sc.choose(enc, aria) == Action(ActionKind.FLEE)
    assert sc.resists(enc, aria, 4, Outcome.SUCCESS) is True
    assert sc.finishes(enc, aria, aria) is False
    assert sc.pursues(enc, aria, aria) is True

    # Si se pide otra decisión del mismo tipo y no queda en la cola -> ScriptError
    with pytest.raises(ScriptError, match="el guion no dice qué hacer"):
        sc.choose(enc, aria)


def test_terminal_combat() -> None:
    """Con StringIO, elige por número, contesta resistir/rematar/perseguir
    y pinta los Beat nuevos una sola vez.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]

    # Simular inputs del usuario: opción 1 para choose, 's' para resistir,
    # 'n' para rematar, Enter (defecto) para perseguir
    inp = io.StringIO("1\ns\nn\n\n")
    out = io.StringIO()
    tc = TerminalCombat(inp, out)

    # Añadir un beat para comprobar que se pinta una sola vez
    enc.beats.append(
        Beat(round=1, actor="lobo", kind=ActionKind.ATTACK, target="aria",
             outcome=Outcome.SUCCESS, damage=4)
    )

    accion = tc.choose(enc, aria)
    assert accion is not None
    salida1 = out.getvalue()
    assert "r1 lobo: atacar a Aria → success, 4 de daño" in salida1

    # Segunda consulta no repite el beat ya visto
    out.seek(0)
    out.truncate(0)
    resiste = tc.resists(enc, aria, 4, Outcome.SUCCESS)
    assert resiste is True
    assert "r1 lobo" not in out.getvalue()

    remata = tc.finishes(enc, aria, lobo)
    assert remata is False

    persigue = tc.pursues(enc, aria, lobo)
    assert persigue is True


def test_down_desconocido_no_carga() -> None:
    """Un resources.down que no es una condición personal del pack -> BindingError."""
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)

    raw = yaml.safe_load(ISLA_BINDING.read_text(encoding="utf-8"))
    raw["resources"]["down"] = {
        "situation": "condicion_inexistente",
        "marca": "cuerpo",
        "gravedad_min": 1.0,
    }

    tmp = Path("/tmp/bad_binding.yaml")
    tmp.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(BindingError, match=r"resources\.down"):
        load_binding(tmp, pack, ruleset)
