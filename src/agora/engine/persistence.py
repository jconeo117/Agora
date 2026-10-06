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
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.memory import Recuerdo
from agora.engine.ontology import (
    ActionId,
    AgentId,
    AgentSpec,
    FactionId,
    FactionKindId,
    GoalId,
    GoalStatus,
    NeedId,
    PlaceId,
    PropertyId,
    PropertyKind,
    RelationId,
    SituationId,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.state import (
    AgentState,
    Bond,
    Condicion,
    Faccion,
    PerformingAction,
    Propiedad,
    Traveling,
    WorldState,
)

FORMATO = 1
"""Version del formato en disco. Un guardado de otra version se rechaza en vez
de cargarse a medias: media partida mal leida es peor que no cargarla."""


class SaveError(ValueError):
    """El guardado no se puede leer con este pack."""


# -----------------------------------------------------------------------------
# Escribir
# -----------------------------------------------------------------------------


def _bond_a_dict(bond: Bond) -> dict[str, Any]:
    return {"regard": bond.regard, "encounters": bond.encounters,
            "shared": bond.shared, "last_seen": bond.last_seen}


def _recuerdo_a_lista(r: Recuerdo) -> list[Any]:
    """Un recuerdo como lista posicional: `[seq, tick, kind, place, action, about,
    importancia, valencia, culpable, por_quien, de_oidas]`.

    Lista y no diccionario por tamaño, que aquí sí importa. Con ciento veintisiete
    agentes y capacidad de doscientos son veinticinco mil recuerdos, y el volcado
    va con `indent=1`: en forma de diccionario son diez líneas cada uno —un cuarto
    de millón de líneas para el mismo dato—. Sigue siendo diffeable, que es lo que
    el guardado tiene que ser.

    Las dos últimas faltaron hasta el 2026-10-05, y sin ellas reanudar olvidaba
    de quién venía cada agravio y daba todo rumor por vivido.
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
        None if r.por_quien is None else str(r.por_quien),
        r.de_oidas,
    ]


def _agente_a_dict(agent: AgentState, recuerdos: tuple[Recuerdo, ...]) -> dict[str, Any]:
    """Solo lo que no se puede recalcular.

    Fuera queda lo derivado. `need_weights`, `phase_shift`, `aptitud_base`,
    `gains`, `caps`, `costs` y `temperament` los rehace `recompose` desde los
    rasgos y las metas; `strain` lo rehace `refresh_state` desde las
    necesidades; `metas` es la ficha, que está en el pack o en `nacidos`; y
    `ledger` es un instrumento de `health`, no estado de la partida.
    Recomponerlos al cargar es más barato que arrastrarlos y más seguro que
    confiar en que sigan valiendo con el pack de hoy. `test_reanudar.py`
    falla si aparece un campo que no está ni aquí ni en el guardado.
    """
    busy: dict[str, Any] | None = None
    if agent.busy is not None:
        busy = {"tipo": type(agent.busy).__name__, **agent.busy.model_dump()}

    return {
        "spec_id": str(agent.spec_id),
        "at": str(agent.at),
        # Cuándo entró en el mundo (D-070). Sin esto, reanudar devuelve a todo
        # el mundo a la edad que el pack le dio de partida, y un mundo con
        # puertas de edad se rejuvenece entero al cargar.
        "nacido_en": agent.nacido_en,
        # A qué grupos pertenece y cuánto. La clave ES la pertenencia (D-090),
        # así que esto guarda las dos cosas de una vez.
        "lealtad": {str(f): v for f, v in sorted(agent.lealtad.items())},
        "needs": {str(k): v for k, v in agent.needs.items()},
        "traits": {str(k): v for k, v in agent.traits.items()},
        "tastes": dict(agent.tastes),
        "goals": {str(k): v.value for k, v in agent.goals.items()},
        "debt": {str(k): v for k, v in agent.debt.items()},
        # Sin esto, guardar y reanudar le perdona a todo el mundo lo que llevaba
        # sin comer. La deuda ya se guardaba; el reloj que mata, no existía.
        "agonia": {str(k): v for k, v in agent.agonia.items()},
        # Cuantos rangos lleva rotos. Sin esto, reanudar devuelve a todo el
        # mundo a novato: el valor del eje se guarda, pero el valor de un eje
        # con rangos no significa nada sin el rango que lo acompanya.
        "rango": {str(k): v for k, v in agent.rango.items()},
        # Lo que lleva encima. Una lista de listas y no de dicts: se escribe una
        # por herida y por cabeza, y aqui las claves repetidas pesan.
        "condiciones": [
            [str(c.situacion), c.marca, c.gravedad,
             -1 if c.hasta is None else c.hasta,
             "" if c.donde is None else str(c.donde),
             "" if c.por_quien is None else str(c.por_quien)]
            for c in agent.condiciones
        ],
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


def _propiedad_a_dict(prop: Propiedad, del_pack: bool) -> dict[str, Any]:
    """Lo que hay que guardar de una propiedad, que depende de si el pack la
    conoce: de la suya, solo lo que cambió; de una nacida en marcha, todo.
    """
    datos: dict[str, Any] = {
        "id": str(prop.id),
        "dueño": None if prop.dueño is None else str(prop.dueño),
        "dueña": None if prop.dueña is None else str(prop.dueña),
        "saldo": sorted([str(n), v] for n, v in prop.saldo.items()),
    }
    if not del_pack:
        datos["tipo"] = str(prop.tipo)
        datos["objeto"] = prop.objeto
        datos["renta"] = sorted([str(n), v] for n, v in prop.renta.items())
    return datos


def save(
    world: WorldState,
    together: set[tuple[AgentId, AgentId]],
    path: Path,
    siguiente_seq: int = 0,
) -> None:
    """Vuelca la partida. El pack NO va dentro: se pasa al cargar.

    Dejarlo fuera es lo que permite reanudar sobre un pack retocado, que es el
    caso normal cuando se esta calibrando.
    """
    pack_ids = {a.id for a in world.pack.agents}
    datos = {
        "formato": FORMATO,
        "pack": world.pack.id,
        "tick": world.tick,
        "seed": world.rng.seed,
        # Por dónde va la numeración de los sucesos. Sin esto, la partida
        # reanudada numeraba desde cero y sus recuerdos nuevos repetían `seq`.
        "seq": siguiente_seq,
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
        # QUIÉN NO ESTÁ, Y POR QUÉ NO ESTÁ.
        #
        # Sin esta lista, un muerto es indistinguible de una ficha nueva: los dos
        # están en el pack y ninguno está en `agents`. Y como al cargar se parte
        # de `WorldState.new` —que crea a TODOS los del pack— para que el elenco
        # se pueda ampliar sin perder la partida, **el muerto volvía vivo**.
        #
        # Medido: 199 vivos antes de guardar, 200 después de reanudar.
        #
        # No es lo mismo que el censo, que se reconstruye del pack de hoy. Esto
        # es lo único del reparto que no se puede derivar: la ausencia con causa.
        "muertos": sorted(str(a) for a in set(world.censo) - set(world.agents)),
        # QUIÉN NACIÓ DESPUÉS DE EMPEZAR (D-071). Del resto del reparto basta
        # con el estado, porque su ficha está en el pack y se reconstruye de
        # ahí; de estos no hay ficha en ningún YAML, así que o se guarda entera
        # o al reanudar no existen. Es la misma decisión que con una deuda
        # nacida en marcha (D-065), un escalón más arriba: aquí lo que se pierde
        # no es un renglón de contabilidad, es una persona.
        "nacidos": [
            world.censo[a].model_dump(mode="json")
            for a in sorted(set(world.censo) - set(pack_ids))
        ],
        # De una propiedad DEL PACK se guarda lo que cambia en marcha —el dueño
        # y lo que queda por cobrar— y nada más: tipo, objeto, renta y tributo
        # los fija el pack de HOY, igual que el fade de la memoria, y guardarlos
        # otra vez los dejaría desincronizados en cuanto se retoque el pack
        # entre corrida y corrida.
        #
        # Una DEUDA nacida en marcha (D-065) no tiene esa red: el pack no sabe
        # nada de ella, así que o se guarda entera o se pierde al reanudar. Es
        # la primera vez que el guardado lleva algo que no es el estado mutable
        # de una entidad declarada, sino la entidad.
        # LOS GRUPOS ENTEROS. No hay `FactionSpec` en el pack del que
        # reconstruirlos —el pack solo declara CLASES— así que o se guardan o al
        # reanudar no existen, igual que quien nació en marcha (D-071).
        "facciones": [
            {
                "id": str(f.id),
                "tipo": str(f.tipo),
                "label": f.label,
                "fundada_en": f.fundada_en,
                "fundador": None if f.fundador is None else str(f.fundador),
                "enemigas": sorted(str(e) for e in f.enemigas),
                "prestigio": f.prestigio,
            }
            for f in sorted(world.facciones.values(), key=lambda x: x.id)
        ],
        "propiedades": [
            _propiedad_a_dict(prop, prop.id in world.pack.property_by_id)
            for prop in sorted(world.propiedades.values(), key=lambda p: p.id)
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
    # Quién lo hizo y de cuántas bocas llegó. Misma tolerancia: una fila corta
    # es de un guardado anterior, y se lee como de nadie y de primera mano.
    crudo_por_quien = fila[9] if len(fila) > 9 else None
    por_quien = AgentId(crudo_por_quien) if crudo_por_quien in agentes else None
    de_oidas = int(fila[10]) if len(fila) > 10 else 0
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
        por_quien=por_quien,
        de_oidas=de_oidas,
    )


def _dict_a_agente(
    datos: dict[str, Any], pack: ContentPack,
    nacidos: Mapping[AgentId, AgentSpec] | None = None,
) -> AgentState:
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
        # `.get` con el defecto de siempre: un guardado anterior a las edades se
        # lee como un mundo donde todos nacieron en el tick cero, que es lo que
        # era -- no había edad que llevar.
        nacido_en=int(datos.get("nacido_en", 0)),
        lealtad={
            FactionId(f): float(v) for f, v in datos.get("lealtad", {}).items()
        },
        # Las metas salen de la ficha, no del guardado: son catálogo, como los
        # rasgos del pack. La de quien nació en marcha viene en `nacidos`, que
        # es su unica ficha en el mundo.
        metas=tuple(
            (pack.agent_by_id.get(AgentId(datos["spec_id"]))
             or (nacidos or {}).get(AgentId(datos["spec_id"]))
             or AgentSpec(id=AgentId(datos["spec_id"]), label="", home=PlaceId(datos["at"]),
                          start_at=PlaceId(datos["at"]))).goals
        ),
        needs=_reconciliar_necesidades(datos["needs"], pack),
        # Los rasgos borrados del pack se caen: `compose_*` los buscaria en
        # `trait_by_id` y reventaria con un KeyError sin explicacion.
        traits={
            TraitId(k): v for k, v in datos["traits"].items() if k in conocidos_rasgo
        },
        tastes=dict(datos["tastes"]),
        goals={GoalId(k): GoalStatus(v) for k, v in datos["goals"].items()},
        debt={NeedId(k): v for k, v in datos["debt"].items() if k in conocidos_need},
        # `.get` como las memorias y los disparadores: un guardado anterior a
        # esto se lee como alguien que no lleva nada a cero, que es lo que era.
        agonia={
            NeedId(k): int(v)
            for k, v in datos.get("agonia", {}).items()
            if k in conocidos_need
        },
        rango={
            NeedId(k): int(v)
            for k, v in datos.get("rango", {}).items()
            if k in conocidos_need
        },
        # Una condicion cuya situacion ya no existe en el pack no vuelve, igual
        # que un rasgo o un agente borrado: `by_situation` reventaria al aplicar
        # sus efectos.
        condiciones=[
            Condicion(
                situacion=SituationId(s), marca=str(marca), gravedad=float(veces),
                hasta=None if int(hasta) < 0 else int(hasta),
                # Un lugar borrado del pack se lee como "sin sitio": la herida
                # sigue doliendo, pero ya no se puede temer donde te la hicieron.
                donde=PlaceId(donde) if donde in conocidos_lugar else None,
                # Y quién se la pegó. Un guardado anterior a D-071 se lee como
                # una condición sin autor, que es lo que era: entonces ninguna
                # lo tenía. Un autor que ya no está en el censo se mantiene a
                # propósito -- lo que cuelga de la condición (el parto) ya sabe
                # tratar con un causante muerto, y borrarlo aquí convertiría a
                # un huérfano en hijo de nadie por haber guardado la partida.
                por_quien=AgentId(autor) if autor else None,
            )
            for s, marca, veces, hasta, *resto in datos.get("condiciones", ())
            for donde in (resto[0] if resto else "",)
            for autor in (resto[1] if len(resto) > 1 else "",)
            if s in {str(x.id) for x in pack.situations}
        ],
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
            # `shared` llego despues: un guardado sin el se lee como gente que se
            # conocia sin haber compartido nada, que es lo que el motor sabia
            # decir entonces.
            AgentId(k): Bond(regard=v["regard"], encounters=v["encounters"],
                             shared=v.get("shared", 0), last_seen=v["last_seen"])
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


def load(
    path: Path, pack: ContentPack
) -> tuple[WorldState, set[tuple[AgentId, AgentId]], int]:
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

    # Los que nacieron en marcha entran en el censo ANTES de rehidratar a nadie:
    # su ficha no está en el pack, y sin ella `_dict_a_agente` los descartaría
    # como si el pack los hubiera borrado. Una ficha guardada que ya no valide
    # contra el pack de hoy —un rasgo que desapareció, una meta que se quitó—
    # se cae aquí con el resto, que es la misma regla de siempre.
    nacidos: dict[AgentId, AgentSpec] = {}
    for crudo in datos.get("nacidos", []):
        try:
            ficha = AgentSpec.model_validate(crudo)
        except ValidationError:
            continue
        nacidos[ficha.id] = ficha

    conocidos = frozenset(str(a.id) for a in pack.agents) | {str(a) for a in nacidos}
    # Quien ya no existe en el pack no vuelve. Es la contrapartida honesta de
    # reconciliar: el guardado se adapta al pack, no al reves.
    agentes = [
        _dict_a_agente(d, pack, nacidos)
        for d in datos["agents"]
        if d["spec_id"] in conocidos
    ]

    world = WorldState.new(pack, seed=datos["seed"])
    world.tick = datos["tick"]
    world.censo.update(nacidos)
    # Una clase de facción borrada del pack se lleva sus grupos, igual que un
    # rasgo borrado se cae de las fichas.
    for cruda in datos.get("facciones", []):
        if cruda["tipo"] not in pack.faction_kind_by_id:
            continue
        world.facciones[FactionId(cruda["id"])] = Faccion(
            id=FactionId(cruda["id"]),
            tipo=FactionKindId(cruda["tipo"]),
            label=str(cruda["label"]),
            fundada_en=int(cruda["fundada_en"]),
            fundador=None if cruda["fundador"] is None else AgentId(cruda["fundador"]),
            enemigas={FactionId(e) for e in cruda.get("enemigas", [])},
            prestigio=float(cruda.get("prestigio", 0.0)),
        )

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
    # `.get` como el resto de lo añadido después: un guardado anterior a la
    # propiedad se lee como un mundo donde nadie había reasignado ninguna
    # todavía, y cada una se queda con el `dueño_inicial` que `WorldState.new`
    # ya le puso. Una propiedad borrada del pack no vuelve, igual que un
    # agente o una situación; una nueva entra con lo que el pack diga, porque
    # el guardado no puede tener opinión sobre algo que no existía.
    for fila in datos.get("propiedades", []):
        # Un guardado anterior a D-065 escribía pares `[id, dueño]` en vez de un
        # objeto. Se leen los dos: las partidas largas son horas de simulación y
        # tirarlas para no escribir cuatro líneas sería cobrar caro un formato.
        if isinstance(fila, list):
            fila = {"id": fila[0], "dueño": fila[1]}
        id_prop = PropertyId(str(fila["id"]))
        propiedad = world.propiedades.get(id_prop)
        if propiedad is None:
            # No está en el pack de hoy. O nació en marcha —y entonces el
            # guardado trae con qué reconstruirla— o el pack la borró entre
            # corridas, y una propiedad borrada no vuelve, igual que un agente
            # o una situación.
            if "tipo" not in fila:
                continue
            renta = {
                NeedId(str(n)): float(v)
                for n, v in fila.get("renta", [])
                if NeedId(str(n)) in pack.need_by_id
            }
            if not renta:
                # Todos sus ejes desaparecieron del pack: no queda nada que
                # cobrar, así que no hay deuda que reconstruir.
                continue
            propiedad = Propiedad(
                id=id_prop,
                tipo=PropertyKind(str(fila["tipo"])),
                objeto=str(fila["objeto"]),
                renta=renta,
                tributo={},
            )
            world.propiedades[id_prop] = propiedad
        propiedad.dueño = None if fila["dueño"] is None else AgentId(str(fila["dueño"]))
        # Un grupo borrado del pack no existe, así que su propiedad vuelve a no
        # ser de nadie -- misma regla que un agente borrado.
        dueña = fila.get("dueña")
        propiedad.dueña = (
            FactionId(str(dueña)) if dueña and FactionId(str(dueña)) in world.facciones
            else None
        )
        # Solo si trae algo: un saldo vacío en el guardado significa "esta
        # propiedad era perpetua cuando se guardó", y sobrescribir con él
        # borraría un `saldo` que el pack de hoy acabe de declarar. Una deuda
        # que llegó a cero no se guarda nunca — se extingue antes.
        saldo = {
            NeedId(str(n)): float(v)
            for n, v in fila.get("saldo", [])
            if NeedId(str(n)) in pack.need_by_id
        }
        if saldo:
            propiedad.saldo = saldo
    # Los que el pack tiene y el guardado no —fichas nuevas— entran frescos, tal
    # y como los dejo `WorldState.new`. Asi se puede ampliar el elenco sin
    # perder la partida.
    for agente in agentes:
        world.agents[agente.spec_id] = agente

    # Y los que faltaban POR MUERTOS se van otra vez. Es la contrapartida de lo
    # de arriba: la misma tolerancia que deja entrar a una ficha nueva resucitaba
    # a quien se habia muerto, porque los dos se ven igual desde aqui — estan en
    # el pack y no estan en el guardado.
    #
    # `.get` con vacio por defecto: un guardado anterior a este campo se lee como
    # una partida donde no habia muerto nadie, que es lo que casi siempre era.
    # Bajar `FORMATO` a rechazarlo invalidaria todas las partidas por un campo
    # que solo anyade informacion.
    #
    # Se quedan en el CENSO, que es lo que permite seguir nombrandolos: el mundo
    # sigue sabiendo quien fue.
    for difunto in datos.get("muertos", ()):
        world.agents.pop(AgentId(difunto), None)

    together = {(AgentId(a), AgentId(b)) for a, b in datos["together"]}
    return world, together, int(datos.get("seq", 0))
