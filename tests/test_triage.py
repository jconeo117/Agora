"""Interrupción por triaje, y la deuda que corrige.

Historia, porque explica por qué el motor no fue así desde el principio:

1. Primero se comprobaba necesidad a necesidad. Con dos urgencias a la vez
   ninguna acción cubre ambas, así que el agente abandonaba lo que hiciera en
   cada tick, indefinidamente.
2. El parche fue exigir que no atendiera NINGUNA. Mató el bucle, pero invirtió
   el sentido del umbral: con el umbral alto casi todo es emergencia, hagas lo
   que hagas atiendes alguna, y quedas excusado. Medido: correlación -0.76
   entre urgencias simultáneas y abandonos. La perilla `aguante` mentía.
3. El coste de cambio permitió volver al triaje. El umbral se estrecha con lo
   invertido, así que abandonar algo avanzado exige una catástrofe: eso ataja
   el traqueteo por donde había que atajarlo, sin mentir sobre el umbral.

Este módulo fija que no volvamos a ninguno de los dos estados anteriores.
"""

from __future__ import annotations

import copy
from typing import Any

from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG = AgentId("ag")
HAMBRE = NeedId("hambre_t")
SUENO = NeedId("sueno_t")


def two_needs_pack(**overrides: Any) -> ContentPack:
    """Dos necesidades que caen deprisa y una acción para cada una.

    Ninguna acción cubre ambas: es el escenario exacto que producía el bucle.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        # Decaimiento agresivo: con algo más suave el agente llega a todo y no
        # hay interrupciones que medir.
        "needs": [
            {"id": "hambre_t", "label": "h", "decay_per_tick": 0.04, "initial": 0.5},
            {"id": "sueno_t", "label": "s", "decay_per_tick": 0.04, "initial": 0.5},
        ],
        "actions": [
            {
                "id": "comer_t",
                "label": "comer_t",
                "duration_ticks": 6,
                "satisfies": {"hambre_t": 1.0},
                "effects": {"hambre_t": 0.7},
            },
            {
                "id": "dormir_t",
                "label": "dormir_t",
                "duration_ticks": 12,
                "satisfies": {"sueno_t": 1.0},
                "effects": {"sueno_t": 0.9},
            },
            {"id": "nada_t", "label": "nada_t", "duration_ticks": 2},
        ],
        "places": [
            {"id": "p1", "label": "p1", "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag", "label": "ag", "home": "p1", "start_at": "p1"}],
        "tuning": {"critical_need_threshold": 0.35, "switch_cost": 0.8},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


SEEDS = (1, 7, 99, 2024, 555)
"""Varias semillas: con una sola, la diferencia entre dos y tres abandonos
parece señal y es ruido. Se aprendió midiendo."""


def ratio(threshold: float = 0.35, switch_cost: float = 0.8) -> float:
    """Abandonos frente a finalizaciones, promediando semillas."""
    pack = two_needs_pack(
        tuning={"critical_need_threshold": threshold, "switch_cost": switch_cost}
    )
    hechas = rotas = 0
    for seed in SEEDS:
        sim = Simulation(pack, seed=seed)
        sim.run(600)
        hechas += len(sim.log.of_kind(EventKind.ACTION_COMPLETED))
        rotas += len(sim.log.of_kind(EventKind.ACTION_ABORTED))
    return rotas / max(hechas, 1)


def test_two_permanent_emergencies_do_not_deadlock_the_agent() -> None:
    """El escenario que producía el bucle: dos urgencias, ninguna acción cubre
    ambas. Con triaje y coste de cambio, el agente sigue completando cosas."""
    sim = Simulation(two_needs_pack(), seed=1)
    sim.run(600)
    assert len(sim.log.of_kind(EventKind.ACTION_COMPLETED)) > 20
    assert EventKind.IDLE_STALLED not in {e.kind for e in sim.log}


def test_the_abort_ratio_stays_bounded() -> None:
    """La red contra el traqueteo. Un agente atrapado en abandonar/reiniciar
    genera muchos más abandonos que finalizaciones."""
    assert ratio() < 0.5


def test_switch_cost_is_what_holds_the_triage_together() -> None:
    """Demuestra CUÁL es la pieza que sostiene el triaje.

    Sin coste de cambio, el mismo escenario deja lo ya invertido sin protección
    y el traqueteo aumenta. Es la razón de que esta regla no se pudiera arreglar
    antes de F1.2: el triaje solo, sin nada que proteja lo empezado, es el bucle
    original con otro nombre.
    """
    assert ratio(switch_cost=0.0) > ratio(switch_cost=0.8)


def unaffordable_pack() -> ContentPack:
    """La urgencia peor solo se atiende con algo que no se puede pagar.

    Reproduce el caso de Samantha: despensa a cero, dinero a cero, la compra
    exige dinero, y trabajar —que es lo correcto— no atiende la despensa.
    """
    return two_needs_pack(
        needs=[
            {"id": "hambre_t", "label": "h", "decay_per_tick": 0.04, "initial": 0.05},
            {"id": "sueno_t", "label": "s", "decay_per_tick": 0.001, "initial": 0.9},
        ],
        actions=[
            {
                "id": "comer_t",
                "label": "comer_t",
                "duration_ticks": 6,
                "requires": {"sueno_t": 0.95},  # nunca alcanzable: arranca en 0.9
                "satisfies": {"hambre_t": 1.0},
                "effects": {"hambre_t": 0.7},
            },
            {
                "id": "dormir_t",
                "label": "dormir_t",
                "duration_ticks": 30,
                "satisfies": {"sueno_t": 1.0},
                "effects": {"sueno_t": 0.05},
            },
            {"id": "nada_t", "label": "nada_t", "duration_ticks": 2},
        ],
        tuning={"critical_need_threshold": 0.35, "switch_cost": 0.8},
    )


def test_no_interruption_when_the_emergency_has_no_remedy() -> None:
    """Interrumpir para hacer algo que no puedes hacer solo destruye el plan.

    Sin esta guarda el agente reinicia lo mismo cada tick indefinidamente:
    medido en el barrio, una residente acumuló 229 abandonos en tres días
    porque no podía permitirse la compra.
    """
    sim = Simulation(unaffordable_pack(), seed=1)
    sim.run(400)

    rotas = len(sim.log.of_kind(EventKind.ACTION_ABORTED))
    hechas = len(sim.log.of_kind(EventKind.ACTION_COMPLETED))
    assert hechas > 5, "debería seguir completando cosas pese a la urgencia sin salida"
    assert rotas < hechas, f"traqueteo: {rotas} abandonos frente a {hechas} finalizaciones"


def test_a_higher_threshold_means_more_interruptions_not_fewer() -> None:
    """La deuda corregida, medida de punta a punta.

    Con la regla vieja esto salía al revés: más umbral, más cosas críticas,
    más coartada, MENOS abandonos. Que ahora crezca en el sentido correcto es
    lo que hace que `aguante` signifique lo que dice su nombre.
    """
    tranquilo = ratio(threshold=0.10)
    intermedio = ratio(threshold=0.35)
    alarmista = ratio(threshold=0.60)
    assert tranquilo < intermedio < alarmista
