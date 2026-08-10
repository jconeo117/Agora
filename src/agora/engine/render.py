"""Vista legible del log. Herramienta de depuración, NO el narrador.

La distinción importa. Esto convierte eventos en líneas para que un humano
pueda leer siete días de simulación y detectar que algo va mal. El narrador de
F5 es otra cosa: leerá los mismos eventos pero producirá prosa, con vocabulario
tomado del pack y no de este archivo.

Por eso aquí los verbos están en duro y no pasa nada: nadie va a jugar leyendo
esto. Si algún día se usara para narrar de verdad, el vocabulario tendría que
salir del content pack.
"""

from __future__ import annotations

from collections.abc import Iterator

from agora.engine.events import Event, EventKind, EventLog
from agora.engine.ontology import ClockSpec, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import PerformingAction, Traveling, WorldState


def format_time(tick: int, clock: ClockSpec) -> str:
    """`d3 06:45` o `d3 06:45 manana`. La longitud del día sale del pack.

    La franja se añade solo si el pack declara alguna: en un mundo sin momentos
    del día, esa columna sería siempre la misma palabra.
    """
    day = tick // clock.ticks_per_day + 1
    minute_of_day = (tick % clock.ticks_per_day) * clock.minutes_per_tick
    stamp = f"d{day} {minute_of_day // 60:02d}:{minute_of_day % 60:02d}"
    phase = clock.phase_at(tick)
    return stamp if phase is None else f"{stamp} {phase}"


def _label_of_action(pack: ContentPack, event: Event) -> str:
    return pack.action_by_id[event.action].label if event.action is not None else "?"


def _label_of_place(pack: ContentPack, place: str | None) -> str:
    """Acepta `str` porque los ids que viajan en `Event.data` son escalares
    planos: el payload se diseñó serializable, sin tipos ricos dentro."""
    if place is None:
        return "?"
    spec = pack.place_by_id.get(PlaceId(place))
    return spec.label if spec is not None else place


def render_event(pack: ContentPack, event: Event) -> str:
    actor = pack.agent_by_id[event.actor].label if event.actor is not None else "-"
    when = format_time(event.tick, pack.clock)
    here = _label_of_place(pack, event.place)

    match event.kind:
        case EventKind.ACTION_STARTED:
            util = event.data.get("utility")
            extra = f"   util {util}" if util is not None else ""
            body = f"inicia    {_label_of_action(pack, event)}  ({here}){extra}"
        case EventKind.ACTION_COMPLETED:
            body = f"termina   {_label_of_action(pack, event)}  ({here})"
        case EventKind.ACTION_ABORTED:
            # Dos motivos distintos y hay que distinguirlos: soltar algo por una
            # urgencia no se lee igual que llegar y encontrarse el sitio vacío.
            if event.data.get("reason") == "condiciones":
                causa = f"no se daban las condiciones ({here})"
            else:
                causa = f"{event.data.get('need')} = {event.data.get('value')}"
            body = f"abandona  {_label_of_action(pack, event)}   <- {causa}"
        case EventKind.TRAVEL_STARTED:
            destination = _label_of_place(pack, str(event.data.get("to")))
            body = (
                f"parte     hacia {destination} para {_label_of_action(pack, event)}"
                f"   {event.data.get('ticks')}t   util {event.data.get('utility')}"
            )
        case EventKind.TRAVEL_ARRIVED:
            body = f"llega     {here}"
        case EventKind.ENCOUNTER:
            other = pack.agent_by_id[event.subject].label if event.subject else "?"
            body = f"coincide  con {other}  ({here})"
        case EventKind.NEED_CRITICAL:
            body = f"!!        {event.data.get('need')} = {event.data.get('value')}"
        case EventKind.GOAL_ACHIEVED:
            body = f"LOGRA     {event.data.get('goal')}"
        case EventKind.GOAL_FAILED:
            body = f"PIERDE    {event.data.get('goal')}   <- se acabo el plazo"
        case EventKind.RELATION_BEGAN:
            otro = pack.agent_by_id[event.subject].label if event.subject else "?"
            body = f"AHORA ES  {event.data.get('relation')} de {otro}"
        case EventKind.RELATION_ENDED:
            otro = pack.agent_by_id[event.subject].label if event.subject else "?"
            body = f"YA NO ES  {event.data.get('relation')} de {otro}"
        case EventKind.SITUATION_BEGAN:
            ticks = event.data.get("ticks")
            plazo = "" if ticks == -1 else f"   {ticks}t"
            body = f"EMPIEZA   {event.data.get('situation')}{plazo}"
        case EventKind.SITUATION_ENDED:
            body = f"ACABA     {event.data.get('situation')}"
        case EventKind.IDLE_STALLED:
            body = f"BLOQUEADO sin opciones válidas  ({here})"

    # Sin `case _`: mypy comprueba que el match cubre todos los EventKind, y al
    # añadir uno nuevo señalará este punto en vez de dejarlo caer al genérico.
    return f"{when}  {actor:<7} {body}"


def render_log(pack: ContentPack, log: EventLog) -> Iterator[str]:
    for event in log:
        yield render_event(pack, event)


def render_state(world: WorldState) -> Iterator[str]:
    """Foto del estado actual. Útil como cabecera y como cierre de una corrida."""
    pack = world.pack
    activas = world.active_situations()
    pasando = ""
    if activas:
        pasando = "  [" + ", ".join(pack.situation_by_id[s].label for s in activas) + "]"
    yield f"tick {world.tick}  ({format_time(world.tick, pack.clock)})  seed={world.seed}{pasando}"
    for agent in world.agents_in_order():
        spec = pack.agent_by_id[agent.spec_id]
        needs = "  ".join(f"{need}={value:.2f}" for need, value in agent.needs.items())

        # Capturar los campos en el patrón (y no leer `agent.busy` dentro del
        # cuerpo) es lo que permite a mypy estrechar el tipo: el estrechamiento
        # se aplica al sujeto del match, no a un atributo releído después.
        match agent.busy:
            case PerformingAction(action=action_id, ticks_remaining=left):
                doing = f"{pack.action_by_id[action_id].label}({left}t)"
            case Traveling(destination=target, ticks_remaining=left):
                doing = f"-> {pack.place_by_id[target].label}({left}t)"
            case None:
                doing = "ocioso"
        place = pack.place_by_id[agent.at].label
        yield f"  {spec.label:<7} {place:<24} {doing:<22} {needs}"


def render_activity_summary(pack: ContentPack, log: EventLog) -> Iterator[str]:
    """Cuántas veces completó cada agente cada acción.

    Es el resumen que más rápido delata una mala calibración: si un agente comió
    40 veces y trabajó 2, los números del pack están mal, no el motor.

    Se lee del `recuento` y no de los eventos: así sigue siendo el resumen de la
    corrida ENTERA aunque el log solo conserve los últimos días.
    """
    tally = {
        (pack.agent_by_id[agent].label, pack.action_by_id[action].label): count
        for agent, acciones in log.recuento.por_agente_accion.items()
        for action, count in acciones.items()
    }
    yield "acciones completadas:"
    for (actor, action), count in sorted(tally.items()):
        yield f"  {actor:<7} {action:<22} {count:>4}"
