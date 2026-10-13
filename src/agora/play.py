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
import textwrap
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TextIO

from agora.agents.decide import Decision
from agora.cognition.conversa import (
    ACT_HELP,
    CONVERSA,
    FAREWELL,
    heard_as,
    interpret_said,
    talk_menu,
)
from agora.cognition.intencion import Entry, Kind, Menu, Order, _representatives, interpret
from agora.cognition.narrador import DEATH, BeatView, Fact, Narrator, Table, Told, round_facts
from agora.cognition.voz import Heard, hablar
from agora.engine.consulta import ficha
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, ClaimKind, NeedId, PlaceId, QuestionKind, SocialAct
from agora.engine.ports import Outcome
from agora.engine.render import render_event
from agora.engine.social import Claim, Conversation
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState
from agora.engine.world import Simulation
from agora.rules.encounter import Action, ActionKind, Beat, Encounter, Fighter, Policy

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

HABLAR = "hablar"
"""Lo que el jugador le dice a alguien (unidad 15): el acto resuelto y a quién,
nunca la frase. `{"tick": t, "hablar": {"con": id, "acto": valor, "sobre": id?}}`."""


class Script:
    def __init__(self, lines: Iterable[str], sim: Simulation | None = None) -> None:
        self.sim = sim
        self.decisiones: dict[int, tuple[str, str, str | None]] = {}
        self.interrupciones: dict[int, bool] = {}
        self.charlas: dict[int, list[dict[str, Any]]] = {}
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
            elif HABLAR in dato:
                self.charlas.setdefault(tick, []).append(dato[HABLAR])
            elif not any(k in dato for k in COMBATE):
                raise ScriptError(f"línea {n}: ni «decidir», ni «interrumpir», ni de combate")
        if self.charlas and sim is None:
            raise ScriptError("el guion tiene líneas «hablar» y no se le dio la simulación")

    def choose(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...]
    ) -> Decision | None:
        if self.sim is not None:
            # Antes de buscar la decisión: lo dicho cambia el aprecio, como cuando
            # se jugó, y la decisión se tomó después de decirlo.
            conversaciones: dict[str, Conversation] = {}
            for h in self.charlas.get(world.tick, ()):
                con = str(h["con"])
                charla = conversaciones.setdefault(con, Conversation(AgentId(con)))
                sobre = h.get("sobre")
                afirma = h.get("afirma")
                pregunta = h.get("pregunta")
                if pregunta is not None:
                    sobre = pregunta["quien"]
                self.sim.apply_social(
                    agent.spec_id, AgentId(con), SocialAct(h["acto"]),
                    None if sobre is None else AgentId(sobre), charla,
                    None if afirma is None else Claim(
                        ClaimKind(afirma["tipo"]), AgentId(afirma["quien"]),
                        None if "lugar" not in afirma else PlaceId(afirma["lugar"]),
                        None if "victima" not in afirma else AgentId(afirma["victima"])),
                    None if pregunta is None else QuestionKind(pregunta["tipo"]),
                )
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

    def __init__(self, source: DecisionSource, out: TextIO, sim: Simulation | None = None) -> None:
        self.source = source
        self.out = out
        self.sim = sim

    def choose(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...]
    ) -> Decision | None:
        desde = self.sim.log.siguiente_seq if self.sim is not None else 0
        elegida = self.source.choose(world, agent, options)
        if self.sim is not None:
            # Lo dicho sale del log y no de la terminal: lo que se graba es lo que
            # el mundo recibió, y va antes de la decisión, que se tomó después.
            for e in self.sim.log:
                if (e.seq >= desde and e.kind is EventKind.SOCIAL_ACT
                        and e.actor == agent.spec_id and e.subject is not None):
                    h: dict[str, Any] = {"con": str(e.subject), "acto": str(e.data["act"])}
                    if "claim" in e.data:
                        afirma = {"tipo": str(e.data["claim"]), "quien": str(e.data["claim_who"])}
                        if "claim_place" in e.data:
                            afirma["lugar"] = str(e.data["claim_place"])
                        if "claim_victim" in e.data:
                            afirma["victima"] = str(e.data["claim_victim"])
                        h["afirma"] = afirma
                    elif "question" in e.data:
                        h["pregunta"] = {"tipo": str(e.data["question"]),
                                         "quien": str(e.data["about"])}
                    elif "about" in e.data:
                        h["sobre"] = str(e.data["about"])
                    self.out.write(json.dumps({"tick": world.tick, HABLAR: h}) + "\n")
            self.out.flush()
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
    """**Ya no se le enseña al jugador** (2026-10-13): en la primera partida de
    prueba, con «te conviene mucho» delante, eligió rematar tres veces seguidas
    sin pensar. Un DM no te dice cuál es la mejor opción. Se queda para
    depurar.

    La utilidad en bandas y no en número: el número delataría al motor, y
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


SIN_NARRADOR = "  (el narrador no contestó: lo cuenta la plantilla)"


def show(out: TextIO, told: Told, chain: bool) -> None:
    """La prosa del narrador, a lo ancho de una terminal. `chain`: si había
    algún modelo al que preguntar, para avisar cuando ninguno contestó."""
    for linea in textwrap.wrap(told.text, width=88):
        out.write(f"  {linea}\n")
    if chain and told.by is None:
        out.write(SIN_NARRADOR + "\n")
    out.flush()


def nearest_places(world: WorldState, options: Sequence[Decision]) -> dict[str, tuple[str, int]]:
    """Acción -> el sitio más cercano donde el jugador sabe que puede hacerla:
    lo que el narrador sabe para contestar «¿dónde hay agua?». Sale del menú,
    con su percepción limitada, y no del mundo."""
    pack = world.pack
    out: dict[str, tuple[str, int]] = {}
    for d in options:
        label = pack.action_by_id[d.action].label
        if label not in out or d.travel_ticks < out[label][1]:
            out[label] = (pack.place_by_id[d.place].label, d.travel_ticks)
    return out


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


POR_VERBO = 3
"""Opciones de cada verbo en la primera página; el resto, con «más»."""


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
        narrator: Narrator | None = None,
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
        self.narrator = narrator
        """Quien cuenta lo que pasa (unidad 17). Sin él, el log de siempre."""
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
        if self.narrator is not None:
            nuevos = [e for e in self.sim.log if e.seq >= self._visto]
            self._visto = self.sim.log.siguiente_seq
            told = self.narrator.world(world, nuevos, str(agent.spec_id))
            if told is not None:
                show(self.out, told, bool(self.narrator.providers))
            return
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

    def _opcion(self, world: WorldState, n: int, d: Decision) -> str:
        return f"  {n:>3}. {self._describir(world, d)}"

    def _describir(self, world: WorldState, d: Decision) -> str:
        """Sin «te conviene» (ver `hint`). El destinatario va tras dos puntos y
        no con «con»: «atacar con Renna» se leía «atacar junto a Renna»."""
        pack = world.pack
        texto = pack.action_by_id[d.action].label
        if d.target is not None:
            texto += f": {world.censo[d.target].label}"
        donde = pack.place_by_id[d.place].label
        cuartos = "1 cuarto" if d.travel_ticks == 1 else f"{d.travel_ticks} cuartos"
        viaje = "aquí" if d.travel_ticks == 0 else f"en {donde}, a {cuartos} de hora"
        return f"{texto} ({viaje})"

    def _vista(self, world: WorldState, options: tuple[Decision, ...]) -> list[int]:
        """El orden en que se enseñan las opciones: por verbo, alfabético, y
        dentro de cada verbo de la más cercana a la más lejana; como mucho
        `POR_VERBO` de cada uno delante y el resto después. El orden del motor
        es de mejor a peor, y enseñarlo así era decirle al jugador cuál elegir;
        y con ocho «esconderse» seguidos no cabía nada más en la pantalla."""
        pack = world.pack

        def clave(i: int) -> tuple[str, int, str, str]:
            d = options[i]
            quien = "" if d.target is None else world.censo[d.target].label
            return (pack.action_by_id[d.action].label, d.travel_ticks,
                    pack.place_by_id[d.place].label, quien)

        orden = sorted(range(len(options)), key=clave)
        primero: list[int] = []
        resto: list[int] = []
        vistos: dict[str, int] = {}
        for i in orden:
            verbo = clave(i)[0]
            vistos[verbo] = vistos.get(verbo, 0) + 1
            (primero if vistos[verbo] <= POR_VERBO else resto).append(i)
        return primero + resto

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
        vista = self._vista(world, options)
        hasta = self.page
        self._decir(f"\n# {world.censo[agent.spec_id].label}, tick {world.tick}")
        for n, i in enumerate(vista[:hasta], start=1):
            self._decir(self._opcion(world, n, options[i]))
        while True:
            linea = self._leer("> ")
            orden = linea.split()
            if not orden:
                continue
            match orden:
                case [numero] if numero.isdigit() and 1 <= int(numero) <= len(options):
                    return options[vista[int(numero) - 1]]
                case ["más" | "mas"]:
                    for n, i in enumerate(vista[hasta : hasta + self.page], start=hasta + 1):
                        self._decir(self._opcion(world, n, options[i]))
                    hasta += self.page
                case ["esperar"]:
                    return None
                case ["esperar", cuantos] if cuantos.isdigit() and int(cuantos) > 0:
                    self._esperar = int(cuantos) - 1
                    return None
                case ["ficha"]:
                    self._orden(world, agent, Order.SHEET, None, options)
                case ["ficha", otro] if AgentId(otro) in world.agents:
                    self._orden(world, agent, Order.SHEET, otro, options)
                case ["mirar"]:
                    self._orden(world, agent, Order.LOOK, None, options)
                case ["hablar", otro] if AgentId(otro) in world.agents:
                    hecho, elegida = self._orden(world, agent, Order.TALK, otro, options)
                    if hecho:
                        return elegida
                case ["salir"]:
                    self.quit = True
                    return None
                case ["ayuda"]:
                    self._decir(AYUDA)
                case _:
                    hecho, elegida = self._interpretar(world, agent, options, linea)
                    if hecho:
                        return elegida

    def _orden(
        self, world: WorldState, agent: AgentState, orden: Order, sobre: str | None,
        options: tuple[Decision, ...],
    ) -> tuple[bool, Decision | None]:
        """Lo que la terminal hace, se escriba como orden o en prosa. Devuelve
        (si ya hay decisión, cuál): esperar es `(True, None)`, y una
        conversación puede acabar en la acción que el pack declara para hablar."""
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
                return self._conversar(world, agent, otro, options)
            case Order.TALK:
                self._decir("  no hay nadie así aquí con quien hablar")
            case Order.WAIT:
                return True, None
        return False, None

    @staticmethod
    def _lugares(world: WorldState, options: tuple[Decision, ...]) -> dict[str, tuple[int, str]]:
        """Nombre corto -> (viaje, el más cercano con ese nombre), de su menú: los
        lugares que el jugador sabe nombrar, como en la 14."""
        return _representatives(world_menu(world, options))

    @staticmethod
    def _conocidos(
        world: WorldState, agent: AgentState, presentes: list[tuple[str, str]],
        options: tuple[Decision, ...],
    ) -> list[tuple[str, str]]:
        """Las personas de las que el jugador puede afirmar algo: quien tiene
        delante, quien le sale en el menú y quien ha visto. Y él mismo, que es
        «yo»: «Tumi me hirió a mí» tiene una víctima."""
        ids = {pid for pid, _ in presentes} | {str(d.target) for d in options if d.target}
        ids |= {str(q) for _, quienes in agent.sightings.values() for q in quienes}
        ids.discard(str(agent.spec_id))
        gente = [(pid, world.censo[AgentId(pid)].label) for pid in sorted(ids)
                 if AgentId(pid) in world.censo]
        return [*gente, (str(agent.spec_id), "yo")]

    def _conversar(
        self, world: WorldState, agent: AgentState, otro: AgentId,
        options: tuple[Decision, ...],
    ) -> tuple[bool, Decision | None]:
        """Una conversación con el mundo parado (unidad 15, D-164): cada frase
        se interpreta como un acto y entra por `apply_social`; la voz pone las
        palabras al tono que decidió la recepción. Al cerrarla, si el pack dice
        qué acción es conversar y se puede hacer aquí mismo, es la decisión."""
        quien = world.censo[otro].label
        presentes = [(str(o.spec_id), world.censo[o.spec_id].label)
                     for o in world.agents_in_order() if o.at == agent.at and o is not agent]
        menu = talk_menu(presentes, str(otro))
        etiquetas = {pid: label for pid, label in presentes}
        talk = Conversation(otro)
        self._decir(f"  hablas con {quien} («adiós» para terminar)")
        while not talk.over:
            frase = self._leer("tú> ")
            if not frase or self.quit:
                break
            semilla = world.rng.stream(
                "conversa", agent.spec_id, world.tick, talk.count).randrange(2**31)
            lectura = interpret(menu, frase, self.interpreter, semilla, CONVERSA)
            if self.interpreter is not None and not lectura.by_model:
                self._decir(SIN_MODELO)
            entrada = None
            if lectura.kind is Kind.ACTION and lectura.entry is not None:
                entrada = menu.entries[lectura.entry]
            elif lectura.kind in (Kind.AMBIGUOUS, Kind.NO_FIT) and lectura.candidates:
                cual = picks(self.inp, self.out, "  ¿qué le dices?", [
                    ACT_HELP[menu.entries[i].action][0]
                    + (f" ({etiquetas[t]})" if (t := menu.entries[i].target) else "")
                    for i in lectura.candidates])
                if cual is not None:
                    entrada = menu.entries[lectura.candidates[cual]]
            if entrada is None:
                self._decir("  no sé qué le dices; prueba de otra forma, o «adiós»")
                continue
            if entrada.action == FAREWELL:
                break
            acto = SocialAct(entrada.action)
            sobre = None if entrada.target is None else AgentId(entrada.target)
            afirma: Claim | None = None
            pregunta: QuestionKind | None = None
            if acto in (SocialAct.AFFIRM, SocialAct.ASK):
                # Una segunda llamada con el esquema anidado (unidad 15b). Sin
                # modelo no hay léxico para esto: un falso sí acusaría a alguien.
                segunda = world.rng.stream(
                    "conversa-dicho", agent.spec_id, world.tick, talk.count).randrange(2**31)
                dicho = interpret_said(
                    self._conocidos(world, agent, presentes, options),
                    [(pid, nombre) for nombre, (_, pid) in self._lugares(world, options).items()],
                    frase, self.interpreter, segunda, str(otro))
                if dicho is None or (dicho.claim is None and dicho.question is None):
                    self._decir("  no sé qué afirmas; dilo de otra forma")
                    continue
                if dicho.claim is not None:
                    acto, afirma, sobre = SocialAct.AFFIRM, dicho.claim, None
                elif dicho.question is not None:
                    acto, (pregunta, sobre) = SocialAct.ASK, dicho.question
            r = self.sim.apply_social(agent.spec_id, otro, acto, sobre, talk, afirma, pregunta)
            de_quien = None if sobre is None else etiquetas.get(str(sobre))
            oido = Heard(frase, heard_as(acto, de_quien), r.tone, r.leaves, talk.count,
                         r.info, r.belief)
            habla, del_modelo, _ = hablar(world, otro, agent.spec_id, self.provider, oido)
            self._decir(f"  {quien}: «{habla.dice}»  [{habla.tono}]"
                        + ("" if del_modelo else "  (respaldo)"))
            if r.leaves:
                self._decir(f"  ({quien} da la conversación por terminada)")
        accion = world.pack.social.action
        if talk.count == 0 or accion is None:
            return False, None
        aqui = next((d for d in options if d.action == accion and d.travel_ticks == 0), None)
        return (True, aqui) if aqui is not None else (False, None)

    def _interpretar(
        self, world: WorldState, agent: AgentState, options: tuple[Decision, ...],
        texto: str,
    ) -> tuple[bool, Decision | None]:
        """(si ya hay decisión, cuál: `None` es esperar)."""
        semilla = world.rng.stream("intencion", agent.spec_id, world.tick).randrange(2**31)
        lectura = interpret(world_menu(world, options), texto, self.interpreter, semilla)
        if self.interpreter is not None and not lectura.by_model:
            self._decir(SIN_MODELO)
        match lectura.kind:
            case Kind.ACTION if lectura.entry is not None:
                d = options[lectura.entry]
                descrita = self._describir(world, d)
                if d.target is None:
                    self._decir(f"  → {descrita}")
                    return True, d
                return (True, d) if confirms(self.inp, self.out, descrita) else (False, None)
            case Kind.ORDER if lectura.order is not None:
                return self._orden(world, agent, lectura.order, lectura.about, options)
            case Kind.AMBIGUOUS | Kind.NO_FIT if lectura.candidates:
                pregunta = ("  ¿cuál de estas?" if lectura.kind is Kind.AMBIGUOUS
                            else "  eso no se puede ahora; lo más parecido:")
                cual = picks(self.inp, self.out, pregunta, [
                    self._describir(world, options[i]) for i in lectura.candidates])
                if cual is None:
                    return False, None
                return True, options[lectura.candidates[cual]]
            case Kind.QUESTION if self.narrator is not None:
                told = self.narrator.answer(world, str(agent.spec_id), texto,
                                            nearest_places(world, options))
                show(self.out, told, bool(self.narrator.providers))
                return False, None
            case _:
                self._decir("  no te entiendo: escribe lo que haces, o un número («ayuda»)")
                return False, None

    def farewell(self) -> None:
        """Lo que pasó desde la última decisión hasta que el jugador murió: el
        bucle se para sin volver a preguntarle, y sin esto nadie se lo contaba."""
        if self.narrator is None or self.sim.state.player is None:
            return
        nuevos = [e for e in self.sim.log if e.seq >= self._visto]
        self._visto = self.sim.log.siguiente_seq
        told = self.narrator.world(self.sim.state, nuevos, str(self.sim.state.player))
        if told is not None:
            show(self.out, told, bool(self.narrator.providers))

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


def scene_facts(
    encounter: Encounter, me: Fighter, beats: Sequence[Beat], table: Table,
) -> tuple[tuple[Fact, ...], tuple[str, ...], tuple[str, ...]]:
    """Los hechos de unas rondas, el estado de cada combatiente y quién hay,
    para el narrador. El daño, en bandas: el narrador no recita números."""
    vistas = []
    for i, b in enumerate(beats):
        banda = ""
        if b.damage and b.target is not None:
            parte = b.damage / max(encounter.fighters[b.target].spec.vitality, 1)
            banda = (", un roce" if parte < 0.2 else ", un buen golpe" if parte < 0.5
                     else ", un golpe brutal")
        kind = next((k for k in ActionKind if k.value == b.kind), None)
        etiqueta = ETIQUETAS[kind].split(" {}")[0] if kind is not None else b.kind
        vistas.append(BeatView(i, b.kind, b.actor, b.target,
                               b.outcome.value if b.outcome else None, banda, etiqueta))

    def name(f: str | None) -> str:
        return "alguien" if f is None else encounter.fighters[f].spec.label.split(",")[0]

    hechos = round_facts(vistas, me.id, name, encounter.combat.narration,
                         encounter.combat.content, table)
    estado = tuple(f"{'tú' if f.id == me.id else name(f.id)}: {_banda(f)}"
                   for f in encounter.fighters.values())
    presentes = tuple(name(f.id) for f in encounter.fighters.values() if f.id != me.id)
    return hechos, estado, presentes


def _banda(f: Fighter) -> str:
    """Cómo está alguien en la escena, sin números: lo que se ve."""
    parte = f.vitality / max(f.spec.vitality, 1)
    salud = ("ileso" if parte >= 0.99 else "herido" if parte > 0.5
             else "malherido" if parte > 0 else "sin fuerzas")
    return f"{salud}, {f.status.value}"


class TerminalCombat:
    """El jugador dentro de una escena: ve cómo va, elige por número o lo
    escribe, y contesta a las preguntas que la escena le hace (resistir,
    rematar, perseguir), que siguen siendo de sí o no."""

    def __init__(self, inp: TextIO, out: TextIO,
                 interpreter: CognitionProvider | None = None,
                 narrator: Narrator | None = None,
                 world: Callable[[], WorldState] | None = None) -> None:
        self.inp = inp
        self.out = out
        self.interpreter = interpreter
        self.narrator = narrator
        self.world = world
        """El mundo de ahora, para el narrador: la escena no lo conoce."""
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

    def _novedades(self, encounter: Encounter, me: Fighter | None = None) -> None:
        visto = self._visto.get(encounter.id, 0)
        if self.narrator is not None and self.world is not None and me is not None:
            self._contar(encounter, me, encounter.beats[visto:])
            self._visto[encounter.id] = len(encounter.beats)
            return
        for b in encounter.beats[visto:]:
            a_quien = f" a {self._nombre(encounter, b.target)}" if b.target else ""
            que = f" → {b.outcome.value}" if b.outcome else ""
            dano = f", {b.damage} de daño" if b.damage else ""
            nota = f" ({b.note})" if b.note else ""
            quien = self._nombre(encounter, b.actor)
            self._decir(f"  r{b.round} {quien}: {b.kind}{a_quien}{que}{dano}{nota}")
        self._visto[encounter.id] = len(encounter.beats)

    def _contar(self, encounter: Encounter, me: Fighter, beats: Sequence[Beat]) -> None:
        assert self.narrator is not None and self.world is not None
        world = self.world()
        hechos, estado, presentes = scene_facts(encounter, me, beats, self.narrator.table)
        told = self.narrator.round(world, me.id, hechos, estado, presentes,
                                   f"{encounter.id}:{encounter.round}")
        if told is not None:
            show(self.out, told, bool(self.narrator.providers))

    def report(self, lines: tuple[str, ...]) -> None:
        if lines:
            self._decir(lines[-1])

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        self._novedades(encounter, me)
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
        self._novedades(encounter, me)
        return self._si(f"  te alcanza un golpe de {hit}. ¿Lo resistes (cuesta estrés)?", False)

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        """Si lo que estás haciendo en el mundo ya era matar (su `content` del
        pack lleva la muerte), no se pregunta: preguntar «¿le rematas?» justo
        después de elegir «rematar a un herido» era redundante (2026-10-13)."""
        self._novedades(encounter, me)
        if self._ya_era_matar(me):
            self._decir(f"  rematas a {fallen.spec.label}: era lo que ibas a hacer")
            return True
        return self._si(f"  {fallen.spec.label} está en el suelo. ¿Le rematas?", False)

    def _ya_era_matar(self, me: Fighter) -> bool:
        if self.world is None:
            return False
        world = self.world()
        yo = world.agents.get(AgentId(me.id))
        if yo is None or not isinstance(yo.busy, PerformingAction):
            return False
        return DEATH in world.pack.action_by_id[yo.busy.action].content

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        self._novedades(encounter, me)
        return self._si(f"  {fleer.spec.label} intenta huir. ¿Le persigues?", True)
