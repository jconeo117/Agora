"""El instrumento de la unidad 08: que la tabla de probabilidades del sistema
sea la que el sistema dice que es.

Es al resolutor lo que `--health` es al mundo. La tabla del borrador (§8.3) se
calculó a mano; si el código se separa de ella, los combates se desequilibran
sin que ningún ejemplo resuelto lo note, porque los ejemplos fijan los dados.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import comb

from agora.engine.ports import Challenge, Outcome
from agora.engine.rng import RngSource
from agora.rules.pool import (
    CRITICAL_SIXES,
    EMPTY_POOL_DICE,
    FULL_MARGIN,
    SUCCESS_FACE,
    KeyedDice,
    PoolResolver,
)

POOLS = (0, 1, 2, 3, 4, 5, 6)
"""Las reservas que se miden por defecto: de la vacía al tope del borrador."""


@dataclass(frozen=True, slots=True)
class PoolRow:
    pool: int
    any_success: float
    full_success: float
    critical: float
    expected_any: Fraction
    expected_full: Fraction
    expected_critical: Fraction

    def line(self) -> str:
        return (
            f"  {self.pool:>7}"
            f"   {self.any_success:6.1%} / {float(self.expected_any):6.1%}"
            f"   {self.full_success:6.1%} / {float(self.expected_full):6.1%}"
            f"   {self.critical:6.1%} / {float(self.expected_critical):6.1%}"
        )


def expected(pool: int, cap: int) -> tuple[Fraction, Fraction, Fraction]:
    """(al menos un éxito, pleno, crítico), exactos, de una tirada simple.

    El crítico es «al menos dos seises» a secas porque dos seises ya son dos
    éxitos: con `CRITICAL_SIXES >= FULL_MARGIN` el pleno va incluido."""
    exito = Fraction(7 - SUCCESS_FACE, 6)
    if pool <= 0:
        return exito**EMPTY_POOL_DICE, Fraction(0), Fraction(0)
    n = min(pool, cap)

    def al_menos(k: int, p: Fraction) -> Fraction:
        return 1 - sum((comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k)), Fraction(0))

    seis = Fraction(1, 6)
    return al_menos(1, exito), al_menos(FULL_MARGIN, exito), al_menos(CRITICAL_SIXES, seis)


def pool_table(
    resolver: PoolResolver, rolls: int, seed: int, pools: Sequence[int] = POOLS
) -> tuple[PoolRow, ...]:
    """Cada reserva tira de su propio flujo (`"montecarlo", reserva`): medir
    una reserva más no cambia lo que salió en las otras."""
    fuente = RngSource(seed)
    filas = []
    for pool in pools:
        dados = KeyedDice(fuente.stream("montecarlo", pool))
        cuenta = Counter(
            resolver.resolve(Challenge(pool=pool), dados).outcome for _ in range(rolls)
        )
        esperado_alguno, esperado_pleno, esperado_critico = expected(pool, resolver.cap)
        filas.append(
            PoolRow(
                pool=pool,
                any_success=1 - cuenta[Outcome.FAILURE] / rolls,
                full_success=(cuenta[Outcome.SUCCESS] + cuenta[Outcome.CRITICAL]) / rolls,
                critical=cuenta[Outcome.CRITICAL] / rolls,
                expected_any=esperado_alguno,
                expected_full=esperado_pleno,
                expected_critical=esperado_critico,
            )
        )
    return tuple(filas)
