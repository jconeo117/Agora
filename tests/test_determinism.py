"""El test que protege todo lo demás.

Mismo seed, mismo log byte a byte. Sin esto, un fallo raro en el día 5 no se
puede investigar: no hay forma de volver a producirlo. Todas las decisiones de
orden fijo repartidas por el motor (agentes en orden de pack, desempates por
id, `sorted` antes de emitir eventos) existen para que este test pase.

Corre contra el pack REAL, no contra uno de juguete: es el único que ejercita
el motor entero, con viajes de varios tramos, interrupciones y encuentros.
"""

from __future__ import annotations

import os
import subprocess
import sys
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


HIJO = """
import hashlib, sys, tempfile
from pathlib import Path
from agora.engine.ontology import AgentId
from agora.engine.pack import load_pack
from agora.engine.world import Simulation
pack = load_pack(Path(sys.argv[1]))
sim = Simulation(pack, seed=1312)
if len(sys.argv) > 2:
    sim.state.focus = AgentId(sys.argv[2])
sim.run(pack.clock.ticks_per_day)
huella_log = hashlib.md5("\\n".join(sim.log.to_jsonl()).encode()).hexdigest()
with tempfile.TemporaryDirectory() as d:
    sim.save(Path(d) / "s.json")
    huella_guardado = hashlib.md5((Path(d) / "s.json").read_bytes()).hexdigest()
print(huella_log, huella_guardado)
"""


def test_la_misma_semilla_da_el_mismo_mundo_en_otro_proceso() -> None:
    """Lo que el test de arriba no puede ver: dentro de un proceso, dos corridas
    comparten la semilla de hash, así que un `set` recorrido sin ordenar sale
    igual en las dos. Entre procesos con `PYTHONHASHSEED` distinto, no. Corre
    sobre `confluencia` porque `dark_fantasy` es demasiado pequeño para que
    el desorden se note (medido: quitar el `sorted` de los encuentros no
    cambiaba ni un evento)."""
    pack = Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml"
    huellas = [
        subprocess.run(
            [sys.executable, "-c", HIJO, str(pack)],
            env={**os.environ, "PYTHONHASHSEED": semilla},
            capture_output=True, text=True, check=True,
        ).stdout
        for semilla in ("0", "1")
    ]
    assert huellas[0] == huellas[1]


def test_el_mismo_foco_da_el_mismo_mundo_en_otro_proceso() -> None:
    """D-141 con foco: misma semilla y mismo foco dan el mismo mundo byte a
    byte en otro proceso con distinto PYTHONHASHSEED. Corre sobre
    `confluencia` con foco en `eris_cenizal`."""
    pack = Path(__file__).resolve().parents[1] / "packs" / "confluencia" / "pack.yaml"
    huellas = [
        subprocess.run(
            [sys.executable, "-c", HIJO, str(pack), "eris_cenizal"],
            env={**os.environ, "PYTHONHASHSEED": semilla},
            capture_output=True, text=True, check=True,
        ).stdout
        for semilla in ("0", "1")
    ]
    assert huellas[0] == huellas[1]

