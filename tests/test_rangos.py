"""Rangos numerados: un eje sin techo donde cada paso cuesta más que el anterior.

**Reemplaza al techo plano, y por una medición.** Un `cap` fijo sobre un eje de
progresión no arreglaba nada: hacía que la gente llegara a su tope ANTES, y el
contenido que dependía de ese eje se moría aún más deprisa.

    sin techo    expoliar por tramo   142 → 346 → 208 → 112
    con techo                         110 → 232 →  61 →  22

El problema nunca fue que el eje se saturase. Es que **atar contenido a un eje de
progresión le pone fecha de caducidad por construcción**: con techo antes, sin
techo después.

Los rangos lo rompen porque **no hay techo**. El valor vive en `[0,1]` y dice
*cuánto llevas de este rango*; al llenarlo, el rango sube uno y vuelve a empezar.
Siempre queda algo que aprender, y siempre cuesta más que la vez anterior:

    ritmo(rango) = ritmo_base / (1 + rango) ** rank_slowdown

Al novato todo le enseña; al maestro ya casi nada. La cuesta no modela que el
mundo se ponga difícil — modela que **queda menos por aprender**.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.persistence import load, save
from agora.engine.state import AgentState
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
P1 = PlaceId("p1")
DOM = NeedId("dominio")
PRACTICAR = ActionId("practicar")
PRODIGIO = TraitId("prodigio")


def rango_pack(**overrides: Any) -> ContentPack:
    """`dominio` con rangos: se llena, sube, y cada vuelta cunde menos."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
            {"id": "dominio", "label": "dominio", "decay_per_tick": 0.0,
             "initial": 0.0, "progression": True, "rank_slowdown": 1.0},
        ],
        "traits": [
            {"id": "prodigio", "label": "prodigio",
             "gain_multipliers": {"dominio": 3.0}},
        ],
        "actions": [
            {"id": "practicar", "label": "practicar", "duration_ticks": 1,
             "requires_affordance": "aff", "satisfies": {"dominio": 1.0},
             "effects": {"dominio": 0.25}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {}}
        ],
        "agents": [{"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"}],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agente(pack: ContentPack, **traits: float) -> AgentState:
    a = AgentState(spec_id=AG1, at=P1,
                   needs={NeedId("n1"): 0.6, DOM: 0.0},
                   traits={TraitId(k): v for k, v in traits.items()})
    a.recompose(pack)
    return a


# --- sin techo ----------------------------------------------------------------


def test_filling_the_axis_breaks_a_rank_instead_of_stopping() -> None:
    """La diferencia entera con un `cap`: ahí se acababa, aquí se empieza otra
    vuelta."""
    pack = rango_pack()
    a = agente(pack)
    rotos = a.apply({DOM: 4.0}, pack.need_by_id)

    assert rotos == [DOM]
    assert a.rango[DOM] == 1
    assert a.needs[DOM] == 0.0, "se empieza el siguiente desde el principio"


def test_there_is_no_ceiling() -> None:
    """Cien vueltas y sigue subiendo. **Siempre se puede ser más fuerte.**"""
    pack = rango_pack()
    a = agente(pack)
    for _ in range(4000):
        a.apply({DOM: 1.0}, pack.need_by_id)
    assert a.rango[DOM] > 20, "se atascó en algún tope"


def test_an_axis_without_ranks_behaves_as_always() -> None:
    """Estrenar esto no puede mover ningún contrato ya medido."""
    pack = rango_pack(**{"needs": [
        {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
        {"id": "dominio", "label": "dominio", "decay_per_tick": 0.0,
         "initial": 0.0, "progression": True},
    ]})
    a = agente(pack)
    assert a.apply({DOM: 4.0}, pack.need_by_id) == []
    assert a.rango == {}
    assert a.needs[DOM] == 1.0, "se queda arriba, como siempre"


# --- y cada vuelta cuesta más -------------------------------------------------


def test_the_rate_is_inversely_proportional_to_the_rank() -> None:
    pack = rango_pack()
    a = agente(pack)
    spec = pack.need_by_id[DOM]

    assert a.ritmo_de_rango(spec) == pytest.approx(1.0)
    a.rango[DOM] = 1
    assert a.ritmo_de_rango(spec) == pytest.approx(0.5)
    a.rango[DOM] = 3
    assert a.ritmo_de_rango(spec) == pytest.approx(0.25)


def test_each_rank_costs_more_than_the_one_before() -> None:
    """**La curva entera, en un test.** Al novato todo le enseña; al maestro
    casi nada."""
    pack = rango_pack()
    a = agente(pack)
    cuestas = []
    for esperado in (1, 2, 3, 4):
        ticks = 0
        while a.rango.get(DOM, 0) < esperado and ticks < 10_000:
            a.apply({DOM: 0.05}, pack.need_by_id)
            ticks += 1
        cuestas.append(ticks)

    assert cuestas == sorted(cuestas), "algún rango costó menos que el anterior"
    assert cuestas[-1] > cuestas[0] * 3, "la cuesta apenas se nota"


def test_the_slowdown_is_a_knob_and_zero_turns_it_off() -> None:
    suave = rango_pack(**{"needs": [
        {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
        {"id": "dominio", "label": "dominio", "decay_per_tick": 0.0,
         "initial": 0.0, "progression": True, "rank_slowdown": 0.5},
    ]})
    a = agente(suave)
    a.rango[DOM] = 3
    assert a.ritmo_de_rango(suave.need_by_id[DOM]) == pytest.approx(0.5)


# --- dos personas, la misma cuesta, tiempos distintos -------------------------


def test_a_prodigy_climbs_the_same_ladder_faster() -> None:
    """**El dinamismo por individuo.** Misma escalera, misma cuesta: lo que
    cambia es quién la sube. Sale de `gain_multipliers`, que ya existía."""
    pack = rango_pack()
    corriente, prodigio = agente(pack), agente(pack, prodigio=1.0)
    for _ in range(300):
        corriente.apply({DOM: 0.05}, pack.need_by_id)
        prodigio.apply({DOM: 0.05}, pack.need_by_id)

    assert prodigio.rango[DOM] > corriente.rango[DOM]


def test_a_lower_personal_bar_also_climbs_faster() -> None:
    """La otra palanca: cuánto te cuesta A TI romper el listón. Un `cap` por
    debajo de 1.0 significa que rompes antes, no que llegas menos lejos — que es
    justo lo que un techo no podía expresar hasta ahora."""
    pack = rango_pack(**{"traits": [
        {"id": "prodigio", "label": "prodigio",
         "cap_multipliers": {"dominio": 0.5}},
    ]})
    corriente, prodigio = agente(pack), agente(pack, prodigio=1.0)
    assert prodigio.caps[DOM] < corriente.caps[DOM]

    for _ in range(200):
        corriente.apply({DOM: 0.05}, pack.need_by_id)
        prodigio.apply({DOM: 0.05}, pack.need_by_id)
    assert prodigio.rango[DOM] > corriente.rango[DOM]


# --- lo que se lee y lo que se cuenta -----------------------------------------


def test_breaking_a_rank_is_worth_telling() -> None:
    """`dominio 0.4` no dice nada; `rango 7 y va por el 0.4 del octavo` sí. Y es
    de las pocas cosas que un habitante contaría en la taberna."""
    sim = Simulation(rango_pack(), seed=1)
    sim.run(40)

    subidas = sim.log.of_kind(EventKind.RANK_UP)
    assert subidas, "nadie subió de rango en cuarenta ticks practicando"
    assert subidas[0].data is not None
    assert subidas[0].data["need"] == "dominio"
    assert subidas[0].data["rango"] == 1


def test_a_gate_can_ask_for_a_rank() -> None:
    """Novena puerta. `requires: {dominio: 0.30}` decía «que lleves el 30 % de tu
    rango actual», que es cierto para un novato y para un maestro por igual — y
    por tanto no dice nada. Lo que un conjuro difícil quiere es rango 3."""
    from agora.agents.decide import is_available

    pack = rango_pack(**{"actions": [
        {"id": "practicar", "label": "practicar", "duration_ticks": 1,
         "requires_affordance": "aff", "satisfies": {"dominio": 1.0},
         "effects": {"dominio": 0.25}},
        {"id": "conjuro_mayor", "label": "conjuro mayor", "duration_ticks": 1,
         "requires_affordance": "aff", "requires_rank": {"dominio": 3},
         "satisfies": {"n1": 1.0}, "effects": {"n1": 0.3}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    spec = pack.action_by_id[ActionId("conjuro_mayor")]
    lugar, necesidades = pack.place_by_id[P1], {NeedId("n1"): 0.6, DOM: 0.9}

    assert not is_available(spec, lugar, 0, necesidades, rango={DOM: 2})
    assert is_available(spec, lugar, 0, necesidades, rango={DOM: 3})
    assert is_available(spec, lugar, 0, necesidades), "sin rango, se resuelve a favor"


def test_the_rank_survives_a_save(tmp_path: Any) -> None:
    """Sin esto, reanudar devuelve a todo el mundo a novato: el valor del eje se
    guardaba, pero no significa nada sin el rango que lo acompaña."""
    pack = rango_pack()
    sim = Simulation(pack, seed=1)
    sim.run(60)
    antes = sim.state.agents[AG1].rango.get(DOM, 0)
    assert antes > 0

    fichero = tmp_path / "partida.json"
    save(sim.state, set(), fichero)
    vuelto, _ = load(fichero, pack)
    assert vuelto.agents[AG1].rango[DOM] == antes
