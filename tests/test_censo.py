"""El censo: quién existe lo dice el mundo, no el pack.

**El bloqueo que este paso levanta**, y conviene escribirlo porque el plan lo
tenía mal diagnosticado. `WorldState.agents` **ya era un dict mutable**: se podía
añadir y quitar desde el primer día. Lo que impedía que naciera nadie era otra
cosa —cada `AgentState` guarda un `spec_id` que apunta a una ficha congelada del
YAML, y quien no estuviera escrito allí reventaba con `KeyError` en cuanto
alguien pidiera su ficha.

Medido antes de tocar nada, lo que se le pregunta a esa ficha **mientras el mundo
corre** resultaron ser tres cosas, no las diecisiete que decía el inventario:

    la etiqueta (render) · las metas (world) · si existes (health, persistencia)

Todo lo demás —rasgos, gustos, necesidades, relaciones, vínculos iniciales— se
copia al `AgentState` al nacer y no se vuelve a mirar. La deliberación entera
vive ya sin el pack: `decide.py` no consulta el reparto ni una vez.

Así que el censo no es una capa nueva sobre un problema grande. Es mover tres
preguntas de sitio.

**Este paso no cambia ninguna conducta, y esa es su prueba**: los tests que ya
había pasan sin editar uno solo. Lo que sí cambia es que ahora existe el sitio
donde escribir una muerte o un nacimiento.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import ActionId, AgentId, AgentSpec, NeedId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.render import render_state
from agora.engine.state import AgentState, WorldState
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
FORASTERO = AgentId("forastero")
P1 = PlaceId("p1")
COMER = ActionId("comer")
HAMBRE = NeedId("hambre")


def censo_pack(**overrides: Any) -> ContentPack:
    """Un mundo mínimo donde comer es lo único que hay que hacer."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "hambre", "label": "hambre", "decay_per_tick": 0.02,
             "initial": 0.5},
        ],
        "actions": [
            {"id": "comer", "label": "comer", "duration_ticks": 1,
             "requires_affordance": "cocina", "satisfies": {"hambre": 1.0},
             "effects": {"hambre": 0.2}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["cocina"],
             "neighbors": {}}
        ],
        "agents": [{"id": "ag1", "label": "Uno", "home": "p1",
                    "start_at": "p1"}],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def forastero() -> AgentSpec:
    """Alguien que el pack no escribió jamás."""
    return AgentSpec(id=FORASTERO, label="Forastero", home=P1, start_at=P1)


def con_forastero(pack: ContentPack, seed: int = 3) -> Simulation:
    """Un mundo con un habitante de más, metido en marcha.

    Las dos líneas del final son, literalmente, lo que hoy significa nacer.
    """
    sim = Simulation(pack, seed=seed)
    spec = forastero()
    sim.state.censo[spec.id] = spec
    sim.state.agents[spec.id] = AgentState.from_spec(pack, spec)
    return sim


# --- de dónde sale el censo --------------------------------------------------


def test_the_census_starts_as_the_pack() -> None:
    """Un mundo recién hecho: el censo dice exactamente lo que decía el pack. Es
    la razón de que este paso no pueda cambiar ninguna conducta."""
    pack = censo_pack()
    world = WorldState.new(pack, seed=1)
    assert world.censo == pack.agent_by_id


def test_the_census_is_a_copy_and_not_the_packs_own_dict() -> None:
    """Si fuera un alias, una muerte en una partida borraría al agente de
    cualquier otra cargada del mismo fichero. Mismo motivo por el que `from_spec`
    copia los dicts en vez de compartirlos."""
    pack = censo_pack()
    uno = WorldState.new(pack, seed=1)
    otro = WorldState.new(pack, seed=2)

    del uno.censo[AG1]

    assert AG1 in pack.agent_by_id, "el pack no es de nadie en particular"
    assert AG1 in otro.censo, "dos partidas del mismo pack no se tocan"


def test_everyone_present_has_a_ficha() -> None:
    """El invariante del campo. Estar en el reparto sin estar en el censo sería
    justo el `KeyError` que este paso viene a hacer imposible."""
    pack = censo_pack()
    world = WorldState.new(pack, seed=1)
    assert set(world.agents) <= set(world.censo)


def test_the_census_answers_who_exists() -> None:
    world = WorldState.new(censo_pack(), seed=1)
    assert world.existe(AG1)
    assert not world.existe(FORASTERO)


def test_spec_of_reads_the_census_and_not_the_pack() -> None:
    """La prueba directa de quién manda: se cambia la ficha en el censo y el
    mundo contesta con la nueva, con el pack intacto."""
    pack = censo_pack()
    world = WorldState.new(pack, seed=1)
    world.censo[AG1] = AgentSpec(id=AG1, label="Otro nombre", home=P1,
                                 start_at=P1)

    assert world.spec_of(world.agents[AG1]).label == "Otro nombre"
    assert pack.agent_by_id[AG1].label == "Uno"


# --- alguien a quien el pack nunca escribió ----------------------------------


def test_someone_the_pack_never_wrote_can_live() -> None:
    """**Lo que este paso compra.** Antes esto reventaba en cuanto el tick loop
    pedía su ficha para revisarle las metas.

    No es todavía nacer —nadie lo crea, lo mete el test a mano— pero es la
    condición previa: hasta ahora no había forma de que existiera un agente sin
    entrada en el YAML, así que la muerte y la descendencia no tenían dónde
    apoyarse.
    """
    pack = censo_pack()
    sim = con_forastero(pack)
    sim.run(200)

    hecho = sim.log.recuento.por_agente_accion[FORASTERO]
    assert hecho[COMER] > 0, "el forastero vivió su vida como cualquiera"


def test_the_stranger_is_a_citizen_and_not_a_passenger() -> None:
    """No basta con que no reviente: tiene que **deliberar**, no dejarse llevar.

    Se comprueba por el resultado y no por el recuento. La primera versión de este
    test exigía que forastero y vecino comieran las mismas veces (±2) y falló:
    96 contra 108. La premisa era mía y era falsa —cada sorteo sale de
    `blake2b(semilla, agente, tick)`, así que **dos agentes con la misma ficha
    nunca sortean igual**, y que coincidieran al detalle sería el síntoma de que
    el RNG no está derivado por agente—.

    Lo que sí tiene que cumplirse es que el forastero se gobierne: que coma
    mucho, y que acabe con el hambre atendida como cualquier vecino.
    """
    pack = censo_pack()
    sim = con_forastero(pack)
    sim.run(200)

    rec = sim.log.recuento.por_agente_accion
    assert rec[FORASTERO][COMER] > 50, "no se limitó a existir: se ocupó de sí"
    assert rec[FORASTERO][COMER] == pytest.approx(rec[AG1][COMER], rel=0.30)

    vecino = sim.state.agents[AG1].needs[HAMBRE]
    assert sim.state.agents[FORASTERO].needs[HAMBRE] == pytest.approx(
        vecino, abs=0.35
    ), "acabó tan atendido como el vecino"


def test_the_stranger_does_not_disturb_the_neighbour() -> None:
    """Determinismo: meter a alguien no puede cambiar la vida de los demás por la
    puerta de atrás. Cada sorteo sale de `blake2b(semilla, agente, tick)`, así que
    un habitante de más no corre el turno de nadie."""
    solo = Simulation(censo_pack(), seed=3)
    solo.run(200)
    acompanado = con_forastero(censo_pack(), seed=3)
    acompanado.run(200)

    assert (solo.log.recuento.por_agente_accion[AG1]
            == acompanado.log.recuento.por_agente_accion[AG1])


def test_the_stranger_has_no_pack_goals() -> None:
    """Se queda sin arcos en vez de reventar, y es lo honesto: sus metas tendrían
    que salir de algún sitio, y decidir de dónde es trabajo de descendencia."""
    pack = censo_pack()
    sim = con_forastero(pack)
    assert sim.state.agents[FORASTERO].pursuing(pack) == ()


def test_the_stranger_can_be_rendered() -> None:
    """El render pedía la ficha al pack. Era el segundo sitio que reventaba."""
    sim = con_forastero(censo_pack())
    sim.run(10)
    assert any("Forastero" in linea for linea in render_state(sim.state))
