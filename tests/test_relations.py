"""Tests de las relaciones con nombre.

**Un vínculo es lo que sientes; una relación es lo que ERES de alguien.** Toda
la suite gira alrededor de esa frase:

- `Bond` es emergente, asimétrico, gradual y se olvida.
- Una relación es un HECHO: no crece con el trato, no se disuelve por dejar de
  verse, y sigue ahí el día que detestas a tu hermano.

Meterlo dentro de `Bond` habría hecho imposible justamente eso: un aprecio con
nombre se disolvería con el aprecio.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, RelationId
from agora.engine.pack import ContentPack
from agora.engine.state import Bond, WorldState
from agora.engine.world import Simulation

PAREJA = RelationId("pareja")
HERMANO = RelationId("hermano")
MAESTRO = RelationId("maestro")
DISCIPULO = RelationId("discipulo")
AG1, AG2, AG3 = AgentId("ag1"), AgentId("ag2"), AgentId("ag3")
CASA = PlaceId("casa")
VINCULO = NeedId("vinculo")
CENAR = ActionId("cenar_en_familia")


def rel_pack(**overrides: Any) -> ContentPack:
    """Tres personas: ag1 y ag2 pareja, ag3 suelto."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.01, "initial": 0.5},
        ],
        "relations": [
            {"id": "pareja", "label": "pareja", "symmetric": True, "exclusive": True,
             "regard_floor": 0.5, "company_multiplier": 2.0},
            {"id": "hermano", "label": "hermano", "symmetric": True},
            {"id": "maestro", "label": "maestro", "inverse": "discipulo"},
            {"id": "discipulo", "label": "discipulo", "inverse": "maestro"},
        ],
        "actions": [
            {"id": "charlar", "label": "charlar", "duration_ticks": 2,
             "satisfies": {"vinculo": 0.9}, "effects": {"vinculo": 0.3}},
            {"id": "cenar_en_familia", "label": "cenar en familia", "duration_ticks": 2,
             "requires_relation": "pareja",
             "satisfies": {"vinculo": 0.9}, "effects": {"vinculo": 0.6}},
        ],
        "places": [
            {"id": "casa", "label": "casa", "neighbors": {"calle": 1}},
            {"id": "calle", "label": "calle", "neighbors": {"casa": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
             "relations": {"pareja": ["ag2"]}},
            {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
            {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
        ],
        "tuning": {"bond_weight": 1.0, "bond_fade": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- el otro lado se cierra solo ---------------------------------------------


def test_a_symmetric_relation_is_declared_once() -> None:
    """Obligar al pack a escribirlo dos veces garantizaría que falte una. Un
    mundo donde A es hermano de B pero B no lo es de A no falla en ninguna
    parte: solo se comporta raro."""
    world = WorldState.new(rel_pack(), seed=1)
    assert world.agents[AG1].related_to(AG2) == (PAREJA,)
    assert world.agents[AG2].related_to(AG1) == (PAREJA,)


def test_a_directed_relation_creates_its_inverse() -> None:
    """Maestro de un lado, discípulo del otro."""
    pack = rel_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
             "relations": {"maestro": ["ag2"]}},
            {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
            {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
        ]
    )
    world = WorldState.new(pack, seed=1)
    assert world.agents[AG1].related_to(AG2) == (MAESTRO,)
    assert world.agents[AG2].related_to(AG1) == (DISCIPULO,)


def test_it_closes_both_sides_at_runtime_too() -> None:
    """Casarse en marcha tiene que dejar el mundo igual de coherente que
    declararlo. Es la puerta por la que entrará nacer."""
    sim = Simulation(rel_pack(), seed=1)
    sim.begin_relation(AG2, AG3, HERMANO)
    assert HERMANO in sim.state.agents[AG3].related_to(AG2)


def test_breaking_it_breaks_both_sides() -> None:
    sim = Simulation(rel_pack(), seed=1)
    sim.end_relation(AG1, AG2, PAREJA)
    assert sim.state.agents[AG1].related_to(AG2) == ()
    assert sim.state.agents[AG2].related_to(AG1) == ()


# --- lo que la distingue de un vínculo ---------------------------------------


def test_a_relation_is_not_forgotten() -> None:
    """LA prueba de que esto es otra cosa. Un hermano al que no ves en un año
    sigue siendo tu hermano; si `forget_bonds` lo borrase, la relación se
    evaporaría por no usarla y sería un aprecio con nombre."""
    world = WorldState.new(rel_pack(), seed=1)
    uno = world.agents[AG1]
    uno.bonds[AG2] = Bond(regard=0.8, last_seen=0)
    uno.bonds[AG3] = Bond(regard=0.8, last_seen=0)

    uno.forget_bonds(tick=100_000, horizon=96)
    assert AG2 in uno.bonds, "a la pareja no se le olvida"
    assert AG3 not in uno.bonds, "al conocido sí"


def test_the_floor_holds_the_regard_up() -> None:
    """La familia se aguanta: el aprecio sigue subiendo y bajando, pero no cae
    por debajo del suelo."""
    world = WorldState.new(rel_pack(), seed=1)
    uno = world.agents[AG1]
    uno.bonds[AG2] = Bond(regard=-0.9)

    assert uno.regard_for(AG2, 0, 1.0) == pytest.approx(-0.9)  # lo que siente
    suelo = uno.relation_floor(world.pack, AG2)
    assert uno.regard_for(AG2, 0, 1.0, suelo) == pytest.approx(0.5)


def test_no_floor_is_not_a_floor_at_zero() -> None:
    """Costó un test: un suelo en cero aplastaría el aprecio negativo, y sería
    imposible detestar a un hermano."""
    world = WorldState.new(rel_pack(), seed=1)
    uno = world.agents[AG1]
    sim = Simulation(rel_pack(), seed=1)
    sim.begin_relation(AG1, AG3, HERMANO)  # `hermano` no declara suelo
    uno = sim.state.agents[AG1]
    uno.bonds[AG3] = Bond(regard=-0.7)

    assert uno.relation_floor(sim.pack, AG3) is None
    assert uno.regard_for(AG3, 0, 1.0, uno.relation_floor(sim.pack, AG3)) == pytest.approx(-0.7)


def test_being_one_of_yours_weighs_more_than_liking_them() -> None:
    """`company_multiplier`: es la diferencia entre apreciar a alguien y que ese
    alguien sea de los tuyos."""
    world = WorldState.new(rel_pack(), seed=1)
    uno = world.agents[AG1]
    uno.bonds[AG2] = Bond(regard=0.5)
    uno.bonds[AG3] = Bond(regard=0.5)  # mismo aprecio, pero no es de los suyos

    con_pareja = uno.effective_company([AG2], 0, 1.0, 1.0, world.pack)
    con_extrano = uno.effective_company([AG3], 0, 1.0, 1.0, world.pack)
    assert con_pareja == pytest.approx(3.0)  # (1 + 1*0.5) * 2.0
    assert con_extrano == pytest.approx(1.5)


def test_without_a_pack_it_behaves_exactly_as_before() -> None:
    """La capa entera es opcional: un mundo sin relaciones no se entera."""
    world = WorldState.new(rel_pack(), seed=1)
    uno = world.agents[AG1]
    uno.bonds[AG2] = Bond(regard=0.5)
    assert uno.effective_company([AG2], 0, 1.0, 1.0) == pytest.approx(1.5)


# --- la puerta dura -----------------------------------------------------------


def test_it_asks_who_not_how_many() -> None:
    """`requires_relation` frente a `requires_company`, y es toda la gracia:
    cenar en familia no se arregla con más gente."""
    from agora.agents.decide import is_available

    pack = rel_pack()
    world = WorldState.new(pack, seed=1)
    cenar, casa = pack.action_by_id[CENAR], pack.place_by_id[CASA]
    needs = {VINCULO: 0.5}
    uno = world.agents[AG1]

    assert is_available(cenar, casa, 1, needs, None, None, (), uno.kin_present([AG2]))
    assert not is_available(cenar, casa, 9, needs, None, None, (), uno.kin_present([AG3]))


def test_not_knowing_who_is_there_resolves_in_favour() -> None:
    """Mismo convenio que la compañía: `None` es 'no lo sé' y va a mirar."""
    from agora.agents.decide import is_available

    pack = rel_pack()
    cenar, casa = pack.action_by_id[CENAR], pack.place_by_id[CASA]
    assert is_available(cenar, casa, None, {VINCULO: 0.5}, None, None, (), None)


def test_the_gate_produces_visible_behaviour() -> None:
    """Sin puerta, tener pareja solo tintaría números. Con ella hay cosas que
    solo existen si esa persona está."""
    sim = Simulation(rel_pack(), seed=1)
    sim.run(400)
    hechas = sim.log.recuento.por_agente_accion
    assert hechas[AG1][CENAR] > 0, "la pareja cena junta"
    assert CENAR not in hechas.get(AG3, {}), "ag3 no tiene con quien"


# --- aprecio de partida -------------------------------------------------------


def test_initial_bonds_give_the_world_a_past() -> None:
    """Sin esto, cualquier mundo empezaba con todos siendo desconocidos y las
    primeras semanas eran el mundo presentándose."""
    pack = rel_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
             "initial_bonds": {"ag2": 0.7, "ag3": -0.4}},
            {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
            {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
        ]
    )
    world = WorldState.new(pack, seed=1)
    uno = world.agents[AG1]
    assert uno.regard_for(AG2, 0, 1.0) == pytest.approx(0.7)
    assert uno.regard_for(AG3, 0, 1.0) == pytest.approx(-0.4)
    assert world.agents[AG2].regard_for(AG1, 0, 1.0) == 0.0, "asimétrico, como siempre"


def test_two_siblings_can_hate_each_other() -> None:
    """Una relación dice QUÉ son el uno del otro; el aprecio dice CÓMO se llevan,
    y a menudo no coincide."""
    pack = rel_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
             "relations": {"hermano": ["ag2"]}, "initial_bonds": {"ag2": -0.8}},
            {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
            {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
        ]
    )
    world = WorldState.new(pack, seed=1)
    uno = world.agents[AG1]
    assert uno.related_to(AG2) == (HERMANO,)
    assert uno.regard_for(AG2, 0, 1.0, uno.relation_floor(world.pack, AG2)) < 0


# --- lo que se habría roto sin cuidarlo ---------------------------------------


def test_relations_are_read_in_order() -> None:
    """Los multiplicadores se multiplican entre sí y los floats no son
    asociativos. Tercera vez que ese par asoma en este motor."""
    sim = Simulation(rel_pack(), seed=1)
    sim.begin_relation(AG1, AG2, HERMANO)
    quienes = sim.state.agents[AG1].related_to(AG2)
    assert quienes == tuple(sorted(quienes)) == (HERMANO, PAREJA)


def test_beginning_and_ending_leave_an_event() -> None:
    sim = Simulation(rel_pack(), seed=1)
    sim.begin_relation(AG2, AG3, HERMANO)
    sim.end_relation(AG2, AG3, HERMANO)

    inicio = sim.log.of_kind(EventKind.RELATION_BEGAN)
    fin = sim.log.of_kind(EventKind.RELATION_ENDED)
    assert [(e.actor, e.subject, e.data["relation"]) for e in inicio] == [
        (AG2, AG3, "hermano")
    ]
    assert [e.data["relation"] for e in fin] == ["hermano"]


def test_relations_survive_a_save(tmp_path: Path) -> None:
    """Y sobre todo las que NACIERON en la partida, que son las interesantes:
    cerrarlas desde el pack al cargar recuperaría solo lo declarado."""
    destino = tmp_path / "partida.json"
    sim = Simulation(rel_pack(), seed=1)
    sim.run(50)
    sim.begin_relation(AG2, AG3, HERMANO)
    sim.save(destino)

    vuelto = Simulation.resume(destino, rel_pack())
    assert vuelto.state.agents[AG1].related_to(AG2) == (PAREJA,)
    assert vuelto.state.agents[AG2].related_to(AG3) == (HERMANO,)
    assert vuelto.state.agents[AG3].related_to(AG2) == (HERMANO,)


# --- validación ---------------------------------------------------------------


def test_nobody_has_two_partners() -> None:
    """No es una regla moral: es el invariante que va a sostener la
    descendencia. Dos parejas es un árbol que deja de poder leerse."""
    with pytest.raises(ValidationError, match="exclusiva"):
        rel_pack(
            agents=[
                {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
                 "relations": {"pareja": ["ag2", "ag3"]}},
                {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
                {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
            ]
        )


def test_two_people_cannot_claim_the_same_partner() -> None:
    """El caso que de verdad se comete, y solo se ve tras cerrar las simetrías."""
    with pytest.raises(ValidationError, match="exclusiva"):
        rel_pack(
            agents=[
                {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
                 "relations": {"pareja": ["ag2"]}},
                {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle",
                 "relations": {"pareja": ["ag2"]}},
                {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
            ]
        )


def test_marrying_twice_at_runtime_is_refused() -> None:
    sim = Simulation(rel_pack(), seed=1)
    with pytest.raises(ValueError, match="exclusiva"):
        sim.begin_relation(AG1, AG3, PAREJA)


def test_inverses_must_agree() -> None:
    """Lo que peor falla a ojo: el mundo se construye sin protestar y queda
    medio torcido."""
    with pytest.raises(ValidationError, match="no dice lo mismo"):
        rel_pack(
            relations=[
                {"id": "pareja", "label": "pareja", "symmetric": True},
                {"id": "maestro", "label": "maestro", "inverse": "discipulo"},
                {"id": "discipulo", "label": "discipulo"},
            ]
        )


def test_symmetric_and_inverse_are_exclusive() -> None:
    with pytest.raises(ValidationError, match="es simétrica y además"):
        rel_pack(
            relations=[
                {"id": "pareja", "label": "pareja", "symmetric": True,
                 "inverse": "hermano"},
                {"id": "hermano", "label": "hermano", "symmetric": True},
            ]
        )


def test_nobody_is_their_own_relative() -> None:
    with pytest.raises(ValidationError, match="lo es de sí mismo"):
        rel_pack(
            agents=[
                {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
                 "relations": {"hermano": ["ag1"]}},
                {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
                {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
            ]
        )


def test_an_unknown_agent_in_a_relation_is_caught() -> None:
    with pytest.raises(ValidationError, match="agente desconocido"):
        rel_pack(
            agents=[
                {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa",
                 "relations": {"hermano": ["nadie"]}},
                {"id": "ag2", "label": "ag2", "home": "casa", "start_at": "casa"},
                {"id": "ag3", "label": "ag3", "home": "calle", "start_at": "calle"},
            ]
        )


def test_a_relation_that_does_nothing_is_legitimate() -> None:
    """Lo que la separa de una situación. Una situación que no afecta a nada es
    contenido muerto; aquí el hecho ya vale por sí solo — es lo que el narrador
    necesita saber y lo que la descendencia va a leer."""
    pack = rel_pack()
    assert pack.relation_by_id[HERMANO].regard_floor is None
    assert pack.relation_by_id[HERMANO].company_multiplier == 1.0
    WorldState.new(pack, seed=1)  # y no protesta
