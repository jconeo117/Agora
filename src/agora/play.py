"""Jugar: la terminal y el guion como fuentes de decisión del jugador (unidad 10).

Esto es interfaz, no motor: lee el mundo y le pasa una decisión por la puerta
que el motor abre (`DecisionSource`), y nada más. Las dos fuentes dicen lo
mismo de la misma forma: cada decisión es (tick, acción, lugar, destinatario),
nunca el número de una opción del menú, porque el menú cambia de un tick a
otro y un guion que dijera «la tercera» sería otra partida sin avisar.

El guion es JSONL, una línea por decisión:

    {"tick": 31, "decidir": {"accion": "comer", "lugar": "posada_central"}}
    {"tick": 44, "interrumpir": true}

Un tick sin línea es esperar; una interrupción sin línea, seguir con lo suyo.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

from agora.agents.decide import Decision
from agora.cognition.voz import hablar
from agora.engine.consulta import ficha
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId
from agora.engine.render import render_event
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState
from agora.engine.world import Simulation

if TYPE_CHECKING:
    from agora.engine.ports import CognitionProvider, DecisionSource


class ScriptError(ValueError):
    """El guion pide algo que el mundo ya no ofrece. No se arregla solo: un
    guion que se saltara lo imposible estaría jugando otra partida."""


def _clave(d: Decision) -> tuple[str, str, str | None]:
    return (str(d.action), str(d.place), None if d.target is None else str(d.target))


class Script:
    def __init__(self, lines: Iterable[str]) -> None:
        self.decisiones: dict[int, tuple[str, str, str | None]] = {}
        self.interrupciones: dict[int, bool] = {}
        for n, linea in enumerate(lines, start=1):
            if not linea.strip():
                continue
            dato = json.loads(linea)
            tick = int(dato["tick"])
            if "decidir" in dato:
                d = dato["decidir"]
                self.decisiones[tick] = (d["accion"], d["lugar"], d.get("destinatario"))
            elif "interrumpir" in dato:
                self.interrupciones[tick] = bool(dato["interrumpir"])
            else:
                raise ScriptError(f"línea {n}: ni «decidir» ni «interrumpir»")

    def choose(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...]
    ) -> Decision | None:
        pedida = self.decisiones.get(world.tick)
        if pedida is None:
            return None
        for opcion in options:
            if _clave(opcion) == pedida:
                return opcion
        raise ScriptError(f"tick {world.tick}: {pedida} no está entre las opciones")

    def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
        return self.interrupciones.get(world.tick, False)


class Recorder:
    """Graba lo que decide otra fuente, en el formato del guion. Lo que se
    graba y se vuelve a jugar con `Script` da el mismo mundo."""

    def __init__(self, source: DecisionSource, out: TextIO) -> None:
        self.source = source
        self.out = out

    def choose(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...]
    ) -> Decision | None:
        elegida = self.source.choose(world, agent, options)
        if elegida is not None:
            accion, lugar, destinatario = _clave(elegida)
            d: dict[str, str] = {"accion": accion, "lugar": lugar}
            if destinatario is not None:
                d["destinatario"] = destinatario
            self.out.write(json.dumps({"tick": world.tick, "decidir": d}) + "\n")
            self.out.flush()
        return elegida

    def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
        si = self.source.interrupt(world, agent, need)
        if si:
            self.out.write(json.dumps({"tick": world.tick, "interrumpir": True}) + "\n")
            self.out.flush()
        return si


def hint(utility: float, best: float, temperature: float) -> str:
    """La utilidad en bandas y no en número: el número delataría al motor, y
    lo que un personaje sabe de sus opciones es si le apetecen, no cuánto.

    La banda es el peso que le daría a esa opción un NPC con su temperamento,
    `exp((u - mejor) / temperatura)`, el mismo de `decide`: «te conviene
    mucho» quiere decir «alguien como tú lo haría a menudo». Se probó antes la
    proporción con la mejor (u / mejor), y en `confluencia` once de las doce
    primeras opciones salían «mucho»: las utilidades se apiñan y la proporción
    no distingue nada."""
    peso = math.exp((utility - best) / temperature)
    if peso >= 0.5:
        return "te conviene mucho"
    if peso >= 0.1:
        return "te conviene"
    if peso >= 0.01:
        return "te conviene poco"
    return "no te conviene"


AYUDA = """  número       elegir esa opción
  más          ver más opciones
  esperar N    dejar pasar N cuartos de hora sin hacer nada
  ficha [id]   lo que se sabe de ti, o de otro
  mirar        quién está aquí y qué hace
  hablar id    preguntarle qué tal le va a alguien que esté aquí
  salir        acabar la partida al final de este cuarto de hora"""


class Terminal:
    """Una persona delante del teclado. Lo que consulta no cambia el mundo:
    ficha, mirar y hablar son lectura (reglas 1 y 4)."""

    def __init__(
        self,
        sim: Simulation,
        inp: TextIO,
        out: TextIO,
        provider: CognitionProvider | None = None,
        page: int = 12,
    ) -> None:
        self.sim = sim
        self.inp = inp
        self.out = out
        self.provider = provider
        self.page = page
        self.quit = False
        self._esperar = 0
        self._visto = 0
        self._rechazos: set[tuple[NeedId, int]] = set()

    def _decir(self, texto: str) -> None:
        self.out.write(texto + "\n")
        self.out.flush()

    def _leer(self, prompt: str) -> str:
        self.out.write(prompt)
        self.out.flush()
        linea = self.inp.readline()
        if not linea:
            self.quit = True
            return "salir"
        return linea.strip()

    def _novedades(self, agent: AgentState) -> None:
        """Lo que le ha pasado al jugador, o con él, desde la última vez."""
        world = self.sim.state
        for evento in self.sim.log:
            if evento.seq < self._visto:
                continue
            # Que otro coincida contigo es su suceso, no el tuyo, y en un lugar
            # concurrido llenaba la pantalla de nombres.
            suyo = evento.actor == agent.spec_id or (
                evento.subject == agent.spec_id and evento.kind is not EventKind.ENCOUNTER
            )
            if suyo:
                self._decir("  " + render_event(world.pack, evento, world.censo))
        self._visto = self.sim.log.siguiente_seq

    def _opcion(
        self, world: WorldState, agent: AgentState, n: int, d: Decision, best: float
    ) -> str:
        pack = world.pack
        texto = pack.action_by_id[d.action].label
        if d.target is not None:
            texto += f" con {world.censo[d.target].label}"
        donde = pack.place_by_id[d.place].label
        cuartos = "1 cuarto" if d.travel_ticks == 1 else f"{d.travel_ticks} cuartos"
        viaje = "aquí" if d.travel_ticks == 0 else f"en {donde}, a {cuartos} de hora"
        banda = hint(d.utility, best, agent.temperament.temperature)
        return f"  {n:>3}. {texto} ({viaje})  — {banda}"

    def _mirar(self, world: WorldState, agent: AgentState) -> None:
        pack = world.pack
        aqui = [o for o in world.agents_in_order() if o.at == agent.at and o is not agent]
        self._decir(f"  en {pack.place_by_id[agent.at].label}: {len(aqui)} más")
        for o in aqui:
            match o.busy:
                case PerformingAction(action=a):
                    que = pack.action_by_id[a].label
                case Traveling():
                    que = "de paso"
                case None:
                    que = "sin hacer nada"
            self._decir(f"    {o.spec_id:<24} {world.censo[o.spec_id].label}: {que}")

    def choose(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...]
    ) -> Decision | None:
        if self.quit:
            return None
        if self._esperar > 0:
            self._esperar -= 1
            return None
        self._novedades(agent)
        if not options:
            self._decir("  no hay nada que puedas hacer ahora; esperas")
            return None
        best = options[0].utility
        hasta = self.page
        self._decir(f"\n# {world.censo[agent.spec_id].label}, tick {world.tick}")
        for n, d in enumerate(options[:hasta], start=1):
            self._decir(self._opcion(world, agent, n, d, best))
        while True:
            orden = self._leer("> ").split()
            if not orden:
                continue
            match orden:
                case [numero] if numero.isdigit() and 1 <= int(numero) <= len(options):
                    return options[int(numero) - 1]
                case ["más" | "mas"]:
                    for n, d in enumerate(options[hasta : hasta + self.page], start=hasta + 1):
                        self._decir(self._opcion(world, agent, n, d, best))
                    hasta += self.page
                case ["esperar"]:
                    return None
                case ["esperar", cuantos] if cuantos.isdigit() and int(cuantos) > 0:
                    self._esperar = int(cuantos) - 1
                    return None
                case ["ficha"]:
                    for linea in ficha(world, agent.spec_id).lines():
                        self._decir(linea)
                case ["ficha", otro] if AgentId(otro) in world.agents:
                    for linea in ficha(world, AgentId(otro), agent.spec_id).lines():
                        self._decir(linea)
                case ["mirar"]:
                    self._mirar(world, agent)
                case ["hablar", otro] if (
                    AgentId(otro) in world.agents and world.agents[AgentId(otro)].at == agent.at
                ):
                    quien = world.censo[AgentId(otro)].label
                    habla, del_modelo, _ = hablar(
                        world, AgentId(otro), agent.spec_id, self.provider
                    )
                    self._decir(f"  {quien}: «{habla.dice}»  [{habla.tono}]"
                                + ("" if del_modelo else "  (respaldo)"))
                case ["salir"]:
                    self.quit = True
                    return None
                case _:
                    self._decir(AYUDA)

    def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
        """Se pregunta una vez por necesidad y ocupación: si dices que no, no
        vuelve a preguntar hasta que empieces otra cosa."""
        clave = (need, id(agent.busy))
        if self.quit or clave in self._rechazos:
            return False
        etiqueta = world.pack.need_by_id[need].label
        respuesta = self._leer(f"  te falta {etiqueta} de verdad. ¿Lo dejas todo? [s/N] ")
        if respuesta.lower().startswith("s"):
            return True
        self._rechazos.add(clave)
        return False


@dataclass(frozen=True, slots=True)
class PlayResult:
    ticks: int
    reason: str
    """«fin» (se acabaron los días), «muerte» o «salir»."""


def play(sim: Simulation, source: DecisionSource, max_ticks: int,
         quitting: Terminal | None = None) -> PlayResult:
    """El bucle de la partida. Solo se para entre ticks: salir a mitad de uno
    dejaría a medio mundo resuelto, y guardarlo así rompería «reanudar = no
    haber parado»."""
    if sim.state.player is None:
        raise ValueError("esta partida no tiene jugador")
    sim.player_source = source
    for hecho in range(max_ticks):
        if sim.state.player not in sim.state.agents:
            return PlayResult(hecho, "muerte")
        if quitting is not None and quitting.quit:
            return PlayResult(hecho, "salir")
        sim.tick()
    if sim.state.player not in sim.state.agents:
        return PlayResult(max_ticks, "muerte")
    return PlayResult(max_ticks, "fin")
