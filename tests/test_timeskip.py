"""Tests del salto temporal.

Una carrera de cinco anos son 172 800 ticks, y casi todo es rutina. El salto
simula dias DE VERDAD, solo que menos: uno de cada `factor`, y a los ejes que
solo suben se les da el avance de los `factor` completos.

La consecuencia que lo justifica todo: **lo que oscila queda exacto porque no se
estima, se simula.** Lo unico aproximado es lo monotono, que es lo suave.

Costo cuatro disenos llegar aqui. Los tres primeros PROYECTABAN cada eje segun su
ritmo medido, y ninguno servia: un eje en equilibrio tiene deriva cero, pero
medida sobre catorce dias da un numero pequeno distinto de cero que multiplicado
por ciento ochenta desplaza medio punto. Se probo con extremos, con medias de dos
mitades y con senal contra ruido; los tres dejaban desviaciones de 0.2 en ejes
como el vinculo.
"""

from __future__ import annotations

import copy
import statistics
from typing import Any

import pytest

from agora.engine.ontology import AgentId, NeedId
from agora.engine.pack import ContentPack
from agora.engine.timeskip import error_de_salto, saltar
from agora.engine.world import Simulation

HAMBRE = NeedId("hambre")
SABER = NeedId("saber")
AG1 = AgentId("ag1")


def skip_pack(**overrides: Any) -> ContentPack:
    """Un eje que oscila (hambre) y otro que solo sube (saber)."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.02, "initial": 0.7,
             "urgency_exponent": 2.0},
            {"id": "saber", "label": "saber", "decay_per_tick": 0.0, "progression": True,
             "initial": 0.0, "base_weight": 0.4, "urgency_exponent": 0.8},
        ],
        "actions": [
            {"id": "comer", "label": "comer", "duration_ticks": 3,
             "satisfies": {"hambre": 0.9}, "effects": {"hambre": 0.8}},
            {"id": "estudiar", "label": "estudiar", "duration_ticks": 5,
             "requires_affordance": "aula",
             "satisfies": {"saber": 0.6}, "effects": {"saber": 0.004}},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aula"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {"critical_need_threshold": 0.15},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def asentado(dias: int = 20) -> Simulation:
    """Un mundo que ya rueda. Saltar desde el tick cero mide el transitorio."""
    sim = Simulation(skip_pack(), seed=1312)
    sim.run(dias * 96)
    return sim


# --- lo que garantiza -------------------------------------------------------


def test_factor_one_is_not_a_shortcut() -> None:
    """La comprobacion de cordura: sin atajo, el salto ES la simulacion."""
    base = asentado()
    real = copy.deepcopy(base)
    real.run(40 * 96)
    salt = copy.deepcopy(base)
    saltar(salt, 40, factor=1)

    assert salt.state.tick == real.state.tick
    for a in real.state.agents_in_order():
        assert salt.state.agents[a.spec_id].needs == a.needs


def test_the_clock_lands_where_it_should() -> None:
    sim = asentado()
    antes = sim.state.tick
    saltar(sim, 90, factor=7)
    assert sim.state.tick == antes + 90 * 96


def test_it_simulates_only_a_fraction() -> None:
    sim = asentado()
    salto = saltar(sim, 90, factor=7)
    assert salto.dias_simulados == 13  # ceil(90/7)
    assert salto.ahorro == pytest.approx(90 / 13)


def test_only_progression_gets_the_stride() -> None:
    """Un eje que se mece NO se amplifica: se simula, y asi no hay que estimarlo."""
    sim = asentado()
    salto = saltar(sim, 30, factor=7)
    assert salto.amplificados == frozenset({SABER})


# --- y lo que consigue -------------------------------------------------------


def test_progression_lands_where_it_would_have() -> None:
    """El eje PARA EL QUE existe el salto."""
    base = asentado()
    real = copy.deepcopy(base)
    real.run(120 * 96)
    salt = copy.deepcopy(base)
    saltar(salt, 120, factor=7)

    esperado = statistics.mean(a.needs[SABER] for a in real.state.agents_in_order())
    obtenido = statistics.mean(a.needs[SABER] for a in salt.state.agents_in_order())
    assert obtenido == pytest.approx(esperado, abs=0.08)


def test_what_oscillates_stays_where_it_belongs() -> None:
    """No se estima: se simula. Asi que la poblacion queda en su equilibrio.

    Se compara la media de la POBLACION y no agente por agente: dos mundos sanos
    pueden tener a la misma persona en distinto punto de su ciclo sin que ninguno
    este mal.
    """
    base = asentado()
    real = copy.deepcopy(base)
    real.run(120 * 96)
    salt = copy.deepcopy(base)
    saltar(salt, 120, factor=7)

    esperado = statistics.mean(a.needs[HAMBRE] for a in real.state.agents_in_order())
    obtenido = statistics.mean(a.needs[HAMBRE] for a in salt.state.agents_in_order())
    assert obtenido == pytest.approx(esperado, abs=0.15)


def test_the_error_is_reported_not_hidden() -> None:
    """Un salto es una aproximacion, y el pack tiene derecho a saber cuanta."""
    error = error_de_salto(asentado(), 90, factor=7)
    assert set(error) == {HAMBRE, SABER}
    assert all(v >= 0.0 for v in error.values())


def test_a_bigger_factor_costs_accuracy() -> None:
    """La perilla hace lo que dice: mas rapido, mas grueso."""
    base = asentado()
    suave = saltar(copy.deepcopy(base), 120, factor=3)
    bruto = saltar(copy.deepcopy(base), 120, factor=20)
    assert bruto.dias_simulados < suave.dias_simulados
    assert bruto.ahorro > suave.ahorro


# --- lo que se habria roto sin cuidarlo --------------------------------------


def test_nobody_forgets_the_city_after_a_skip() -> None:
    """El fallo mas facil de cometer aqui.

    Los vinculos y los avistamientos guardan CUANDO. Si el reloj salta seis meses
    y sus marcas no, todo caduca de golpe: nadie recuerda un sitio y
    `forget_bonds` borra a la ciudad entera al primer tick.
    """
    pack = skip_pack(tuning={"critical_need_threshold": 0.15, "bond_horizon": 2880,
                             "bond_rate": 0.2, "bond_scale": 0.05,
                             "sighting_horizon": 96})
    sim = Simulation(pack, seed=1312)
    sim.run(20 * 96)
    assert sim.state.agents[AG1].bonds
    assert sim.state.agents[AG1].sightings

    saltar(sim, 180, factor=7)
    sim.run(96)  # el tick siguiente, que es donde se borraria

    assert sim.state.agents[AG1].bonds, "la ciudad se habria olvidado entera"
    assert sim.state.agents[AG1].sightings


def test_the_stride_respects_the_ceiling() -> None:
    """Amplificar pasa por `restore`, no por asignacion: el techo sigue siendo 1."""
    sim = asentado()
    saltar(sim, 400, factor=20)
    for a in sim.state.agents_in_order():
        assert 0.0 <= a.needs[SABER] <= 1.0


def test_goals_close_during_the_skip_not_after() -> None:
    """Un arco que se cumple a mitad del salto se cumple a mitad del salto.

    Importa porque el logro mueve rasgos, y los rasgos cambian el ritmo de todo
    lo que venga despues. Cerrar todo al final seria otra historia.
    """
    pack = skip_pack(
        agents=[
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
             "goals": [{"id": "sabio", "label": "sabio", "need": "saber",
                        "at_least": 0.5, "on_success": {}}]},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ]
    )
    sim = Simulation(pack, seed=1312)
    saltar(sim, 200, factor=7)

    from agora.engine.events import EventKind
    from agora.engine.ontology import GoalStatus

    logros = sim.log.of_kind(EventKind.GOAL_ACHIEVED)
    assert logros, "deberia haberse cumplido"
    assert logros[0].tick < sim.state.tick, "y no en el ultimo tick"
    assert sim.state.agents[AG1].goals["sabio"] == GoalStatus.ACHIEVED  # type: ignore[index]
