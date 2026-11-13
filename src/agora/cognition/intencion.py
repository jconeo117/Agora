"""Entender lo que el jugador escribe, sobre el menú que ya calculó el motor
(unidad 14, D-163).

El intérprete no decide nada: señala una entrada del menú, o dice que no
encaja, o que es una pregunta. Por eso el modelo elige de enumerados hechos con
el menú de este momento, y aun así `resolve` vuelve a buscar su elección en el
menú: un modelo que se salta el esquema no puede colar una acción que el motor
no habría ofrecido. Lo que el guion graba es la entrada elegida, nunca la
prosa, y la partida se reproduce sin modelo (regla 4).

Sin modelo, o si tarda o falla, interpreta el léxico: determinista, peor, y
casi siempre con la opción buena entre las candidatas que propone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError, create_model

from agora.engine.ports import CognitionProvider

PLANTILLA = (Path(__file__).parent / "prompts" / "intencion.txt").read_text(encoding="utf-8")


class Kind(StrEnum):
    ACTION = "accion"
    ORDER = "orden"
    AMBIGUOUS = "ambigua"
    NO_FIT = "no_encaja"
    QUESTION = "pregunta"


class Order(StrEnum):
    """Lo que la terminal hace sin decidir cada cuarto de hora. Mirar, ficha y
    hablar no pasan el tiempo; esperar y vivir sí. Salir no está a propósito: una
    orden que no tiene vuelta atrás solo se acepta escrita tal cual (en el banco, un
    7B contestó «salir» a «remato al herido»)."""

    LOOK = "mirar"
    SHEET = "ficha"
    WAIT = "esperar"
    TALK = "hablar"
    LIVE = "vivir"


ORDER_HELP: dict[Order, tuple[str, tuple[str, ...]]] = {
    Order.LOOK: ("mirar quién hay y qué hace",
                 ("miro alrededor", "quién hay aquí", "qué pasa aquí")),
    Order.SHEET: ("lo que se sabe de ti o de otro",
                  ("cómo estoy", "qué sé de", "mi ficha")),
    Order.WAIT: ("dejar pasar un cuarto de hora",
                 ("espero", "dejo pasar el tiempo", "no hago nada")),
    Order.TALK: ("preguntarle a alguien qué tal le va",
                 ("hablo con", "le pregunto qué tal", "saludo a")),
    Order.LIVE: ("seguir con tu vida sola hasta que pase algo",
                 ("sigo con mi vida", "vivir hasta mañana", "dejo que el día pase")),
}


@dataclass(frozen=True, slots=True)
class Entry:
    """Una entrada del menú, por contenido. El índice en `Menu.entries` es lo
    que se devuelve; quien construyó el menú sabe a qué objeto corresponde."""

    action: str
    place: str | None = None
    target: str | None = None
    force: bool = False
    item: str | None = None
    """Un objeto, para dar o pedir (unidad 16a). El índice del menú sigue siendo
    lo que se devuelve; el objeto es lo que quien construyó el menú sabe leer."""


@dataclass(frozen=True, slots=True)
class Menu:
    entries: tuple[Entry, ...]
    """En el orden del motor, mejor primero: a igualdad, gana la primera."""
    actions: tuple[tuple[str, str, tuple[str, ...]], ...]
    """(id, etiqueta, ejemplos) de cada acción que aparece en `entries`."""
    places: tuple[tuple[str, str, int], ...] = ()
    """(id, etiqueta, cuartos de viaje) de cada lugar que aparece en `entries`."""
    people: tuple[tuple[str, str], ...] = ()
    """(id, etiqueta) de cada destinatario."""
    orders: tuple[Order, ...] = ()
    """Vacío en una escena: allí no se mira ni se espera."""


@dataclass(frozen=True, slots=True)
class Reading:
    kind: Kind
    entry: int | None = None
    order: Order | None = None
    about: str | None = None
    candidates: tuple[int, ...] = ()
    by_model: bool = False


# --- la puerta única ----------------------------------------------------------


def short_name(label: str) -> str:
    """«arroyo (la selva, interior)» es «arroyo». El jugador dice «voy al
    arroyo» y quiere el más cercano: hay tres en la isla."""
    return label.split(" (")[0]


def same_place(menu: Menu, a: str | None, b: str) -> bool:
    names = {pid: short_name(label) for pid, label, _ in menu.places}
    return a is not None and a in names and b in names and names[a] == names[b]


def resolve(
    menu: Menu, kind: Kind, action: str | None = None, place: str | None = None,
    target: str | None = None, force: bool = False,
    candidates: tuple[tuple[str, str | None], ...] = (), by_model: bool = False,
) -> Reading:
    """Busca la intención en el menú. Lo que no está es «no encaja», con las
    más cercanas: nunca se completa una intención con algo que no se dijo,
    salvo el lugar, que si falta es el primero del menú (el que el motor
    pondría: el mejor, que casi siempre es el más cercano)."""
    if kind is Kind.QUESTION:
        return Reading(Kind.QUESTION, by_model=by_model)
    if kind is Kind.AMBIGUOUS:
        found: list[int] = []
        for a, t in candidates:
            r = resolve(menu, Kind.ACTION, a, None, t)
            if r.entry is not None and r.entry not in found:
                found.append(r.entry)
        if len(found) == 1:
            return Reading(Kind.ACTION, found[0], by_model=by_model)
        if found:
            return Reading(Kind.AMBIGUOUS, candidates=tuple(found[:3]), by_model=by_model)
        return Reading(Kind.NO_FIT, candidates=nearest(menu, None, None, None), by_model=by_model)
    if kind is Kind.ACTION and action is not None:
        for i, e in enumerate(menu.entries):
            if (e.action == action and e.force == force
                    and (place is None or same_place(menu, e.place, place))
                    and (target is None or e.target == target)):
                return Reading(Kind.ACTION, i, by_model=by_model)
    return Reading(Kind.NO_FIT, candidates=nearest(menu, action, place, target), by_model=by_model)


def nearest(
    menu: Menu, action: str | None, place: str | None, target: str | None
) -> tuple[int, ...]:
    """Hasta tres entradas que comparten algo con lo pedido, una por acción y
    destinatario. Cuenta el doble acertar la acción o la persona que el sitio."""

    def score(e: Entry) -> int:
        return (2 * (action is not None and e.action == action)
                + 2 * (target is not None and e.target == target)
                + (place is not None and same_place(menu, e.place, place)))

    order = sorted(range(len(menu.entries)), key=lambda i: (-score(menu.entries[i]), i))
    out: list[int] = []
    for i in order:
        e = menu.entries[i]
        if score(e) == 0:
            break
        if all((e.action, e.target) != (menu.entries[j].action, menu.entries[j].target)
               for j in out):
            out.append(i)
        if len(out) == 3:
            break
    return tuple(out)


# --- el léxico ----------------------------------------------------------------

EMPTY = frozenset((
    "a", "al", "el", "la", "los", "las", "lo", "le", "les", "de", "del", "en", "con", "y",
    "o", "u", "un", "una", "unos", "unas", "me", "mi", "mis", "te", "tu", "se", "su", "sus",
    "que", "por", "para", "mientras", "ya", "luego", "hasta", "aqui", "alli", "este", "esta",
    "eso", "esto",
))
"""Palabras que no distinguen una acción de otra."""

THRESHOLD = 0.5
"""Qué parte de una frase de ejemplo tiene que aparecer en lo escrito."""


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def stems(text: str) -> tuple[str, ...]:
    """Las cinco primeras letras de cada palabra con contenido: «remato» y
    «rematar» coinciden sin un lematizador, que sería una dependencia."""
    return tuple(w[:5] for w in re.findall(r"[a-z0-9]+", _fold(text)) if w not in EMPTY)


def _likeness(written: frozenset[str], phrase: str) -> float:
    s = stems(phrase)
    return sum(1 for w in s if w in written) / len(s) if s else 0.0


def lexical(menu: Menu, prose: str) -> Reading:
    written = frozenset(stems(prose))
    named = [pid for pid, label in menu.people
             if (first := stems(label.split(",")[0])) and first[0] in written]
    target = named[0] if named else None
    place = next((pid for name, (_, pid) in _representatives(menu).items()
                  if (ws := stems(name)) and all(w in written for w in ws)), None)

    # Órdenes y acciones compiten con la misma vara; el entero desempata.
    scored: list[tuple[float, int, str]] = []
    for n, o in enumerate(menu.orders):
        label, examples = ORDER_HELP[o]
        scored.append((max(_likeness(written, f) for f in (label, *examples)), n, o.value))
    for n, (aid, label, examples) in enumerate(menu.actions):
        s = max(_likeness(written, f) for f in (label, *examples))
        if target is not None and any(e.action == aid and e.target == target for e in menu.entries):
            s += 0.25
        scored.append((s, 100 + n, aid))
    scored.sort(key=lambda x: (-x[0], x[1]))
    best, rank, ident = scored[0]
    if best < THRESHOLD:
        kind = Kind.QUESTION if "?" in prose else Kind.NO_FIT
        return Reading(kind, candidates=nearest(menu, None, place, target))
    if rank < 100:
        return Reading(Kind.ORDER, order=Order(ident), about=target)
    r = resolve(menu, Kind.ACTION, ident, place, target)
    if r.entry is None and place is not None:
        r = resolve(menu, Kind.ACTION, ident, None, target)
    second = next((x for x in scored[1:] if x[1] >= 100), None)
    if r.entry is not None and second is not None and second[0] >= best - 0.01:
        other = resolve(menu, Kind.ACTION, second[2], place, target)
        if other.entry is not None:
            return Reading(Kind.AMBIGUOUS, candidates=(r.entry, other.entry))
    return r


# --- el modelo ----------------------------------------------------------------


def _literal(values: tuple[str, ...]) -> Any:
    """Un enumerado hecho con el menú de este momento: el modelo no puede
    escribir un id que no exista. Sin valores, ningún campo lo usa."""
    return Literal[values] if values else str


def schema(menu: Menu) -> type[BaseModel]:
    actions = _literal(tuple(a for a, _, _ in menu.actions))
    people = _literal(tuple(p for p, _ in menu.people))
    places = _literal(tuple(pid for _, pid in _representatives(menu).values()))
    orders = _literal(tuple(o.value for o in menu.orders))
    candidate = create_model("Candidata", accion=(actions, ...), destinatario=(people | None, None))
    model: type[BaseModel] = create_model(
        "Intencion",
        __config__=ConfigDict(extra="ignore"),
        tipo=(Literal["accion", "orden", "ambigua", "no_encaja", "pregunta"], ...),
        accion=(actions | None, None),
        lugar=(places | None, None),
        destinatario=(people | None, None),
        forzar=(bool, False),
        orden=(orders | None, None),
        sobre=(people | None, None),
        candidatas=(list[candidate], []),
    )
    return model


def _representatives(menu: Menu) -> dict[str, tuple[int, str]]:
    """Nombre corto -> (viaje, el lugar más cercano con ese nombre). Listar
    los 103 lugares de la isla eran 3 000 tokens por decisión; por nombre, 1 770."""
    out: dict[str, tuple[int, str]] = {}
    for pid, label, travel in sorted(menu.places, key=lambda p: (p[2], p[0])):
        out.setdefault(short_name(label), (travel, pid))
    return out


def briefing(menu: Menu, prose: str, template: str = PLANTILLA) -> str:
    lines = ["ACCIONES (id: etiqueta; cómo se pide):"]
    for aid, label, examples in menu.actions:
        lines.append(f"  {aid}: {label}" + (f"; {' / '.join(examples)}" if examples else ""))
    with_whom: dict[str, list[str]] = {}
    for e in menu.entries:
        if e.target is not None and e.action not in with_whom.setdefault(e.target, []):
            with_whom[e.target].append(e.action)
    if menu.people:
        lines.append("PERSONAS (id: quién; qué se puede hacer con ella):")
        lines += [f"  {pid}: {label}; {', '.join(with_whom.get(pid, []))}"
                  for pid, label in menu.people]
    if menu.places:
        names = {pid: short_name(label) for pid, label, _ in menu.places}
        where: dict[str, list[str]] = {}
        for e in menu.entries:
            if e.place is not None and e.action not in where.setdefault(names[e.place], []):
                where[names[e.place]].append(e.action)
        lines.append("LUGARES (id: nombre, cuartos de hora hasta el más cercano; "
                     "qué se hace allí):")
        for name, (travel, pid) in _representatives(menu).items():
            lejos = "aquí" if travel == 0 else str(travel)
            lines.append(f"  {pid}: {name}, {lejos}; {', '.join(where.get(name, []))}")
    if any(e.force for e in menu.entries):
        lines.append("forzar=true: atacar forzándote (más efecto, más cansancio).")
    if menu.orders:
        lines.append("ÓRDENES: "
                     + "; ".join(f"{o.value} ({ORDER_HELP[o][0]})" for o in menu.orders))
    return template.format(menu="\n".join(lines), prosa=prose)


def interpret(
    menu: Menu, prose: str, provider: CognitionProvider | None, seed: int,
    template: str = PLANTILLA,
) -> Reading:
    if provider is None:
        return lexical(menu, prose)
    out = provider.think(briefing(menu, prose, template), schema(menu), seed)
    if not isinstance(out, BaseModel):
        return lexical(menu, prose)
    try:
        d = out.model_dump()
        kind = Kind(d["tipo"])
        if kind is Kind.ORDER:
            if d["orden"] is None:
                return lexical(menu, prose)
            return Reading(Kind.ORDER, order=Order(d["orden"]),
                           about=d["sobre"] or d["destinatario"], by_model=True)
        candidates = tuple((c["accion"], c["destinatario"]) for c in d["candidatas"])
        return resolve(menu, kind, d["accion"], d["lugar"], d["destinatario"], d["forzar"],
                       candidates, by_model=True)
    except (KeyError, ValueError, TypeError, ValidationError):
        return lexical(menu, prose)
