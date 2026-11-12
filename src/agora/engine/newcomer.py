"""El forastero: la ficha con la que un jugador crea a su propio personaje
(unidad 10), y la creación guiada por las reglas del mundo (unidad 21a).

La ficha dice lo que el jugador quiere decir; lo demás lo pone el pack
(`ContentPack.newcomer`) y, por debajo, el `initial` de cada necesidad. El
resultado es un `AgentSpec` como el de cualquier otro habitante, y se valida
con la misma puerta que valida a los habitantes del pack: si un agente así no
podría estar escrito en el pack, tampoco puede llegar.

Crear desde las reglas del mundo (`ContentPack.creation`) produce una
`NewcomerSheet` normal: todo lo de después no sabe de dónde salió.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from agora.engine.ontology import (
    AgentId,
    AgentSpec,
    CreationSpec,
    NeedId,
    NewcomerSpec,
    PlaceId,
    Spec,
    TasteSpec,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.rng import RngSource


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


# --- Crear el personaje desde las reglas del mundo (unidad 21a, D-175) -----------------

EPS = 1e-9
"""Margen para comparar floats que vienen de sumas y de pasos: sin él, 0.1 + 0.05 * 7
no cabe en su propio rango."""

STEP_TOLERANCE = 1e-6
"""Cuánto puede separarse un valor de su paso antes de contar como fuera de paso."""


class CreationError(ValueError):
    """La elección no cumple las reglas que el mundo declara para crear personaje."""


class CreationChoice(Spec):
    """Lo que el jugador elige al crear. No dice nada que el mundo no permita: se
    valida contra `ContentPack.creation`, y si algo no cabe, `build_sheet` dice qué.

    `mode` son los tres modos de la unidad: `free` (libre, dentro de los rangos),
    `points` (con un presupuesto por dificultad) y `roll` (los dados reparten los
    potenciales, una sola vez)."""

    name: str
    mode: Literal["free", "points", "roll"]
    difficulty: str | None = None
    groups: tuple[TraitId, ...] = ()
    """Un rasgo por grupo que se elige. El grupo se deduce del rasgo."""
    potentials: dict[TraitId, float] = Field(default_factory=dict)
    """En libre y con puntos: el valor de cada potencial. Lo que no se diga vale su `min`."""
    character: dict[TraitId, float] = Field(default_factory=dict)


def parse_choice(raw: Mapping[str, object]) -> CreationChoice:
    """La elección tal como llega de fuera, o `CreationError` con qué forma le falta."""
    try:
        return CreationChoice.model_validate(raw)
    except ValidationError as exc:
        raise CreationError(f"la elección no tiene la forma correcta:\n{exc}") from exc


def build_sheet(
    pack: ContentPack, choice: CreationChoice, seed: int
) -> tuple[NewcomerSheet, dict[TraitId, float]]:
    """La ficha del personaje creado, y los raros que le tocaron. Los raros no los
    elige nadie: se le cuentan al jugador al empezar.

    Todo sale de (elección, semilla): la misma elección y la misma semilla dan la
    misma ficha, y así `--jugar-ficha` reproduce al personaje que se creó."""
    spec = pack.creation
    if spec is None:
        raise CreationError(f"el mundo {pack.id!r} no deja crear personaje")
    name = choice.name.strip()
    if not name:
        raise CreationError("el personaje necesita un nombre")
    if choice.mode != "points" and choice.difficulty is not None:
        raise CreationError("la dificultad solo cuenta cuando se reparten puntos")
    traits: dict[TraitId, float] = {}
    traits.update(_group_traits(spec, choice))
    traits.update(_potential_traits(pack, spec, choice, name, seed))
    traits.update(_character_traits(spec, choice))
    rares = _rare_traits(spec, name, seed)
    traits.update(rares)
    sheet = NewcomerSheet(
        id=_free_id(pack, name), label=name, traits=dict(sorted(traits.items()))
    )
    return sheet, rares


def _group_traits(spec: CreationSpec, choice: CreationChoice) -> dict[TraitId, float]:
    """Un rasgo por grupo obligatorio, cero o uno por grupo opcional. El rasgo elegido
    entra a 1.0: es lo que dice el grupo, y no tiene coste."""
    for trait in choice.groups:
        if not any(trait in group.traits for group in spec.groups):
            raise CreationError(f"{trait!r} no es una elección de este mundo")
    chosen: dict[TraitId, float] = {}
    for group in spec.groups:
        inside = [trait for trait in choice.groups if trait in group.traits]
        if len(inside) > 1:
            raise CreationError(
                f"en «{group.label}» se elige uno, y elegiste {len(inside)}: {', '.join(inside)}"
            )
        if not inside and group.required:
            raise CreationError(f"falta elegir «{group.label}»")
        for trait in inside:
            chosen[trait] = 1.0
    return chosen


def _potential_traits(
    pack: ContentPack, spec: CreationSpec, choice: CreationChoice, name: str, seed: int
) -> dict[TraitId, float]:
    potentials = spec.potentials
    if potentials is None:
        if choice.mode == "points" or choice.potentials:
            raise CreationError("el mundo no tiene potenciales que elegir")
        return {}
    if choice.mode == "roll":
        if choice.potentials:
            raise CreationError("en tirada los potenciales los reparten los dados, no tú")
        return roll_potentials(pack, name, seed)
    for trait in choice.potentials:
        if trait not in potentials.traits:
            raise CreationError(f"{trait!r} no es un potencial de este mundo")
    values = {trait: choice.potentials.get(trait, potentials.min) for trait in potentials.traits}
    for trait, value in values.items():
        in_range = potentials.min - EPS <= value <= potentials.max + EPS
        steps = round((value - potentials.min) / potentials.step)
        on_step = abs(potentials.min + steps * potentials.step - value) <= STEP_TOLERANCE
        if not (in_range and on_step):
            raise CreationError(
                f"{trait}: {value} no vale; va de {potentials.min} a {potentials.max} "
                f"en pasos de {potentials.step}"
            )
    if choice.mode == "points":
        budget = _budget(spec, choice)
        spent = sum(values.values())
        if spent > budget + EPS:
            raise CreationError(
                f"los potenciales cuestan {spent:.2f} y el presupuesto de "
                f"«{choice.difficulty}» es {budget:.2f}"
            )
    return values


def _budget(spec: CreationSpec, choice: CreationChoice) -> float:
    if not spec.budgets:
        raise CreationError("este mundo no deja crear con puntos")
    if choice.difficulty is None:
        raise CreationError(
            f"con puntos hay que elegir dificultad: {', '.join(sorted(spec.budgets))}"
        )
    if choice.difficulty not in spec.budgets:
        raise CreationError(f"no hay dificultad {choice.difficulty!r}")
    return spec.budgets[choice.difficulty]


def roll_potentials(pack: ContentPack, name: str, seed: int) -> dict[TraitId, float]:
    """Los potenciales de una tirada, sin elegir nada más. La usa la página para
    enseñar los dados antes de que el jugador elija grupo, y `build_sheet` para la
    ficha: la misma tirada en los dos sitios, por una sola puerta.

    Cada potencial sale de los valores reales de ese rasgo en los habitantes del
    pack: sale gente parecida a la del mundo, no números uniformes. Un solo flujo
    para todos, en orden de declaración: el orden importa y está fijado por el pack."""
    spec = pack.creation
    if spec is None or spec.potentials is None:
        raise CreationError("el mundo no tiene potenciales que tirar")
    potentials = spec.potentials
    stream = RngSource(seed).stream("creacion", name, seed)
    values: dict[TraitId, float] = {}
    for trait in potentials.traits:
        observed = sorted(agent.traits[trait] for agent in pack.agents if trait in agent.traits)
        if not observed:
            values[trait] = potentials.min
            continue
        drawn = stream.choice(observed)
        steps = round((drawn - potentials.min) / potentials.step)
        snapped = potentials.min + steps * potentials.step
        values[trait] = round(min(max(snapped, potentials.min), potentials.max), 4)
    return values


def _character_traits(spec: CreationSpec, choice: CreationChoice) -> dict[TraitId, float]:
    values: dict[TraitId, float] = {}
    for trait, value in sorted(choice.character.items()):
        if trait not in spec.character:
            raise CreationError(
                f"{trait!r} no se elige al crear: solo se eligen los grupos, los potenciales "
                "y el carácter que el mundo declara; los raros los reparte el azar"
            )
        low, high = spec.character[trait]
        if not low <= value <= high:
            raise CreationError(f"{trait}: {value} queda fuera de [{low}, {high}]")
        values[trait] = value
    return values


def _rare_traits(spec: CreationSpec, name: str, seed: int) -> dict[TraitId, float]:
    """Cada raro con su propio sorteo, en orden de id: el resultado de uno no depende
    de si otro salió. Ningún gesto del jugador lo cambia."""
    granted: dict[TraitId, float] = {}
    for trait in sorted(spec.rare):
        rare = spec.rare[trait]
        stream = RngSource(seed).stream("creacion-raro", name, trait, seed)
        if stream.random() < rare.chance:
            granted[trait] = round(stream.uniform(rare.min, rare.max), 4)
    return granted


def _free_id(pack: ContentPack, name: str) -> AgentId:
    """El id sale del nombre, sin tildes ni signos. Si ya lo usa un habitante, se le
    añade un sufijo: el mismo nombre da siempre el mismo id."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    root = "_".join(re.findall(r"[a-z0-9]+", ascii_name.lower())) or "personaje"
    taken = {str(agent.id) for agent in pack.agents}
    candidate, suffix = root, 2
    while candidate in taken:
        candidate = f"{root}_{suffix}"
        suffix += 1
    return AgentId(candidate)
