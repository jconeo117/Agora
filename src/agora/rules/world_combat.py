"""Pelear desde el mundo: la escena de la 09 con las fichas de la 11, cuando
el jugador está en ella (unidad 13, D-161).

Implementa `EncounterResolver`, la costura del motor. El motor pregunta quién
ataca a quién y quién estaba desprevenido; aquí se derivan las dos fichas, se
juega la escena con el estilo de cada NPC y las decisiones del jugador, y se
devuelve cómo acaba cada uno **en términos del mundo**: el enlace sabe qué
necesidad es la Vitalidad y cuál el descanso, y qué herida se lleva quien cae.
Aplicarlo es cosa del motor (regla 1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agora.engine.ontology import AgentId, NeedId
from agora.engine.ports import CombatantOutcome, EncounterOutcome, Fate, Outcome
from agora.engine.state import WorldState
from agora.rules.binding import BindingSpec
from agora.rules.derive import duel
from agora.rules.encounter import Action, Encounter, Fighter, Policy, Status
from agora.rules.policy import StylePolicy
from agora.rules.simulator import account
from agora.rules.system import Ruleset

_FATE = {
    Status.ACTIVE: Fate.STANDING,
    Status.DOWN: Fate.DOWN,
    Status.DEAD: Fate.DEAD,
    Status.FLED: Fate.FLED,
    Status.SURRENDERED: Fate.SURRENDERED,
    Status.BROKEN: Fate.FLED,
}
"""Quien se quiebra (§11.3) sale de la escena: en el mundo, huye."""


@dataclass(frozen=True, slots=True)
class MixedPolicy:
    """El jugador decide por sí mismo; cada NPC, con su estilo (D-158)."""

    player: str
    player_policy: Policy
    npc_policy: Policy

    def _de(self, me: Fighter) -> Policy:
        return self.player_policy if me.id == self.player else self.npc_policy

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        return self._de(me).choose(encounter, me)

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        return self._de(me).resists(encounter, me, hit, outcome)

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        return self._de(me).finishes(encounter, me, fallen)

    def pursues(self, encounter: Encounter, me: Fighter, fleer: Fighter) -> bool:
        return self._de(me).pursues(encounter, me, fleer)


@dataclass(slots=True)
class WorldCombat:
    ruleset: Ruleset
    binding: BindingSpec
    player_policy: Policy
    report: Callable[[tuple[str, ...]], None] | None = None
    """A quién contarle el relato al acabar: la terminal, para que el jugador
    vea cómo terminó lo que vivió ronda a ronda."""

    def resolve(
        self, world: WorldState, attacker: AgentId, defender: AgentId,
        surprised: frozenset[AgentId],
    ) -> EncounterOutcome | None:
        if world.player is None:
            return None
        escenario = duel(world, attacker, defender, self.ruleset, self.binding)
        encuentro = Encounter(
            escenario, self.ruleset, world.rng,
            f"mundo:{world.tick}:{attacker}:{defender}",
            frozenset(str(s) for s in surprised),
        )
        politica = MixedPolicy(str(world.player), self.player_policy, StylePolicy())
        resultado = encuentro.run(politica)
        recursos = self.binding.resources
        desenlaces = []
        for r in resultado.fighters:
            f = encuentro.fighters[r.id]
            fate = _FATE[r.status]
            # Solo lo que la escena cambió: ida y vuelta por enteros (la salud
            # 0.83 entra como 15 de 18 y saldría 0.833) movería a quien no recibió
            # ni un golpe.
            necesidades: list[tuple[NeedId, float]] = []
            if fate is Fate.DOWN or r.vitality != f.spec.start_vitality:
                vida = 0.0 if fate is Fate.DOWN else r.vitality / f.spec.vitality
                necesidades.append((NeedId(recursos.vitality), vida))
            if recursos.fatigue is not None and r.fatigue != f.spec.start_fatigue:
                necesidades.append(
                    (NeedId(recursos.fatigue), max(0.0, 1.0 - r.fatigue / f.spec.fatigue))
                )
            desenlaces.append(CombatantOutcome(
                agent=AgentId(r.id), fate=fate, needs=tuple(necesidades),
                inflicts=recursos.down if fate is Fate.DOWN else None,
            ))
        relato = tuple(account(escenario, resultado))
        if self.report is not None:
            self.report(relato)
        return EncounterOutcome(combatants=tuple(desenlaces), rounds=resultado.rounds, lines=relato)
