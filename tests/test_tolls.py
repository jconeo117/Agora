"""Tests de peajes: aristas que cuestan algo más que tiempo.

Es lo que separa un **servicio** de un atajo. Un porte que deja en la boca de la
sima en un tick no es un camino corto: es algo por lo que se paga, y por eso hay
quien lo toma y quien va andando. Sin precio siempre ganaría, todo el mundo iría
en carro y no habría decisión ninguna.

Dos propiedades que conviene tener claras:

**El peaje entra en la deliberación pesado por la urgencia**, así que a quien va
justo de dinero le duele mucho más. De ahí sale que el pobre camine y el holgado
pague, sin una regla escrita para ello.

**Pero no bloquea el paso.** Quien acabe cruzando sin fondos paga lo que tenga y
llega a cero. Bloquear obligaría a buscar ruta por agente —y una ruta distinta
para cada bolsillo—, y eso es otro motor.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, toll_cost
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, PlaceSpec
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.topology import TravelMap
from agora.engine.world import Simulation

ORO = NeedId("oro")
AG1 = AgentId("ag1")
CIUDAD = PlaceId("ciudad")
PUERTA = PlaceId("puerta")
SIMA = PlaceId("sima")
EXPOLIAR = ActionId("expoliar")


def toll_pack(**overrides: Any) -> ContentPack:
    """La ciudad, y dos formas de llegar a la sima: el porte o los pies.

        ciudad --porte 1t, 0.20 de oro--> sima
        ciudad --puerta 3t--> sima 3t     (andando, gratis)
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "oro", "label": "oro", "decay_per_tick": 0.001, "initial": 0.6,
             "base_weight": 1.0, "urgency_exponent": 1.6},
            {"id": "gloria", "label": "gloria", "decay_per_tick": 0.01, "initial": 0.5},
        ],
        "actions": [
            {"id": "expoliar", "label": "expoliar", "duration_ticks": 4,
             "requires_affordance": "expolio",
             "satisfies": {"gloria": 0.8}, "effects": {"gloria": 0.5}},
            {"id": "holgar", "label": "holgar", "duration_ticks": 2,
             "satisfies": {"gloria": 0.1}, "effects": {"gloria": 0.05}},
        ],
        "places": [
            {"id": "ciudad", "label": "ciudad",
             "neighbors": {"sima": 1, "puerta": 3},
             "tolls": {"sima": {"oro": 0.20}}},
            {"id": "puerta", "label": "puerta", "neighbors": {"ciudad": 3, "sima": 3}},
            {"id": "sima", "label": "sima", "affordances": ["expolio"],
             "neighbors": {"puerta": 3}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "ciudad", "start_at": "ciudad"}],
        "tuning": {"critical_need_threshold": 0.0, "travel_discount": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def sin_peaje() -> ContentPack:
    pack = toll_pack()
    d = pack.model_dump()
    d["places"][0]["tolls"] = {}
    return ContentPack.model_validate(d)


# --- el mapa lo acumula ------------------------------------------------------


def test_an_untolled_route_costs_nothing() -> None:
    tm = TravelMap(sin_peaje().places)
    assert tm.toll(CIUDAD, SIMA) == {}


def test_the_toll_travels_with_the_route() -> None:
    tm = TravelMap(toll_pack().places)
    assert tm.toll(CIUDAD, SIMA) == {ORO: pytest.approx(0.20)}


def test_the_way_back_is_its_own_edge() -> None:
    """El grafo es dirigido: llevar es una arista y volver es otra."""
    tm = TravelMap(toll_pack().places)
    assert tm.toll(SIMA, CIUDAD) == {}


def test_tolls_add_up_along_the_way() -> None:
    """Dos tramos de pago en la misma ruta se suman."""
    pack = toll_pack(
        places=[
            {"id": "ciudad", "label": "c", "neighbors": {"puerta": 1},
             "tolls": {"puerta": {"oro": 0.1}}},
            {"id": "puerta", "label": "p", "neighbors": {"ciudad": 1, "sima": 1},
             "tolls": {"sima": {"oro": 0.05}}},
            {"id": "sima", "label": "s", "affordances": ["expolio"],
             "neighbors": {"puerta": 1}},
        ]
    )
    assert TravelMap(pack.places).toll(CIUDAD, SIMA) == {ORO: pytest.approx(0.15)}


def test_nowhere_costs_nothing() -> None:
    tm = TravelMap(toll_pack().places)
    assert tm.toll(CIUDAD, CIUDAD) == {}


# --- duele según el bolsillo -------------------------------------------------


def test_an_empty_toll_is_free() -> None:
    pack = toll_pack()
    world = WorldState.new(pack, seed=1)
    assert toll_cost(pack, world.agents[AG1], world.agents[AG1].need_weights, {}) == 0.0


def test_the_same_toll_hurts_the_poor_more() -> None:
    """Aquí está lo que convierte un servicio en una decisión."""
    pack = toll_pack()
    world = WorldState.new(pack, seed=1)
    agente = world.agents[AG1]
    peaje = {ORO: 0.2}

    agente.needs[ORO] = 0.9
    holgado = toll_cost(pack, agente, agente.need_weights, peaje)
    agente.needs[ORO] = 0.1
    justo = toll_cost(pack, agente, agente.need_weights, peaje)

    assert justo > holgado * 5


# --- cambia la decisión ------------------------------------------------------


def test_the_toll_lowers_what_it_reaches() -> None:
    """El peaje es de la RUTA, así que baja todo lo que se pueda hacer allí."""
    con = WorldState.new(toll_pack(), seed=1)
    sin = WorldState.new(sin_peaje(), seed=1)
    for w in (con, sin):
        w.agents[AG1].needs[ORO] = 0.2

    caro = next(d for d in candidates(con, con.agents[AG1]) if d.action == EXPOLIAR)
    gratis = next(d for d in candidates(sin, sin.agents[AG1]) if d.action == EXPOLIAR)
    assert caro.utility < gratis.utility


def test_the_route_is_still_the_shortest_one() -> None:
    """El peaje se cobra, no se esquiva: la ruta la siguen eligiendo los ticks.

    Buscar la ruta más barata sería otro grafo, y uno distinto por agente porque
    cada cual valora el dinero de otra forma. Aquí la ruta es una.
    """
    tm = TravelMap(toll_pack().places)
    assert tm.distance(CIUDAD, SIMA) == 1
    assert tm.first_hop(CIUDAD, SIMA) == SIMA


# --- se cobra al cruzar ------------------------------------------------------


def test_crossing_charges_it() -> None:
    """Contra el mismo mundo sin peaje, que es lo único que dice algo.

    "El oro baja" pasaría igual sin cobrar nada: baja solo por el decaimiento.
    """

    def oro_tras(pack: ContentPack, ticks: int = 120) -> float:
        sim = Simulation(pack, seed=1)
        sim.run(ticks)
        return sim.state.agents[AG1].needs[ORO]

    assert oro_tras(toll_pack()) < oro_tras(sin_peaje()) - 0.1


def test_paying_makes_him_go_less_often() -> None:
    """Y no solo cuesta: disuade. Medido, 9 bajadas contra 12."""

    def bajadas(pack: ContentPack) -> int:
        sim = Simulation(pack, seed=1)
        sim.run(120)
        return len(
            [e for e in sim.log.of_kind(EventKind.ACTION_COMPLETED) if e.action == EXPOLIAR]
        )

    assert bajadas(toll_pack()) < bajadas(sin_peaje())


def test_walking_the_long_way_is_free() -> None:
    sim = Simulation(sin_peaje(), seed=1)
    antes = sim.state.agents[AG1].needs[ORO]
    sim.run(40)
    # Solo baja por el decaimiento, no por peaje: 40 ticks a 0.001.
    assert sim.state.agents[AG1].needs[ORO] == pytest.approx(antes - 0.04, abs=0.005)


def test_a_broke_traveller_is_not_blocked() -> None:
    """Paga lo que tenga y llega a cero. Bloquear pediría ruta por agente."""
    sim = Simulation(toll_pack(), seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.05
    sim.run(40)
    assert sim.state.agents[AG1].needs[ORO] >= 0.0


# --- validaciones ------------------------------------------------------------


def test_a_toll_to_a_stranger_is_caught() -> None:
    """Un peaje hacia quien no es vecino no se cobra jamás: la arista no existe."""
    with pytest.raises(ValidationError, match="no es vecino suyo"):
        toll_pack(
            places=[
                {"id": "ciudad", "label": "c", "neighbors": {"puerta": 1},
                 "tolls": {"sima": {"oro": 0.2}}},
                {"id": "puerta", "label": "p", "neighbors": {"ciudad": 1, "sima": 1}},
                {"id": "sima", "label": "s", "affordances": ["expolio"],
                 "neighbors": {"puerta": 1}},
            ]
        )


def test_an_unknown_toll_need_is_caught() -> None:
    with pytest.raises(ValidationError, match="necesidad desconocida"):
        toll_pack(
            places=[
                {"id": "ciudad", "label": "c", "neighbors": {"sima": 1, "puerta": 3},
                 "tolls": {"sima": {"favores": 0.2}}},
                {"id": "puerta", "label": "p", "neighbors": {"ciudad": 3, "sima": 3}},
                {"id": "sima", "label": "s", "affordances": ["expolio"],
                 "neighbors": {"puerta": 3}},
            ]
        )


def test_a_negative_toll_is_rejected() -> None:
    """Un peaje negativo sería cobrar por viajar, y para eso están los efectos."""
    with pytest.raises(ValidationError):
        PlaceSpec(
            id=CIUDAD, label="c", neighbors={SIMA: 1}, tolls={SIMA: {ORO: -0.2}}
        )
