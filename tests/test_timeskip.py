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

from agora.engine.ontology import AgentId, NeedId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.state import Bond
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
    error = error_de_salto(asentado(), 90, factor=7).ejes
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


# --- lo que el salto SI extrapola (D-085) -------------------------------------
#
# La regla del modulo es no adivinar: se simulan dias de verdad, solo que menos.
# Una condicion personal es la unica excepcion, y no la contradice: no hay
# ninguna deriva que medir, porque una condicion drena `effects * gravedad` cada
# tick, viaja con quien la lleva y no depende de donde este ni de lo que haga.
# Multiplicarlo por los ticks saltados es aritmetica, no una suposicion.
#
# Las situaciones del LUGAR no entran, y la diferencia es justo esa: dependen de
# donde estuviera cada cual, y eso no se simulo.


def herido_pack(**overrides: Any) -> ContentPack:
    """Un mundo con una condicion que drena y mata, y nada que la cure."""
    data: dict[str, Any] = {
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.02, "initial": 0.7,
             "urgency_exponent": 2.0},
            {"id": "saber", "label": "saber", "decay_per_tick": 0.0, "progression": True,
             "initial": 0.0, "base_weight": 0.4, "urgency_exponent": 0.8},
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0, "initial": 1.0,
             "lethal_after": 8},
        ],
        "situations": [
            {"id": "hemorragia", "label": "hemorragia", "personal": True,
             "effects": {"salud": -0.0005}},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return skip_pack(**data)


def test_a_condition_charges_the_stride() -> None:
    """Sin esto, la salud de un herido bajaba `factor` veces mas despacio que en
    el mundo real mientras el reloj avanzaba igual."""
    seguido = Simulation(herido_pack(), seed=1312)
    seguido.state.agents[AgentId("ag1")].afligir(SituationId("hemorragia"))
    seguido.run(7 * 96)

    saltado = Simulation(herido_pack(), seed=1312)
    saltado.state.agents[AgentId("ag1")].afligir(SituationId("hemorragia"))
    saltar(saltado, 7, 7)

    real = seguido.state.agents[AgentId("ag1")].needs[NeedId("salud")]
    atajo = saltado.state.agents[AgentId("ag1")].needs[NeedId("salud")]
    assert atajo == pytest.approx(real, abs=0.02)


def test_severity_multiplies_the_stride_too() -> None:
    uno = Simulation(herido_pack(), seed=1312)
    uno.state.agents[AgentId("ag1")].afligir(SituationId("hemorragia"), gravedad=1.0)
    saltar(uno, 7, 7)
    grave = Simulation(herido_pack(), seed=1312)
    grave.state.agents[AgentId("ag1")].afligir(SituationId("hemorragia"), gravedad=2.0)
    saltar(grave, 7, 7)

    leve = 1.0 - uno.state.agents[AgentId("ag1")].needs[NeedId("salud")]
    fuerte = 1.0 - grave.state.agents[AgentId("ag1")].needs[NeedId("salud")]
    assert fuerte == pytest.approx(leve * 2.0, rel=0.05)


def test_under_a_skip_somebody_can_finally_die() -> None:
    """Era la consecuencia que el modulo tenia escrita como limite: bajo salto no
    se moria nadie por necesidad, porque la agonia se borraba en cada zancada.
    Una carrera de anyos no producia una sola muerte, y eso no es un mundo
    conservador: es un mundo distinto."""
    sim = Simulation(herido_pack(), seed=1312)
    sim.state.agents[AgentId("ag1")].afligir(SituationId("hemorragia"), gravedad=4.0)
    saltar(sim, 120, 7)
    assert AgentId("ag1") not in sim.state.agents
    assert AgentId("ag2") in sim.state.agents, "el que no sangraba sigue vivo"


def test_getting_up_from_zero_still_wipes_the_clock() -> None:
    """La objecion original sigue contestada, y ahora por el propio dia simulado:
    quien come, se levanta del cero, y entonces la agonia no avanza nada."""
    sim = Simulation(skip_pack(**{"needs": [
        {"id": "hambre", "label": "hambre", "decay_per_tick": 0.02, "initial": 0.02,
         "urgency_exponent": 2.0, "lethal_after": 200},
        {"id": "saber", "label": "saber", "decay_per_tick": 0.0, "progression": True,
         "initial": 0.0, "base_weight": 0.4, "urgency_exponent": 0.8},
    ]}), seed=1312)
    saltar(sim, 60, 7)
    assert AgentId("ag1") in sim.state.agents, "come, así que no se muere de hambre"
    assert not sim.state.agents[AgentId("ag1")].agonia


def test_a_place_situation_does_not_charge_the_stride() -> None:
    """Depende de donde estuviera cada cual, y eso no se simulo."""
    sim = Simulation(skip_pack(**{
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.02, "initial": 0.7,
             "urgency_exponent": 2.0},
            {"id": "saber", "label": "saber", "decay_per_tick": 0.0, "progression": True,
             "initial": 0.0, "base_weight": 0.4, "urgency_exponent": 0.8},
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0, "initial": 1.0},
        ],
        "situations": [
            {"id": "ventisca", "label": "ventisca", "every": 96, "lasts": 95,
             "effects": {"salud": -0.002}},
        ],
    }), seed=1312)
    saltar(sim, 7, 7)
    # Siete dias de reloj, uno simulado: pierde lo de UN dia (0.002 * 96), no lo
    # de siete. Si la ventisca cobrara la zancada estaria muerto.
    perdido = 1.0 - sim.state.agents[AgentId("ag1")].needs[NeedId("salud")]
    assert perdido == pytest.approx(0.002 * 96, abs=0.02)


# --- lo que el hueco SI envejece (D-088) ---------------------------------------


def test_only_who_you_saw_today_keeps_a_fresh_mark() -> None:
    """Las marcas de «cuando lo vi» adelantaban TODAS con el reloj, y el motivo
    era bueno: sin eso un salto de seis meses caducaria de golpe la memoria del
    mundo entero. Pero el instrumento era romo — para no caducar los vinculos de
    la gente con la que convives, congelaba tambien los de la gente a la que no
    ves, y con ellos `tick - last_seen` no crecia nunca."""
    sim = Simulation(skip_pack(), seed=1312)
    sim.run(96)
    ag1 = sim.state.agents[AgentId("ag1")]
    # Alguien a quien no ve desde hace mucho, y que no aparecera hoy.
    ag1.bonds[AgentId("fantasma")] = Bond(regard=0.5, encounters=1, last_seen=0)
    antes_vecino = dict(ag1.bonds)

    saltar(sim, 7, 7)

    hueco_fantasma = sim.state.tick - ag1.bonds[AgentId("fantasma")].last_seen
    assert hueco_fantasma > 96 * 6, "al que no viste, el hueco le cuenta entero"
    # Y a quien SI se vio hoy no le caduca nada, que es lo que el adelanto
    # protegia desde el principio.
    vistos = [
        o for o, b in antes_vecino.items()
        if o != AgentId("fantasma") and b.last_seen > 0
    ]
    for otro in vistos:
        assert sim.state.tick - sim.state.agents[AgentId("ag1")].bonds[otro].last_seen < 96 * 2


def test_the_instrument_counts_events_and_not_only_averages() -> None:
    """Una media poblacional no ve lo que NO ocurrio. Con solo los ejes, este
    instrumento decia que el salto estaba sano mientras suprimia la mitad de las
    muertes del mundo."""
    f = error_de_salto(asentado(dias=5), 20, factor=5)
    assert set(f.sucesos()) == {
        "muertes", "partos", "lazos rotos", "lazos nuevos", "poblacion"
    }
    assert f.poblacion[0] == f.poblacion[1] == 2
    assert f.ejes, "y los ejes siguen estando"
