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
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

from agora.agents.decide import Decision
from agora.cognition.intencion import Entry, Kind, Menu, Order, interpret
from agora.cognition.voz import hablar
from agora.engine.consulta import ficha
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId, PlaceId
from agora.engine.ports import Outcome
from agora.engine.render import render_event
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState
from agora.engine.world import Simulation
from agora.rules.encounter import Action, ActionKind, Encounter, Fighter, Policy

if TYPE_CHECKING:
    from agora.engine.ports import CognitionProvider, DecisionSource


class ScriptError(ValueError):
    """El guion pide algo que el mundo ya no ofrece. No se arregla solo: un
    guion que se saltara lo imposible estaría jugando otra partida."""


def _clave(d: Decision) -> tuple[str, str, str | None]:
    return (str(d.action), str(d.place), None if d.target is None else str(d.target))


COMBATE = ("combate", "resistir", "rematar", "perseguir")
"""Lo que el jugador decide dentro de una escena (unidad 13), en el mismo
guion. Cada clase se consume en orden dentro de su tick."""


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
            elif not any(k in dato for k in COMBATE):
                raise ScriptError(f"línea {n}: ni «decidir», ni «interrumpir», ni de combate")

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
  salir        acabar la partida al final de este cuarto de hora
  ayuda        esto
  o escribe lo que haces: «me escondo en el arroyo», «¿quién hay aquí?»"""


SIN_MODELO = "  (el intérprete no contestó: entiende el léxico)"
"""Como el «(respaldo)» de la voz: que el jugador sepa por qué de pronto se
le entiende peor. Sin esto, una API sin créditos pasaba por un léxico mudo."""


def world_menu(world: WorldState, options: Sequence[Decision]) -> Menu:
    """El menú de `options()` para el intérprete (unidad 14), en el mismo
    orden: la entrada i es la decisión i."""
    pack = world.pack
    viaje: dict[PlaceId, int] = {}
    for d in options:
        viaje[d.place] = min(viaje.get(d.place, d.travel_ticks), d.travel_ticks)
    return Menu(
        entries=tuple(Entry(d.action, d.place, d.target) for d in options),
        actions=tuple((a, pack.action_by_id[a].label, pack.action_by_id[a].examples)
                      for a in sorted({d.action for d in options})),
        places=tuple((p, pack.place_by_id[p].label, t) for p, t in sorted(viaje.items())),
        people=tuple((t, world.censo[t].label)
                     for t in sorted({d.target for d in options if d.target is not None})),
        orders=tuple(Order),
    )


def confirms(inp: TextIO, out: TextIO, texto: str) -> bool:
    """El eco de lo entendido cuando va contra alguien. En el banco, «me ocupo
    de Vidan» acabó en rematarle con los dos modelos de 70B. Enter es que sí."""
    out.write(f"  entiendo: {texto}. ¿Sí? [S/n] ")
    out.flush()
    return not inp.readline().strip().lower().startswith("n")


def picks(inp: TextIO, out: TextIO, pregunta: str, textos: Sequence[str]) -> int | None:
    """Elegir entre las candidatas del intérprete por letra, para no chocar con
    los números del menú. Cualquier otra cosa es ninguna."""
    letras = "abc"[: len(textos)]
    out.write(pregunta + "\n")
    for letra, texto in zip(letras, textos, strict=False):
        out.write(f"    {letra}) {texto}\n")
    out.write("  ¿cuál? ")
    out.flush()
    r = inp.readline().strip().lower()
    return letras.index(r) if len(r) == 1 and r in letras else None


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
        interpreter: CognitionProvider | None = None,
    ) -> None:
        self.sim = sim
        self.inp = inp
        self.out = out
        self.provider = provider
        """La voz de los NPCs."""
        self.interpreter = interpreter
        """Quien entiende lo que escribes. Otro proveedor que la voz, aunque
        fuera el mismo modelo: nada de lo que se le pregunta a uno le llega al
        otro."""
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
        return f"  {n:>3}. {self._describir(world, agent, d, best)}"

    def _describir(self, world: WorldState, agent: AgentState, d: Decision, best: float) -> str:
        pack = world.pack
        texto = pack.action_by_id[d.action].label
        if d.target is not None:
            texto += f" con {world.censo[d.target].label}"
        donde = pack.place_by_id[d.place].label
        cuartos = "1 cuarto" if d.travel_ticks == 1 else f"{d.travel_ticks} cuartos"
        viaje = "aquí" if d.travel_ticks == 0 else f"en {donde}, a {cuartos} de hora"
        banda = hint(d.utility, best, agent.temperament.temperature)
        return f"{texto} ({viaje})  — {banda}"

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
            linea = self._leer("> ")
            orden = linea.split()
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
                    self._orden(world, agent, Order.SHEET, None)
                case ["ficha", otro] if AgentId(otro) in world.agents:
                    self._orden(world, agent, Order.SHEET, otro)
                case ["mirar"]:
                    self._orden(world, agent, Order.LOOK, None)
                case ["hablar", otro] if AgentId(otro) in world.agents:
                    self._orden(world, agent, Order.TALK, otro)
                case ["salir"]:
                    self.quit = True
                    return None
                case ["ayuda"]:
                    self._decir(AYUDA)
                case _:
                    hecho, elegida = self._interpretar(world, agent, options, linea, best)
                    if hecho:
                        return elegida

    def _orden(self, world: WorldState, agent: AgentState, orden: Order, sobre: str | None) -> bool:
        """Lo que la terminal hace sin decidir nada, se escriba como orden o en
        prosa. Devuelve si el jugador ha decidido esperar."""
        otro = AgentId(sobre) if sobre is not None and AgentId(sobre) in world.agents else None
        match orden:
            case Order.SHEET:
                hechos = (ficha(world, otro, agent.spec_id) if otro is not None
                          else ficha(world, agent.spec_id))
                for linea in hechos.lines():
                    self._decir(linea)
            case Order.LOOK:
                self._mirar(world, agent)
            case Order.TALK if otro is not None and world.agents[otro].at == agent.at:
                quien = world.censo[otro].label
                habla, del_modelo, _ = hablar(world, otro, agent.spec_id, self.provider)
                self._decir(f"  {quien}: «{habla.dice}»  [{habla.tono}]"
                            + ("" if del_modelo else "  (respaldo)"))
            case Order.TALK:
                self._decir("  no hay nadie así aquí con quien hablar")
            case Order.WAIT:
                return True
        return False

    def _interpretar(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...],
        texto: str, best: float,
    ) -> tuple[bool, Decision | None]:
        """(si ya hay decisión, cuál: `None` es esperar)."""
        semilla = world.rng.stream("intencion", agent.spec_id, world.tick).randrange(2**31)
        lectura = interpret(world_menu(world, options), texto, self.interpreter, semilla)
        if self.interpreter is not None and not lectura.by_model:
            self._decir(SIN_MODELO)
        match lectura.kind:
            case Kind.ACTION if lectura.entry is not None:
                d = options[lectura.entry]
                descrita = self._describir(world, agent, d, best)
                if d.target is None:
                    self._decir(f"  → {descrita}")
                    return True, d
                return (True, d) if confirms(self.inp, self.out, descrita) else (False, None)
            case Kind.ORDER if lectura.order is not None:
                return self._orden(world, agent, lectura.order, lectura.about), None
            case Kind.AMBIGUOUS | Kind.NO_FIT if lectura.candidates:
                pregunta = ("  ¿cuál de estas?" if lectura.kind is Kind.AMBIGUOUS
                            else "  eso no se puede ahora; lo más parecido:")
                cual = picks(self.inp, self.out, pregunta, [
                    self._describir(world, agent, options[i], best) for i in lectura.candidates])
                if cual is None:
                    return False, None
                return True, options[lectura.candidates[cual]]
            case _:
                self._decir("  no te entiendo: escribe lo que haces, o un número («ayuda»)")
                return False, None

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


# --- La escena de combate (unidad 13) ---------------------------------------------


def _accion(a: Action) -> dict[str, object]:
    d: dict[str, object] = {"accion": a.kind.value}
    if a.target is not None:
        d["objetivo"] = a.target
    if a.force:
        d["forzar"] = True
    return d


class ScriptCombat:
    """Las decisiones del jugador en una escena, leídas del guion. Por
    contenido (acción, objetivo) y nunca por número de opción."""

    def __init__(self, lines: Iterable[str], tick: Callable[[], int]) -> None:
        self.tick = tick
        self.colas: dict[tuple[int, str], list[object]] = {}
        for linea in lines:
            if not linea.strip():
                continue
            dato = json.loads(linea)
            for clase in COMBATE:
                if clase in dato:
                    self.colas.setdefault((int(dato["tick"]), clase), []).append(dato[clase])

    def _siguiente(self, clase: str) -> object:
        cola = self.colas.get((self.tick(), clase))
        if not cola:
            raise ScriptError(f"tick {self.tick()}: el guion no dice qué hacer ({clase})")
        return cola.pop(0)

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        d = self._siguiente("combate")
        assert isinstance(d, dict)
        return Action(ActionKind(d["accion"]), d.get("objetivo"), bool(d.get("forzar", False)))

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        return bool(self._siguiente("resistir"))

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        return bool(self._siguiente("rematar"))

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        return bool(self._siguiente("perseguir"))


class CombatRecorder:
    """Graba lo que decide otra política de combate, en el formato del guion."""

    def __init__(self, policy: Policy, out: TextIO, tick: Callable[[], int]) -> None:
        self.policy = policy
        self.out = out
        self.tick = tick

    def _grabar(self, clase: str, valor: object) -> None:
        self.out.write(json.dumps({"tick": self.tick(), clase: valor}) + "\n")
        self.out.flush()

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        a: Action = self.policy.choose(encounter, me)
        self._grabar("combate", _accion(a))
        return a

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        si: bool = self.policy.resists(encounter, me, hit, outcome)
        self._grabar("resistir", si)
        return si

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        si: bool = self.policy.finishes(encounter, me, fallen)
        self._grabar("rematar", si)
        return si

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        si: bool = self.policy.pursues(encounter, me, fleer)
        self._grabar("perseguir", si)
        return si


ETIQUETAS = {
    ActionKind.ATTACK: "atacar a {}",
    ActionKind.TOTAL_DEFENSE: "cubrirte (defensa total)",
    ActionKind.RECOVER: "recuperar el aliento",
    ActionKind.FIRST_AID: "socorrer a {}",
    ActionKind.FINISH: "rematar a {}",
    ActionKind.FLEE: "huir",
    ActionKind.SURRENDER: "rendirte",
}


def scene_menu(encounter: Encounter, legales: Sequence[Action]) -> Menu:
    """Las acciones legales de la escena para el intérprete, en el mismo orden."""
    return legal_menu(
        encounter.combat.examples,
        {f.id: f.spec.label for f in encounter.fighters.values()},
        [(a.kind.value, a.target, a.force) for a in legales],
    )


def legal_menu(
    examples: Mapping[str, tuple[str, ...]], labels: Mapping[str, str],
    legales: Sequence[tuple[str, str | None, bool]],
) -> Menu:
    """El menú de una escena a partir de datos: lo usa también el banco, que
    no monta escenas."""
    kinds = [k for k in ActionKind if any(a == k.value for a, _, _ in legales)]
    gente = sorted({o for _, o, _ in legales if o is not None})
    return Menu(
        entries=tuple(Entry(a, None, o, f) for a, o, f in legales),
        actions=tuple((k.value, ETIQUETAS[k].split(" {}")[0], tuple(examples.get(k.value, ())))
                      for k in kinds),
        people=tuple((g, labels[g]) for g in gente),
    )


class TerminalCombat:
    """El jugador dentro de una escena: ve cómo va, elige por número o lo
    escribe, y contesta a las preguntas que la escena le hace (resistir,
    rematar, perseguir), que siguen siendo de sí o no."""

    def __init__(self, inp: TextIO, out: TextIO,
                 interpreter: CognitionProvider | None = None) -> None:
        self.inp = inp
        self.out = out
        self.interpreter = interpreter
        self._visto: dict[str, int] = {}

    def _decir(self, texto: str) -> None:
        self.out.write(texto + "\n")
        self.out.flush()

    def _si(self, pregunta: str, defecto: bool) -> bool:
        self.out.write(pregunta + (" [S/n] " if defecto else " [s/N] "))
        self.out.flush()
        linea = self.inp.readline().strip().lower()
        return defecto if not linea else linea.startswith("s")

    def _nombre(self, encounter: Encounter, quien: str | None) -> str:
        return "?" if quien is None else encounter.fighters[quien].spec.label

    def _novedades(self, encounter: Encounter) -> None:
        visto = self._visto.get(encounter.id, 0)
        for b in encounter.beats[visto:]:
            a_quien = f" a {self._nombre(encounter, b.target)}" if b.target else ""
            que = f" → {b.outcome.value}" if b.outcome else ""
            dano = f", {b.damage} de daño" if b.damage else ""
            nota = f" ({b.note})" if b.note else ""
            quien = self._nombre(encounter, b.actor)
            self._decir(f"  r{b.round} {quien}: {b.kind}{a_quien}{que}{dano}{nota}")
        self._visto[encounter.id] = len(encounter.beats)

    def report(self, lines: tuple[str, ...]) -> None:
        if lines:
            self._decir(lines[-1])

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        self._novedades(encounter)
        for f in encounter.fighters.values():
            self._decir(f"    {f.spec.label:<24} {f.vitality:>3}/{f.spec.vitality} PV"
                        f"  fatiga {f.fatigue}/{f.spec.fatigue}  estrés {f.stress}/{f.spec.stress}"
                        f"  {f.status.value}")
        legales = list(encounter.legal_actions(me))
        if not encounter.exhausted(me):
            legales += [Action(a.kind, a.target, True) for a in legales
                        if a.kind is ActionKind.ATTACK]
        for n, a in enumerate(legales, start=1):
            self._decir(f"  {n:>3}. {self._etiqueta(encounter, a)}")
        while True:
            self.out.write("combate> ")
            self.out.flush()
            linea = self.inp.readline()
            if not linea:
                return legales[0]
            if linea.strip().isdigit() and 1 <= int(linea) <= len(legales):
                return legales[int(linea) - 1]
            if linea.strip():
                elegida = self._interpretar(encounter, me, legales, linea.strip())
                if elegida is not None:
                    return elegida

    def _etiqueta(self, encounter: Encounter, a: Action) -> str:
        texto = ETIQUETAS[a.kind].format(self._nombre(encounter, a.target))
        return texto + (" forzándote" if a.force else "")

    def _interpretar(
        self, encounter: Encounter, me: Fighter, legales: list[Action], texto: str
    ) -> Action | None:
        semilla = encounter.source.stream(
            "intencion", encounter.id, encounter.round, me.id).randrange(2**31)
        lectura = interpret(scene_menu(encounter, legales), texto, self.interpreter, semilla)
        if self.interpreter is not None and not lectura.by_model:
            self._decir(SIN_MODELO)
        match lectura.kind:
            case Kind.ACTION if lectura.entry is not None:
                a = legales[lectura.entry]
                if a.target is None:
                    self._decir(f"  → {self._etiqueta(encounter, a)}")
                    return a
                return a if confirms(self.inp, self.out, self._etiqueta(encounter, a)) else None
            case Kind.AMBIGUOUS | Kind.NO_FIT if lectura.candidates:
                pregunta = ("  ¿cuál de estas?" if lectura.kind is Kind.AMBIGUOUS
                            else "  eso no se puede ahora; lo más parecido:")
                cual = picks(self.inp, self.out, pregunta,
                             [self._etiqueta(encounter, legales[i]) for i in lectura.candidates])
                return legales[lectura.candidates[cual]] if cual is not None else None
            case _:
                self._decir("  elige un número de la lista, o escribe lo que haces")
                return None

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        self._novedades(encounter)
        return self._si(f"  te alcanza un golpe de {hit}. ¿Lo resistes (cuesta estrés)?", False)

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        self._novedades(encounter)
        return self._si(f"  {fallen.spec.label} está en el suelo. ¿Le rematas?", False)

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        self._novedades(encounter)
        return self._si(f"  {fleer.spec.label} intenta huir. ¿Le persigues?", True)
