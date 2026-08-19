"""El techo: hasta dónde puede llegar cada cual, y el lazo que sí se gana.

Dos huecos que destapó una corrida larga —doscientos agentes, año y medio— y que
ninguna calibración podía tapar porque no eran de calibración.

**El techo.** Un ritmo no es un tope. Con `gain_multipliers` bajo se tarda más en
llegar a 1.0, pero con tiempo suficiente llega todo el mundo: los doscientos
acabaron al máximo del eje de dominio y el sistema de rangos —Novato a
Trascendente— se quedó sin significar nada. Bajar la tasa solo habría movido la
fecha. Un techo es escala-invariante: quién llega adónde deja de ser cuestión de
tiempo y pasa a ser cuestión de quién eres.

**El lazo.** Cruzarse no es convivir. El motor ya lo distinguía —`meet` da
reconocimiento, `remember_company` da afecto— pero contaba solo los cruces, así
que dos que se ven cien veces sin hablarse eran indistinguibles de dos que se ven
veinte y comparten diez.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.disposition import compose_caps, urgency
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import AgentState
from agora.engine.world import Simulation

DOM = NeedId("dominio")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
DON = TraitId("don")


def techo_pack(**overrides: Any) -> ContentPack:
    """`dominio` llega a 0.35 para cualquiera; el don lo multiplica por 2.8."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
            {"id": "dominio", "label": "dominio", "decay_per_tick": 0.0,
             "initial": 0.05, "progression": True, "cap": 0.35},
        ],
        "traits": [
            {"id": "don", "label": "don", "cap_multipliers": {"dominio": 2.8}},
        ],
        "actions": [
            {"id": "practicar", "label": "practicar", "duration_ticks": 1,
             "requires_affordance": "aff", "satisfies": {"dominio": 1.0},
             "effects": {"dominio": 0.05}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {}}
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def agente(pack: ContentPack, **traits: float) -> AgentState:
    a = AgentState(spec_id=AG1, at=P1, needs={NeedId("n1"): 0.6, DOM: 0.05},
                   traits={TraitId(k): v for k, v in traits.items()})
    a.recompose(pack)
    return a


# --- la composición del techo ------------------------------------------------


def test_without_a_gift_you_reach_what_anyone_reaches() -> None:
    assert compose_caps(techo_pack(), {})[DOM] == pytest.approx(0.35)


def test_a_need_without_a_cap_is_the_world_of_always() -> None:
    """Lo ausente vale 1.0: un pack que no declare techos se comporta igual que
    antes de que esto existiera."""
    assert compose_caps(techo_pack(), {})[NeedId("n1")] == 1.0


def test_the_gift_raises_the_ceiling() -> None:
    assert compose_caps(techo_pack(), {DON: 1.0})[DOM] == pytest.approx(0.98)


def test_birth_and_learned_are_the_same_trait_at_two_intensities() -> None:
    """**La regla del sistema de magia, sin caso especial.** Con tu elemento
    llegas a lo mas alto; con el que estudiaste te quedas a mitad de camino."""
    pack = techo_pack()
    nacimiento = compose_caps(pack, {DON: 1.00})[DOM]
    aprendida = compose_caps(pack, {DON: 0.35})[DOM]
    assert nacimiento == pytest.approx(0.98)
    assert aprendida == pytest.approx(0.35 * 2.8**0.35)
    assert nacimiento > aprendida > 0.35


def test_no_gift_takes_you_past_the_world() -> None:
    """Se recorta a 1.0: un don enorme deja llegar al final del rango, no salirse
    de el."""
    pack = techo_pack(
        **{"traits": [{"id": "don", "label": "don",
                       "cap_multipliers": {"dominio": 50.0}}]}
    )
    assert compose_caps(pack, {DON: 1.0})[DOM] == 1.0


# --- el techo se respeta de verdad -------------------------------------------


def test_you_cannot_grow_past_your_ceiling() -> None:
    pack = techo_pack()
    a = agente(pack)
    for _ in range(50):
        a.apply({DOM: 0.05}, pack.need_by_id)
    assert a.needs[DOM] == pytest.approx(0.35)


def test_a_gifted_agent_goes_further() -> None:
    pack = techo_pack()
    normal, dotado = agente(pack), agente(pack, don=1.0)
    for a in (normal, dotado):
        for _ in range(50):
            a.apply({DOM: 0.05}, pack.need_by_id)
    assert dotado.needs[DOM] > normal.needs[DOM]


def test_time_does_not_beat_a_ceiling() -> None:
    """**Lo que un ritmo no puede dar.** Con aptitud baja se tarda mas y se llega
    igual; con techo, no se llega nunca. Es lo que hace que la distribucion siga
    abierta a los diez anos sin tocar una sola tasa."""
    pack = techo_pack()
    a = agente(pack)
    for _ in range(100_000):
        a.apply({DOM: 0.05}, pack.need_by_id)
    assert a.needs[DOM] == pytest.approx(0.35)


# --- y deja de apretar al llegar ---------------------------------------------


def test_urgency_is_measured_against_your_own_ceiling() -> None:
    """Sin esto un techo seria una trampa: quien ya lo dio todo seguiria
    sintiendo la mitad del apremio y se pasaria la vida entrenando algo que no
    puede mejorar."""
    assert urgency(0.35, 2.0, cap=0.35) == pytest.approx(0.0)
    assert urgency(0.35, 2.0, cap=1.0) == pytest.approx(0.4225)


def test_a_capped_agent_spends_its_life_elsewhere() -> None:
    """En un mundo corriendo: quien tiene techo bajo deja de perseguir ese eje y
    dedica su tiempo a otra cosa.

    Se compara contra un dotado y no contra el cero absoluto, y la distincion
    importa: el motor promete que **cuando todo vale cero se hace algo razonable
    ahi mismo**, y entrenar es tan razonable como quedarse quieto. Lo que el
    techo cambia no es que deje de entrenar del todo, es que deja de PREFERIRLO
    en cuanto hay algo que si le hace falta.
    """
    pack = techo_pack(
        **{
            "actions": [
                {"id": "practicar", "label": "practicar", "duration_ticks": 1,
                 "requires_affordance": "aff", "satisfies": {"dominio": 1.0},
                 "effects": {"dominio": 0.05}},
                {"id": "descansar", "label": "descansar", "duration_ticks": 1,
                 "requires_affordance": "aff", "satisfies": {"n1": 1.0},
                 "effects": {"n1": 0.12}},
                {"id": "nada", "label": "nada", "duration_ticks": 1},
            ],
            "agents": [
                {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
                {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1",
                 "traits": {"don": 1.0}},
            ],
        }
    )
    sim = Simulation(pack, seed=5)
    sim.run(600)

    topado = sim.state.agents[AG1]
    dotado = sim.state.agents[AG2]
    assert topado.needs[DOM] == pytest.approx(0.35)
    assert dotado.needs[DOM] > 0.9, "el dotado tenia sitio para seguir"

    rec = sim.log.recuento.por_agente_accion
    practica = ActionId("practicar")
    assert rec[AG1][practica] < rec[AG2][practica], (
        "el topado deberia haber dejado de perseguir un eje que no puede mover"
    )


# --- el lazo que se gana -----------------------------------------------------


def test_crossing_paths_is_not_sharing() -> None:
    """Dos que se ven cien veces sin dirigirse la palabra se distinguen y nada
    mas. `meet` no toca `shared` jamas."""
    a = AgentState(spec_id=AG1, at=P1, needs={})
    for t in range(100):
        a.meet(AG2, tick=t)
    assert a.bonds[AG2].encounters == 100
    assert a.bonds[AG2].shared == 0
    assert a.bonds[AG2].regard == 0.0


def test_sharing_counts_apart() -> None:
    a = AgentState(spec_id=AG1, at=P1, needs={})
    for t in range(20):
        a.meet(AG2, tick=t)
    for t in range(10):
        a.remember_company([AG2], premium=0.4, rate=0.3, tick=t)
    bond = a.bonds[AG2]
    assert bond.encounters == 20
    assert bond.shared == 10
    assert bond.regard > 0.0


def test_two_pairs_that_used_to_look_identical() -> None:
    """La razon de que el campo exista. Antes, la unica diferencia visible entre
    estos dos pares era el aprecio, que mezcla cuanto valio con cuantas veces."""
    vecinos = AgentState(spec_id=AG1, at=P1, needs={})
    amigos = AgentState(spec_id=AG2, at=P1, needs={})
    for t in range(100):
        vecinos.meet(AG2, tick=t)
    for t in range(20):
        amigos.meet(AG1, tick=t)
    for t in range(10):
        amigos.remember_company([AG1], premium=0.4, rate=0.3, tick=t)

    assert vecinos.bonds[AG2].encounters > amigos.bonds[AG1].encounters
    assert vecinos.bonds[AG2].shared == 0
    assert amigos.bonds[AG1].shared == 10
