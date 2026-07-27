"""El test que protege todo lo demás.

Mismo seed, mismo log byte a byte. Sin esto, un fallo raro en el día 5 no se
puede investigar: no hay forma de volver a producirlo. Todas las decisiones de
orden fijo repartidas por el motor (agentes en orden de pack, desempates por
id, `sorted` antes de emitir eventos) existen para que este test pase.

Corre contra el pack REAL, no contra uno de juguete: es el único que ejercita
el motor entero, con viajes de varios tramos, interrupciones y encuentros.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agora.engine.pack import ContentPack, load_pack
from agora.engine.world import Simulation

DAYS = 7


@pytest.fixture(scope="module")
def pack() -> ContentPack:
    root = Path(__file__).resolve().parents[1]
    return load_pack(root / "packs" / "dark_fantasy" / "pack.yaml")


def run(pack: ContentPack, seed: int, days: int = DAYS) -> list[str]:
    sim = Simulation(pack, seed=seed)
    sim.run(days * pack.clock.ticks_per_day)
    return list(sim.log.to_jsonl())


def test_same_seed_produces_an_identical_log(pack: ContentPack) -> None:
    assert run(pack, seed=1312) == run(pack, seed=1312)


def test_different_seeds_diverge(pack: ContentPack) -> None:
    """Si esto falla, el RNG no está influyendo en nada y el softmax es
    decorativo."""
    assert run(pack, seed=1) != run(pack, seed=2)


def test_a_full_week_produces_activity(pack: ContentPack) -> None:
    sim = Simulation(pack, seed=1312)
    sim.run(DAYS * pack.clock.ticks_per_day)
    assert len(sim.log) > 100


def test_a_full_week_runs_fast(pack: ContentPack) -> None:
    """Criterio de F0: una semana simulada en menos de un segundo. El motor
    tiene que ser barato para que calibrar sea un ciclo corto."""
    import time

    start = time.perf_counter()
    Simulation(pack, seed=1312).run(DAYS * pack.clock.ticks_per_day)
    assert time.perf_counter() - start < 1.0
