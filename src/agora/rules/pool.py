"""Resolver una tirada con una reserva de dados de seis caras (unidad 08).

Es el modo progresivo del borrador 1 (D-156). Cuatro reglas que no se ven en
la firma y deciden mucho:

- El empate favorece a quien se opone: un margen de 0 es un fallo.
- Lo que pasa del tope no se tira: es excedente y sube el efecto. Un maestro no
  acierta más que un experto; logra más cuando acierta.
- Con la reserva a 0 o menos se tiran dos y se queda el peor. Es el azar
  acotado del borrador: nunca es imposible, ni siquiera sin dados.
- Los pasos de efecto se suman todos (contexto, escala, crítico, excedente) y
  se recortan a nulo AL FINAL. El borrador no dice el orden, y con limitado,
  dos tiers por encima y un crítico, recortar en cada paso da limitado y
  sumar da nulo. Sumar es lo único que no depende del orden (contrato 08, §3).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from agora.engine.ports import Challenge, Dice, Effect, Outcome, Resolution
from agora.rules.system import Ruleset

SUCCESS_FACE = 5
"""Desde qué cara un dado es un éxito: el 5 y el 6, uno de cada tres."""

FULL_MARGIN = 2
"""Desde qué margen un éxito deja de tener coste."""

CRITICAL_SIXES = 2
"""Cuántos seises de quien actúa convierten un éxito pleno en crítico."""

EMPTY_POOL_DICE = 2
"""Cuántos dados se tiran, quedándose el peor, cuando la reserva no llega a 1."""

NULL_TIER_GAP = 3
"""Desde cuántos tiers por encima el efecto es nulo pase lo que pase: ni un
crítico ni el excedente lo levantan. Por debajo de eso, cada tier baja un paso
y se puede compensar con preparación."""


@dataclass(frozen=True, slots=True)
class KeyedDice:
    """Dados de un flujo derivado por clave (`RngSource.stream`). La clave la
    pone quien tira; aquí solo se consume, como en el resto del motor."""

    rng: random.Random

    def roll(self, n: int) -> tuple[int, ...]:
        return tuple(self.rng.randint(1, 6) for _ in range(n))


def roll_pool(pool: int, cap: int, dice: Dice) -> tuple[tuple[int, ...], int, int]:
    """(dados, éxitos, seises). Con la reserva vacía no cuenta ningún seis: con
    el peor de dos no cabe más de un éxito, así que tampoco un crítico."""
    if pool <= 0:
        tirada = dice.roll(EMPTY_POOL_DICE)
        return tirada, int(min(tirada) >= SUCCESS_FACE), 0
    tirada = dice.roll(min(pool, cap))
    return tirada, sum(d >= SUCCESS_FACE for d in tirada), sum(d == 6 for d in tirada)


def outcome_of(margin: int, sixes: int) -> Outcome:
    """En una tirada simple el margen son los éxitos; en una enfrentada, los de
    quien actúa menos los de quien se opone. Los seises son siempre de quien
    actúa: defenderse no da críticos."""
    if margin <= 0:
        return Outcome.FAILURE
    if margin < FULL_MARGIN:
        return Outcome.SUCCESS_AT_COST
    if sixes >= CRITICAL_SIXES:
        return Outcome.CRITICAL
    return Outcome.SUCCESS


def scaled_effect(effect: int, tier_gap: int, critical: bool, overflow: int) -> int:
    """Un rival de tier más bajo no sube el efecto: contra él se lucha como
    contra un enemigo menor (§13 del borrador, unidad 09), no golpeando más."""
    if tier_gap >= NULL_TIER_GAP:
        return Effect.NONE
    return max(Effect.NONE, effect - max(0, tier_gap) + int(critical) + overflow)


@dataclass(frozen=True, slots=True)
class Resistance:
    dice: tuple[int, ...]
    successes: int
    effect: int
    """El efecto del golpe, un paso más bajo. Resistir siempre baja un paso; la
    tirada solo decide cuánto estrés cuesta."""
    stress: int


@dataclass(frozen=True, slots=True)
class PoolResolver:
    """El `RuleSystem` del modo progresivo. Sin estado: los topes salen del
    sistema y los dados, de quien llama."""

    cap: int = 6
    overflow_cap: int = 2
    resist_stress: int = 3

    @classmethod
    def from_ruleset(cls, ruleset: Ruleset) -> PoolResolver:
        return cls(
            cap=ruleset.pool.cap,
            overflow_cap=ruleset.pool.overflow_cap,
            resist_stress=ruleset.pool.resist_stress,
        )

    def resolve(self, challenge: Challenge, dice: Dice) -> Resolution:
        """Tira primero quien actúa y después quien se opone: un test que
        escribe los dados los escribe en ese orden."""
        tirada, exitos, seises = roll_pool(challenge.pool, self.cap, dice)
        contra: tuple[int, ...] = ()
        exitos_contra = 0
        if challenge.opposing_pool is not None:
            contra, exitos_contra, _ = roll_pool(challenge.opposing_pool, self.cap, dice)
        outcome = outcome_of(exitos - exitos_contra, seises)
        overflow = min(self.overflow_cap, max(0, challenge.pool - self.cap))
        critical = outcome is Outcome.CRITICAL
        effect = (
            Effect.NONE
            if outcome is Outcome.FAILURE
            else scaled_effect(challenge.effect, challenge.tier_gap, critical, overflow)
        )
        return Resolution(
            outcome=outcome,
            dice=tirada,
            opposing_dice=contra,
            successes=exitos,
            opposing_successes=exitos_contra,
            sixes=seises,
            overflow=overflow,
            effect=effect,
        )

    def resist(self, pool: int, effect: int, dice: Dice) -> Resistance:
        """Resistir un golpe ya acertado (§10.4). Que sea una vez por golpe lo
        vigila el encuentro (unidad 09), que es quien sabe qué golpe es."""
        tirada, exitos, _ = roll_pool(pool, self.cap, dice)
        return Resistance(
            dice=tirada,
            successes=exitos,
            effect=max(Effect.NONE, effect - 1),
            stress=max(0, self.resist_stress - exitos),
        )
