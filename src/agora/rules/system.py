"""El sistema de la mesa, en datos (unidad 08).

Es a `rules/<sistema>/rules.yaml` lo que `ContentPack` es a un pack: un sistema
malformado no arranca. Lo que el borrador marca «a calibrar» vive aquí y no en
el código, porque la calibración cambia con la mesa y no con el motor.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

import yaml
from pydantic import Field, ValidationError, model_validator

from agora.engine.ontology import Example, Spec


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
    wounded_penalty: int = Field(default=1, ge=0)
    """Dados de menos en acciones físicas por estar herido (unidad 09)."""
    grave_penalty: int = Field(default=2, ge=0)
    """Ídem por estar grave, que además empeora un paso la posición."""


class CombatSpec(Spec):
    """Lo que un encuentro necesita saber del sistema (unidad 09).

    Los papeles (con qué se defiende, con qué se aguanta, qué atributo da la
    perforación) se nombran por id porque el código de las reglas no puede
    saber qué es la fuerza de nadie: lo dice la mesa. El resto son los números
    que el borrador marca «a calibrar».
    """

    initiative: tuple[str, ...]
    """Atributos cuyos VALORES se suman a 1d6 para la iniciativa (§9.1)."""
    initiative_tiebreak: str
    """Atributo que desempata la iniciativa; después, el id."""
    defense_skill: str
    resist_skill: str
    """La competencia con la que se resiste el daño y se aguanta caído; se tira
    con su atributo por defecto."""
    first_aid_skill: str
    break_attribute: str
    """Con qué se tira al quebrarse por estrés (§11.3)."""
    strength_attribute: str
    """Atacar con este atributo da +1 de perforación (§10.3)."""
    agile_attribute: str
    """Atacar con este atributo exige un arma ágil (§14.1)."""
    defense_step: int = Field(default=1, ge=0)
    total_defense_bonus: int = Field(default=2, ge=0)
    force_fatigue: int = Field(default=2, ge=0)
    recover_fatigue: int = Field(default=2, ge=1)
    long_fight_every: int = Field(default=4, ge=1)
    death_clock: int = Field(default=4, ge=1)
    tired_at: int = Field(default=50, gt=0, lt=100)
    exhausted_at: int = Field(default=75, gt=0, lt=100)
    tired_penalty: int = Field(default=1, ge=0)
    exhausted_penalty: int = Field(default=2, ge=0)
    max_rounds: int = Field(default=30, ge=1)
    """Tope de rondas: un encuentro que no acaba es un empate, no un bucle."""
    chase_skill: str | None = None
    """Con qué se huye y se persigue (D-165, unidad 13). `None` deja la huida
    como en la 09: gratis y siempre sale, que es lo que este campo viene a
    corregir."""
    chase_clock: int = Field(default=3, ge=1)
    """Segmentos de los dos relojes de una persecución: escapar y alcanzar."""
    examples: dict[str, tuple[Example, ...]] = Field(default_factory=dict)
    """Cómo pediría un jugador cada acción de la escena, por su id (unidad 14).
    Es de la mesa y no del mundo: «me cubro» es defensa total en cualquier isla."""

    @model_validator(mode="after")
    def _examples_known(self) -> CombatSpec:
        # Import tardío: `encounter` importa este módulo.
        from agora.rules.encounter import ActionKind

        conocidas = {k.value for k in ActionKind}
        sobran = sorted(k for k in self.examples if k not in conocidas)
        if sobran:
            raise ValueError(f"combat.examples: acciones que la escena no tiene: {sobran}")
        return self


class CalibrationTarget(Spec):
    """Una promesa medible del sistema (§24.4), como el contrato de salud de un
    pack: el simulador la comprueba y dice CUMPLE o NO CUMPLE."""

    scenario: str
    """El escenario, por nombre de archivo en `escenarios/` junto al sistema."""
    side: str
    win_min: int = Field(ge=0, le=100)
    win_max: int = Field(ge=0, le=100)
    rounds_min: int | None = Field(default=None, ge=1)
    rounds_max: int | None = Field(default=None, ge=1)
    """Banda de la MEDIANA de rondas; sin ella no se mira la duración."""


class TermSource(StrEnum):
    VALUE = "valor"
    GRADE = "grado"
    SKILL = "competencia"


class TermSpec(Spec):
    """Un sumando de una fórmula: `num * x // den`, con x el valor o el grado de
    un atributo, o el nivel de una competencia. El suelo va por término, que es
    como redondea el borrador (`⌊Voluntad / 2⌋` en la Vitalidad)."""

    source: TermSource
    id: str
    num: int = Field(default=1, ge=1)
    den: int = Field(default=1, ge=1)


class FormulaSpec(Spec):
    base: int = 0
    terms: tuple[TermSpec, ...] = ()


class ResourcesSpec(Spec):
    """Las capacidades de §5.3 (unidad 11). Las fórmulas son del sistema; qué
    necesidad del mundo dice cuánto queda es del enlace con cada mundo (D-154)."""

    vitality: FormulaSpec
    fatigue: FormulaSpec
    stress: FormulaSpec
    impetus: FormulaSpec


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
    combat: CombatSpec | None = None
    """Sin esta sección el sistema tira dados pero no sabe pelear."""
    calibration: tuple[CalibrationTarget, ...] = ()
    resources: ResourcesSpec | None = None
    """Sin esta sección el sistema no sabe cuánto aguanta nadie: las fichas de
    escena tienen que escribirlo a mano."""

    def grade(self, value: int) -> int:
        """El grado es lo único del atributo que entra en una tirada; el valor
        alimenta los recursos. Por debajo del primer grado, 0: un atributo a 0
        no aporta dados."""
        return max((g.grade for g in self.grades if g.min_value <= value), default=0)

    def evaluate(
        self, formula: FormulaSpec, values: Mapping[str, int], skills: Mapping[str, int]
    ) -> int:
        total = formula.base
        for t in formula.terms:
            match t.source:
                case TermSource.VALUE:
                    x = values[t.id]
                case TermSource.GRADE:
                    x = self.grade(values[t.id])
                case TermSource.SKILL:
                    x = skills.get(t.id, 0)
            total += t.num * x // t.den
        return total

    @model_validator(mode="after")
    def _validate(self) -> Ruleset:
        problems = [
            *_duplicates("attributes", (a.id for a in self.attributes)),
            *_duplicates("skills", (s.id for s in self.skills)),
            *self._check_grades(),
            *self._check_tiers(),
            *self._check_skills(),
            *self._check_combat(),
            *self._check_calibration(),
            *self._check_resources(),
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

    def _check_combat(self) -> list[str]:
        """Un papel con una errata no rompe nada visible: nadie se defendería
        con nada y los combates durarían la mitad."""
        c = self.combat
        if c is None:
            return []
        atributos = frozenset(a.id for a in self.attributes)
        competencias = frozenset(s.id for s in self.skills)
        problems = [
            f"combat: atributo desconocido {a!r}"
            for a in (*c.initiative, c.initiative_tiebreak, c.break_attribute,
                      c.strength_attribute, c.agile_attribute)
            if a not in atributos
        ]
        problems += [
            f"combat: competencia desconocida {s!r}"
            for s in (c.defense_skill, c.resist_skill, c.first_aid_skill,
                      *(() if c.chase_skill is None else (c.chase_skill,)))
            if s not in competencias
        ]
        if c.tired_at >= c.exhausted_at:
            problems.append("combat: tired_at tiene que quedar por debajo de exhausted_at")
        return problems

    def _check_resources(self) -> list[str]:
        if self.resources is None:
            return []
        atributos = frozenset(a.id for a in self.attributes)
        competencias = frozenset(s.id for s in self.skills)
        problems = []
        for nombre in ("vitality", "fatigue", "stress", "impetus"):
            formula: FormulaSpec = getattr(self.resources, nombre)
            for t in formula.terms:
                conocidos = competencias if t.source is TermSource.SKILL else atributos
                if t.id not in conocidos:
                    problems.append(f"resources.{nombre}: {t.source.value} desconocido {t.id!r}")
        return problems

    def _check_calibration(self) -> list[str]:
        problems = [
            f"calibration.{t.scenario}: win_min ({t.win_min}) por encima de win_max ({t.win_max})"
            for t in self.calibration
            if t.win_min > t.win_max
        ]
        if self.calibration and self.combat is None:
            problems.append("calibration: prometer combates exige la sección combat")
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
