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

from agora.engine.ontology import ActionId, AgentId, PlaceId, SituationId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.world import Simulation
from agora.health import (
    DivergenceReport,
    HealthReport,
    _differentiation,
    check,
    divergence,
    measure,
)

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


# --- imprevistos: la línea base de la raíz 3 ---------------------------------


def test_a_world_can_have_things_happen_to_it(
    world: tuple[ContentPack, HealthReport],
) -> None:
    """Sustituye a `test_nothing_unexpected_happens_yet`, que afirmaba que a
    ningún mundo le pasaba nunca nada y **pedía por escrito que se le borrara**
    el día que los disparadores existieran de verdad. Ese día llegó: confluencia
    declara veinte eventuales y pasa el 61 % del tiempo con algo encendido.

    Lo que se comprueba ahora es lo único universal: que la fracción sea una
    fracción. Cuánto imprevisto es sano lo declara cada pack, no este test —
    `ciudad` y `aldea` siguen en 0.0 legítimamente.
    """
    _, report = world
    assert 0.0 <= report.eventful_time <= 1.0


def test_declared_eventual_situations_never_happen(
    world: tuple[ContentPack, HealthReport],
) -> None:
    """Tercer miembro de la familia de `unused` y `deserted`. La ciudad declara
    `ventisca` y `oleada`, y once acciones llevan multiplicadores para ellas.

    **Las personales quedan fuera, y este test lo daba por sentado al revés.** Una
    condición no aparece jamás en `state.situations` —vive pegada a quien la
    lleva, no al mundo— así que el panel la contaba como *nunca pasa* mientras
    treinta y ocho personas de confluencia iban sangrando por el mapa. El test
    afirmaba el bug: se escribió cuando no existían las condiciones y no había
    forma de distinguirlas.
    """
    pack, report = world
    eventuales = {s.id for s in pack.situations if not s.periodic and not s.personal}
    # Subconjunto y no igualdad: desde que los disparadores funcionan, algunas
    # SÍ ocurren. Lo que se sigue exigiendo es que el panel no invente ninguna
    # que el pack no declare — y que las personales queden fuera, porque una
    # condición nunca aparece en `state.situations`.
    assert report.never_happened <= eventuales


def test_a_situation_that_happens_is_not_reported_as_never() -> None:
    """El medidor tiene que poder ver una situación encendida, o el número de
    arriba seria un cero que no significa nada."""
    ciudad = next((p for p in PACKS if p.parent.name == "ciudad"), None)
    if ciudad is None:  # pragma: no cover - el repo lo trae
        pytest.skip("no está el pack de la ciudad")
    pack = load_pack(ciudad)
    sim = Simulation(pack, seed=7)
    sim.begin_situation(SituationId("ventisca"), ticks=50)
    sim.run(10)
    assert sim.state.situations, "la situación tendría que seguir encendida"


# --- divergencia entre semillas ----------------------------------------------


def test_divergence_needs_something_to_compare() -> None:
    """Con una semilla no hay con qué comparar, y devolver 0.0 sería mentir:
    diría 'mundo guionizado' cuando lo que pasa es que no se midió."""
    pack = load_pack(PACKS[0])
    with pytest.raises(ValueError, match="semillas"):
        divergence(pack, seeds=(7,), days=1)


def test_the_same_seed_twice_diverges_in_nothing() -> None:
    """Invariante duro: el mismo mundo con la misma semilla es el mismo mundo.
    Si esto falla, el determinismo se rompió."""
    pack = load_pack(PACKS[0])
    assert divergence(pack, seeds=(7, 7), days=2).lives == pytest.approx(0.0)


def test_different_seeds_diverge_somewhat() -> None:
    """Y el otro lado: si cambiar la moneda no cambia nada, el mundo está
    guionizado y el softmax no está haciendo su trabajo."""
    pack = load_pack(PACKS[0])
    assert divergence(pack, seeds=(7, 8, 9), days=3).lives > 0.0


def test_divergence_is_reproducible() -> None:
    pack = load_pack(PACKS[0])
    assert divergence(pack, seeds=(7, 8), days=2) == divergence(pack, seeds=(7, 8), days=2)


def test_character_still_outweighs_chance() -> None:
    """**El freno cuantitativo que el plan pedía y no tenía.**

    Medido antes de que existieran los disparadores, 7 días: aldea 0.29, barrio
    0.39, ciudad 0.41. El carácter manda por dos y medio a tres y medio. Si al
    encender los disparadores esto se acerca a 1, el mundo se volvió aleatorio.

    Se comprueba flojo —por debajo de 1— a propósito: la banda buena la dirá
    calibrar, y clavar aquí un umbral fino sería pelearse con ella.
    """
    barrio = next((p for p in PACKS if p.parent.name == "barrio"), None)
    if barrio is None:  # pragma: no cover - el repo lo trae
        pytest.skip("no está el pack del barrio")
    report = divergence(load_pack(barrio), seeds=(1312, 7, 99), days=3)
    assert 0.0 < report.ratio < 1.0


def test_the_ratio_survives_a_world_with_no_differentiation() -> None:
    """Dividir por la diferenciación es lo que hace legible el número, y también
    lo que puede dividir por cero. Un mundo de un solo agente no tiene con quién
    diferenciarse."""
    assert DivergenceReport(seeds=(1, 2), days=1, lives=0.5).ratio == 0.0


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
