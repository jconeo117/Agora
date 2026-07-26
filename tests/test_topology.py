"""Tests de topología. Ambientación neutra a propósito: los lugares se llaman
`a`, `b`, `c`. Un test del motor que necesita nombrar una posada está probando
el pack, no el motor.
"""

from __future__ import annotations

from agora.engine.ontology import PlaceId, PlaceSpec
from agora.engine.topology import INFINITE, TravelMap, is_strongly_connected


def place(name: str, **neighbors: int) -> PlaceSpec:
    return PlaceSpec(
        id=PlaceId(name),
        label=name,
        neighbors={PlaceId(k): v for k, v in neighbors.items()},
    )


def test_bidirectional_graph_is_strongly_connected() -> None:
    places = [place("a", b=1), place("b", a=1, c=2), place("c", b=2)]
    assert is_strongly_connected(places)


def test_one_way_exit_is_not_strongly_connected() -> None:
    """El pozo: se entra a `c` pero no se sale. Conexo en débil, trampa mortal
    para un agente. Es justo el bug que esta comprobación existe para atrapar.
    """
    places = [place("a", b=1), place("b", a=1, c=2), place("c")]
    assert not is_strongly_connected(places)


def test_single_place_is_trivially_connected() -> None:
    assert is_strongly_connected([place("a")])


def test_distance_uses_shortest_route_not_direct_edge() -> None:
    """Ruta directa cara (10) frente a desvío barato (1+1). Gana el desvío."""
    places = [
        place("a", b=1, c=10),
        place("b", a=1, c=1),
        place("c", a=10, b=1),
    ]
    travel = TravelMap(places)
    assert travel.distance(PlaceId("a"), PlaceId("c")) == 2
    assert travel.first_hop(PlaceId("a"), PlaceId("c")) == PlaceId("b")
    assert travel.route(PlaceId("a"), PlaceId("c")) == [PlaceId("b"), PlaceId("c")]


def test_distance_to_self_is_zero_and_has_no_hop() -> None:
    travel = TravelMap([place("a", b=1), place("b", a=1)])
    assert travel.distance(PlaceId("a"), PlaceId("a")) == 0
    assert travel.first_hop(PlaceId("a"), PlaceId("a")) is None


def test_unreachable_place_reports_infinite_and_empty_route() -> None:
    travel = TravelMap([place("a"), place("b")])
    assert travel.distance(PlaceId("a"), PlaceId("b")) == INFINITE
    assert not travel.is_reachable(PlaceId("a"), PlaceId("b"))
    assert travel.route(PlaceId("a"), PlaceId("b")) == []


def test_asymmetric_costs_are_preserved() -> None:
    """Bajar el acantilado cuesta 1, subirlo 5. El grafo dirigido debe notarlo."""
    places = [place("alto", bajo=1), place("bajo", alto=5)]
    travel = TravelMap(places)
    assert travel.distance(PlaceId("alto"), PlaceId("bajo")) == 1
    assert travel.distance(PlaceId("bajo"), PlaceId("alto")) == 5
