"""Tests de `company_scale`: qué es una multitud en este mundo.

La curva de la compañía estuvo clavada en `n/(n+1)`, **y eso es una aldea**. Con
esa escala tres personas ya dan tres cuartos del máximo y a partir de ahí es
casi plana. Medido en la ciudad, la ocupación media es de 14.4 personas: todo lo
social vivía pegado al techo y las gradaciones del pack no discriminaban nada.

El síntoma era que el vínculo NUNCA llegó a ser urgente —cero veces en 256 000
muestras— mientras el panel de salud decía que el mundo estaba sano.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import NeedId
from agora.engine.outcome import company_saturation, signed_saturation
from agora.engine.pack import ContentPack
from agora.engine.state import Ledger
from agora.engine.world import Simulation
from agora.health import measure

SED = NeedId("sed")
AGENTES = 8


def scale_pack(**overrides: Any) -> ContentPack:
    """Un mundo con una necesidad social y gente de sobra en un solo sitio."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "sed", "label": "sed", "decay_per_tick": 0.01, "initial": 0.6,
             "company_relief": 0.01},
        ],
        "actions": [
            {"id": "beber", "label": "beber", "duration_ticks": 2,
             "satisfies": {"sed": 0.9}, "effects": {"sed": 0.4},
             "effects_per_company": {"sed": 0.3}},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": f"ag{i}", "label": f"ag{i}", "home": "p1", "start_at": "p1"}
            for i in range(AGENTES)
        ],
        "tuning": {"bond_weight": 0.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- la curva -----------------------------------------------------------------


def test_scale_one_is_exactly_what_there_was() -> None:
    """Ningún pack calibrado se mueve. Es la condición para poder añadirla."""
    for n in (0.0, 1.0, 3.0, 14.0, -3.0):
        assert company_saturation(n, 1.0) == pytest.approx(n / (abs(n) + 1.0))
        assert company_saturation(n) == pytest.approx(company_saturation(n, 1.0))


def test_a_bigger_scale_makes_a_crowd_count_less() -> None:
    """Lo que la perilla existe para hacer."""
    assert company_saturation(14, 1.0) == pytest.approx(0.933, abs=0.001)
    assert company_saturation(14, 4.0) == pytest.approx(0.778, abs=0.001)
    assert company_saturation(14, 8.0) == pytest.approx(0.636, abs=0.001)


def test_a_bigger_scale_restores_the_gradation() -> None:
    """El motivo de fondo: con la curva plana, el pack distingue con cuidado 0.25
    y 0.50 por compañía y las dos se multiplican por lo mismo."""
    plana = company_saturation(14, 1.0) - company_saturation(2, 1.0)
    ancha = company_saturation(14, 8.0) - company_saturation(2, 8.0)
    assert ancha > plana * 1.5


def test_it_stays_signed() -> None:
    """Mala compañía sigue restando, con cualquier escala. Un cuarto con alguien
    que no soportas es más solitario que un cuarto vacío."""
    for k in (1.0, 4.0, 8.0):
        assert company_saturation(-3.0, k) < 0.0
        assert company_saturation(0.0, k) == 0.0


# --- la separación que evita que se filtre ------------------------------------


def test_the_bond_curve_does_not_inherit_the_knob() -> None:
    """`company_premium` normaliza una cantidad de UTILIDAD, no personas.

    Si compartieran función, decir "aquí una multitud son ocho" movería de
    rebote la escala del aprecio, en silencio, y con ella una calibración que
    costó una medición encontrar.
    """
    assert signed_saturation(0.5) == pytest.approx(0.5 / 1.5)
    assert signed_saturation(0.5, 4.0) == pytest.approx(0.5 / 4.5)
    # Y `company_saturation` es solo la curva aplicada a gente.
    assert company_saturation(0.5, 4.0) == signed_saturation(0.5, 4.0)


def test_the_knob_is_positive() -> None:
    """A cero, `saturación(0)` sería 0/0."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        scale_pack(tuning={"company_scale": 0.0})


# --- lo que cambia en un mundo de verdad --------------------------------------


def test_a_bigger_scale_makes_the_axis_scarcer() -> None:
    """La prueba que importa: con la misma gente y los mismos números, subir la
    escala hace que la necesidad social deje de estar resuelta."""
    floja = measure(scale_pack(), days=4, seeds=(1312,))
    dura = measure(
        scale_pack(tuning={"bond_weight": 0.0, "company_scale": 8.0}), days=4, seeds=(1312,)
    )
    assert floja.supply[SED] > dura.supply[SED]


def test_it_cuts_what_arrives_for_free() -> None:
    """El alivio pasivo es lo que más se lleva la escala: con la curva de aldea,
    estar rodeado cubre casi todo el decaimiento sin hacer nada."""
    floja = measure(scale_pack(), days=4, seeds=(1312,))
    dura = measure(
        scale_pack(tuning={"bond_weight": 0.0, "company_scale": 8.0}), days=4, seeds=(1312,)
    )
    assert floja.lonely[SED] > dura.lonely[SED]


# --- el instrumento -----------------------------------------------------------


def test_the_ledger_is_off_by_default() -> None:
    """Una corrida de juego no paga por instrumentarse."""
    sim = Simulation(scale_pack(), seed=1)
    assert all(a.ledger is None for a in sim.state.agents_in_order())
    sim.run(50)  # y no revienta


def test_the_ledger_separates_what_arrives_for_free() -> None:
    """Es toda la gracia: el neto esconde justo lo que se quiere ver."""
    sim = Simulation(scale_pack(), seed=1)
    for a in sim.state.agents_in_order():
        a.ledger = Ledger()
    sim.run(200)

    libro = sim.state.agents_in_order()[0].ledger
    assert libro is not None
    assert libro.demanda[SED] > 0.0
    assert libro.pasivo[SED] > 0.0, "hay siete personas delante"
    assert libro.activo[SED] > 0.0, "y ademas bebe"


def test_health_reports_a_dead_axis() -> None:
    """Lo que habría cantado el problema del vínculo el primer día.

    `crisis_time` es un agregado y un eje que nunca aprieta se esconde detrás de
    los que sí: el panel se ve sano mientras el mecanismo está muerto.
    """
    informe = measure(scale_pack(), days=4, seeds=(1312,))
    assert SED in informe.supply
    assert any("oferta/demanda" in linea for linea in informe.lines())


def test_progression_axes_are_left_out() -> None:
    """No tienen demanda: dividir daría infinito, y la pregunta "¿decide algo?"
    no aplica a un eje que nadie puede perder."""
    pack = scale_pack(
        needs=[
            {"id": "sed", "label": "sed", "decay_per_tick": 0.01, "initial": 0.6},
            {"id": "saber", "label": "saber", "decay_per_tick": 0.0, "initial": 0.0,
             "progression": True},
        ],
        actions=[
            {"id": "beber", "label": "beber", "duration_ticks": 2,
             "satisfies": {"sed": 0.9}, "effects": {"sed": 0.4, "saber": 0.01}},
        ],
    )
    informe = measure(pack, days=3, seeds=(1312,))
    assert SED in informe.supply
    assert NeedId("saber") not in informe.supply


# --- el footgun que el validador ahora tapa -----------------------------------


def test_relief_above_decay_is_refused() -> None:
    """Por encima del decaimiento, la necesidad SUBE sola por estar en una
    multitud: deja de ser satisfacible por acciones y el bucle social entero
    muere sin que nada falle."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="sube sola"):
        scale_pack(
            needs=[
                {"id": "sed", "label": "sed", "decay_per_tick": 0.01, "initial": 0.6,
                 "company_relief": 0.02},
            ]
        )


def test_relief_equal_to_decay_is_allowed() -> None:
    """Igual es el máximo útil: la compañía frena la necesidad pero nunca la
    llena, y para llenarla hay que actuar."""
    pack = scale_pack()
    assert pack.need_by_id[SED].company_relief == pack.need_by_id[SED].decay_per_tick
