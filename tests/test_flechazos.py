"""Atracción y ruptura: vínculos que empiezan de golpe y lazos que se acaban.

Dos cosas que el motor no sabía decir, y las dos salieron de mirar `confluencia`
antes de escribir nada:

- **Nadie podía gustar de nadie.** Los gustos sesgan instancias —un lugar, una
  acción— y desde la capa relacional podían apuntar a una persona, pero nadie
  los consultaba nunca hacia nadie: medido, los 704 gustos del pack apuntaban a
  lugares. Sin eso, quién se junta con quién lo decide la proximidad.
- **Una relación con nombre no se disolvía nunca**, que es lo que el README
  decía y valía mientras las únicas fueran de sangre y de oficio. Deja de valer
  con noviazgos: alguien a quien no ves desde hace meses no es tu novio, y
  sostener que lo es no es conservador, es falso.

La clave que hace compatibles el suelo de aprecio y el desamor: `regard_floor`
se aplica **al leer** (`regard_for`), así que el aprecio crudo sí puede caer. El
suelo gobierna cómo tratas a alguien mientras es tuyo; la ruptura, si lo sigue
siendo.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId, PlaceId, RelationId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

UNO = AgentId("uno")
DOS = AgentId("dos")
TRES = AgentId("tres")
P1 = PlaceId("p1")
VINCULO = NeedId("vinculo")
PAREJA = RelationId("pareja")


def cortejo_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.2},
        ],
        "traits": [
            {"id": "audaz", "label": "audaz"},
            {"id": "hosco", "label": "hosco"},
        ],
        "relations": [
            {"id": "pareja", "label": "pareja", "symmetric": True,
             "exclusive": True},
        ],
        "actions": [
            {"id": "cortejar", "label": "cortejar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
             "target": {"gives": {"vinculo": 0.15}, "acerca": 0.25,
                        "crea_relacion": "pareja"}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"]},
        ],
        "agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- gustar de alguien (D-086) -------------------------------------------------


def test_a_taste_can_point_at_a_trait() -> None:
    """La única clave que sirve para alguien que no estaba escrito en el YAML, y
    por tanto la única con la que la atracción sobrevive a la segunda
    generación."""
    pack = cortejo_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "tastes": [{"target": "audaz", "multiplier": 1.6}]},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1",
         "traits": {"audaz": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[UNO].afinidad(sim.state.agents[DOS]) == pytest.approx(1.6)


def test_it_scales_by_how_much_of_it_the_other_one_has() -> None:
    """Un umbral daría un escalón donde lo que hay es una gradación, y haría que
    0.49 y 0.51 fueran mundos distintos."""
    pack = cortejo_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "tastes": [{"target": "audaz", "multiplier": 1.6}]},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1",
         "traits": {"audaz": 0.5}},
    ]})
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[UNO].afinidad(sim.state.agents[DOS]) == pytest.approx(1.3)


def test_being_the_opposite_is_not_the_same_as_lacking_it() -> None:
    """Un rasgo con signo negativo dice que la persona es lo contrario, no que
    tenga menos de lo que a ti te gusta. Multiplicar por un negativo daría una
    atracción invertida que nadie pidió."""
    pack = cortejo_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "tastes": [{"target": "audaz", "multiplier": 1.6}]},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1",
         "traits": {"audaz": -0.8}},
    ]})
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[UNO].afinidad(sim.state.agents[DOS]) == pytest.approx(1.0)


def test_a_taste_can_still_point_at_one_person() -> None:
    pack = cortejo_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "tastes": [{"target": "dos", "multiplier": 2.0}]},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
    ]})
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[UNO].afinidad(sim.state.agents[DOS]) == pytest.approx(2.0)


def test_who_you_find_attractive_is_who_you_go_for() -> None:
    """La prueba de que sirve para algo: dos candidatos iguales en todo salvo en
    un rasgo, y uno de ellos gusta. A igualdad de aprecio —dos desconocidos, los
    dos a cero— antes desempataba el id."""
    pack = cortejo_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "tastes": [{"target": "audaz", "multiplier": 3.0}]},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1",
         "traits": {"hosco": 1.0}},
        {"id": "tres", "label": "Tres", "home": "p1", "start_at": "p1",
         "traits": {"audaz": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(4)
    assert sim.state.agents[UNO].relations.get(PAREJA) == {TRES}


def test_a_taste_towards_nothing_at_all_does_not_load() -> None:
    with pytest.raises(ValidationError, match="ni rasgo"):
        cortejo_pack(**{"agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
             "tastes": [{"target": "inexistente", "multiplier": 1.5}]},
            {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
        ]})


# --- vínculos que empiezan de golpe -------------------------------------------


def test_a_bond_can_jump_instead_of_being_cooked() -> None:
    sim = Simulation(cortejo_pack(), seed=1)
    sim.run(2)
    assert sim.state.agents[UNO].bonds[DOS].regard >= 0.25


def test_it_moves_both_because_both_were_there() -> None:
    sim = Simulation(cortejo_pack(), seed=1)
    sim.run(2)
    assert sim.state.agents[DOS].bonds[UNO].regard >= 0.25


def test_it_adds_on_top_of_what_was_already_there() -> None:
    """Al revés que `remember_company`, donde un suceso único casi no mueve a
    quien ya está cerca del premio."""
    sim = Simulation(cortejo_pack(), seed=1)
    for t in range(20):
        sim.state.agents[UNO].remember_company([DOS], premium=0.5, rate=0.4, tick=t)
    antes = sim.state.agents[UNO].bonds[DOS].regard
    sim.run(2)
    assert sim.state.agents[UNO].bonds[DOS].regard > antes


# --- lo que se acaba (D-087) ---------------------------------------------------


def rompible_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "relations": [
            {"id": "pareja", "label": "pareja", "symmetric": True,
             "exclusive": True, "regard_floor": 0.45,
             "se_rompe_sin_verse": 50, "se_rompe_bajo": -0.2},
            {"id": "hermano", "label": "hermano", "symmetric": True},
        ],
        "agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
             "relations": {"pareja": ["dos"], "hermano": ["dos"]}},
            {"id": "dos", "label": "Dos", "home": "p2", "start_at": "p2"},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"],
             "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["sitio"],
             "neighbors": {"p1": 1}},
        ],
        "actions": [
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return cortejo_pack(**data)


def test_whoever_you_have_not_seen_in_months_is_not_yours_anymore() -> None:
    sim = Simulation(rompible_pack(), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=-100)
    sim.run(1)
    assert not sim.state.agents[UNO].relations.get(PAREJA)
    assert not sim.state.agents[DOS].relations.get(PAREJA), "y del otro lado también"


def test_blood_does_not_break_no_matter_how_long() -> None:
    """La sangre no declara ninguna de las dos causas, y por eso sigue sin
    romperse jamás: lo decide el pack relación a relación, no el motor."""
    sim = Simulation(rompible_pack(), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=-100)
    sim.run(1)
    assert sim.state.agents[UNO].relations[RelationId("hermano")] == {DOS}


def test_losing_interest_breaks_it_even_with_a_floor() -> None:
    """El suelo gobierna cómo la tratas mientras es tuya; esto, si lo sigue
    siendo. Mirando el aprecio con el suelo puesto, una pareja con `regard_floor`
    no podría romperse jamás por desamor — que es justo lo que un suelo NO quiere
    decir."""
    sim = Simulation(rompible_pack(), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=0)
    sim.state.agents[UNO].bonds[DOS].regard = -0.5
    sim.run(2)
    assert not sim.state.agents[UNO].relations.get(PAREJA)


def test_the_floor_still_holds_while_it_lasts() -> None:
    sim = Simulation(rompible_pack(), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=0)
    sim.state.agents[UNO].bonds[DOS].regard = 0.0
    sim.run(1)
    aprecio = sim.state.agents[UNO].regard_for(
        DOS, sim.state.tick, 1.0, sim.state.agents[UNO].relation_floor(sim.pack, DOS)
    )
    assert aprecio == pytest.approx(0.45)


def test_breaking_it_is_announced() -> None:
    sim = Simulation(rompible_pack(), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=0)
    sim.state.agents[UNO].bonds[DOS].regard = -0.5
    sim.run(2)
    rotas = sim.log.of_kind(EventKind.RELATION_ENDED)
    assert [e.data["relation"] for e in rotas] == ["pareja"]


def test_once_it_is_broken_they_can_be_forgotten() -> None:
    """El orden importa y es el mecanismo: `forget_bonds` protege a los tuyos,
    así que mientras el lazo aguante nadie se olvida de nadie. Al romperlo antes
    del olvido, la protección se cae con él."""
    # Sin el lazo de hermano: mientras quede CUALQUIER relación con alguien,
    # sigue siendo de los tuyos y `forget_bonds` lo protege. Es correcto y
    # conviene verlo escrito -- una expareja que además es tu hermana no se te
    # olvida.
    sim = Simulation(rompible_pack(**{
        "tuning": {"bond_horizon": 60},
        "agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
             "relations": {"pareja": ["dos"]}},
            {"id": "dos", "label": "Dos", "home": "p2", "start_at": "p2"},
        ],
    }), seed=1)
    sim.state.agents[UNO].meet(DOS, tick=-100)
    sim.run(1)
    assert not sim.state.agents[UNO].relations.get(PAREJA), "primero deja de serlo"
    assert DOS not in sim.state.agents[UNO].bonds, "y en la misma ronda se olvida"


def test_a_world_where_nothing_breaks_pays_nothing_for_this() -> None:
    """Estrenar esto no puede mover ningún contrato ya medido."""
    pack = cortejo_pack()
    assert all(
        not r.se_rompe_sin_verse and r.se_rompe_bajo is None for r in pack.relations
    )
    sim = Simulation(pack, seed=1)
    assert not sim.se_rompen
    sim.run(50)
    assert len(sim.state.agents) == 2
