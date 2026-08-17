"""Cada pack del repositorio cumple lo que él mismo promete.

Es la red que faltaba. Los tests unitarios verifican que las piezas funcionan;
esto verifica que el MUNDO que sale de juntarlas sigue siendo el que se
pretendía. Sin él, cambiar un decay en un YAML puede romper una propiedad que
dábamos por buena y nadie se entera hasta leer un log de siete días.

Encontró su primer fallo en la primera ejecución: `dark_fantasy` se había
degradado en silencio mientras el motor evolucionaba.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from agora.engine.ontology import ActionId, AgentId, PlaceId
from agora.engine.pack import ContentPack, load_pack
from agora.health import HealthReport, _differentiation, check, measure

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


# --- diferenciación geográfica -----------------------------------------------


def test_geography_uses_the_same_vara_as_activity() -> None:
    """Genérica en la clave a propósito: dos varas distintas para la misma
    pregunta divergirían, y comparar los dos números dejaría de significar nada.

    Se comprueba con la misma FORMA de datos en los dos ejes: si el número sale
    igual, la vara es una sola.
    """
    lugares = {
        AgentId("a"): Counter({PlaceId("p1"): 30, PlaceId("p2"): 10}),
        AgentId("b"): Counter({PlaceId("p1"): 10, PlaceId("p2"): 30}),
    }
    acciones = {
        AgentId("a"): Counter({ActionId("p1"): 30, ActionId("p2"): 10}),
        AgentId("b"): Counter({ActionId("p1"): 10, ActionId("p2"): 30}),
    }
    assert _differentiation(lugares) == pytest.approx(_differentiation(acciones))
    assert _differentiation(lugares) > 0.0


def test_everyone_in_the_same_place_is_a_dead_map() -> None:
    perfiles = {
        AgentId("a"): Counter({PlaceId("p1"): 100}),
        AgentId("b"): Counter({PlaceId("p1"): 100}),
    }
    assert _differentiation(perfiles) == pytest.approx(0.0)


def test_disjoint_places_reach_the_ceiling() -> None:
    perfiles = {
        AgentId("a"): Counter({PlaceId("p1"): 100}),
        AgentId("b"): Counter({PlaceId("p2"): 100}),
    }
    assert _differentiation(perfiles) == pytest.approx(2.0)


def test_geography_sees_what_activity_cannot() -> None:
    """**La razón de existir de la medida.** Dos agentes que hacen exactamente
    lo mismo en sitios distintos son idénticos en actividad y distintos aquí.

    Medido en el repositorio: `dark_fantasy` tiene diferenciación de actividad
    0.015 —dos agentes prácticamente iguales— y geográfica 0.688.
    """
    misma_actividad = {
        AgentId("a"): Counter({ActionId("x"): 50}),
        AgentId("b"): Counter({ActionId("x"): 50}),
    }
    distinto_sitio = {
        AgentId("a"): Counter({PlaceId("p1"): 50}),
        AgentId("b"): Counter({PlaceId("p2"): 50}),
    }
    assert _differentiation(misma_actividad) == pytest.approx(0.0)
    assert _differentiation(distinto_sitio) > 0.0


def test_every_pack_reports_a_geography(world: tuple[ContentPack, HealthReport]) -> None:
    _, report = world
    assert 0.0 <= report.geography <= 2.0


def test_a_populated_world_is_not_geographically_flat(
    world: tuple[ContentPack, HealthReport],
) -> None:
    """Un mapa donde todo el mundo ocupa igual los lugares es un mapa que no
    decide nada — el mismo diagnóstico que destapó el vínculo muerto, aplicado
    al espacio."""
    pack, report = world
    if len(pack.agents) > 1 and len(pack.places) > 1:
        assert report.geography > 0.0


def test_a_deserted_place_is_reported() -> None:
    """El gemelo geográfico de `unused`. Lo encontró en su primera corrida:
    `nucleo_sima` en la ciudad, donde no entra nadie en veintiún días."""
    ciudad = next((p for p in PACKS if p.parent.name == "ciudad"), None)
    if ciudad is None:  # pragma: no cover - el repo lo trae
        pytest.skip("no está el pack de la ciudad")
    report = measure(load_pack(ciudad), days=2, seeds=(7,))
    assert PlaceId("nucleo_sima") in report.deserted


def test_places_that_are_used_are_not_deserted(
    world: tuple[ContentPack, HealthReport],
) -> None:
    """Nadie puede estar desierto y ocupado a la vez: los agentes arrancan en
    algún sitio, así que al menos sus casas están habitadas."""
    pack, report = world
    arranques = {a.start_at for a in pack.agents}
    assert not (arranques & report.deserted)


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
