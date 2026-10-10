"""Pruebas del renderizado legible del log y el estado (unidad 10, §B.4)."""

from __future__ import annotations

from pathlib import Path

from agora.engine.events import Event, EventKind
from agora.engine.ontology import AgentId, AgentSpec
from agora.engine.pack import load_pack
from agora.engine.render import _label_of_agent, render_event

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")


def test_todo_suceso_tiene_linea() -> None:
    # 29. un evento de cada EventKind se renderiza sin excepción (cubre M18).
    pack = load_pack(CONFLUENCIA_PACK)
    actor_id = next(iter(pack.agent_by_id.keys()))
    place_id = next(iter(pack.place_by_id.keys()))
    subject_id = list(pack.agent_by_id.keys())[1]

    for kind in EventKind:
        event = Event(
            seq=1,
            tick=10,
            kind=kind,
            actor=actor_id,
            subject=subject_id,
            place=place_id,
            data={
                "action": "comer",
                "need": "energia",
                "value": 0.5,
                "goal": "sobrevivir",
                "relation": "amigo",
                "situation": "hambre_extrema",
                "ticks": 5,
                "porque": "inanicion",
                "clave_extra": "valor_extra",
            },
        )
        line = render_event(pack, event)
        assert isinstance(line, str)
        assert len(line) > 0


def test_la_etiqueta_sale_del_censo() -> None:
    # 30. un evento de alguien que no está en el pack pero sí en el censo lleva su label;
    # sin censo, su id (cubre M19).
    pack = load_pack(CONFLUENCIA_PACK)
    forastero_id = AgentId("forastero_desconocido")
    place_id = next(iter(pack.place_by_id.keys()))

    assert forastero_id not in pack.agent_by_id

    censo = {
        forastero_id: AgentSpec(
            id=forastero_id,
            label="El Gran Forastero",
            home=place_id,
            start_at=place_id,
        )
    }

    event = Event(
        seq=1,
        tick=5,
        kind=EventKind.AGENT_ARRIVED,
        actor=forastero_id,
        place=place_id,
    )

    # Con censo: usa el label del censo
    rendered_con = render_event(pack, event, censo=censo)
    assert "El Gran Forastero" in rendered_con

    # Sin censo: usa el id en forma de cadena
    rendered_sin = render_event(pack, event, censo=None)
    assert "forastero_desconocido" in rendered_sin
    assert "El Gran Forastero" not in rendered_sin

    # Comprobación unitaria directa de la función auxiliar
    assert _label_of_agent(pack, forastero_id, censo) == "El Gran Forastero"
    assert _label_of_agent(pack, forastero_id, None) == "forastero_desconocido"
