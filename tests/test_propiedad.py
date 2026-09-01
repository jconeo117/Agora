"""Propiedad: quién tiene qué, y lo que le rinde.

**Por qué una sola forma para cinco clases.** Un lugar, un objeto, un título,
una deuda y una persona no tienen nada en común salvo que alguien puede
tenerlos — y precisamente por eso el motor no necesita cinco primitivas: solo
dos formas de rendir. Las cuatro primeras dan lo mismo pase lo que pase
(`renta`, un ingreso pasivo); la quinta decide por sí misma y gana algo
distinto cada vez, así que lo suyo es una fracción de lo que gane
(`tributo`), nunca un monto fijo.

**Por qué una persona puede ser propiedad.** En un mundo con esclavitud una
persona es tan propiedad como una granja, y el motor no necesita saber la
diferencia moral entre las dos — solo la mecánica. Esta primera pasada es
puramente económica a propósito: posee a alguien y no le toca la voluntad,
solo una parte de lo que gana. La coerción, si llega, es contenido futuro
(un código moral por facción), no motor.

**Por qué la herencia no espera al nacimiento.** `RelationSpec.hereda` reusa
una pieza que ya existía — quién es tu familia, ya declarado en el pack — así
que "quién puede heredar" no necesita esperar a que el motor sepa crear
agentes nuevos. Va entera a quien tenga MÁS aprecio hacia el difunto, no
repartida: una propiedad indivisible partida en trozos deja de significar lo
que significaba.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from agora.engine.ontology import AgentId, NeedId, PlaceId, PropertyId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

DUENYO = AgentId("duenyo")
ESCLAVO = AgentId("esclavo")
HIJO1 = AgentId("hijo1")
HIJO2 = AgentId("hijo2")
EXTRANO = AgentId("extranyo")
P1 = PlaceId("p1")
DINERO = NeedId("dinero")


def propiedad_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "dinero", "label": "dinero", "decay_per_tick": 0.0, "initial": 0.3},
        ],
        "actions": [
            {"id": "trabajar", "label": "trabajar", "duration_ticks": 1,
             "requires_affordance": "sitio", "satisfies": {"dinero": 1.0},
             "effects": {"dinero": 0.20}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"]},
        ],
        "agents": [
            {"id": "duenyo", "label": "Dueño", "home": "p1", "start_at": "p1"},
            {"id": "esclavo", "label": "Esclavo", "home": "p1", "start_at": "p1"},
        ],
        "properties": [
            {"id": "granja", "label": "granja", "tipo": "lugar", "objeto": "p1",
             "renta": {"dinero": 0.05}, "dueño_inicial": "duenyo"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- lo que el pack puede declarar -------------------------------------------


def test_a_place_declaring_tributo_is_dead_content() -> None:
    """Una tierra no rinde una fracción de nada: rinde lo mismo pase lo que
    pase, o no es la clase de cosa que `tributo` describe."""
    with pytest.raises(ValueError, match="usa `renta`"):
        propiedad_pack(**{"properties": [
            {"id": "granja", "label": "granja", "tipo": "lugar", "objeto": "p1",
             "tributo": {"dinero": 0.5}},
        ]})


def test_a_person_declaring_renta_is_dead_content() -> None:
    """Una persona no rinde un monto fijo ajeno a lo que haga: decide por sí
    misma, y lo que gana varía. `renta` describiría a otra cosa."""
    with pytest.raises(ValueError, match="usa `tributo`"):
        propiedad_pack(**{"properties": [
            {"id": "esclavitud", "label": "esclavitud", "tipo": "persona",
             "objeto": "esclavo", "renta": {"dinero": 0.05}},
        ]})


def test_tributo_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"fuera de \[0, 1\]"):
        propiedad_pack(**{"properties": [
            {"id": "esclavitud", "label": "esclavitud", "tipo": "persona",
             "objeto": "esclavo", "tributo": {"dinero": 1.5}},
        ]})


def test_property_object_must_exist() -> None:
    with pytest.raises(ValueError, match="agente desconocido"):
        propiedad_pack(**{"properties": [
            {"id": "esclavitud", "label": "esclavitud", "tipo": "persona",
             "objeto": "nadie", "tributo": {"dinero": 0.5}},
        ]})


def test_property_place_object_must_exist() -> None:
    with pytest.raises(ValueError, match="lugar desconocido"):
        propiedad_pack(**{"properties": [
            {"id": "granja", "label": "granja", "tipo": "lugar",
             "objeto": "ningun_lugar", "renta": {"dinero": 0.05}},
        ]})


def test_initial_owner_must_exist() -> None:
    with pytest.raises(ValueError, match="dueño_inicial"):
        propiedad_pack(**{"properties": [
            {"id": "granja", "label": "granja", "tipo": "lugar", "objeto": "p1",
             "renta": {"dinero": 0.05}, "dueño_inicial": "nadie"},
        ]})


def test_a_person_cannot_have_two_owners_at_once() -> None:
    """El motor cobra el tributo una sola vez por acción completada: con dos
    registros no habría a cuál de los dos dueños pagarle."""
    with pytest.raises(ValueError, match="a lo sumo una"):
        propiedad_pack(**{"properties": [
            {"id": "granja", "label": "granja", "tipo": "lugar", "objeto": "p1",
             "renta": {"dinero": 0.05}, "dueño_inicial": "duenyo"},
            {"id": "esclavitud1", "label": "esclavitud1", "tipo": "persona",
             "objeto": "esclavo", "tributo": {"dinero": 0.5},
             "dueño_inicial": "duenyo"},
            {"id": "esclavitud2", "label": "esclavitud2", "tipo": "persona",
             "objeto": "esclavo", "tributo": {"dinero": 0.3},
             "dueño_inicial": "duenyo"},
        ]})


def test_a_pack_without_properties_pays_nothing_for_this() -> None:
    """Estrenar esto no puede mover ningún contrato ya medido: sin
    propiedades declaradas, `WorldState.propiedades` está vacío y
    `_aplicar_rentas` no toca a nadie -- ni revienta al no encontrar nada."""
    pack = propiedad_pack(properties=[])
    sim = Simulation(pack, seed=1)
    assert sim.state.propiedades == {}
    sim.run(10)  # no debe reventar


# --- renta: lugares, objetos, títulos, deudas --------------------------------


def _solo_renta_pack(**overrides: Any) -> ContentPack:
    """Sin `trabajar`: aísla la renta de cualquier ingreso por acción propia,
    para que las pruebas de esta sección midan solo lo que dicen medir."""
    return propiedad_pack(actions=[{"id": "nada", "label": "nada", "duration_ticks": 1}],
                          **overrides)


def test_the_owner_of_a_place_collects_its_rent() -> None:
    sim = Simulation(_solo_renta_pack(), seed=1)
    antes = sim.state.agents[DUENYO].needs[DINERO]
    sim.tick()
    assert sim.state.agents[DUENYO].needs[DINERO] == pytest.approx(antes + 0.05)


def test_rent_compounds_over_several_ticks() -> None:
    sim = Simulation(_solo_renta_pack(), seed=1)
    antes = sim.state.agents[DUENYO].needs[DINERO]
    sim.run(3)
    assert sim.state.agents[DUENYO].needs[DINERO] == pytest.approx(antes + 0.15)


def test_a_property_without_an_owner_pays_nobody() -> None:
    pack = _solo_renta_pack(properties=[
        {"id": "granja", "label": "granja", "tipo": "lugar", "objeto": "p1",
         "renta": {"dinero": 0.05}},
    ])
    sim = Simulation(pack, seed=1)
    antes = sim.state.agents[DUENYO].needs[DINERO]
    sim.run(5)
    assert sim.state.agents[DUENYO].needs[DINERO] == pytest.approx(antes)


# --- tributo: la persona ------------------------------------------------------


def _dueño_sin_donde_trabajar(**overrides: Any) -> ContentPack:
    """El dueño vive en `p2`, sin la affordance `sitio`: así no puede hacer
    `trabajar` él mismo, y lo único que puede moverle el dinero es el
    tributo -- aísla la medición de su propio ingreso."""
    return propiedad_pack(**{
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": [], "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "duenyo", "label": "Dueño", "home": "p2", "start_at": "p2"},
            {"id": "esclavo", "label": "Esclavo", "home": "p1", "start_at": "p1"},
        ],
        **overrides,
    })


def test_owning_a_person_redirects_a_cut_of_what_they_earn() -> None:
    """Y ES UNA TRANSFERENCIA, NO UNA COPIA: lo que se lleva el dueño es lo
    que deja de quedarse el esclavo, no dinero nuevo salido de la nada."""
    pack = _dueño_sin_donde_trabajar(properties=[
        {"id": "esclavitud", "label": "esclavitud", "tipo": "persona",
         "objeto": "esclavo", "tributo": {"dinero": 0.5}, "dueño_inicial": "duenyo"},
    ])
    sim = Simulation(pack, seed=1)
    dinero_esclavo_antes = sim.state.agents[ESCLAVO].needs[DINERO]
    dinero_duenyo_antes = sim.state.agents[DUENYO].needs[DINERO]

    sim.run(2)  # ambos "trabajar", único candidato con requires_affordance sitio

    esclavo_gano = sim.state.agents[ESCLAVO].needs[DINERO] - dinero_esclavo_antes
    duenyo_gano = sim.state.agents[DUENYO].needs[DINERO] - dinero_duenyo_antes

    assert esclavo_gano == pytest.approx(0.10), "la mitad de 0.20, no el 0.20 entero"
    assert duenyo_gano == pytest.approx(0.10), "la otra mitad, redirigida"


def test_nobody_is_taxed_on_what_they_spend() -> None:
    """El tributo es sobre lo GANADO, nunca sobre lo que cuesta: gravar el
    coste sería doble castigo, no una fracción de lo ganado."""
    pack = _dueño_sin_donde_trabajar(**{
        "actions": [
            {"id": "trabajar", "label": "trabajar", "duration_ticks": 1,
             "requires_affordance": "sitio", "satisfies": {"dinero": 1.0},
             "costs": {"dinero": 0.0}, "effects": {"dinero": -0.10}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "properties": [
            {"id": "esclavitud", "label": "esclavitud", "tipo": "persona",
             "objeto": "esclavo", "tributo": {"dinero": 0.5}, "dueño_inicial": "duenyo"},
        ]})
    sim = Simulation(pack, seed=1)
    dinero_duenyo_antes = sim.state.agents[DUENYO].needs[DINERO]
    sim.run(2)
    assert sim.state.agents[DUENYO].needs[DINERO] == pytest.approx(dinero_duenyo_antes), (
        "perder dinero no le paga nada al dueño"
    )


def test_an_unowned_person_keeps_everything() -> None:
    pack = propiedad_pack(properties=[])
    sim = Simulation(pack, seed=1)
    antes = sim.state.agents[ESCLAVO].needs[DINERO]
    sim.run(2)
    assert sim.state.agents[ESCLAVO].needs[DINERO] == pytest.approx(antes + 0.20)


# --- herencia -----------------------------------------------------------------


def herencia_pack(**overrides: Any) -> ContentPack:
    return propiedad_pack(**{
        "relations": [
            # `hereda` va en `padre`, la relación que SOSTIENE EL HIJO hacia el
            # difunto -- es su lado el que se recorre al buscar herederos, no
            # el del padre mirando a sus hijos.
            {"id": "hijo", "label": "hijo", "inverse": "padre"},
            {"id": "padre", "label": "padre", "inverse": "hijo", "hereda": True},
            {"id": "conocido", "label": "conocido", "symmetric": True},
        ],
        "agents": [
            {"id": "duenyo", "label": "Dueño", "home": "p1", "start_at": "p1"},
            {"id": "esclavo", "label": "Esclavo", "home": "p1", "start_at": "p1"},
            {"id": "hijo1", "label": "Hijo1", "home": "p1", "start_at": "p1",
             "relations": {"padre": ["duenyo"]}},
            {"id": "hijo2", "label": "Hijo2", "home": "p1", "start_at": "p1",
             "relations": {"padre": ["duenyo"]}},
        ],
        **overrides,
    })


def test_property_goes_to_the_heir_with_the_most_regard() -> None:
    sim = Simulation(herencia_pack(), seed=1)
    for t in range(40):
        sim.state.agents[HIJO1].meet(DUENYO, tick=t)
        sim.state.agents[HIJO1].remember_company([DUENYO], premium=0.6, rate=0.4, tick=t)
    # HIJO2 nunca convive con DUENYO: su aprecio se queda en 0.

    sim.morir(DUENYO)

    assert sim.state.propiedades[PropertyId("granja")].dueño == HIJO1


def test_a_relation_without_hereda_does_not_qualify() -> None:
    pack = herencia_pack(**{"agents": [
        {"id": "duenyo", "label": "Dueño", "home": "p1", "start_at": "p1"},
        {"id": "esclavo", "label": "Esclavo", "home": "p1", "start_at": "p1"},
        {"id": "extranyo", "label": "Extraño", "home": "p1", "start_at": "p1",
         "relations": {"conocido": ["duenyo"]}},
    ]})
    sim = Simulation(pack, seed=1)
    for t in range(40):
        sim.state.agents[EXTRANO].meet(DUENYO, tick=t)
        sim.state.agents[EXTRANO].remember_company([DUENYO], premium=0.6, rate=0.4, tick=t)

    sim.morir(DUENYO)

    assert sim.state.propiedades[PropertyId("granja")].dueño is None, (
        "mucho aprecio no basta sin una relación que herede"
    )


def test_no_qualifying_heir_leaves_the_property_ownerless() -> None:
    sim = Simulation(propiedad_pack(), seed=1)  # sin relaciones declaradas
    sim.morir(DUENYO)
    assert sim.state.propiedades[PropertyId("granja")].dueño is None


def test_a_hated_heir_still_inherits_over_no_heir_at_all() -> None:
    """La herencia no exige aprecio positivo, solo la relación correcta -- al
    revés que el duelo, que sí lo exige para grabarse."""
    pack = herencia_pack()
    sim = Simulation(pack, seed=1)
    # Nadie convive con nadie: los dos hijos tienen aprecio 0.0 hacia DUENYO.
    sim.morir(DUENYO)
    heredero = sim.state.propiedades[PropertyId("granja")].dueño
    assert heredero in (HIJO1, HIJO2), "empate a 0.0, pero alguien de los que califican hereda"


# --- persistencia --------------------------------------------------------------


def test_ownership_survives_save_and_resume(tmp_path: Path) -> None:
    sim = Simulation(propiedad_pack(), seed=1)
    sim.state.propiedades[PropertyId("granja")].dueño = ESCLAVO
    sim.save(tmp_path / "s.json")

    reanudado = Simulation.resume(tmp_path / "s.json", propiedad_pack())
    assert reanudado.state.propiedades[PropertyId("granja")].dueño == ESCLAVO


def test_a_property_removed_from_the_pack_does_not_come_back(tmp_path: Path) -> None:
    sim = Simulation(propiedad_pack(), seed=1)
    sim.save(tmp_path / "s.json")

    pack_sin_propiedad = propiedad_pack(properties=[])
    reanudado = Simulation.resume(tmp_path / "s.json", pack_sin_propiedad)
    assert reanudado.state.propiedades == {}
