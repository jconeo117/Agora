"""Los estados de animo: una condicion que cambia COMO decides.

**La forma ya estaba hecha y nadie se habia dado cuenta.** Una `Condicion` tiene
duracion, gravedad y origen, llega por `inflicts` desde cualquier evento o
accion, y se va por plazo o porque alguien la cure. Es exactamente la forma de
un animo — solo le faltaba hacer lo que un animo hace.

Hasta aqui una condicion solo sabia DRENAR. Podia quitarte salud dia tras dia,
pero no cambiaba en nada como decidias, asi que enfadado, abatido y agotado eran
indistinguibles: el mismo valor bajo en un eje.

De aqui sale la distincion que faltaba: **el rasgo es quien eres, el animo es
como estas hoy.** Uno es fijo, el otro va y viene.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import AgentId, NeedId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
PAN = NeedId("pan")
ABATIDO = SituationId("abatido")


def animo_pack(**overrides: Any) -> ContentPack:
    """Un mundo con un animo que encoge el mundo: rinde menos y se arriesga
    menos."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "pan", "label": "pan", "decay_per_tick": 0.01, "initial": 0.5},
        ],
        "situations": [
            {"id": "abatido", "label": "abatido", "personal": True,
             "gain_multipliers": {"pan": 0.5},
             "temperament_multipliers": {"travel_discount": 0.5,
                                         "critical_need_threshold": 1.5}},
        ],
        "actions": [
            {"id": "comer", "label": "comer", "duration_ticks": 2,
             "satisfies": {"pan": 1.0}, "effects": {"pan": 0.4}},
        ],
        "places": [{"id": "p1", "label": "p1", "neighbors": {}}],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {"critical_need_threshold": 0.2, "travel_discount": 0.9},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- como decide -------------------------------------------------------------


def test_a_mood_changes_how_you_decide() -> None:
    """**Lo que este paso compra.** El mismo agente, el mismo mundo, y decide
    distinto por lo que lleva encima."""
    sim = Simulation(animo_pack(), seed=1)
    antes = sim.state.agents[AG1].temperament
    sim.afligir(AG1, ABATIDO)
    sim.tick()
    despues = sim.state.agents[AG1].temperament

    assert despues.travel_discount < antes.travel_discount, "sale menos"
    assert despues.critical_need_threshold > antes.critical_need_threshold, (
        "se alarma antes"
    )


def test_the_severity_is_the_exponent() -> None:
    """Como la intensidad de un rasgo (D-030), y NO como producto: con 0 el
    animo no hace nada y con el doble de gravedad compone al cuadrado en vez de
    salirse de rango."""
    def con(gravedad: float) -> Simulation:
        sim = Simulation(animo_pack(), seed=1)
        sim.afligir(AG1, ABATIDO)
        # La gravedad la sortea quien inflige, asi que aqui se pone a mano: lo
        # que se prueba es la COMPOSICION, no el sorteo.
        sim.state.agents[AG1].condiciones[0].gravedad = gravedad
        sim.tick()
        return sim

    leve, grave = con(1.0), con(2.0)

    t_leve = leve.state.agents[AG1].temperament.travel_discount
    t_grave = grave.state.agents[AG1].temperament.travel_discount
    assert t_grave == pytest.approx(0.9 * 0.5**2)
    assert t_leve == pytest.approx(0.9 * 0.5)


def test_two_marks_of_the_same_mood_add_up() -> None:
    """Estar herido dos veces afecta mas a como decides que estarlo una. Es la
    misma regla que ya siguen sus `effects`."""
    sim = Simulation(animo_pack(), seed=1)
    sim.afligir(AG1, ABATIDO, marca="una")
    sim.afligir(AG1, ABATIDO, marca="otra")
    sim.tick()
    assert sim.state.agents[AG1].animos() == {ABATIDO: pytest.approx(2.0)}


def test_when_it_passes_you_go_back_to_being_you() -> None:
    """Un animo VA Y VIENE, y ahi esta la diferencia con un rasgo. Si no se
    deshiciera seria una personalidad con otro nombre."""
    pack = animo_pack(situations=[
        {"id": "abatido", "label": "abatido", "personal": True,
         "gain_multipliers": {"pan": 0.5},
         "temperament_multipliers": {"travel_discount": 0.5}},
    ])
    sim = Simulation(pack, seed=1)
    normal = sim.state.agents[AG1].temperament.travel_discount
    sim.afligir(AG1, ABATIDO, ticks=3)
    sim.tick()
    assert sim.state.agents[AG1].temperament.travel_discount < normal
    sim.run(6)
    assert sim.state.agents[AG1].temperament.travel_discount == pytest.approx(normal)


# --- cuanto le cunde ---------------------------------------------------------


def test_a_mood_also_shrinks_what_things_yield() -> None:
    """La otra mitad: una fiebre no solo drena, hace que todo cunda menos
    mientras dura."""
    sim = Simulation(animo_pack(), seed=1)
    antes = sim.state.agents[AG1].gains[PAN]
    sim.afligir(AG1, ABATIDO)
    sim.tick()
    assert sim.state.agents[AG1].gains[PAN] == pytest.approx(antes * 0.5)


def test_the_aptitude_of_the_traits_survives_underneath() -> None:
    """El animo MULTIPLICA la aptitud, no la sustituye. Alguien con mano para
    algo y abatido sigue teniendo mano — menos."""
    pack = animo_pack(
        traits=[{"id": "manitas", "label": "manitas",
                 "gain_multipliers": {"pan": 3.0}}],
        agents=[{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1",
                 "traits": {"manitas": 1.0}}],
    )
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[AG1].gains[PAN] == pytest.approx(3.0)
    sim.afligir(AG1, ABATIDO)
    sim.tick()
    assert sim.state.agents[AG1].gains[PAN] == pytest.approx(1.5)


def test_curing_it_gives_the_aptitude_back() -> None:
    sim = Simulation(animo_pack(), seed=1)
    antes = sim.state.agents[AG1].gains[PAN]
    sim.afligir(AG1, ABATIDO)
    sim.tick()
    sim.aliviar(AG1, ABATIDO)
    sim.tick()
    assert sim.state.agents[AG1].gains[PAN] == pytest.approx(antes)


# --- y no cambia nada para quien no lo pide ----------------------------------


def test_a_condition_without_the_channels_behaves_as_before() -> None:
    """Estrenar el canal no puede mover un mundo que no lo declara."""
    pack = animo_pack(situations=[
        {"id": "abatido", "label": "abatido", "personal": True,
         "effects": {"pan": -0.01}},
    ])
    sim = Simulation(pack, seed=1)
    antes = sim.state.agents[AG1].temperament
    ganancia = dict(sim.state.agents[AG1].gains)
    sim.afligir(AG1, ABATIDO)
    sim.tick()
    assert sim.state.agents[AG1].temperament == antes
    assert sim.state.agents[AG1].gains == ganancia
