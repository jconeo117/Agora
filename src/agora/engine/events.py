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

import json
from collections import Counter, deque
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from typing import TextIO

from agora.engine.ontology import ActionId, AgentId, PlaceId

type Payload = Mapping[str, str | int | float | bool]
"""Datos extra del evento. Deliberadamente plano y sin objetos: el log debe
poder serializarse a JSONL sin ceremonia, y un briefing para un modelo pequeño
se construye mucho mejor desde valores escalares."""

SIN_DATOS: Payload = MappingProxyType({})
"""El payload de los eventos que no llevan ninguno, que son el 90%.

Un `default_factory=dict` alojaba un diccionario vacío nuevo por evento: 64
bytes por cada uno de los dos millones de una carrera larga, para no guardar
nada. Compartir uno inmutable cuesta cero y no se puede mutar por accidente."""


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

    GOAL_ACHIEVED = "goal_achieved"
    """Alguien consiguió lo que quería. Cierra un arco y mueve sus rasgos."""

    GOAL_FAILED = "goal_failed"
    """Se le acabó el plazo. Suele ser el material más interesante de los dos."""

    IDLE_STALLED = "idle_stalled"
    """Un agente quedó ocioso sin ninguna opción válida. En un motor sano no
    debería aparecer nunca; si aparece en el log, hay un bug de diseño en el
    pack (falta la acción de red de seguridad) o en la deliberación."""


@dataclass(frozen=True, slots=True)
class Event:
    """Un hecho ocurrido. Inmutable: el pasado no se reescribe.

    **No es un modelo de pydantic, y la distinción es de fondo:** pydantic
    existe para validar lo que escribe el humano —el YAML del pack, que puede
    estar mal—. Un evento lo construye el motor con datos que él mismo acaba de
    calcular. Validarlo es pagar por comprobar lo que ya sabemos.

    El precio era literal. Medido, doscientos mil eventos de cada:

        pydantic (frozen)      1176 B/evento    6.84 us/emision
        dataclass + slots       136 B/evento    3.83 us/emision

    Un `BaseModel` congelado arrastra `__dict__`, `__pydantic_extra__`,
    `__pydantic_private__` y `__pydantic_fields_set__` —este último un *set*,
    que solo él ya pesa mas que el evento entero—. Con `slots` no hay ninguno de
    los cuatro. En una carrera de cinco años son treinta gigas contra cuatro.
    """

    seq: int
    tick: int
    kind: EventKind
    actor: AgentId | None = None
    place: PlaceId | None = None
    action: ActionId | None = None
    subject: AgentId | None = None
    """El otro agente implicado, cuando lo hay (encuentros, y en F2 diálogo)."""

    data: Payload = SIN_DATOS

    def __deepcopy__(self, memo: dict[int, Any]) -> Event:
        """Se devuelve a sí mismo, y no es un atajo sucio: es la consecuencia de
        ser inmutable. Copiar un hecho pasado no puede producir nada distinto.

        Lo destapó `error_de_salto`, que clona la simulación dos veces: estaba
        deep-copiando dos millones de eventos uno a uno para volver a tener
        exactamente los mismos.
        """
        return self

    def __copy__(self) -> Event:
        return self

    def to_json(self) -> str:
        """Una línea JSONL. Se omite lo que no lleva valor, incluido el payload
        vacío: en el 90% de los eventos `"data":{}` era ruido puro."""
        campos: dict[str, Any] = {"seq": self.seq, "tick": self.tick, "kind": self.kind.value}
        if self.actor is not None:
            campos["actor"] = self.actor
        if self.place is not None:
            campos["place"] = self.place
        if self.action is not None:
            campos["action"] = self.action
        if self.subject is not None:
            campos["subject"] = self.subject
        if self.data:
            campos["data"] = dict(self.data)
        return json.dumps(campos, separators=(",", ":"), ensure_ascii=False)


@dataclass(slots=True)
class Recuento:
    """Los totales de la corrida, acumulados al emitir.

    Existe por dos razones y la segunda es la importante.

    La barata: `health` y el resumen de actividad recorrían dos millones de
    eventos para producir treinta números. Contar al emitir cuesta cero.

    **La que manda: hace que los totales no dependan de lo que el log conserve.**
    En cuanto haya ventana, `of_kind` solo ve el tramo retenido, y un resumen
    calculado sobre él *mentiría* en vez de fallar. Por eso esto va ANTES que la
    ventana y no después.

    Tres campos con nombre y no un contador genérico: cada uno responde a una
    pregunta concreta que ya se hace hoy.
    """

    por_tipo: Counter[EventKind] = field(default_factory=Counter)
    """Cuántos de cada clase. Completadas, abortadas y bloqueos salen de aquí."""

    por_agente_accion: dict[AgentId, Counter[ActionId]] = field(default_factory=dict)
    """Quién completó qué, y cuántas veces. Es el perfil con el que se mide la
    diferenciación: si dos agentes tienen el mismo, el pack no los distingue."""

    ticks_de_viaje: int = 0
    """Tiempo total en tránsito. El único campo que lee dentro de un payload
    (`ticks` de TRAVEL_STARTED), porque el dato no cabe en el propio evento."""

    def anotar(self, event: Event) -> None:
        self.por_tipo[event.kind] += 1
        if event.kind is EventKind.ACTION_COMPLETED:
            if event.actor is not None and event.action is not None:
                self.por_agente_accion.setdefault(event.actor, Counter())[event.action] += 1
        elif event.kind is EventKind.TRAVEL_STARTED:
            ticks = event.data.get("ticks", 0)
            self.ticks_de_viaje += int(ticks) if isinstance(ticks, int | float) else 0


class EventoDesalojadoError(LookupError):
    """Se pidió un evento que la ventana ya descartó.

    Revienta a propósito. Con ventana, `self._events[seq]` devolvería un evento
    DISTINTO en silencio, y ese es exactamente el tipo de fallo que este
    proyecto no se puede permitir: un log que miente sin avisar.
    """


LOTE_DE_PURGA = 4096
"""Cada cuántos eventos se mira si hay que desalojar.

No se purga en cada emisión porque `del lista[:k]` mueve el resto: hacerlo de
uno en uno sería cuadrático. En lotes es amortizado O(1), a cambio de que la
ventana retenga un poco más de lo pedido, nunca menos."""


class EventLog:
    """Append-only, con índices para las consultas que el motor hará de verdad.

    Los índices por actor y por lugar no son optimización prematura: son
    exactamente las dos preguntas de F1. "¿Qué recuerda Mira?" y "¿qué ha
    pasado en esta plaza?". Construirlos al insertar cuesta nada; reconstruirlos
    después obliga a recorrer el log entero en cada consulta.

    **La ventana.** Con `window` en ticks, el log conserva solo lo reciente. No
    es solo un apaño de memoria: la memoria episódica de F1 va a leer de aquí, y
    *nadie recuerda cinco años de comidas*. Se saca lo saliente de una ventana,
    no de un archivo perpetuo.

    Lo que la ventana NO toca:

    - `seq` sigue siendo global y monótono, como promete su docstring. Nunca se
      reutiliza; simplemente deja de haber evento detrás, y pedirlo revienta.
    - `recuento` sigue siendo el de la corrida entera. Por eso se construyó
      antes que esto.

    Ojo a cómo se combina con el salto temporal: la ventana cuenta en tiempo del
    MUNDO, no en días simulados. Con `--skip 14 --window 7` el reloj avanza trece
    días de golpe entre tramo y tramo, así que lo que queda retenido es el último
    día simulado y no siete. Es correcto —el mundo sí pasó por esos días— pero no
    es lo que sugiere el número.

    **El vertido.** Con `sink`, cada evento se escribe según se genera. Es lo que
    hace inocua a la ventana: la historia entera queda en el fichero y en memoria
    solo vive lo reciente. Antes el volcado se hacía al final, así que para
    obtener el fichero había que retener antes los dos millones de eventos.

    Sin `window` ni `sink`, nada cambia: se guarda todo, como siempre.
    """

    __slots__ = (
        "_by_actor",
        "_by_place",
        "_desalojados",
        "_events",
        "_sin_purgar",
        "_sink",
        "_window",
        "recuento",
    )

    def __init__(self, window: int | None = None, sink: TextIO | None = None) -> None:
        self._events: list[Event] = []
        # Deques y no listas: el desalojo va en orden de `seq`, así que el que
        # se va siempre es la cabeza, y `popleft` en un deque es O(1).
        self._by_actor: dict[AgentId, deque[int]] = {}
        self._by_place: dict[PlaceId, deque[int]] = {}
        self.recuento = Recuento()
        self._window = window
        self._sink = sink
        self._desalojados = 0
        """Cuántos se descartaron. Es también el `seq` del primero que queda, y
        con eso se traduce un `seq` a su posición actual en la lista."""
        self._sin_purgar = 0

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
            # `_desalojados +` y no `len(self._events)` a secas: lo segundo
            # reiniciaría la numeración cada vez que la ventana descarta, y
            # `seq` es la clave con la que F1 referenciará recuerdos.
            seq=self._desalojados + len(self._events),
            tick=tick,
            kind=kind,
            actor=actor,
            place=place,
            action=action,
            subject=subject,
            data=data if data else SIN_DATOS,
        )
        self._events.append(event)
        self.recuento.anotar(event)
        # Antes de indexar y antes de purgar: al vertido va TODO lo que ocurre,
        # se retenga o no. Es lo que permite descartar en memoria sin perder.
        if self._sink is not None:
            self._sink.write(event.to_json())
            self._sink.write("\n")

        if event.actor is not None:
            self._by_actor.setdefault(event.actor, deque()).append(event.seq)
        # Un encuentro es memoria de ambos, no solo de quien lo provocó.
        if event.subject is not None:
            self._by_actor.setdefault(event.subject, deque()).append(event.seq)
        if event.place is not None:
            self._by_place.setdefault(event.place, deque()).append(event.seq)

        self._sin_purgar += 1
        if self._window is not None and self._sin_purgar >= LOTE_DE_PURGA:
            self._purgar(tick)

        return event

    def _purgar(self, tick_actual: int) -> None:
        """Descarta lo que quedó fuera de la ventana, en un solo corte.

        Los índices guardan `seq`, no eventos: si no se podan también, la
        memoria sigue creciendo aunque los eventos se vayan. Y como el desalojo
        va en orden de `seq` y cada índice los tiene ascendentes, el que se va
        siempre es la cabeza — de ahí los deques.
        """
        assert self._window is not None
        self._sin_purgar = 0
        limite = tick_actual - self._window

        cuantos = 0
        for event in self._events:
            if event.tick >= limite:
                break
            cuantos += 1
        if cuantos == 0:
            return

        for event in self._events[:cuantos]:
            if event.actor is not None:
                self._by_actor[event.actor].popleft()
            if event.subject is not None:
                self._by_actor[event.subject].popleft()
            if event.place is not None:
                self._by_place[event.place].popleft()

        del self._events[:cuantos]
        self._desalojados += cuantos

    def __len__(self) -> int:
        """Los RETENIDOS, que son los que se pueden recorrer.

        Con ventana esto deja de ser lo mismo que `emitidos`, y se elige que
        `len` case con la iteración: un `len` que no coincide con lo que sale al
        iterar es peor mentira que un número más pequeño del esperado.
        """
        return len(self._events)

    @property
    def emitidos(self) -> int:
        """Cuántos ocurrieron en total, se conserven o no."""
        return self._desalojados + len(self._events)

    @property
    def desalojados(self) -> int:
        return self._desalojados

    def __iter__(self) -> Iterator[Event]:
        return iter(self._events)

    def __getitem__(self, seq: int) -> Event:
        posicion = seq - self._desalojados
        if posicion < 0 or posicion >= len(self._events):
            raise EventoDesalojadoError(
                f"el evento {seq} ya no está: la ventana conserva "
                f"de {self._desalojados} a {self.emitidos - 1}"
            )
        return self._events[posicion]

    def by_actor(self, actor: AgentId) -> list[Event]:
        """Todo lo que este agente vivió. Base de la memoria episódica (F1)."""
        return [self[seq] for seq in self._by_actor.get(actor, ())]

    def by_place(self, place: PlaceId) -> list[Event]:
        """Todo lo que ocurrió aquí. Base de la memoria del lugar (F1).

        Es lo que convierte "la plaza" en "la plaza donde ahorcaron a mi
        hermano", y no cuesta ni una llamada al modelo.
        """
        return [self[seq] for seq in self._by_place.get(place, ())]

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
        """Serialización estable de lo RETENIDO, para diffear dos corridas.

        El test de determinismo compara exactamente esto: mismo seed, mismo
        JSONL, byte a byte. Con ventana solo cubre el tramo conservado; para una
        corrida larga, lo que hay que diffear es el fichero del `sink`, que sí
        lo lleva todo.
        """
        return (event.to_json() for event in self._events)
