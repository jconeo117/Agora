"""Infligir: lo que te deja algo encima, y por qué la muerte lo necesitaba.

**Este campo no salió de una idea, salió de medir tres mundos.** La muerte por
agotamiento no puede ocurrir en un mundo calibrado para ser habitable:

    ciudad        nadie pasa mas de 43 ticks (once horas) sin comer,
                  y solo 56 de 127 llegan a tocar fondo alguna vez
    confluencia   el mana no llega a cero NI UNA VEZ en catorce dias;
                  el eje mas castigado del mundo aguanta medio dia

Y eso está bien: una ciudad donde se muere de hambre a diario está rota, no es
peligrosa. Pero significa que `lethal_after` por sí solo es decoración — el
contrato de salud premia justamente que nadie se bloquee, así que ningún eje se
queda vacío el tiempo suficiente para matar.

Para que la muerte exista hace falta algo que drene **desde fuera de las
decisiones del agente**. Un `costs` no sirve: se paga una vez y se acabó, y quien
lo nota deja de hacer la acción. Una condición sigue sangrando hagas lo que
hagas, y por eso hay que ir a que te la quiten.

Tres sitios infligen y **una sola forma los gobierna** (`AflictionSpec`). Tres
formas distintas para la misma idea habrían divergido —una con plazo, otra sin,
una con marca, otra no— y entonces *infligir* dejaría de significar lo mismo
según dónde se escriba.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
SANGRE = NeedId("sangre")
HERIDA = SituationId("herida")
VENTISCA = SituationId("ventisca")


def base_pack(**overrides: Any) -> ContentPack:
    """Bajar sangra. Y no se puede parar: no hay quien cure."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "sangre", "label": "sangre", "decay_per_tick": 0.0,
             "initial": 1.0, "lethal_after": 6},
            {"id": "botin", "label": "botin", "decay_per_tick": 0.02,
             "initial": 0.3},
        ],
        "situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.05}},
        ],
        "actions": [
            {"id": "bajar", "label": "bajar", "duration_ticks": 2,
             "requires_affordance": "sima", "satisfies": {"botin": 1.0},
             "effects": {"botin": 0.4},
             "inflicts": {"situation": "herida", "marca": "torso"}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sima"], "neighbors": {}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 20, "memory_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- lo que el pack puede declarar -------------------------------------------


def test_you_cannot_inflict_something_nobody_can_carry() -> None:
    with pytest.raises(ValueError, match=r"\.inflicts.*no es una situación personal"):
        base_pack(**{
            "situations": [
                {"id": "herida", "label": "herida", "personal": True,
                 "effects": {"sangre": -0.05}},
                {"id": "invierno", "label": "invierno",
                 "effects": {"sangre": -0.001}}],
            "actions": [
                {"id": "bajar", "label": "bajar", "duration_ticks": 2,
                 "requires_affordance": "sima", "satisfies": {"botin": 1.0},
                 "effects": {"botin": 0.4},
                 "inflicts": {"situation": "invierno"}},
                {"id": "nada", "label": "nada", "duration_ticks": 1}]})


def test_a_situation_cannot_inflict_itself() -> None:
    with pytest.raises(ValueError, match="se pega a sí misma"):
        base_pack(**{"situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.05},
             "inflicts": {"situation": "herida"}}]})


# --- lo que hacer algo te hace a TI ------------------------------------------


def test_going_down_wounds_you() -> None:
    sim = Simulation(base_pack(), seed=1)
    sim.run(4)
    assert sim.state.agents[AG1].lleva(HERIDA)


def test_it_lands_when_you_finish_and_not_when_you_start() -> None:
    """Media faena no cuenta, como `cures`. Lo inabandonable ya se declara con
    `interruptible`; esto no tiene que duplicarlo."""
    sim = Simulation(base_pack(), seed=1)
    sim.run(2)
    assert not sim.state.agents[AG1].condiciones, "aún estaba bajando"
    sim.run(1)
    assert sim.state.agents[AG1].lleva(HERIDA)


def test_going_down_twice_hurts_twice() -> None:
    """Misma marca: agrava en vez de duplicar. Dos tajos en el mismo torso no
    duran más, duelen más."""
    sim = Simulation(base_pack(), seed=1)
    sim.run(3)
    primera = sim.state.agents[AG1].condiciones[0].gravedad
    sim.run(3)
    condiciones = sim.state.agents[AG1].condiciones
    assert len(condiciones) == 1
    assert condiciones[0].gravedad > primera


def test_a_cost_is_paid_once_and_a_wound_keeps_bleeding() -> None:
    """**La distinción entera de este paso.** Se compara la misma acción con el
    daño puesto como `costs` y como `inflicts`, y luego se deja de bajar.

    Con `costs`, dejar de bajar te salva. Con `inflicts`, no: sigue sangrando
    hagas lo que hagas, y por eso hace falta ir a que te lo quiten.

    Se prueba sobre el mecanismo y no sobre la deliberación: la primera versión
    de este test ponía `botin` a 1.0 para que el agente dejara de bajar, y el
    `botin` decae, así que volvía a bajar a los pocos ticks y la comparación
    medía otra cosa.
    """
    # Un mundo sin sima: nadie puede volver a hacerse daño desde aquí.
    quieto = base_pack(**{
        "actions": [{"id": "nada", "label": "nada", "duration_ticks": 1}],
        "places": [{"id": "p1", "label": "p1", "affordances": [],
                    "neighbors": {}}],
    })

    precio = Simulation(quieto, seed=1)
    precio.state.agents[AG1].endure({SANGRE: -0.30}, precio.pack.need_by_id)
    tras_el_golpe = precio.state.agents[AG1].needs[SANGRE]
    precio.run(15)

    herida = Simulation(quieto, seed=1)
    herida.afligir(AG1, HERIDA, marca="torso")
    herida.run(15)

    assert precio.state.agents[AG1].needs[SANGRE] == pytest.approx(tras_el_golpe), (
        "un precio se paga una vez y ahí acaba"
    )
    assert herida.state.agents[AG1].needs[SANGRE] < tras_el_golpe, (
        "una herida sigue sangrando aunque no vuelvas a bajar"
    )


def test_and_this_is_how_death_finally_happens() -> None:
    """**Lo que este paso compra, de una pieza.** Bajas, te hieres, drena, y no
    hay quien lo pare: te mueres. Sin `inflicts` esto era imposible en un mundo
    que funciona — medido en tres mundos antes de escribir el campo."""
    sim = Simulation(base_pack(), seed=1)
    sim.run(120)
    assert AG1 not in sim.state.agents


# --- lo que el mundo le hace a quien alcanza ---------------------------------


def ventisca_pack(chance: float) -> ContentPack:
    """El frío apenas sangra: aquí se mide *cuándo prende*, no cuánto mata.

    Con el drenaje de una herida de verdad, trescientos ticks a la intemperie
    acumulan tanto frío que el agente se muere antes de terminar la medición —
    que es el mecanismo funcionando, pero mata el test.
    """
    return base_pack(**{
        "situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.0004}},
            {"id": "ventisca", "label": "ventisca",
             "inflicts": {"situation": "herida", "marca": "frio",
                          "chance": chance}},
        ],
        "actions": [{"id": "nada", "label": "nada", "duration_ticks": 1}],
        "places": [{"id": "p1", "label": "p1", "affordances": [],
                    "neighbors": {}}],
    })


def test_the_weather_leaves_something_on_you() -> None:
    sim = Simulation(ventisca_pack(chance=1.0), seed=1)
    sim.begin_situation(VENTISCA, ticks=10)
    sim.run(2)
    assert sim.state.agents[AG1].lleva(HERIDA)


def test_what_it_leaves_outlives_the_storm() -> None:
    """La diferencia entre un mal rato y una consecuencia. Un `effects` negativo
    se recupera cuando la situación acaba; esto te sigue a casa."""
    sim = Simulation(ventisca_pack(chance=1.0), seed=1)
    sim.begin_situation(VENTISCA, ticks=3)
    sim.run(6)
    assert VENTISCA not in sim.state.situations, "la ventisca ya pasó"
    assert sim.state.agents[AG1].lleva(HERIDA), "y el frío sigue encima"


def test_exposure_is_what_makes_it_likely() -> None:
    """**Por qué `chance` importa aquí y no en una acción.** Los efectos de una
    situación se aplican cada tick, así que a 1.0 una ventisca heriría noventa y
    seis veces al día. El número bajo no es azar decorativo: es cuánto aguantas a
    la intemperie, y sale gratis que el riesgo crezca con la exposición."""
    sim = Simulation(ventisca_pack(chance=0.05), seed=3)
    sim.begin_situation(VENTISCA, ticks=4)
    sim.run(4)
    corta = sim.state.agents[AG1].condiciones and sim.state.agents[AG1].condiciones[0].gravedad

    largo = Simulation(ventisca_pack(chance=0.05), seed=3)
    largo.begin_situation(VENTISCA, ticks=300)
    largo.run(300)
    assert largo.state.agents[AG1].lleva(HERIDA), "trescientos ticks a la intemperie"
    assert largo.state.agents[AG1].condiciones[0].gravedad > (corta or 0)


def test_the_draw_is_by_key_and_not_by_order() -> None:
    """Dos procesos con la misma semilla hieren exactamente a la misma gente."""
    def correr() -> list[tuple[str, str, float]]:
        sim = Simulation(ventisca_pack(chance=0.3), seed=9)
        sim.begin_situation(VENTISCA, ticks=200)
        sim.run(200)
        return [
            (str(a.spec_id), c.marca, c.gravedad)
            for a in sim.state.agents_in_order()
            for c in a.condiciones
        ]

    assert correr() == correr()


# --- y no cambia nada para quien no lo pide ----------------------------------


def test_a_pack_without_inflicts_pays_nothing() -> None:
    pack = base_pack(**{"actions": [
        {"id": "bajar", "label": "bajar", "duration_ticks": 2,
         "requires_affordance": "sima", "satisfies": {"botin": 1.0},
         "effects": {"botin": 0.4}},
        {"id": "nada", "label": "nada", "duration_ticks": 1}]})
    assert all(a.inflicts is None for a in pack.actions)
    sim = Simulation(pack, seed=1)
    sim.run(100)
    assert not sim.state.agents[AG1].condiciones
    assert len(sim.state.agents) == 2
