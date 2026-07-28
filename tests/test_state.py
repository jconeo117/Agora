"""Contrato de `state.py`. Cada test rojo es un PASO pendiente.

    uv run pytest tests/test_state.py -v

Requiere `pack.py` terminado (estos tests construyen packs).
"""

from __future__ import annotations

import pytest

from agora.engine.ontology import ActionId, AgentId, NeedId, NeedSpec, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, PerformingAction, Traveling, WorldState
from tests.test_pack import base_pack

N1 = NeedId("n1")
T1 = TraitId("t1")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
P2 = PlaceId("p2")


@pytest.fixture
def pack() -> ContentPack:
    return ContentPack.model_validate(base_pack())


def agent(**kwargs: object) -> AgentState:
    defaults: dict[str, object] = {"spec_id": AG1, "at": P1, "needs": {N1: 0.5}}
    defaults.update(kwargs)
    return AgentState(**defaults)  # type: ignore[arg-type]


# --- PASOS 1 y 3: decay y clamp ---------------------------------------------


def test_decay_lowers_each_need_by_its_own_rate() -> None:
    specs = {N1: NeedSpec(id=N1, label="n1", decay_per_tick=0.1)}
    a = agent(needs={N1: 0.5})
    a.decay(specs)
    assert a.needs[N1] == pytest.approx(0.4)


def test_decay_never_goes_below_zero() -> None:
    specs = {N1: NeedSpec(id=N1, label="n1", decay_per_tick=0.3)}
    a = agent(needs={N1: 0.1})
    a.decay(specs)
    assert a.needs[N1] == 0.0


# --- PASO 2: efectos ---------------------------------------------------------


def test_apply_adds_deltas_and_accepts_negatives() -> None:
    a = agent(needs={N1: 0.4, NeedId("n2"): 0.8})
    a.apply({N1: 0.3, NeedId("n2"): -0.5})
    assert a.needs[N1] == pytest.approx(0.7)
    assert a.needs[NeedId("n2")] == pytest.approx(0.3)


def test_apply_never_exceeds_one() -> None:
    a = agent(needs={N1: 0.9})
    a.apply({N1: 0.5})
    assert a.needs[N1] == 1.0


def test_apply_leaves_untouched_needs_alone() -> None:
    a = agent(needs={N1: 0.4, NeedId("n2"): 0.8})
    a.apply({N1: 0.1})
    assert a.needs[NeedId("n2")] == 0.8


# --- PASOS 4 y 5: avanzar y ocioso ------------------------------------------


def test_advance_consumes_one_tick_of_an_action() -> None:
    a = agent(busy=PerformingAction(action=ActionId("act_libre"), ticks_remaining=3))
    a.advance()
    assert isinstance(a.busy, PerformingAction)
    assert a.busy.ticks_remaining == 2


def test_advance_stops_at_zero_without_clearing_busy() -> None:
    """Quien llama necesita ver qué acción terminó, para aplicar sus efectos.
    Si `advance` pusiera `busy = None`, esa información se pierde."""
    a = agent(busy=PerformingAction(action=ActionId("act_libre"), ticks_remaining=1))
    a.advance()
    assert a.busy is not None
    assert a.busy.ticks_remaining == 0


def test_advance_does_not_mutate_the_previous_busy_object() -> None:
    """`Busy` es inmutable: avanzar crea uno nuevo. Si este test falla, alguien
    hizo `busy.ticks_remaining -= 1` y tienes un bug de aliasing esperando."""
    original = PerformingAction(action=ActionId("act_libre"), ticks_remaining=3)
    a = agent(busy=original)
    a.advance()
    assert original.ticks_remaining == 3


def test_advance_on_idle_agent_is_a_no_op() -> None:
    a = agent(busy=None)
    a.advance()
    assert a.busy is None


def test_is_idle_covers_both_none_and_exhausted() -> None:
    assert agent(busy=None).is_idle
    assert agent(
        busy=Traveling(
            destination=P2, intent=ActionId("act_libre"), next_hop=P2, ticks_remaining=0
        )
    ).is_idle
    assert not agent(
        busy=PerformingAction(action=ActionId("act_libre"), ticks_remaining=1)
    ).is_idle


# --- PASOS 6 y 7: mundo ------------------------------------------------------


def test_new_places_every_agent_at_its_start(pack: ContentPack) -> None:
    world = WorldState.new(pack, seed=42)
    assert world.tick == 0
    assert world.agents[AG1].at == P1


def test_new_gives_every_agent_every_need(pack: ContentPack) -> None:
    """Aunque el agente no la mencione. Un dict incompleto obliga a cada
    consumidor a inventarse un default, y acabarán siendo distintos."""
    world = WorldState.new(pack, seed=42)
    assert set(world.agents[AG1].needs) == {n.id for n in pack.needs}


def test_new_respects_initial_needs_override(pack: ContentPack) -> None:
    """El pack de prueba pone `initial_needs: {n1: 0.9}` para ag1."""
    world = WorldState.new(pack, seed=42)
    assert world.agents[AG1].needs[N1] == pytest.approx(0.9)


def test_new_starts_everyone_idle(pack: ContentPack) -> None:
    world = WorldState.new(pack, seed=42)
    assert all(a.is_idle for a in world.agents.values())


def test_agents_in_order_is_stable_across_runs(pack: ContentPack) -> None:
    first = [a.spec_id for a in WorldState.new(pack, seed=1).agents_in_order()]
    second = [a.spec_id for a in WorldState.new(pack, seed=99).agents_in_order()]
    assert first == second


def test_same_seed_gives_the_same_random_streams(pack: ContentPack) -> None:
    a = WorldState.new(pack, seed=7)
    b = WorldState.new(pack, seed=7)
    assert a.seed == b.seed == 7
    assert a.rng.stream("x", 1).random() == b.rng.stream("x", 1).random()


def test_travel_map_is_built_once(pack: ContentPack) -> None:
    world = WorldState.new(pack, seed=1)
    assert world.travel.distance(P1, P2) == 1


# --- disposición: quién es el agente AHORA -----------------------------------


def test_disposition_is_copied_into_the_state(pack: ContentPack) -> None:
    world = WorldState.new(pack, seed=1)
    state = world.agents[AG1]
    assert state.traits == {"t1": 0.5}
    assert state.tastes == {"p2": 1.2}
    assert state.need_weights[N1] > 0.0


def test_mutating_an_agent_never_touches_the_pack(pack: ContentPack) -> None:
    """`AgentSpec` es frozen, pero eso solo impide reasignar sus atributos: el
    dict de dentro sigue siendo mutable. Sin copiar, la deriva de un agente
    contaminaría el pack y con él cualquier otro mundo cargado del mismo
    fichero."""
    world = WorldState.new(pack, seed=1)
    world.agents[AG1].traits[T1] = -1.0
    world.agents[AG1].tastes["p2"] = 99.0

    limpio = WorldState.new(pack, seed=1)
    assert limpio.agents[AG1].traits == {"t1": 0.5}
    assert limpio.agents[AG1].tastes == {"p2": 1.2}


def test_two_worlds_from_the_same_pack_do_not_share_state(pack: ContentPack) -> None:
    a, b = WorldState.new(pack, seed=1), WorldState.new(pack, seed=1)
    a.agents[AG1].traits[T1] = -1.0
    assert b.agents[AG1].traits[T1] == 0.5


def test_drift_moves_the_trait_and_recomposes_the_weights(pack: ContentPack) -> None:
    """El invariante que justifica que exista `drift_trait`: `need_weights` es
    derivado de `traits`, y tocarlos por separado dejaría al agente decidiendo
    con los pesos de quien era antes."""
    world = WorldState.new(pack, seed=1)
    agent = world.agents[AG1]
    antes = agent.need_weights[N1]

    agent.drift_trait(pack, TraitId("t1"), +0.5)

    assert agent.traits[TraitId("t1")] == pytest.approx(1.0)
    assert agent.need_weights[N1] > antes


def test_drift_clamps_to_the_valid_range(pack: ContentPack) -> None:
    world = WorldState.new(pack, seed=1)
    agent = world.agents[AG1]

    agent.drift_trait(pack, TraitId("t1"), +99.0)
    assert agent.traits[TraitId("t1")] == 1.0
    agent.drift_trait(pack, TraitId("t1"), -99.0)
    assert agent.traits[TraitId("t1")] == -1.0


def test_drift_can_awaken_a_trait_the_agent_did_not_have() -> None:
    """Nadie nace con todos los rasgos del pack declarados. La experiencia puede
    despertar uno que estaba a cero."""
    data = base_pack()
    data["traits"] = [
        {"id": "t1", "label": "t1", "need_weight_multipliers": {"n1": 1.5}},
        {"id": "t2", "label": "t2", "need_weight_multipliers": {"n1": 0.5}},
    ]
    pack = ContentPack.model_validate(data)
    agent = WorldState.new(pack, seed=1).agents[AG1]
    assert TraitId("t2") not in agent.traits

    agent.drift_trait(pack, TraitId("t2"), +0.3)
    assert agent.traits[TraitId("t2")] == pytest.approx(0.3)


def test_drift_towards_an_undeclared_trait_fails_loudly(pack: ContentPack) -> None:
    """Un rasgo que no existe en el pack es una errata, no una capacidad
    emergente. Sin esta guarda, reventaría con un KeyError enterrado dentro de
    la composición de pesos."""
    agent = WorldState.new(pack, seed=1).agents[AG1]
    with pytest.raises(KeyError, match="inventado"):
        agent.drift_trait(pack, TraitId("inventado"), +0.3)
