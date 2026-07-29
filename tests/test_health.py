"""Cada pack del repositorio cumple lo que él mismo promete.

Es la red que faltaba. Los tests unitarios verifican que las piezas funcionan;
esto verifica que el MUNDO que sale de juntarlas sigue siendo el que se
pretendía. Sin él, cambiar un decay en un YAML puede romper una propiedad que
dábamos por buena y nadie se entera hasta leer un log de siete días.

Encontró su primer fallo en la primera ejecución: `dark_fantasy` se había
degradado en silencio mientras el motor evolucionaba.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agora.engine.ontology import ActionId
from agora.engine.pack import ContentPack, load_pack
from agora.health import HealthReport, check, measure

PACKS = sorted((Path(__file__).resolve().parents[1] / "packs").glob("*/pack.yaml"))


def ids(path: Path) -> str:
    return path.parent.name


@pytest.fixture(scope="module", params=PACKS, ids=ids)
def world(request: pytest.FixtureRequest) -> tuple[ContentPack, HealthReport]:
    """Medir cuesta ~1 s por pack, así que se hace una vez por módulo."""
    pack = load_pack(request.param)
    return pack, measure(pack)


def test_packs_exist() -> None:
    """Evita el falso verde: una batería que no encuentra packs siempre pasa."""
    assert PACKS


def test_the_pack_keeps_its_own_contract(world: tuple[ContentPack, HealthReport]) -> None:
    pack, report = world
    problemas = check(pack, report)
    assert not problemas, (
        f"el pack {pack.id!r} ya no cumple lo que declara:\n"
        + "\n".join(f"  - {p}" for p in problemas)
        + "\n\nmedido:\n"
        + "\n".join(report.lines())
    )


def test_nobody_ever_runs_out_of_options(world: tuple[ContentPack, HealthReport]) -> None:
    """Invariante universal: un mundo donde alguien se queda sin nada que hacer
    está roto se proponga lo que se proponga."""
    _, report = world
    assert report.stalls == 0


def test_needs_stay_within_bounds(world: tuple[ContentPack, HealthReport]) -> None:
    _, report = world
    assert not report.out_of_bounds


def test_everyone_does_something(world: tuple[ContentPack, HealthReport]) -> None:
    pack, report = world
    assert report.completed >= len(pack.agents)


# --- el propio medidor -------------------------------------------------------


def test_measuring_is_reproducible() -> None:
    """Si esto falla, el determinismo se rompió por algún sitio."""
    pack = load_pack(PACKS[0])
    assert measure(pack, days=2, seeds=(7,)) == measure(pack, days=2, seeds=(7,))


def test_check_reports_a_violated_band() -> None:
    """El contrato tiene que poder fallar, o no sirve de red."""
    pack = load_pack(PACKS[0])
    imposible = pack.model_copy(
        update={"health": pack.health.model_copy(update={"min_differentiation": 1.99})}
    )
    assert any("diferenciación" in p for p in check(imposible, measure(pack, days=2, seeds=(7,))))


def test_an_unused_action_is_reported_unless_declared() -> None:
    pack = load_pack(PACKS[0])
    report = measure(pack, days=2, seeds=(7,))
    sin_permiso = pack.model_copy(
        update={"health": pack.health.model_copy(update={"may_go_unused": frozenset()})}
    )
    if report.unused:
        assert any("nunca ocurren" in p for p in check(sin_permiso, report))


def test_a_pack_without_bands_only_faces_the_universal_invariants() -> None:
    """Un pack que no declara nada no puede fallar por calibración."""
    pack = load_pack(PACKS[0])
    desnudo = pack.model_copy(
        update={
            "health": pack.health.model_copy(
                update={
                    "min_crisis": None,
                    "max_crisis": None,
                    "max_abort_ratio": None,
                    "max_transit": None,
                    "min_differentiation": None,
                    "may_go_unused": frozenset(
                        ActionId(a.id) for a in pack.actions
                    ),
                }
            )
        }
    )
    assert check(desnudo, measure(pack, days=2, seeds=(7,))) == []
