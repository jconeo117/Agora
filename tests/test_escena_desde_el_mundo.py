"""Pruebas de la costura entre el mundo y la escena de combate (unidad 13)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    ActionSpec,
    AgentId,
    NeedId,
    PlaceId,
    SituationId,
    TargetSpec,
)
from agora.engine.pack import ContentPack
from agora.engine.ports import (
    CombatantOutcome,
    EncounterOutcome,
    Fate,
)
from agora.engine.state import AgentState, PerformingAction
from agora.engine.world import Simulation

SALUD = NeedId("salud")
COMBATE = NeedId("combate")
HERIDA = SituationId("herida")


def mundo_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test_mundo",
        "label": "test_mundo",
        "needs": [
            {
                "id": "salud",
                "label": "salud",
                "decay_per_tick": 0.0,
                "initial": 1.0,
                "max_debt": 2.0,
            },
            {"id": "combate", "label": "combate", "decay_per_tick": 0.0, "initial": 0.5},
        ],
        "situations": [
            {"id": "herida", "label": "herida", "personal": True, "effects": {"salud": -0.05}},
        ],
        "actions": [
            {
                "id": "atacar",
                "label": "atacar",
                "duration_ticks": 1,
                "requires_company": 1,
                "satisfies": {"combate": 1.0},
                "target": {
                    "gives": {"salud": -0.3},
                    "combate": True,
                    "por_desconocido": True,
                    "inflicts": {"situation": "herida", "marca": "cuerpo", "gravedad_min": 0.5},
                },
            },
            {"id": "descansar", "label": "descansar", "duration_ticks": 2},
        ],
        "places": [
            {
                "id": "plaza",
                "label": "plaza",
                "affordances": ["sitio"],
                "neighbors": {"bosque": 1},
            },
            {
                "id": "bosque",
                "label": "bosque",
                "affordances": ["sitio"],
                "neighbors": {"plaza": 1},
            },
        ],
        "agents": [
            {"id": "atacante", "label": "Atacante", "home": "plaza", "start_at": "plaza"},
            {"id": "defensor", "label": "Defensor", "home": "plaza", "start_at": "plaza"},
        ],
        "tuning": {
            "memory_capacity": 20,
            "memory_scale": 1.0,
            "bond_rate": 0.3,
            "bond_scale": 1.0,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


class FixedResolver:
    def __init__(self, outcome: EncounterOutcome | None) -> None:
        self.outcome = outcome
        self.called = False

    def resolve(
        self,
        world: Any,
        attacker: AgentId,
        defender: AgentId,
        surprised: frozenset[AgentId],
    ) -> EncounterOutcome | None:
        self.called = True
        return self.outcome


def test_sin_jugador_no_hay_escena() -> None:
    """Una acción combate: true entre dos NPCs no llama al resolutor
    y aplica gives como siempre.
    """
    pack = mundo_pack()
    sim = Simulation(pack, seed=1)
    resolver = FixedResolver(None)
    sim.encounter_resolver = resolver
    # No hay jugador en el mundo (sim.state.player is None)

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]

    assert not resolver.called
    # Se aplicó gives (-0.3)
    assert defensor.needs[SALUD] == 0.7


def test_sin_resolutor_no_hay_escena() -> None:
    """Con jugador y sin resolutor, igual."""
    pack = mundo_pack()
    sim = Simulation(pack, seed=1)
    sim.set_player(AgentId("defensor"))
    sim.encounter_resolver = None

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]
    assert defensor.needs[SALUD] == 0.7


def test_con_jugador_el_desenlace_sustituye_a_gives() -> None:
    """Un resolutor de juguete que devuelve un desenlace fijo: se aplican
    sus necesidades y su condición, y no el gives, el cures ni el inflicts
    de la acción. La enemistad y el recuerdo con nombre siguen.
    """
    pack = mundo_pack()
    sim = Simulation(pack, seed=1)
    sim.set_player(AgentId("defensor"))

    # Desenlace fijo: el defensor queda con salud 0.5 (en vez de 1.0 - 0.3 = 0.7)
    # y sin condiciones de la acción
    desenlace = EncounterOutcome(
        combatants=(
            CombatantOutcome(
                agent=AgentId("defensor"),
                fate=Fate.STANDING,
                needs=((SALUD, 0.5),),
                inflicts=None,
            ),
        ),
        rounds=2,
    )
    sim.encounter_resolver = FixedResolver(desenlace)

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]

    # La necesidad toma el valor del desenlace (0.5), no 0.7
    assert defensor.needs[SALUD] == 0.5
    # No se aplicó el inflicts de la acción porque desenlace no es None
    assert not defensor.condiciones
    # La memoria y enemistad con nombre continúan
    recuerdos = sim.state.memoria.de(defensor.spec_id)
    assert any(r.about == atacante.spec_id for r in recuerdos)


def test_un_resolutor_que_no_sabe_es_utilidad() -> None:
    """Si devuelve None, gives."""
    pack = mundo_pack()
    sim = Simulation(pack, seed=1)
    sim.set_player(AgentId("defensor"))
    sim.encounter_resolver = FixedResolver(None)

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]
    assert defensor.needs[SALUD] == 0.7


def test_muerto_por_morir() -> None:
    """Fate.DEAD -> World.morir con porque="combate", y el resto de _entregar no revienta."""
    pack = mundo_pack()
    sim = Simulation(pack, seed=1)
    sim.set_player(AgentId("defensor"))

    desenlace = EncounterOutcome(
        combatants=(
            CombatantOutcome(
                agent=AgentId("defensor"),
                fate=Fate.DEAD,
                needs=((SALUD, 0.0),),
            ),
        ),
        rounds=1,
    )
    sim.encounter_resolver = FixedResolver(desenlace)

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    atacante.meet(defensor.spec_id, tick=0)
    atacante.bonds[defensor.spec_id].regard = 0.5
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]

    # El defensor murió y ya no está en el censo de agentes vivos
    assert AgentId("defensor") not in sim.state.agents
    # Se emitió el evento de muerte por combate
    eventos_muerte = [e for e in sim.log if e.kind == EventKind.AGENT_DIED]
    assert len(eventos_muerte) == 1
    assert eventos_muerte[0].data.get("porque") == "combate"


def test_quien_huye_acaba_en_un_vecino() -> None:
    """Fate.FLED -> otro lugar vecino, reproducible con la misma semilla,
    con su evento TRAVEL_ARRIVED y huida; y si estaba haciendo algo, ACTION_ABORTED.
    """
    pack = mundo_pack()
    sim = Simulation(pack, seed=1312)
    sim.set_player(AgentId("defensor"))

    desenlace = EncounterOutcome(
        combatants=(
            CombatantOutcome(
                agent=AgentId("defensor"),
                fate=Fate.FLED,
                needs=(),
            ),
        ),
        rounds=1,
    )
    sim.encounter_resolver = FixedResolver(desenlace)

    atacante = sim.state.agents[AgentId("atacante")]
    defensor = sim.state.agents[AgentId("defensor")]
    defensor.busy = PerformingAction(action=ActionId("descansar"), total_ticks=2, ticks_remaining=1)
    accion = pack.action_by_id[ActionId("atacar")]

    sim._entregar(atacante, accion, defensor.spec_id, None)  # type: ignore[arg-type]

    # El defensor acabó en el vecino (bosque)
    assert defensor.at == PlaceId("bosque")
    assert sim.state.agents[AgentId("defensor")].busy is None

    # Eventos emitidos: ACTION_ABORTED y TRAVEL_ARRIVED con huida=True
    eventos_abort = [e for e in sim.log if e.kind == EventKind.ACTION_ABORTED]
    assert eventos_abort
    eventos_viaje = [
        e for e in sim.log if e.kind == EventKind.TRAVEL_ARRIVED and e.data.get("huida") is True
    ]
    assert eventos_viaje


def test_adopt_pasa_por_restore_y_spend() -> None:
    """Bajar una necesidad por debajo de cero anota deuda como _spend;
    subirla salda deuda como restore.
    """
    agente = AgentState(
        spec_id=AgentId("test"),
        at=PlaceId("plaza"),
        needs={SALUD: 0.5},
    )

    # Bajar a -0.2: delta = -0.7. Gasto 0.7 con max_debt=2.0
    # La necesidad queda en 0.0 y la deuda anota 0.2
    agente.adopt(SALUD, -0.2, max_debt=2.0)
    assert agente.needs[SALUD] == 0.0
    assert agente.debt[SALUD] == pytest.approx(0.2)

    # Subir a 0.5: delta = +0.5. Salda deuda 0.2 primero, resto 0.3 a la necesidad
    agente.adopt(SALUD, 0.5, max_debt=2.0)
    assert agente.debt.get(SALUD, 0.0) == pytest.approx(0.0)
    assert agente.needs[SALUD] == pytest.approx(0.3)


def test_combate_y_vulnerable_por_defecto_no_hacen_nada() -> None:
    """TargetSpec.combate y ActionSpec.vulnerable son False por defecto."""
    spec_target = TargetSpec()
    assert spec_target.combate is False

    spec_action = ActionSpec(
        id=ActionId("a"),
        label="a",
        duration_ticks=1,
    )
    assert spec_action.vulnerable is False
