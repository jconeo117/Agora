"""Registro de eventos: la única ventana al mundo.

Regla dura: **nada muta el estado sin emitir un evento**. En F0 el log es la
forma de leer la simulación; en F1 se convierte en la materia prima de la
memoria de los agentes y de la memoria de los lugares; en F5 es lo que el
narrador consulta para no inventarse nada.

Si un cambio no deja evento, para las capas de arriba ese cambio nunca ocurrió.

El log es append-only y cada entrada lleva un `seq` monótono. Ese `seq` es el
identificador con el que `MemoryStore` referencia recuerdos, así que no se
reordena ni se reutiliza jamás.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agora.engine.ontology import ActionId, AgentId, PlaceId

type Payload = Mapping[str, str | int | float | bool]
"""Datos extra del evento. Deliberadamente plano y sin objetos: el log debe
poder serializarse a JSONL sin ceremonia, y un briefing para un modelo pequeño
se construye mucho mejor desde valores escalares."""


class EventKind(StrEnum):
    """Vocabulario de eventos. Abstracto: ninguno nombra ambientación."""

    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_ABORTED = "action_aborted"
    """La acción dejó de ser válida a mitad. Sin esto, depurar agentes
    atascados es adivinar."""

    TRAVEL_STARTED = "travel_started"
    TRAVEL_ARRIVED = "travel_arrived"

    ENCOUNTER = "encounter"
    """Dos agentes coinciden en un lugar. En F0 solo se registra; en F1 mueve
    relaciones y en F2 dispara diálogo."""

    NEED_CRITICAL = "need_critical"
    """Una necesidad cruzó su umbral hacia abajo. Es la señal barata que en F1
    marca recuerdos como importantes: lo que duele, se recuerda."""

    IDLE_STALLED = "idle_stalled"
    """Un agente quedó ocioso sin ninguna opción válida. En un motor sano no
    debería aparecer nunca; si aparece en el log, hay un bug de diseño en el
    pack (falta la acción de red de seguridad) o en la deliberación."""


class Event(BaseModel):
    """Un hecho ocurrido. Inmutable: el pasado no se reescribe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int = Field(ge=0)
    tick: int = Field(ge=0)
    kind: EventKind
    actor: AgentId | None = None
    place: PlaceId | None = None
    action: ActionId | None = None
    subject: AgentId | None = None
    """El otro agente implicado, cuando lo hay (encuentros, y en F2 diálogo)."""

    data: Payload = Field(default_factory=dict)


class EventLog:
    """Append-only, con índices para las consultas que el motor hará de verdad.

    Los índices por actor y por lugar no son optimización prematura: son
    exactamente las dos preguntas de F1. "¿Qué recuerda Mira?" y "¿qué ha
    pasado en esta plaza?". Construirlos al insertar cuesta nada; reconstruirlos
    después obliga a recorrer el log entero en cada consulta.
    """

    __slots__ = ("_by_actor", "_by_place", "_events")

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_actor: dict[AgentId, list[int]] = {}
        self._by_place: dict[PlaceId, list[int]] = {}

    def emit(
        self,
        *,
        tick: int,
        kind: EventKind,
        actor: AgentId | None = None,
        place: PlaceId | None = None,
        action: ActionId | None = None,
        subject: AgentId | None = None,
        data: Payload | None = None,
    ) -> Event:
        """Registra un hecho y devuelve el evento ya sellado con su `seq`.

        Solo por argumentos con nombre: una llamada con seis posicionales del
        mismo tipo es un error esperando a ocurrir.
        """
        event = Event(
            seq=len(self._events),
            tick=tick,
            kind=kind,
            actor=actor,
            place=place,
            action=action,
            subject=subject,
            data=data or {},
        )
        self._events.append(event)

        if event.actor is not None:
            self._by_actor.setdefault(event.actor, []).append(event.seq)
        # Un encuentro es memoria de ambos, no solo de quien lo provocó.
        if event.subject is not None:
            self._by_actor.setdefault(event.subject, []).append(event.seq)
        if event.place is not None:
            self._by_place.setdefault(event.place, []).append(event.seq)

        return event

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __getitem__(self, seq: int) -> Event:
        return self._events[seq]

    def by_actor(self, actor: AgentId) -> list[Event]:
        """Todo lo que este agente vivió. Base de la memoria episódica (F1)."""
        return [self._events[seq] for seq in self._by_actor.get(actor, ())]

    def by_place(self, place: PlaceId) -> list[Event]:
        """Todo lo que ocurrió aquí. Base de la memoria del lugar (F1).

        Es lo que convierte "la plaza" en "la plaza donde ahorcaron a mi
        hermano", y no cuesta ni una llamada al modelo.
        """
        return [self._events[seq] for seq in self._by_place.get(place, ())]

    def since(self, tick: int) -> list[Event]:
        """Eventos desde `tick` inclusive. El log está ordenado por tick, así
        que basta recorrer desde el final hacia atrás."""
        cut = len(self._events)
        while cut > 0 and self._events[cut - 1].tick >= tick:
            cut -= 1
        return self._events[cut:]

    def of_kind(self, *kinds: EventKind) -> list[Event]:
        wanted = frozenset(kinds)
        return [event for event in self._events if event.kind in wanted]

    def to_jsonl(self) -> Iterable[str]:
        """Serialización estable para diffear dos corridas con el mismo seed.

        El test de determinismo compara exactamente esto: mismo seed, mismo
        JSONL, byte a byte.
        """
        return (event.model_dump_json(exclude_none=True) for event in self._events)
