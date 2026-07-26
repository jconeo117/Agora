"""Carga y validación del content pack.

Un pack inválido debe explotar AL CARGAR, con un mensaje que diga exactamente
qué está mal. La alternativa es descubrirlo tres horas después, con un NPC
comportándose raro y sin pista de por qué.

Equivalente en C#: validar `appsettings.json` con `IValidateOptions<T>` en el
arranque, en vez de reventar en la primera petición que toca una opción mal
puesta.

Cada `_check_*` devuelve una LISTA DE PROBLEMAS (vacía = todo bien) en vez de
lanzar. Así el autor del pack ve todos los errores de una pasada, no el primero
y a repetir. Editar un mundo es un ciclo de prueba y error: un validador que
solo reporta el primer fallo convierte diez erratas en diez cargas.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from functools import cached_property
from pathlib import Path

import yaml
from pydantic import ValidationError, model_validator

from agora.engine.ontology import (
    ActionId,
    ActionSpec,
    AgentId,
    AgentSpec,
    NeedId,
    NeedSpec,
    PlaceId,
    PlaceSpec,
    Spec,
    TraitId,
    TraitSpec,
)
from agora.engine.topology import is_strongly_connected


class PackError(ValueError):
    """El pack está mal formado. El mensaje lista todos los problemas."""


class ContentPack(Spec):
    """Un mundo entero, en datos. El motor no conoce ningún otro."""

    id: str
    label: str
    needs: tuple[NeedSpec, ...]
    traits: tuple[TraitSpec, ...] = ()
    actions: tuple[ActionSpec, ...]
    places: tuple[PlaceSpec, ...]
    agents: tuple[AgentSpec, ...]

    # -------------------------------------------------------------------------
    # Índices.
    #
    # `@cached_property` = `Lazy<T>`: se calcula la primera vez que se pide y se
    # guarda en la instancia. La deliberación (0.5) busca specs por id miles de
    # veces por corrida; recorrer una tupla cada vez sería el cuello de botella.
    #
    # Ojo: estos índices NO se usan durante la validación. Un dict colapsa las
    # claves repetidas, así que si el pack tuviera ids duplicados el índice los
    # ocultaría justo cuando queremos detectarlos. Las validaciones trabajan
    # siempre sobre las tuplas crudas.
    # -------------------------------------------------------------------------

    @cached_property
    def need_by_id(self) -> dict[NeedId, NeedSpec]:
        return {need.id: need for need in self.needs}

    @cached_property
    def trait_by_id(self) -> dict[TraitId, TraitSpec]:
        return {trait.id: trait for trait in self.traits}

    @cached_property
    def action_by_id(self) -> dict[ActionId, ActionSpec]:
        return {action.id: action for action in self.actions}

    @cached_property
    def place_by_id(self) -> dict[PlaceId, PlaceSpec]:
        return {place.id: place for place in self.places}

    @cached_property
    def agent_by_id(self) -> dict[AgentId, AgentSpec]:
        return {agent.id: agent for agent in self.agents}

    @cached_property
    def offered_affordances(self) -> frozenset[str]:
        """Todo lo que se puede hacer en algún sitio del mundo."""
        return frozenset(aff for place in self.places for aff in place.affordances)

    @cached_property
    def fallback_actions(self) -> tuple[ActionSpec, ...]:
        """Acciones válidas en cualquier lugar. La red de seguridad del motor."""
        return tuple(a for a in self.actions if a.requires_affordance is None)

    # -------------------------------------------------------------------------
    # Validaciones
    # -------------------------------------------------------------------------

    @staticmethod
    def _duplicates(kind: str, ids: Iterable[str]) -> list[str]:
        counts = Counter(ids)
        return [
            f"{kind}: id duplicado {dup!r} (aparece {n} veces)"
            for dup, n in counts.items()
            if n > 1
        ]

    @staticmethod
    def _unknown_keys(
        context: str, kind: str, keys: Iterable[str], known: frozenset[str]
    ) -> list[str]:
        """Reporta claves que no existen en `known`.

        `sorted` no es cosmético: sin él el orden de los mensajes dependería del
        orden de iteración de un set, que varía entre ejecuciones. Un pack roto
        debe producir SIEMPRE el mismo texto de error, o comparar dos corridas
        se vuelve imposible.
        """
        return [
            f"{context}: {kind} desconocida/o {key!r}" for key in sorted(set(keys) - known)
        ]

    def _check_unique_ids(self) -> list[str]:
        return [
            *self._duplicates("necesidades", (n.id for n in self.needs)),
            *self._duplicates("rasgos", (t.id for t in self.traits)),
            *self._duplicates("acciones", (a.id for a in self.actions)),
            *self._duplicates("lugares", (p.id for p in self.places)),
            *self._duplicates("agentes", (a.id for a in self.agents)),
        ]

    def _check_global_id_collisions(self) -> list[str]:
        """Acciones, lugares y agentes no pueden compartir id.

        `TasteSpec.target` puede apuntar a cualquiera de los tres. Para mypy son
        tipos distintos, pero `NewType` no existe en runtime: los tres son `str`.
        Si una acción y un lugar se llaman igual, un gusto es ambiguo y nadie
        avisa. De ahí el `str(...)` explícito: aquí comparamos deliberadamente
        al nivel en el que la colisión ocurre de verdad.
        """
        spaces: tuple[tuple[str, set[str]], ...] = (
            ("acción", {str(a.id) for a in self.actions}),
            ("lugar", {str(p.id) for p in self.places}),
            ("agente", {str(a.id) for a in self.agents}),
        )
        problems: list[str] = []
        for index, (left_name, left) in enumerate(spaces):
            for right_name, right in spaces[index + 1 :]:
                for clash in sorted(left & right):
                    problems.append(
                        f"id {clash!r} usado a la vez por un/a {left_name} y un/a "
                        f"{right_name}: los gustos no podrían distinguirlos"
                    )
        return problems

    def _check_need_refs(self) -> list[str]:
        known = frozenset(str(n.id) for n in self.needs)
        problems: list[str] = []

        for trait in self.traits:
            problems += self._unknown_keys(
                f"rasgo {trait.id!r}", "necesidad", trait.need_weight_multipliers, known
            )

        for action in self.actions:
            for field, mapping in (
                ("satisfies", action.satisfies),
                ("effects", action.effects),
            ):
                problems += self._unknown_keys(
                    f"acción {action.id!r}.{field}", "necesidad", mapping, known
                )

        for agent in self.agents:
            problems += self._unknown_keys(
                f"agente {agent.id!r}.initial_needs", "necesidad", agent.initial_needs, known
            )

        return problems

    def _check_trait_refs(self) -> list[str]:
        known = frozenset(str(t.id) for t in self.traits)
        return [
            problem
            for agent in self.agents
            for problem in self._unknown_keys(
                f"agente {agent.id!r}", "rasgo", agent.traits, known
            )
        ]

    def _check_place_refs(self) -> list[str]:
        known = frozenset(str(p.id) for p in self.places)
        problems: list[str] = []

        for place in self.places:
            problems += self._unknown_keys(
                f"lugar {place.id!r}.neighbors", "lugar", place.neighbors, known
            )

        for agent in self.agents:
            for field, value in (("home", agent.home), ("start_at", agent.start_at)):
                if str(value) not in known:
                    problems.append(f"agente {agent.id!r}.{field}: lugar desconocido {value!r}")

        return problems

    def _check_taste_refs(self) -> list[str]:
        known = (
            frozenset(str(a.id) for a in self.actions)
            | frozenset(str(p.id) for p in self.places)
            | frozenset(str(a.id) for a in self.agents)
        )
        return [
            f"agente {agent.id!r}: gusto hacia {taste.target!r}, que no es "
            f"ninguna acción, lugar ni agente"
            for agent in self.agents
            for taste in agent.tastes
            if str(taste.target) not in known
        ]

    def _check_actions_are_reachable(self) -> list[str]:
        """Toda affordance requerida la ofrece algún lugar.

        Si `trabajar` exige `labor` y ningún lugar la ofrece, la acción está
        muerta: nunca será válida en ningún sitio. El pack "funciona" y ese
        comportamiento simplemente no existe. Es el fallo más caro de detectar
        a ojo, porque no produce ningún síntoma: produce una ausencia.
        """
        offered = self.offered_affordances
        return [
            f"acción {action.id!r}: requiere la affordance "
            f"{action.requires_affordance!r}, que no ofrece ningún lugar "
            f"(acción huerfana, jamás ejecutable)"
            for action in self.actions
            if action.requires_affordance is not None
            and action.requires_affordance not in offered
        ]

    def _check_fallback_action_exists(self) -> list[str]:
        """Debe existir al menos una acción sin `requires_affordance`.

        Es la red de seguridad. Sin ella, un agente en un lugar cuyas
        affordances no cubren ninguna de sus necesidades se queda sin opciones
        legales y el tick loop no tiene nada que elegir: deadlock.
        """
        if self.fallback_actions:
            return []
        return [
            "ninguna acción prescinde de affordance: un agente puede quedarse "
            "sin opciones válidas y bloquear la simulación"
        ]

    def _check_world_is_navigable(self) -> list[str]:
        """El grafo debe ser fuertemente conexo.

        Conexidad débil no basta: un lugar con entrada y sin salida es una
        trampa permanente para cualquier agente que llegue.
        """
        if is_strongly_connected(self.places):
            return []
        return [
            "el grafo de lugares no es fuertemente conexo: existe al menos un "
            "lugar desde el que no se puede volver, y un agente que entre "
            "quedará varado el resto de la partida"
        ]

    # -------------------------------------------------------------------------
    # Orquestador
    # -------------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate(self) -> ContentPack:
        problems = [
            *self._check_unique_ids(),
            *self._check_global_id_collisions(),
            *self._check_need_refs(),
            *self._check_trait_refs(),
            *self._check_place_refs(),
            *self._check_taste_refs(),
            *self._check_actions_are_reachable(),
            *self._check_fallback_action_exists(),
            *self._check_world_is_navigable(),
        ]
        if problems:
            raise ValueError(
                f"pack {self.id!r} inválido:\n" + "\n".join(f"  - {p}" for p in problems)
            )
        return self


def load_pack(path: Path) -> ContentPack:
    """Lee un pack desde disco.

    `safe_load`, nunca `load`: `yaml.load` a secas puede instanciar objetos
    Python arbitrarios desde el fichero. Con packs propios da igual; el día que
    cargues el pack de otra persona, no.

    Gotcha de pydantic: si un validador lanza `ValueError`, pydantic lo captura
    y lo re-lanza envuelto en `ValidationError`. El mensaje sobrevive, el tipo
    no. Por eso se traduce aquí a `PackError`: el resto del programa captura un
    tipo propio y no una excepción de la librería.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return ContentPack.model_validate(raw)
    except ValidationError as exc:
        raise PackError(f"no se pudo cargar {path}:\n{exc}") from exc


def describe_pack(pack: ContentPack) -> Mapping[str, int]:
    """Resumen numérico. Útil para la primera línea del log de una corrida."""
    return {
        "needs": len(pack.needs),
        "traits": len(pack.traits),
        "actions": len(pack.actions),
        "places": len(pack.places),
        "agents": len(pack.agents),
    }
