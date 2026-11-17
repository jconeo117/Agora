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
from agora.engine.ports import Challenge, Contest
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

    def _label(self, skill: str) -> str:
        """«Porte» lo tira quien miente; «Instinto + Alerta» quien nota, con el
        atributo por el que tira delante de la competencia."""
        spec = next(s for s in self.ruleset.skills if s.id == skill)
        return spec.label

    def _opposing_label(self, skill: str) -> str:
        spec = next(s for s in self.ruleset.skills if s.id == skill)
        atributo = next(a.label for a in self.ruleset.attributes if a.id == spec.attribute)
        return f"{atributo} + {spec.label}"

    def deceive(
        self, world: WorldState, liar: AgentId, listener: AgentId, key: str
    ) -> Contest | None:
        social = self.ruleset.social
        if social is None:
            return None
        reto = Challenge(
            pool=self.pool(world, liar, social.deceive),
            opposing_pool=self.pool(world, listener, social.notice),
        )
        dados = KeyedDice(world.rng.stream("enganyo", key, liar, listener))
        resolucion = PoolResolver.from_ruleset(self.ruleset).resolve(reto, dados)
        return Contest(resolucion, self._label(social.deceive),
                       self._opposing_label(social.notice))

    def contest(
        self, world: WorldState, actor: AgentId, rival: AgentId | None, prueba: str, key: str,
    ) -> Contest | None:
        """Una prueba del pack con las competencias que el enlace le asigna (23a, A.4). Sin
        enlace para esa prueba, `None`: la regla de respaldo del motor la resuelve."""
        enlace = self.binding.pruebas.get(prueba)
        if enlace is None:
            return None
        contra = enlace.contra if rival is not None else None
        reto = Challenge(
            pool=self.pool(world, actor, enlace.tira),
            opposing_pool=None if contra is None or rival is None
            else self.pool(world, rival, contra),
        )
        dados = KeyedDice(world.rng.stream("prueba", key, actor, "" if rival is None else rival))
        resolucion = PoolResolver.from_ruleset(self.ruleset).resolve(reto, dados)
        return Contest(
            resolucion,
            self._label(enlace.tira),
            "" if contra is None else self._opposing_label(contra),
        )
