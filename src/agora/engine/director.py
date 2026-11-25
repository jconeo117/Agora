"""El director de ritmo (unidad 23b-2, A.1): cuándo le toca al mundo un arco grande.

Son reglas, no un modelo, y no favorece a nadie —tampoco al jugador—. Como las señales de estado
no sirven de tensión (23b-2, §1), el director mira tres cosas, todas del pack:

- el **tiempo desde el último arco**, de cualquier modo: `min_gap_days`;
- un **presupuesto de intensidad** que se recarga cada día y se gasta al empezar un arco que el
  director eligió, con el coste de su escala;
- el **ritmo de hechos recientes** (muertes, combates, rupturas y enfrentamientos de los últimos
  siete días): si el mundo está revuelto por encima de `calm_events`, no echa más leña.

Entre los arcos que cumplen, elige uno por clave, ponderado por su peso. Un arco que sale por
calendario o por condición no pasa por aquí: cuenta como «último arco», pero no gasta presupuesto.

Solo existe con `director` en el pack. Sin él, el mundo sigue como antes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agora.engine import arcs, chronicle
from agora.engine.events import Event, EventKind
from agora.engine.ontology import AgentId, DirectorProfile, PlaceId

if TYPE_CHECKING:
    from agora.engine.ontology import ArcSpec
    from agora.engine.world import Simulation as World

VENTANA_DE_RITMO = 7
"""Días que mira el ritmo de hechos. Una semana: lo bastante para que una pelea de un día no
decida nada, y lo bastante corta para que la calma vuelva a contar."""

_HECHOS_DE_RITMO = frozenset({
    EventKind.COMBAT, EventKind.RELATION_ENDED, EventKind.FACTIONS_AT_ODDS,
})


def _activo(mundo: World) -> bool:
    return mundo.pack.director is not None


def _dia(mundo: World) -> int:
    return mundo.state.tick // mundo.pack.clock.ticks_per_day


def _sumar_ritmo(mundo: World) -> None:
    dia = _dia(mundo)
    mundo.state.hechos_de_ritmo[dia] = mundo.state.hechos_de_ritmo.get(dia, 0) + 1


def observar(mundo: World, evento: Event) -> None:
    """Lee un hecho recién emitido: cuenta para el ritmo si es de los que cuentan, y lo pasa a
    la crónica. Lo llama `World._registrar`, la única puerta por la que entra un hecho al log."""
    if not _activo(mundo):
        return
    if evento.kind in _HECHOS_DE_RITMO:
        _sumar_ritmo(mundo)
    chronicle.observar(mundo, evento)


def muerte(mundo: World, quien: AgentId, lugar: PlaceId, deudos: int, porque: str) -> None:
    """Una muerte cuenta para el ritmo una vez, y entra en la crónica si pesa. Va desde `morir`:
    `AGENT_DIED` se emite una vez por superviviente, y contarlo ahí sería contar a los dolientes."""
    if not _activo(mundo):
        return
    _sumar_ritmo(mundo)
    chronicle.muerte(mundo, quien, lugar, deudos, porque)


def ritmo_reciente(mundo: World) -> float:
    """Hechos de ritmo por día, de media, en la última semana. Sin historia, cero."""
    dia = _dia(mundo)
    total = sum(
        mundo.state.hechos_de_ritmo.get(d, 0)
        for d in range(dia - VENTANA_DE_RITMO + 1, dia + 1)
    )
    return total / VENTANA_DE_RITMO


def pasar_dia(mundo: World) -> None:
    """Lo que el director hace una vez al día (23b-2, A.1): recarga el presupuesto, olvida el
    ritmo que cae fuera de la semana, y si toca y hay calma, empieza un arco."""
    libro = mundo.pack.director
    if libro is None:
        return
    s = mundo.state
    perfil = libro.profiles[libro.profile]
    dia = _dia(mundo)
    s.presupuesto += perfil.budget_per_day
    for viejo in [d for d in s.hechos_de_ritmo if d <= dia - VENTANA_DE_RITMO]:
        del s.hechos_de_ritmo[viejo]

    tpd = mundo.pack.clock.ticks_per_day
    if s.ultimo_arco is not None and s.tick - s.ultimo_arco < perfil.min_gap_days * tpd:
        return
    if ritmo_reciente(mundo) > perfil.calm_events:
        return
    elegido = _elegir(mundo, perfil, dia)
    if elegido is None:
        return
    arco, _ = elegido
    s.presupuesto -= perfil.cost[arco.scale]
    arcs.comenzar(mundo, arco, porque="director")


def _elegir(mundo: World, perfil: DirectorProfile, dia: int) -> tuple[ArcSpec, float] | None:
    """El arco que el director empieza hoy, si hay alguno. Entre los que cumplen —con el
    presupuesto para su escala, sin estar en curso y con sus condiciones— gana el de mayor
    clave ponderada: `u ** (1/peso)`, con `u` un sorteo de (arco, día). Desempata por id."""
    s = mundo.state
    if mundo.pack.arcs is None:
        return None
    candidatos: list[tuple[float, str, ArcSpec, float]] = []
    for arco in mundo.pack.arcs.arcs:
        if arco.id in s.arcos:
            continue
        disparo = next((t for t in arco.trigger if t.director is not None), None)
        if disparo is None or disparo.director is None:
            continue
        if perfil.cost[arco.scale] > s.presupuesto:
            continue
        if not arcs.condiciones_cumplen(mundo, disparo):
            continue
        u = s.rng.stream("director", arco.id, dia).random()
        clave = u ** (1.0 / disparo.director.weight)
        candidatos.append((clave, str(arco.id), arco, disparo.director.weight))
    if not candidatos:
        return None
    _, _, arco, peso = max(candidatos, key=lambda c: (c[0], c[1]))
    return arco, peso
