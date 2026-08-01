"""Tests de percepción limitada.

Sin esto, cada agente conoce en tiempo real la ocupación de todos los lugares
del mundo. Con esto solo sabe lo que vio con sus ojos y hace cuánto.

El principio, que costó llegar a él: se limita el CONOCIMIENTO, no el ALCANCE.
Deliberar solo sobre lo cercano reintroduce el fallo estructural de F0 —viajar
no satisface ninguna necesidad, así que nunca gana, y el agente se muere de
hambre a tres ticks de la comida—. Aquí se sigue deliberando sobre el mundo
entero; lo que cambia es con qué información.
"""

from __future__ import annotations

import copy
from typing import Any

from agora.agents.decide import candidates, is_available
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, WorldState
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
SOCIAL = ActionId("act_social")


def seen_pack(**overrides: Any) -> ContentPack:
    """`act_social` exige compañía y solo se puede en p2, a 2 ticks."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.3}],
        "actions": [
            {
                "id": "act_social",
                "label": "act_social",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "requires_company": 1,
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.5},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 2}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 2}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {"sighting_horizon": 20, "critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agent_at(place: PlaceId = P1) -> AgentState:
    return AgentState(spec_id=AG1, at=place, needs={N1: 0.5})


# --- la memoria --------------------------------------------------------------


def test_an_unseen_place_is_unknown() -> None:
    assert agent_at().perceived_company(P2, tick=0, horizon=20) is None


def test_what_was_seen_is_remembered() -> None:
    a = agent_at(P2)
    a.observe(tick=10, company=3)
    assert a.perceived_company(P2, tick=15, horizon=20) == 3


def test_a_sighting_expires() -> None:
    a = agent_at(P2)
    a.observe(tick=10, company=3)
    assert a.perceived_company(P2, tick=29, horizon=20) == 3
    assert a.perceived_company(P2, tick=31, horizon=20) is None


def test_horizon_zero_restores_omniscience() -> None:
    """Devuelve `None` siempre, y quien pregunta se queda con la verdad."""
    a = agent_at(P2)
    a.observe(tick=10, company=3)
    assert a.perceived_company(P2, tick=10, horizon=0) is None


def test_an_agent_only_sees_where_it_stands() -> None:
    """Nadie ve el barrio entero desde su cocina."""
    a = agent_at(P1)
    a.observe(tick=5, company=2)
    assert set(a.sightings) == {P1}


# --- lo desconocido se supone a favor ----------------------------------------


def test_unknown_company_passes_the_gate() -> None:
    """Suponer vacío haría que nadie fuera nunca a donde no acabara de estar."""
    pack = seen_pack()
    action, place = pack.action_by_id[SOCIAL], pack.place_by_id[P2]
    assert is_available(action, place, company=None, needs={N1: 1.0})
    assert not is_available(action, place, company=0, needs={N1: 1.0})


def test_a_remembered_empty_place_is_not_offered() -> None:
    world = WorldState.new(seen_pack(), seed=1)
    agent = world.agents[AG1]
    world.agents[AG2].at = P1  # p2 está vacío de verdad
    world.tick = 10
    agent.sightings[P2] = (10, 0)  # y él lo sabe

    assert not any(d.action == SOCIAL for d in candidates(world, agent))


def test_a_stale_memory_lets_him_try_again() -> None:
    """Cerrado el ciclo: recuerdas vacío, no vas; caduca, vuelves a probar."""
    world = WorldState.new(seen_pack(), seed=1)
    agent = world.agents[AG1]
    world.agents[AG2].at = P1
    agent.sightings[P2] = (10, 0)

    world.tick = 25
    assert not any(d.action == SOCIAL for d in candidates(world, agent))
    world.tick = 40
    assert any(d.action == SOCIAL for d in candidates(world, agent))


def test_the_current_place_is_known_first_hand() -> None:
    """Donde está, lo ve. Ninguna memoria caducada le engaña sobre eso."""
    world = WorldState.new(seen_pack(), seed=1)
    agent = world.agents[AG1]
    agent.at = P2
    world.agents[AG2].at = P1  # p2 está vacío AHORA
    agent.sightings[P2] = (0, 5)  # pero recuerda que estaba lleno
    world.tick = 1

    assert not any(d.action == SOCIAL and d.place == P2 for d in candidates(world, agent))


# --- integración -------------------------------------------------------------


def test_the_trip_that_turns_out_wrong() -> None:
    """El "fui al café y estaba vacío".

    No hace falta maquinaria nueva: la comprobación al llegar ya existía desde
    que la compañía es un requisito. Solo cambia con qué se decide.
    """
    sim = Simulation(seen_pack(), seed=1)
    sim.run(400)

    chascos = [
        e
        for e in sim.log.of_kind(EventKind.ACTION_ABORTED)
        if e.data.get("reason") == "condiciones"
    ]
    assert chascos, "con memoria caducable alguien debería viajar en balde"


def test_knowing_less_changes_the_behaviour() -> None:
    """La dirección del cambio depende del mundo, y conviene no afirmar de más.

    En el barrio —diez agentes, veintiún lugares— la memoria fresca es rara, así
    que casi todo se supone a favor y los viajes en balde suben de 144 a 386 al
    mes. En este escenario de dos agentes pasa lo contrario: el recuerdo suele
    ser "estaba vacío", y eso RETIENE al agente en casa.

    Lo que sí es robusto en ambos casos es que la conducta cambia. Este test lo
    fija sin inventarse una monotonía que no existe.
    """

    def trayectoria(horizonte: int) -> list[str]:
        sim = Simulation(
            seen_pack(
                tuning={"sighting_horizon": horizonte, "critical_need_threshold": 0.0}
            ),
            seed=1,
        )
        sim.run(400)
        return [
            f"{e.tick}:{e.kind}:{e.action}"
            for e in sim.log
            if e.actor == AG1
        ]

    assert trayectoria(20) != trayectoria(0)


def test_agents_still_deliberate_over_the_whole_world() -> None:
    """Se limita el conocimiento, NO el alcance.

    Si se limitara el alcance volvería el fallo estructural de F0: viajar no
    satisface ninguna necesidad, así que nunca ganaría, y un agente se moriría
    de hambre a tres ticks de la comida.
    """
    world = WorldState.new(seen_pack(), seed=1)
    agent = world.agents[AG1]
    lugares = {d.place for d in candidates(world, agent)}
    assert lugares == {P1, P2}
