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
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agora.cognition.intencion import stems
from agora.engine.consulta import ficha
from agora.engine.events import Event, EventKind
from agora.engine.ontology import AgentId, ContentTag, NarrationSpec, Spec
from agora.engine.ports import CognitionProvider
from agora.engine.state import WorldState

PROMPTS = Path(__file__).parent / "prompts"
TELL = (PROMPTS / "narrador.txt").read_text(encoding="utf-8")
ANSWER = (PROMPTS / "pregunta.txt").read_text(encoding="utf-8")

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


class Table(Spec):
    """Lo que la mesa acordó antes de jugar (sesión cero). Es de la mesa y no
    del mundo: la misma isla se juega con líneas distintas en mesas distintas."""

    lines: tuple[ContentTag, ...] = ()
    """No se narra: el motor lo simula igual, pero queda fuera de plano."""
    veils: tuple[ContentTag, ...] = ()
    """Se narra sin detalle."""


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


@dataclass(frozen=True, slots=True)
class Sighting:
    """Dónde estaba el jugador y con quién en la decisión anterior: quien
    estaba y ya no vive murió delante de él aunque no le conociera."""

    place: str | None = None
    present: frozenset[str] = frozenset()


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
) -> tuple[Fact, ...]:
    """Lo que merece contarse de `events`, de lo más grave a lo menos, y luego
    en el orden en que pasó. Sin vocabulario de mundo: las formas de cada
    acción vienen del pack."""
    pack = world.pack
    yo = AgentId(player)
    here = str(world.agents[yo].at) if yo in world.agents else seen.place
    facts: list[Fact] = []
    if yo not in world.agents and DEATH not in table.lines:
        # Nadie emite la muerte de uno para él mismo: `AGENT_DIED` es de quien
        # le llora. Sin esto, la partida acababa sin que nadie te lo contara.
        facts.append(Fact(6, 1 << 62, "caes, y ya no te levantas", (), (DEATH,), mine=True))
    target_of: dict[str, str] = {}
    mourned: set[str] = set()

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
            target_of[actor] = target
        if actor == player:
            match e.kind:
                case EventKind.TRAVEL_ARRIVED if e.place is not None:
                    add(3, e, f"llegas a {pack.place_by_id[e.place].label}")
                case EventKind.ACTION_STARTED if spec is not None and target is not None:
                    add(3, e, tell(spec.narration, spec.label, actor, target, player, name),
                        (name(target),), content)
                case EventKind.ACTION_COMPLETED if spec is not None:
                    t = target_of.get(player) if spec.target is not None else None
                    add(2, e, tell(spec.narration, spec.label, actor, t, player, name),
                        (name(t),) if t is not None else (), content)
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
                case EventKind.RELATION_BEGAN if e.subject is not None:
                    rel = pack.relation_by_id.get(e.data.get("relation"))  # type: ignore[call-overload]
                    etiqueta = rel.label if rel is not None else str(e.data.get("relation"))
                    add(3, e, f"ahora eres {etiqueta} de {name(str(e.subject))}",
                        (name(str(e.subject)),))
            continue
        if (target == player and spec is not None
                and e.kind is EventKind.ACTION_STARTED):
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
    if here is not None and here == seen.place and DEATH not in table.lines:
        alive = {str(a) for a in world.agents}
        for muerto in sorted(seen.present - alive - mourned - {player}):
            facts.append(Fact(4, 1 << 62, f"el cuerpo de {name(muerto)} yace aquí",
                              (name(muerto),), (DEATH,), mine=False))
    return _trim(facts)


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
                 last_place: str | None = None) -> Moment:
    return _base(world, player, Kind.WORLD, facts, table, last_place)


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


def briefing(m: Moment) -> str:
    lines = [f"PERSONAJE: {m.player} (el jugador: tú)", f"LUGAR: {m.place}"]
    if m.description:
        lines.append(f"CÓMO ES: {m.description}")
    if m.phase:
        lines.append(f"HORA: {m.phase}")
    if m.present:
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
    """Nombres del censo que la prosa dice y el briefing no. Basta uno para
    descartar la narración: es la única invención que se puede comprobar sin
    otro modelo, y la que más rompe la mesa (un muerto que reaparece)."""
    told = briefing(m)

    def says(text: str, n: str) -> bool:
        return re.search(rf"\b{re.escape(n)}\b", text) is not None

    return tuple(n for n in m.everyone if says(prose, n) and not says(told, n))


def fallback(m: Moment) -> str:
    if m.kind is Kind.QUESTION:
        # Lo que sabe y comparte alguna palabra con la pregunta: «¿dónde puedo
        # beber agua?» encuentra «beber: en la cornucopia», con las mismas
        # raíces que el léxico del intérprete (una sola puerta).
        pide = set(stems(m.question or ""))
        utiles = [k for k in m.knowledge
                  if k.startswith(CAN) and pide & set(stems(k[len(CAN):].split(":")[0]))]
        return (" ".join(f"{k[0].upper()}{k[1:]}." for k in utiles[:4])
                or "Sin el narrador no sé contestarte eso; prueba «ficha» o «mirar».")
    return " ".join(f.text[0].upper() + f.text[1:] + "." for f in m.facts)


@dataclass(frozen=True, slots=True)
class Told:
    text: str
    by: int | None
    """Qué proveedor de la cadena lo contó; `None` es la plantilla."""


def narrate(m: Moment, providers: Sequence[CognitionProvider], seed: int) -> Told:
    texto = briefing(m)
    for i, p in enumerate(providers):
        out = p.think(texto, Narration, seed)
        if isinstance(out, Narration) and not strangers(m, out.prosa):
            return Told(out.prosa, i)
    return Told(fallback(m), None)


def _seed(world: WorldState, player: str, what: str) -> int:
    return world.rng.stream("narrador", what, player, world.tick).randrange(2**31)


@dataclass
class Narrator:
    """El narrador de una partida: la cadena de proveedores (D-166: su propia
    instancia, no la del intérprete ni la de la voz), la mesa, y dónde estaba
    el jugador la última vez que se contó algo."""

    providers: tuple[CognitionProvider, ...]
    table: Table
    seen: Sighting = Sighting()

    def world(self, world: WorldState, events: Iterable[Event], player: str) -> Told | None:
        facts = select(world, events, player, self.seen, self.table)
        last = self.seen.place
        a = world.agents.get(AgentId(player))
        if a is not None:
            self.seen = Sighting(str(a.at), frozenset(
                str(o.spec_id) for o in world.agents_in_order() if o.at == a.at))
        if not facts:
            return None
        m = world_moment(world, player, facts, self.table, last)
        return narrate(m, self.providers, _seed(world, player, "mundo"))

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
        everyone=tuple(d["everyone"]),
    )
