"""La percepción: lo que cada uno ha visto delante, y lo público de quien conoce
(unidad 23-0, D-178).

Son dos cosas, y el motor las mantiene separadas:

- **Lo presenciado.** Un hecho que alguien tuvo delante (un acto dirigido, un
  objeto que pasa de mano, un desenlace de combate, una muerte). Cada presente
  distinto del actor lo anota en su búfer, acotado por días y por número.
- **Lo público.** Lo que cualquiera que conozca a una persona sabe de ella: sus
  relaciones con nombre, sus grupos, los rasgos de creación, su edad, si vive y
  las condiciones que el pack marca como visibles. Lo privado (aprecio,
  necesidades, carácter, marcas, metas) no sale de aquí nunca.

Las consultas son funciones puras de lectura: nada de esto decide nada todavía
(la 23a será la primera que lo use), y no toca el RNG.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agora.engine.events import Event, EventKind
from agora.engine.ontology import ActionId, AgentId, PlaceId, TraitId

if TYPE_CHECKING:
    from agora.engine.memory import Recuerdo
    from agora.engine.state import WorldState


@dataclass(frozen=True, slots=True)
class Percepcion:
    """Un hecho presenciado: lo que se vio, quién lo hizo, a quién iba y dónde."""

    seq: int
    tick: int
    kind: EventKind
    actor: AgentId
    target: AgentId | None
    place: PlaceId
    action: ActionId | None


def es_presenciable(evento: Event) -> bool:
    """Si este hecho es algo que se ve delante y puede ser un latido de trama.

    No todo lo que pasa delante: un acto dirigido sí, una acción suelta no.
    """
    if evento.actor is None or evento.place is None:
        return False
    match evento.kind:
        case EventKind.ACTION_STARTED:
            return "target" in evento.data
        case EventKind.SOCIAL_ACT:
            return True
        case EventKind.ITEM_MOVED:
            # Dar o quitar: entre dos personas. Ponerse algo, o gastarlo, no.
            return evento.subject is not None and evento.subject != evento.actor
        case EventKind.AGENT_DIED:
            # El testigo es quien lo tuvo delante; el resto, sin lugar, no lo vio.
            return True
        case EventKind.ACTION_ABORTED:
            return evento.data.get("reason") == "combate"
        case EventKind.TRAVEL_ARRIVED:
            return evento.data.get("huida") is True
    return False


def _destinatario(evento: Event) -> AgentId | None:
    if evento.subject is not None:
        return evento.subject
    destino = evento.data.get("target")
    return None if destino is None else AgentId(str(destino))


def percepcion_de(evento: Event) -> Percepcion | None:
    """Lo que se anotaría de este hecho, o `None` si no es presenciable."""
    if not es_presenciable(evento) or evento.actor is None or evento.place is None:
        return None
    return Percepcion(
        seq=evento.seq,
        tick=evento.tick,
        kind=evento.kind,
        actor=evento.actor,
        target=_destinatario(evento),
        place=evento.place,
        action=evento.action,
    )


def anotar(
    buffers: dict[AgentId, deque[Percepcion]],
    percepcion: Percepcion,
    presentes: Iterable[AgentId],
    ticks_de_ventana: int,
    maximo: int,
) -> None:
    """Anota el hecho en el búfer de cada presente, y poda lo que se queda viejo o
    sobra. Es la única puerta de escritura: quien llama decide quién estaba delante."""
    corte = percepcion.tick - ticks_de_ventana
    for quien in presentes:
        buffer = buffers.setdefault(quien, deque())
        buffer.append(percepcion)
        while buffer and (buffer[0].tick < corte or len(buffer) > maximo):
            buffer.popleft()


def _desde(world: WorldState, days: int | None) -> int:
    dias = world.pack.tuning.perception_days if days is None else days
    return world.tick - dias * world.pack.clock.ticks_per_day


def saw(
    world: WorldState,
    quien: AgentId,
    *,
    kind: EventKind | None = None,
    actor: AgentId | None = None,
    target: AgentId | None = None,
    days: int | None = None,
) -> tuple[Percepcion, ...]:
    """Lo que `quien` ha visto delante, de más viejo a más nuevo, con los filtros que
    se le pasen. Sin `days`, el plazo del pack."""
    corte = _desde(world, days)
    return tuple(
        p for p in world.percepcion.get(quien, ())
        if p.tick >= corte
        and (kind is None or p.kind is kind)
        and (actor is None or p.actor == actor)
        and (target is None or p.target == target)
    )


def seen_together(
    world: WorldState, quien: AgentId, a: AgentId, b: AgentId, days: int | None = None
) -> int:
    """Cuántos hechos presenció `quien` en los que `a` y `b` son actor y destinatario,
    en cualquier orden."""
    pareja = {a, b}
    return sum(
        1 for p in saw(world, quien, days=days)
        if p.target is not None and {p.actor, p.target} == pareja
    )


def heard(
    world: WorldState, quien: AgentId, *, about: AgentId | None = None,
    days: int | None = None,
) -> tuple[Recuerdo, ...]:
    """Lo que `quien` oyó de segunda mano, leído de su memoria (no se copia aparte)."""
    corte = _desde(world, days)
    return tuple(
        r for r in world.memoria.de(quien)
        if r.de_oidas > 0 and r.tick >= corte and (about is None or r.about == about)
    )


def knows(world: WorldState, quien: AgentId, otro: AgentId) -> bool:
    """Si `quien` conoce a `otro`: tiene un vínculo, una relación con nombre, o le ha
    visto (en un hecho presenciado o en un avistamiento de lugar)."""
    yo = world.agents.get(quien)
    if yo is None or quien == otro:
        return False
    if otro in yo.bonds or yo.related_to(otro):
        return True
    if any(otro in (p.actor, p.target) for p in saw(world, quien)):
        return True
    return any(otro in quienes for _, quienes in yo.sightings.values())


@dataclass(frozen=True, slots=True)
class PublicFacts:
    """Lo que cualquiera que conozca a una persona sabe de ella. Nada de lo privado."""

    nombre: str
    vivo: bool
    relaciones: tuple[tuple[str, tuple[str, ...]], ...]
    """(etiqueta de la relación, nombres de quienes la tienen), en orden de relación."""
    grupos: tuple[str, ...]
    """Los grupos a los que pertenece, por su nombre."""
    rasgos: tuple[str, ...]
    """El rasgo que la persona muestra en cada grupo de creación del pack."""
    edad: int | None
    """Los años que tiene, si vive."""
    condiciones: tuple[str, ...]
    """Las condiciones que el pack marca como visibles."""


def public_facts(world: WorldState, quien: AgentId, otro: AgentId) -> PublicFacts | None:
    """Lo público de `otro`, si `quien` le conoce. `None` si no."""
    if not knows(world, quien, otro):
        return None
    pack = world.pack
    persona = world.agents.get(otro)
    nombre = world.censo[otro].label if otro in world.censo else str(otro)
    relaciones = tuple(
        (pack.relation_by_id[rel].label if rel in pack.relation_by_id else str(rel),
         tuple(sorted(_nombre(world, q) for q in quienes)))
        for rel, quienes in sorted(persona.relations.items() if persona else ())
    )
    grupos = tuple(
        world.facciones[f].label for f in sorted(persona.lealtad if persona else ())
        if f in world.facciones
    )
    rasgos = _rasgos_de_creacion(world, persona.traits if persona else {})
    visibles = tuple(
        pack.situation_by_id[c.situacion].label
        for c in (persona.condiciones if persona else ())
        if pack.situation_by_id[c.situacion].visible
    )
    return PublicFacts(
        nombre=nombre,
        vivo=persona is not None,
        relaciones=relaciones,
        grupos=grupos,
        rasgos=rasgos,
        edad=None if persona is None else persona.edad(world.tick),
        condiciones=visibles,
    )


def _rasgos_de_creacion(world: WorldState, rasgos: dict[TraitId, float]) -> tuple[str, ...]:
    """Por cada grupo de creación, el rasgo que más pesa en la persona, si tiene
    alguno. Se resuelve por valor y, con empate, por id: nunca por el orden de un set."""
    creacion = world.pack.creation
    if creacion is None:
        return ()
    salida: list[str] = []
    for grupo in creacion.groups:
        marcados = sorted(
            ((rasgos[t], t) for t in grupo.traits if rasgos.get(t, 0.0) > 0.0),
            key=lambda par: (-par[0], str(par[1])),
        )
        if marcados:
            salida.append(world.pack.trait_by_id[marcados[0][1]].label)
    return tuple(salida)


def _nombre(world: WorldState, quien: AgentId) -> str:
    return world.censo[quien].label if quien in world.censo else str(quien)
