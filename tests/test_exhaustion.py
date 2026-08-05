"""Tests de duración elástica, deuda y acciones inabandonables.

Tres mecanismos que se necesitan mutuamente, y por eso están en un solo archivo.

**Elasticidad.** El modelo por defecto trata dormir como una transacción, y
dormir es una acumulación. Se notaba en dos sitios: quien está poco cansado
tenía que comprometer las ocho horas enteras o nada, y a quien lo levantaban a
falta de un tick se quedaba sin absolutamente nada.

**Deuda.** El motor no sabía estar peor que vacío. Un guerrero que pelea tres
días y alguien que durmió mal una noche estaban los dos en 0.0 y eran
indistinguibles: el suelo recortaba y la información se perdía.

**Inabandonable.** Es lo que hace posible lo anterior. Mientras todo se pueda
soltar, un agente se autolimita y nunca llega al agotamiento extremo — la
necesidad no llega a hundirse y no hay nada que acumular. Nadie deja una batalla
a la mitad para echar una cabezada.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import planned_duration, recovery_rate
from agora.engine.ontology import ActionId, AgentId, NeedId, NeedSpec, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, WorldState
from agora.engine.world import Simulation

DESCANSO = NeedId("descanso")
AG1 = AgentId("ag1")
CAMA = PlaceId("cama")
SUELO = PlaceId("suelo")
CAMPO = PlaceId("campo")
DORMIR = ActionId("dormir")
BATALLA = ActionId("batalla")


def rest_pack(**overrides: Any) -> ContentPack:
    """Una cama buena, un suelo malo, y una batalla de la que no se sale.

    Los números son los de la aldea: decaimiento 0.007 y ritmo 0.033, para que
    la aritmética del guerrero salga en horas reconocibles.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "clock": {"minutes_per_tick": 15, "ticks_per_day": 96},
        "needs": [
            {
                "id": "descanso",
                "label": "descanso",
                "decay_per_tick": 0.007,
                "initial": 1.0,
                "max_debt": 1.0,
            }
        ],
        "traits": [
            {
                "id": "sueno_pesado",
                "label": "sueno pesado",
                "gain_multipliers": {"descanso": 2.0},
            }
        ],
        "actions": [
            {
                "id": "dormir",
                "label": "dormir",
                "duration_ticks": 64,
                "requires_affordance": "lecho",
                "elastic": {"need": "descanso", "per_tick": 0.033, "min_ticks": 4},
                "satisfies": {"descanso": 0.95},
            },
            {
                "id": "batalla",
                "label": "batalla",
                "duration_ticks": 40,
                "requires_affordance": "guerra",
                "interruptible": False,
                "satisfies": {"descanso": 0.0},
                "effects": {},
            },
            {"id": "holgazanear", "label": "holgazanear", "duration_ticks": 4},
        ],
        "places": [
            {
                "id": "cama",
                "label": "cama",
                "affordances": ["lecho"],
                "neighbors": {"suelo": 1, "campo": 1},
            },
            {
                "id": "suelo",
                "label": "suelo",
                "affordances": ["lecho"],
                "neighbors": {"cama": 1},
                "gain_multipliers": {"descanso": 0.45},
            },
            {
                "id": "campo",
                "label": "campo",
                "affordances": ["guerra"],
                "neighbors": {"cama": 1},
            },
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "cama", "start_at": "cama"}],
        "tuning": {"critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def guerrero(descanso: float = 1.0, debt: float = 0.0) -> AgentState:
    a = AgentState(spec_id=AG1, at=CAMA, needs={DESCANSO: descanso})
    if debt:
        a.debt[DESCANSO] = debt
    return a


# --- elasticidad -------------------------------------------------------------


def test_a_fixed_action_keeps_its_duration() -> None:
    """Lo no elástico no se entera de que esto existe."""
    pack = rest_pack()
    accion = pack.action_by_id[ActionId("holgazanear")]
    assert planned_duration(accion, guerrero(), pack.place_by_id[CAMA]) == 4


def test_the_less_tired_sleep_less() -> None:
    """Ya es por persona sin declarar nada por persona: sale del déficit."""
    pack = rest_pack()
    dormir, cama = pack.action_by_id[DORMIR], pack.place_by_id[CAMA]
    assert planned_duration(dormir, guerrero(0.9), cama) == 4  # el suelo de min_ticks
    assert planned_duration(dormir, guerrero(0.5), cama) == 16
    assert planned_duration(dormir, guerrero(0.0), cama) == 31  # ~7h45


def test_the_floor_stops_a_pointless_nap() -> None:
    """Nadie se acuesta para quince minutos, aunque le sobre con eso."""
    pack = rest_pack()
    dormir, cama = pack.action_by_id[DORMIR], pack.place_by_id[CAMA]
    assert planned_duration(dormir, guerrero(0.99), cama) == 4


def test_the_cap_holds() -> None:
    pack = rest_pack()
    dormir, cama = pack.action_by_id[DORMIR], pack.place_by_id[CAMA]
    assert planned_duration(dormir, guerrero(0.0, debt=5.0), cama) == 64


def test_a_bad_place_slows_the_rate() -> None:
    """Dormir mal es tener mal ritmo, no tener un tope bajo."""
    pack = rest_pack()
    dormir = pack.action_by_id[DORMIR]
    assert recovery_rate(dormir, guerrero(), pack.place_by_id[CAMA]) == pytest.approx(0.033)
    assert recovery_rate(dormir, guerrero(), pack.place_by_id[SUELO]) == pytest.approx(0.01485)


def test_a_trait_speeds_it_up() -> None:
    """Quien duerme dos horas y está entero recupera deprisa, no duerme menos."""
    pack = rest_pack(
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "cama",
                "start_at": "cama",
                "traits": {"sueno_pesado": 1.0},
            }
        ]
    )
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    agente.needs[DESCANSO] = 0.0
    dormir, cama = pack.action_by_id[DORMIR], pack.place_by_id[CAMA]
    assert recovery_rate(dormir, agente, cama) == pytest.approx(0.066)
    assert planned_duration(dormir, agente, cama) == 16


def test_person_and_place_compose() -> None:
    """Duerme mal quien tiene mal sueño, quien duerme en mal sitio, y peor las dos."""
    pack = rest_pack(
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "cama",
                "start_at": "cama",
                "traits": {"sueno_pesado": 1.0},
            }
        ]
    )
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    assert recovery_rate(
        pack.action_by_id[DORMIR], agente, pack.place_by_id[SUELO]
    ) == pytest.approx(0.033 * 2.0 * 0.45)


# --- deuda -------------------------------------------------------------------


def test_without_max_debt_the_floor_just_cuts() -> None:
    """Todo lo calibrado hasta ahora sigue comportándose igual."""
    specs = {DESCANSO: NeedSpec(id=DESCANSO, label="d", decay_per_tick=0.5)}
    a = guerrero(0.2)
    a.decay(specs)
    assert a.needs[DESCANSO] == 0.0
    assert a.debt == {}


def test_what_the_floor_would_eat_becomes_debt() -> None:
    pack = rest_pack()
    a = guerrero(0.005)
    a.decay(pack.need_by_id)  # 0.007 de caída sobre 0.005
    assert a.needs[DESCANSO] == 0.0
    assert a.debt[DESCANSO] == pytest.approx(0.002)


def test_debt_is_capped() -> None:
    """Sin tope, una campaña de un mes dejaría una deuda impagable."""
    pack = rest_pack()
    a = guerrero(0.0)
    for _ in range(1000):
        a.decay(pack.need_by_id)
    assert a.debt[DESCANSO] == pytest.approx(1.0)


def test_restoring_pays_the_debt_first() -> None:
    a = guerrero(0.0, debt=0.5)
    llegado = a.restore(DESCANSO, 0.8)
    assert a.debt.get(DESCANSO, 0.0) == pytest.approx(0.0)
    assert a.needs[DESCANSO] == pytest.approx(0.3)
    assert llegado == pytest.approx(0.3)


def test_a_short_night_only_pays_the_debt() -> None:
    """A quien lo despiertan pronto se levanta sin deber nada y hecho polvo."""
    a = guerrero(0.0, debt=1.0)
    a.restore(DESCANSO, 0.5)
    assert a.needs[DESCANSO] == 0.0
    assert a.debt[DESCANSO] == pytest.approx(0.5)


def test_the_deficit_includes_the_debt() -> None:
    """Dos agentes con el descanso a cero duermen cosas muy distintas."""
    assert guerrero(0.0).deficit(DESCANSO) == pytest.approx(1.0)
    assert guerrero(0.0, debt=1.0).deficit(DESCANSO) == pytest.approx(2.0)


def test_the_warrior_needs_fifteen_hours() -> None:
    """La cuenta entera, y no hay ningún caso especial en ella.

    Tres días de batalla con decaimiento 0.007: se llega a cero en día y medio y
    el resto se acumula, hasta el tope de 1.00. Pagar eso y llenar el descanso
    son 2.00 a razón de 0.033 por tick.
    """
    pack = rest_pack()
    a = guerrero(1.0)
    for _ in range(3 * 96):
        a.decay(pack.need_by_id)

    assert a.needs[DESCANSO] == 0.0
    assert a.debt[DESCANSO] == pytest.approx(1.0)

    horas = planned_duration(pack.action_by_id[DORMIR], a, pack.place_by_id[CAMA]) / 4
    assert horas == pytest.approx(15.25, abs=0.5)


def test_waking_him_at_eight_leaves_him_wrecked() -> None:
    """Días de esfuerzo cuestan días de recuperación."""
    a = guerrero(0.0, debt=1.0)
    a.restore(DESCANSO, 0.033 * 32)  # ocho horas
    assert a.needs[DESCANSO] == pytest.approx(0.056, abs=0.01)


# --- inabandonable -----------------------------------------------------------


def test_a_battle_is_not_dropped_midway() -> None:
    """Y es lo que hace posible la deuda: sin esto el agente se autolimita."""
    pack = rest_pack(
        needs=[
            {
                "id": "descanso",
                "label": "descanso",
                "decay_per_tick": 0.05,
                "initial": 0.5,
                "max_debt": 1.0,
            }
        ],
        agents=[{"id": "ag1", "label": "ag1", "home": "campo", "start_at": "campo"}],
        tuning={"critical_need_threshold": 0.9},  # todo es emergencia
    )
    sim = Simulation(pack, seed=1)
    sim.run(60)

    from agora.engine.events import EventKind

    sueltas = [
        e for e in sim.log.of_kind(EventKind.ACTION_ABORTED) if e.action == BATALLA
    ]
    assert not sueltas


def test_the_debt_only_grows_because_he_cannot_stop() -> None:
    pack = rest_pack(
        needs=[
            {
                "id": "descanso",
                "label": "descanso",
                "decay_per_tick": 0.05,
                "initial": 0.5,
                "max_debt": 1.0,
            }
        ],
        agents=[{"id": "ag1", "label": "ag1", "home": "campo", "start_at": "campo"}],
        tuning={"critical_need_threshold": 0.9},
    )
    sim = Simulation(pack, seed=1)
    sim.run(60)
    assert sim.state.agents[AG1].debt.get(DESCANSO, 0.0) > 0.0


def test_a_normal_action_is_still_droppable() -> None:
    pack = rest_pack()
    assert pack.action_by_id[ActionId("holgazanear")].interruptible
    assert not pack.action_by_id[BATALLA].interruptible


# --- lo que se suelta a medias sí cuenta -------------------------------------


def test_a_broken_sleep_credits_what_it_earned() -> None:
    """Sin esto la elasticidad EMPEORA las cosas: comprometer quince horas para
    no cobrar nada si te levantan es peor que comprometer ocho.

    El descanso arranca por ENCIMA del umbral y el hambre por debajo, o el
    triaje hace lo correcto y no interrumpe: quien duerme ya está atendiendo la
    peor urgencia si el descanso es lo que peor está.
    """
    pack = rest_pack(
        needs=[
            {
                "id": "descanso",
                "label": "descanso",
                "decay_per_tick": 0.007,
                "initial": 0.45,
                "max_debt": 1.0,
            },
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.15, "initial": 0.95},
        ],
        actions=[
            {
                "id": "dormir",
                "label": "dormir",
                "duration_ticks": 64,
                "requires_affordance": "lecho",
                "elastic": {"need": "descanso", "per_tick": 0.033, "min_ticks": 4},
                "satisfies": {"descanso": 0.95},
            },
            {
                "id": "comer",
                "label": "comer",
                "duration_ticks": 2,
                "satisfies": {"hambre": 0.9},
                "effects": {"hambre": 0.9},
            },
        ],
        tuning={"critical_need_threshold": 0.25},
    )
    sim = Simulation(pack, seed=1)
    sim.run(14)

    from agora.engine.events import EventKind

    rotos = [e for e in sim.log.of_kind(EventKind.ACTION_ABORTED) if e.action == DORMIR]
    assert rotos, "el hambre debería levantarlo a mitad de sueño"
    assert sim.state.agents[AG1].needs[DESCANSO] > 0.45


# --- validaciones ------------------------------------------------------------


def test_declaring_the_elastic_need_twice_is_rejected() -> None:
    """Se aplicaría dos veces: una por tick cumplido y otra de golpe al acabar."""
    with pytest.raises(Exception, match="se aplicaría dos veces"):
        rest_pack(
            actions=[
                {
                    "id": "dormir",
                    "label": "dormir",
                    "duration_ticks": 64,
                    "requires_affordance": "lecho",
                    "elastic": {"need": "descanso", "per_tick": 0.033},
                    "satisfies": {"descanso": 0.95},
                    "effects": {"descanso": 0.95},
                },
                {"id": "holgazanear", "label": "holgazanear", "duration_ticks": 4},
            ]
        )


def test_a_floor_above_the_cap_is_rejected() -> None:
    with pytest.raises(Exception, match="supera el tope"):
        rest_pack(
            actions=[
                {
                    "id": "dormir",
                    "label": "dormir",
                    "duration_ticks": 10,
                    "requires_affordance": "lecho",
                    "elastic": {"need": "descanso", "per_tick": 0.033, "min_ticks": 20},
                    "satisfies": {"descanso": 0.95},
                },
                {"id": "holgazanear", "label": "holgazanear", "duration_ticks": 4},
            ]
        )


def test_an_unknown_gain_need_is_caught() -> None:
    with pytest.raises(Exception, match="necesidad desconocida"):
        rest_pack(
            places=[
                {
                    "id": "cama",
                    "label": "cama",
                    "affordances": ["lecho"],
                    "neighbors": {"suelo": 1, "campo": 1},
                    "gain_multipliers": {"vigor": 0.5},
                },
                {
                    "id": "suelo",
                    "label": "suelo",
                    "affordances": ["lecho"],
                    "neighbors": {"cama": 1},
                },
                {
                    "id": "campo",
                    "label": "campo",
                    "affordances": ["guerra"],
                    "neighbors": {"cama": 1},
                },
            ]
        )
