"""Muerte con causa: el pack dice qué mata, el motor solo lleva el reloj.

**El motor no puede saber que el hambre mata.** Que un eje sea mortal es
ambientación pura — en un mundo el sustento mata en tres días, en otro el aire
mata en dos minutos, en otro no mata nada— así que se declara por necesidad en
el pack y el motor no menciona ninguna. Lo vigila `test_agnosticism`.

Es la primera vez que el motor produce una pérdida **sin que nadie la pida**.
Hasta aquí `morir` era API: un guion o un test decidían. Con esto, morirse es
consecuencia de lo que pasó, y por tanto puede pasar mientras nadie mira — que es
lo que hacía falta para que la memoria, el duelo y los rumores tengan de qué
alimentarse.

Dos ejes, y son independientes:

    debt     cuán hundido estás      se paga a plazos
    agonia   cuánto llevas hundido   se borra de golpe al levantar

Solo el segundo mata. Se puede tocar fondo un instante sin morirse, y vivir
raspando el suelo un mes sin morirse tampoco.
"""

from __future__ import annotations

import copy
from typing import Any

from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.persistence import load, save
from agora.engine.timeskip import saltar
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
HAMBRE = NeedId("hambre")


def mortal_pack(**overrides: Any) -> ContentPack:
    """El hambre mata a los 10 ticks a cero. Nadie puede comer: no hay comida."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.10,
             "initial": 0.5, "lethal_after": 10},
        ],
        "actions": [
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": [], "neighbors": {}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 20, "memory_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def comestible_pack(**overrides: Any) -> ContentPack:
    """Igual, pero se puede comer."""
    return mortal_pack(
        **{
            "actions": [
                {"id": "comer", "label": "comer", "duration_ticks": 1,
                 "requires_affordance": "cocina", "satisfies": {"hambre": 1.0},
                 "effects": {"hambre": 0.5}},
                {"id": "nada", "label": "nada", "duration_ticks": 1},
            ],
            "places": [
                {"id": "p1", "label": "p1", "affordances": ["cocina"],
                 "neighbors": {}},
            ],
            **overrides,
        }
    )


# --- lo que el pack declara --------------------------------------------------


def test_nothing_is_lethal_unless_the_pack_says_so() -> None:
    """0 es el defecto, y es lo que garantiza que estrenar esto no mate a nadie
    en los packs que ya existen."""
    pack = mortal_pack(
        **{"needs": [{"id": "hambre", "label": "hambre",
                      "decay_per_tick": 0.10, "initial": 0.5}]}
    )
    assert pack.need_by_id[HAMBRE].lethal_after == 0

    sim = Simulation(pack, seed=1)
    sim.run(500)
    assert len(sim.state.agents) == 2, "sin declararlo no mata nada"
    assert sim.state.agents[AG1].needs[HAMBRE] == 0.0, "sí estaba a cero"


def test_the_clock_only_runs_for_what_can_kill() -> None:
    """Disperso: un mundo sin nada letal no paga ni un byte por el contador."""
    pack = mortal_pack(
        **{"needs": [{"id": "hambre", "label": "hambre",
                      "decay_per_tick": 0.10, "initial": 0.5}]}
    )
    sim = Simulation(pack, seed=1)
    sim.run(50)
    assert sim.state.agents[AG1].agonia == {}


# --- el reloj ----------------------------------------------------------------


def test_the_clock_counts_ticks_at_zero() -> None:
    sim = Simulation(mortal_pack(), seed=1)
    sim.run(6)          # 0.5 a 0.10/tick: llega a cero en el quinto
    assert sim.state.agents[AG1].agonia[HAMBRE] > 0


def test_dying_takes_exactly_what_the_pack_said() -> None:
    """Determinista y sin sorteo, a diferencia de los disparadores: una regla que
    a veces mata a los tres días y a veces a los cinco no se puede aprender.

    Se parte de cero puesto a mano y no de dejarlo caer, y eso salió de un test
    que falló: `0.5 - 5*0.10` da **2.8e-17**, no `0.0`. Con `value <= 0.0` el
    reloj arranca un tick más tarde de lo que la aritmética sugiere. No es un
    fallo —el suelo recorta a cero exacto al tick siguiente y a partir de ahí
    todo va bien— pero contar ticks desde una resta de floats sí lo sería.
    """
    sim = Simulation(mortal_pack(), seed=1)
    sim.run(1)
    sim.state.agents[AG1].needs[HAMBRE] = 0.0
    sim.state.agents[AG1].agonia.clear()

    sim.run(9)
    assert sim.state.agents[AG1].agonia[HAMBRE] == 9, "aún aguanta"
    sim.run(1)
    assert AG1 not in sim.state.agents, "al décimo, no antes ni después"


def test_eating_wipes_the_clock_and_does_not_pay_it_in_instalments() -> None:
    """La diferencia con la deuda, que sí se paga a plazos."""
    sim = Simulation(comestible_pack(), seed=1)
    sim.run(6)
    agente = sim.state.agents[AG1]
    agente.agonia[HAMBRE] = 8

    agente.apply({HAMBRE: 0.9}, sim.pack.need_by_id)
    sim.run(1)
    assert HAMBRE not in agente.agonia


def test_you_can_scrape_the_floor_forever_without_dying() -> None:
    """Los dos ejes son independientes: tocar fondo un instante no mata, y vivir
    raspando el suelo tampoco. Solo mata llevar demasiado a cero."""
    sim = Simulation(comestible_pack(), seed=3)
    sim.run(400)
    assert AG1 in sim.state.agents


# --- lo que arrastra ---------------------------------------------------------


def test_the_dead_stop_acting_that_very_tick() -> None:
    """Se cobra antes de deliberar: un muerto no cierra metas ni actúa. Dejarle
    resolver su ocupación sería darle un turno de más."""
    sim = Simulation(mortal_pack(), seed=1)
    sim.run(40)
    assert not sim.state.agents
    antes = len(sim.log)
    sim.run(20)
    assert len(sim.log) == antes, "un mundo vacío no emite nada"


def test_dying_of_two_things_at_once_kills_you_once() -> None:
    pack = mortal_pack(
        **{"needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.10,
             "initial": 0.5, "lethal_after": 10},
            {"id": "sed", "label": "sed", "decay_per_tick": 0.10,
             "initial": 0.5, "lethal_after": 10},
        ]}
    )
    sim = Simulation(pack, seed=1)
    sim.run(40)
    assert AG2 not in sim.state.agents
    muertes = [e for e in sim.log.of_kind(EventKind.AGENT_DIED)]
    # Sin vínculos no hay duelo, así que ni un evento; lo que importa es que no
    # reventó al intentar matar dos veces al mismo.
    assert all(e.subject != e.actor for e in muertes)


def test_the_log_says_what_killed_you() -> None:
    """`porque` lleva el eje. Es el mismo freno que los disparadores: el log tiene
    que decir por qué, no solo que pasó."""
    sim = Simulation(mortal_pack(), seed=1)
    for t in range(60):
        sim.state.agents[AG2].meet(AG1, tick=t) if AG2 in sim.state.agents else None
        if AG2 in sim.state.agents:
            sim.state.agents[AG2].remember_company([AG1], premium=0.5, rate=0.4,
                                                   tick=t)
        sim.run(1)
        if AG1 not in sim.state.agents:
            break
    muertes = sim.log.of_kind(EventKind.AGENT_DIED)
    assert muertes, "nadie lloró a nadie"
    assert muertes[0].data is not None
    assert muertes[0].data["porque"] == "hambre"


def test_the_census_remembers_the_dead() -> None:
    sim = Simulation(mortal_pack(), seed=1)
    sim.run(40)
    assert sim.state.existe(AG1)
    assert AG1 not in sim.state.agents


# --- durar -------------------------------------------------------------------


def test_saving_does_not_forgive_what_you_had_not_eaten(tmp_path: Any) -> None:
    """La deuda ya se guardaba; el reloj que mata no existía. Sin esto, guardar y
    reanudar le perdona a todo el mundo lo que llevaba sin comer."""
    pack = mortal_pack()
    sim = Simulation(pack, seed=1)
    sim.run(8)
    llevaba = sim.state.agents[AG1].agonia[HAMBRE]
    assert llevaba > 0

    fichero = tmp_path / "partida.json"
    save(sim.state, set(), fichero)
    vuelto, _ = load(fichero, pack)
    assert vuelto.agents[AG1].agonia[HAMBRE] == llevaba


def test_a_skip_does_not_carry_a_starvation_clock_across_the_gap() -> None:
    """**La limitación del atajo, fijada aquí a propósito.**

    `agonia` cuenta ticks SEGUIDOS, y a través de trece días sin simular
    "seguidos" es falso. Las dos alternativas eran inventarse algo: adelantarla
    mata a todo el que estuviera a cero al saltar —1248 ticks pasan cualquier
    umbral, y los días simulados demuestran que esa gente come—, y dejarla
    colgando cuenta como consecutivos unos ticks repartidos por un mes.

    Consecuencia, y por eso hay test: **bajo `--skip` no se muere nadie de
    hambre** salvo que el pack lo declare letal en menos de lo que dura un día
    simulado. Lo que no se simula, no se inventa.
    """
    sim = Simulation(comestible_pack(), seed=1)
    sim.run(6)
    sim.state.agents[AG1].agonia[HAMBRE] = 9

    saltar(sim, dias=3, factor=3)
    assert HAMBRE not in sim.state.agents[AG1].agonia


# --- y lo que esto desbloquea ------------------------------------------------


def test_a_death_that_nobody_asked_for_feeds_the_grief() -> None:
    """**Lo que este paso compra.** Hasta aquí una muerte la pedía un guion, así
    que el duelo, la memoria y los rumores no tenían de qué alimentarse solos.
    Ahora la pérdida es consecuencia de lo que pasó."""
    pack = comestible_pack(
        **{"tuning": {"memory_capacity": 20, "memory_scale": 1.0,
                      "grief_scale": 1.0}}
    )
    sim = Simulation(pack, seed=1)
    for t in range(30):
        sim.state.agents[AG2].meet(AG1, tick=t)
        sim.state.agents[AG2].remember_company([AG1], premium=0.5, rate=0.4,
                                               tick=t)
    # Se hunde SOLO a ag1: en este mundo se puede comer, así que el deudo
    # sobrevive para poder llorarlo. La primera versión de este test mataba a los
    # dos y fallaba con razón — al morirse el deudo se le borra la memoria, duelo
    # incluido.
    sim.state.agents[AG1].needs[HAMBRE] = 0.0
    sim.state.agents[AG1].agonia[HAMBRE] = 9

    sim.run(1)
    assert AG1 not in sim.state.agents, "no llegó a morirse"
    assert AG2 in sim.state.agents, "el deudo tiene que seguir vivo"

    duelo = sim.state.memoria.duelo(AG2, sim.state.tick, escala=1.0)
    assert duelo.get(AG1, 0.0) > 0.0, "nadie lo lloró"
    assert sim.state.memoria.de(AG1) == (), "lo que sabía se fue con él"


def test_the_engine_still_knows_nothing_about_hunger() -> None:
    """Un pack puede llamar mortal a cualquier cosa. Aquí se mata de aburrimiento
    para dejarlo por escrito."""
    pack = mortal_pack(
        **{"needs": [{"id": "asombro", "label": "asombro",
                      "decay_per_tick": 0.20, "initial": 0.4,
                      "lethal_after": 3}]}
    )
    sim = Simulation(pack, seed=1)
    sim.run(20)
    assert not sim.state.agents
