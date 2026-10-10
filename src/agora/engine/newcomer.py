"""El forastero: la ficha con la que un jugador crea a su propio personaje
(unidad 10).

La ficha dice lo que el jugador quiere decir; lo demás lo pone el pack
(`ContentPack.newcomer`) y, por debajo, el `initial` de cada necesidad. El
resultado es un `AgentSpec` como el de cualquier otro habitante, y se valida
con la misma puerta que valida a los habitantes del pack: si un agente así no
podría estar escrito en el pack, tampoco puede llegar.
"""

from __future__ import annotations

from collections.abc import Collection
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from agora.engine.ontology import (
    AgentId,
    AgentSpec,
    NeedId,
    NewcomerSpec,
    PlaceId,
    Spec,
    TasteSpec,
    TraitId,
)
from agora.engine.pack import ContentPack


class NewcomerError(ValueError):
    """La ficha no describe a alguien que pueda vivir en este mundo."""


class NewcomerSheet(Spec):
    """Lo que el jugador escribe. Todo es opcional salvo quién es: lo que falte
    lo completa el pack. No lleva relaciones, vínculos ni metas a propósito:
    quien llega de fuera no conoce a nadie, y querer algo lo aprende viviendo."""

    id: AgentId
    label: str
    home: PlaceId | None = None
    start_at: PlaceId | None = None
    traits: dict[TraitId, float] = Field(default_factory=dict)
    tastes: tuple[TasteSpec, ...] = ()
    initial_rank: dict[NeedId, int] = Field(default_factory=dict)
    initial_needs: dict[NeedId, float] = Field(default_factory=dict)
    edad_inicial: int | None = Field(default=None, ge=0)


def newcomer_spec(pack: ContentPack, sheet: NewcomerSheet, taken: Collection[AgentId]) -> AgentSpec:
    """La ficha gana al pack campo a campo; en los diccionarios, clave a clave.
    `taken` es el censo de la partida, que incluye a los nacidos en marcha y a
    los muertos: un id no se reutiliza nunca, o un recuerdo sobre el muerto
    pasaría a ser sobre el recién llegado."""
    base = pack.newcomer if pack.newcomer is not None else NewcomerSpec()
    if sheet.id in taken:
        raise NewcomerError(f"{sheet.id!r} ya existe en esta partida")
    home = sheet.home if sheet.home is not None else base.home
    if home is None:
        raise NewcomerError("ni la ficha ni el pack (`newcomer.home`) dicen dónde vive")
    start = sheet.start_at or base.start_at or home
    spec = AgentSpec(
        id=sheet.id,
        label=sheet.label,
        home=home,
        start_at=start,
        traits={**base.traits, **sheet.traits},
        tastes=sheet.tastes,
        initial_rank=dict(sheet.initial_rank),
        initial_needs={**base.initial_needs, **sheet.initial_needs},
        edad_inicial=sheet.edad_inicial if sheet.edad_inicial is not None else base.edad_inicial,
    )
    try:
        ContentPack.model_validate({**pack.model_dump(), "agents": [*pack.agents, spec]})
    except ValidationError as exc:
        raise NewcomerError(f"{sheet.id!r} no cabe en el pack {pack.id!r}:\n{exc}") from exc
    return spec


def load_sheet(path: Path) -> NewcomerSheet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return NewcomerSheet.model_validate(raw)
    except ValidationError as exc:
        raise NewcomerError(f"no se pudo cargar {path}:\n{exc}") from exc
