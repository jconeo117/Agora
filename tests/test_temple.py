"""El temple: cuánto le duele a cada cual lo que gasta.

Quinto canal de un rasgo, y el espejo del que faltaba. La aptitud llevaba desde
F1.9 diciendo en su propio docstring lo que no sabía hacer — *"la aptitud escala
lo que se GANA, no lo que cuesta"*— y con eso quedaba fuera una familia entera de
criaturas: la que aguanta.

    need_weight_multipliers  ->  cuánto le IMPORTA
    gain_multipliers         ->  cuánto le CUNDE lo que gana
    cost_multipliers         ->  cuánto le DUELE lo que gasta

Lo pidió un sistema de maná. Una reserva grande no es más que *cada conjuro me
drena menos*; una afinidad de nacimiento frente a una aprendida es *lo mismo, más
barato*; y la resistencia de una raza al retroceso ambiental es esto sobre el eje
que el retroceso muerde.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.disposition import compose_costs, compose_gains
from agora.engine.ontology import AgentId, NeedId, PlaceId, SituationId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Ledger
from agora.engine.world import Simulation

MANA = NeedId("mana")
AG1 = AgentId("ag1")
P1 = PlaceId("p1")
ENANO = TraitId("enano")
TORMENTA = SituationId("tormenta")


def temple_pack(**overrides: Any) -> ContentPack:
    """`conjurar` cuesta maná. `enano` lo abarata; `frágil` lo encarece."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "mana", "label": "mana", "decay_per_tick": 0.001, "initial": 0.9,
             "max_debt": 0.5},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.01, "initial": 0.8},
        ],
        "traits": [
            {"id": "enano", "label": "enano", "cost_multipliers": {"mana": 0.5}},
            {"id": "fragil", "label": "fragil", "cost_multipliers": {"mana": 2.0}},
            {"id": "avido", "label": "avido", "gain_multipliers": {"mana": 2.0}},
        ],
        "actions": [
            {"id": "conjurar", "label": "conjurar", "duration_ticks": 1,
             "requires_affordance": "aff", "satisfies": {"n2": 1.0},
             "requires": {"mana": 0.2}, "costs": {"mana": 1.0},
             "effects": {"n2": 0.3, "mana": -0.2}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {}}
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agente(pack: ContentPack, **traits: float) -> AgentState:
    a = AgentState(spec_id=AG1, at=P1, needs={MANA: 0.9, NeedId("n2"): 0.8},
                   traits={TraitId(k): v for k, v in traits.items()})
    a.recompose(pack)
    return a


# --- la composición ----------------------------------------------------------


def test_without_traits_everything_costs_the_same() -> None:
    """Lo ausente vale 1.0: un pack que no lo declare se comporta igual que
    antes de que este canal existiera."""
    assert compose_costs(temple_pack(), {}) == {MANA: 1.0, NeedId("n2"): 1.0}


def test_a_trait_can_make_things_cheaper() -> None:
    costes = compose_costs(temple_pack(), {ENANO: 1.0})
    assert costes[MANA] == pytest.approx(0.5)
    assert costes[NeedId("n2")] == 1.0, "solo toca los ejes que declara"


def test_intensity_is_an_exponent_not_an_interpolation() -> None:
    """**De aquí sale gratis la afinidad de nacimiento frente a la aprendida.**

    Son el mismo rasgo a distinta intensidad: plena sale a la mitad, parcial a
    0.76. No hace falta un mecanismo separado para "aprendida cuesta más".
    """
    pack = temple_pack()
    assert compose_costs(pack, {ENANO: 1.0})[MANA] == pytest.approx(0.5)
    assert compose_costs(pack, {ENANO: 0.4})[MANA] == pytest.approx(0.5**0.4)
    assert compose_costs(pack, {ENANO: 0.0})[MANA] == pytest.approx(1.0)


def test_a_negative_intensity_inverts_it() -> None:
    """0 neutraliza y -1 invierte exactamente, como en los demás canales."""
    assert compose_costs(temple_pack(), {ENANO: -1.0})[MANA] == pytest.approx(2.0)


def test_traits_compose_by_multiplying() -> None:
    costes = compose_costs(temple_pack(), {ENANO: 1.0, TraitId("fragil"): 1.0})
    assert costes[MANA] == pytest.approx(1.0), "0.5 * 2.0 se cancelan"


def test_temper_and_aptitude_are_independent() -> None:
    """Las cuatro combinaciones describen criaturas distintas, y con un solo
    canal ninguna sería expresable. El enano almacena mucho y repone despacio."""
    pack = temple_pack()
    traits = {ENANO: 1.0}
    assert compose_costs(pack, traits)[MANA] == pytest.approx(0.5)
    assert compose_gains(pack, traits)[MANA] == pytest.approx(1.0)

    avido = {TraitId("avido"): 1.0}
    assert compose_costs(pack, avido)[MANA] == pytest.approx(1.0)
    assert compose_gains(pack, avido)[MANA] == pytest.approx(2.0)


# --- lo que se paga de verdad ------------------------------------------------


def test_a_hardy_agent_spends_less() -> None:
    pack = temple_pack()
    normal, enano = agente(pack), agente(pack, enano=1.0)
    for a in (normal, enano):
        a.apply({MANA: -0.2}, pack.need_by_id)
    assert normal.needs[MANA] == pytest.approx(0.7)
    assert enano.needs[MANA] == pytest.approx(0.8)


def test_a_frail_agent_spends_more() -> None:
    pack = temple_pack()
    fragil = agente(pack, fragil=1.0)
    fragil.apply({MANA: -0.2}, pack.need_by_id)
    assert fragil.needs[MANA] == pytest.approx(0.5)


def test_it_does_not_touch_what_is_gained() -> None:
    """El temple es del gasto. Lo que se gana ya tiene su canal, y confundirlos
    haría que "aguanto" significara "me repongo", que es otra criatura."""
    pack = temple_pack()
    enano = agente(pack, enano=1.0)
    enano.needs[MANA] = 0.3
    enano.apply({MANA: 0.2}, pack.need_by_id)
    assert enano.needs[MANA] == pytest.approx(0.5)


def test_the_ledger_records_what_was_really_paid() -> None:
    """Si el libro anotara lo nominal, la demanda del panel mentiría en cuanto
    una raza tuviera temple — y de ahí sale la columna oferta/demanda."""
    pack = temple_pack()
    enano = agente(pack, enano=1.0)
    enano.ledger = Ledger()
    enano.apply({MANA: -0.2}, pack.need_by_id)
    assert enano.ledger.demanda[MANA] == pytest.approx(0.1)


def test_the_debt_also_scales() -> None:
    """La deuda es lo que el suelo se habría comido, así que tiene que salir del
    gasto REAL. Es lo que hace que quemar reservas duela distinto según quién."""
    pack = temple_pack()
    normal, enano = agente(pack), agente(pack, enano=1.0)
    for a in (normal, enano):
        a.needs[MANA] = 0.1
        a.apply({MANA: -0.5}, pack.need_by_id)
    assert normal.debt[MANA] == pytest.approx(0.4)
    assert enano.debt[MANA] == pytest.approx(0.15)


def test_the_world_hurts_the_hardy_less() -> None:
    """La resistencia de una raza al retroceso ambiental: un enano bajo tierra
    sufre menos cuando alguien fuerza la Tierra cerca. No canaliza mejor — su
    cuerpo aguanta esas condiciones."""
    pack = temple_pack()
    normal, enano = agente(pack), agente(pack, enano=1.0)
    for a in (normal, enano):
        a.endure({MANA: -0.2}, pack.need_by_id)
    assert enano.needs[MANA] > normal.needs[MANA]


# --- en un mundo corriendo ----------------------------------------------------


def test_a_reserve_lasts_longer_in_practice() -> None:
    """La prueba que importa: dos agentes con la misma ficha salvo el temple
    viven distinto. El de reserva grande conjura sin vaciarse."""
    pack = temple_pack(
        **{
            "agents": [
                {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
                {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1",
                 "traits": {"enano": 1.0}},
            ]
        }
    )
    sim = Simulation(pack, seed=7)
    sim.run(120)
    normal = sim.state.agents[AG1].needs[MANA]
    enano = sim.state.agents[AgentId("ag2")].needs[MANA]
    assert enano > normal


def test_packs_without_the_channel_are_untouched() -> None:
    """La garantía que permite estrenarlo sin mover ningún contrato medido."""
    pack = temple_pack()
    a = agente(pack)
    assert all(v == 1.0 for v in a.costs.values())
    a.apply({MANA: -0.3}, pack.need_by_id)
    assert a.needs[MANA] == pytest.approx(0.6)
