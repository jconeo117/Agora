"""Puertos: las fronteras del motor con el mundo exterior.

Ninguno se implementa en F0. Existen ahora para que el motor se construya
*contra ellos* desde el primer día. Un puerto añadido tarde obliga a reescribir
todo lo que debió pasar por él.

`Protocol` es el equivalente Python de una `interface` de C#: mypy verifica que
una clase la cumple sin que esta herede de nada.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from agora.engine.ontology import ActionId, AgentId

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
    """

    SUCCESS = "success"
    SUCCESS_AT_COST = "success_at_cost"
    FAILURE = "failure"
    GRAVE_FAILURE = "grave_failure"


@runtime_checkable
class RuleSystem(Protocol):
    """Resolución de acciones con oposición dramática. Entra en F4.

    Clave: la simulación NO usa esto. Los NPCs viviendo sus vidas resuelven
    por utilidad determinista, sin dados. Las reglas solo importan cuando hay
    un jugador empujando contra el mundo.
    """

    def resolve(self, actor: AgentId, action: ActionId, difficulty: float) -> Outcome: ...


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

    def think(self, briefing: str, schema: type) -> object | None:
        """Devuelve None si el modelo falló. None NO es un error: es la señal
        de que el motor debe seguir por su cuenta."""
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
