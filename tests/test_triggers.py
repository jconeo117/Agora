"""Disparadores: que al mundo le pase algo que nadie decidió.

**La primera pieza del motor que crea sucesos por su cuenta**, y la única
peligrosa de esta forma: si se le da demasiada cuerda, el mundo pasa de vivo a
aleatorio y eso destruye la legibilidad, que es la regla rectora del proyecto.

Por eso la mitad de este fichero prueba los frenos y no la función. Un
disparador que dispara es fácil; uno que se puede explicar, no.
"""

from __future__ import annotations

import copy
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.timeskip import saltar
from agora.engine.world import Simulation

TORMENTA = SituationId("tormenta")
INVIERNO = SituationId("invierno")


def trigger_pack(**overrides: Any) -> ContentPack:
    """Un mundo mínimo con una situación eventual disparable.

    `tormenta` cierra `refugio`, así que hace algo — el validador rechaza una
    situación que no afecte a nada.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "clock": {"ticks_per_day": 10, "days_per_year": 10},
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.8}
        ],
        "actions": [
            {
                "id": "act",
                "label": "act",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.2},
            },
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"refugio": 1}},
            {
                "id": "refugio",
                "label": "refugio",
                "affordances": ["aff"],
                "neighbors": {"p1": 1},
                "closed_during": ["tormenta"],
            },
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "situations": [
            {
                "id": "tormenta",
                "label": "tormenta",
                "trigger": {
                    "expected_per_year": 50.0,
                    "lasts_min": 3,
                    "lasts_max": 3,
                    "cooldown": 20,
                },
            }
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def encendidos(sim: Simulation) -> list[Any]:
    return [e for e in sim.log if e.kind is EventKind.SITUATION_BEGAN]


# --- los frenos, que es lo que de verdad hay que probar -----------------------


def test_off_by_default_moves_nothing() -> None:
    """`expected_per_year` a 0 desactiva el mecanismo. Es lo que permite que
    estrenar los disparadores no toque ningún contrato ya medido."""
    pack = trigger_pack(
        **{
            "situations": [
                {"id": "tormenta", "label": "tormenta", "trigger": {"lasts_min": 3,
                                                                    "lasts_max": 3}}
            ]
        }
    )
    sim = Simulation(pack, seed=7)
    sim.run(500)
    assert not sim.state.situations
    assert encendidos(sim) == []


def test_a_situation_without_a_trigger_never_fires() -> None:
    pack = trigger_pack(**{"situations": [{"id": "tormenta", "label": "tormenta"}]})
    sim = Simulation(pack, seed=7)
    sim.run(500)
    assert encendidos(sim) == []


def test_an_active_trigger_needs_a_cooldown() -> None:
    """Sin él, la situación se reenciende al tick siguiente de apagarse y lo que
    el pack quiso decir con 'de vez en cuando' es 'siempre, con parpadeos'."""
    with pytest.raises(ValidationError, match="cooldown"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "trigger": {"expected_per_year": 5.0, "lasts_min": 2,
                                    "lasts_max": 2},
                    }
                ]
            }
        )


def test_the_cooldown_has_to_outlast_the_situation() -> None:
    """Se cuenta desde el encendido, así que un cooldown más corto que la
    duración expiraría mientras la cosa todavía pasa: no separa nada."""
    with pytest.raises(ValidationError, match="no supera la duración"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "trigger": {"expected_per_year": 5.0, "lasts_min": 2,
                                    "lasts_max": 10, "cooldown": 5},
                    }
                ]
            }
        )


def test_a_backwards_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="rango al revés"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "trigger": {"lasts_min": 9, "lasts_max": 2},
                    }
                ]
            }
        )


def test_a_periodic_situation_cannot_be_triggered() -> None:
    """Iría sola de todos modos y el disparador parecería funcionar. Es el mismo
    malentendido que `begin_situation` ya rechaza."""
    with pytest.raises(ValidationError, match="periódica"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "every": 100,
                        "lasts": 10,
                        "trigger": {"lasts_min": 1, "lasts_max": 1},
                    }
                ]
            }
        )


def test_a_trigger_that_requires_itself_is_rejected() -> None:
    """No podría encenderse jamás, y nada lo diría: el disparador está puesto y
    simplemente no dispara."""
    with pytest.raises(ValidationError, match="a sí misma"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "trigger": {
                            "expected_per_year": 5.0, "lasts_min": 1, "lasts_max": 1,
                            "cooldown": 10, "requires_situations": ["tormenta"],
                        },
                    }
                ]
            }
        )


def test_a_trigger_pointing_at_nothing_is_rejected() -> None:
    with pytest.raises(ValidationError, match="situación desconocida"):
        trigger_pack(
            **{
                "situations": [
                    {
                        "id": "tormenta",
                        "label": "tormenta",
                        "trigger": {
                            "expected_per_year": 5.0, "lasts_min": 1, "lasts_max": 1,
                            "cooldown": 10, "requires_situations": ["que_no_existe"],
                        },
                    }
                ]
            }
        )


# --- que dispare ---------------------------------------------------------------


def test_the_world_eventually_gets_a_surprise() -> None:
    sim = Simulation(trigger_pack(), seed=7)
    sim.run(2000)
    assert encendidos(sim), "con 50 al año y 2000 ticks tendría que haber pasado algo"


def test_the_same_seed_gets_the_same_surprises() -> None:
    """El determinismo alcanza también a lo que el mundo decide solo. Sin esto,
    reproducir un fallo del día cinco deja de ser posible."""
    uno, otro = Simulation(trigger_pack(), seed=11), Simulation(trigger_pack(), seed=11)
    uno.run(1000)
    otro.run(1000)
    assert [e.to_json() for e in encendidos(uno)] == [e.to_json() for e in encendidos(otro)]


def test_different_seeds_get_different_surprises() -> None:
    ticks = [
        tuple(e.tick for e in encendidos(_corrida(seed)))
        for seed in (1, 2, 3, 4, 5)
    ]
    assert len(set(ticks)) > 1, "si la semilla no cambia nada, no hay azar ninguno"


def _corrida(seed: int) -> Simulation:
    sim = Simulation(trigger_pack(), seed=seed)
    sim.run(1000)
    return sim


def test_the_cooldown_separates_two_episodes() -> None:
    sim = Simulation(trigger_pack(), seed=7)
    sim.run(3000)
    momentos = [e.tick for e in encendidos(sim)]
    assert len(momentos) >= 2, "el test no prueba nada con un solo encendido"
    assert all(b - a >= 20 for a, b in pairwise(momentos))


def test_the_duration_is_drawn_from_the_range() -> None:
    """Rango y no número fijo: una tormenta que siempre dura lo mismo no es
    aleatoria, es guionizada, y eso es tan ilegible como el ruido."""
    pack = trigger_pack(
        **{
            "situations": [
                {
                    "id": "tormenta",
                    "label": "tormenta",
                    "trigger": {"expected_per_year": 80.0, "lasts_min": 2,
                                "lasts_max": 9, "cooldown": 30},
                }
            ]
        }
    )
    duraciones: set[int] = set()
    for seed in range(40):
        sim = Simulation(pack, seed=seed)
        sim.run(600)
        duraciones.update(int(e.data["ticks"]) for e in encendidos(sim))
    assert duraciones, "no disparó nunca"
    assert all(2 <= d <= 9 for d in duraciones)
    assert len(duraciones) > 1, "siempre la misma duración: el rango no se sortea"


def test_a_condition_gates_the_trigger() -> None:
    """La ventisca solo en invierno, sin mecanismo nuevo."""
    pack = trigger_pack(
        **{
            "situations": [
                {"id": "invierno", "label": "invierno", "every": 100, "lasts": 10,
                 "gain_multipliers": {"n1": 0.5}},
                {
                    "id": "tormenta",
                    "label": "tormenta",
                    "trigger": {
                        "expected_per_year": 200.0, "lasts_min": 2, "lasts_max": 2,
                        "cooldown": 5, "requires_situations": ["invierno"],
                    },
                },
            ]
        }
    )
    sim = Simulation(pack, seed=7)
    sim.run(1000)
    assert encendidos(sim), "no disparó nunca; el test no probaría nada"
    for evento in encendidos(sim):
        # `invierno` dura 10 de cada 100 ticks, empezando en 0.
        assert evento.tick % 100 < 10, "encendió fuera de invierno"


# --- el tercer freno: el log dice por qué -------------------------------------


def test_the_log_says_it_was_chance() -> None:
    sim = Simulation(trigger_pack(), seed=7)
    sim.run(1000)
    assert all(e.data["porque"] == "azar" for e in encendidos(sim))


def test_the_log_names_the_condition_that_held() -> None:
    pack = trigger_pack(
        **{
            "situations": [
                {"id": "invierno", "label": "invierno", "every": 100, "lasts": 10,
                 "gain_multipliers": {"n1": 0.5}},
                {
                    "id": "tormenta",
                    "label": "tormenta",
                    "trigger": {
                        "expected_per_year": 200.0, "lasts_min": 2, "lasts_max": 2,
                        "cooldown": 5, "requires_situations": ["invierno"],
                    },
                },
            ]
        }
    )
    sim = Simulation(pack, seed=7)
    sim.run(1000)
    assert encendidos(sim)
    assert all(e.data["porque"] == "invierno" for e in encendidos(sim))


def test_a_situation_lit_by_hand_says_so() -> None:
    """Distinguir lo que decidió alguien de lo que decidió el mundo es la mitad
    del valor del campo."""
    sim = Simulation(trigger_pack(), seed=7)
    sim.begin_situation(TORMENTA, ticks=5)
    assert encendidos(sim)[0].data["porque"] == "a mano"


# --- convivencia con lo que ya había ------------------------------------------


def test_the_cooldown_survives_a_save(tmp_path: Path) -> None:
    """Sin esto, reanudar rearmaría todos los disparadores a la vez y el mundo se
    llenaría de imprevistos justo al cargar."""
    pack = trigger_pack()
    sim = Simulation(pack, seed=7)
    sim.run(1000)
    assert sim.state.last_trigger, "el test no prueba nada sin disparos"

    destino = tmp_path / "partida.json"
    sim.save(destino)
    vuelto = Simulation.resume(destino, pack)
    assert vuelto.state.last_trigger == sim.state.last_trigger


def test_a_save_from_before_triggers_loads_clean(tmp_path: Path) -> None:
    import json

    pack = trigger_pack()
    sim = Simulation(pack, seed=7)
    sim.run(200)
    destino = tmp_path / "vieja.json"
    sim.save(destino)

    datos = json.loads(destino.read_text(encoding="utf-8"))
    del datos["last_trigger"]
    destino.write_text(json.dumps(datos), encoding="utf-8")

    assert Simulation.resume(destino, pack).state.last_trigger == {}


# --- el cuarto canal: que le pase algo a alguien ------------------------------


def dolor_pack(**overrides: Any) -> ContentPack:
    """Un mundo donde la tormenta hace daño, no solo cierra el refugio."""
    base = trigger_pack().model_dump(mode="json")
    data: dict[str, Any] = {
        **{k: v for k, v in base.items() if k not in {"situations"}},
        "situations": [
            {
                "id": "tormenta",
                "label": "tormenta",
                "effects": {"n1": -0.05},
                "places": ["p1"],
            }
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_a_situation_can_finally_hurt_you() -> None:
    """**El agujero que el paso 1 dejaba a la vista.** Sin este canal, una oleada
    de monstruos significa exactamente que apetece más trabajar."""
    sim = Simulation(dolor_pack(), seed=7)
    agente = sim.state.agents[AgentId("ag1")]
    antes = agente.needs[NeedId("n1")]

    sim.begin_situation(TORMENTA, ticks=100)
    sim.run(1)
    assert agente.needs[NeedId("n1")] < antes - 0.04


def test_it_only_reaches_where_it_says() -> None:
    """El alcance ya lo declaraba la situación; el daño lo respeta sin código
    nuevo, por `situations_at`."""
    sim = Simulation(dolor_pack(), seed=7)
    agente = sim.state.agents[AgentId("ag1")]
    agente.at = PlaceId("refugio")  # fuera del alcance de la tormenta
    antes = agente.needs[NeedId("n1")]

    sim.begin_situation(TORMENTA, ticks=100)
    sim.run(1)
    # Solo el decaimiento normal, muy por debajo del 0.05 de la tormenta.
    assert agente.needs[NeedId("n1")] > antes - 0.03


def test_the_damage_can_cause_the_crisis() -> None:
    """El orden dentro del tick es lo que hace útil el mecanismo: el daño va
    antes del chequeo crítico, así que puede EMPUJARTE por debajo del umbral y la
    crisis sale con el lugar puesto. Es la materia prima del miedo a lugares."""
    sim = Simulation(dolor_pack(), seed=7)
    agente = sim.state.agents[AgentId("ag1")]
    agente.needs[NeedId("n1")] = 0.2

    sim.begin_situation(TORMENTA, ticks=100)
    sim.run(3)
    crisis = [e for e in sim.log if e.kind is EventKind.NEED_CRITICAL]
    assert crisis, "la tormenta tendría que haber hundido el eje"
    assert crisis[0].place == PlaceId("p1")


def test_a_gift_is_filed_as_free_not_as_earned() -> None:
    """**La razón de que `endure` exista aparte de `apply`.** Lo que llega por
    estar ahí no lo mueve ninguna decisión; archivarlo como `activo` inflaría la
    oferta atribuida a las decisiones y vaciaría la columna `de gorra`, que es la
    que dice dónde cortar. Ese error ya costó una campaña con el vínculo."""
    from agora.engine.state import Ledger

    sim = Simulation(dolor_pack(**{"situations": [
        {"id": "tormenta", "label": "tormenta", "effects": {"n1": 0.05},
         "places": ["p1"]}
    ]}), seed=7)
    agente = sim.state.agents[AgentId("ag1")]
    agente.ledger = Ledger()
    agente.needs[NeedId("n1")] = 0.3

    sim.begin_situation(TORMENTA, ticks=100)
    sim.run(1)
    libro = agente.ledger
    assert libro.pasivo.get(NeedId("n1"), 0.0) >= 0.05
    assert libro.activo.get(NeedId("n1"), 0.0) == 0.0


def test_damage_counts_as_demand() -> None:
    """Perder es perder, lo pierdas por gastarlo o porque nieva. Si no entrara en
    la demanda, el panel de oferta/demanda mentiría en cuanto nevara."""
    from agora.engine.state import Ledger

    sim = Simulation(dolor_pack(), seed=7)
    agente = sim.state.agents[AgentId("ag1")]
    agente.ledger = Ledger()

    sim.begin_situation(TORMENTA, ticks=100)
    sim.run(1)
    assert agente.ledger.demanda.get(NeedId("n1"), 0.0) >= 0.05


def test_a_situation_that_only_hurts_is_not_dead_content() -> None:
    """El validador rechaza situaciones que no hacen nada. Una que solo baja el
    sustento de quien está dentro no necesita que ninguna acción la mencione
    para ser una hambruna."""
    pack = dolor_pack()  # tormenta no cierra nada ni la menciona ninguna acción
    assert pack.situation_by_id[TORMENTA].effects


def test_a_situation_that_really_does_nothing_is_still_rejected() -> None:
    """Añadir un canal no puede aflojar la comprobación: una situación con
    nombre que no toca nada sigue siendo contenido muerto.

    Hay que quitarle también el `closed_during` del refugio — con él la tormenta
    sí hace algo, y el test no probaría nada.
    """
    with pytest.raises(ValidationError, match="no hace absolutamente nada"):
        dolor_pack(
            **{
                "situations": [{"id": "tormenta", "label": "tormenta", "places": ["p1"]}],
                "places": [
                    {"id": "p1", "label": "p1", "affordances": ["aff"],
                     "neighbors": {"refugio": 1}},
                    {"id": "refugio", "label": "refugio", "affordances": ["aff"],
                     "neighbors": {"p1": 1}},
                ],
            }
        )


def test_the_whole_chain_leaves_a_memory_of_the_place() -> None:
    """**Lo que los pasos 1 y 2 existen para conseguir, de punta a punta.**

    Nadie decide que haya tormenta; la tormenta hunde un eje; la crisis sale con
    el lugar puesto; el recuerdo la guarda con signo negativo. Eso es *algo malo
    me pasó AQUÍ*, y es la señal que el frente del miedo a lugares no tenía —los
    chascos de llegada resultaron ser la percepción funcionando, no una herida.

    No conecta el miedo: comprueba que ya hay de qué alimentarlo.
    """
    # El eje arranca bajo y la tormenta pega fuerte: con `act` dando 0.2 por
    # tick, una tormenta de 0.05 la absorbe el agente sin despeinarse y no hay
    # crisis que grabar. Lo que se prueba aquí es la cadena, no si sabe huir.
    pack = dolor_pack(
        **{
            "needs": [
                {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.25}
            ],
            "situations": [
                {
                    "id": "tormenta",
                    "label": "tormenta",
                    "effects": {"n1": -0.12},
                    "places": ["p1"],
                    "trigger": {"expected_per_year": 300.0, "lasts_min": 20,
                                "lasts_max": 20, "cooldown": 40},
                }
            ],
            "tuning": {"memory_capacity": 20, "memory_scale": 0.5},
        }
    )
    sim = Simulation(pack, seed=3)
    sim.run(600)

    assert encendidos(sim), "no llegó a haber tormenta"
    recuerdos = sim.state.memoria.de(AgentId("ag1"))
    dolorosos = [
        r for r in recuerdos
        if r.valencia < 0.0 and r.action is None and r.place is not None
    ]
    assert dolorosos, "nada malo quedó grabado con un lugar detrás"
    assert any(r.place == PlaceId("p1") for r in dolorosos)


def test_a_timeskip_does_not_calm_the_world_down() -> None:
    """**El fallo que casi se cuela.** `_adelantar_reloj` mueve el tick sin pasar
    por el tick loop, así que sin darles su zancada los disparadores se evaluarían
    una vez cada `factor` días — y la carrera de cinco años de la ciudad usa
    `--skip 14`. El mundo habría tenido catorce veces menos imprevistos sin que
    nada lo dijera.
    """
    dias = 200
    seguido = Simulation(trigger_pack(), seed=7)
    seguido.run(dias * 10)

    saltado = Simulation(trigger_pack(), seed=7)
    saltar(saltado, dias, factor=5)

    # No se exige igualdad: el salto aproxima, y como mucho enciende una vez por
    # zancada. Lo que se exige es que no se apague el mecanismo.
    assert len(encendidos(saltado)) > 0
    assert len(encendidos(saltado)) >= len(encendidos(seguido)) // 3
