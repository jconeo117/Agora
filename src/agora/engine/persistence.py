"""Guardar y recuperar una partida.

Sin esto, cada corrida empieza en el tick cero. Con ciento veintisiete
habitantes, ver graduarse a una promocion son horas de simulacion continua, y
cada cambio de calibracion obliga a rehacerlas enteras.

Dos decisiones gobiernan el archivo:

**Se guarda lo NO DERIVADO.** Los pesos, la aptitud, el desfase, el temperamento
y el desgaste se recomponen al cargar. Es mas pequeno, pero sobre todo garantiza
que lo derivado quede coherente con el pack ACTUAL — que casi nunca es el mismo
con el que se guardo.

**Se guarda el estado, no la historia.** El log queda fuera y es deliberado: un
ano de ciento veintisiete agentes son cientos de megas. Al recuperar una partida
el mundo es el mismo pero *nadie recuerda como llego ahi*, y eso tendra que
resolverlo la memoria episodica cuando exista.

El determinismo sobrevive de gratis, y no por suerte. `RngSource` sortea con
`blake2b(semilla, agente, tick)`, asi que el sorteo del tick 5000 no depende de
cuantos hubo antes: reanudar en el 5000 da exactamente lo mismo que no haber
parado. Esa propiedad se decidio en F0 y esta es la primera vez que se cobra.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agora.engine.events import EventKind
from agora.engine.memory import Recuerdo
from agora.engine.ontology import (
    ActionId,
    AgentId,
    GoalId,
    GoalStatus,
    NeedId,
    PlaceId,
    RelationId,
    SituationId,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Bond, PerformingAction, Traveling, WorldState

FORMATO = 1
"""Version del formato en disco. Un guardado de otra version se rechaza en vez
de cargarse a medias: media partida mal leida es peor que no cargarla."""


class SaveError(ValueError):
    """El guardado no se puede leer con este pack."""


# -----------------------------------------------------------------------------
# Escribir
# -----------------------------------------------------------------------------


def _bond_a_dict(bond: Bond) -> dict[str, Any]:
    return {"regard": bond.regard, "encounters": bond.encounters, "last_seen": bond.last_seen}


def _recuerdo_a_lista(r: Recuerdo) -> list[Any]:
    """Un recuerdo como lista posicional: `[seq, tick, kind, place, action, about,
    importancia, valencia]`.

    Lista y no diccionario por tamaño, que aquí sí importa. Con ciento veintisiete
    agentes y capacidad de doscientos son veinticinco mil recuerdos, y el volcado
    va con `indent=1`: en forma de diccionario son diez líneas cada uno —un cuarto
    de millón de líneas para el mismo dato—. Sigue siendo diffeable, que es lo que
    el guardado tiene que ser.
    """
    return [
        r.seq,
        r.tick,
        r.kind.value,
        None if r.place is None else str(r.place),
        None if r.action is None else str(r.action),
        None if r.about is None else str(r.about),
        r.importancia,
        r.valencia,
        None if r.culpable is None else str(r.culpable),
    ]


def _agente_a_dict(agent: AgentState, recuerdos: tuple[Recuerdo, ...]) -> dict[str, Any]:
    """Solo lo que no se puede recalcular.

    Fuera quedan `need_weights`, `gains`, `phase_shift`, `temperament` y
    `strain`: los cinco salen de los rasgos, las metas y las necesidades, y
    recomponerlos al cargar es mas barato que arrastrarlos y mas seguro que
    confiar en que sigan valiendo con el pack de hoy.
    """
    busy: dict[str, Any] | None = None
    if agent.busy is not None:
        busy = {"tipo": type(agent.busy).__name__, **agent.busy.model_dump()}

    return {
        "spec_id": str(agent.spec_id),
        "at": str(agent.at),
        "needs": {str(k): v for k, v in agent.needs.items()},
        "traits": {str(k): v for k, v in agent.traits.items()},
        "tastes": dict(agent.tastes),
        "goals": {str(k): v.value for k, v in agent.goals.items()},
        "debt": {str(k): v for k, v in agent.debt.items()},
        "gain_beliefs": {
            str(a): {str(n): v for n, v in creencias.items()}
            for a, creencias in agent.gain_beliefs.items()
        },
        "cost_beliefs": {
            str(a): {str(n): v for n, v in creencias.items()}
            for a, creencias in agent.cost_beliefs.items()
        },
        "bonds": {str(k): _bond_a_dict(v) for k, v in agent.bonds.items()},
        # Las relaciones SI se guardan, y las simetrias tambien: cerrarlas al
        # cargar como hace `WorldState.new` reconstruiria solo lo que el pack
        # declaro, y perderia las que nacieron durante la partida — que son
        # justo las interesantes.
        "relations": {
            str(rel): sorted(str(x) for x in quienes)
            for rel, quienes in sorted(agent.relations.items())
            if quienes
        },
        # El `frozenset` no es JSON. Se ordena al escribir, no por estetica: sin
        # orden fijo dos guardados del mismo mundo diferirian byte a byte y
        # compararlos con `diff` dejaria de servir.
        "sightings": {
            str(sitio): [tick, sorted(str(x) for x in quienes)]
            for sitio, (tick, quienes) in agent.sightings.items()
        },
        "saturation": {str(k): v for k, v in agent.saturation.items()},
        "busy": busy,
        # **Aquí se salda la deuda que dejó escrita el docstring de este módulo.**
        # Decía que al recuperar una partida el mundo es el mismo pero *nadie
        # recuerda cómo llegó ahí*, y que eso tendría que resolverlo la memoria
        # episódica cuando existiera. Se resuelve porque un `Recuerdo` es
        # autónomo: si guardara ids de evento, esto no serviría de nada — la
        # historia sigue sin guardarse y los punteros no apuntarían a ningún
        # sitio.
        "memorias": [_recuerdo_a_lista(r) for r in recuerdos],
    }


def save(world: WorldState, together: set[tuple[AgentId, AgentId]], path: Path) -> None:
    """Vuelca la partida. El pack NO va dentro: se pasa al cargar.

    Dejarlo fuera es lo que permite reanudar sobre un pack retocado, que es el
    caso normal cuando se esta calibrando.
    """
    datos = {
        "formato": FORMATO,
        "pack": world.pack.id,
        "tick": world.tick,
        "seed": world.rng.seed,
        # Sin esto, al reanudar se emitiria un encuentro por cada par que ya
        # estaba junto: el mundo cargado se saludaria entero de golpe.
        "together": sorted([str(a), str(b)] for a, b in together),
        # Solo las EVENTUALES: una periódica es una función del reloj, así que
        # guardarla sería guardar algo que ya se sabe calcular — y peor, al
        # reanudar sobre un pack retocado se contradiría con lo que el pack dice.
        "situations": sorted(
            [str(s), -1 if hasta is None else hasta]
            for s, hasta in world.situations.items()
        ),
        # El cooldown de los disparadores. Sin esto, reanudar una partida
        # rearmaría todos los disparadores a la vez y el mundo se llenaría de
        # imprevistos justo al cargar — que es lo contrario de "reanudar en el
        # tick N da lo mismo que no haber parado".
        "last_trigger": sorted(
            [str(s), tick] for s, tick in world.last_trigger.items()
        ),
        "agents": [
            _agente_a_dict(a, world.memoria.de(a.spec_id)) for a in world.agents_in_order()
        ],
    }
    path.write_text(json.dumps(datos, indent=1, ensure_ascii=False), encoding="utf-8")


# -----------------------------------------------------------------------------
# Leer
# -----------------------------------------------------------------------------


def _reconciliar_necesidades(
    guardadas: dict[str, float], pack: ContentPack
) -> dict[NeedId, float]:
    """Ajusta las necesidades al pack de HOY.

    Es la parte que hace util el guardado durante la calibracion. Un eje nuevo
    entra con su `initial`; uno que ya no existe se descarta. Sin esto, anadir
    una necesidad al pack invalidaria todas las partidas guardadas — y el motor
    reventaria al primer `decay`, que indexa directo a proposito.
    """
    return {
        need.id: guardadas.get(str(need.id), need.initial) for need in pack.needs
    }


def _lista_a_recuerdo(
    fila: list[Any],
    lugares: frozenset[str],
    acciones: frozenset[str],
    agentes: frozenset[str],
    situaciones: frozenset[str],
) -> Recuerdo:
    """Reconstruye un recuerdo, limpiando lo que el pack de hoy ya no tiene.

    **Aquí la reconciliación va al revés que en el resto del módulo, y es
    deliberado.** A un rasgo o a una necesidad borrados hay que dejarlos caer
    porque el motor los indexa directo y reventaría con un `KeyError`. A un lugar
    borrado dentro de un recuerdo no lo indexa nadie: solo se compara por
    igualdad al recuperar. Así que dejar caer el recuerdo entero costaría
    biografía sin ganar nada.

    Se anula la referencia muerta y el recuerdo sobrevive. Lo que le pasó a
    alguien le pasó, aunque la taberna ya no exista.
    """
    seq, tick, kind, place, action, about, importancia = fila[:7]
    # La valencia llegó con el arrepentimiento, una fase después que el resto de
    # la fila. Un guardado de siete campos se lee como recuerdos sin signo, que
    # es exactamente lo que eran: cosas que pasaron, ni buenas ni malas.
    valencia = float(fila[7]) if len(fila) > 7 else 0.0
    # Y el culpable llegó con el miedo a lugares, otra fase después. Misma
    # tolerancia: una fila corta es un recuerdo de cuando el mundo no sabía
    # hacerle nada a nadie, así que nadie tenía la culpa de nada.
    crudo_culpable = fila[8] if len(fila) > 8 else None
    culpable = (
        SituationId(crudo_culpable) if crudo_culpable in situaciones else None
    )
    return Recuerdo(
        seq=int(seq),
        tick=int(tick),
        kind=EventKind(kind),
        place=PlaceId(place) if place in lugares else None,
        action=ActionId(action) if action in acciones else None,
        about=AgentId(about) if about in agentes else None,
        importancia=float(importancia),
        valencia=valencia,
        culpable=culpable,
    )


def _dict_a_agente(datos: dict[str, Any], pack: ContentPack) -> AgentState:
    conocidos_relacion = frozenset(str(r.id) for r in pack.relations)
    conocidos_accion = frozenset(str(a.id) for a in pack.actions)
    conocidos_need = frozenset(str(n.id) for n in pack.needs)
    conocidos_lugar = frozenset(str(p.id) for p in pack.places)
    conocidos_rasgo = frozenset(str(t.id) for t in pack.traits)

    busy = None
    if datos["busy"] is not None:
        crudo = dict(datos["busy"])
        tipo = crudo.pop("tipo")
        busy = (
            PerformingAction.model_validate(crudo)
            if tipo == "PerformingAction"
            else Traveling.model_validate(crudo)
        )

    agent = AgentState(
        spec_id=AgentId(datos["spec_id"]),
        at=PlaceId(datos["at"]),
        needs=_reconciliar_necesidades(datos["needs"], pack),
        # Los rasgos borrados del pack se caen: `compose_*` los buscaria en
        # `trait_by_id` y reventaria con un KeyError sin explicacion.
        traits={
            TraitId(k): v for k, v in datos["traits"].items() if k in conocidos_rasgo
        },
        tastes=dict(datos["tastes"]),
        goals={GoalId(k): GoalStatus(v) for k, v in datos["goals"].items()},
        debt={NeedId(k): v for k, v in datos["debt"].items() if k in conocidos_need},
        gain_beliefs={
            ActionId(a): {NeedId(n): v for n, v in c.items()}
            for a, c in datos["gain_beliefs"].items()
            if a in conocidos_accion
        },
        cost_beliefs={
            ActionId(a): {NeedId(n): v for n, v in c.items()}
            for a, c in datos["cost_beliefs"].items()
            if a in conocidos_accion
        },
        bonds={
            AgentId(k): Bond(regard=v["regard"], encounters=v["encounters"],
                             last_seen=v["last_seen"])
            for k, v in datos["bonds"].items()
        },
        relations={
            RelationId(rel): {AgentId(x) for x in quienes}
            for rel, quienes in datos.get("relations", {}).items()
            if rel in conocidos_relacion
        },
        sightings={
            PlaceId(sitio): (tick, frozenset(AgentId(x) for x in quienes))
            for sitio, (tick, quienes) in datos["sightings"].items()
            if sitio in conocidos_lugar
        },
        saturation={
            ActionId(k): v for k, v in datos["saturation"].items() if k in conocidos_accion
        },
        busy=busy,
    )
    # Y aqui se rehace todo lo derivado, contra el pack de hoy.
    agent.recompose(pack)
    agent.refresh_state(pack)
    return agent


def load(path: Path, pack: ContentPack) -> tuple[WorldState, set[tuple[AgentId, AgentId]]]:
    """Recupera la partida sobre el pack dado.

    El pack puede no ser exactamente el que se guardo, y ese es el caso normal:
    se calibra entre corrida y corrida. Lo que no puede es ser OTRO mundo, y por
    eso se comprueba el id — reanudar la ciudad sobre la aldea produciria un
    desastre silencioso en vez de un error.
    """
    datos = json.loads(path.read_text(encoding="utf-8"))

    if datos.get("formato") != FORMATO:
        raise SaveError(
            f"{path}: formato {datos.get('formato')!r}, se esperaba {FORMATO}. "
            f"Media partida mal leida es peor que no cargarla."
        )
    if datos["pack"] != pack.id:
        raise SaveError(
            f"{path}: guardado del pack {datos['pack']!r} y se esta cargando "
            f"{pack.id!r}. Son mundos distintos."
        )

    conocidos = frozenset(str(a.id) for a in pack.agents)
    # Quien ya no existe en el pack no vuelve. Es la contrapartida honesta de
    # reconciliar: el guardado se adapta al pack, no al reves.
    agentes = [_dict_a_agente(d, pack) for d in datos["agents"] if d["spec_id"] in conocidos]

    world = WorldState.new(pack, seed=datos["seed"])
    world.tick = datos["tick"]

    # `.get` y no `[...]`, a diferencia del resto de campos, y no es descuido:
    # un guardado anterior a la memoria episódica se lee perfectamente como
    # alguien que no recuerda nada, que es exactamente lo que era. Bajar
    # `FORMATO` a rechazarlo invalidaría todas las partidas guardadas por un
    # campo que solo añade.
    lugares = frozenset(str(p.id) for p in pack.places)
    acciones = frozenset(str(a.id) for a in pack.actions)
    # Una situación borrada del pack no vuelve, igual que un rasgo o un agente:
    # `gains_at` la buscaría en `situation_by_id` y reventaria con un KeyError.
    conocidas = frozenset(str(s.id) for s in pack.situations)
    for guardado in datos["agents"]:
        if guardado["spec_id"] not in conocidos:
            continue
        filas = guardado.get("memorias", ())
        if filas:
            world.memoria.cargar(
                AgentId(guardado["spec_id"]),
                (
                    _lista_a_recuerdo(f, lugares, acciones, conocidos, conocidas)
                    for f in filas
                ),
            )
    world.situations = {
        SituationId(s): (None if hasta == -1 else int(hasta))
        for s, hasta in datos.get("situations", [])
        if s in conocidas
    }
    # `.get` como en las memorias: un guardado anterior a los disparadores se lee
    # como un mundo donde todavía no había ninguno, que es lo que era.
    world.last_trigger = {
        SituationId(s): int(tick)
        for s, tick in datos.get("last_trigger", [])
        if s in conocidas
    }
    # Los que el pack tiene y el guardado no —fichas nuevas— entran frescos, tal
    # y como los dejo `WorldState.new`. Asi se puede ampliar el elenco sin
    # perder la partida.
    for agente in agentes:
        world.agents[agente.spec_id] = agente

    together = {(AgentId(a), AgentId(b)) for a, b in datos["together"]}
    return world, together
