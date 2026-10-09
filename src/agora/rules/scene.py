"""Quién pelea, con qué y cómo: la ficha de escena (unidad 09).

Una ficha de escena lleva sus números escritos a mano. Derivarlos del agente
(D-154) es del puente con el mundo, la unidad 12, y para entonces esta misma
ficha será lo que el puente rellene. Las armas y armaduras viajan dentro del
escenario porque son ambientación (D-153) y todavía no hay pack que las lea.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from agora.engine.ontology import Spec
from agora.engine.ports import Effect
from agora.rules.system import Ruleset


class ScenarioError(ValueError):
    """El escenario está mal formado o no casa con el sistema."""


class WeaponSpec(Spec):
    id: str
    label: str
    base: int = Field(ge=0)
    piercing: int = Field(default=0, ge=0)
    agile: bool = False
    """Permite atacar con el atributo ágil del sistema."""
    defensive: bool = False
    """Un dado más al defenderse mientras se empuña."""


class ArmorSpec(Spec):
    id: str
    label: str
    protection: int = Field(default=0, ge=0)
    resist_dice: int = Field(default=0, ge=0)
    """Dados de más al resistir el daño."""


class TargetChoice(StrEnum):
    WEAKEST = "mas_debil"
    STRONGEST = "mas_fuerte"
    HATED = "peor_le_cae"


class FinishOff(StrEnum):
    NEVER = "nunca"
    HATED = "si_le_odia"
    ALWAYS = "siempre"


class CombatStyle(Spec):
    """Cómo pelea alguien (D-158). Cinco perillas y nada más: en la unidad 12
    saldrán de sus rasgos, su temperamento y lo que siente por cada cual, así
    que cada una tiene que poder explicarse con una frase sobre quién es."""

    aggression: int = Field(default=50, ge=0, le=100)
    """Atacar frente a protegerse. Alta: se fuerza y no recula. Baja: se
    defiende cuando va mal, recupera el aliento y socorre a los suyos."""
    flee_below: int = Field(default=25, ge=0, le=100)
    """Por debajo de este porcentaje de Vitalidad se va: huye, o se rinde si ya
    no le quedan fuerzas. 0 es no rendirse nunca."""
    target: TargetChoice = TargetChoice.WEAKEST
    finish_off: FinishOff = FinishOff.NEVER
    """Qué hace con quien cae: dejarlo, rematarlo si lo odia o rematarlo."""
    whim: int = Field(default=0, ge=0, le=100)
    """Probabilidad, en porcentaje, de hacer cualquier otra cosa legal: el azar
    del temperamento. Sin él, dos encuentros iguales se pelean igual."""


class CombatantSpec(Spec):
    id: str
    label: str
    tier: int = Field(ge=1)
    attributes: dict[str, int]
    """Valores, no grados: el grado lo calcula el sistema."""
    skills: dict[str, int] = Field(default_factory=dict)
    specialties: tuple[str, ...] = ()
    """Competencias con especialidad: un dado más cuando se tiran (§6.2)."""
    attack_skill: str
    weapon: str
    armor: str | None = None
    vitality: int = Field(ge=1)
    fatigue: int = Field(ge=1)
    """Capacidad de fatiga, no la fatiga de partida, que es 0."""
    stress: int = Field(ge=1)
    """Capacidad de estrés."""
    impetus: int = Field(ge=0)
    """Máximo de Ímpetu. Se cuenta y no se gasta hasta que haya técnicas."""
    style: CombatStyle = Field(default_factory=CombatStyle)
    regard: dict[str, int] = Field(default_factory=dict)
    """Lo que siente por los demás de la escena, de -100 a 100. Lo leen
    `peor_le_cae` y `si_le_odia`; sin entrada, 0."""


class SideSpec(Spec):
    id: str
    label: str
    combatants: tuple[CombatantSpec, ...] = Field(min_length=1)
    effect: int = Field(default=Effect.STANDARD, ge=0)
    """Pasos de efecto de partida de sus ataques: la preparación (§21.3)."""


class ScenarioSpec(Spec):
    id: str
    label: str
    weapons: tuple[WeaponSpec, ...]
    armors: tuple[ArmorSpec, ...] = ()
    sides: tuple[SideSpec, SideSpec]


def check_scenario(scenario: ScenarioSpec, ruleset: Ruleset) -> list[str]:
    """Lo que el escenario promete y el sistema no sabe cumplir. Va aparte del
    validador del escenario porque depende de con qué sistema se juegue."""
    atributos = frozenset(a.id for a in ruleset.attributes)
    competencias = frozenset(s.id for s in ruleset.skills)
    armas = frozenset(w.id for w in scenario.weapons)
    armaduras = frozenset(a.id for a in scenario.armors)
    todos = [c for side in scenario.sides for c in side.combatants]
    ids = frozenset(c.id for c in todos)
    techos = {t.tier: t.attribute_cap for t in ruleset.tiers}
    problems = [
        f"id repetido {i!r}" for i, n in sorted(Counter(c.id for c in todos).items()) if n > 1
    ]
    if scenario.sides[0].id == scenario.sides[1].id:
        problems.append(f"los dos bandos se llaman {scenario.sides[0].id!r}")
    if ruleset.combat is None:
        problems.append(f"el sistema {ruleset.id!r} no tiene sección combat")
    for c in todos:
        problems += [f"{c.id}: atributo desconocido {a!r}" for a in sorted(c.attributes)
                     if a not in atributos]
        problems += [f"{c.id}: atributo {a!r} sin valor" for a in sorted(atributos)
                     if a not in c.attributes]
        problems += [f"{c.id}: competencia desconocida {s!r}"
                     for s in sorted({*c.skills, *c.specialties, c.attack_skill})
                     if s not in competencias]
        problems += [f"{c.id}: nivel {n} de {s!r} pasa de {ruleset.skill_max_level}"
                     for s, n in sorted(c.skills.items()) if n > ruleset.skill_max_level]
        problems += [f"{c.id}: regard hacia {o!r}, que no está en la escena"
                     for o in sorted(c.regard) if o not in ids]
        if c.weapon not in armas:
            problems.append(f"{c.id}: arma desconocida {c.weapon!r}")
        if c.armor is not None and c.armor not in armaduras:
            problems.append(f"{c.id}: armadura desconocida {c.armor!r}")
        if c.tier not in techos:
            problems.append(f"{c.id}: tier {c.tier} que el sistema no tiene")
        else:
            problems += [f"{c.id}: {a} = {v} pasa del techo del tier {c.tier} ({techos[c.tier]})"
                         for a, v in sorted(c.attributes.items()) if v > techos[c.tier]]
    return problems


def load_scenario(path: Path, ruleset: Ruleset) -> ScenarioSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        scenario = ScenarioSpec.model_validate(raw)
    except ValidationError as exc:
        raise ScenarioError(f"no se pudo cargar {path}:\n{exc}") from exc
    problems = check_scenario(scenario, ruleset)
    if problems:
        raise ScenarioError(
            f"escenario {scenario.id!r} inválido con el sistema {ruleset.id!r}:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return scenario
