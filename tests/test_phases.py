"""Tests del ciclo de día y noche.

Hasta aquí el reloj era **decorativo**: `ticks_per_day` solo lo leían el
renderizador y el bucle, para saber cuándo parar. Nada de la deliberación lo
consultaba, así que el motor no sabía que era de noche y la gente se acostaba
escalonada a cualquier hora, cuando el cansancio apretaba.

Dos principios, y el segundo costó una medición entera:

**Las franjas las declara el pack.** El motor no sabe qué es "la noche". Sabe
que el ciclo se parte en tramos con nombre. Un pack podría declarar
`marea_alta` y `marea_baja`.

**El cronotipo es un desfase, no una preferencia.** La primera versión daba a
cada rasgo multiplicadores por franja. Falla al medirla: con `dormir` favorecido
de noche, un rasgo nocturno que multiplica lo nocturno hace que el búho duerma
MÁS de noche, al revés de lo que se quiere. Y dejar el sueño neutro para
esquivarlo deja al descanso sin ancla horaria — medido, la gente dormía a
cualquier hora y la aldea tenía el mismo trasiego a las cuatro de la mañana que
a mediodía.

Rotando la franja PERCIBIDA todo cae solo: para un ave nocturna la noche no vale
más, la noche *es* su mañana. Lo que no se rota son los horarios de los lugares:
la herrería cierra a la misma hora para todos.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from agora.agents.decide import candidates, is_available, phase_fit
from agora.engine.disposition import compose_phase_shift
from agora.engine.ontology import (
    ActionId,
    AgentId,
    ClockSpec,
    NeedId,
    PhaseId,
    PhaseSpec,
    PlaceId,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.render import format_time
from agora.engine.state import WorldState
from agora.engine.world import Simulation

N1 = NeedId("n1")
AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
DIA = PhaseId("dia")
NOCHE = PhaseId("noche")
LABOR = ActionId("act_labor")
LIBRE = ActionId("act_libre")

SIN_FRANJAS: dict[str, Any] = {"minutes_per_tick": 60, "ticks_per_day": 20}
ACCIONES_LLANAS: list[dict[str, Any]] = [
    {
        "id": "act_labor",
        "label": "act_labor",
        "duration_ticks": 2,
        "requires_affordance": "aff",
        "satisfies": {"n1": 0.8},
        "effects": {"n1": 0.6},
    },
    {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
]


def phase_pack(**overrides: Any) -> ContentPack:
    """Dos franjas de 10 ticks. `act_labor` solo cunde de día."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "clock": {
            "minutes_per_tick": 60,
            "ticks_per_day": 20,
            "phases": [
                {"id": "dia", "label": "dia", "starts_at": 4},
                {"id": "noche", "label": "noche", "starts_at": 14},
            ],
        },
        "needs": [{"id": "n1", "label": "n1", "decay_per_tick": 0.02, "initial": 0.5}],
        "traits": [{"id": "nocturnidad", "label": "nocturnidad", "phase_shift": 10}],
        "actions": [
            {
                "id": "act_labor",
                "label": "act_labor",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 0.8},
                "effects": {"n1": 0.6},
                "phase_multipliers": {"noche": 0.2},
            },
            {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"critical_need_threshold": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def flat_pack(**overrides: Any) -> ContentPack:
    """El mismo mundo sin franjas. Quitarlas obliga a quitar lo que las nombra."""
    base: dict[str, Any] = {
        "clock": SIN_FRANJAS,
        "traits": [{"id": "nocturnidad", "label": "nocturnidad"}],
        "actions": ACCIONES_LLANAS,
    }
    base.update(overrides)
    return phase_pack(**base)


def cierra_de_noche() -> list[dict[str, Any]]:
    return [
        {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
        {
            "id": "p2",
            "label": "p2",
            "affordances": ["aff"],
            "neighbors": {"p1": 1},
            "open_during": ["dia"],
        },
    ]


# --- el reloj sabe la hora ---------------------------------------------------


def test_a_world_without_phases_has_no_moments() -> None:
    """Y todo lo horario queda inerte sin una condición en el motor."""
    assert ClockSpec().phase_at(0) is None


def test_the_phase_is_found_by_the_tick() -> None:
    clock = phase_pack().clock
    assert clock.phase_at(4) == DIA
    assert clock.phase_at(13) == DIA
    assert clock.phase_at(14) == NOCHE


def test_before_the_first_phase_belongs_to_the_last() -> None:
    """Así una noche declarada en el tick 14 cubre también la madrugada, sin
    partirla en dos franjas que serían la misma."""
    clock = phase_pack().clock
    assert clock.phase_at(0) == NOCHE
    assert clock.phase_at(3) == NOCHE


def test_the_cycle_wraps() -> None:
    clock = phase_pack().clock
    assert clock.phase_at(24) == clock.phase_at(4)


def test_phases_out_of_order_are_rejected() -> None:
    with pytest.raises(ValidationError, match="antes o a la vez"):
        ClockSpec(
            ticks_per_day=20,
            phases=(
                PhaseSpec(id=PhaseId("b"), label="b", starts_at=10),
                PhaseSpec(id=PhaseId("a"), label="a", starts_at=2),
            ),
        )


def test_a_phase_outside_the_cycle_is_rejected() -> None:
    with pytest.raises(ValidationError, match="fuera del ciclo"):
        ClockSpec(
            ticks_per_day=20,
            phases=(PhaseSpec(id=PhaseId("a"), label="a", starts_at=40),),
        )


# --- la hora cambia lo que rinde ---------------------------------------------


def test_an_action_without_declared_phases_is_indifferent() -> None:
    libre = phase_pack().action_by_id[LIBRE]
    assert phase_fit(libre, DIA) == 1.0
    assert phase_fit(libre, NOCHE) == 1.0


def test_a_world_without_phases_leaves_it_inert() -> None:
    assert phase_fit(phase_pack().action_by_id[LABOR], None) == 1.0


def test_the_world_declares_when_things_pay_off() -> None:
    labor = phase_pack().action_by_id[LABOR]
    assert phase_fit(labor, DIA) == 1.0
    assert phase_fit(labor, NOCHE) == pytest.approx(0.2)


# --- el cronotipo es un desfase ----------------------------------------------


def test_the_chronotype_shifts_the_clock() -> None:
    pack = phase_pack()
    assert compose_phase_shift(pack, {TraitId("nocturnidad"): 1.0}) == 10
    assert compose_phase_shift(pack, {TraitId("nocturnidad"): 0.0}) == 0


def test_the_shift_inverts_with_the_sign() -> None:
    """No hace falta un rasgo `diurnidad`: es el nocturno con el signo cambiado.

    Con un ciclo de 20 ticks, adelantar 10 y atrasar 10 caen en el mismo sitio —
    media vuelta es media vuelta en los dos sentidos.
    """
    assert compose_phase_shift(phase_pack(), {TraitId("nocturnidad"): -1.0}) == 10


def test_the_shift_wraps_into_the_cycle() -> None:
    """Un desfase mayor que el ciclo no significa nada nuevo."""
    pack = phase_pack(traits=[{"id": "nocturnidad", "label": "n", "phase_shift": 25}])
    assert compose_phase_shift(pack, {TraitId("nocturnidad"): 1.0}) == 5


def test_a_world_without_phases_has_no_shift() -> None:
    assert compose_phase_shift(flat_pack(), {TraitId("nocturnidad"): 1.0}) == 0


def test_a_shift_without_phases_is_rejected() -> None:
    """Declararlo sin franjas no hace nada, y no hacer nada en silencio es peor
    que fallar ruidosamente."""
    with pytest.raises(ValidationError, match="el reloj no"):
        flat_pack(traits=[{"id": "nocturnidad", "label": "n", "phase_shift": 10}])


def test_a_typo_in_a_phase_is_caught() -> None:
    """Sin esto no hay síntoma: el multiplicador no se aplica nunca y la herrería
    que creías cerrada sigue abierta."""
    with pytest.raises(ValidationError, match="franja desconocida"):
        phase_pack(
            actions=[
                {
                    "id": "act_labor",
                    "label": "act_labor",
                    "duration_ticks": 2,
                    "requires_affordance": "aff",
                    "satisfies": {"n1": 0.8},
                    "effects": {"n1": 0.6},
                    "phase_multipliers": {"medianoche": 0.2},
                },
                {"id": "act_libre", "label": "act_libre", "duration_ticks": 1},
            ]
        )


# --- cerrar es una puerta, no un descuento -----------------------------------


def test_a_closed_place_offers_nothing() -> None:
    pack = phase_pack(places=cierra_de_noche())
    accion, lugar = pack.action_by_id[LABOR], pack.place_by_id[P2]
    assert is_available(accion, lugar, None, {N1: 1.0}, DIA)
    assert not is_available(accion, lugar, None, {N1: 1.0}, NOCHE)


def test_an_empty_schedule_means_always_open() -> None:
    pack = phase_pack()
    accion, lugar = pack.action_by_id[LABOR], pack.place_by_id[P2]
    assert is_available(accion, lugar, None, {N1: 1.0}, NOCHE)


def test_closing_does_not_block_the_road() -> None:
    """Si cerrar cortara aristas, el mundo dejaría de estar fuertemente conexo a
    ciertas horas y alguien podría quedarse encerrado lejos de su cama."""
    world = WorldState.new(phase_pack(places=cierra_de_noche()), seed=1)
    assert world.travel.distance(P1, P2) == 1


def test_a_place_closed_forever_is_rejected() -> None:
    """`open_during` vacío ya significa siempre abierto, así que declararlo con
    franjas inexistentes solo puede ser una errata."""
    with pytest.raises(ValidationError, match="franja desconocida"):
        phase_pack(
            places=[
                {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
                {
                    "id": "p2",
                    "label": "p2",
                    "affordances": ["aff"],
                    "neighbors": {"p1": 1},
                    "open_during": ["crepusculo"],
                },
            ]
        )


# --- se nota en la conducta --------------------------------------------------


def test_the_same_option_scores_differently_by_hour() -> None:
    world = WorldState.new(phase_pack(), seed=1)
    agent = world.agents[AG1]

    world.tick = 5  # de día
    de_dia = next(d for d in candidates(world, agent) if d.action == LABOR)
    world.tick = 15  # de noche
    de_noche = next(d for d in candidates(world, agent) if d.action == LABOR)

    assert de_dia.utility > de_noche.utility


def test_the_night_owl_and_the_early_bird_diverge() -> None:
    """Misma ficha salvo un eje, y a la misma hora valoran lo mismo distinto."""
    pack = phase_pack(
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "traits": {"nocturnidad": 1.0},
            },
            {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1"},
        ]
    )
    world = WorldState.new(pack, seed=1)
    world.tick = 15  # noche de verdad

    buho = next(d for d in candidates(world, world.agents[AG1]) if d.action == LABOR)
    normal = next(d for d in candidates(world, world.agents[AG2]) if d.action == LABOR)
    # Para el búho su reloj marca las 5: de día, y la faena cunde.
    assert buho.utility > normal.utility


def test_the_body_clock_shifts_but_the_shutters_do_not() -> None:
    """El horario del mundo es objetivo; el del cuerpo, subjetivo.

    Si el desfase moviera también las aperturas, un ave nocturna se encontraría
    la herrería abierta a las tres de la mañana solo por serlo.
    """
    pack = phase_pack(
        places=cierra_de_noche(),
        agents=[
            {
                "id": "ag1",
                "label": "ag1",
                "home": "p1",
                "start_at": "p1",
                "traits": {"nocturnidad": 1.0},
            }
        ],
    )
    world = WorldState.new(pack, seed=1)
    world.tick = 15  # noche real, "día" para el búho
    assert not any(d.action == LABOR for d in candidates(world, world.agents[AG1]))


def test_a_run_changes_when_the_clock_is_read() -> None:
    def trayectoria(pack: ContentPack) -> list[str]:
        sim = Simulation(pack, seed=1)
        sim.run(200)
        return [f"{e.tick}:{e.kind}:{e.action}" for e in sim.log]

    assert trayectoria(phase_pack()) != trayectoria(flat_pack())


def test_the_log_shows_the_phase() -> None:
    clock = phase_pack().clock
    assert format_time(15, clock).endswith("noche")
    assert format_time(5, clock).endswith("dia")


def test_a_world_without_phases_keeps_the_bare_stamp() -> None:
    assert format_time(5, ClockSpec()) == "d1 01:15"
