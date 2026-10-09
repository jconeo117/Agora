"""Qué se puede saber de un agente ahora mismo, en hechos y no en prosa.

Es la primera pieza de la capa de consulta (paso 4 de D-149). La leen el DM
(`--consultar`) y la voz, y no escribe nada: preguntarle al mundo no puede
cambiarlo (regla 1). La prosa no vive aquí, porque el motor no sabe en qué
mundo corre (regla 2): esto devuelve etiquetas del pack y números.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agora.engine.memory import Cue
from agora.engine.ontology import AgentId
from agora.engine.state import PerformingAction, Traveling, WorldState

RECUERDOS = 3
"""Cuántos recuerdos lleva una ficha. Más no caben en un briefing corto, que es
lo que el puerto exige para que un modelo de 7 B rinda igual que uno grande."""

CARACTER_MINIMO = 0.3
"""Desde qué grado se nombra un rasgo de carácter. Por debajo, todo el mundo
tendría de todo un poco y la ficha no distinguiría a nadie."""


class Lack(StrEnum):
    """Cuánto le falta algo. Bandas y no números: el motor sabe que 0.08 es
    desesperado, pero un modelo no tiene por qué saberlo."""

    DESPERATE = "desesperada"
    SEVERE = "mucha"
    MODERATE = "bastante"
    MILD = "poca"


def banda(valor: float) -> Lack:
    if valor < 0.1:
        return Lack.DESPERATE
    if valor < 0.25:
        return Lack.SEVERE
    if valor < 0.45:
        return Lack.MODERATE
    return Lack.MILD


@dataclass(frozen=True, slots=True)
class RecuerdoFicha:
    tipo: str
    accion: str | None
    lugar: str | None
    persona: str | None
    valencia: float


@dataclass(frozen=True, slots=True)
class Ficha:
    agente: AgentId
    nombre: str
    identidad: tuple[str, ...]
    caracter: tuple[str, ...]
    lugar: str
    fase: str | None
    actividad: str | None
    """La etiqueta de lo que está haciendo; `None` si está ocioso."""
    de_camino_a: str | None
    carencias: tuple[tuple[str, Lack], ...]
    """Las dos necesidades más bajas (sin las de progresión), de menor a mayor."""
    recuerdos: tuple[RecuerdoFicha, ...]
    aprecia: tuple[str, ...]
    detesta: tuple[str, ...]
    interlocutor: str | None
    aprecio_al_interlocutor: float | None
    relaciones_con_interlocutor: tuple[str, ...]

    def lines(self) -> list[str]:
        """Para el DM: los hechos tal cual, una línea cada uno."""
        haciendo = self.actividad or (
            "de camino a " + self.de_camino_a if self.de_camino_a else "-"
        )
        salida = [
            f"  {self.nombre}  ({', '.join(self.identidad) or '-'})",
            f"  carácter      {', '.join(self.caracter) or '-'}",
            f"  dónde         {self.lugar}  [{self.fase or '-'}]",
            f"  haciendo      {haciendo}",
            f"  le falta      {', '.join(f'{n} ({b})' for n, b in self.carencias) or '-'}",
            f"  aprecia       {', '.join(self.aprecia) or '-'}",
            f"  detesta       {', '.join(self.detesta) or '-'}",
        ]
        salida += [
            f"  recuerda      {r.tipo} {r.accion or ''} {('en ' + r.lugar) if r.lugar else ''} "
            f"{('con ' + r.persona) if r.persona else ''} ({r.valencia:+.1f})"
            for r in self.recuerdos
        ]
        if self.interlocutor is not None:
            salida.append(
                f"  ante {self.interlocutor}: aprecio {self.aprecio_al_interlocutor:+.2f}"
                f" {', '.join(self.relaciones_con_interlocutor)}"
            )
        return salida


def ficha(world: WorldState, agente: AgentId, interlocutor: AgentId | None = None) -> Ficha:
    """Revienta con `KeyError` si el agente no está vivo: preguntar por un
    muerto es un error de quien pregunta, no algo que inventar."""
    pack = world.pack
    a = world.agents[agente]
    tick = world.tick

    def nombre(i: AgentId) -> str:
        return world.censo[i].label if i in world.censo else str(i)

    voz = pack.voice
    identidad = tuple(
        pack.trait_by_id[t].label
        for t in (voz.identity_traits if voz else ())
        if a.traits.get(t, 0.0) > 0.0
    )
    caracter = tuple(
        pack.trait_by_id[t].label
        for t in sorted(
            (
                t
                for t in (voz.character_traits if voz else ())
                if a.traits.get(t, 0.0) >= CARACTER_MINIMO
            ),
            key=lambda t: (-a.traits[t], str(t)),
        )[:3]
    )
    actividad = de_camino_a = None
    match a.busy:
        case PerformingAction(action=accion):
            actividad = pack.action_by_id[accion].label
        case Traveling(destination=destino):
            de_camino_a = pack.place_by_id[destino].label
        case _:
            pass
    fase_id = pack.clock.phase_at(tick)
    fase = next((f.label for f in pack.clock.phases if f.id == fase_id), None)
    carencias = tuple(
        (pack.need_by_id[n].label, banda(v))
        for v, n in sorted(
            (a.needs[n.id], n.id) for n in pack.needs if not n.progression
        )[:2]
    )
    pista = Cue(about=interlocutor) if interlocutor is not None else Cue()
    recuerdos = tuple(
        RecuerdoFicha(
            tipo=r.kind.value,
            accion=None if r.action is None else pack.action_by_id[r.action].label,
            lugar=None if r.place is None else pack.place_by_id[r.place].label,
            persona=None if r.about is None else nombre(r.about),
            valencia=r.valencia,
        )
        for r in world.memoria.recall(agente, pista, RECUERDOS)
    )

    def aprecio(otro: AgentId) -> float:
        return a.regard_for(otro, tick, a.temperament.bond_fade, a.relation_floor(pack, otro))

    ordenados = sorted(((aprecio(o), str(o)) for o in a.bonds), reverse=True)
    aprecia = tuple(nombre(AgentId(o)) for r, o in ordenados[:2] if r > 0.0)
    detesta = tuple(nombre(AgentId(o)) for r, o in reversed(ordenados[-2:]) if r < 0.0)
    return Ficha(
        agente=agente, nombre=nombre(agente), identidad=identidad, caracter=caracter,
        lugar=pack.place_by_id[a.at].label, fase=fase, actividad=actividad,
        de_camino_a=de_camino_a, carencias=carencias, recuerdos=recuerdos,
        aprecia=aprecia, detesta=detesta,
        interlocutor=None if interlocutor is None else nombre(interlocutor),
        aprecio_al_interlocutor=None if interlocutor is None else aprecio(interlocutor),
        relaciones_con_interlocutor=tuple(
            pack.relation_by_id[r].label
            for r, quienes in sorted(a.relations.items())
            if interlocutor is not None and interlocutor in quienes
        ),
    )
