"""Puertos: las fronteras del motor con el mundo exterior.

Ninguno se implementa en F0. Existen ahora para que el motor se construya
*contra ellos* desde el primer día. Un puerto añadido tarde obliga a reescribir
todo lo que debió pasar por él.

`Protocol` es el equivalente Python de una `interface` de C#: mypy verifica que
una clase la cumple sin que esta herede de nada.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from agora.engine.ontology import ActionId, AgentId


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
    """Memoria episódica por agente. Entra en F1.

    En F1 la implementación es una lista en Python. La interfaz existe para
    que cambiar a sqlite-vec o Qdrant sea sustituir una clase, no un refactor.

    El parámetro `owner` es obligatorio a propósito: hace imposible consultar
    memoria sin decir de quién es, y con ello imposible el bug de omnisciencia
    (un NPC recordando lo que solo presenció otro).
    """

    def remember(self, owner: AgentId, event_id: int, importance: float) -> None: ...

    def recall(self, owner: AgentId, cue: str, limit: int) -> list[int]:
        """Devuelve ids de evento, ordenados por
        `recencia * importancia * relevancia`. La similitud vectorial es solo
        el tercer factor: un vector store crudo no basta."""
        ...
