"""El enlace entre un mundo y un sistema de rol (unidad 11, D-159).

Dice cómo se leen los rasgos y ejes de un mundo como números de un sistema. No
lo sabe el pack (no sabe de reglas) ni el sistema (no sabe de mundos): vive en
un archivo del pack por sistema, `packs/<mundo>/reglas/<sistema>.yaml`, y
cambiar de mesa es cambiar de archivo.

Todo número se escribe igual, como una forma lineal sobre señales del mundo:

    valor = base + Σ peso · señal

Una señal es `rasgo:x` (su valor), `rango:eje` (rangos rotos de un eje de
progresión), `eje:x` (el valor de una necesidad) o `temperamento:perilla` (la
del agente dividida por la del pack, así que 1 es lo normal). Sin lenguaje de
expresiones a propósito: una forma lineal se lee de un vistazo y se valida
entera al cargar.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from agora.engine.disposition import Temperament
from agora.engine.ontology import AflictionSpec, Spec
from agora.engine.pack import ContentPack
from agora.rules.scene import ArmorSpec, WeaponSpec
from agora.rules.system import Ruleset


class BindingError(ValueError):
    """El enlace no casa con el mundo o con el sistema."""


class SignalKind(StrEnum):
    TRAIT = "rasgo"
    RANK = "rango"
    NEED = "eje"
    TEMPERAMENT = "temperamento"


def parse_signal(signal: str) -> tuple[SignalKind, str]:
    tipo, _, nombre = signal.partition(":")
    return SignalKind(tipo), nombre


class LinearSpec(Spec):
    base: float = 0.0
    terms: dict[str, float] = Field(default_factory=dict)
    """Señal → peso."""


class GrowthSpec(Spec):
    """Cómo pasa el potencial a valor con la experiencia (§7.3 del borrador):
    `inicio + (potencial - inicio) * rango / (rango + mitad)`. Con `mitad`
    rangos se llega a medio camino, y al techo no se llega nunca del todo."""

    rank_of: str
    """El eje de progresión cuyos rangos son la experiencia."""
    start: int = Field(default=4, ge=0)
    half: float = Field(default=4.0, gt=0.0)


class AccessSpec(Spec):
    """Quién puede tener esta pieza a mano. Sin señal, cualquiera."""

    signal: str | None = None
    at_least: float = 0.0


class GearWeapon(WeaponSpec):
    skill: str
    """Con qué competencia se ataca con ella."""
    access: AccessSpec = Field(default_factory=AccessSpec)


class GearArmor(ArmorSpec):
    access: AccessSpec = Field(default_factory=AccessSpec)


class ResourceNeeds(Spec):
    """Qué necesidad del mundo dice cuánto queda de cada recurso (D-154). La
    Vitalidad es la necesidad por el máximo; la Fatiga, lo que le falta a la
    necesidad por la capacidad; el Estrés, el desgaste por la capacidad."""

    vitality: str
    fatigue: str | None = None
    down: AflictionSpec | None = None
    """Lo que se lleva al mundo quien cae en una escena (unidad 13): la herida
    grave que, con el `lethal_after` del mundo, decide si sobrevive."""


class StyleBinding(Spec):
    """El estilo de D-158, sacado de quién es cada uno (D-160)."""

    aggression: LinearSpec
    flee_below: LinearSpec
    whim: LinearSpec
    target: str
    """Señal de a quién va: alta, al más fuerte; baja, al más débil; en medio,
    a quien peor le cae."""
    finish: str
    """Señal de piedad: baja, remata siempre; alta, nunca; en medio, solo a
    quien odia."""
    low: float = 0.35
    high: float = 0.65


class RoleSpec(Spec):
    attributes: tuple[str, str]
    label: str


class BindingSpec(Spec):
    system: str
    """El id del sistema al que enlaza; tiene que coincidir con el cargado."""
    potentials: dict[str, LinearSpec]
    """Una entrada por atributo del sistema: su potencial, de 0 al techo."""
    growth: GrowthSpec
    level: LinearSpec
    skills: dict[str, LinearSpec] = Field(default_factory=dict)
    weapons: tuple[GearWeapon, ...] = Field(min_length=1)
    armors: tuple[GearArmor, ...] = ()
    resources: ResourceNeeds
    style: StyleBinding
    roles: tuple[RoleSpec, ...] = ()


_PERILLAS = frozenset(f.name for f in fields(Temperament))


def check_binding(binding: BindingSpec, pack: ContentPack, ruleset: Ruleset) -> list[str]:
    """Lo que el enlace nombra y el mundo o el sistema no tienen. Un error aquí
    no rompería nada visible: una señal mal escrita valdría 0 en todos, y todo
    el mundo saldría igual de fuerte."""
    rasgos = frozenset(str(t.id) for t in pack.traits)
    ejes = frozenset(str(n.id) for n in pack.needs)
    con_rangos = frozenset(str(n.id) for n in pack.needs if n.rank_slowdown > 0)
    atributos = frozenset(a.id for a in ruleset.attributes)
    competencias = frozenset(s.id for s in ruleset.skills)
    problems: list[str] = []
    if binding.system != ruleset.id:
        problems.append(f"enlaza con el sistema {binding.system!r} y no con {ruleset.id!r}")
    if ruleset.combat is None or ruleset.resources is None:
        problems.append(f"el sistema {ruleset.id!r} necesita combat y resources")

    def senal(donde: str, s: str) -> None:
        try:
            tipo, nombre = parse_signal(s)
        except ValueError:
            problems.append(f"{donde}: señal {s!r} sin tipo conocido")
            return
        conocidos = {
            SignalKind.TRAIT: rasgos, SignalKind.NEED: ejes,
            SignalKind.RANK: con_rangos, SignalKind.TEMPERAMENT: _PERILLAS,
        }[tipo]
        if nombre not in conocidos:
            problems.append(f"{donde}: {s!r} no existe en este mundo")

    def lineal(donde: str, spec: LinearSpec) -> None:
        for s in sorted(spec.terms):
            senal(donde, s)

    if set(binding.potentials) != atributos:
        problems.append(
            f"potentials: hacen falta exactamente los atributos {sorted(atributos)}"
        )
    for nombre, spec in sorted(binding.potentials.items()):
        lineal(f"potentials.{nombre}", spec)
    if binding.growth.rank_of not in con_rangos:
        problems.append(f"growth.rank_of: {binding.growth.rank_of!r} no es un eje con rangos")
    lineal("level", binding.level)
    for nombre, spec in sorted(binding.skills.items()):
        if nombre not in competencias:
            problems.append(f"skills: competencia desconocida {nombre!r}")
        lineal(f"skills.{nombre}", spec)
    piezas: list[GearWeapon | GearArmor] = [*binding.weapons, *binding.armors]
    for pieza in piezas:
        if pieza.access.signal is not None:
            senal(f"{pieza.id}.access", pieza.access.signal)
        problems += [f"{pieza.id}: requires de un atributo desconocido {a!r}"
                     for a in sorted(pieza.requires) if a not in atributos]
    problems += [f"{w.id}: competencia desconocida {w.skill!r}"
                 for w in binding.weapons if w.skill not in competencias]
    ids = [p.id for p in piezas]
    problems += [f"pieza repetida {i!r}" for i in sorted(set(ids)) if ids.count(i) > 1]
    for eje in (binding.resources.vitality, binding.resources.fatigue):
        if eje is not None and eje not in ejes:
            problems.append(f"resources: eje desconocido {eje!r}")
    caida = binding.resources.down
    if caida is not None:
        personales = frozenset(str(s.id) for s in pack.situations if s.personal)
        if caida.situation not in personales:
            problems.append(f"resources.down: {caida.situation!r} no es una condición personal")
    for nombre, spec in (("aggression", binding.style.aggression),
                         ("flee_below", binding.style.flee_below),
                         ("whim", binding.style.whim)):
        lineal(f"style.{nombre}", spec)
    senal("style.target", binding.style.target)
    senal("style.finish", binding.style.finish)
    for r in binding.roles:
        problems += [f"roles.{r.label}: atributo desconocido {a!r}"
                     for a in r.attributes if a not in atributos]
    return problems


def load_binding(path: Path, pack: ContentPack, ruleset: Ruleset) -> BindingSpec:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        binding = BindingSpec.model_validate(raw)
    except ValidationError as exc:
        raise BindingError(f"no se pudo cargar {path}:\n{exc}") from exc
    problems = check_binding(binding, pack, ruleset)
    if problems:
        raise BindingError(
            f"el enlace {path} no casa con {pack.id!r} y {ruleset.id!r}:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    return binding


def role_label(binding: BindingSpec, first: str, second: str, labels: Mapping[str, str]) -> str:
    """El rol es una salida (D-160): el nombre de la pareja de atributos más
    altos, o los dos nombres si el enlace no le da uno."""
    for r in binding.roles:
        if {first, second} == set(r.attributes):
            return r.label
    return f"{labels[first].lower()} y {labels[second].lower()}"
