"""Un encuentro de combate por rondas, en una sola zona (unidad 09).

Es una escena por debajo del tick: una ronda son segundos y un tick, quince
minutos, así que el mundo no corre mientras se pelea. El encuentro no toca el
mundo (regla 1). Devuelve lo que pasó, y quien lo aplique será el puente de la
unidad 12. Tampoco decide nada por nadie: cada turno pregunta a una `Policy`.
Hoy esa política es el estilo del NPC (D-158); con la unidad 11 será también
el jugador.

Lo que la unidad 09 deja fuera a propósito, porque sin zonas no tiene lector:
el movimiento y las distancias, la acción rápida y la reacción (ataque de
oportunidad, interponerse), los enemigos menores y las maniobras. Llegan con
la unidad 10.

Los dados salen de un flujo por turno: `("encuentro", id, ronda, actor)`.
Todo lo que se tira en el turno de alguien, incluida la defensa de otro, sale
de ese flujo y en el orden en que pasa. La iniciativa tiene su propio flujo,
`("encuentro", id, "iniciativa", actor)`, y el capricho del estilo el suyo,
`("estilo", id, ronda, actor)`, para que encender el capricho no mueva los
dados de nadie.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from agora.engine.ports import Challenge, Dice, Outcome, Resolution
from agora.engine.rng import RngSource
from agora.rules.damage import VitalityBand, damage, vitality_band
from agora.rules.pool import KeyedDice, PoolResolver
from agora.rules.scene import ArmorSpec, CombatantSpec, ScenarioError, ScenarioSpec, WeaponSpec
from agora.rules.system import CombatSpec, Ruleset


def best_attribute(
    ruleset: Ruleset, attributes: Mapping[str, int], skill: str,
    allowed: frozenset[str] | None = None,
) -> str:
    """El atributo con más grado entre el de la competencia y sus enfoques;
    a igualdad, el de por defecto y luego el orden en que el sistema los
    declara. Vive fuera del encuentro porque quien elige equipo (unidad 11)
    tiene que hacer la misma cuenta que quien pelea: una sola puerta."""
    spec = next(s for s in ruleset.skills if s.id == skill)
    candidatos = [a for a in (spec.attribute, *spec.approaches)
                  if allowed is None or a in allowed]
    return max(candidatos, key=lambda a: (ruleset.grade(attributes[a]), -candidatos.index(a)))


def attack_approach(
    ruleset: Ruleset, attributes: Mapping[str, int], skill: str, weapon: WeaponSpec
) -> str:
    """Con qué atributo ataca: el ágil solo con arma ágil (§14.1)."""
    assert ruleset.combat is not None
    todos = frozenset(a.id for a in ruleset.attributes)
    permitidos = todos if weapon.agile else todos - {ruleset.combat.agile_attribute}
    return best_attribute(ruleset, attributes, skill, permitidos)


class Status(StrEnum):
    ACTIVE = "activo"
    DOWN = "caído"
    DEAD = "muerto"
    FLED = "huido"
    SURRENDERED = "rendido"
    BROKEN = "quebrado"


GONE = frozenset({Status.DEAD, Status.FLED, Status.SURRENDERED, Status.BROKEN})
"""Quien ya no está en la escena: ni actúa, ni se le ataca, ni se le remata."""


BEAT_KINDS = frozenset({"quiebre", "reloj_de_muerte"})
"""Los hechos de la escena que no son una acción elegida: los que pone `_beat`
con un texto en vez de un `ActionKind`. Los lee el narrador (unidad 17)."""


class ActionKind(StrEnum):
    ATTACK = "atacar"
    TOTAL_DEFENSE = "defensa_total"
    RECOVER = "recuperar_aliento"
    FIRST_AID = "primeros_auxilios"
    FINISH = "rematar"
    FLEE = "huir"
    SURRENDER = "rendirse"


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionKind
    target: str | None = None
    force: bool = False
    """Forzarse: un dado más a cambio de fatiga (§8.5). Solo al atacar."""


@dataclass(slots=True)
class Fighter:
    """El estado de escena de un combatiente. Mutable porque vive lo que dura
    la escena y nada más; lo que haya que llevarse al mundo sale en el
    `EncounterResult`."""

    spec: CombatantSpec
    side: str
    weapon: WeaponSpec
    armor: ArmorSpec | None
    vitality: int
    fatigue: int = 0
    stress: int = 0
    impetus: int = 0
    status: Status = Status.ACTIVE
    stabilized: bool = False
    death_marks: int = 0
    defenses: int = 0
    total_defense: bool = False
    edge: dict[str, int] = field(default_factory=dict)
    """Dados de más contra cada rival, ganados por la posición (§10.2). Se
    gastan en la siguiente acción contra él."""
    trauma: bool = False
    escape: int = 0
    """Segmentos de su reloj de escapar (D-165)."""
    caught: int = 0
    """Segmentos del reloj de alcanzarle. Lleno, ya no puede huir."""
    refused: bool = False
    """Si ya le rechazaron la rendición en esta escena."""

    @property
    def id(self) -> str:
        return self.spec.id


@dataclass(frozen=True, slots=True)
class Beat:
    """Un hecho del encuentro, con los dados a la vista para quien lo lea."""

    round: int
    actor: str
    kind: str
    target: str | None = None
    outcome: Outcome | None = None
    damage: int = 0
    note: str = ""
    dice: tuple[int, ...] = ()
    opposing_dice: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class FighterReport:
    id: str
    side: str
    status: Status
    vitality: int
    fatigue: int
    stress: int
    impetus: int
    stabilized: bool
    trauma: bool


@dataclass(frozen=True, slots=True)
class EncounterResult:
    winner: str | None
    """El bando que queda en pie; `None` si nadie o si se acabaron las rondas."""
    rounds: int
    fighters: tuple[FighterReport, ...]
    beats: tuple[Beat, ...]


class Policy(Protocol):
    """Quién decide en cada turno. La costura por la que entrará el jugador."""

    def choose(self, encounter: Encounter, me: Fighter) -> Action: ...

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        """Si gasta estrés en resistir un golpe que ya sabe cuánto le hace."""
        ...

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        """Si remata a un caído. También decide si acepta la rendición de
        alguien: quien remataría no acepta (D-165)."""
        ...

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        """Si persigue a quien huye. Si nadie persigue, la huida sale sola."""
        ...


HIT = frozenset({Outcome.SUCCESS_AT_COST, Outcome.SUCCESS, Outcome.CRITICAL})
KILL = frozenset({Outcome.SUCCESS, Outcome.CRITICAL})
"""Rematar exige éxito pleno (§10.6): con coste, el golpe no basta."""


class Encounter:
    def __init__(
        self, scenario: ScenarioSpec, ruleset: Ruleset, source: RngSource, encounter_id: str,
        surprised: frozenset[str] = frozenset(),
    ) -> None:
        if ruleset.combat is None:
            raise ScenarioError(f"el sistema {ruleset.id!r} no tiene sección combat")
        self.scenario = scenario
        self.ruleset = ruleset
        self.combat: CombatSpec = ruleset.combat
        self.resolver = PoolResolver.from_ruleset(ruleset)
        self.source = source
        self.id = encounter_id
        self.round = 0
        self.beats: list[Beat] = []
        armas = {w.id: w for w in scenario.weapons}
        armaduras = {a.id: a for a in scenario.armors}
        self.fighters: dict[str, Fighter] = {
            c.id: Fighter(
                spec=c, side=side.id, weapon=armas[c.weapon],
                armor=None if c.armor is None else armaduras[c.armor],
                vitality=c.vitality if c.start_vitality is None else c.start_vitality,
                fatigue=c.start_fatigue or 0,
                stress=c.start_stress or 0,
            )
            for side in scenario.sides
            for c in side.combatants
        }
        self.side_effect = {side.id: side.effect for side in scenario.sides}
        self.surprised = surprised
        """Quien actúa al final de la primera ronda (§9.1): le pillaron
        desprevenido. Solo la primera ronda; después, su iniciativa."""
        self.order = self._initiative()

    # -- lo que se puede preguntar ------------------------------------------

    def grade(self, f: Fighter, attribute: str) -> int:
        return self.ruleset.grade(f.spec.attributes[attribute])

    def band(self, f: Fighter) -> VitalityBand:
        return vitality_band(f.vitality, f.spec.vitality, self.ruleset.vitality)

    def tired(self, f: Fighter) -> bool:
        return f.fatigue * 100 >= f.spec.fatigue * self.combat.tired_at

    def exhausted(self, f: Fighter) -> bool:
        return f.fatigue * 100 >= f.spec.fatigue * self.combat.exhausted_at

    def collapsed(self, f: Fighter) -> bool:
        """Fatiga al tope: cae sin perder Vitalidad y solo puede recuperarse."""
        return f.fatigue >= f.spec.fatigue

    def enemies(self, f: Fighter) -> list[Fighter]:
        return [o for o in self.fighters.values() if o.side != f.side and o.status not in GONE]

    def allies(self, f: Fighter) -> list[Fighter]:
        return [
            o for o in self.fighters.values()
            if o.side == f.side and o.id != f.id and o.status not in GONE
        ]

    def legal_actions(self, f: Fighter) -> tuple[Action, ...]:
        """En orden fijo: el capricho elige de aquí con un sorteo por clave."""
        if self.collapsed(f):
            return (Action(ActionKind.RECOVER),)
        enemigos = self.enemies(f)
        acciones = [Action(ActionKind.ATTACK, o.id) for o in enemigos if o.status is Status.ACTIVE]
        acciones += [Action(ActionKind.FINISH, o.id) for o in enemigos if o.status is Status.DOWN]
        acciones += [
            Action(ActionKind.FIRST_AID, o.id) for o in self.allies(f)
            if o.status is Status.DOWN and not o.stabilized
        ]
        acciones += [Action(k) for k in (ActionKind.TOTAL_DEFENSE, ActionKind.RECOVER)]
        if f.caught < self.combat.chase_clock:
            acciones.append(Action(ActionKind.FLEE))
        acciones.append(Action(ActionKind.SURRENDER))
        return tuple(acciones)

    def style_rng(self, f: Fighter) -> random.Random:
        return self.source.stream("estilo", self.id, self.round, f.id)

    # -- reservas ------------------------------------------------------------

    def physical_penalty(self, f: Fighter) -> int:
        vit = self.ruleset.vitality
        herida = {VitalityBand.WOUNDED: vit.wounded_penalty,
                  VitalityBand.GRAVE: vit.grave_penalty}.get(self.band(f), 0)
        cansancio = (self.combat.exhausted_penalty if self.exhausted(f)
                     else self.combat.tired_penalty if self.tired(f) else 0)
        return herida + cansancio

    def _skill(self, f: Fighter, skill: str) -> int:
        return f.spec.skills.get(skill, 0) + int(skill in f.spec.specialties)

    def _best_attribute(self, f: Fighter, skill: str, allowed: frozenset[str] | None = None) -> str:
        return best_attribute(self.ruleset, f.spec.attributes, skill, allowed)

    def approach(self, f: Fighter) -> str:
        return attack_approach(self.ruleset, f.spec.attributes, f.spec.attack_skill, f.weapon)

    def attack_pool(self, f: Fighter, target: Fighter, force: bool) -> int:
        return (self.grade(f, self.approach(f)) + self._skill(f, f.spec.attack_skill)
                + f.edge.get(target.id, 0) + int(force) - self.physical_penalty(f))

    def defense_pool(self, f: Fighter) -> int:
        c = self.combat
        return (self.grade(f, self._best_attribute(f, c.defense_skill))
                + self._skill(f, c.defense_skill) + int(f.weapon.defensive)
                + (c.total_defense_bonus if f.total_defense else 0)
                - f.defenses * c.defense_step - self.physical_penalty(f))

    def endurance_pool(self, f: Fighter) -> int:
        """Aguante a secas: grado de su atributo y nivel, sin armadura ni
        penalizaciones. Es lo que tira un caído contra su reloj de muerte."""
        skill = self.combat.resist_skill
        atributo = next(s for s in self.ruleset.skills if s.id == skill).attribute
        return self.grade(f, atributo) + self._skill(f, skill)

    def resist_pool(self, f: Fighter) -> int:
        armadura = f.armor.resist_dice if f.armor is not None else 0
        return self.endurance_pool(f) + armadura - self.physical_penalty(f)

    def first_aid_pool(self, f: Fighter) -> int:
        skill = self.combat.first_aid_skill
        return self.grade(f, self._best_attribute(f, skill)) + self._skill(f, skill)

    # -- el bucle ------------------------------------------------------------

    def _initiative(self) -> tuple[str, ...]:
        c = self.combat

        def clave(f: Fighter) -> tuple[int, int, str]:
            d6 = self.source.stream("encuentro", self.id, "iniciativa", f.id).randint(1, 6)
            total = sum(f.spec.attributes[a] for a in c.initiative) + d6
            return (-total, -f.spec.attributes[c.initiative_tiebreak], f.id)

        return tuple(f.id for f in sorted(self.fighters.values(), key=clave))

    def winner(self) -> str | None:
        en_pie = sorted({f.side for f in self.fighters.values() if f.status is Status.ACTIVE})
        return en_pie[0] if len(en_pie) == 1 else None

    def over(self) -> bool:
        return len({f.side for f in self.fighters.values() if f.status is Status.ACTIVE}) < 2

    def run(self, policy: Policy) -> EncounterResult:
        while not self.over() and self.round < self.combat.max_rounds:
            self.round += 1
            turnos = self.order
            if self.round == 1 and self.surprised:
                turnos = (*(i for i in self.order if i not in self.surprised),
                          *(i for i in self.order if i in self.surprised))
            for fid in turnos:
                f = self.fighters[fid]
                if f.status in GONE:
                    continue
                dice = KeyedDice(self.source.stream("encuentro", self.id, self.round, fid))
                self._turn(f, policy, dice)
                if self.over():
                    break
            if not self.over() and self.round % self.combat.long_fight_every == 0:
                for f in self.fighters.values():
                    if f.status is Status.ACTIVE:
                        f.fatigue += 1
        self._close(policy)
        return EncounterResult(
            winner=self.winner(),
            rounds=self.round,
            fighters=tuple(
                FighterReport(f.id, f.side, f.status, f.vitality, f.fatigue, f.stress,
                              f.impetus, f.stabilized, f.trauma)
                for f in self.fighters.values()
            ),
            beats=tuple(self.beats),
        )

    def _turn(self, f: Fighter, policy: Policy, dice: Dice) -> None:
        f.defenses = 0
        f.total_defense = False
        if f.status is Status.DOWN:
            self._death_clock(f, dice)
            return
        accion = policy.choose(self, f)
        # Una sola puerta para las dos políticas, la del estilo y la del
        # jugador: lo que no es legal no se hace, en vez de hacerse a medias.
        if Action(accion.kind, accion.target) not in self.legal_actions(f):
            raise ValueError(f"{f.id}: acción ilegal {accion}")
        if accion.force and (accion.kind is not ActionKind.ATTACK or self.exhausted(f)):
            raise ValueError(f"{f.id}: solo se fuerza al atacar y sin estar exhausto")
        match accion.kind:
            case ActionKind.ATTACK:
                assert accion.target is not None
                self._attack(f, self.fighters[accion.target], accion.force, dice, policy, True)
            case ActionKind.TOTAL_DEFENSE:
                f.total_defense = True
                self._beat(f, accion.kind)
            case ActionKind.RECOVER:
                f.fatigue = max(0, f.fatigue - self.combat.recover_fatigue)
                self._beat(f, accion.kind)
            case ActionKind.FIRST_AID:
                assert accion.target is not None
                self._first_aid(f, self.fighters[accion.target], dice)
            case ActionKind.FINISH:
                assert accion.target is not None
                self._finish(f, self.fighters[accion.target], dice)
            case ActionKind.FLEE:
                self._flee(f, dice, policy)
            case ActionKind.SURRENDER:
                self._surrender(f, policy)

    # -- lo que pasa al actuar -------------------------------------------------

    def _attack(
        self, f: Fighter, target: Fighter, force: bool, dice: Dice, policy: Policy,
        consequences: bool, why: str = "contraataque",
    ) -> None:
        """Atacar (§10). `consequences` es falso en el contraataque inmediato
        de una posición desesperada: si no, cada contraataque fallido abriría
        otro y el turno no acabaría nunca."""
        pool = self.attack_pool(f, target, force)
        f.edge.pop(target.id, None)
        if force:
            f.fatigue += self.combat.force_fatigue
        defensa = self.defense_pool(target)
        target.defenses += 1
        desesperada = self.band(f) is VitalityBand.GRAVE
        res = self.resolver.resolve(
            Challenge(pool=pool, effect=self.side_effect[f.side],
                      tier_gap=target.spec.tier - f.spec.tier, opposing_pool=defensa),
            dice,
        )
        golpe = 0
        notas = [f"{pool} contra {defensa}"]
        if force:
            notas.append("forzándose")
        if not consequences:
            notas.append(why)
        if res.outcome in HIT:
            atributo = self.approach(f)
            perfora = f.weapon.piercing + int(atributo == self.combat.strength_attribute)
            proteccion = target.armor.protection if target.armor is not None else 0
            grado = self.grade(f, atributo)
            golpe = damage(f.weapon.base, grado, res.effect, proteccion, perfora)
            if res.outcome is Outcome.CRITICAL:
                self._impetus(target)
            if golpe > 0 and policy.resists(self, target, golpe, res.outcome):
                r = self.resolver.resist(self.resist_pool(target), res.effect, dice)
                golpe = damage(f.weapon.base, grado, r.effect, proteccion, perfora)
                notas.append(f"resiste, {r.stress} de estrés")
                self._stress(target, r.stress, dice)
        self._beat(f, ActionKind.ATTACK, target.id, res.outcome, golpe, ", ".join(notas),
                   res=res)
        if golpe > 0:
            self._hurt(target, golpe, dice)
        if consequences and res.outcome in (Outcome.FAILURE, Outcome.SUCCESS_AT_COST):
            if desesperada:
                if res.outcome is Outcome.FAILURE:
                    self._impetus(f)
                if target.status is Status.ACTIVE and not self.collapsed(target):
                    self._attack(target, f, False, dice, policy, False)
            else:
                target.edge[f.id] = target.edge.get(f.id, 0) + 1

    def chase_pool(self, f: Fighter) -> int:
        skill = self.combat.chase_skill
        assert skill is not None
        return (self.grade(f, self._best_attribute(f, skill)) + self._skill(f, skill)
                - self.physical_penalty(f))

    def _flee(self, f: Fighter, dice: Dice, policy: Policy) -> None:
        """Una persecución con dos relojes (D-165). Sin competencia de
        persecución en el sistema, huir sale siempre, como en la 09."""
        reloj = self.combat.chase_clock
        perseguidores = [
            o for o in self.enemies(f)
            if o.status is Status.ACTIVE and not self.collapsed(o) and policy.pursues(self, o, f)
        ]
        if self.combat.chase_skill is None or not perseguidores:
            f.status = Status.FLED
            self._beat(f, ActionKind.FLEE, note="nadie le persigue")
            return
        cazador = max(perseguidores, key=lambda o: (self.chase_pool(o), o.id))
        res = self.resolver.resolve(
            Challenge(pool=self.chase_pool(f), opposing_pool=self.chase_pool(cazador)), dice
        )
        golpe = False
        match res.outcome:
            case Outcome.SUCCESS | Outcome.CRITICAL:
                f.escape += 2
            case Outcome.SUCCESS_AT_COST:
                f.escape += 1
                f.caught += 1
                golpe = True
            case Outcome.FAILURE:
                f.caught += 2
                golpe = True
        relojes = f"escapar {min(f.escape, reloj)}/{reloj}, alcanzar {min(f.caught, reloj)}/{reloj}"
        self._beat(f, ActionKind.FLEE, cazador.id, res.outcome, note=relojes, res=res)
        if golpe:
            self._attack(cazador, f, False, dice, policy, False, "golpe de oportunidad")
        if f.escape >= reloj and f.status is Status.ACTIVE:
            f.status = Status.FLED

    def _surrender(self, f: Fighter, policy: Policy) -> None:
        """Rendirse exige que lo acepten todos los rivales en pie (D-165)."""
        rechazan = [o.id for o in self.enemies(f)
                    if o.status is Status.ACTIVE and policy.finishes(self, o, f)]
        if rechazan:
            f.refused = True
            self._beat(f, ActionKind.SURRENDER, note=f"rechazada por {', '.join(rechazan)}")
            return
        f.status = Status.SURRENDERED
        self._beat(f, ActionKind.SURRENDER)

    def _hurt(self, f: Fighter, golpe: int, dice: Dice) -> None:
        antes = self.band(f)
        f.vitality = max(0, f.vitality - golpe)
        despues = self.band(f)
        escalones = (VitalityBand.WOUNDED, VitalityBand.GRAVE)
        cruzados = sum(1 for b in escalones if _below(despues, b) and not _below(antes, b))
        for _ in range(cruzados):
            self._impetus(f)
        if despues is VitalityBand.DOWN and f.status is Status.ACTIVE:
            f.status = Status.DOWN
            for aliado in self.allies(f):
                if aliado.status is Status.ACTIVE:
                    self._impetus(aliado)
                    self._stress(aliado, 1, dice)

    def _impetus(self, f: Fighter) -> None:
        f.impetus = min(f.spec.impetus, f.impetus + 1)

    def _stress(self, f: Fighter, amount: int, dice: Dice) -> None:
        """Al tope, se quiebra (§11.3): con éxito despierta (Ímpetu lleno,
        estrés a la mitad); si falla, sale de la escena con un trauma."""
        if amount <= 0 or f.status is not Status.ACTIVE:
            return
        f.stress = min(f.spec.stress, f.stress + amount)
        if f.stress < f.spec.stress:
            return
        res = self.resolver.resolve(
            Challenge(pool=self.grade(f, self.combat.break_attribute)), dice
        )
        if res.outcome is Outcome.FAILURE:
            f.status = Status.BROKEN
            f.trauma = True
            self._beat(f, "quiebre", outcome=res.outcome, note="trauma", res=res)
        else:
            f.impetus = f.spec.impetus
            f.stress = f.spec.stress // 2
            self._beat(f, "quiebre", outcome=res.outcome, note="despertar", res=res)

    def _death_clock(self, f: Fighter, dice: Dice) -> None:
        if f.stabilized:
            return
        res = self.resolver.resolve(Challenge(pool=self.endurance_pool(f)), dice)
        if res.outcome is Outcome.FAILURE:
            f.death_marks += 1
            if f.death_marks >= self.combat.death_clock:
                f.status = Status.DEAD
        self._beat(f, "reloj_de_muerte", outcome=res.outcome,
                   note=f"{f.death_marks}/{self.combat.death_clock}", res=res)

    def _first_aid(self, f: Fighter, fallen: Fighter, dice: Dice) -> None:
        res = self.resolver.resolve(Challenge(pool=self.first_aid_pool(f)), dice)
        if res.outcome is not Outcome.FAILURE:
            fallen.stabilized = True
        self._beat(f, ActionKind.FIRST_AID, fallen.id, res.outcome, res=res)

    def _finish(self, f: Fighter, fallen: Fighter, dice: Dice) -> None:
        """Un caído no se defiende: es una tirada simple, y mata con éxito
        pleno. Hacerlo o no es decisión de quien remata (D-158)."""
        res = self.resolver.resolve(
            Challenge(pool=self.attack_pool(f, fallen, False),
                      tier_gap=fallen.spec.tier - f.spec.tier),
            dice,
        )
        if res.outcome in KILL and res.effect > 0:
            fallen.status = Status.DEAD
        self._beat(f, ActionKind.FINISH, fallen.id, res.outcome, res=res)

    def _close(self, policy: Policy) -> None:
        """Al acabar, quien queda en pie decide qué hace con los caídos del otro
        bando. Quien no remata los deja como están: lo que les pase después es
        cosa del mundo (unidad 12), no de la escena."""
        ganador = self.winner()
        if ganador is None:
            return
        for fid in self.order:
            f = self.fighters[fid]
            if f.side != ganador or f.status is not Status.ACTIVE:
                continue
            dice = KeyedDice(self.source.stream("encuentro", self.id, "cierre", fid))
            for caido in self.enemies(f):
                if caido.status is Status.DOWN and policy.finishes(self, f, caido):
                    self._finish(f, caido, dice)

    def _beat(
        self, f: Fighter, kind: str, target: str | None = None,
        outcome: Outcome | None = None, golpe: int = 0, note: str = "",
        res: Resolution | None = None,
    ) -> None:
        dados = res.dice if res is not None else ()
        rivales = res.opposing_dice if res is not None else ()
        self.beats.append(Beat(self.round, f.id, str(kind), target, outcome, golpe, note,
                               dados, rivales))


_ORDEN = (VitalityBand.HEALTHY, VitalityBand.WOUNDED, VitalityBand.GRAVE, VitalityBand.DOWN)


def _below(band: VitalityBand, threshold: VitalityBand) -> bool:
    """Si `band` está en `threshold` o por debajo."""
    return _ORDEN.index(band) >= _ORDEN.index(threshold)
