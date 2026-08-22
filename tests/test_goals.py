"""Tests de metas y arcos.

Una necesidad y una meta no son lo mismo, y la diferencia es toda la gracia: la
necesidad se agota y se mantiene, la meta se cumple **una vez**. Lo primero
produce rutina; lo segundo, historia.

Mecánicamente no hizo falta un término nuevo en la fórmula. `need_weights` ya es
el dial que dice cuánto le importa algo a alguien, y una meta es exactamente eso
subido un rato: un empujón **temporal y personal** que se apaga al lograrse.

Y el arco es lo que pasa después. `drift_trait` llevaba desde F1 construido y sin
llamarse nunca; esto es lo que lo estrena. Sin la deriva, el personaje llega a su
meta y sigue siendo exactamente quien era, que es lo contrario de una historia.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.disposition import compose_need_weights
from agora.engine.events import EventKind
from agora.engine.ontology import (
    AgentId,
    GoalId,
    GoalSpec,
    GoalStatus,
    NeedId,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation

ORO = NeedId("oro")
PAN = NeedId("pan")
AG1 = AgentId("ag1")
AVARICIA = TraitId("avaricia")
IRSE = GoalId("irse")


def goal_pack(**overrides: Any) -> ContentPack:
    """Alguien que junta oro para marcharse, come para no morirse, y tiene una
    tentación que le desvía.

    El ocio existe para que la meta tenga algo QUE VENCER. Sin competencia el
    agente perseguiría el oro de todos modos y la meta no cambiaría nada: medido
    en una versión anterior de este mundo, con meta llegaba al umbral en el tick
    38 y sin ella en el 39. Una diferencia de un tick no demuestra un mecanismo.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "oro", "label": "oro", "decay_per_tick": 0.001, "initial": 0.1,
             "base_weight": 1.0, "urgency_exponent": 1.5},
            {"id": "pan", "label": "pan", "decay_per_tick": 0.02, "initial": 0.8,
             "base_weight": 1.0, "urgency_exponent": 2.0},
            {"id": "ocio", "label": "ocio", "decay_per_tick": 0.02, "initial": 0.5,
             "base_weight": 1.4, "urgency_exponent": 1.6},
        ],
        "traits": [
            {"id": "avaricia", "label": "avaricia", "need_weight_multipliers": {"oro": 2.0}},
            {"id": "arraigo", "label": "arraigo",
             "temperament_multipliers": {"travel_discount": 0.8}},
        ],
        "actions": [
            {"id": "trabajar", "label": "trabajar", "duration_ticks": 6,
             "satisfies": {"oro": 0.6}, "costs": {"pan": 0.1, "ocio": 0.4},
             "effects": {"oro": 0.05, "pan": -0.02, "ocio": -0.10}},
            {"id": "holgar", "label": "holgar", "duration_ticks": 4,
             "satisfies": {"ocio": 0.8}, "effects": {"ocio": 0.5}},
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"pan": 0.9}, "effects": {"pan": 0.9}},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "goals": [
                    {
                        "id": "irse",
                        "label": "irse del pueblo",
                        "need": "oro",
                        "at_least": 0.7,
                        "weight_multiplier": 3.0,
                        "on_success": {"arraigo": -0.6},
                        "on_failure": {"arraigo": 0.5},
                    }
                ],
            }
        ],
        "tuning": {"critical_need_threshold": 0.15},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def sin_meta() -> ContentPack:
    return goal_pack(agents=[{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}])


# --- una meta es un empujón sobre un dial que ya existía ----------------------


def test_a_goal_lifts_the_weight_of_its_axis() -> None:
    pack = goal_pack()
    meta = pack.agent_by_id[AG1].goals[0]
    sin = compose_need_weights(pack, {})
    con = compose_need_weights(pack, {}, (meta,))
    assert con[ORO] == pytest.approx(sin[ORO] * 3.0)


def test_it_leaves_the_other_axes_alone() -> None:
    pack = goal_pack()
    meta = pack.agent_by_id[AG1].goals[0]
    assert compose_need_weights(pack, {}, (meta,))[PAN] == compose_need_weights(pack, {})[PAN]


def test_a_goal_bites_harder_on_someone_who_already_cared() -> None:
    """Multiplica, no suma. Querer irse pesa distinto en un avaro."""
    pack = goal_pack()
    meta = pack.agent_by_id[AG1].goals[0]
    normal = compose_need_weights(pack, {}, (meta,))[ORO]
    avaro = compose_need_weights(pack, {AVARICIA: 1.0}, (meta,))[ORO]
    assert avaro == pytest.approx(normal * 2.0)


def test_the_agent_starts_out_pursuing_it() -> None:
    world = WorldState.new(goal_pack(), seed=1)
    agente = world.agents[AG1]
    assert agente.goals[IRSE] is GoalStatus.ACTIVE
    assert len(agente.pursuing(world.pack)) == 1


def test_someone_without_goals_is_legitimate() -> None:
    world = WorldState.new(sin_meta(), seed=1)
    assert world.agents[AG1].goals == {}
    assert world.agents[AG1].pursuing(world.pack) == ()


# --- se cumple una vez, y entonces deja de empujar ---------------------------


def test_reaching_the_threshold_closes_it() -> None:
    sim = Simulation(goal_pack(), seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.72
    sim.tick()
    assert sim.state.agents[AG1].goals[IRSE] is GoalStatus.ACHIEVED


def test_the_push_is_given_back() -> None:
    """Si siguiera pesando después de conseguirla, sería una necesidad con otro
    nombre."""
    sim = Simulation(goal_pack(), seed=1)
    antes = sim.state.agents[AG1].need_weights[ORO]
    sim.state.agents[AG1].needs[ORO] = 0.72
    sim.tick()
    assert sim.state.agents[AG1].need_weights[ORO] == pytest.approx(antes / 3.0)


def test_it_only_closes_once() -> None:
    sim = Simulation(goal_pack(), seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.9
    sim.run(20)
    logros = sim.log.of_kind(EventKind.GOAL_ACHIEVED)
    assert len(logros) == 1


def test_the_world_writes_it_down() -> None:
    """Nada muta el estado sin emitir un evento: el narrador vivirá de esto."""
    sim = Simulation(goal_pack(), seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.72
    sim.tick()
    evento = sim.log.of_kind(EventKind.GOAL_ACHIEVED)[0]
    assert evento.actor == AG1
    assert evento.data["goal"] == "irse"


# --- el arco: lograrlo te cambia ---------------------------------------------


def test_achieving_it_moves_the_person() -> None:
    """Se fue del pueblo, así que ya no es el que no salía."""
    sim = Simulation(goal_pack(), seed=1)
    agente = sim.state.agents[AG1]
    assert agente.traits.get(TraitId("arraigo"), 0.0) == 0.0
    agente.needs[ORO] = 0.72
    sim.tick()
    assert agente.traits[TraitId("arraigo")] == pytest.approx(-0.6)


def test_the_drift_reaches_the_temperament() -> None:
    """No basta con mover el rasgo: hay que recomponer lo que depende de él."""
    sim = Simulation(goal_pack(), seed=1)
    agente = sim.state.agents[AG1]
    antes = agente.temperament.travel_discount
    agente.needs[ORO] = 0.72
    sim.tick()
    assert agente.temperament.travel_discount > antes


def test_a_goal_without_drift_still_closes() -> None:
    """El arco es opcional; cerrar la meta no."""
    pack = goal_pack(
        agents=[
            {
                "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                "goals": [{"id": "irse", "label": "irse", "need": "oro", "at_least": 0.7}],
            }
        ]
    )
    sim = Simulation(pack, seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.9
    sim.tick()
    assert sim.state.agents[AG1].goals[IRSE] is GoalStatus.ACHIEVED


# --- el plazo, y el otro final -----------------------------------------------


def test_the_deadline_loses_it() -> None:
    pack = goal_pack(
        agents=[
            {
                "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                "goals": [
                    {
                        "id": "irse", "label": "irse", "need": "oro", "at_least": 0.99,
                        "deadline": 5, "on_failure": {"arraigo": 0.5},
                    }
                ],
            }
        ]
    )
    sim = Simulation(pack, seed=1)
    sim.run(6)
    agente = sim.state.agents[AG1]
    assert agente.goals[IRSE] is GoalStatus.FAILED
    assert agente.traits[TraitId("arraigo")] == pytest.approx(0.5)
    assert sim.log.of_kind(EventKind.GOAL_FAILED)


def test_beating_the_deadline_wins() -> None:
    """El plazo no cierra lo que ya estaba conseguido."""
    pack = goal_pack(
        agents=[
            {
                "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                "goals": [
                    {"id": "irse", "label": "irse", "need": "oro",
                     "at_least": 0.5, "deadline": 3},
                ],
            }
        ]
    )
    sim = Simulation(pack, seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.6
    sim.run(10)
    assert sim.state.agents[AG1].goals[IRSE] is GoalStatus.ACHIEVED


def test_without_a_deadline_it_waits_forever() -> None:
    sim = Simulation(goal_pack(), seed=1)
    sim.state.agents[AG1].needs[ORO] = 0.0
    sim.run(50)
    assert not sim.log.of_kind(EventKind.GOAL_FAILED)


# --- y se nota en la conducta -------------------------------------------------


def test_the_goal_changes_what_he_does() -> None:
    """Lo único que separa las dos corridas es querer algo."""

    def trayectoria(pack: ContentPack) -> list[str]:
        sim = Simulation(pack, seed=1)
        sim.run(200)
        return [f"{e.tick}:{e.kind}:{e.action}" for e in sim.log]

    assert trayectoria(goal_pack()) != trayectoria(sin_meta())


def test_wanting_it_makes_him_get_there_sooner() -> None:
    """Lo que la meta cambia es la PRISA, no el techo.

    Comparar el estado final no distingue nada: en un mundo donde el oro se
    puede llenar, los dos acaban llenos. Lo que separa a quien lo quiere de
    quien no es cuánto tarda.
    """

    def cuando_llega(pack: ContentPack, umbral: float = 0.7) -> int:
        sim = Simulation(pack, seed=1)
        for tick in range(1, 401):
            sim.tick()
            if sim.state.agents[AG1].needs[ORO] >= umbral:
                return tick
        return 10**6

    assert cuando_llega(goal_pack()) < cuando_llega(sin_meta())


def test_a_whole_arc_runs_on_its_own() -> None:
    """Nadie escribió "trabaja hasta 0.7 y luego relájate"."""
    sim = Simulation(goal_pack(), seed=1)
    sim.run(400)
    agente = sim.state.agents[AG1]
    assert agente.goals[IRSE] is GoalStatus.ACHIEVED
    assert agente.traits[TraitId("arraigo")] == pytest.approx(-0.6)


# --- validaciones ------------------------------------------------------------


def test_an_unknown_need_is_caught() -> None:
    with pytest.raises(ValidationError, match="necesidad desconocida"):
        goal_pack(
            agents=[
                {
                    "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                    "goals": [{"id": "x", "label": "x", "need": "gloria", "at_least": 0.5}],
                }
            ]
        )


def test_an_unknown_drift_trait_is_caught() -> None:
    with pytest.raises(ValidationError, match="rasgo desconocida/o"):
        goal_pack(
            agents=[
                {
                    "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                    "goals": [
                        {"id": "x", "label": "x", "need": "oro", "at_least": 0.5,
                         "on_success": {"templanza": -0.5}},
                    ],
                }
            ]
        )


def test_an_unreachable_goal_is_caught() -> None:
    """Un umbral difícil es diseño; un eje que nadie sube es una errata."""
    with pytest.raises(ValidationError, match="ninguna acción sube"):
        goal_pack(
            actions=[
                {"id": "comer", "label": "comer", "duration_ticks": 2,
                 "satisfies": {"pan": 0.9}, "effects": {"pan": 0.9}},
            ]
        )


def test_two_goals_with_the_same_id_are_caught() -> None:
    """El estado las colapsaría en una y la segunda no existiría."""
    with pytest.raises(ValidationError, match="id duplicado"):
        goal_pack(
            agents=[
                {
                    "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                    "goals": [
                        {"id": "x", "label": "a", "need": "oro", "at_least": 0.5},
                        {"id": "x", "label": "b", "need": "oro", "at_least": 0.9},
                    ],
                }
            ]
        )


def test_two_people_may_want_the_same_thing() -> None:
    """La unicidad es por ficha, no global: querer lo mismo es lo natural."""
    pack = goal_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
             "goals": [{"id": "irse", "label": "irse", "need": "oro", "at_least": 0.7}]},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2",
             "goals": [{"id": "irse", "label": "irse", "need": "oro", "at_least": 0.7}]},
        ]
    )
    assert len(pack.agents) == 2


def test_an_absurd_drift_is_caught() -> None:
    """Los rasgos viven en [-1, 1]; un 2 ya cruza el rango entero."""
    with pytest.raises(ValidationError, match="fuera de"):
        GoalSpec(
            id=IRSE, label="irse", need=ORO, at_least=0.5,
            on_success={TraitId("arraigo"): -9.0},
        )


# --- una meta sobre el RANGO -------------------------------------------------
#
# **La ambicion arquetipica de un mundo con rangos, y era la unica que no se
# podia escribir.** Con `rank_slowdown`, el valor del eje vuelve a cero cada vez
# que se rompe un rango, asi que un `at_least` sobre el se cumple con el primero
# y no significa nada. Salio de medir: en confluencia, con el umbral al filo del
# maximo alcanzable y plazo de ciento veinte dias, **119 metas cumplidas de 119
# y cero falladas**. No era el numero: era el eje.


def rango_pack(**overrides: Any) -> ContentPack:
    """Un mundo con un eje de rangos y alguien que quiere llegar lejos."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "pan", "label": "pan", "decay_per_tick": 0.02, "initial": 0.9},
            {"id": "arte", "label": "arte", "decay_per_tick": 0.0, "initial": 0.0,
             "progression": True, "rank_slowdown": 1.0, "cap": 0.20},
        ],
        "actions": [
            {"id": "ensayar", "label": "ensayar", "duration_ticks": 2,
             "satisfies": {"arte": 1.0}, "effects": {"arte": 0.05}},
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"pan": 0.9}, "effects": {"pan": 0.9}},
        ],
        "places": [{"id": "p1", "label": "p1", "neighbors": {}}],
        "agents": [{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [{"id": "maestria", "label": "llegar a maestro",
                       "need": "arte", "at_rank": 6,
                       "on_success": {}, "on_failure": {}}],
        }],
        "tuning": {"critical_need_threshold": 0.15, "memory_capacity": 400,
                   "memory_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_a_rank_goal_needs_the_ranks_and_not_the_value() -> None:
    """Romper un rango no la cierra: hacen falta los tres. Con `at_least` sobre
    el mismo eje se habria cerrado con el primero, que es justo el fallo."""
    sim = Simulation(rango_pack(), seed=1)
    sim.run(60)
    assert sim.state.agents[AG1].rango.get(NeedId("arte"), 0) >= 1, "ya rompió alguno"
    assert sim.state.agents[AG1].goals[GoalId("maestria")] is GoalStatus.ACTIVE


def test_and_it_closes_when_the_ranks_are_there() -> None:
    sim = Simulation(rango_pack(), seed=1)
    sim.run(4000)
    assert sim.state.agents[AG1].rango[NeedId("arte")] >= 6
    assert sim.state.agents[AG1].goals[GoalId("maestria")] is GoalStatus.ACHIEVED


def test_the_higher_the_rank_the_deeper_the_mark() -> None:
    """Lo que se graba sale de lo que la meta EXIGIA, no de cómo anda el eje al
    cerrarla. Con rangos el déficit no existe —el eje vuelve a cero— así que se
    usa la curva de saturación de siempre sobre el rango pedido: `n/(n+1)`."""
    def marca(rango: int) -> float:
        pack = rango_pack(agents=[{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [{"id": "maestria", "label": "llegar a maestro",
                       "need": "arte", "at_rank": rango}],
        }])
        # Se lee EN CUANTO cierra: con capacidad 40, dejarlo correr mil ticks
        # más desaloja el logro por rutina, que es el olvido funcionando.
        sim = Simulation(pack, seed=1)
        while sim.state.agents[AG1].goals[GoalId("maestria")] is GoalStatus.ACTIVE:
            assert sim.state.tick < 12000, "no llegó nunca"
            sim.tick()
        logros = [r for r in sim.state.memoria.de(AG1) if r.valencia >= 1.0]
        assert logros, "no se grabó el logro"
        return max(r.importancia for r in logros)

    assert marca(4) > marca(1)


def test_exactly_one_way_to_measure_it() -> None:
    """Ni las dos ni ninguna. Con las dos habria que decidir si se cumple con
    una o con ambas, y cualquier respuesta seria una convencion que nadie
    recuerda al leer el pack."""
    for mal in ({}, {"at_least": 0.5, "at_rank": 3}):
        with pytest.raises(ValidationError, match="EXACTAMENTE una"):
            GoalSpec.model_validate({"id": "x", "label": "x", "need": "arte", **mal})


def test_a_rank_goal_on_an_axis_without_ranks_does_not_load() -> None:
    """El mismo error que pedir un eje que ninguna acción sube, con otra cara:
    el número nunca sube de cero y el agente se queda escorado de por vida."""
    with pytest.raises(ValueError, match="no tiene `rank_slowdown`"):
        rango_pack(agents=[{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [{"id": "x", "label": "x", "need": "pan", "at_rank": 2}],
        }])


# --- las otras dos varas, y EL ORDEN -----------------------------------------
#
# Un arco no necesita primitiva: es lo que emerge de metas encadenadas. Lo que
# faltaba era poder medir mas de una cosa y poder decir cual va antes.


def arco_pack(**overrides: Any) -> ContentPack:
    """Un arco de tres eslabones sobre el mismo mundo de rangos.

        1  llegar a rango 1                    abierta de salida
        2  ser alguien (rasgo `nombrado`)      la abre la 1, y la 1 lo concede
        3  llegar a rango 3                    la abre la 2

    El rasgo del eslabon 2 no lo mueve nada del mundo: lo concede el
    `on_success` del 1. Es el unico camino que hay hoy para que un rasgo cambie,
    y por eso `at_traits` y `requires_goal` se escribieron juntos.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "pan", "label": "pan", "decay_per_tick": 0.02, "initial": 0.9},
            {"id": "arte", "label": "arte", "decay_per_tick": 0.0, "initial": 0.0,
             "progression": True, "rank_slowdown": 1.0, "cap": 0.20},
        ],
        "traits": [{"id": "nombrado", "label": "nombrado",
                    "need_weight_multipliers": {"arte": 1.2}}],
        "actions": [
            {"id": "ensayar", "label": "ensayar", "duration_ticks": 2,
             "satisfies": {"arte": 1.0}, "effects": {"arte": 0.05}},
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"pan": 0.9}, "effects": {"pan": 0.9}},
        ],
        "places": [{"id": "p1", "label": "p1", "neighbors": {}}],
        "agents": [{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [
                {"id": "primero", "label": "empezar", "need": "arte",
                 "at_rank": 1, "on_success": {"nombrado": 1.0}},
                {"id": "segundo", "label": "ser alguien", "need": "arte",
                 "at_traits": {"nombrado": 1.0}, "requires_goal": "primero"},
                {"id": "tercero", "label": "llegar lejos", "need": "arte",
                 "at_rank": 3, "requires_goal": "segundo"},
            ],
        }],
        "tuning": {"critical_need_threshold": 0.15, "memory_capacity": 400,
                   "memory_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_what_depends_on_another_is_born_locked() -> None:
    world = WorldState.new(arco_pack(), seed=1)
    metas = world.agents[AG1].goals
    assert metas[GoalId("primero")] is GoalStatus.ACTIVE
    assert metas[GoalId("segundo")] is GoalStatus.LOCKED
    assert metas[GoalId("tercero")] is GoalStatus.LOCKED


def test_a_locked_goal_pushes_nothing() -> None:
    """Si empujara mientras espera, el arco no seria un orden: seria tres deseos
    a la vez con nombres distintos."""
    world = WorldState.new(arco_pack(), seed=1)
    assert [g.id for g in world.agents[AG1].pursuing(world.pack)] == [GoalId("primero")]


def test_a_locked_goal_cannot_fail() -> None:
    """No puedes perder lo que aun no habias empezado. Un plazo corriendo
    mientras esperas castigaria por algo que no dependia de ti."""
    pack = arco_pack(agents=[{
        "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
        "goals": [
            {"id": "primero", "label": "empezar", "need": "arte", "at_rank": 40},
            {"id": "segundo", "label": "despues", "need": "arte", "at_rank": 1,
             "requires_goal": "primero", "deadline": 5},
        ],
    }])
    sim = Simulation(pack, seed=1)
    sim.run(60)
    assert sim.state.agents[AG1].goals[GoalId("segundo")] is GoalStatus.LOCKED
    assert sim.log.of_kind(EventKind.GOAL_FAILED) == []


def test_the_whole_chain_runs_by_itself() -> None:
    """**Lo que estas tres piezas compran, de una pieza.** Nadie orquesta nada:
    cada eslabon se abre cuando el anterior se cierra, y el del medio se mide
    con un rasgo que la primera meta concedio."""
    sim = Simulation(arco_pack(), seed=1)
    sim.run(4000)
    metas = sim.state.agents[AG1].goals
    assert metas[GoalId("primero")] is GoalStatus.ACHIEVED
    assert metas[GoalId("segundo")] is GoalStatus.ACHIEVED
    assert metas[GoalId("tercero")] is GoalStatus.ACHIEVED

    abiertas = sim.log.of_kind(EventKind.GOAL_UNLOCKED)
    assert [e.data["goal"] for e in abiertas] == ["segundo", "tercero"]
    # Y en ORDEN: cada una se abre despues de que se cierre la suya.
    cierres = {e.data["goal"]: e.tick for e in sim.log.of_kind(EventKind.GOAL_ACHIEVED)}
    assert cierres["primero"] <= cierres["segundo"] <= cierres["tercero"]


def test_a_trait_goal_reads_the_trait_and_not_the_axis() -> None:
    sim = Simulation(arco_pack(), seed=1)
    sim.run(4000)
    # El rasgo llego por la deriva de la primera meta, no por el mundo.
    assert sim.state.agents[AG1].traits[TraitId("nombrado")] >= 1.0


def test_counting_kin_is_a_conjunction() -> None:
    """Pide TODO lo que nombra. Y hoy se decide en el tick 0: nada anuda lazos
    en marcha, asi que el validador avisa de las dos formas de ser inutil."""
    with pytest.raises(ValueError, match=r"se cerraría en el primer tick"):
        arco_pack(
            relations=[{"id": "discipulo", "label": "discipulo", "symmetric": True}],
            agents=[{
                "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                "relations": {"discipulo": ["ag2"]},
                "goals": [{"id": "x", "label": "x", "need": "arte",
                           "at_kin": {"discipulo": 1}}],
            }, {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1"}],
        )


def test_a_trait_nobody_grants_is_caught() -> None:
    with pytest.raises(ValueError, match="solo las derivas mueven un rasgo"):
        arco_pack(agents=[{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [{"id": "x", "label": "x", "need": "arte",
                       "at_traits": {"nombrado": 1.0}}],
        }])


def test_waiting_for_someone_elses_goal_is_caught() -> None:
    with pytest.raises(ValueError, match="no es una meta suya"):
        arco_pack(agents=[{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [{"id": "x", "label": "x", "need": "arte", "at_rank": 1,
                       "requires_goal": "la_de_otro"}],
        }])


def test_a_chain_that_bites_its_tail_is_caught() -> None:
    """Un ciclo deja a todas sus metas bloqueadas para siempre, y en silencio:
    no fallan, no empujan, no salen en el panel."""
    with pytest.raises(ValueError, match="ciclo de metas"):
        arco_pack(agents=[{
            "id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
            "goals": [
                {"id": "a", "label": "a", "need": "arte", "at_rank": 1,
                 "requires_goal": "b"},
                {"id": "b", "label": "b", "need": "arte", "at_rank": 2,
                 "requires_goal": "a"},
            ],
        }])


def test_a_goal_cannot_open_itself() -> None:
    with pytest.raises(ValidationError, match="se abre a sí misma"):
        GoalSpec.model_validate({"id": "x", "label": "x", "need": "arte",
                                 "at_rank": 1, "requires_goal": "x"})


def test_still_exactly_one_condition_with_four_to_choose_from() -> None:
    for mal in ({}, {"at_rank": 1, "at_traits": {"nombrado": 1.0}},
                {"at_least": 0.5, "at_kin": {"discipulo": 2}}):
        with pytest.raises(ValidationError, match="EXACTAMENTE una"):
            GoalSpec.model_validate({"id": "x", "label": "x", "need": "arte", **mal})
