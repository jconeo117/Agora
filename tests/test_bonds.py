"""Tests de la capa relacional.

Sin esto el mundo está poblado pero no habitado: los agentes cuentan cabezas y
nunca saben de quién son. Un vecino con el que te cruzas cuarenta veces sigue
sin existir para ti.

El principio: **el vínculo es asimétrico y se gana**. Cada uno guarda el suyo,
nadie nace queriendo a nadie, y lo que mueve el aprecio no es la co-presencia
sino haber sacado algo de ella cuando hacía falta.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import candidates, companionship
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId
from agora.engine.outcome import company_premium, company_saturation
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState, Bond, WorldState
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
AG3 = AgentId("ag3")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
P3 = PlaceId("p3")
SOCIAL = ActionId("act_social")
LIBRE = ActionId("act_libre")


def bond_pack(**overrides: Any) -> ContentPack:
    """p1 en el centro, p2 y p3 a la misma distancia. Los tres son sociales.

    La simetría de p2 y p3 es lo que permite aislar el efecto del vínculo: si
    un agente prefiere uno de los dos, no puede ser por la distancia.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {
                "id": "n1",
                "label": "n1",
                "decay_per_tick": 0.01,
                "initial": 0.5,
                "urgency_exponent": 2.0,
            }
        ],
        "actions": [
            {
                "id": "act_social",
                "label": "act_social",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "requires_company": 1,
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.2},
                "effects_per_company": {"n1": 0.4},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {
                "id": "p1",
                "label": "p1",
                "affordances": ["aff"],
                "neighbors": {"p2": 2, "p3": 2},
            },
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 2}},
            {"id": "p3", "label": "p3", "affordances": ["aff"], "neighbors": {"p1": 2}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
            {"id": "ag3", "label": "ag3", "home": "p3", "start_at": "p3"},
        ],
        "tuning": {
            "sighting_horizon": 50,
            "critical_need_threshold": 0.0,
            "bond_rate": 0.3,
            "bond_scale": 0.05,
            "bond_weight": 1.0,
            "companionship_weight": 0.5,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agent_at(place: PlaceId = P1) -> AgentState:
    return AgentState(spec_id=AG1, at=place, needs={N1: 0.5})


# --- el vínculo como dato ----------------------------------------------------


def test_a_stranger_is_neutral_not_absent() -> None:
    """Lo ausente vale 0: ni atrae ni repele. Nadie nace odiando."""
    assert agent_at().regard_for(AG2, tick=0, fade=1.0) == 0.0


def test_meeting_someone_creates_the_bond() -> None:
    a = agent_at()
    a.meet(AG2, tick=5)
    assert a.bonds[AG2].encounters == 1
    assert a.bonds[AG2].last_seen == 5


def test_meeting_again_accumulates() -> None:
    """`encounters` responde lo único que el aprecio no puede: si os conocéis.

    Un aprecio de 0.0 es a la vez el desconocido y el vecino indiferente.
    """
    a = agent_at()
    a.meet(AG2, tick=5)
    a.meet(AG2, tick=9)
    assert a.bonds[AG2].encounters == 2
    assert a.bonds[AG2].last_seen == 9


def test_regard_fades_with_time_apart() -> None:
    bond = Bond(regard=1.0, last_seen=10)
    assert bond.regard_at(tick=10, fade=0.9) == pytest.approx(1.0)
    assert bond.regard_at(tick=13, fade=0.9) == pytest.approx(0.729)


def test_fade_of_one_never_forgets() -> None:
    bond = Bond(regard=1.0, last_seen=0)
    assert bond.regard_at(tick=10_000, fade=1.0) == 1.0


def test_a_bond_expires_entirely() -> None:
    """El segundo mecanismo de olvido, y el que acota el estado."""
    a = agent_at()
    a.meet(AG2, tick=10)
    a.forget_bonds(tick=59, horizon=50)
    assert AG2 in a.bonds
    a.forget_bonds(tick=61, horizon=50)
    assert AG2 not in a.bonds


def test_horizon_zero_never_forgets() -> None:
    a = agent_at()
    a.meet(AG2, tick=0)
    a.forget_bonds(tick=10**6, horizon=0)
    assert AG2 in a.bonds


# --- quién, no cuántos -------------------------------------------------------


def test_without_weight_the_world_is_anonymous() -> None:
    """A peso 0 la compañía vuelve a ser un recuento, que es como estaba."""
    a = agent_at()
    a.bonds[AG2] = Bond(regard=1.0)
    assert a.effective_company([AG2, AG3], tick=0, weight=0.0, fade=1.0) == 2.0


def test_a_valued_person_counts_for_more_than_a_stranger() -> None:
    a = agent_at()
    a.bonds[AG2] = Bond(regard=0.5)
    assert a.effective_company([AG2], tick=0, weight=1.0, fade=1.0) == pytest.approx(1.5)
    assert a.effective_company([AG3], tick=0, weight=1.0, fade=1.0) == pytest.approx(1.0)


def test_bad_company_subtracts() -> None:
    """Tres personas a las que detestas no son compañía, son un problema."""
    a = agent_at()
    for other in (AG2, AG3):
        a.bonds[other] = Bond(regard=-1.0)
    assert a.effective_company([AG2, AG3], tick=0, weight=1.0, fade=1.0) == 0.0


def test_saturation_is_signed_and_symmetric() -> None:
    """Sin firmar, la mala compañía solo podría no ayudar; nunca hacer daño."""
    assert company_saturation(-1.0) == pytest.approx(-0.5)
    assert company_saturation(-3.0) == pytest.approx(-0.75)
    assert company_saturation(-1.0) == pytest.approx(-company_saturation(1.0))


def test_saturation_unchanged_for_the_calibrated_range() -> None:
    """Firmarla no puede mover nada de lo ya calibrado."""
    for crowd in range(0, 10):
        assert company_saturation(float(crowd)) == pytest.approx(crowd / (crowd + 1))


def test_lonelier_than_alone() -> None:
    """Un cuarto con alguien a quien no soportas decae MÁS que un cuarto vacío."""
    specs = bond_pack(
        needs=[
            {
                "id": "n1",
                "label": "n1",
                "decay_per_tick": 0.02,
                "initial": 0.5,
                "company_relief": 0.02,
            }
        ]
    ).need_by_id

    solo, mala = agent_at(), agent_at()
    solo.decay(specs, company=0.0)
    mala.decay(specs, company=-2.0)
    assert mala.needs[N1] < solo.needs[N1]


# --- cómo se gana el aprecio -------------------------------------------------


def test_a_solitary_action_builds_nothing() -> None:
    """Estar en la misma sala mientras cada uno trabaja lo suyo no acerca."""
    pack = bond_pack()
    assert (
        company_premium(
            pack.action_by_id[LIBRE], pack.need_by_id, {N1: 1.0}, {N1: 0.5}, 3.0, 0.05
        )
        == 0.0
    )


def test_the_same_evening_is_worth_more_to_whoever_needed_it() -> None:
    """La afirmación central de este paso.

    Misma acción, misma gente, misma compañía. Lo único que cambia es cómo
    llegaba cada cual. De aquí sale que un agente sociable forme vínculos
    deprisa y uno con la necesidad cubierta apenas los forme — sin una sola
    regla escrita para ello.
    """
    pack = bond_pack()
    social = pack.action_by_id[SOCIAL]

    hambriento = company_premium(social, pack.need_by_id, {N1: 1.0}, {N1: 0.1}, 1.0, 0.05)
    saciado = company_premium(social, pack.need_by_id, {N1: 1.0}, {N1: 0.9}, 1.0, 0.05)
    assert hambriento > saciado * 5


def test_regard_moves_toward_what_the_evening_was_worth() -> None:
    a = agent_at()
    a.remember_company([AG2], premium=1.0, rate=0.5, tick=3)
    assert a.bonds[AG2].regard == pytest.approx(0.5)
    a.remember_company([AG2], premium=1.0, rate=0.5, tick=4)
    assert a.bonds[AG2].regard == pytest.approx(0.75)


def test_the_target_is_clamped() -> None:
    """El premio es una suma pesada sin techo natural; el aprecio sí lo tiene."""
    a = agent_at()
    for tick in range(50):
        a.remember_company([AG2], premium=17.0, rate=0.5, tick=tick)
    assert a.bonds[AG2].regard <= 1.0


def test_everyone_present_gets_the_same_credit() -> None:
    """No es simplificación: nadie sabe cuál de los cuatro hizo buena la velada.

    Lo que separa a unos de otros es la repetición, no el reparto.
    """
    a = agent_at()
    a.remember_company([AG2, AG3], premium=1.0, rate=0.5, tick=1)
    assert a.bonds[AG2].regard == a.bonds[AG3].regard


def test_repetition_is_what_separates_them() -> None:
    a = agent_at()
    for tick in range(10):
        a.remember_company([AG2, AG3], premium=1.0, rate=0.3, tick=tick)
    for tick in range(10, 30):
        a.remember_company([AG2], premium=1.0, rate=0.3, tick=tick)
    assert a.bonds[AG2].regard > a.bonds[AG3].regard


def test_rate_zero_disables_learning() -> None:
    a = agent_at()
    a.remember_company([AG2], premium=1.0, rate=0.0, tick=1)
    assert AG2 not in a.bonds


# --- cómo cambia la decisión -------------------------------------------------


def test_company_does_not_flatter_a_solitary_plan() -> None:
    """Sin el filtro, un agente preferiría dormir rodeado de gente."""
    pack = bond_pack()
    assert companionship(pack.action_by_id[LIBRE], company=5.0, weight=1.0) == 1.0


def test_a_fuller_place_is_more_appealing() -> None:
    """El punto ciego que esto cierra: antes, una persona y cinco puntuaban igual."""
    social = bond_pack().action_by_id[SOCIAL]
    assert companionship(social, 1.0, 1.0) < companionship(social, 5.0, 1.0)


def test_bad_company_repels() -> None:
    social = bond_pack().action_by_id[SOCIAL]
    assert companionship(social, -2.0, 1.0) < 1.0


def test_weight_zero_disables_it() -> None:
    social = bond_pack().action_by_id[SOCIAL]
    assert companionship(social, 5.0, 0.0) == 1.0


def test_he_goes_where_the_person_he_values_is() -> None:
    """El test que justifica el paso entero.

    Dos sitios a la misma distancia, misma acción, una persona en cada uno. La
    única diferencia es a quién aprecia.
    """
    world = WorldState.new(bond_pack(), seed=1)
    agent = world.agents[AG1]
    world.tick = 10
    agent.sightings[P2] = (10, frozenset({AG2}))
    agent.sightings[P3] = (10, frozenset({AG3}))
    agent.bonds[AG2] = Bond(regard=0.9, last_seen=10)

    scored = {d.place: d.utility for d in candidates(world, agent) if d.action == SOCIAL}
    assert scored[P2] > scored[P3]


def test_a_misanthrope_can_still_enter_a_crowded_bar() -> None:
    """La puerta dura cuenta CABEZAS, el atractivo cuenta personas.

    Confundirlas dejaría a quien detesta a todo el mundo sin poder pisar un
    sitio lleno, que no es lo que significa detestar a la gente.
    """
    world = WorldState.new(bond_pack(), seed=1)
    agent = world.agents[AG1]
    world.tick = 10
    agent.sightings[P2] = (10, frozenset({AG2}))
    agent.bonds[AG2] = Bond(regard=-1.0, last_seen=10)

    assert any(d.action == SOCIAL and d.place == P2 for d in candidates(world, agent))


# --- integración -------------------------------------------------------------


def test_a_run_produces_bonds_nobody_wrote() -> None:
    sim = Simulation(bond_pack(), seed=1)
    sim.run(300)
    formados = [
        (agent.spec_id, other, bond.regard)
        for agent in sim.state.agents_in_order()
        for other, bond in agent.bonds.items()
        if bond.regard != 0.0
    ]
    assert formados, "trescientos ticks de vida en común deberían dejar rastro"


def test_the_bond_is_asymmetric() -> None:
    """Cada uno guarda el suyo. Que A quiera a B más que B a A es lo normal.

    Con un vínculo compartido esto sería inexpresable, y es la mitad de lo que
    hace interesante a un mundo social.
    """
    sim = Simulation(bond_pack(), seed=1)
    sim.run(300)

    pares = [
        (
            sim.state.agents[a].bonds[b].regard,
            sim.state.agents[b].bonds[a].regard,
        )
        for a, b in ((AG1, AG2), (AG1, AG3), (AG2, AG3))
        if b in sim.state.agents[a].bonds and a in sim.state.agents[b].bonds
    ]
    assert any(uno != otro for uno, otro in pares)


def test_knowing_people_changes_the_behaviour() -> None:
    """La dirección depende del mundo; que la conducta cambie, no."""

    def trayectoria(weight: float) -> list[str]:
        sim = Simulation(
            bond_pack(
                tuning={
                    "sighting_horizon": 50,
                    "critical_need_threshold": 0.0,
                    "bond_rate": 0.3,
                    "bond_scale": 0.05,
                    "bond_weight": weight,
                    "companionship_weight": 0.5,
                }
            ),
            seed=1,
        )
        sim.run(300)
        return [f"{e.tick}:{e.kind}:{e.action}" for e in sim.log if e.actor == AG1]

    assert trayectoria(1.0) != trayectoria(0.0)


def test_the_tick_loop_forgets() -> None:
    """La rampancia, atajada donde tocaba: nadie acumula a todo el que vio.

    Un `<= 2` aquí no diría nada —solo hay tres agentes, así que se cumple sin
    olvidar nada—. Lo que hay que comprobar es que el bucle LLAMA al olvido, y
    eso se ve comparando: con horizonte corto, alguien que se conoció y luego se
    perdió de vista tiene que desaparecer del diccionario.
    """
    perilla = {
        "sighting_horizon": 50,
        "critical_need_threshold": 0.0,
        "bond_rate": 0.3,
        "bond_scale": 0.05,
        "bond_weight": 1.0,
    }

    def vinculos(horizon: int) -> int:
        sim = Simulation(bond_pack(tuning={**perilla, "bond_horizon": horizon}), seed=1)
        total = 0
        for _ in range(400):
            sim.tick()
            total += sum(len(a.bonds) for a in sim.state.agents_in_order())
        return total

    conocidos = vinculos(0)
    assert conocidos > 0, "sin nadie conocido el test no compara nada"
    assert vinculos(5) < conocidos
