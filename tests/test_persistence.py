"""Tests de guardar y reanudar.

Sin esto cada corrida empieza en el tick cero, y con ciento veintisiete
habitantes ver graduarse a una promocion son horas de simulacion continua.

La propiedad que sostiene todo el diseno, y la que se comprueba primero:

    **reanudar en el tick N da exactamente lo mismo que no haber parado.**

No es suerte. `RngSource` sortea con `blake2b(semilla, agente, tick)`, asi que
ningun sorteo depende de cuantos hubo antes. Se decidio en F0 —"asi se puede
avanzar una parte del mundo sin avanzar el resto"— y esta es la primera vez que
se cobra.

Lo segundo que se comprueba es la RECONCILIACION, que es lo que hace util el
guardado durante la calibracion: entre corrida y corrida el pack cambia, y una
partida que se invalidara al anadir una necesidad no serviria para nada.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.persistence import SaveError
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")


def save_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6,
             "max_debt": 0.5},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.004, "initial": 0.5,
             "company_relief": 0.004},
        ],
        "traits": [
            {"id": "avaricia", "label": "avaricia", "need_weight_multipliers": {"n1": 2.0}},
        ],
        "actions": [
            {"id": "act_a", "label": "act_a", "duration_ticks": 3,
             "satisfies": {"n1": 0.8}, "effects": {"n1": 0.5}},
            {"id": "act_social", "label": "act_social", "duration_ticks": 4,
             "requires_affordance": "aff", "requires_company": 1,
             "satisfies": {"n2": 0.7}, "effects": {"n2": 0.3},
             "effects_per_company": {"n2": 0.4}},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 2}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 2}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
             "traits": {"avaricia": 0.6}},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {"bond_rate": 0.2, "bond_scale": 0.05, "bond_weight": 0.5,
                   "learning_rate": 0.1, "sighting_horizon": 40},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def foto(sim: Simulation) -> list[tuple[object, ...]]:
    """Todo lo que define el estado de una partida, comparable."""
    return [
        (
            str(a.spec_id), str(a.at), a.busy,
            tuple(sorted((str(k), round(v, 12)) for k, v in a.needs.items())),
            tuple(sorted((str(k), round(v, 12)) for k, v in a.debt.items())),
            tuple(sorted((str(k), round(v, 12)) for k, v in a.traits.items())),
            tuple(sorted((str(k), b.regard, b.encounters, b.last_seen)
                         for k, b in a.bonds.items())),
            tuple(sorted((str(k), round(v, 12)) for k, v in a.saturation.items())),
            tuple(sorted((str(k), v.value) for k, v in a.goals.items())),
        )
        for a in sim.state.agents_in_order()
    ]


# --- la propiedad que sostiene todo ------------------------------------------


def test_resuming_equals_never_stopping(tmp_path: Path) -> None:
    """El test que justifica el diseno entero."""
    pack = save_pack()

    seguido = Simulation(pack, seed=1312)
    seguido.run(400)

    partido = Simulation(pack, seed=1312)
    partido.run(150)
    partido.save(tmp_path / "mitad.json")
    partido = Simulation.resume(tmp_path / "mitad.json", pack)
    partido.run(250)

    assert partido.state.tick == seguido.state.tick == 400
    assert foto(partido) == foto(seguido)


def test_three_stops_are_the_same_as_none(tmp_path: Path) -> None:
    """Y parar tres veces tampoco deja rastro."""
    pack = save_pack()
    seguido = Simulation(pack, seed=7)
    seguido.run(300)

    sim = Simulation(pack, seed=7)
    for _ in range(3):
        sim.run(100)
        sim.save(tmp_path / "s.json")
        sim = Simulation.resume(tmp_path / "s.json", pack)

    assert foto(sim) == foto(seguido)


def test_what_travels_across_the_save(tmp_path: Path) -> None:
    """Lo que un agente ha VIVIDO, no solo donde esta."""
    pack = save_pack()
    sim = Simulation(pack, seed=1312)
    sim.run(300)
    antes = sim.state.agents[AG1]
    assert antes.bonds, "deberia conocer a alguien"
    assert antes.gain_beliefs, "deberia haber aprendido algo"
    assert antes.sightings, "deberia recordar algun sitio"

    sim.save(tmp_path / "s.json")
    despues = Simulation.resume(tmp_path / "s.json", pack).state.agents[AG1]

    assert despues.bonds.keys() == antes.bonds.keys()
    assert despues.bonds[AG2].regard == pytest.approx(antes.bonds[AG2].regard)
    assert despues.gain_beliefs == antes.gain_beliefs
    assert despues.sightings == antes.sightings
    assert despues.saturation == antes.saturation


def test_the_derived_state_is_rebuilt(tmp_path: Path) -> None:
    """No se guarda, se recompone. Y tiene que quedar igual."""
    pack = save_pack()
    sim = Simulation(pack, seed=1312)
    sim.run(120)
    antes = sim.state.agents[AG1]
    sim.save(tmp_path / "s.json")
    despues = Simulation.resume(tmp_path / "s.json", pack).state.agents[AG1]

    assert despues.need_weights == antes.need_weights
    assert despues.gains == antes.gains
    assert despues.temperament == antes.temperament
    assert despues.strain == pytest.approx(antes.strain)


def test_nobody_greets_everybody_on_resume(tmp_path: Path) -> None:
    """Sin guardar quien estaba con quien, el mundo cargado se saluda entero.

    `_detect_encounters` emite cuando dos agentes coinciden y antes no. Al
    reanudar con la memoria en blanco, cada par ya junto contaria como encuentro
    nuevo — y cada uno se llevaria un `meet` que no ocurrio.
    """
    pack = save_pack()
    sim = Simulation(pack, seed=1312)
    sim.run(200)
    # Se les fuerza a estar juntos y se guarda con ellos ahi.
    sim.state.agents[AG2].at = sim.state.agents[AG1].at
    sim.tick()
    encuentros_antes = {k: v.encounters for k, v in sim.state.agents[AG1].bonds.items()}

    sim.save(tmp_path / "s.json")
    revivido = Simulation.resume(tmp_path / "s.json", pack)
    revivido.tick()

    assert {k: v.encounters for k, v in revivido.state.agents[AG1].bonds.items()} == (
        encuentros_antes
    )


# --- reconciliacion: el pack cambia entre corrida y corrida ------------------


def test_a_new_need_arrives_at_its_initial(tmp_path: Path) -> None:
    """Es lo que hace util el guardado mientras se calibra.

    Sin reconciliar, anadir una necesidad invalidaria todas las partidas y el
    motor reventaria en el primer `decay`, que indexa directo a proposito.
    """
    sim = Simulation(save_pack(), seed=1)
    sim.run(100)
    sim.save(tmp_path / "s.json")

    ampliado = save_pack(
        needs=[
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
            {"id": "n2", "label": "n2", "decay_per_tick": 0.004, "initial": 0.5},
            {"id": "n3", "label": "n3", "decay_per_tick": 0.002, "initial": 0.33},
        ]
    )
    revivido = Simulation.resume(tmp_path / "s.json", ampliado)
    assert revivido.state.agents[AG1].needs[NeedId("n3")] == pytest.approx(0.33)
    revivido.run(20)  # y el mundo sigue andando


def test_a_removed_trait_does_not_explode(tmp_path: Path) -> None:
    """Un rasgo borrado del pack reventaria al componer, con un KeyError mudo."""
    sim = Simulation(save_pack(), seed=1)
    sim.run(50)
    sim.save(tmp_path / "s.json")

    sin_rasgo = save_pack(
        traits=[],
        agents=[
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
    )
    revivido = Simulation.resume(tmp_path / "s.json", sin_rasgo)
    assert TraitId("avaricia") not in revivido.state.agents[AG1].traits
    revivido.run(20)


def test_a_new_agent_starts_fresh(tmp_path: Path) -> None:
    """Ampliar el elenco sin perder la partida."""
    sim = Simulation(save_pack(), seed=1)
    sim.run(100)
    sim.save(tmp_path / "s.json")

    con_uno_mas = save_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
             "traits": {"avaricia": 0.6}},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
            {"id": "ag3", "label": "ag3", "home": "p1", "start_at": "p1"},
        ]
    )
    revivido = Simulation.resume(tmp_path / "s.json", con_uno_mas)
    nuevo = revivido.state.agents[AgentId("ag3")]
    assert nuevo.needs[N1] == pytest.approx(0.6)  # el initial del pack
    assert revivido.state.agents[AG1].needs[N1] != pytest.approx(0.6)  # el viejo, vivido


def test_a_removed_agent_does_not_come_back(tmp_path: Path) -> None:
    """La contrapartida honesta: el guardado se adapta al pack, no al reves."""
    sim = Simulation(save_pack(), seed=1)
    sim.run(50)
    sim.save(tmp_path / "s.json")

    # Sin el segundo, `act_social` deja de ser alcanzable y el validador lo caza
    # —con razon—, asi que se va con el.
    solo_uno = save_pack(
        actions=[{"id": "act_a", "label": "act_a", "duration_ticks": 3,
                  "satisfies": {"n1": 0.8}, "effects": {"n1": 0.5}}],
        agents=[{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
    )
    revivido = Simulation.resume(tmp_path / "s.json", solo_uno)
    assert set(revivido.state.agents) == {AG1}


def test_a_stale_belief_about_a_gone_action_is_dropped(tmp_path: Path) -> None:
    sim = Simulation(save_pack(), seed=1)
    sim.run(200)
    assert sim.state.agents[AG1].gain_beliefs
    sim.save(tmp_path / "s.json")

    recortado = save_pack(
        actions=[{"id": "act_a", "label": "act_a", "duration_ticks": 3,
                  "satisfies": {"n1": 0.8}, "effects": {"n1": 0.5}}],
        agents=[{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
                {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"}],
    )
    revivido = Simulation.resume(tmp_path / "s.json", recortado)
    assert ActionId("act_social") not in revivido.state.agents[AG1].gain_beliefs


# --- lo que se niega a cargar ------------------------------------------------


def test_another_world_is_refused(tmp_path: Path) -> None:
    """Reanudar la ciudad sobre la aldea seria un desastre silencioso."""
    sim = Simulation(save_pack(), seed=1)
    sim.save(tmp_path / "s.json")
    with pytest.raises(SaveError, match="mundos distintos"):
        Simulation.resume(tmp_path / "s.json", save_pack(id="otro"))


def test_another_format_is_refused(tmp_path: Path) -> None:
    """Media partida mal leida es peor que no cargarla."""
    import json

    sim = Simulation(save_pack(), seed=1)
    sim.save(tmp_path / "s.json")
    datos = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    datos["formato"] = 99
    (tmp_path / "s.json").write_text(json.dumps(datos), encoding="utf-8")

    with pytest.raises(SaveError, match="formato"):
        Simulation.resume(tmp_path / "s.json", save_pack())


# --- forma del fichero -------------------------------------------------------


def test_the_save_is_stable_byte_for_byte(tmp_path: Path) -> None:
    """Dos guardados del mismo mundo tienen que ser identicos, o `diff` no sirve.

    Los avistamientos guardan un `frozenset`, cuyo orden de iteracion depende del
    hash de las cadenas —aleatorizado por proceso—, asi que se ordenan al
    escribir. Es la misma razon por la que `effective_company` suma ordenado.
    """
    pack = save_pack()
    for nombre in ("a.json", "b.json"):
        sim = Simulation(pack, seed=1312)
        sim.run(200)
        sim.save(tmp_path / nombre)
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_the_save_holds_state_not_history(tmp_path: Path) -> None:
    """El log queda fuera a proposito: un ano de ciento veintisiete agentes son
    cientos de megas. El mundo se recupera; el recuerdo de como llego ahi, no."""
    pack = save_pack()
    sim = Simulation(pack, seed=1)
    sim.run(200)
    assert len(sim.log) > 0
    sim.save(tmp_path / "s.json")
    assert len(Simulation.resume(tmp_path / "s.json", pack).log) == 0
