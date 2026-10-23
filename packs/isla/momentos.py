"""Graba el banco de narración de la isla (unidad 17): juega en automático con
tres tributos y guarda lo que el narrador contaría en cada decisión, en cada
ronda y ante unas preguntas. Es herramienta de una vez, como `generar.py`:

    uv run python packs/isla/momentos.py packs/isla/banco-narracion.jsonl

El banco se graba con la mesa vacía, sin líneas ni velos: los velos se miden
aparte, y una línea quitaría hechos que el banco necesita ver.
"""

import json
import sys
from pathlib import Path

from agora.agents.decide import Decision
from agora.cognition.narrador import (
    Hilos, Sighting, Table, moment_to_json, question_moment, round_moment, scene_of, select,
    world_moment,
)
from agora.engine.ontology import AgentId
from agora.engine.pack import load_pack
from agora.engine.world import Simulation
from agora.play import nearest_places, scene_facts
from agora.rules.binding import load_binding
from agora.rules.policy import StylePolicy
from agora.rules.system import load_ruleset
from agora.rules.world_combat import WorldCombat

MESA = Table()
PREGUNTAS = ["¿dónde puedo beber agua?", "¿cómo estoy?", "¿dónde puedo esconderme?",
             "¿hay salida de esta isla?", "¿quién anda por aquí?"]
momentos: list[dict] = []


class Auto:
    """Un jugador que hace lo que haría su personaje: la primera opción."""

    def __init__(self, sim: Simulation, yo: str) -> None:
        self.sim, self.yo, self.visto, self.n = sim, yo, 0, 0
        self.seen = Sighting()
        self.preguntas = list(PREGUNTAS)
        self.hilos = Hilos()
        self.ultimo: int | None = None
        self.pelea = False

    def acabo_pelea(self, relato: tuple[str, ...]) -> None:
        """Lo que `TerminalCombat.report` marca: la siguiente decisión cuenta la escena entera."""
        self.pelea = True

    def choose(self, world, agent, opts: tuple[Decision, ...]):
        eventos = [e for e in self.sim.log if e.seq >= self.visto]
        self.visto = self.sim.log.siguiente_seq
        hechos = select(world, eventos, self.yo, self.seen, MESA, self.hilos)
        transcurrido = 0 if self.ultimo is None else world.tick - self.ultimo
        escena = scene_of(world, self.yo, self.seen, self.hilos.involved, self.pelea, transcurrido)
        self.pelea = False
        self.ultimo = world.tick
        momentos.append(moment_to_json(
            world_moment(world, self.yo, hechos, MESA, self.seen.place, escena)))
        self.n += 1
        if self.preguntas and self.n % 3 == 2:
            q = question_moment(world, self.yo, self.preguntas.pop(0), nearest_places(world, opts), MESA)
            momentos.append(moment_to_json(q))
        self.seen = Sighting(str(agent.at), frozenset(
            str(o.spec_id) for o in world.agents_in_order() if o.at == agent.at))
        return opts[0] if opts else None

    def interrupt(self, world, agent, need) -> bool:
        return True


class Escena:
    """Su estilo de NPC, y antes de cada turno, la ronda que contaría el narrador."""

    def __init__(self, sim: Simulation, yo: str) -> None:
        self.sim, self.yo, self.visto, self.base = sim, yo, {}, StylePolicy()

    def choose(self, enc, me):
        v = self.visto.get(enc.id, 0)
        self.visto[enc.id] = len(enc.beats)
        hechos, estado, presentes = scene_facts(enc, me, enc.beats[v:], MESA)
        if hechos:
            m = round_moment(self.sim.state, self.yo, hechos, estado, presentes, MESA)
            momentos.append(moment_to_json(m))
        return self.base.choose(enc, me)

    def resists(self, enc, me, hit, outcome):
        return self.base.resists(enc, me, hit, outcome)

    def finishes(self, enc, me, fallen):
        return self.base.finishes(enc, me, fallen)

    def pursues(self, enc, me, fleer):
        return self.base.pursues(enc, me, fleer)


def jugar(semilla: int, yo: str, ticks: int) -> None:
    pack = load_pack(Path("packs/isla/pack.yaml"))
    reglas = load_ruleset(Path("rules/base/rules.yaml"))
    enlace = load_binding(Path("packs/isla/reglas/base.yaml"), pack, reglas)
    sim = Simulation(pack, seed=semilla)
    sim.set_player(AgentId(yo))
    auto = Auto(sim, yo)
    sim.player_source = auto
    sim.encounter_resolver = WorldCombat(reglas, enlace, Escena(sim, yo), auto.acabo_pelea)
    for _ in range(ticks):
        if AgentId(yo) not in sim.state.agents:
            break
        sim.tick()


if __name__ == "__main__":
    for semilla, yo in ((1, "elor_d1"), (2, "naia_d2"), (3, "finrenlo_d7")):
        jugar(semilla, yo, 96 * 2)
    salida = Path(sys.argv[1])
    salida.write_text("".join(json.dumps(m, ensure_ascii=False) + "\n" for m in momentos), encoding="utf-8")
    tipos: dict[str, int] = {}
    for m in momentos:
        tipos[m["kind"]] = tipos.get(m["kind"], 0) + 1
    print(f"{len(momentos)} momentos -> {salida}: {tipos}")
