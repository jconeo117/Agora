"""Puertos: las fronteras del motor con el mundo exterior.

Ninguno se implementa en F0. Existen ahora para que el motor se construya
*contra ellos* desde el primer día. Un puerto añadido tarde obliga a reescribir
todo lo que debió pasar por él.

`Protocol` es el equivalente Python de una `interface` de C#: mypy verifica que
una clase la cumple sin que esta herede de nada.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agora.engine.ontology import AgentId

if TYPE_CHECKING:
    # Solo para tipar. En runtime un `Protocol` marcado como `runtime_checkable`
    # comprueba nombres de método, no firmas, así que importar de verdad aquí
    # solo serviría para acoplar el puerto a su implementación.
    from agora.engine.events import Event
    from agora.engine.memory import Cue, Recuerdo


class Outcome(StrEnum):
    """Resultado abstracto de una tirada. Deliberadamente pobre.

    Todo sistema de rol sabe expresar estos cuatro estados. Si añadimos un
    quinto porque "d20 lo necesita", el motor deja de ser agnóstico.

    El cuarto fue `GRAVE_FAILURE` hasta la unidad 08 (D-153). Con el primer
    sistema de verdad resultó que la gravedad de un fallo no es un resultado: la
    pone la posición desde la que se tira. Lo que el resultado sí tiene que
    distinguir es el acierto que sube el efecto. Nadie lo usaba.
    """

    FAILURE = "failure"
    SUCCESS_AT_COST = "success_at_cost"
    SUCCESS = "success"
    CRITICAL = "critical"


class Effect(IntEnum):
    """Cuánto se logra al acertar, en pasos enteros (unidad 08).

    Entero y abierto por arriba a propósito. El multiplicador de daño de cada
    paso es exactamente `pasos / 2` (nulo, medio, uno, uno y medio, dos, y medio
    más por cada paso), así que el daño se calcula sin coma flotante; y un
    efecto puede pasar de `EXTREME`, cosa que un enumerado cerrado no sabría
    decir. Estos son los escalones con nombre; un efecto es cualquier entero
    desde cero.
    """

    NONE = 0
    LIMITED = 1
    STANDARD = 2
    GREAT = 3
    EXTREME = 4


@dataclass(frozen=True, slots=True)
class Challenge:
    """Una tirada ya montada: el contexto está sumado, falta tirar.

    No lleva atributo ni competencia: cómo se suma una reserva lo decide el
    sistema de la mesa, y el puerto solo ve el resultado de esa suma.
    """

    pool: int
    """Dados de quien actúa, con las penalizaciones ya restadas y SIN tope: lo
    que pasa del tope es excedente, y el tope lo pone el sistema."""

    effect: int = Effect.STANDARD
    """Pasos de efecto del contexto (preparación, enfoque), antes de tirar."""

    tier_gap: int = 0
    """Tier del rival menos el propio. Positivo: el rival está por encima."""

    opposing_pool: int | None = None
    """Dados de quien se opone. `None` es una tirada simple."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """Lo que salió, con los dados a la vista: un DM tiene que poder leerlo."""

    outcome: Outcome
    dice: tuple[int, ...]
    opposing_dice: tuple[int, ...]
    successes: int
    opposing_successes: int
    sixes: int
    overflow: int
    """Pasos de excedente que trajo la reserva, ya con su tope."""
    effect: int
    """Pasos finales si acertó; `Effect.NONE` si falló."""


@runtime_checkable
class Dice(Protocol):
    """De dónde salen los dados. El motor da uno derivado por clave; un test,
    uno con los dados escritos."""

    def roll(self, n: int) -> tuple[int, ...]:
        """`n` dados de seis caras, en el orden en que salen."""
        ...


@runtime_checkable
class RuleSystem(Protocol):
    """Resolución de acciones con oposición dramática (unidad 08, F4).

    Clave: la simulación NO usa esto. Los NPCs viviendo sus vidas resuelven
    por utilidad determinista, sin dados. Las reglas solo importan cuando hay
    un jugador empujando contra el mundo. Que la violencia entre NPCs pase
    también por aquí es un destino aplazado, que se mide con `--divergence`
    (D-155).

    La firma reservada en F0 era `resolve(actor, action, difficulty: float)`, y
    se equivocó como la de `MemoryStore`: no llevaba ni la reserva ni el efecto,
    y una dificultad en coma flotante no se compara con dados sin redondear en
    algún sitio que nadie ve (D-153).
    """

    def resolve(self, challenge: Challenge, dice: Dice) -> Resolution: ...


@runtime_checkable
class CognitionProvider(Protocol):
    """Puerta única al LLM. Entra en F2.

    Contrato que hace posible jugar con un 7B local igual que con Claude:
      - recibe un briefing YA precomputado por el motor, corto y cerrado;
      - devuelve una estructura pequeña y validable;
      - si falla o no valida, el motor usa su fallback determinista.

    El modelo nunca sostiene el estado del mundo. Cambiar de modelo debe
    cambiar la calidad de la prosa, jamás la coherencia del mundo.
    """

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        """Devuelve None si el modelo falló. None NO es un error: es la señal
        de que el motor debe seguir por su cuenta.

        `semilla` la deriva el motor por clave, como todo su azar: misma partida
        y mismo modelo, mismas palabras. Un proveedor que no sepa sembrar la
        ignora; lo que no puede hacer es inventarse una."""
        ...


@runtime_checkable
class MemoryStore(Protocol):
    """Memoria episódica por agente. Implementada en F1.12.

    La implementación es una lista en Python (`engine/memory.py`). La interfaz
    existe para que cambiar a sqlite-vec o Qdrant sea sustituir una clase, no un
    refactor.

    El parámetro `owner` es obligatorio a propósito: hace imposible consultar
    memoria sin decir de quién es, y con ello imposible el bug de omnisciencia
    (un NPC recordando lo que solo presenció otro).

    **La firma cambió al implementarla, y merece quedar escrito por qué.** Se
    declaró como `remember(owner, event_id, ...)` con `recall` devolviendo ids y
    un `cue: str`. Las tres piezas estaban mal, y ninguna se descubrió pensando:

    - Un **id no es un recuerdo**. El log tiene ventana, así que `log[seq]` de
      algo viejo levanta `EventoDesalojadoError`; y `persistence` no guarda la
      historia, así que al reanudar los punteros no apuntan a nada. El recuerdo
      lleva su propia copia de lo saliente.
    - Un **`cue` de texto libre** invita a vocabulario de ambientación dentro del
      motor —prohibido y verificado por AST— y a similitud vectorial, que rompe
      el determinismo y la legibilidad. La señal es estructural.
    - Por lo mismo, la **relevancia no es coseno**: es coincidencia contada sobre
      ids del propio motor, y por eso se puede explicar por qué salió un recuerdo
      y no otro.

    Un puerto declarado antes de tiempo acierta la costura y se equivoca en los
    tipos. Acertar la costura era lo que importaba: nada tuvo que reescribirse.
    """

    def remember(self, owner: AgentId, event: Event, importancia: float) -> Recuerdo | None: ...

    def recall(self, owner: AgentId, cue: Cue, limit: int) -> tuple[Recuerdo, ...]:
        """Devuelve recuerdos, ordenados por `relevancia * valor`, donde el valor
        es la importancia desdibujada por el tiempo. Los dos factores multiplican:
        lo que no viene a cuento no sale por muy grabado que esté."""
        ...
