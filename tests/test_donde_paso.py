"""Dónde te lo hicieron, no dónde lo notaste.

**El campo que desatasca el mecanismo que lleva más tiempo parado.** `miedo()`
pide un recuerdo con lugar y con culpable, y una herida da las dos cosas — pero
el recuerdo se graba cuando la necesidad cruza su umbral, y un herido sangra
durante días: cruza el umbral **en su posada**, o en el templo, o de camino.

Sin `Condicion.donde`, la lección aprendida sería temer la propia cama. Y no es
una hipótesis: es exactamente la contaminación que dejó el miedo a lugares
parado una fase entera la primera vez, entonces por los chascos sociales, que
también ocurren donde uno pasa el tiempo.

La regla, en una línea: **el lugar de un daño es donde lo causaron, no donde se
nota.**
"""

from __future__ import annotations

import copy
from typing import Any

from agora.engine.ontology import AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
MAZMORRA = PlaceId("mazmorra")
POSADA = PlaceId("posada")
SANGRE = NeedId("sangre")
HERIDA = SituationId("herida")


def dos_sitios(**overrides: Any) -> ContentPack:
    """Una mazmorra donde te hieren y una posada donde te desangras."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "sangre", "label": "sangre", "decay_per_tick": 0.0,
             "initial": 0.20, "lethal_after": 0},
            {"id": "descanso", "label": "descanso", "decay_per_tick": 0.01,
             "initial": 0.9},
        ],
        "situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.02}},
        ],
        "actions": [
            {"id": "dormir", "label": "dormir", "duration_ticks": 2,
             "requires_affordance": "cama", "satisfies": {"descanso": 1.0},
             "effects": {"descanso": 0.3}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "mazmorra", "label": "mazmorra", "affordances": [],
             "neighbors": {"posada": 1}},
            {"id": "posada", "label": "posada", "affordances": ["cama"],
             "neighbors": {"mazmorra": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "posada",
             "start_at": "mazmorra"},
        ],
        "tuning": {"memory_capacity": 20, "memory_scale": 1.0,
                   "critical_need_threshold": 0.15},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_a_wound_remembers_where_you_got_it() -> None:
    sim = Simulation(dos_sitios(), seed=1)
    sim.afligir(AG1, HERIDA, marca="cuerpo")
    assert sim.state.agents[AG1].condiciones[0].donde == MAZMORRA


def test_the_first_one_keeps_the_place() -> None:
    """Reescribirlo con el de la última haría que la mazmorra donde casi te matan
    se borrase por un rasguño reciente en la plaza. Lo que enseña a temer un
    lugar es lo que empezó, no lo que remató."""
    sim = Simulation(dos_sitios(), seed=1)
    sim.afligir(AG1, HERIDA, marca="cuerpo")
    sim.state.agents[AG1].at = POSADA
    sim.afligir(AG1, HERIDA, marca="cuerpo")

    cond = sim.state.agents[AG1].condiciones[0]
    assert cond.veces == 2, "se agravó, como debe"
    assert cond.donde == MAZMORRA, "y sigue apuntando a donde empezó"


def test_you_fear_the_dungeon_and_not_the_bed() -> None:
    """**Lo que este campo viene a arreglar, de una pieza.**

    Se hiere al agente en la mazmorra, se le lleva a la posada, y se le deja
    sangrar hasta cruzar el umbral. El recuerdo tiene que llevar la mazmorra
    aunque el agente esté durmiendo en su cama cuando ocurre.
    """
    sim = Simulation(dos_sitios(), seed=1)
    sim.afligir(AG1, HERIDA, marca="cuerpo")
    sim.state.agents[AG1].at = POSADA
    sim.run(6)

    assert sim.state.agents[AG1].at == POSADA, "se desangró en su cama"
    doloroso = [
        r for r in sim.state.memoria.de(AG1)
        if r.valencia < 0.0 and r.culpable is not None and r.action is None
    ]
    assert doloroso, "no quedó grabado nada con culpable"
    assert doloroso[0].place == MAZMORRA, "aprendió a temer su propia cama"

    pavor = sim.state.memoria.miedo(AG1, sim.state.tick, escala=1.0)
    assert MAZMORRA in pavor
    assert POSADA not in pavor


def test_a_place_situation_still_hurts_where_you_stand() -> None:
    """Solo las condiciones cambian de sitio. Una ventisca hace daño donde estás,
    y ahí el lugar ya era el correcto — corregirlo también habría sido romper lo
    que funcionaba."""
    pack = dos_sitios(**{"situations": [
        {"id": "herida", "label": "herida", "personal": True,
         "effects": {"sangre": -0.02}},
        {"id": "ventisca", "label": "ventisca", "places": ["mazmorra"],
         "effects": {"sangre": -0.06}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.begin_situation(SituationId("ventisca"), ticks=20)
    sim.run(4)

    doloroso = [
        r for r in sim.state.memoria.de(AG1)
        if r.valencia < 0.0 and r.culpable == SituationId("ventisca")
    ]
    assert doloroso, "la ventisca no dejó marca"
    assert doloroso[0].place == MAZMORRA, "donde le pilló, que es donde estaba"


def test_it_survives_a_save(tmp_path: Any) -> None:
    from agora.engine.persistence import load, save

    pack = dos_sitios()
    sim = Simulation(pack, seed=1)
    sim.afligir(AG1, HERIDA, marca="cuerpo")

    fichero = tmp_path / "partida.json"
    save(sim.state, set(), fichero)
    vuelto, _ = load(fichero, pack)
    assert vuelto.agents[AG1].condiciones[0].donde == MAZMORRA


def test_an_old_save_reads_as_a_wound_without_a_place(tmp_path: Any) -> None:
    """Compatibilidad hacia atrás: un guardado anterior a este campo se lee como
    una herida que sigue doliendo pero de la que ya no se sabe el sitio."""
    import json

    pack = dos_sitios()
    sim = Simulation(pack, seed=1)
    sim.afligir(AG1, HERIDA, marca="cuerpo")
    fichero = tmp_path / "vieja.json"
    save_mod = __import__("agora.engine.persistence", fromlist=["save", "load"])
    save_mod.save(sim.state, set(), fichero)

    datos = json.loads(fichero.read_text(encoding="utf-8"))
    for a in datos["agents"]:
        a["condiciones"] = [fila[:4] for fila in a["condiciones"]]
    fichero.write_text(json.dumps(datos), encoding="utf-8")

    vuelto, _ = save_mod.load(fichero, pack)
    cond = vuelto.agents[AG1].condiciones[0]
    assert cond.situacion == HERIDA and cond.veces == 1
    assert cond.donde is None
