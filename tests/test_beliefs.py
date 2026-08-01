"""Tests de expectativas aprendidas.

Sin esto, `satisfies` es una constante del pack idéntica para todos, y ningún
NPC puede equivocarse sobre el mundo. Con esto, dos agentes con la misma ficha
esperan cosas distintas de lo mismo porque han vivido cosas distintas.

Nota sobre el orden de construcción: el mecanismo exige que el mundo tenga
varianza. Con `effects` constantes, lo prometido y lo recibido coinciden siempre
y no hay nada que aprender. La varianza la aporta la compañía.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import benefit, candidates
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.outcome import company_saturation, contextual_effects, learn
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation

VINCULO = NeedId("vinculo_test")
OTRA = NeedId("otra")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
SOCIAL = ActionId("act_social")


def social_data() -> dict[str, Any]:
    """`act_social` da más cuanta más gente haya."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        # Arrancan con hueco: hace falta margen bajo el techo para que haya algo
        # que aprender, y presión para que el agente actúe.
        "needs": [
            {"id": "vinculo_test", "label": "v", "decay_per_tick": 0.01, "initial": 0.3},
            {"id": "otra", "label": "o", "decay_per_tick": 0.01, "initial": 0.3},
        ],
        "actions": [
            {
                "id": "act_social",
                "label": "act_social",
                "duration_ticks": 2,
                "satisfies": {"vinculo_test": 1.0},
                "effects": {"vinculo_test": 0.20, "otra": 0.05},
                "effects_per_company": {"vinculo_test": 0.40},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {"learning_rate": 0.5, "critical_need_threshold": 0.0},
    }
    return data


def social_pack(**overrides: Any) -> ContentPack:
    data = social_data()
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- la varianza del mundo ---------------------------------------------------


def test_company_saturates() -> None:
    assert company_saturation(0) == 0.0
    assert company_saturation(1) == pytest.approx(0.5)
    assert company_saturation(3) == pytest.approx(0.75)
    assert company_saturation(999) < 1.0


def test_alone_the_effect_is_the_bare_one() -> None:
    action = social_pack().action_by_id[SOCIAL]
    assert contextual_effects(action, company=0)[VINCULO] == pytest.approx(0.20)


def test_company_raises_the_effect() -> None:
    action = social_pack().action_by_id[SOCIAL]
    assert contextual_effects(action, company=1)[VINCULO] == pytest.approx(0.40)
    assert contextual_effects(action, company=3)[VINCULO] == pytest.approx(0.50)


def test_an_action_without_company_scaling_is_untouched() -> None:
    """Sin varianza declarada, pasar por aquí no cambia nada."""
    action = social_pack().action_by_id[ActionId("act_libre")]
    assert contextual_effects(action, company=99) == dict(action.effects)


# --- el aprendizaje ----------------------------------------------------------


def learn_once(received: float, before: float = 0.0, rate: float = 0.5) -> float:
    ganancias: dict[NeedId, float] = {}
    learn(
        ganancias,
        {},
        social_pack().action_by_id[SOCIAL],
        {VINCULO: received},
        {VINCULO: before, OTRA: before},
        rate,
    )
    return ganancias.get(VINCULO, 1.0)


def test_getting_exactly_what_was_promised_keeps_the_belief() -> None:
    assert learn_once(received=0.20) == pytest.approx(1.0)


def test_getting_more_than_promised_raises_the_belief() -> None:
    assert learn_once(received=0.40) > 1.0


def test_getting_less_than_promised_lowers_the_belief() -> None:
    assert learn_once(received=0.10) < 1.0


def test_learning_is_gradual() -> None:
    """Con alfa 0.5, la creencia recorre la mitad del camino cada vez."""
    assert learn_once(received=0.40, rate=0.5) == pytest.approx(1.5)
    assert learn_once(received=0.40, rate=0.1) == pytest.approx(1.1)


def test_rate_zero_disables_learning() -> None:
    assert learn_once(received=0.40, rate=0.0) == 1.0


def test_nothing_is_learned_when_the_ceiling_cut_the_effect() -> None:
    """Que te recorten la comida por estar lleno no dice nada sobre la comida.

    Sin esta guarda, un agente que come estando saciado concluiría que comer no
    sirve — justo por haber comido bien.
    """
    assert learn_once(received=0.05, before=0.95) == 1.0


def test_side_effects_teach_nothing() -> None:
    """Trabajar sube el vínculo de rebote, pero no se fue a trabajar por eso.

    Solo se actualiza lo que aparece en `satisfies`: la expectativa es sobre lo
    que se perseguía, no sobre lo que salió de propina.
    """
    ganancias: dict[NeedId, float] = {}
    learn(
        ganancias,
        {},
        social_pack().action_by_id[SOCIAL],
        {VINCULO: 0.20, OTRA: 0.90},
        {VINCULO: 0.0, OTRA: 0.0},
        rate=0.5,
    )
    assert OTRA not in ganancias


# --- el precio también se aprende --------------------------------------------


def costly_pack() -> ContentPack:
    """`act_cara` cuesta y el precio sube con la compañía."""
    data = social_data()
    data["needs"].append(
        {"id": "dinero_t", "label": "d", "decay_per_tick": 0.001, "initial": 0.9}
    )
    data["actions"].append(
        {
            "id": "act_cara",
            "label": "act_cara",
            "duration_ticks": 2,
            "satisfies": {"vinculo_test": 1.0},
            "costs": {"dinero_t": 0.5},
            "effects": {"vinculo_test": 0.20, "dinero_t": -0.10},
            "effects_per_company": {"dinero_t": -0.20},
        }
    )
    return ContentPack.model_validate(data)


DINERO = NeedId("dinero_t")
CARA = ActionId("act_cara")


def learn_price(spent: float, before: float = 0.9, rate: float = 0.5) -> float:
    precios: dict[NeedId, float] = {}
    learn(
        {},
        precios,
        costly_pack().action_by_id[CARA],
        {DINERO: -spent},
        {VINCULO: 0.3, DINERO: before},
        rate,
    )
    return precios.get(DINERO, 1.0)


def test_paying_what_was_expected_keeps_the_price_belief() -> None:
    assert learn_price(spent=0.10) == pytest.approx(1.0)


def test_paying_more_than_expected_raises_the_price_belief() -> None:
    """Descubrir que algo sale caro es tan capaz de cambiar una rutina como
    descubrir que rinde poco."""
    assert learn_price(spent=0.30) > 1.0


def test_nothing_is_learned_when_the_floor_cut_the_spending() -> None:
    """Espejo por abajo de la guarda del techo: si te quedan 0.05 y algo cuesta
    0.10, gastas 0.05 y concluirías que es barato."""
    assert learn_price(spent=0.05, before=0.05) == 1.0


def test_gains_and_prices_live_in_separate_stores() -> None:
    """Una necesidad puede estar a los dos lados de la misma acción; con un solo
    diccionario, las dos creencias se pisarían."""
    ganancias: dict[NeedId, float] = {}
    precios: dict[NeedId, float] = {}
    learn(
        ganancias,
        precios,
        costly_pack().action_by_id[CARA],
        {VINCULO: 0.40, DINERO: -0.30},
        {VINCULO: 0.3, DINERO: 0.9},
        rate=0.5,
    )
    assert ganancias[VINCULO] > 1.0
    assert precios[DINERO] > 1.0
    assert DINERO not in ganancias and VINCULO not in precios


def test_a_learned_price_lowers_the_utility() -> None:
    """El precio aprendido entra en la decisión, no solo en la contabilidad."""
    world = WorldState.new(costly_pack(), seed=1)
    agent = world.agents[AG1]
    agent.needs[VINCULO] = 0.3
    agent.needs[DINERO] = 0.4

    def utility() -> float:
        return next(d for d in candidates(world, agent) if d.action == CARA).utility

    ingenuo = utility()
    agent.cost_beliefs[CARA] = {DINERO: 2.0}
    assert utility() < ingenuo


def test_the_price_is_learned_over_a_real_run() -> None:
    sim = Simulation(costly_pack(), seed=1)
    sim.run(400)

    aprendido = [
        agent.cost_beliefs.get(CARA, {}).get(DINERO)
        for agent in sim.state.agents_in_order()
    ]
    assert any(v is not None and v > 1.0 for v in aprendido), (
        f"nadie aprendió que sale más caro acompañado: {aprendido}"
    )


# --- efecto en la decisión ---------------------------------------------------


def test_the_belief_scales_what_the_agent_expects() -> None:
    world = WorldState.new(social_pack(), seed=1)
    pack, agent = world.pack, world.agents[AG1]
    agent.needs[VINCULO] = 0.3
    action = pack.action_by_id[SOCIAL]

    ingenuo = benefit(pack, agent, action, agent.need_weights)
    agent.gain_beliefs[SOCIAL] = {VINCULO: 1.5}
    assert benefit(pack, agent, action, agent.need_weights) == pytest.approx(ingenuo * 1.5)


def test_an_agent_with_no_experience_trusts_the_pack() -> None:
    world = WorldState.new(social_pack(), seed=1)
    assert world.agents[AG1].gain_beliefs == {}


# --- integración: las creencias divergen -------------------------------------


def together_pack() -> ContentPack:
    """Los dos agentes arrancan juntos, así que la acción social rinde de más.

    `act_solo` da y promete lo mismo siempre: es el control.
    """
    data = social_data()
    data["agents"] = [
        {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
        {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1"},
    ]
    data["actions"].append(
        {
            "id": "act_solo",
            "label": "act_solo",
            "duration_ticks": 2,
            "satisfies": {"otra": 1.0},
            "effects": {"otra": 0.30},
        }
    )
    return ContentPack.model_validate(data)


def test_experience_moves_the_expectation_over_a_real_run() -> None:
    """En una corrida de verdad, no forzando el estado a mano."""
    sim = Simulation(together_pack(), seed=1)
    sim.run(300)

    aprendido = sim.state.agents[AG1].gain_beliefs.get(SOCIAL, {}).get(VINCULO, 1.0)
    assert aprendido > 1.05, "acompañado recibe más de lo prometido y debería notarlo"


def test_an_action_without_variance_never_moves_its_expectation() -> None:
    """Sin sorpresas no hay nada que aprender, y el mecanismo no inventa ruido.

    Es la mitad honesta del asunto: el aprendizaje solo existe donde el mundo
    da resultados que dependen del contexto.
    """
    sim = Simulation(together_pack(), seed=1)
    sim.run(300)

    for agent in sim.state.agents_in_order():
        control = agent.gain_beliefs.get(ActionId("act_solo"), {})
        assert all(value == pytest.approx(1.0) for value in control.values())


def test_a_shared_life_produces_a_shared_expectation() -> None:
    """Dos agentes que viven siempre juntos acaban creyendo lo mismo.

    No es un fallo, es el control del test siguiente: la divergencia viene de
    vivir distinto, no del mecanismo por sí solo.
    """
    sim = Simulation(together_pack(), seed=1)
    sim.run(300)

    creencias = [
        agent.gain_beliefs.get(SOCIAL, {}).get(VINCULO, 1.0)
        for agent in sim.state.agents_in_order()
    ]
    assert creencias[0] == pytest.approx(creencias[1])


def test_living_alone_or_accompanied_produces_different_expectations() -> None:
    """Misma ficha, vidas distintas, expectativas distintas.

    Quien siempre actúa acompañado acaba esperando más de lo que el pack promete;
    quien lo hace solo recibe exactamente lo prometido y no aprende nada. Nadie
    escribió esa diferencia: sale de la varianza del mundo.
    """
    acompanado = Simulation(together_pack(), seed=1)
    acompanado.run(300)

    data = social_data()
    data["agents"] = [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}]
    solo = Simulation(ContentPack.model_validate(data), seed=1)
    solo.run(300)

    con = acompanado.state.agents[AG1].gain_beliefs.get(SOCIAL, {}).get(VINCULO, 1.0)
    sin = solo.state.agents[AG1].gain_beliefs.get(SOCIAL, {}).get(VINCULO, 1.0)

    assert con > 1.05, "acompañado recibe más de lo prometido y debería notarlo"
    assert sin == pytest.approx(1.0), "solo recibe exactamente lo dicho: nada que aprender"
