"""La crónica del mundo (unidad 23b-2, A.2): lo que pasó y pesa, guardado y consultable.

Una sola crónica. Entra lo que la hoja de ruta marca —muertes con peso, nacimientos en casas
con prestigio, parejas y rupturas, grupos que se funden o se enfrentan, ascensos altos y los
arcos que acaban con su reconocido— y nada más. Sin vectores: cada entrada lleva a quién
toca, dónde y de qué grupo, y se busca por esos campos y por fecha.

Solo existe con `director` en el pack. Sin él, nada entra y el mundo sigue igual.

Quién decide qué entra: el motor, por el vocabulario cerrado de abajo. El pack solo pone
umbrales (`CronicaSpec`). Las muertes se anotan una vez por víctima, desde `morir`, porque
`AGENT_DIED` se emite una vez por cada superviviente que la llora.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    AgentId,
    FactionId,
    PlaceId,
)

if TYPE_CHECKING:
    from agora.engine.world import Simulation as World


TIPOS = ("muerte", "nacimiento", "pareja", "ruptura", "grupo", "enfrentamiento", "ascenso", "arco")
"""El vocabulario cerrado de la crónica. Un tipo que el pack invente no entra."""

PUBLICOS = frozenset({"muerte", "arco"})
"""Lo que cualquiera que conozca el mundo sabe: una muerte se oye, y un arco que acaba
reconoce a alguien en voz alta. Lo demás solo lo sabe quien estaba, lo vivió o se lo contaron."""


@dataclass(frozen=True, slots=True)
class Entrada:
    """Un hecho de la crónica. `testigos` es quién estaba en el sitio cuando pasó: sin eso no
    hay forma de decir luego quién lo presenció, y el narrador no puede contarlo a quien no."""

    tick: int
    tipo: str
    quienes: tuple[AgentId, ...]
    lugar: PlaceId | None
    grupo: FactionId | None
    texto_clave: str
    testigos: tuple[AgentId, ...] = ()


@dataclass(slots=True)
class Cronica:
    """La crónica entera. Las entradas van en orden de tick, que es el de su llegada: así
    `between` puede buscar por bisección y no recorrer todo."""

    entradas: list[Entrada] = field(default_factory=list)
    por_persona: dict[AgentId, list[int]] = field(default_factory=dict)
    por_lugar: dict[PlaceId, list[int]] = field(default_factory=dict)
    por_grupo: dict[FactionId, list[int]] = field(default_factory=dict)

    def anotar(self, entrada: Entrada) -> None:
        if entrada.tipo not in TIPOS:
            raise ValueError(f"la crónica no tiene el tipo {entrada.tipo!r}")
        n = len(self.entradas)
        self.entradas.append(entrada)
        for quien in dict.fromkeys(entrada.quienes):
            self.por_persona.setdefault(quien, []).append(n)
        if entrada.lugar is not None:
            self.por_lugar.setdefault(entrada.lugar, []).append(n)
        if entrada.grupo is not None:
            self.por_grupo.setdefault(entrada.grupo, []).append(n)

    def __len__(self) -> int:
        return len(self.entradas)

    def about(self, quien: AgentId) -> tuple[Entrada, ...]:
        """Lo que la crónica dice de una persona, de más viejo a más nuevo."""
        return tuple(self.entradas[i] for i in self.por_persona.get(quien, ()))

    def at(self, lugar: PlaceId) -> tuple[Entrada, ...]:
        return tuple(self.entradas[i] for i in self.por_lugar.get(lugar, ()))

    def of(self, grupo: FactionId) -> tuple[Entrada, ...]:
        return tuple(self.entradas[i] for i in self.por_grupo.get(grupo, ()))

    def between(self, t0: int, t1: int) -> tuple[Entrada, ...]:
        """Lo que pasó desde `t0` hasta `t1`, ambos incluidos."""
        ticks = [e.tick for e in self.entradas]
        return tuple(self.entradas[i] for i in range(bisect_left(ticks, t0),
                                                     _hasta(ticks, t1)))

    def a_json(self) -> list[dict[str, Any]]:
        """Solo las entradas: los índices se rehacen al cargar, como cualquier derivado."""
        return [
            {
                "tick": e.tick, "tipo": e.tipo,
                "quienes": [str(q) for q in e.quienes],
                "lugar": None if e.lugar is None else str(e.lugar),
                "grupo": None if e.grupo is None else str(e.grupo),
                "texto_clave": e.texto_clave,
                "testigos": [str(q) for q in e.testigos],
            }
            for e in self.entradas
        ]

    @staticmethod
    def de_json(crudas: list[dict[str, Any]]) -> Cronica:
        cronica = Cronica()
        for c in crudas:
            cronica.anotar(Entrada(
                tick=int(c["tick"]), tipo=str(c["tipo"]),
                quienes=tuple(AgentId(str(q)) for q in c["quienes"]),
                lugar=None if c["lugar"] is None else PlaceId(str(c["lugar"])),
                grupo=None if c["grupo"] is None else FactionId(str(c["grupo"])),
                texto_clave=str(c["texto_clave"]),
                testigos=tuple(AgentId(str(q)) for q in c.get("testigos", [])),
            ))
        return cronica


def _hasta(ticks: list[int], t1: int) -> int:
    """El índice tras la última entrada con tick ≤ t1."""
    lo, hi = 0, len(ticks)
    while lo < hi:
        medio = (lo + hi) // 2
        if ticks[medio] <= t1:
            lo = medio + 1
        else:
            hi = medio
    return lo


def _activa(mundo: World) -> bool:
    return mundo.pack.director is not None


def _testigos(mundo: World, lugar: PlaceId | None) -> tuple[AgentId, ...]:
    if lugar is None:
        return ()
    return tuple(a.spec_id for a in mundo.state.agents_in_order() if a.at == lugar)


def _anotar(mundo: World, tipo: str, quienes: tuple[AgentId, ...], lugar: PlaceId | None,
            grupo: FactionId | None, texto_clave: str) -> None:
    # Testigo es quien estaba allí y no es protagonista: la víctima no presencia su propia muerte.
    testigos = tuple(q for q in _testigos(mundo, lugar) if q not in quienes)
    mundo.state.cronica.anotar(Entrada(
        tick=mundo.state.tick, tipo=tipo, quienes=quienes, lugar=lugar, grupo=grupo,
        texto_clave=texto_clave, testigos=testigos,
    ))


def observar(mundo: World, evento: Event) -> None:
    """Lee un hecho recién emitido y, si el pack quiere, lo anota en la crónica. Lo llama
    `World._registrar`, la única puerta por la que un hecho entra en el log."""
    if not _activa(mundo):
        return
    cronica = mundo.pack.director.cronica  # type: ignore[union-attr]
    relacion = str(evento.data.get("relation", ""))
    match evento.kind:
        case EventKind.RELATION_BEGAN if relacion in cronica.relaciones and evento.actor \
                and _aprecio(mundo, evento.actor, evento.subject) >= cronica.relacion_aprecio_min:
            _anotar(mundo, "pareja", (evento.actor, _quien(evento.subject)),
                    _lugar_de(mundo, evento.actor), None, relacion)
        # Una ruptura llega cuando el aprecio ya cayó: lo que la hace notable es que la pareja
        # haya entrado antes en la crónica, no el aprecio del momento.
        case EventKind.RELATION_ENDED if relacion in cronica.relaciones and evento.actor \
                and _pareja_notable(mundo, evento.actor, evento.subject):
            _anotar(mundo, "ruptura", (evento.actor, _quien(evento.subject)),
                    _lugar_de(mundo, evento.actor), None, relacion)
        case EventKind.RANK_UP if evento.actor and int(evento.data.get("rango", 0)) >= \
                cronica.ascenso_rango_min:
            _anotar(mundo, "ascenso", (evento.actor,), evento.place, None,
                    str(evento.data.get("need", "")))
        case EventKind.AGENT_BORN if evento.actor:
            _nacimiento(mundo, evento.actor)
        case EventKind.FACTION_FOUNDED if evento.actor:
            _anotar(mundo, "grupo", (evento.actor,), _lugar_de(mundo, evento.actor),
                    FactionId(str(evento.data.get("faccion", ""))), "fundado")
        case EventKind.FACTIONS_AT_ODDS if evento.actor and evento.subject:
            _anotar(mundo, "enfrentamiento", (evento.actor, evento.subject), None,
                    FactionId(str(evento.data.get("una", ""))), str(evento.data.get("otra", "")))
        case EventKind.ARC_ENDED:
            reconocido = str(evento.data.get("reconocido", ""))
            quienes = (AgentId(reconocido),) if reconocido else ()
            _anotar(mundo, "arco", quienes, evento.place, None, str(evento.data.get("rama", "")))


def _quien(q: AgentId | None) -> AgentId:
    # Una relación siempre tiene dos; el tipo de `subject` lo garantiza el motor.
    if q is None:  # pragma: no cover - una relación nace con sus dos extremos
        raise ValueError("relación sin el segundo extremo")
    return q


def _pareja_notable(mundo: World, quien: AgentId, otro: AgentId | None) -> bool:
    """Si esta pareja ya está en la crónica como pareja: entonces su ruptura también entra."""
    if otro is None:
        return False
    return any(
        e.tipo == "pareja" and set(e.quienes) == {quien, otro}
        for e in mundo.state.cronica.about(quien)
    )


def _aprecio(mundo: World, quien: AgentId, otro: AgentId | None) -> float:
    """El aprecio que `quien` tiene hoy por `otro`, desdibujado como cualquier otro trato."""
    a = mundo.state.agents.get(quien)
    if a is None or otro is None or otro not in a.bonds:
        return 0.0
    return a.bonds[otro].regard_at(mundo.state.tick, a.temperament.bond_fade)


def _lugar_de(mundo: World, quien: AgentId) -> PlaceId | None:
    vivo = mundo.state.agents.get(quien)
    return None if vivo is None else vivo.at


def _nacimiento(mundo: World, nuevo: AgentId) -> None:
    """Un nacimiento entra si su casa tiene prestigio. Un recién nacido sin grupo no entra."""
    agente = mundo.state.agents.get(nuevo)
    if agente is None:
        return
    umbral = mundo.pack.director.cronica.nacimiento_prestigio_min  # type: ignore[union-attr]
    for faccion_id in sorted(agente.lealtad):
        faccion = mundo.state.facciones.get(faccion_id)
        if faccion is not None and faccion.prestigio >= umbral:
            _anotar(mundo, "nacimiento", (nuevo,), agente.at, faccion_id, faccion.label)
            return


def muerte(mundo: World, quien: AgentId, lugar: PlaceId, deudos: int, porque: str) -> None:
    """Una muerte, una vez por víctima (23b-2, A.2). Entra si la fama o los dolientes llegan al
    umbral del pack. Se llama desde `morir`, antes de borrar a la víctima de sus datos."""
    if not _activa(mundo):
        return
    cronica = mundo.pack.director.cronica  # type: ignore[union-attr]
    fama = mundo.state.fama.get(quien, 0.0)
    if fama < cronica.muerte_fama_min and deudos < cronica.muerte_deudos_min:
        return
    _anotar(mundo, "muerte", (quien,), lugar, None, porque)
