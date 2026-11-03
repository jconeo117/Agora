"""Tests para la isla: sesgo del desempate y la fuerza (I-007, I-008)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from agora.engine.ontology import ActionId, AgentId, NeedId, TraitId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.world import Simulation


@pytest.fixture(scope="module")
def pack_isla() -> ContentPack:
    return load_pack(Path(__file__).resolve().parents[1] / "packs" / "isla" / "pack.yaml")


@pytest.fixture(scope="module")
def corrida_isla(pack_isla: ContentPack) -> dict[int, set[AgentId]]:
    """Corre la simulación de la isla hasta el día 5 en la semilla 1312
    y guarda los vivos en los cortes de interés (día 4 y día 5). El corte tardío
    era el día 9 hasta que la calibración acabó la partida el día 7: ya no queda
    nadie a quien comparar.
    """
    sim = Simulation(pack_isla, seed=1312)
    cortes: dict[int, set[AgentId]] = {}
    for dia in range(1, 6):
        sim.run(pack_isla.clock.ticks_per_day)
        if dia in (4, 5):
            cortes[dia] = set(sim.state.agents.keys())
    return cortes


def test_la_isla_carga_y_es_reproducible(pack_isla: ContentPack) -> None:
    """El generador da el pack.yaml del repositorio byte a byte."""
    ruta_generar = Path(__file__).resolve().parents[1] / "packs" / "isla" / "generar.py"
    spec = importlib.util.spec_from_file_location("generar_isla", ruta_generar)
    assert spec is not None and spec.loader is not None
    generar = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generar)

    texto_cabecera = (
        "# Generado por packs/isla/generar.py. No se edita a mano: se cambia el\n"
        "# generador y se vuelve a correr. Ver el docstring del generador.\n"
    )
    contenido_esperado = texto_cabecera + yaml.safe_dump(
        generar.pack(), allow_unicode=True, sort_keys=False, width=110
    )

    ruta_yaml = Path(__file__).resolve().parents[1] / "packs" / "isla" / "pack.yaml"
    assert ruta_yaml.read_text(encoding="utf-8") == contenido_esperado
    assert pack_isla.id == "isla"
    assert len(pack_isla.agents) == 300


def test_el_alfabeto_no_decide(
    pack_isla: ContentPack, corrida_isla: dict[int, set[AgentId]]
) -> None:
    """A día 4 en la semilla 1312, ninguna mitad del alfabeto tiene menos
    del 55 % de los vivos de la otra (I-007; 57 % tras introducir objetos en 16a).
    """
    todos_los_agentes = sorted(a.id for a in pack_isla.agents)
    corte_medio = len(todos_los_agentes) // 2
    mitad_a = set(todos_los_agentes[:corte_medio])
    mitad_b = set(todos_los_agentes[corte_medio:])

    vivos_dia_4 = corrida_isla[4]
    vivos_a = len(vivos_dia_4 & mitad_a)
    vivos_b = len(vivos_dia_4 & mitad_b)

    assert vivos_a > 0 and vivos_b > 0
    ratio = min(vivos_a, vivos_b) / max(vivos_a, vivos_b)
    assert ratio >= 0.55, (
        f"Sesgo alfabético a día 4: mitad A={vivos_a}, mitad B={vivos_b}, ratio={ratio:.2f} < 0.55"
    )


def test_la_fuerza_pesa(
    pack_isla: ContentPack, corrida_isla: dict[int, set[AgentId]]
) -> None:
    """A día 5 en la semilla 1312, el cuartil más fuerte tiene más vivos que
    el más débil (I-008). Además, la acción de atacar declara quita_por_pericia (M10).
    """
    accion_atacar = pack_isla.action_by_id[ActionId("atacar")]
    assert accion_atacar.target is not None
    assert accion_atacar.target.quita_por_pericia == NeedId("combate")

    fuerzas = {a.id: a.traits.get(TraitId("fuerza"), 0.0) for a in pack_isla.agents}
    por_fuerza = sorted(fuerzas, key=lambda aid: (fuerzas[aid], aid))
    tamano_cuartil = len(por_fuerza) // 4
    q0_debil = set(por_fuerza[:tamano_cuartil])
    q3_fuerte = set(por_fuerza[3 * tamano_cuartil:])

    vivos_dia_5 = corrida_isla[5]
    vivos_q0 = len(vivos_dia_5 & q0_debil)
    vivos_q3 = len(vivos_dia_5 & q3_fuerte)

    assert vivos_q3 > vivos_q0, (
        f"A día 5 el cuartil más fuerte ({vivos_q3}) no supera al más débil ({vivos_q0})"
    )
