"""El sistema de la mesa, en datos (unidad 08).

Es a `rules/<sistema>/rules.yaml` lo que `ContentPack` es a un pack: un sistema
malformado no arranca. Lo que el borrador marca «a calibrar» vive aquí y no en
el código, porque la calibración cambia con la mesa y no con el motor.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path

import yaml
from pydantic import Field, ValidationError, model_validator

from agora.engine.ontology import Spec


class RulesetError(ValueError):
    """El sistema está mal formado. El mensaje lista todos los problemas."""


class AttributeSpec(Spec):
    id: str
    label: str
    minimum: int = Field(default=1, ge=0)
    """El valor más bajo posible. En el borrador 1 todos parten de 1 salvo uno,
    que puede valer 0 y entonces cierra todo lo que se tire con él."""


class GradeSpec(Spec):
    grade: int = Field(ge=1)
    min_value: int = Field(ge=1)
    """Desde qué valor de atributo se tiene este grado."""


class TierSpec(Spec):
    tier: int = Field(ge=1)
    label: str
    min_level: int = Field(ge=1)
    max_level: int = Field(ge=1)
    attribute_cap: int = Field(ge=1)
    """Hasta dónde puede llegar un atributo en este tier."""


class SkillSpec(Spec):
    id: str
    label: str
    attribute: str
    """El atributo con el que se tira por defecto."""
    approaches: tuple[str, ...] = ()
    """Los atributos con los que la situación puede permitir tirarla."""


class PoolSpec(Spec):
    """Lo que el borrador marca «a calibrar» de la reserva (§25)."""

    cap: int = Field(default=6, ge=1)
    overflow_cap: int = Field(default=2, ge=0)
    resist_stress: int = Field(default=3, ge=0)
    """Resistir cuesta esto menos los éxitos, en estrés, sin bajar de 0."""


class VitalitySpec(Spec):
    """Umbrales de Vitalidad en porcentaje ENTERO del máximo (§10.5): la
    comparación se hace multiplicando, y así ninguna frontera depende de cómo
    redondee una división."""

    wounded_below: int = Field(default=50, gt=0, lt=100)
    grave_below: int = Field(default=25, gt=0, lt=100)


class Ruleset(Spec):
    """Un sistema de rol entero, en datos. Las reglas no conocen ningún otro."""

    id: str
    label: str
    attributes: tuple[AttributeSpec, ...]
    grades: tuple[GradeSpec, ...]
    tiers: tuple[TierSpec, ...]
    skills: tuple[SkillSpec, ...]
    skill_max_level: int = Field(default=4, ge=1)
    pool: PoolSpec = Field(default_factory=PoolSpec)
    vitality: VitalitySpec = Field(default_factory=VitalitySpec)

    def grade(self, value: int) -> int:
        """El grado es lo único del atributo que entra en una tirada; el valor
        alimenta los recursos. Por debajo del primer grado, 0: un atributo a 0
        no aporta dados."""
        return max((g.grade for g in self.grades if g.min_value <= value), default=0)

    @model_validator(mode="after")
    def _validate(self) -> Ruleset:
        problems = [
            *_duplicates("attributes", (a.id for a in self.attributes)),
            *_duplicates("skills", (s.id for s in self.skills)),
            *self._check_grades(),
            *self._check_tiers(),
            *self._check_skills(),
        ]
        if self.vitality.grave_below >= self.vitality.wounded_below:
            problems.append(
                f"vitality: grave_below ({self.vitality.grave_below}) tiene que quedar "
                f"por debajo de wounded_below ({self.vitality.wounded_below})"
            )
        if problems:
            raise ValueError(
                f"sistema {self.id!r} inválido:\n" + "\n".join(f"  - {p}" for p in problems)
            )
        return self

    def _check_grades(self) -> list[str]:
        """Un grado que no crece con el valor haría que entrenar empeorase."""
        problems = []
        if [g.grade for g in self.grades] != list(range(1, len(self.grades) + 1)):
            problems.append("grades: los grados van de uno en uno, desde 1 y en orden")
        problems += [
            f"grades: el min_value del grado {b.grade} no supera al del {a.grade}"
            for a, b in pairwise(self.grades)
            if b.min_value <= a.min_value
        ]
        return problems

    def _check_tiers(self) -> list[str]:
        """Los tiers parten los niveles sin huecos ni solapes, y uno más alto
        nunca baja el techo: subir de tier no puede quitar nada."""
        problems = []
        if [t.tier for t in self.tiers] != list(range(1, len(self.tiers) + 1)):
            problems.append("tiers: los tiers van de uno en uno, desde 1 y en orden")
        problems += [
            f"tiers: el tier {t.tier} acaba en el nivel {t.max_level}, antes del {t.min_level}"
            for t in self.tiers
            if t.max_level < t.min_level
        ]
        problems += [
            f"tiers: el tier {b.tier} no empieza justo después del {a.tier}"
            for a, b in pairwise(self.tiers)
            if b.min_level != a.max_level + 1
        ]
        problems += [
            f"tiers: el techo del tier {b.tier} baja respecto al del {a.tier}"
            for a, b in pairwise(self.tiers)
            if b.attribute_cap < a.attribute_cap
        ]
        return problems

    def _check_skills(self) -> list[str]:
        """Una errata aquí no rompe nada visible: la competencia simplemente no
        se podría tirar nunca con ese atributo."""
        conocidos = frozenset(a.id for a in self.attributes)
        problems = []
        for s in self.skills:
            problems += [
                f"skills.{s.id}: atributo desconocido {a!r}"
                for a in (s.attribute, *s.approaches)
                if a not in conocidos
            ]
            if s.attribute in s.approaches:
                problems.append(
                    f"skills.{s.id}: {s.attribute!r} es a la vez el atributo y un enfoque"
                )
        return problems


def _duplicates(campo: str, ids: Iterable[str]) -> list[str]:
    return [f"{campo}: id repetido {i!r}" for i, n in sorted(Counter(ids).items()) if n > 1]


def load_ruleset(path: Path) -> Ruleset:
    """`safe_load` y un error propio, por las mismas razones que `load_pack`."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return Ruleset.model_validate(raw)
    except ValidationError as exc:
        raise RulesetError(f"no se pudo cargar {path}:\n{exc}") from exc
