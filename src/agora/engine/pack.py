"""Carga y validación del content pack.

Un pack inválido debe explotar AL CARGAR, con un mensaje que diga exactamente
qué está mal. La alternativa es descubrirlo tres horas después, con un NPC
comportándose raro y sin pista de por qué.

Analogía con C#: esto es el equivalente a validar un `appsettings.json` con
`IValidateOptions<T>` en el arranque, en vez de reventar en la primera petición
que toca una opción mal puesta.

--- CÓMO TRABAJAR ESTE ARCHIVO -------------------------------------------------
Cada `_check_*` devuelve una LISTA DE PROBLEMAS (vacía = todo bien) en vez de
lanzar excepción. Así el usuario ve todos los errores del pack de una vez, no
el primero y a repetir.

Están todos devolviendo `[]`, así que el pack carga sin validar nada. Ve
implementándolos de uno en uno; `tests/test_pack.py` tiene un test por cada
uno y te dice cuál falta. Corre:

    uv run pytest tests/test_pack.py -v
--------------------------------------------------------------------------------
"""

from __future__ import annotations

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
from agora.engine.topology import is_strongly_connected  # noqa: F401  (lo usas en el PASO 10)


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
    # `@cached_property` = `Lazy<T>` de C#: se calcula la primera vez que se
    # pide y se guarda. Aquí importa porque la deliberación (0.5) va a buscar
    # specs por id miles de veces por corrida.
    #
    # PASO 1: implementa los cinco. Son todos el mismo one-liner:
    #     return {x.id: x for x in self.xxx}
    # (equivale a `self.Xxx.ToDictionary(x => x.Id)`)
    # -------------------------------------------------------------------------

    @cached_property
    def need_by_id(self) -> dict[NeedId, NeedSpec]:
        raise NotImplementedError("PASO 1")

    @cached_property
    def trait_by_id(self) -> dict[TraitId, TraitSpec]:
        raise NotImplementedError("PASO 1")

    @cached_property
    def action_by_id(self) -> dict[ActionId, ActionSpec]:
        raise NotImplementedError("PASO 1")

    @cached_property
    def place_by_id(self) -> dict[PlaceId, PlaceSpec]:
        raise NotImplementedError("PASO 1")

    @cached_property
    def agent_by_id(self) -> dict[AgentId, AgentSpec]:
        raise NotImplementedError("PASO 1")

    # -------------------------------------------------------------------------
    # Validaciones. Cada una devuelve los problemas que encuentra.
    # -------------------------------------------------------------------------

    def _check_unique_ids(self) -> list[str]:
        """PASO 2: ningún id repetido dentro de su colección.

        Reporta CUÁL id está duplicado, no solo que hay uno. Un mensaje de
        error que no dice qué arreglar no sirve para nada.

        Pista: `collections.Counter` te da los repetidos en una línea.
        """
        return []

    def _check_global_id_collisions(self) -> list[str]:
        """PASO 3: acciones, lugares y agentes no pueden compartir id.

        Por qué: `TasteSpec.target` puede apuntar a cualquiera de los tres.
        `ActionId`, `PlaceId` y `AgentId` son tipos distintos para mypy, pero
        los tres son `str` en runtime — `NewType` no existe al ejecutar. Si una
        acción y un lugar se llaman igual, un gusto es ambiguo y nadie avisa.

        Esta es la clase de bug que solo previene una validación explícita.
        """
        return []

    def _check_need_refs(self) -> list[str]:
        """PASO 4: toda necesidad citada existe.

        Dónde se citan:
          - trait.need_weight_multipliers  (claves)
          - action.satisfies, action.effects  (claves)
          - agent.initial_needs  (claves)
        """
        return []

    def _check_trait_refs(self) -> list[str]:
        """PASO 5: todo rasgo que un agente declara existe en `traits`."""
        return []

    def _check_place_refs(self) -> list[str]:
        """PASO 6: todo lugar citado existe.

        Dónde: `place.neighbors` (destinos), `agent.home`, `agent.start_at`.
        """
        return []

    def _check_taste_refs(self) -> list[str]:
        """PASO 7: el objetivo de cada gusto existe como acción, lugar o agente."""
        return []

    def _check_actions_are_reachable(self) -> list[str]:
        """PASO 8: toda affordance requerida la ofrece algún lugar.

        Si `trabajar` exige la affordance `labor` y ningún lugar la ofrece, esa
        acción está muerta: nunca será válida en ningún sitio. El pack "funciona"
        y ese comportamiento simplemente no existe. Silencioso y caro.
        """
        return []

    def _check_fallback_action_exists(self) -> list[str]:
        """PASO 9: existe al menos una acción sin `requires_affordance`.

        Es la red de seguridad. Sin ella, un agente en un lugar cuyas
        affordances no cubren ninguna necesidad se queda sin opciones legales:
        deadlock.
        """
        return []

    def _check_world_is_navigable(self) -> list[str]:
        """PASO 10: el grafo de lugares es fuertemente conexo.

        Usa `is_strongly_connected(self.places)`, ya implementado en
        `topology.py`. Recuerda por qué la conexidad débil no basta: un lugar
        con entrada y sin salida es una trampa permanente.
        """
        return []

    # -------------------------------------------------------------------------
    # Orquestador. Ya escrito: es el patrón, no el trabajo.
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

    Gotcha de pydantic que conviene conocer: si un validador lanza `ValueError`,
    pydantic lo captura y lo re-lanza envuelto en `ValidationError`. El mensaje
    sobrevive, el tipo no. Por eso se traduce aquí a `PackError`, y el resto del
    programa puede capturar un tipo propio.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return ContentPack.model_validate(raw)
    except ValidationError as exc:
        raise PackError(f"no se pudo cargar {path}:\n{exc}") from exc
