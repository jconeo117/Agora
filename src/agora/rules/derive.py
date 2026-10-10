"""La ficha mecánica de un agente, derivada de quién es (unidad 11, D-154, D-160).

No se guarda nada: la ficha es una función del estado del mundo, como el nivel
de detalle de un agente lo es del foco. Si el agente entrena, su ficha sube;
si lo hieren, entra herido en la escena. Lo que algún día se gane en escena
(los hitos del borrador) irá como un delta guardado encima; hoy no hay hitos,
así que tampoco hay delta.

Leer el mundo no lo cambia (regla 1): `derive` no escribe estado ni log.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agora.engine.ontology import AgentId, NeedId, TraitId
from agora.engine.ports import Effect
from agora.engine.state import AgentState, WorldState
from agora.rules.binding import (
    BindingSpec,
    GearArmor,
    GearWeapon,
    LinearSpec,
    SignalKind,
    parse_signal,
    role_label,
)
from agora.rules.damage import damage
from agora.rules.encounter import attack_approach
from agora.rules.scene import (
    ArmorSpec,
    CombatantSpec,
    CombatStyle,
    FinishOff,
    ScenarioSpec,
    SideSpec,
    TargetChoice,
    WeaponSpec,
)
from agora.rules.system import Ruleset

REFERENCE_PROTECTION = 1
"""Contra qué protección se compara un arma al elegirla: la de un cuero. Un
arma perforante solo rinde más contra quien lleva algo encima."""


def signal(world: WorldState, agent: AgentState, s: str) -> float:
    tipo, nombre = parse_signal(s)
    match tipo:
        case SignalKind.TRAIT:
            return agent.traits.get(TraitId(nombre), 0.0)
        case SignalKind.RANK:
            return float(agent.rango.get(NeedId(nombre), 0))
        case SignalKind.NEED:
            return agent.needs[NeedId(nombre)]
        case SignalKind.TEMPERAMENT:
            base = float(getattr(world.pack.tuning, nombre))
            return float(getattr(agent.temperament, nombre)) / base if base else 0.0


def linear(world: WorldState, agent: AgentState, spec: LinearSpec) -> float:
    return spec.base + sum(
        peso * signal(world, agent, s) for s, peso in sorted(spec.terms.items())
    )


def _clamp(x: float, low: int, high: int) -> int:
    return max(low, min(high, round(x)))


def _accessible(world: WorldState, agent: AgentState, pieza: GearWeapon | GearArmor) -> bool:
    acceso = pieza.access
    return acceso.signal is None or signal(world, agent, acceso.signal) >= acceso.at_least


def _fits(ruleset: Ruleset, values: dict[str, int], pieza: GearWeapon | GearArmor) -> bool:
    return all(ruleset.grade(values[a]) >= n for a, n in pieza.requires.items())


@dataclass(frozen=True, slots=True)
class MechanicalSheet:
    combatant: CombatantSpec
    potentials: dict[str, int]
    level: int
    role: str
    weapon: GearWeapon
    armor: GearArmor | None

    def lines(self, ruleset: Ruleset) -> list[str]:
        c = self.combatant
        etiquetas = {a.id: a.label for a in ruleset.attributes}
        atributos = "  ".join(
            f"{etiquetas[a]} {v}/{self.potentials[a]} (g{ruleset.grade(v)})"
            for a, v in c.attributes.items()
        )
        competencias = ", ".join(f"{s} {n}" for s, n in sorted(c.skills.items())) or "-"
        estilo = c.style
        return [
            f"  {c.label}: {self.role}, tier {c.tier}, nivel {self.level}",
            f"  atributos     {atributos}   (valor/potencial)",
            f"  competencias  {competencias}",
            f"  equipo        {self.weapon.label} ({c.attack_skill})"
            f", {self.armor.label if self.armor else 'sin armadura'}",
            f"  vitalidad     {c.start_vitality}/{c.vitality}"
            f"   fatiga {c.start_fatigue}/{c.fatigue}"
            f"   estrés {c.start_stress}/{c.stress}   ímpetu máx {c.impetus}",
            f"  estilo        agresividad {estilo.aggression}, huye bajo {estilo.flee_below} %,"
            f" capricho {estilo.whim} %, va a por {estilo.target.value},"
            f" remata {estilo.finish_off.value}",
        ]


def derive(
    world: WorldState, agent_id: AgentId, ruleset: Ruleset, binding: BindingSpec,
    rivals: Sequence[AgentId] = (),
) -> MechanicalSheet:
    """Revienta con `KeyError` si el agente no está vivo, como `ficha`."""
    if ruleset.combat is None or ruleset.resources is None:
        raise ValueError(f"el sistema {ruleset.id!r} necesita combat y resources")
    a = world.agents[agent_id]
    techo_absoluto = ruleset.tiers[-1].attribute_cap
    nivel_max = ruleset.tiers[-1].max_level
    nivel = _clamp(linear(world, a, binding.level), 1, nivel_max)
    tier = next(t for t in ruleset.tiers if t.min_level <= nivel <= t.max_level)

    rango = float(a.rango.get(NeedId(binding.growth.rank_of), 0))
    progreso = rango / (rango + binding.growth.half)
    inicio = binding.growth.start
    potenciales: dict[str, int] = {}
    valores: dict[str, int] = {}
    for attr in ruleset.attributes:
        potencial = _clamp(linear(world, a, binding.potentials[attr.id]), attr.minimum,
                           techo_absoluto)
        potenciales[attr.id] = potencial
        valor = potencial if potencial <= inicio else inicio + (potencial - inicio) * progreso
        valores[attr.id] = _clamp(valor, attr.minimum, tier.attribute_cap)

    competencias = {
        s: n for s, spec in sorted(binding.skills.items())
        if (n := _clamp(linear(world, a, spec), 0, ruleset.skill_max_level)) > 0
    }

    def rinde(w: GearWeapon) -> tuple[int, str]:
        """Daño estándar contra un cuero por los dados que tira: lo que se
        espera de un golpe por lo a menudo que se acierta."""
        atributo = attack_approach(ruleset, valores, w.skill, w)
        grado = ruleset.grade(valores[atributo])
        assert ruleset.combat is not None
        perfora = w.piercing + int(atributo == ruleset.combat.strength_attribute)
        golpe = damage(w.base, grado, Effect.STANDARD, REFERENCE_PROTECTION, perfora)
        dados = grado + competencias.get(w.skill, 0) + int(w.defensive)
        return (golpe * dados, w.id)

    armas = [w for w in binding.weapons
             if _accessible(world, a, w) and _fits(ruleset, valores, w)]
    if not armas:
        raise ValueError(f"{agent_id}: ninguna arma del enlace está a su alcance")
    arma = max(armas, key=lambda w: (rinde(w)[0], [-ord(c) for c in w.id]))
    armaduras = [p for p in binding.armors
                 if _accessible(world, a, p) and _fits(ruleset, valores, p)]
    armadura = (max(armaduras, key=lambda p: (2 * p.protection + p.resist_dice,
                                               [-ord(c) for c in p.id]))
                if armaduras else None)

    r = ruleset.resources
    vit_max = ruleset.evaluate(r.vitality, valores, competencias)
    fat_max = ruleset.evaluate(r.fatigue, valores, competencias)
    est_max = ruleset.evaluate(r.stress, valores, competencias)
    impetu = ruleset.evaluate(r.impetus, valores, competencias)
    necesidades = binding.resources
    # Nadie entra a una escena caído: con la salud a cero ya se está muriendo
    # en el mundo, y eso lo lleva el motor, no el encuentro.
    vit = _clamp(a.needs[NeedId(necesidades.vitality)] * vit_max, 1, vit_max)
    fat = (0 if necesidades.fatigue is None
           else _clamp((1.0 - a.needs[NeedId(necesidades.fatigue)]) * fat_max, 0, fat_max))
    est = _clamp(a.strain * est_max, 0, est_max - 1)

    s = binding.style
    def banda(senal_: str) -> int:
        v = signal(world, a, senal_)
        return -1 if v <= s.low else 1 if v >= s.high else 0
    estilo = CombatStyle(
        aggression=_clamp(linear(world, a, s.aggression), 0, 100),
        flee_below=_clamp(linear(world, a, s.flee_below), 0, 100),
        whim=_clamp(linear(world, a, s.whim), 0, 100),
        target={1: TargetChoice.STRONGEST, -1: TargetChoice.WEAKEST}.get(
            banda(s.target), TargetChoice.HATED),
        finish_off={-1: FinishOff.ALWAYS, 1: FinishOff.NEVER}.get(
            banda(s.finish), FinishOff.HATED),
    )
    aprecio = {
        str(o): _clamp(
            a.regard_for(o, world.tick, a.temperament.bond_fade, a.relation_floor(world.pack, o))
            * 100, -100, 100)
        for o in sorted(rivals) if o != agent_id
    }

    # Por valor y, a igualdad, por potencial: sin experiencia todos los valores
    # empatan en el de partida, y desempatar por el orden del sistema daba el
    # mismo rol a casi la mitad del mundo (89 de 200 en la primera sonda).
    orden = [x.id for x in ruleset.attributes]
    primero, segundo = sorted(
        orden, key=lambda x: (-valores[x], -potenciales[x], orden.index(x))
    )[:2]
    etiquetas = {x.id: x.label for x in ruleset.attributes}
    combatiente = CombatantSpec(
        id=str(agent_id), label=world.censo[agent_id].label, tier=tier.tier,
        attributes=valores, skills=competencias, attack_skill=arma.skill,
        weapon=arma.id, armor=None if armadura is None else armadura.id,
        vitality=vit_max, fatigue=fat_max, stress=est_max, impetus=impetu,
        style=estilo, regard=aprecio,
        start_vitality=vit, start_fatigue=fat, start_stress=est,
    )
    return MechanicalSheet(
        combatant=combatiente, potentials=potenciales, level=nivel,
        role=role_label(binding, primero, segundo, etiquetas), weapon=arma, armor=armadura,
    )


def _equipo_de_escena(binding: BindingSpec) -> tuple[tuple[WeaponSpec, ...], tuple[ArmorSpec, ...]]:
    """El catálogo del enlace sin lo que solo sirve para elegir (acceso,
    competencia): lo que el encuentro necesita saber de una pieza."""
    armas = tuple(
        WeaponSpec.model_validate(w.model_dump(exclude={"skill", "access"}))
        for w in binding.weapons
    )
    armaduras = tuple(
        ArmorSpec.model_validate(p.model_dump(exclude={"access"})) for p in binding.armors
    )
    return armas, armaduras


def duel(
    world: WorldState, one: AgentId, other: AgentId, ruleset: Ruleset, binding: BindingSpec
) -> ScenarioSpec:
    """Dos agentes del mundo, uno en cada bando, tal como están ahora. Es el
    cruce entre la ficha derivada y el simulador de la 09: si la ficha dice
    que alguien es fuerte, el simulador tiene que darle la razón."""
    armas, armaduras = _equipo_de_escena(binding)
    lados = tuple(
        SideSpec(id=str(quien), label=world.censo[quien].label,
                 combatants=(derive(world, quien, ruleset, binding, (rival,)).combatant,))
        for quien, rival in ((one, other), (other, one))
    )
    return ScenarioSpec(
        id=f"duelo_{one}_{other}", label=f"{lados[0].label} contra {lados[1].label}",
        weapons=armas, armors=armaduras, sides=(lados[0], lados[1]),
    )


def census(world: WorldState, ruleset: Ruleset, binding: BindingSpec) -> list[str]:
    """El instrumento de la unidad 11: cómo se reparten las fichas de todos los
    vivos. Si salen planas (todos el mismo tier, la misma arma, el mismo
    estilo), la derivación no distingue a nadie, y eso se ve antes de pelear."""
    fichas = [derive(world, a, ruleset, binding) for a in sorted(world.agents)]
    if not fichas:
        return ["  nadie vivo"]

    def reparto(cosas: Sequence[str | int]) -> str:
        cuenta: dict[str | int, int] = {}
        for c in cosas:
            cuenta[c] = cuenta.get(c, 0) + 1
        orden = sorted(cuenta.items(), key=lambda x: (-x[1], str(x[0])))
        return "  ".join(f"{k} {n}" for k, n in orden)

    salida = [f"# {len(fichas)} fichas, tick {world.tick}"]
    salida.append("  tiers         " + reparto([f.combatant.tier for f in fichas]))
    for attr in ruleset.attributes:
        grados = [ruleset.grade(f.combatant.attributes[attr.id]) for f in fichas]
        salida.append(f"  {attr.label:<13} grados  " + reparto(grados))
    salida.append("  roles         " + reparto([f.role for f in fichas]))
    salida.append("  armas         " + reparto([f.weapon.label for f in fichas]))
    salida.append("  armaduras     " + reparto([f.armor.label if f.armor else "-" for f in fichas]))
    estilos = [f.combatant.style for f in fichas]
    def quintos(xs: list[int]) -> str:
        xs = sorted(xs)
        return " / ".join(str(xs[min(len(xs) - 1, i * len(xs) // 4)]) for i in range(5))
    salida.append("  agresividad   " + quintos([e.aggression for e in estilos])
                  + "   (mín / cuartiles / máx)")
    salida.append("  huye bajo     " + quintos([e.flee_below for e in estilos]))
    salida.append("  capricho      " + quintos([e.whim for e in estilos]))
    salida.append("  va a por      " + reparto([e.target.value for e in estilos]))
    salida.append("  remata        " + reparto([e.finish_off.value for e in estilos]))
    distintas = len(
        {f.combatant.model_dump_json(exclude={"id", "label", "regard"}) for f in fichas}
    )
    salida.append(
        f"  fichas distintas  {distintas} de {len(fichas)} ({distintas / len(fichas):.0%})"
    )
    return salida
