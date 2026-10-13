"""Engañar a alguien desde el mundo, con las reglas de la mesa (unidad 15b,
D-164).

Implementa `SocialResolver`, la costura del motor: el motor pregunta si una
mentira cuela y aquí se tira Porte contra Instinto + Alerta, o las competencias
que diga la sección `social` del sistema. La reserva de cada uno es el grado
del atributo de la competencia más su nivel, con la misma ficha derivada que
usa la pelea (`derive`), y los dados salen de un flujo por clave: la misma
mentira, en la misma conversación y la misma semilla, da el mismo resultado en
cualquier proceso.
"""

from __future__ import annotations

from dataclasses import dataclass

from agora.engine.ontology import AgentId
from agora.engine.ports import Challenge, Outcome
from agora.engine.state import WorldState
from agora.rules.binding import BindingSpec
from agora.rules.derive import derive
from agora.rules.pool import KeyedDice, PoolResolver
from agora.rules.system import Ruleset


@dataclass(frozen=True, slots=True)
class WorldSocial:
    ruleset: Ruleset
    binding: BindingSpec

    def pool(self, world: WorldState, who: AgentId, skill: str) -> int:
        """Grado del atributo de la competencia más el nivel de la competencia."""
        ficha = derive(world, who, self.ruleset, self.binding).combatant
        atributo = next(s.attribute for s in self.ruleset.skills if s.id == skill)
        return self.ruleset.grade(ficha.attributes[atributo]) + ficha.skills.get(skill, 0)

    def deceive(
        self, world: WorldState, liar: AgentId, listener: AgentId, key: str
    ) -> Outcome | None:
        social = self.ruleset.social
        if social is None:
            return None
        reto = Challenge(
            pool=self.pool(world, liar, social.deceive),
            opposing_pool=self.pool(world, listener, social.notice),
        )
        dados = KeyedDice(world.rng.stream("enganyo", key, liar, listener))
        return PoolResolver.from_ruleset(self.ruleset).resolve(reto, dados).outcome
