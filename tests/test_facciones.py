"""Facciones: grupos con identidad propia, fundados por quien vive dentro.

**Lo que un grupo NO es: un rasgo compartido.** `enano` y `guerrero` ya reparten
a la población y ya gatean acciones, y les falta exactamente lo que hace que un
grupo sea un grupo — identidad propia, gente que entra y sale, cosas que posee, e
intereses que chocan con los de otro. Un número en una ficha no puede tener nada
de eso.

**El pack declara CLASES, el mundo tiene grupos.** Es el mismo reparto que ya
rige en otras dos capas: el pack dice qué es una `pareja` y el mundo dice quién
es pareja de quién; el pack dice qué es una DEUDA y el mundo quién le debe a
quién. Aquí el pack dice qué es un gremio y el mundo cuáles hay — que es lo que
hace posible que EMERJAN, empezando por un mundo sin ninguno.

**Pertenecer es tener lealtad**, literalmente: la clave de `AgentState.lealtad`
ES la pertenencia. Un solo sitio para las dos preguntas —si eres de los suyos, y
cuánto— porque son la misma, y con dos estructuras habría un estado en que una
dice que sí y la otra que no.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    FactionKindId,
    NeedId,
    PlaceId,
)
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

UNO = AgentId("uno")
DOS = AgentId("dos")
TRES = AgentId("tres")
P1 = PlaceId("p1")
GREMIO = FactionKindId("gremio")
VINCULO = NeedId("vinculo")


def gremio_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.2},
        ],
        "faction_kinds": [
            {"id": "gremio", "label": "gremio", "company_multiplier": 1.8,
             "lealtad_inicial": 0.5},
        ],
        "actions": [
            {"id": "fundar", "label": "fundar", "duration_ticks": 1,
             "requires_affordance": "sitio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "funda_faccion": "gremio"},
            {"id": "trabajar_para_el_gremio", "label": "trabajar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_faccion": "gremio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.10},
             "lealtad": 0.1},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [{"id": "p1", "label": "p1", "affordances": ["sitio"]}],
        "agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- nacer (D-090) -------------------------------------------------------------


def test_a_world_can_start_with_no_groups_and_end_with_some() -> None:
    """El pack no declara ni un grupo: declara qué ES un gremio."""
    sim = Simulation(gremio_pack(), seed=1)
    assert sim.state.facciones == {}
    sim.run(4)
    assert sim.state.facciones, "nadie fundó nada"
    fundada = next(iter(sim.state.facciones.values()))
    assert fundada.tipo == GREMIO
    assert fundada.fundador is not None


def test_the_founder_is_inside_from_the_first_moment() -> None:
    sim = Simulation(gremio_pack(), seed=1)
    for _ in range(6):
        sim.run(1)
        if sim.state.facciones:
            break
    cual, faccion = next(iter(sim.state.facciones.items()))
    assert faccion.fundador is not None
    # Con la lealtad de entrada exacta: trabajar para ellos la sube después.
    assert sim.state.agents[faccion.fundador].lealtad[cual] == pytest.approx(0.5)


def test_the_id_does_not_come_from_a_counter() -> None:
    """La lección de D-065 y D-071 por tercera vez: un contador depende del orden
    en que se resuelvan los agentes, y ese orden depende de quién estaba dónde."""
    uno = Simulation(gremio_pack(), seed=3)
    uno.run(6)
    otro = Simulation(gremio_pack(), seed=3)
    otro.run(6)
    assert sorted(uno.state.facciones) == sorted(otro.state.facciones)


def test_an_exclusive_kind_is_founded_only_once_per_head() -> None:
    """Fundar un segundo país no puede ser el efecto colateral de una acción."""
    pack = gremio_pack(**{"faction_kinds": [
        {"id": "gremio", "label": "pais", "exclusive": True},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(30)
    for agente in sim.state.agents.values():
        assert len(sim.state.facciones_de(agente, GREMIO)) <= 1


def test_belonging_is_having_loyalty_and_there_is_no_second_list() -> None:
    sim = Simulation(gremio_pack(), seed=1)
    sim.run(4)
    cual = next(iter(sim.state.facciones))
    esperados = sorted(a for a, ag in sim.state.agents.items() if cual in ag.lealtad)
    assert sim.state.miembros_de(cual) == esperados


# --- que pertenecer importe ----------------------------------------------------


def test_an_outsider_cannot_do_what_the_group_does() -> None:
    """Si pertenecer no cierra ni abre una puerta, el grupo es decoración."""
    pack = gremio_pack(**{"actions": [
        {"id": "trabajar_para_el_gremio", "label": "trabajar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_faccion": "gremio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30}},
        {"id": "fundar", "label": "fundar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_traits": {"jefe": 0.5},
         "satisfies": {"vinculo": 0.2}, "effects": {"vinculo": 0.05},
         "funda_faccion": "gremio"},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ], "traits": [{"id": "jefe", "label": "jefe"}], "agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
         "traits": {"jefe": 1.0}},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(20)
    hechas = sim.log.recuento.por_agente_accion
    assert "trabajar_para_el_gremio" not in {
        str(a) for a in hechas.get(DOS, {})
    }, "el de fuera hizo lo del gremio"


def test_loyalty_gates_what_a_newcomer_cannot_do_yet() -> None:
    """El rango interno sin declarar rangos."""
    pack = gremio_pack(**{"actions": [
        {"id": "fundar", "label": "fundar", "duration_ticks": 1,
         "requires_affordance": "sitio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "funda_faccion": "gremio"},
        {"id": "trabajar_para_el_gremio", "label": "presidir", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_faccion": "gremio",
         "requires_lealtad": 0.95,
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(6)
    assert sim.state.facciones, "fundó"
    hechas = {str(a) for acc in sim.log.recuento.por_agente_accion.values() for a in acc}
    assert "trabajar_para_el_gremio" not in hechas, "un recién llegado no preside"


def test_working_for_them_raises_your_loyalty() -> None:
    sim = Simulation(gremio_pack(), seed=1)
    sim.run(4)
    cual = next(iter(sim.state.facciones))
    quien = sim.state.facciones[cual].fundador
    assert quien is not None
    sim.run(30)
    assert sim.state.agents[quien].lealtad[cual] > 0.5


def test_theirs_is_worth_more_company_than_a_stranger() -> None:
    """Espejo de `RelationSpec.company_multiplier` un escalón más arriba, y se
    componen."""
    sim = Simulation(gremio_pack(), seed=1)
    sim.run(4)
    cual = next(iter(sim.state.facciones))
    uno, dos = sim.state.agents[UNO], sim.state.agents[DOS]
    uno.lealtad[cual] = 0.5
    dos.lealtad.pop(cual, None)
    solo_aprecio = uno.effective_company([DOS], 0, 0.5, 1.0, sim.pack, sim.state)
    dos.lealtad[cual] = 0.5
    con_gremio = uno.effective_company([DOS], 0, 0.5, 1.0, sim.pack, sim.state)
    assert con_gremio == pytest.approx(solo_aprecio * 1.8)


# --- reclutar, salirse y enemistarse -------------------------------------------


def recluta_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "actions": [
            {"id": "fundar", "label": "fundar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_traits": {"jefe": 0.5},
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "funda_faccion": "gremio"},
            {"id": "trabajar_para_el_gremio", "label": "reclutar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "requires_faccion": "gremio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "target": {"gives": {"vinculo": 0.1}, "suma_a_faccion": "gremio"}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "traits": [{"id": "jefe", "label": "jefe"}],
        "agents": [
            {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1",
             "traits": {"jefe": 1.0}},
            {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return gremio_pack(**data)


def test_a_member_can_bring_somebody_in() -> None:
    sim = Simulation(recluta_pack(), seed=1)
    sim.run(10)
    cual = next(iter(sim.state.facciones))
    assert sim.state.miembros_de(cual) == [DOS, UNO]


def test_a_recruiter_who_belongs_to_nothing_recruits_nobody() -> None:
    """Quien recluta es quien ya está dentro."""
    pack = recluta_pack(**{"agents": [
        {"id": "uno", "label": "Uno", "home": "p1", "start_at": "p1"},
        {"id": "dos", "label": "Dos", "home": "p1", "start_at": "p1"},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(20)
    assert sim.state.facciones == {}, "nadie tenía el rasgo para fundar"
    assert not any(a.lealtad for a in sim.state.agents.values())


def test_loyalty_cools_down_and_you_end_up_out() -> None:
    """Sin esto, entrar una vez es ser de los suyos para siempre — el mismo error
    que las parejas eternas de antes de D-087."""
    pack = gremio_pack(**{"faction_kinds": [
        {"id": "gremio", "label": "gremio", "lealtad_inicial": 0.3,
         "lealtad_por_tick": 0.02, "lealtad_minima": 0.1},
    ], "actions": [
        {"id": "fundar", "label": "fundar", "duration_ticks": 1,
         "requires_affordance": "sitio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "funda_faccion": "gremio"},
        {"id": "trabajar_para_el_gremio", "label": "trabajar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_faccion": "gremio",
         "satisfies": {"vinculo": 0.01}, "effects": {"vinculo": 0.001},
         "lealtad": 0.05},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(3)
    cual = next(iter(sim.state.facciones))
    quien = sim.state.facciones[cual].fundador
    assert quien is not None
    sim.run(60)
    assert cual not in sim.state.agents[quien].lealtad
    assert sim.log.of_kind(EventKind.FACTION_LEFT)


def test_hitting_somebody_of_another_group_sets_the_two_at_odds() -> None:
    """En un mundo donde los grupos los funda la gente, quién odia a quién es lo
    que la simulación descubre."""
    pack = gremio_pack(**{"actions": [
        {"id": "fundar", "label": "fundar", "duration_ticks": 1,
         "requires_affordance": "sitio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "funda_faccion": "gremio"},
        {"id": "trabajar_para_el_gremio", "label": "asaltar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_company": 1,
         "requires_faccion": "gremio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "target": {"gives": {"vinculo": -0.1}, "otra_faccion": "gremio",
                    "enemista": True}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(30)
    assert len(sim.state.facciones) >= 2, "hacen falta dos para enemistarse"
    enfrentadas = [f for f in sim.state.facciones.values() if f.enemigas]
    assert enfrentadas, "nadie se enemistó con nadie"
    assert sim.log.of_kind(EventKind.FACTIONS_AT_ODDS)


def test_another_group_is_not_the_same_as_no_group() -> None:
    """`otra_faccion` no es la negación de `misma_faccion`: quien no pertenece a
    ninguno tampoco vale. Un asalto entre gremios pide que haya DOS gremios, no
    que al otro le falte el tuyo."""
    sim = Simulation(recluta_pack(), seed=1)
    sim.run(4)
    cual = next(iter(sim.state.facciones))
    uno, dos = sim.state.agents[UNO], sim.state.agents[DOS]
    uno.lealtad, dos.lealtad = {cual: 0.5}, {}
    destino = sim.pack.action_by_id[ActionId("trabajar_para_el_gremio")].target
    assert destino is not None
    solo_otra = destino.model_copy(update={"suma_a_faccion": None, "otra_faccion": GREMIO})
    assert not uno._pasa_las_de_faccion(dos, solo_otra, sim.state), (
        "sin grupo propio no es de otro grupo"
    )
    solo_misma = destino.model_copy(update={"suma_a_faccion": None, "misma_faccion": GREMIO})
    assert not uno._pasa_las_de_faccion(dos, solo_misma, sim.state)


# --- lo que el pack no puede declarar ------------------------------------------


def test_a_kind_nothing_founds_does_not_load() -> None:
    """En un mundo donde los grupos los funda la gente, una clase sin acción que
    la funde no puede existir jamás."""
    with pytest.raises(ValidationError, match="no puede existir nunca"):
        gremio_pack(**{"actions": [
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ]})


def test_a_kind_nobody_looks_at_does_not_load() -> None:
    with pytest.raises(ValidationError, match="pertenecer no cambia nada"):
        gremio_pack(**{"faction_kinds": [
            {"id": "gremio", "label": "gremio"},
        ], "actions": [
            {"id": "fundar", "label": "fundar", "duration_ticks": 1,
             "requires_affordance": "sitio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "funda_faccion": "gremio"},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ]})


def test_weighing_more_as_company_is_already_changing_decisions() -> None:
    """Que la compañía de los tuyos pese más YA cambia decisiones, sin que
    ninguna acción la nombre: es el mismo argumento por el que los `effects` de
    una situación cuentan como hacer algo."""
    gremio_pack(**{"faction_kinds": [
        {"id": "gremio", "label": "gremio", "company_multiplier": 1.8},
    ], "actions": [
        {"id": "fundar", "label": "fundar", "duration_ticks": 1,
         "requires_affordance": "sitio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "funda_faccion": "gremio"},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})


def test_moving_loyalty_without_saying_which_group_does_not_load() -> None:
    with pytest.raises(ValidationError, match="no hay grupo en el que moverla"):
        gremio_pack(**{"actions": [
            {"id": "fundar", "label": "fundar", "duration_ticks": 1,
             "requires_affordance": "sitio", "lealtad": 0.2,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "funda_faccion": "gremio"},
            {"id": "trabajar_para_el_gremio", "label": "t", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_faccion": "gremio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.10}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ]})


# --- persistencia ----------------------------------------------------------------


def test_groups_founded_in_play_survive_save_and_resume(tmp_path: Any) -> None:
    """No hay `FactionSpec` en el pack del que reconstruirlos —el pack solo
    declara CLASES— así que o se guardan enteros o al reanudar no existen."""
    sim = Simulation(gremio_pack(), seed=1)
    sim.run(6)
    antes = {f: (v.tipo, v.fundador) for f, v in sim.state.facciones.items()}
    lealtades = {a: dict(ag.lealtad) for a, ag in sim.state.agents.items()}
    sim.save(tmp_path / "s.json")

    otra = Simulation.resume(tmp_path / "s.json", gremio_pack())
    assert {f: (v.tipo, v.fundador) for f, v in otra.state.facciones.items()} == antes
    assert {a: dict(ag.lealtad) for a, ag in otra.state.agents.items()} == lealtades
