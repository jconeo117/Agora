"""Tests de las situaciones: cómo está el mundo.

Una franja es una función del tick: cíclica, siempre hay exactamente una, y no
se puede empezar ni terminar. Eso vale para la noche y no vale para una guerra.
Una situación es lo mismo un escalón más arriba — **tiene principio y final,
pueden coincidir varias, y algunas no se sabe cuándo llegan.**

Dos formas de estar activa y las dos hacen falta: la periódica es función del
reloj (estaciones, ferias) y no guarda estado; la eventual (guerra, derrumbe)
solo está si alguien la enciende, y esa sí es estado que se persiste.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

FERIA = SituationId("feria")
GUERRA = SituationId("guerra")
HAMBRE = NeedId("hambre")
GOZO = NeedId("gozo")
PLAZA = PlaceId("plaza")
CASA = PlaceId("casa")
AG1 = AgentId("ag1")
COMER = ActionId("comer")
BAILAR = ActionId("bailar")


def sit_pack(**overrides: Any) -> ContentPack:
    """Una feria que vuelve cada 10 días y una guerra que no vuelve sola."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.01, "initial": 0.6},
            {"id": "gozo", "label": "gozo", "decay_per_tick": 0.01, "initial": 0.5},
        ],
        "actions": [
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"hambre": 0.9}, "effects": {"hambre": 0.5}},
            {"id": "bailar", "label": "bailar", "duration_ticks": 2,
             "requires_affordance": "fiesta",
             "satisfies": {"gozo": 0.9}, "effects": {"gozo": 0.4},
             "situation_multipliers": {"feria": 3.0}},
        ],
        "places": [
            {"id": "plaza", "label": "plaza", "affordances": ["fiesta"],
             "neighbors": {"casa": 1}},
            {"id": "casa", "label": "casa", "neighbors": {"plaza": 1}},
        ],
        "situations": [
            {"id": "feria", "label": "feria", "every": 960, "lasts": 96},
            {"id": "guerra", "label": "guerra", "gain_multipliers": {"hambre": 0.25}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "casa", "start_at": "casa"},
            {"id": "ag2", "label": "ag2", "home": "plaza", "start_at": "plaza"},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- las dos formas de estar activa ------------------------------------------


def test_a_periodic_situation_is_a_function_of_the_clock() -> None:
    """Como una franja, solo que de un ciclo más largo. No hay estado que mirar."""
    sim = Simulation(sit_pack(), seed=1)
    assert sim.state.active_situations() == (FERIA,)  # el tick 0 cae dentro

    sim.state.tick = 200
    assert sim.state.active_situations() == ()
    sim.state.tick = 960
    assert sim.state.active_situations() == (FERIA,)


def test_a_periodic_situation_is_not_stored() -> None:
    """Guardarla sería guardar algo que ya se sabe calcular, y en un salto
    temporal habría que arrastrarla."""
    sim = Simulation(sit_pack(), seed=1)
    assert sim.state.active_situations() == (FERIA,)
    assert sim.state.situations == {}


def test_an_eventual_situation_only_happens_if_something_causes_it() -> None:
    sim = Simulation(sit_pack(), seed=1)
    sim.state.tick = 200  # fuera de la feria
    assert sim.state.active_situations() == ()

    sim.begin_situation(GUERRA)
    assert sim.state.active_situations() == (GUERRA,)


def test_an_eventual_situation_ends_when_its_time_runs_out() -> None:
    sim = Simulation(sit_pack(), seed=1)
    sim.run(200)
    sim.begin_situation(GUERRA, ticks=10)
    assert GUERRA in sim.state.active_situations()

    sim.run(9)
    assert GUERRA in sim.state.active_situations()
    sim.run(1)
    assert GUERRA not in sim.state.active_situations()


def test_an_eventual_situation_can_last_until_someone_ends_it() -> None:
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA)
    sim.run(500)
    assert GUERRA in sim.state.active_situations()

    sim.end_situation(GUERRA)
    assert GUERRA not in sim.state.active_situations()


def test_lighting_a_periodic_situation_by_hand_is_refused() -> None:
    """No se ignora, revienta: querría decir que quien llama la cree eventual, y
    ese malentendido no se ve en el log."""
    sim = Simulation(sit_pack(), seed=1)
    with pytest.raises(ValueError, match="periódica"):
        sim.begin_situation(FERIA)


# --- los tres canales por los que se nota -------------------------------------


def test_it_changes_what_people_choose() -> None:
    """`situation_multipliers`, gemelo de `phase_multipliers`."""
    from agora.agents.decide import situation_fit

    pack = sit_pack()
    bailar = pack.action_by_id[BAILAR]
    assert situation_fit(bailar, ()) == 1.0
    assert situation_fit(bailar, (FERIA,)) == 3.0
    assert situation_fit(bailar, (GUERRA,)) == 1.0  # no la menciona


def test_several_at_once_multiply() -> None:
    """Feria bajo la lluvia luce menos, y eso es lo correcto."""
    from agora.agents.decide import situation_fit

    pack = sit_pack(
        situations=[
            {"id": "feria", "label": "feria", "every": 960, "lasts": 96},
            {"id": "lluvia", "label": "lluvia", "gain_multipliers": {"gozo": 0.5}},
        ],
        actions=[
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"hambre": 0.9}, "effects": {"hambre": 0.5}},
            {"id": "bailar", "label": "bailar", "duration_ticks": 2,
             "requires_affordance": "fiesta",
             "satisfies": {"gozo": 0.9}, "effects": {"gozo": 0.4},
             "situation_multipliers": {"feria": 3.0, "lluvia": 0.5}},
        ],
    )
    bailar = pack.action_by_id[BAILAR]
    assert situation_fit(bailar, (FERIA, SituationId("lluvia"))) == pytest.approx(1.5)


def test_it_changes_what_things_actually_yield() -> None:
    """`gain_multipliers`: una hambruna hace que comer alimente menos, que es lo
    que ES una hambruna. No le quita las ganas de comer a nadie."""
    sim = Simulation(sit_pack(), seed=1)
    agente = sim.state.agents[AG1]
    agente.needs[HAMBRE] = 0.0

    normal = dict(sim.state.gains_at(CASA))
    sim.begin_situation(GUERRA)
    con_guerra = dict(sim.state.gains_at(CASA))

    assert normal.get(HAMBRE, 1.0) == 1.0
    assert con_guerra[HAMBRE] == pytest.approx(0.25)

    agente.apply({HAMBRE: 0.5}, sim.pack.need_by_id, con_guerra)
    assert agente.needs[HAMBRE] == pytest.approx(0.125)


def test_it_can_close_a_place_outright() -> None:
    """`closed_during`, gemelo de `open_during`: puerta dura, no desánimo. La
    mina derrumbada no es menos atractiva, es que no está."""
    from agora.agents.decide import is_available

    pack = sit_pack(
        places=[
            {"id": "plaza", "label": "plaza", "affordances": ["fiesta"],
             "neighbors": {"casa": 1}, "closed_during": ["guerra"]},
            {"id": "casa", "label": "casa", "neighbors": {"plaza": 1}},
        ]
    )
    plaza, bailar = pack.place_by_id[PLAZA], pack.action_by_id[BAILAR]
    needs = {HAMBRE: 1.0, GOZO: 0.0}
    assert is_available(bailar, plaza, 0, needs, None, None, ())
    assert not is_available(bailar, plaza, 0, needs, None, None, (GUERRA,))


# --- el alcance ---------------------------------------------------------------


def test_a_situation_without_places_reaches_everywhere() -> None:
    """Vacío = en todo el mundo, como `open_during` vacío es siempre abierto."""
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA)
    assert GUERRA in sim.state.situations_at(PLAZA)
    assert GUERRA in sim.state.situations_at(CASA)


def test_a_situation_with_places_stays_there() -> None:
    """Lo que separa una guerra —que lo tiñe todo— de una feria en la plaza."""
    pack = sit_pack(
        situations=[
            {"id": "feria", "label": "feria", "every": 960, "lasts": 96, "places": ["plaza"]},
            {"id": "guerra", "label": "guerra", "gain_multipliers": {"hambre": 0.25}},
        ]
    )
    sim = Simulation(pack, seed=1)
    assert sim.state.active_situations() == (FERIA,)
    assert sim.state.situations_at(PLAZA) == (FERIA,)
    assert sim.state.situations_at(CASA) == ()


# --- lo que se habría roto sin cuidarlo ---------------------------------------


def test_the_active_list_is_sorted() -> None:
    """Los multiplicadores se multiplican entre sí, multiplicar floats no es
    asociativo, y el orden de un `frozenset` depende del hash. Sería la tercera
    vez que ese par rompe el determinismo en este motor."""
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA)
    activas = sim.state.active_situations()
    assert activas == tuple(sorted(activas))
    assert isinstance(activas, tuple)


def test_beginning_and_ending_leave_an_event() -> None:
    """Nada muta el estado sin emitir un evento. Para las capas de arriba, un
    cambio sin evento nunca ocurrió."""
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA, ticks=5)
    sim.run(5)

    began = sim.log.of_kind(EventKind.SITUATION_BEGAN)
    ended = sim.log.of_kind(EventKind.SITUATION_ENDED)
    assert [e.data["situation"] for e in began] == ["guerra"]
    assert [e.data["situation"] for e in ended] == ["guerra"]


def test_a_periodic_situation_is_silent() -> None:
    """Anunciar una periódica sería anunciar que amaneció cada mañana."""
    sim = Simulation(sit_pack(), seed=1)
    sim.run(1000)  # cruza una feria entera
    assert not sim.log.of_kind(EventKind.SITUATION_BEGAN)


def test_it_expires_before_anyone_acts() -> None:
    """Por lo mismo que el reloj: todos los agentes de un tick tienen que ver el
    mundo en un solo estado. Si expirase a mitad, los primeros de la lista
    decidirían con la guerra puesta y los últimos sin ella."""
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA, ticks=1)
    sim.run(1)
    vistas = [
        e.tick for e in sim.log.of_kind(EventKind.SITUATION_ENDED)
    ]
    actuaron = [
        e.tick for e in sim.log.of_kind(EventKind.ACTION_STARTED) if e.tick == sim.state.tick
    ]
    assert vistas == [sim.state.tick]
    assert all(t >= vistas[0] for t in actuaron)


def test_an_eventual_situation_survives_a_save(tmp_path: Path) -> None:
    """Una guerra a medias no puede evaporarse al guardar la partida."""
    destino = tmp_path / "partida.json"
    sim = Simulation(sit_pack(), seed=1)
    sim.run(200)
    sim.begin_situation(GUERRA, ticks=500)
    esperado = sim.state.situations[GUERRA]
    sim.save(destino)

    vuelto = Simulation.resume(destino, sit_pack())
    assert vuelto.state.situations == {GUERRA: esperado}


def test_a_periodic_situation_is_not_in_the_save(tmp_path: Path) -> None:
    """Guardarla la congelaría: al reanudar sobre un pack retocado se
    contradiría con lo que el pack dice de ella."""
    import json

    destino = tmp_path / "partida.json"
    sim = Simulation(sit_pack(), seed=1)
    assert FERIA in sim.state.active_situations()
    sim.save(destino)

    guardado = json.loads(destino.read_text(encoding="utf-8"))
    assert guardado["situations"] == []


def test_a_situation_deleted_from_the_pack_does_not_come_back(tmp_path: Path) -> None:
    """La contrapartida honesta de reconciliar: `gains_at` la buscaría en
    `situation_by_id` y reventaría con un KeyError sin explicación."""
    destino = tmp_path / "partida.json"
    sim = Simulation(sit_pack(), seed=1)
    sim.begin_situation(GUERRA)
    sim.save(destino)

    sin_guerra = sit_pack(
        situations=[{"id": "feria", "label": "feria", "every": 960, "lasts": 96}]
    )
    vuelto = Simulation.resume(destino, sin_guerra)
    assert vuelto.state.situations == {}
    vuelto.run(5)  # y no revienta


def test_a_periodic_situation_lands_right_after_a_time_skip() -> None:
    """Ser función del reloj es exactamente lo que hace que el salto no la
    despeine: no hay nada que arrastrar."""
    from agora.engine.timeskip import saltar

    sim = Simulation(sit_pack(), seed=1)
    saltar(sim, 30, factor=7)
    assert sim.state.tick == 30 * 96
    esperado = sim.pack.situation_by_id[FERIA].active_at(sim.state.tick)
    assert (FERIA in sim.state.active_situations()) == esperado


def test_a_world_without_situations_is_untouched() -> None:
    """Vacío = el mundo no tiene estados, y todo lo que dependa de ellos queda
    inerte, igual que sin franjas."""
    pack = sit_pack(
        situations=[],
        actions=[
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"hambre": 0.9}, "effects": {"hambre": 0.5}},
            {"id": "bailar", "label": "bailar", "duration_ticks": 2,
             "requires_affordance": "fiesta",
             "satisfies": {"gozo": 0.9}, "effects": {"gozo": 0.4}},
        ],
    )
    sim = Simulation(pack, seed=1)
    sim.run(300)
    assert sim.state.active_situations() == ()
    assert sim.state.gains_at(CASA) == {}


# --- validación ---------------------------------------------------------------


def test_a_situation_that_does_nothing_is_rejected() -> None:
    """Se lee como contenido vivo —tiene nombre, se enciende, sale en el log— y
    no cambia una sola decisión. El motor no lo detecta solo: no revienta,
    simplemente no pasa nada."""
    with pytest.raises(ValidationError, match="no hace absolutamente nada"):
        sit_pack(
            situations=[
                {"id": "feria", "label": "feria", "every": 960, "lasts": 96},
                {"id": "guerra", "label": "guerra"},
            ]
        )


def test_an_unknown_situation_in_a_multiplier_is_caught() -> None:
    """Una errata aquí no rompe nada visible: lo ausente vale 1.0, así que la
    situación mal escrita no hace nada y no se distingue de una que sí funciona
    pero nunca se ha encendido."""
    with pytest.raises(ValidationError, match="desconocida/o 'ferai'"):
        sit_pack(
            actions=[
                {"id": "comer", "label": "comer", "duration_ticks": 2,
                 "satisfies": {"hambre": 0.9}, "effects": {"hambre": 0.5}},
                {"id": "bailar", "label": "bailar", "duration_ticks": 2,
                 "requires_affordance": "fiesta",
                 "satisfies": {"gozo": 0.9}, "effects": {"gozo": 0.4},
                 "situation_multipliers": {"ferai": 3.0}},
            ]
        )


def test_a_periodic_situation_that_never_ends_is_refused() -> None:
    with pytest.raises(ValueError, match="no se apaga jamás"):
        sit_pack(
            situations=[
                {"id": "feria", "label": "feria", "every": 96, "lasts": 96},
                {"id": "guerra", "label": "guerra", "gain_multipliers": {"hambre": 0.25}},
            ]
        )


def test_a_periodic_situation_that_never_happens_is_refused() -> None:
    with pytest.raises(ValueError, match="no llega a ocurrir"):
        sit_pack(
            situations=[
                {"id": "feria", "label": "feria", "every": 960},
                {"id": "guerra", "label": "guerra", "gain_multipliers": {"hambre": 0.25}},
            ]
        )
