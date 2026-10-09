"""El estilo de combate como política (unidad 09, D-158).

Un NPC no pelea con una táctica: pelea como es. Las cinco perillas de
`CombatStyle` deciden cada turno con una regla corta y en un orden fijo, para
que quien mire el relato pueda decir por qué hizo lo que hizo. El orden es el
contrato:

1. Por debajo de su umbral, se va: huye, o se rinde si está exhausto.
2. El capricho: con probabilidad `whim`, cualquier acción legal.
3. Remata a quien quiera rematar.
4. Si no es agresivo (menos de 50): socorre a un aliado caído, recupera el
   aliento si está exhausto y se cubre si está grave.
5. Ataca a quien su perilla diga, y se fuerza si es muy agresivo (70 o más) y
   aún no está cansado.

Resistir no es una perilla: resiste un crítico, o un golpe que lo dejaría
grave o caído, si el estrés le da para el peor caso sin quebrarse.
"""

from __future__ import annotations

from dataclasses import dataclass

from agora.engine.ports import Outcome
from agora.rules.damage import VitalityBand, vitality_band
from agora.rules.encounter import Action, ActionKind, Encounter, Fighter, Status
from agora.rules.scene import FinishOff, TargetChoice

AGGRESSIVE = 50
"""Desde aquí no se protege, no socorre ni descansa mientras pueda pelear."""

RECKLESS = 70
"""Desde aquí se fuerza en cada ataque mientras no esté cansado."""


@dataclass(frozen=True, slots=True)
class StylePolicy:
    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        estilo = me.spec.style
        legales = encounter.legal_actions(me)
        if len(legales) == 1:
            return legales[0]
        if me.vitality * 100 < me.spec.vitality * estilo.flee_below:
            return Action(ActionKind.SURRENDER if encounter.exhausted(me) else ActionKind.FLEE)
        if estilo.whim:
            azar = encounter.style_rng(me)
            if azar.randint(1, 100) <= estilo.whim:
                return azar.choice(legales)
        for accion in legales:
            if (
                accion.kind is ActionKind.FINISH
                and accion.target is not None
                and self.finishes(encounter, me, encounter.fighters[accion.target])
            ):
                return accion
        if estilo.aggression < AGGRESSIVE:
            socorrer = [a for a in legales if a.kind is ActionKind.FIRST_AID]
            if socorrer:
                return socorrer[0]
            if encounter.exhausted(me):
                return Action(ActionKind.RECOVER)
            if encounter.band(me) is VitalityBand.GRAVE:
                return Action(ActionKind.TOTAL_DEFENSE)
        forzar = estilo.aggression >= RECKLESS and not encounter.tired(me)
        return Action(ActionKind.ATTACK, self._target(encounter, me), forzar)

    def _target(self, encounter: Encounter, me: Fighter) -> str:
        rivales = [o for o in encounter.enemies(me) if o.status is Status.ACTIVE]

        def debil(o: Fighter) -> tuple[int, str]:
            return (o.vitality * 100 // o.spec.vitality, o.id)

        match me.spec.style.target:
            case TargetChoice.WEAKEST:
                return min(rivales, key=debil).id
            case TargetChoice.STRONGEST:
                return min(rivales, key=lambda o: (-o.spec.tier, -o.vitality, o.id)).id
            case TargetChoice.HATED:
                return min(rivales, key=lambda o: (me.spec.regard.get(o.id, 0), *debil(o))).id

    def resists(self, encounter: Encounter, me: Fighter, hit: int, outcome: Outcome) -> bool:
        if me.stress + encounter.resolver.resist_stress >= me.spec.stress:
            return False
        despues = vitality_band(me.vitality - hit, me.spec.vitality, encounter.ruleset.vitality)
        return outcome is Outcome.CRITICAL or despues in (VitalityBand.GRAVE, VitalityBand.DOWN)

    def finishes(self, encounter: Encounter, me: Fighter, fallen: Fighter) -> bool:
        match me.spec.style.finish_off:
            case FinishOff.NEVER:
                return False
            case FinishOff.ALWAYS:
                return True
            case FinishOff.HATED:
                return me.spec.regard.get(fallen.id, 0) < 0
