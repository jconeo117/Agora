"""Pruebas del factor de sorpresa en combate y en el mundo (unidad 13)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from agora.engine.ontology import ActionId, AgentId
from agora.engine.pack import ContentPack
from agora.engine.ports import EncounterOutcome
from agora.engine.rng import RngSource
from agora.engine.state import PerformingAction
from agora.engine.world import Simulation
from agora.rules.encounter import Action, ActionKind, Encounter, Fighter
from agora.rules.scene import load_scenario
from agora.rules.system import load_ruleset
from tests.test_persecucion import DummyPolicy

BASE_RULES = Path("rules/base/rules.yaml")
ESCENARIOS_DIR = Path("rules/base/escenarios")


class TurnRecorder(DummyPolicy):
    """Registra los turnos de combate ronda a ronda."""

    def __init__(self) -> None:
        super().__init__(Action(ActionKind.RECOVER))
        self.turnos: list[tuple[int, str]] = []

    def choose(self, encounter: Encounter, me: Fighter) -> Action:
        self.turnos.append((encounter.round, me.id))
        assert self.action is not None
        return self.action


def test_el_desprevenido_actua_al_final_de_la_primera_ronda() -> None:
    """En la primera ronda, el sorprendido actúa el último aunque su iniciativa
    sea mayor; en la segunda, por su iniciativa.
    """
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIOS_DIR / "aria_lobo.yaml", ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    primero = enc.order[0]
    segundo = enc.order[1]

    # Ponemos al primero de la iniciativa como sorprendido
    enc_sorpresa = Encounter(
        esc, ruleset, RngSource(1312), "test_sorpresa", surprised=frozenset([primero])
    )
    recorder = TurnRecorder()
    enc_sorpresa.run(recorder)

    turnos_r1 = [fid for r, fid in recorder.turnos if r == 1]
    turnos_r2 = [fid for r, fid in recorder.turnos if r == 2]

    # En la ronda 1 actúa al final
    assert turnos_r1 == [segundo, primero]
    # En la ronda 2 actúa primero por su iniciativa normal
    assert turnos_r2 == [primero, segundo]


def sorpresa_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "test_sorpresa",
        "label": "test_sorpresa",
        "needs": [
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0, "initial": 1.0},
            {"id": "combate", "label": "combate", "decay_per_tick": 0.0, "initial": 0.5},
            {"id": "descanso", "label": "descanso", "decay_per_tick": 0.0, "initial": 0.5},
        ],
        "actions": [
            {
                "id": "dormir",
                "label": "dormir",
                "duration_ticks": 4,
                "vulnerable": True,
                "satisfies": {"descanso": 1.0},
            },
            {
                "id": "vigilar",
                "label": "vigilar",
                "duration_ticks": 4,
                "vulnerable": False,
                "satisfies": {"descanso": 0.5},
            },
            {
                "id": "atacar",
                "label": "atacar",
                "duration_ticks": 1,
                "requires_company": 1,
                "satisfies": {"combate": 1.0},
                "target": {"gives": {"salud": -0.2}, "combate": True, "por_desconocido": True},
            },
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [{"id": "campamento", "label": "campamento", "affordances": ["sitio"]}],
        "agents": [
            {"id": "jugador", "label": "Jugador", "home": "campamento", "start_at": "campamento"},
            {"id": "enemigo", "label": "Enemigo", "home": "campamento", "start_at": "campamento"},
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


class MockResolver:
    def __init__(self) -> None:
        self.ultimo_surprised: frozenset[AgentId] | None = None

    def resolve(
        self,
        world: Any,
        attacker: AgentId,
        defender: AgentId,
        surprised: frozenset[AgentId],
    ) -> EncounterOutcome | None:
        self.ultimo_surprised = surprised
        return None


def test_dormir_deja_desprevenido() -> None:
    """En el mundo, un jugador atacado mientras hace una acción vulnerable
    llega al resolutor como sorprendido; haciendo otra cosa, no.
    """
    pack = sorpresa_pack()
    sim = Simulation(pack, seed=1312)
    jugador_id = AgentId("jugador")
    enemigo_id = AgentId("enemigo")
    sim.set_player(jugador_id)

    resolver = MockResolver()
    sim.encounter_resolver = resolver

    jugador = sim.state.agents[jugador_id]
    enemigo = sim.state.agents[enemigo_id]
    accion_atacar = pack.action_by_id[ActionId("atacar")]
    assert accion_atacar.target is not None

    # Caso 1: jugador durmiendo (vulnerable = True)
    jugador.busy = PerformingAction(action=ActionId("dormir"), total_ticks=4, ticks_remaining=3)
    sim._entregar(enemigo, accion_atacar, jugador_id, None)  # type: ignore[arg-type]
    assert resolver.ultimo_surprised == frozenset([jugador_id])

    # Caso 2: jugador vigilando (vulnerable = False)
    jugador.busy = PerformingAction(action=ActionId("vigilar"), total_ticks=4, ticks_remaining=3)
    sim._entregar(enemigo, accion_atacar, jugador_id, None)  # type: ignore[arg-type]
    assert resolver.ultimo_surprised == frozenset()
