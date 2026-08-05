"""Tests de los ejes de progresión.

Un eje que solo sube: nivel, experiencia, reputación, dominio de un arte.

La diferencia con una necesidad no es de grado sino de naturaleza. Estar a 0.1
de sustento es una emergencia; estar a 0.1 de experiencia es ser novato. Por eso
no basta con declarar una necesidad que no decae: **la progresión no puede
entrar en crisis**, o quien empieza abajo pasa toda su escalada bajo el umbral,
soltando lo que hiciera para ir a entrenar. Medido con una ganancia realista,
el tiempo en crisis del mundo pasa de 0 % a 27.7 %: de sobra para reventar el
contrato de un mundo sano.

Lo que SÍ conserva es la urgencia, y ahí está todo el mecanismo: `(1 - valor)^exp`
hace que crecer apremie mientras se es novato y deje de importar cerca del tope.
Querer volverse más fuerte no necesita un sistema de metas — la fórmula ya sabe
querer, y esto solo le da un eje donde hacerlo.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, critical_need, critical_needs
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, NeedSpec, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation
from agora.health import measure

EP = NeedId("ep")
SUSTENTO = NeedId("sustento")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
ENTRENAR = ActionId("entrenar")
COMER = ActionId("comer")
GESTA = ActionId("gesta")


def xp_pack(**overrides: Any) -> ContentPack:
    """Un eje que sube entrenando, y una gesta que exige haber crecido."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {
                "id": "sustento",
                "label": "sustento",
                "decay_per_tick": 0.01,
                "initial": 0.8,
                "urgency_exponent": 2.0,
            },
            {
                "id": "ep",
                "label": "experiencia",
                "decay_per_tick": 0.0,
                "progression": True,
                "initial": 0.05,
                "base_weight": 0.8,
                "urgency_exponent": 1.3,
            },
        ],
        "actions": [
            {
                "id": "entrenar",
                "label": "entrenar",
                "duration_ticks": 6,
                "satisfies": {"ep": 0.30},
                "effects": {"ep": 0.03},
            },
            {
                "id": "comer",
                "label": "comer",
                "duration_ticks": 3,
                "satisfies": {"sustento": 0.9},
                "effects": {"sustento": 0.9},
            },
            {
                "id": "gesta",
                "label": "gesta",
                "duration_ticks": 10,
                "requires_affordance": "renombre",
                "requires": {"ep": 0.45},
                "satisfies": {"ep": 0.5},
                "effects": {"ep": 0.05},
            },
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["renombre"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"critical_need_threshold": 0.15},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- un eje que no decae -----------------------------------------------------


def test_a_progression_axis_never_falls() -> None:
    pack = xp_pack()
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    for _ in range(500):
        agente.decay(pack.need_by_id)
    assert agente.needs[EP] == pytest.approx(0.05)


def test_a_plain_need_still_falls() -> None:
    """La relajación del validador no toca a nadie más."""
    pack = xp_pack()
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    agente.decay(pack.need_by_id)
    assert agente.needs[SUSTENTO] < 0.8


# --- ser novato no es una emergencia ----------------------------------------


def test_being_a_novice_is_not_a_crisis() -> None:
    """El punto entero. Con EP a 0.05 y el umbral en 0.15, sin esta guarda el
    agente estaría en emergencia permanente."""
    world = WorldState.new(xp_pack(), seed=1)
    agente = world.agents[AG1]
    assert agente.needs[EP] == 0.05
    assert EP not in critical_needs(world, agente)


def test_hunger_still_interrupts() -> None:
    """Excluir la progresión no puede desactivar el triaje de verdad."""
    world = WorldState.new(xp_pack(), seed=1)
    agente = world.agents[AG1]
    agente.needs[SUSTENTO] = 0.05
    assert critical_need(world, agente) == SUSTENTO


def test_a_novice_does_not_poison_the_health_contract() -> None:
    """La comparación directa, que es lo único que dice algo.

    Un `< 0.9` suelto no probaría nada; lo que hay que ver es la diferencia
    entre el mismo mundo con y sin la guarda. Y con una ganancia realista —lenta,
    que es el caso de verdad— la diferencia es de reventar contratos.
    """
    lento = xp_pack().model_dump()
    lento["actions"][0]["effects"]["ep"] = 0.004

    con_guarda = measure(ContentPack.model_validate(lento), days=7, seeds=(1,))
    lento["needs"][1]["progression"] = False
    sin_guarda = measure(ContentPack.model_validate(lento), days=7, seeds=(1,))

    assert con_guarda.crisis_time == 0.0
    assert sin_guarda.crisis_time > 0.25


# --- pero crecer sigue apeteciendo ------------------------------------------


def test_the_urge_to_grow_survives() -> None:
    """Pierde el poder de interrumpir, no el de atraer."""
    world = WorldState.new(xp_pack(), seed=1)
    agente = world.agents[AG1]
    assert any(d.action == ENTRENAR and d.utility > 0.0 for d in candidates(world, agente))


def test_growing_matters_less_once_grown() -> None:
    """`(1 - valor)^exp`: apremia siendo novato y se desinfla cerca del tope."""
    world = WorldState.new(xp_pack(), seed=1)
    agente = world.agents[AG1]

    novato = next(d for d in candidates(world, agente) if d.action == ENTRENAR).utility
    agente.needs[EP] = 0.95
    veterano = next(d for d in candidates(world, agente) if d.action == ENTRENAR).utility
    assert novato > veterano * 5


# --- se puede exigir haber crecido -------------------------------------------


def test_a_deed_is_locked_until_you_have_grown() -> None:
    world = WorldState.new(xp_pack(), seed=1)
    agente = world.agents[AG1]
    assert not any(d.action == GESTA for d in candidates(world, agente))
    agente.needs[EP] = 0.5
    assert any(d.action == GESTA for d in candidates(world, agente))


def test_a_run_unlocks_it_on_its_own() -> None:
    """Nadie escribió "entrena hasta 0.45": la urgencia lo empuja sola."""
    sim = Simulation(xp_pack(), seed=1)
    sim.run(600)
    gestas = [e for e in sim.log.of_kind(EventKind.ACTION_COMPLETED) if e.action == GESTA]
    assert gestas, "seiscientos ticks deberían bastar para llegar a la gesta"
    assert sim.state.agents[AG1].needs[EP] > 0.45


# --- coherencia --------------------------------------------------------------


def test_progression_rejects_decay() -> None:
    with pytest.raises(ValidationError, match="no significa nada"):
        NeedSpec(id=EP, label="ep", decay_per_tick=0.01, progression=True)


def test_progression_rejects_debt() -> None:
    """No se debe experiencia."""
    with pytest.raises(ValidationError, match="max_debt"):
        NeedSpec(id=EP, label="ep", decay_per_tick=0.0, progression=True, max_debt=1.0)


def test_progression_rejects_strain() -> None:
    """Ser novato no nubla el juicio."""
    with pytest.raises(ValidationError, match="strain_weight"):
        NeedSpec(id=EP, label="ep", decay_per_tick=0.0, progression=True, strain_weight=1.0)


def test_progression_rejects_company_relief() -> None:
    """No se sube de nivel por estar acompañado."""
    with pytest.raises(ValidationError, match="company_relief"):
        NeedSpec(id=EP, label="ep", decay_per_tick=0.0, progression=True, company_relief=0.01)


def test_all_the_offenders_are_reported_at_once() -> None:
    with pytest.raises(ValidationError, match="company_relief, decay_per_tick"):
        NeedSpec(
            id=EP,
            label="ep",
            decay_per_tick=0.01,
            progression=True,
            company_relief=0.01,
        )


def test_a_plain_need_may_still_be_static() -> None:
    """Decaimiento 0 sin `progression` sigue valiendo: es un eje que solo cambia
    por lo que se hace y que SÍ puede ser una emergencia."""
    assert NeedSpec(id=SUSTENTO, label="s", decay_per_tick=0.0).decay_per_tick == 0.0
