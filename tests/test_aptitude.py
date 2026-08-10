"""Tests de aptitud y de puertas por rasgo.

Dos piezas pequeñas que abren la capa de competencia.

**Aptitud.** Hasta aquí, estudiar rendía lo mismo a todo el mundo y "se le da
bien la magia" solo podía significar "le gusta más", que es la mitad de la idea.
`need_weight_multipliers` dice cuánto le IMPORTA algo a alguien; `gain_multipliers`
dice cuánto le CUNDE. Son la misma forma y significan cosas opuestas, y con un
solo canal no se puede expresar a quien tiene mano para algo que le trae sin
cuidado.

De paso absorbe `elastic_rate_multipliers`, que decía esto mismo solo para el
sueño. Dos mecanismos que significan lo mismo son uno de más.

**Puertas por rasgo.** `requires` solo sabía mirar necesidades, y hay cosas que
no dependen de lo que tengas sino de quién eres. Es lo que permite que las
clases, los linajes y las afinidades sean rasgos —continuos, componibles,
capaces de híbridos— en vez de una necesidad por cada categoría.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, is_available, planned_duration, recovery_rate
from agora.engine.disposition import compose_gains
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation

ARCANO = NeedId("arcano")
VIGOR = NeedId("vigor")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
AULA = PlaceId("aula")
CAMPO = PlaceId("campo")
ESTUDIAR = ActionId("estudiar")
PIRO = ActionId("pyromancia")
HIDRO = ActionId("hidromancia")
DON = TraitId("don_arcano")
FUEGO = TraitId("elem_fuego")


def academy_pack(**overrides: Any) -> ContentPack:
    """Un aula donde se estudia y dos conjuros que piden afinidad."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "arcano", "label": "arcano", "decay_per_tick": 0.0,
             "progression": True, "initial": 0.05, "base_weight": 0.6,
             "urgency_exponent": 0.8},
            {"id": "vigor", "label": "vigor", "decay_per_tick": 0.01, "initial": 0.7,
             "max_debt": 0.5},
        ],
        "traits": [
            {"id": "don_arcano", "label": "don arcano",
             "gain_multipliers": {"arcano": 3.0}},
            {"id": "elem_fuego", "label": "afinidad de fuego"},
        ],
        "actions": [
            {"id": "estudiar", "label": "estudiar", "duration_ticks": 6,
             "requires_affordance": "archivo",
             "satisfies": {"arcano": 0.5}, "costs": {"vigor": 0.2},
             "effects": {"arcano": 0.02, "vigor": -0.05}},
            {"id": "pyromancia", "label": "pyromancia", "duration_ticks": 4,
             "requires_traits": {"elem_fuego": 0.5},
             "satisfies": {"arcano": 0.3}, "effects": {"arcano": 0.03}},
            {"id": "hidromancia", "label": "hidromancia", "duration_ticks": 4,
             "satisfies": {"arcano": 0.2}, "effects": {"arcano": 0.01}},
            {"id": "dormir", "label": "dormir", "duration_ticks": 40,
             "requires_affordance": "cama",
             "elastic": {"need": "vigor", "per_tick": 0.03, "min_ticks": 4},
             "satisfies": {"vigor": 0.9}},
        ],
        "places": [
            {"id": "aula", "label": "aula", "affordances": ["archivo", "cama"],
             "neighbors": {"campo": 1}},
            {"id": "campo", "label": "campo", "affordances": ["cama"],
             "neighbors": {"aula": 1},
             "gain_multipliers": {"vigor": 0.5}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "aula", "start_at": "aula"}],
        "tuning": {"critical_need_threshold": 0.1},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def con_rasgos(**rasgos: float) -> ContentPack:
    return academy_pack(
        agents=[{"id": "ag1", "label": "ag1", "home": "aula", "start_at": "aula",
                 "traits": rasgos}]
    )


# --- aptitud: cuánto le cunde --------------------------------------------


def test_without_the_trait_everyone_is_average() -> None:
    assert compose_gains(academy_pack(), {}) == {ARCANO: 1.0, VIGOR: 1.0}


def test_a_gift_multiplies_what_you_learn() -> None:
    assert compose_gains(academy_pack(), {DON: 1.0})[ARCANO] == pytest.approx(3.0)


def test_the_sign_inverts_it() -> None:
    """No hace falta un rasgo `torpeza`: es el don con el signo cambiado."""
    assert compose_gains(academy_pack(), {DON: -1.0})[ARCANO] == pytest.approx(1 / 3)


def test_aptitude_lands_on_the_effect() -> None:
    """La prueba de fondo: la misma acción rinde distinto a dos personas."""
    normal = Simulation(academy_pack(), seed=1)
    dotado = Simulation(con_rasgos(don_arcano=1.0), seed=1)
    normal.run(60)
    dotado.run(60)
    assert dotado.state.agents[AG1].needs[ARCANO] > normal.state.agents[AG1].needs[ARCANO] * 2


def test_aptitude_does_not_touch_what_it_costs() -> None:
    """Que se te dé bien la magia hace que estudiar cunda más; no hace que
    cansarse cueste menos."""
    pack = con_rasgos(don_arcano=1.0)
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    antes = agente.needs[VIGOR]
    agente.apply({VIGOR: -0.1}, pack.need_by_id)
    assert agente.needs[VIGOR] == pytest.approx(antes - 0.1)


def test_it_reaches_the_elastic_rate_too() -> None:
    """Es la misma pregunta hecha dos veces, y ahora tiene una sola respuesta."""
    pack = con_rasgos(don_arcano=0.0)
    world = WorldState.new(pack, seed=1)
    dormir, aula = pack.action_by_id[ActionId("dormir")], pack.place_by_id[AULA]
    assert recovery_rate(dormir, world.agents[AG1], aula.gain_multipliers) == pytest.approx(0.03)


def test_person_and_place_compose() -> None:
    """lo que rinde algo = base * aptitud de quien lo hace * calidad del sitio."""
    pack = academy_pack(
        traits=[
            {"id": "don_arcano", "label": "don", "gain_multipliers": {"vigor": 2.0}},
            {"id": "elem_fuego", "label": "fuego"},
        ],
        agents=[{"id": "ag1", "label": "ag1", "home": "aula", "start_at": "aula",
                 "traits": {"don_arcano": 1.0}}],
    )
    world = WorldState.new(pack, seed=1)
    dormir = pack.action_by_id[ActionId("dormir")]
    aula, campo = pack.place_by_id[AULA], pack.place_by_id[CAMPO]
    assert recovery_rate(dormir, world.agents[AG1], aula.gain_multipliers) == pytest.approx(0.06)
    assert recovery_rate(dormir, world.agents[AG1], campo.gain_multipliers) == pytest.approx(0.03)


def test_a_gift_shortens_the_elastic_duration() -> None:
    """Quien se repone deprisa duerme menos, y sale del mismo número."""
    pack = academy_pack(
        traits=[
            {"id": "don_arcano", "label": "don", "gain_multipliers": {"vigor": 2.0}},
            {"id": "elem_fuego", "label": "fuego"},
        ],
        agents=[
            {"id": "ag1", "label": "ag1", "home": "aula", "start_at": "aula",
             "traits": {"don_arcano": 1.0}},
            {"id": "ag2", "label": "ag2", "home": "aula", "start_at": "aula"},
        ],
    )
    world = WorldState.new(pack, seed=1)
    dormir, aula = pack.action_by_id[ActionId("dormir")], pack.place_by_id[AULA]
    for a in world.agents.values():
        a.needs[VIGOR] = 0.0
    assert planned_duration(dormir, world.agents[AG1], aula.gain_multipliers) < planned_duration(
        dormir, world.agents[AG2], aula.gain_multipliers
    )


# --- puertas por rasgo -------------------------------------------------------


def test_without_the_affinity_the_door_is_shut() -> None:
    pack = academy_pack()
    piro, aula = pack.action_by_id[PIRO], pack.place_by_id[AULA]
    assert not is_available(piro, aula, None, {}, None, {})
    assert is_available(piro, aula, None, {}, None, {FUEGO: 1.0})


def test_a_weak_affinity_is_not_enough() -> None:
    """Es un umbral, no un interruptor: los híbridos a medias no entran."""
    pack = academy_pack()
    piro, aula = pack.action_by_id[PIRO], pack.place_by_id[AULA]
    assert not is_available(piro, aula, None, {}, None, {FUEGO: 0.3})
    assert is_available(piro, aula, None, {}, None, {FUEGO: 0.5})


def test_no_traits_given_disables_the_gate() -> None:
    """Para poder preguntar por una acción sin un agente delante."""
    pack = academy_pack()
    assert is_available(pack.action_by_id[PIRO], pack.place_by_id[AULA], None, {}, None, None)


def test_an_ungated_action_is_open_to_everyone() -> None:
    pack = academy_pack()
    assert is_available(pack.action_by_id[HIDRO], pack.place_by_id[AULA], None, {}, None, {})


def test_the_gate_shows_up_in_deliberation() -> None:
    sin = WorldState.new(academy_pack(), seed=1)
    con = WorldState.new(con_rasgos(elem_fuego=1.0), seed=1)
    assert not any(d.action == PIRO for d in candidates(sin, sin.agents[AG1]))
    assert any(d.action == PIRO for d in candidates(con, con.agents[AG1]))


def test_two_affinities_live_different_lives() -> None:
    """Misma ficha salvo un rasgo, y no hacen lo mismo."""
    pack = academy_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "aula", "start_at": "aula",
             "traits": {"elem_fuego": 1.0}},
            {"id": "ag2", "label": "ag2", "home": "aula", "start_at": "aula"},
        ]
    )
    sim = Simulation(pack, seed=1)
    sim.run(300)
    from agora.engine.events import EventKind

    hechos = {
        actor: {e.action for e in sim.log.by_actor(actor) if e.kind == EventKind.ACTION_COMPLETED}
        for actor in (AG1, AG2)
    }
    assert PIRO in hechos[AG1]
    assert PIRO not in hechos[AG2]


# --- validaciones ------------------------------------------------------------


def test_an_unknown_gate_trait_is_caught() -> None:
    """Sin esto no hay síntoma: la puerta se queda abierta y nadie se entera."""
    with pytest.raises(ValidationError, match="rasgo desconocida/o"):
        academy_pack(
            actions=[
                {"id": "estudiar", "label": "estudiar", "duration_ticks": 6,
                 "requires_affordance": "archivo",
                 "satisfies": {"arcano": 0.5}, "effects": {"arcano": 0.02}},
                {"id": "pyromancia", "label": "pyromancia", "duration_ticks": 4,
                 "requires_traits": {"elem_sombra": 0.5},
                 "satisfies": {"arcano": 0.3}, "effects": {"arcano": 0.03}},
            ]
        )


def test_an_unknown_gain_need_is_caught() -> None:
    with pytest.raises(ValidationError, match="necesidad desconocida"):
        academy_pack(
            traits=[
                {"id": "don_arcano", "label": "don", "gain_multipliers": {"gloria": 2.0}},
                {"id": "elem_fuego", "label": "fuego"},
            ]
        )
