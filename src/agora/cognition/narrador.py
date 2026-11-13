"""El narrador: cuenta lo que el jugador acaba de vivir (unidad 17, D-162,
D-167).

Tres capas, como el intérprete: un selector determinista elige del log lo que
merece contarse (en un día de isla pasan unos 950 hechos en el sitio del
jugador, 703 de ellos «coincide con»), un modelo lo cuenta en prosa con un
briefing cerrado, y si el modelo falla, tarda o nombra a alguien que no está en
el briefing, lo cuenta la plantilla. Lo que dice el narrador no se guarda en
ningún sitio: no es estado ni va al guion, y reproducir una partida la narra de
nuevo con los mismos hechos (regla 4).

Las líneas de la mesa se aplican aquí, antes del modelo: lo que es línea no
llega al briefing, y un modelo no puede contar lo que no sabe.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agora.cognition.intencion import stems
from agora.engine.consulta import ficha
from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    ContentTag,
    FactionId,
    ItemId,
    ItemSlot,
    NarrationSpec,
    NeedId,
    PlaceId,
    RelationId,
    Spec,
)
from agora.engine.ports import CognitionProvider
from agora.engine.state import PerformingAction, Traveling, WorldState

PROMPTS = Path(__file__).parent / "prompts"
TELL = (PROMPTS / "narrador.txt").read_text(encoding="utf-8")
ANSWER = (PROMPTS / "pregunta.txt").read_text(encoding="utf-8")
OPENING_PROMPT = (PROMPTS / "apertura.txt").read_text(encoding="utf-8")

DEATH = "muerte"
"""La etiqueta de contenido de una muerte. Es la única que pone el código: la
muerte es una primitiva del motor (`AGENT_DIED`), no algo que declare un pack."""

CAN = "puedes "
"""Cómo empieza una línea de «dónde se puede hacer qué» en lo que sabe el
personaje: es lo único que el respaldo sabe emparejar con una pregunta."""

TOP = 8
"""Hechos por narración. Con ocho, los dos modelos del banco ya recitaban."""

ALIKE = 2
"""Cuántos hechos ajenos del mismo tipo se cuentan uno a uno antes de agruparse."""

TOP_NOTABLES = 5
"""Cuántas personas caben en la escena; las demás son «y otros N» (unidad 18)."""


class Table(Spec):
    """Lo que la mesa acordó antes de jugar (sesión cero). Es de la mesa y no
    del mundo: la misma isla se juega con líneas distintas en mesas distintas."""

    lines: tuple[ContentTag, ...] = ()
    """No se narra: el motor lo simula igual, pero queda fuera de plano."""
    veils: tuple[ContentTag, ...] = ()
    """Se narra sin detalle."""
    dice: bool = True
    """Si los dados de las tiradas se ven (unidad 18): `false` los oculta."""


def load_table(path: Path) -> Table:
    return Table.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


@dataclass(frozen=True, slots=True)
class Fact:
    priority: int
    order: int
    text: str
    names: tuple[str, ...] = ()
    content: tuple[str, ...] = ()
    alike: str | None = None
    """Clave de agrupación de los hechos ajenos: si hay más de `ALIKE` con la
    misma, el resto se cuenta como uno («y tres más»)."""
    mine: bool = False
    """Lo hizo el jugador o se lo hicieron a él: eso no se resume nunca. En el
    banco, con «frases cortas», el modelo se comió dos «rematas a...» del
    propio jugador entre la violencia ajena."""


class Kind(StrEnum):
    WORLD = "mundo"
    ROUND = "ronda"
    QUESTION = "pregunta"
    OPENING = "apertura"


PROSA_MAX = 1200
"""Lo más largo que se acepta de una narración de turno."""

APERTURA_MAX = 3500
"""Lo más largo que se acepta de la apertura: unas 500 palabras con holgura."""

MOVIMIENTO_DIAS = 7
"""Hasta dónde mira la apertura en el log para contar lo que se mueve (unidad 22)."""

MOVIMIENTO_TOP = 5
"""Cuántos hechos caben en lo que se mueve; lo demás no se cuenta."""


@dataclass(frozen=True, slots=True)
class Notable:
    name: str
    wounded: bool
    doing: str
    """Su acción, «de paso» o «sin hacer nada»."""
    carries: str | None = None
    """Cómo se nombra el arma que lleva puesta (unidad 16a). `None` si no lleva."""


@dataclass(frozen=True, slots=True)
class Scene:
    """Lo que se ve al llegar a una decisión, antes de lo que pasó (unidad 18).
    La lista de gente vive aquí y no en `present`: el briefing no puede tener
    dos listas que se contradigan."""

    full: bool
    """Completa (cambió de sitio, o hubo pelea) o breve."""
    notables: tuple[Notable, ...]
    others: int
    """Los que no caben entre los notables."""
    elapsed: int
    """Ticks desde la decisión anterior."""
    floor: tuple[str, ...] = ()
    """Lo que hay en el suelo del sitio, ya nombrado; con «(xn)» si hay varios
    del mismo. Vacío si no hay nada o el mundo no tiene objetos."""


@dataclass(frozen=True, slots=True)
class Moment:
    kind: Kind
    player: str
    place: str
    description: str | None
    phase: str | None
    present: tuple[str, ...]
    state: tuple[str, ...]
    facts: tuple[Fact, ...]
    veils: tuple[str, ...] = ()
    question: str | None = None
    knowledge: tuple[str, ...] = ()
    everyone: tuple[str, ...] = ()
    """Todos los nombres del censo: lo que el anclaje busca en la prosa."""
    scene: Scene | None = None
    # Lo que solo tiene la apertura (unidad 22). Los momentos de turno los dejan vacíos.
    places: tuple[str, ...] = ()
    """Todos los nombres de lugar del pack: lo que la apertura comprueba en la prosa."""
    premise: tuple[str, ...] = ()
    """El texto del mundo, párrafo a párrafo (`mundo.yaml`). Vacío sin ese archivo."""
    tone: str | None = None
    known: tuple[str, ...] = ()
    neighbors: tuple[str, ...] = ()
    """Los lugares contiguos, con lo que cuesta llegar a cada uno."""
    population: int = 0
    groups: tuple[str, ...] = ()
    """Los grupos más grandes, por nombre."""
    calendar: str | None = None
    who: tuple[str, ...] = ()
    """Quién eres, en líneas: la ficha, y para un residente, su familia y su gremio."""
    moving: tuple[str, ...] = ()
    """Lo que se mueve en los últimos días del log, ya contado."""


@dataclass(frozen=True, slots=True)
class Sighting:
    """Dónde estaba el jugador y con quién en la decisión anterior: quien
    estaba y ya no vive murió delante de él aunque no le conociera."""

    place: str | None = None
    present: frozenset[str] = frozenset()


@dataclass
class Hilos:
    """Lo que sigue abierto entre dos ventanas de narración (unidad 18): quién
    empezó algo contra el jugador y aún no ha acabado, y a quién apuntó él por
    última vez. Sin esto, «Tumi te ataca» no tenía final en la siguiente
    ventana, y «haces un pacto con » salía sin nombre."""

    pending: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Quién → (id de la acción, tick en que empezó). El id, no la etiqueta: de
    él sale el `content` que decide si la mesa lo deja fuera."""
    my_target: str | None = None
    involved: frozenset[str] = frozenset()
    """Quién actuó sobre el jugador o sobre quien él actuó en la última ventana."""


# --- contar un hecho ----------------------------------------------------------


def name_of(world: WorldState, agent: str | None) -> str:
    """El nombre propio: lo que va antes de la primera coma de la etiqueta."""
    if agent is None:
        return "alguien"
    spec = world.censo.get(AgentId(agent))
    return spec.label.split(",")[0] if spec is not None else agent


def tell(
    spec: NarrationSpec | None, label: str, actor: str | None, target: str | None,
    player: str, name: Callable[[str | None], str], d: str = "",
) -> str:
    """El hecho en la forma que toca: tú, otro, o otro sobre ti."""
    a, o = name(actor), name(target) if target is not None else ""
    if spec is None:
        quien = "tú" if actor == player else a
        sobre = "" if target is None else f" ({'a ti' if target == player else o})"
        return f"{quien}: {label}{sobre}{d}"
    if actor == player:
        forma = spec.you
    elif target == player and spec.at_you is not None:
        forma = spec.at_you
    else:
        forma = spec.them
    return forma.format(a=a, o=o, d=d)


def select(
    world: WorldState, events: Iterable[Event], player: str, seen: Sighting, table: Table,
    hilos: Hilos | None = None,
) -> tuple[Fact, ...]:
    """Lo que merece contarse de `events`, de lo más grave a lo menos, y luego
    en el orden en que pasó. Sin vocabulario de mundo: las formas de cada
    acción vienen del pack. `hilos` es lo que sigue abierto de ventanas
    anteriores; sin él, cada ventana empieza de cero (lo que hacen los momentos
    sueltos)."""
    pack = world.pack
    yo = AgentId(player)
    here = str(world.agents[yo].at) if yo in world.agents else seen.place
    hilos = Hilos() if hilos is None else hilos
    events = tuple(events)  # se recorre dos veces: los hechos y los hilos que cierran
    facts: list[Fact] = []
    if yo not in world.agents and DEATH not in table.lines:
        # Nadie emite la muerte de uno para él mismo: `AGENT_DIED` es de quien
        # le llora. Sin esto, la partida acababa sin que nadie te lo contara.
        facts.append(Fact(6, 1 << 62, "caes, y ya no te levantas", (), (DEATH,), mine=True))
    mourned: set[str] = set()
    inv: set[str] = set()

    def name(a: str | None) -> str:
        return name_of(world, a)

    def add(priority: int, e: Event, text: str, names: tuple[str, ...] = (),
            content: tuple[str, ...] = (), alike: str | None = None, mine: bool = True) -> None:
        if any(c in table.lines for c in content) or any(f.text == text for f in facts):
            return
        # Doble de la secuencia: deja un hueco detrás de cada hecho para el
        # resumen de su grupo (ver `_trim`).
        facts.append(Fact(priority, 2 * e.seq, text, names, content, alike, mine))

    for e in events:
        actor = None if e.actor is None else str(e.actor)
        raw = e.data.get("target")
        target = None if raw is None else str(raw)
        spec = pack.action_by_id[e.action] if e.action is not None else None
        content = spec.content if spec is not None else ()
        if e.kind is EventKind.ACTION_STARTED and actor is not None and target is not None:
            if target == player:
                inv.add(actor)
            if actor == player:
                inv.add(target)
        if e.kind is EventKind.ITEM_MOVED:
            # Un objeto que cambia de manos o de puesto: lo tuyo siempre, lo ajeno
            # solo si pasa en tu sitio (como cualquier otro hecho de los demás).
            dicho = _movimiento(world, e, player, name)
            if dicho is not None:
                texto, prioridad, propio = dicho
                if propio or (e.place is not None and str(e.place) == here):
                    add(prioridad, e, texto, (), (), None, propio)
            continue
        if actor == player:
            match e.kind:
                case EventKind.TRAVEL_ARRIVED if e.place is not None:
                    add(3, e, f"llegas a {pack.place_by_id[e.place].label}")
                case EventKind.ACTION_STARTED if spec is not None and target is not None:
                    hilos.my_target = target
                    add(3, e, tell(spec.narration, spec.label, actor, target, player, name),
                        (name(target),), content)
                case EventKind.ACTION_COMPLETED if spec is not None and spec.target is None:
                    # El fin de una acción dirigida no es un hecho: su inicio ya lo
                    # contó, y lo que cambió (la herida, el saqueo) llega por su hecho.
                    add(2, e, tell(spec.narration, spec.label, actor, None, player, name),
                        (), content)
                case EventKind.ACTION_ABORTED if spec is not None:
                    add(2, e, f"dejas a medias: {spec.label}")
                case EventKind.SITUATION_BEGAN:
                    sit = pack.situation_by_id.get(str(e.data.get("situation")))  # type: ignore[call-overload]
                    if sit is not None:
                        add(5, e, f"empieza para ti: {sit.label}", (), sit.content)
                case EventKind.NEED_CRITICAL:
                    need = pack.need_by_id.get(e.data.get("need"))  # type: ignore[call-overload]
                    if need is not None:
                        add(2, e, f"te apremia: {need.label}")
                case EventKind.AGENT_DIED if e.subject is not None:
                    muerto = name(str(e.subject))
                    mourned.add(str(e.subject))
                    text = (f"{muerto}, a quien conocías, muere delante de ti"
                            if e.data.get("testigo")
                            else f"te enteras de que {muerto}, a quien conocías, ha muerto")
                    add(5 if e.data.get("testigo") else 4, e, text, (muerto,), (DEATH,))
                case EventKind.GAME_ENDED:
                    # Solo llega aquí si el ganador es quien juega: el final de otro
                    # lo cuenta `run`, con su nombre (unidad 19).
                    add(6, e, "eres el último en pie")
                case EventKind.RELATION_BEGAN if e.subject is not None:
                    rel = pack.relation_by_id.get(e.data.get("relation"))  # type: ignore[call-overload]
                    etiqueta = rel.label if rel is not None else str(e.data.get("relation"))
                    add(3, e, f"ahora eres {etiqueta} de {name(str(e.subject))}",
                        (name(str(e.subject)),))
            continue
        if (target == player and spec is not None
                and e.kind is EventKind.ACTION_STARTED):
            if actor is not None:
                hilos.pending[actor] = (str(spec.id), str(e.tick))
            add(5, e, tell(spec.narration, spec.label, actor, target, player, name),
                (name(actor),), content)
            continue
        if e.place is None or str(e.place) != here or actor is None:
            continue
        if e.kind is EventKind.ACTION_STARTED and spec is not None and target is not None:
            add(3 if content else 1, e,
                tell(spec.narration, spec.label, actor, target, player, name),
                (name(actor), name(target)), content,
                alike="violenta" if content else str(e.action), mine=False)
        elif e.kind is EventKind.TRAVEL_ARRIVED:
            add(1, e, f"llega {name(actor)}", (name(actor),), alike="llega", mine=False)
    # Ningún hilo suelto (unidad 18): lo que alguien empezó contra el jugador
    # tiene que acabar en algún hecho, aunque se cuente en otra ventana.
    hilos.involved = frozenset(inv | set(hilos.pending))
    # Quien empezó contra el jugador en esta ventana ya tiene su inicio contado:
    # de él, el cierre solo añade un «desiste», nunca otro «termina» ni «sigue».
    empezados_aqui = {str(e.actor) for e in events
                      if e.kind is EventKind.ACTION_STARTED and e.actor is not None
                      and str(e.data.get("target")) == player}
    for a in sorted(hilos.pending):
        accion, _ = hilos.pending[a]
        spec_a = pack.action_by_id[ActionId(accion)]
        aqui = a in empezados_aqui
        cierre = next((e for e in events
                       if e.kind in (EventKind.ACTION_COMPLETED, EventKind.ACTION_ABORTED)
                       and str(e.actor) == a), None)
        if cierre is None:
            # Sin evento no hay orden que dar: va al final. Lleva el `content` de
            # su acción, para que una línea de la mesa lo quite como a cualquier hecho.
            if not aqui and not any(c in table.lines for c in spec_a.content):
                facts.append(Fact(5, 1 << 61, f"{name(a)} sigue yendo a por ti", (name(a),),
                                  spec_a.content))
            continue
        del hilos.pending[a]
        if cierre.kind is EventKind.ACTION_ABORTED:
            add(5, cierre, f"{name(a)} desiste", (name(a),), spec_a.content)
            continue
        if aqui:
            continue
        # Si acabó dejándote una herida, el hecho ya es la herida: no se cuenta dos veces.
        ya_contado = any(e.kind is EventKind.SITUATION_BEGAN and str(e.actor) == player
                         and str(e.data.get("por_quien")) == a for e in events)
        if not ya_contado:
            # Sin `at_you`, la forma de «ellos» pone «ti» donde iría el nombre: los
            # patrones ya traen la preposición («contra {o}», «a {o}»).
            def de_ti(x: str | None) -> str:
                return "ti" if x == player else name(x)

            add(5, cierre, tell(spec_a.narration, spec_a.label, a, player, player, de_ti),
                (name(a),), spec_a.content)
    if here is not None and here == seen.place and DEATH not in table.lines:
        alive = {str(a) for a in world.agents}
        for muerto in sorted(seen.present - alive - mourned - {player}):
            facts.append(Fact(4, 1 << 62, f"el cuerpo de {name(muerto)} yace aquí",
                              (name(muerto),), (DEATH,), mine=False))
    return _trim(facts)


def _movimiento(
    world: WorldState, e: Event, player: str, name: Callable[[str | None], str],
) -> tuple[str, int, bool] | None:
    """Lo que cuenta un objeto que cambia de manos o de puesto: texto, prioridad y
    si es del jugador. El nombre del objeto sale del pack; las formas («coges»,
    «te quita») son del narrador, como «llegas a». `de` y `a` son `lugar:<id>`
    o `agente:<id>` (ver `Simulation._mover_objeto`)."""
    spec = world.pack.item_by_id.get(ItemId(str(e.data.get("item"))))
    if spec is None:
        return None
    nombre = spec.narration or spec.label
    yo = f"agente:{player}"
    de = str(e.data.get("de"))
    a = str(e.data.get("a"))
    actor = None if e.actor is None else str(e.actor)
    if a == "gastado":
        # Se come, se cura: lo gasta quien lo lleva, y solo se cuenta si es del jugador.
        return (f"gastas {nombre}", 3, True) if actor == player else None
    if de == a:
        # Se puso o se quitó: solo cuenta si es del jugador.
        if actor != player:
            return None
        return (f"te pones {nombre}" if e.data.get("puesto") else f"te quitas {nombre}", 3, True)
    if a == yo:
        if de.startswith("lugar:"):
            return (f"coges {nombre}", 3, True)
        donante = de.removeprefix("agente:")
        if actor == player:
            return (f"consigues {nombre} de {name(donante)}", 3, True)
        if actor == donante:
            return (f"{name(actor)} te da {nombre}", 3, True)
        return None
    if de == yo:
        if a.startswith("lugar:") or actor is None:
            return None
        receptor = a.removeprefix("agente:")
        if actor == player:
            return (f"le das {nombre} a {name(receptor)}", 3, True)
        return (f"{name(actor)} te quita {nombre}", 5, True)
    if actor is not None and de.startswith("lugar:") and a.startswith("agente:"):
        return (f"{name(actor)} coge {nombre}", 1, False)
    return None


def _trim(facts: list[Fact]) -> tuple[Fact, ...]:
    grupos: dict[str, list[Fact]] = {}
    for f in facts:
        if f.alike is not None:
            grupos.setdefault(f.alike, []).append(f)
    for grupo in grupos.values():
        if len(grupo) > ALIKE:
            resto = grupo[ALIKE:]
            facts = [f for f in facts if f not in resto]
            # Justo detrás del último que se cuenta: ordenado por el primero de
            # los resumidos, caía detrás de otra cosa («llega Sami») y el
            # modelo lo leyó como «y llegan muchos más».
            facts.append(Fact(resto[0].priority - 1, grupo[ALIKE - 1].order + 1,
                              f"y {len(resto)} más así a tu alrededor", (), resto[0].content,
                              mine=False))
    facts.sort(key=lambda f: (-f.priority, f.order))
    kept = facts[:TOP]
    kept.sort(key=lambda f: f.order)
    return tuple(kept)


# --- los momentos ---------------------------------------------------------------


def _phase(world: WorldState) -> str | None:
    clock = world.pack.clock
    pid = clock.phase_at(world.tick)
    return next((p.label for p in clock.phases if p.id == pid), None) if pid is not None else None


def _state(world: WorldState, player: str) -> tuple[str, ...]:
    """Lo que el personaje nota de sí mismo: las carencias de la ficha, la
    misma puerta que usa la voz."""
    return tuple(f"te falta {need}: {lack.value}"
                 for need, lack in ficha(world, AgentId(player)).carencias)


def _base(world: WorldState, player: str, kind: Kind, facts: tuple[Fact, ...],
          table: Table, last_place: str | None = None) -> Moment:
    a = world.agents.get(AgentId(player))
    where = a.at if a is not None else last_place
    place = world.pack.place_by_id[where] if where is not None else None  # type: ignore[index]
    present = tuple(name_of(world, str(o.spec_id)) for o in world.agents_in_order()
                    if a is not None and o.at == a.at and o is not a)
    veils = tuple(sorted({c for f in facts for c in f.content if c in table.veils}))
    return Moment(
        kind=kind, player=name_of(world, player), place=place.label if place else "-",
        description=place.description if place else None, phase=_phase(world),
        present=present, state=_state(world, player) if a is not None else (),
        facts=facts, veils=veils,
        everyone=tuple(sorted({name_of(world, str(x)) for x in world.censo})),
    )


def world_moment(world: WorldState, player: str, facts: tuple[Fact, ...], table: Table,
                 last_place: str | None = None, scene: Scene | None = None) -> Moment:
    return replace(_base(world, player, Kind.WORLD, facts, table, last_place), scene=scene)


def scene_of(
    world: WorldState, player: str, seen: Sighting, involved: frozenset[str],
    last_was_fight: bool, elapsed: int,
) -> Scene:
    """La escena de ahora. Notables: primero quien actuó sobre el jugador o él
    sobre quien, luego a quien aprecia o con quien tiene relación (de más a
    menos aprecio), luego quien se ve herido, y el resto por nombre. Desempate
    por id: el nombre puede repetirse y el orden no puede depender de eso.

    Completa si cambió de sitio, si es la primera decisión o si acabó una
    pelea; breve si no."""
    yo = world.agents.get(AgentId(player))
    if yo is None:
        return Scene(full=True, notables=(), others=0, elapsed=elapsed)
    full = seen.place is None or seen.place != str(yo.at) or last_was_fight
    visibles = frozenset(sid for sid, spec in world.pack.situation_by_id.items() if spec.visible)
    candidatos: list[tuple[tuple[int, int, float, int, str, str], Notable]] = []
    for o in world.agents_in_order():
        if o is yo or o.at != yo.at:
            continue
        otro = o.spec_id
        aprecio = yo.regard_for(otro, world.tick, yo.temperament.bond_fade,
                                yo.relation_floor(world.pack, otro))
        apreciado = aprecio > 0 or bool(yo.related_to(otro))
        herido = any(c.situacion in visibles for c in o.condiciones)
        match o.busy:
            case PerformingAction(action=accion):
                haciendo = world.pack.action_by_id[accion].label
            case Traveling():
                haciendo = "de paso"
            case _:
                haciendo = "sin hacer nada"
        nombre = name_of(world, str(otro))
        clave = (0 if str(otro) in involved else 1, 0 if apreciado else 1,
                 -aprecio if apreciado else 0.0, 0 if herido else 1, nombre, str(otro))
        candidatos.append((clave, Notable(nombre, herido, haciendo, _arma_puesta(world, otro))))
    candidatos.sort(key=lambda par: par[0])
    notables = tuple(n for _, n in candidatos[:TOP_NOTABLES])
    return Scene(full, notables, max(0, len(candidatos) - TOP_NOTABLES), elapsed,
                 _suelo(world, yo.at))


def _arma_puesta(world: WorldState, quien: AgentId) -> str | None:
    """Cómo se nombra lo que lleva en la mano, si lleva algo (unidad 16a)."""
    for p in world.objetos_de(quien):
        if p.equipado:
            spec = world.pack.item_by_id[ItemId(p.objeto)]
            if spec.slot is ItemSlot.ARMA:
                return spec.narration or spec.label
    return None


def _suelo(world: WorldState, lugar: PlaceId) -> tuple[str, ...]:
    """Lo del suelo, agrupado por clase de objeto. Sin plural en el pack, un
    grupo se cuenta como «(xn)» tras el nombre: no inventa una forma."""
    cuenta: dict[str, int] = {}
    for p in world.objetos_en(lugar):
        cuenta[p.objeto] = cuenta.get(p.objeto, 0) + 1
    partes: list[str] = []
    for item_id, n in sorted(cuenta.items()):
        spec = world.pack.item_by_id[ItemId(item_id)]
        nombre = spec.narration or spec.label
        partes.append(nombre if n == 1 else f"{nombre} (x{n})")
    return tuple(partes)


def question_moment(
    world: WorldState, player: str, question: str, nearest: Mapping[str, tuple[str, int]],
    table: Table,
) -> Moment:
    """`nearest`: etiqueta de acción -> (el sitio más cercano donde se puede,
    cuartos de viaje), sacado del menú del jugador: lo que sabe que hay, no lo
    que hay (percepción limitada)."""
    m = _base(world, player, Kind.QUESTION, (), table)
    saber = [ln.strip() for ln in ficha(world, AgentId(player)).lines()]
    saber += [f"{CAN}{accion}: en {lugar}, " + ("aquí" if t == 0 else "a 1 cuarto de hora" if t == 1
                                                 else f"a {t} cuartos de hora")
              for accion, (lugar, t) in sorted(nearest.items())]
    return Moment(m.kind, m.player, m.place, m.description, m.phase, m.present, m.state, (),
                  m.veils, question, tuple(saber), m.everyone)


@dataclass(frozen=True, slots=True)
class BeatView:
    """Un `Beat` de la escena visto desde fuera de `rules/`: lo traduce
    `play.py`, que sabe qué es cada combatiente."""

    order: int
    kind: str
    actor: str
    target: str | None
    outcome: str | None
    band: str
    """«, un roce», «, un buen golpe», «, un golpe brutal» o nada: el daño sin
    números, que el narrador no debe recitar."""
    label: str


def round_facts(
    beats: Sequence[BeatView], player: str, name: Callable[[str | None], str],
    narration: Mapping[str, NarrationSpec], content: Mapping[str, tuple[str, ...]],
    table: Table,
) -> tuple[Fact, ...]:
    facts = []
    for b in beats:
        tags = content.get(b.kind, ())
        if any(c in table.lines for c in tags):
            continue
        spec = narration.get(f"{b.kind}.{b.outcome}") or narration.get(b.kind)
        text = tell(spec, b.label, b.actor, b.target, player, name, b.band)
        nombres = tuple(name(x) for x in (b.actor, b.target) if x is not None and x != player)
        facts.append(Fact(3, b.order, text, nombres, tags,
                          mine=player in (b.actor, b.target)))
    return tuple(facts)


def round_moment(world: WorldState, player: str, facts: tuple[Fact, ...],
                 state: tuple[str, ...], present: tuple[str, ...], table: Table) -> Moment:
    m = _base(world, player, Kind.ROUND, facts, table)
    return Moment(m.kind, m.player, m.place, None, m.phase, present, state, facts,
                  m.veils, everyone=m.everyone)


# --- briefing, anclaje, respaldo ------------------------------------------------


VEIL = ("\n- Con lo que toque {cosas}: dilo, sin detalle gráfico ni regodeo; "
        "una frase sobria basta.")


def _ha_pasado(ticks: int) -> str:
    """Un cuarto de hora por tick: a partir de dos horas se dice en horas."""
    return (f"HA PASADO: {ticks} cuartos de hora" if ticks < 8
            else f"HA PASADO: {ticks // 4} horas")


def _escena(s: Scene) -> list[str]:
    lines = [f"ESCENA AHORA ({'completa' if s.full else 'breve'}):"]
    for n in s.notables:
        partes = ["herido"] if n.wounded else []
        if n.carries is not None:
            partes.append(f"lleva {n.carries}")
        lines.append(f"  - {n.name}: {', '.join([*partes, n.doing])}")
    if s.others:
        lines.append(f"  - y otros {s.others}")
    if not s.notables:
        lines.append("  - nadie más")
    if s.floor:
        lines.append(f"  - en el suelo: {', '.join(s.floor)}")
    return lines


def _lista(partes: list[str]) -> str:
    if len(partes) <= 1:
        return "".join(partes)
    return ", ".join(partes[:-1]) + " y " + partes[-1]


def briefing(m: Moment) -> str:
    if m.kind is Kind.OPENING:
        return _briefing_apertura(m)
    lines = [f"PERSONAJE: {m.player} (el jugador: tú)", f"LUGAR: {m.place}"]
    if m.description:
        lines.append(f"CÓMO ES: {m.description}")
    if m.phase:
        lines.append(f"HORA: {m.phase}")
    if m.scene is not None:
        if m.scene.elapsed >= 4:
            lines.append(_ha_pasado(m.scene.elapsed))
        lines += _escena(m.scene)
    elif m.present:
        extra = f" y {len(m.present) - 6} más" if len(m.present) > 6 else ""
        lines.append(f"AQUÍ HAY: {', '.join(m.present[:6])}{extra}")
    else:
        lines.append("AQUÍ HAY: nadie más")
    if m.state:
        lines.append("ESTADO: " + "; ".join(m.state))
    veils = VEIL.format(cosas=" o ".join(m.veils)) if m.veils else ""
    if m.kind is Kind.QUESTION:
        lines.append("LO QUE SABES:")
        lines += [f"  - {s}" for s in m.knowledge]
        return ANSWER.format(velos=veils, contexto="\n".join(lines), pregunta=m.question)
    lines.append("HECHOS:")
    lines += [f"  {i}. {'(TUYO) ' if f.mine else ''}{f.text}"
              for i, f in enumerate(m.facts, start=1)]
    frases = "una a tres frases" if len(m.facts) <= 3 else "tres a cinco frases"
    return TELL.format(frases=frases, velos=veils, contexto="\n".join(lines))


class Narration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    prosa: str = Field(min_length=1, max_length=1200)


def strangers(m: Moment, prose: str) -> tuple[str, ...]:
    """Nombres del censo, y lugares del pack, que la prosa dice y el briefing no.
    Basta uno para descartar la narración: es la única invención que se puede
    comprobar sin otro modelo, y la que más rompe la mesa (un muerto que reaparece,
    un lugar que no está). Los lugares solo se miran en la apertura, que es la única
    que los nombra por su cuenta; un turno solo nombra gente."""
    told = briefing(m)

    def says(text: str, n: str) -> bool:
        return re.search(rf"\b{re.escape(n)}\b", text) is not None

    nombres = tuple(n for n in m.everyone if says(prose, n) and not says(told, n))
    lugares = tuple(p for p in m.places if says(prose, p) and not says(told, p))
    return nombres + lugares


def fallback(m: Moment) -> str:
    if m.kind is Kind.OPENING:
        return _apertura_plantilla(m)
    if m.kind is Kind.QUESTION:
        # Lo que sabe y comparte alguna palabra con la pregunta: «¿dónde puedo
        # beber agua?» encuentra «beber: en la cornucopia», con las mismas
        # raíces que el léxico del intérprete (una sola puerta).
        pide = set(stems(m.question or ""))
        utiles = [k for k in m.knowledge
                  if k.startswith(CAN) and pide & set(stems(k[len(CAN):].split(":")[0]))]
        return (" ".join(f"{k[0].upper()}{k[1:]}." for k in utiles[:4])
                or "Sin el narrador no sé contestarte eso; prueba «ficha» o «mirar».")
    partes = [f.text[0].upper() + f.text[1:] + "." for f in m.facts]
    if m.scene is not None:
        partes += _escena_plantilla(m, m.scene)
    return " ".join(partes)


def _escena_plantilla(m: Moment, s: Scene) -> list[str]:
    if not s.full:
        return [f"Sigues en {m.place}."]
    items = [f"{n.name} (herido)" if n.wounded else n.name for n in s.notables]
    if s.others:
        items.append(f"otros {s.others}")
    aqui = f"Aquí: {_lista(items)}." if items else "Aquí: nadie más."
    return [f"Estás en {m.place}.", *([m.description] if m.description else []), aqui]


GRUPOS_TOP = 5
"""Cuántos grupos, por tamaño, caben en la apertura."""

PRIORIDAD_MOVIMIENTO = {
    EventKind.AGENT_DIED: 0,
    EventKind.FACTION_FOUNDED: 1,
    EventKind.FACTIONS_AT_ODDS: 1,
    EventKind.AGENT_BORN: 2,
    EventKind.RELATION_BEGAN: 3,
    EventKind.RELATION_ENDED: 3,
    EventKind.RANK_UP: 4,
}
"""Qué se cuenta primero de lo que se mueve (unidad 22): la muerte antes que el
nacimiento, y así. Dentro de cada prioridad, lo más reciente."""


def opening_moment(
    world: WorldState, player: str, events: Iterable[Event], table: Table
) -> Moment:
    """La apertura (unidad 22): el mundo, dónde llegas y quién eres, y lo que se
    mueve. Solo lee: nada de esto cambia el mundo (regla 1)."""
    pack = world.pack
    base = _base(world, player, Kind.OPENING, (), table)
    yo = world.agents.get(AgentId(player))
    estados = list(base.state)
    vecinos: tuple[str, ...] = ()
    quien: tuple[str, ...] = ()
    if yo is not None:
        estados += [f"eres {pack.situation_by_id[c.situacion].label}"
                    for c in yo.condiciones if pack.situation_by_id[c.situacion].personal]
        lugar = pack.place_by_id[yo.at]
        vecinos = tuple(
            f"{pack.place_by_id[n].label} (a {_minutos(t * pack.clock.minutes_per_tick)})"
            for n, t in sorted(lugar.neighbors.items(), key=lambda par: (par[1], str(par[0])))
        )
        quien = _quien_eres(world, player)
    grupos = sorted(world.facciones.values(),
                    key=lambda f: (-len(world.miembros_de(f.id)), str(f.id)))
    lore = pack.world
    return replace(
        base,
        state=tuple(estados),
        places=tuple(sorted({p.label for p in pack.places})),
        premise=tuple(p.strip() for p in lore.premise.split("\n\n") if p.strip()) if lore else (),
        tone=lore.tone if lore else None,
        known=tuple(lore.known) if lore else (),
        neighbors=vecinos,
        population=len(world.agents),
        groups=tuple(f.label for f in grupos[:GRUPOS_TOP]),
        calendar=f"día {world.tick // pack.clock.ticks_per_day + 1}",
        who=quien,
        moving=_se_mueve(world, events),
    )


def _minutos(minutos: int) -> str:
    return f"{minutos} minutos"


def _quien_eres(world: WorldState, player: str) -> tuple[str, ...]:
    """Lo que el personaje sabe de sí: identidad, carácter, a quién aprecia o detesta,
    y para un residente, su familia y su gremio. Un forastero no conoce a nadie: sus
    listas de gente salen vacías porque no tiene nada que nombrar. Lo que falta
    (carencias) ya está en el ESTADO, y no se repite aquí."""
    yo = world.agents[AgentId(player)]
    f = ficha(world, AgentId(player))
    lineas: list[str] = []
    if f.identidad:
        lineas.append(f"identidad: {', '.join(f.identidad)}")
    if f.caracter:
        lineas.append(f"carácter: {', '.join(f.caracter)}")
    if f.aprecia:
        lineas.append(f"aprecia a: {', '.join(f.aprecia)}")
    if f.detesta:
        lineas.append(f"detesta a: {', '.join(f.detesta)}")
    for rel, quienes in sorted(yo.relations.items()):
        spec = world.pack.relation_by_id.get(rel)
        etiqueta = rel if spec is None else spec.label
        lineas += [f"{etiqueta}: {name_of(world, str(otro))}" for otro in sorted(quienes)]
    for fid in sorted(yo.lealtad):
        grupo = world.facciones.get(fid)
        if grupo is not None:
            lineas.append(f"gremio: {grupo.label}")
    return tuple(lineas)


def _se_mueve(world: WorldState, events: Iterable[Event]) -> tuple[str, ...]:
    """Lo notable de los últimos días, en frases (unidad 22). Una muerte cuenta una
    vez por víctima, aunque la emitan todos sus dolientes (`AGENT_DIED` se repite
    por superviviente). Por prioridad y, dentro de cada una, lo más reciente."""
    desde = world.tick - MOVIMIENTO_DIAS * world.pack.clock.ticks_per_day
    recientes = sorted(
        (e for e in events if e.tick >= desde and e.kind in PRIORIDAD_MOVIMIENTO),
        key=lambda e: -e.seq,
    )
    muertos: set[str] = set()
    hechos: list[tuple[int, int, str]] = []
    for e in recientes:
        texto = _hecho_que_se_mueve(world, e, muertos)
        if texto is not None:
            hechos.append((PRIORIDAD_MOVIMIENTO[e.kind], -e.seq, texto))
    hechos.sort()
    return tuple(texto for _, _, texto in hechos[:MOVIMIENTO_TOP])


def _hecho_que_se_mueve(world: WorldState, e: Event, muertos: set[str]) -> str | None:
    pack = world.pack

    def dato(clave: str) -> str | None:
        valor = e.data.get(clave)
        return None if valor is None else str(valor)

    match e.kind:
        case EventKind.AGENT_DIED:
            victima = None if e.subject is None else str(e.subject)
            if victima is None or victima in muertos:
                return None
            muertos.add(victima)
            return f"ha muerto {name_of(world, victima)}"
        case EventKind.AGENT_BORN if e.actor is not None:
            return f"ha nacido {name_of(world, str(e.actor))}"
        case EventKind.FACTION_FOUNDED if dato("faccion") is not None:
            return f"se funda {_grupo(world, dato('faccion') or '')}"
        case EventKind.FACTIONS_AT_ODDS if dato("una") and dato("otra"):
            return (f"{_grupo(world, dato('una') or '')} y "
                    f"{_grupo(world, dato('otra') or '')} se enfrentan")
        case EventKind.RELATION_BEGAN | EventKind.RELATION_ENDED if (
            dato("relation") is not None and e.subject is not None
        ):
            pareja = f"{name_of(world, str(e.actor))} y {name_of(world, str(e.subject))}"
            rel = RelationId(dato("relation") or "")
            spec = pack.relation_by_id.get(rel)
            etiqueta = str(rel) if spec is None else spec.label
            if e.kind is EventKind.RELATION_BEGAN:
                return f"{pareja} son ahora {etiqueta}"
            return f"{pareja} ya no son {etiqueta}"
        case EventKind.RANK_UP if dato("need") is not None and e.actor is not None:
            eje = NeedId(dato("need") or "")
            spec_eje = pack.need_by_id.get(eje)
            etiqueta = str(eje) if spec_eje is None else spec_eje.label
            return f"{name_of(world, str(e.actor))} sube de rango en {etiqueta}"
    return None


def _grupo(world: WorldState, faccion: str) -> str:
    grupo = world.facciones.get(FactionId(faccion))
    return faccion if grupo is None else grupo.label


def _briefing_apertura(m: Moment) -> str:
    lines: list[str] = []
    if m.premise or m.tone or m.known:
        lines.append("MUNDO:")
        lines += [f"  {p}" for p in m.premise]
        if m.tone:
            lines.append(f"TONO: {m.tone}")
        if m.known:
            lines.append("TODOS SABEN:")
            lines += [f"  - {k}" for k in m.known]
    lines += [f"PERSONAJE: {m.player} (tú)", f"LUGAR: {m.place}"]
    if m.description:
        lines.append(f"CÓMO ES: {m.description}")
    if m.calendar:
        lines.append(f"CUÁNDO: {m.calendar}")
    if m.phase:
        lines.append(f"HORA: {m.phase}")
    if m.neighbors:
        lines.append("LUGARES CONTIGUOS: " + "; ".join(m.neighbors))
    if m.present:
        extra = f" y {len(m.present) - 6} más" if len(m.present) > 6 else ""
        lines.append(f"AQUÍ HAY: {', '.join(m.present[:6])}{extra}")
    else:
        lines.append("AQUÍ HAY: nadie más")
    if m.population:
        lines.append(f"EN EL MUNDO VIVEN: {m.population} personas")
    if m.groups:
        lines.append("GRUPOS MÁS GRANDES: " + "; ".join(m.groups))
    if m.state:
        lines.append("ESTADO: " + "; ".join(m.state))
    if m.who:
        lines.append("QUIÉN ERES:")
        lines += [f"  {w}" for w in m.who]
    if m.moving:
        lines.append("LO QUE SE MUEVE:")
        lines += [f"  - {x}" for x in m.moving]
    return OPENING_PROMPT.format(contexto="\n".join(lines))


def _apertura_plantilla(m: Moment) -> str:
    """Sin modelo, o si el modelo nombra a alguien o a un lugar que no se le dio: el
    mundo, luego la llegada con sus vecinos, luego quién eres, y lo que se mueve."""
    parrafos = list(m.premise)
    llegada = f"Llegas a {m.place}."
    if m.description:
        llegada += f" {m.description}"
    if m.neighbors:
        llegada += f" Desde aquí se llega a {_lista(list(m.neighbors))}."
    if m.present:
        extra = f" y {len(m.present) - 6} más" if len(m.present) > 6 else ""
        llegada += f" Aquí: {_lista(list(m.present[:6]))}{extra}."
    else:
        llegada += " Aquí: nadie más."
    parrafos.append(llegada)
    quien = [f"Eres {m.player}."]
    quien += [f"{s[0].upper()}{s[1:]}." for s in m.state]
    quien += [f"{w[0].upper()}{w[1:]}." for w in m.who]
    parrafos.append(" ".join(quien))
    if m.moving:
        parrafos.append(f"Lo que se mueve: {_lista(list(m.moving))}.")
    return "\n\n".join(parrafos)


@dataclass(frozen=True, slots=True)
class Told:
    text: str
    by: int | None
    """Qué proveedor de la cadena lo contó; `None` es la plantilla."""


def narrate(m: Moment, providers: Sequence[CognitionProvider], seed: int) -> Told:
    """La prosa se pide entera y sola (20a): el modelo devuelve el texto, no un
    JSON que hubiera que desenvolver. Se valida igual que antes (longitud y
    nombres de fuera); lo que no pase, lo cuenta el siguiente proveedor, o la
    plantilla. `Narration` se acepta por quien aún la devuelva."""
    return narrate_con_motivos(m, providers, seed)[0]


def narrate_con_motivos(
    m: Moment, providers: Sequence[CognitionProvider], seed: int
) -> tuple[Told, tuple[str, ...]]:
    """Lo mismo que `narrate`, y además por qué cada proveedor no valió (el banco de
    aperturas lo muestra). Una sola puerta: `narrate` no tiene otra lógica."""
    texto = briefing(m)
    motivos: list[str] = []
    for i, p in enumerate(providers):
        out = p.think(texto, str, seed)
        prosa = out.prosa if isinstance(out, Narration) else out if isinstance(out, str) else None
        if prosa is None:
            motivos.append(f"proveedor {i}: sin respuesta")
            continue
        prosa = prosa.strip()
        tope = APERTURA_MAX if m.kind is Kind.OPENING else PROSA_MAX
        if not 1 <= len(prosa) <= tope:
            motivos.append(f"proveedor {i}: longitud {len(prosa)}")
            continue
        nombres = strangers(m, prosa)
        if nombres:
            motivos.append(f"proveedor {i}: nombra a {', '.join(nombres)}")
            continue
        return Told(prosa, i), tuple(motivos)
    return Told(fallback(m), None), tuple(motivos)


def _seed(world: WorldState, player: str, what: str) -> int:
    return world.rng.stream("narrador", what, player, world.tick).randrange(2**31)


def semilla_de_apertura(world: WorldState, player: str) -> int:
    """La semilla de la apertura: la misma para la partida y para el banco."""
    return _seed(world, player, "apertura")


@dataclass
class Narrator:
    """El narrador de una partida: la cadena de proveedores (D-166: su propia
    instancia, no la del intérprete ni la de la voz), la mesa, y dónde estaba
    el jugador la última vez que se contó algo."""

    providers: tuple[CognitionProvider, ...]
    table: Table
    seen: Sighting = Sighting()
    hilos: Hilos = field(default_factory=Hilos)
    last_tick: int | None = None
    """Cuándo fue la decisión anterior: de ahí sale «HA PASADO»."""
    last_was_fight: bool = False
    """Acabó una escena de combate desde la última narración. La marca quien
    lleva la pelea (`TerminalCombat.report`) y la gasta la siguiente narración."""
    opening_providers: tuple[CognitionProvider, ...] | None = None
    """La cadena de la apertura, si la prosa de la apertura necesita más tokens que
    la de un turno (unidad 22). `None` = la misma cadena."""

    def world(self, world: WorldState, events: Iterable[Event], player: str) -> Told:
        """Siempre hay momento: aunque no pase nada, la escena se cuenta (unidad 18)."""
        facts = select(world, events, player, self.seen, self.table, self.hilos)
        elapsed = 0 if self.last_tick is None else world.tick - self.last_tick
        scene = scene_of(world, player, self.seen, self.hilos.involved,
                         self.last_was_fight, elapsed)
        self.last_was_fight = False
        self.last_tick = world.tick
        last = self.seen.place
        a = world.agents.get(AgentId(player))
        if a is not None:
            self.seen = Sighting(str(a.at), frozenset(
                str(o.spec_id) for o in world.agents_in_order() if o.at == a.at))
        m = world_moment(world, player, facts, self.table, last, scene)
        return narrate(m, self.providers, _seed(world, player, "mundo"))

    def opening(self, world: WorldState, player: str, events: Iterable[Event]) -> Told:
        """La apertura (unidad 22): una vez, antes del primer turno. Deja al narrador
        donde está el jugador, para que el primer turno cuente lo que pase desde aquí
        y no la escena entera otra vez."""
        m = opening_moment(world, player, events, self.table)
        cadena = self.providers if self.opening_providers is None else self.opening_providers
        told = narrate(m, cadena, semilla_de_apertura(world, player))
        a = world.agents.get(AgentId(player))
        if a is not None:
            self.seen = Sighting(str(a.at), frozenset(
                str(o.spec_id) for o in world.agents_in_order() if o.at == a.at))
        self.last_tick = world.tick
        return told

    def answer(self, world: WorldState, player: str, question: str,
               nearest: Mapping[str, tuple[str, int]]) -> Told:
        m = question_moment(world, player, question, nearest, self.table)
        return narrate(m, self.providers, _seed(world, player, "pregunta"))

    def round(self, world: WorldState, player: str, facts: tuple[Fact, ...],
              state: tuple[str, ...], present: tuple[str, ...], key: str) -> Told | None:
        """`key`: la escena y la ronda, para que dos rondas del mismo tick no
        compartan semilla."""
        if not facts:
            return None
        m = round_moment(world, player, facts, state, present, self.table)
        return narrate(m, self.providers, _seed(world, player, key))


def moment_to_json(m: Moment) -> dict[str, object]:
    """Un momento como dato, para el banco de narración: se graba jugando y se
    narra después, sin volver a simular."""
    d = asdict(m)
    d["kind"] = m.kind.value
    return d


def moment_from_json(d: Mapping[str, Any]) -> Moment:
    facts = tuple(
        Fact(f["priority"], f["order"], f["text"], tuple(f["names"]), tuple(f["content"]),
             f.get("alike"), f.get("mine", False))
        for f in d["facts"]
    )
    return Moment(
        kind=Kind(d["kind"]), player=d["player"], place=d["place"],
        description=d.get("description"), phase=d.get("phase"), present=tuple(d["present"]),
        state=tuple(d["state"]), facts=facts, veils=tuple(d["veils"]),
        question=d.get("question"), knowledge=tuple(d["knowledge"]),
        everyone=tuple(d["everyone"]), scene=_scene_from_json(d.get("scene")),
    )


def _scene_from_json(d: Mapping[str, Any] | None) -> Scene | None:
    if d is None:
        return None
    return Scene(
        full=d["full"],
        notables=tuple(
            Notable(n["name"], n["wounded"], n["doing"], n.get("carries"))
            for n in d["notables"]
        ),
        others=d["others"], elapsed=d["elapsed"],
        floor=tuple(d.get("floor", ())),
    )
