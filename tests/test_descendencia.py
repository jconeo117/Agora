"""Descendencia: el reparto deja de ser cerrado.

Hasta aquí un mundo tenía la gente que su YAML decía, y como mucho la perdía.
Nacer es la primera cosa que lo AMPLÍA, y por eso toca tres piezas que no
existían:

- **La edad** (D-070). No es un rasgo (un rasgo se declara y se queda) ni un
  eje de progresión (un eje se gana haciendo algo): crece sola, para todo el
  mundo, sin que nadie la toque. Es `tick - nacido_en`, y quien ya estaba al
  empezar la partida guarda un `nacido_en` negativo para que la cuenta sea la
  misma para todos.
- **Puertas sobre el OTRO** (D-070). `TargetSpec` sabía preguntar qué lleva
  encima el destinatario, pero no quién es ni cuánto lleva. Sin eso no se puede
  escribir lo que necesita dos partes que no son intercambiables: un rasgo de
  quien actúa no dice nada del otro.
- **El parto** (D-071). Cuelga de la CONDICIÓN y no de la acción, porque entre
  causar algo y que ese algo dé fruto pasa tiempo, y la única pieza del motor
  que sabe esperar es una condición con `lasts`. De ahí que la condición tuviera
  que aprender de quién viene (`Condicion.por_quien`): nueve meses son mucho más
  de lo que dura un recuerdo, así que preguntarle a la memoria de quién es el
  hijo daría *nadie* casi siempre.

**Y el causante puede no estar.** Pudo morir durante la espera. No es un caso de
error: es un huérfano, hereda solo del portador, y el motor no tiene por qué
impedirlo.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agora.engine.events import EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    NeedId,
    PlaceId,
    RelationId,
    SituationId,
    TraitId,
)
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

EL = AgentId("el")
ELLA = AgentId("ella")
CRIA = AgentId("cria")
P1 = PlaceId("p1")
VINCULO = NeedId("vinculo")
VARON = TraitId("varon")
MUJER = TraitId("mujer")
FUERZA = TraitId("fuerza")
PRENADA = SituationId("prenada")
ENGENDRAR = ActionId("engendrar")
RELACION_PORTADORA = RelationId("hijo_de_portadora")
RELACION_CAUSANTE = RelationId("hijo_de_causante")
MADRE = RelationId("madre")
PADRE = RelationId("padre")

MAYORIA = 500
GESTACION = 20


def nacer_pack(**overrides: Any) -> ContentPack:
    """Dos adultos en la misma sala, y una acción que solo uno de los dos puede
    hacerle al otro."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.2},
        ],
        "traits": [
            {"id": "varon", "label": "varon"},
            {"id": "mujer", "label": "mujer"},
            {"id": "fuerza", "label": "fuerza"},
        ],
        "relations": [
            {"id": "hijo_de_portadora", "label": "hijo de", "inverse": "madre"},
            {"id": "madre", "label": "madre", "inverse": "hijo_de_portadora"},
            {"id": "hijo_de_causante", "label": "hijo de", "inverse": "padre"},
            {"id": "padre", "label": "padre", "inverse": "hijo_de_causante"},
        ],
        "situations": [
            {"id": "prenada", "label": "prenada", "personal": True,
             "al_expirar": {
                 "hereda_traits": ["fuerza"],
                 "sortea_traits": [["varon", "mujer"]],
                 "initial_needs": {"vinculo": 0.5},
                 "relacion_con_portador": "hijo_de_portadora",
                 "relacion_con_causante": "hijo_de_causante",
             }},
        ],
        "actions": [
            {"id": "engendrar", "label": "engendrar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "requires_traits": {"varon": 0.5},
             "requires_edad": MAYORIA,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "target": {"gives": {"vinculo": 0.10},
                        "requires_traits": {"mujer": 0.5},
                        "requires_edad": MAYORIA,
                        "forbids_condition": "prenada",
                        "inflicts": {"situation": "prenada", "lasts": GESTACION}}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"]},
        ],
        "agents": [
            {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
             "edad_inicial": 10_000, "traits": {"varon": 1.0, "fuerza": 0.8}},
            {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
             "edad_inicial": 10_000, "traits": {"mujer": 1.0, "fuerza": 0.2}},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def gestando(sim: Simulation) -> Simulation:
    """Corre hasta que ELLA lleva la condición encima."""
    for _ in range(20):
        sim.run(1)
        if sim.state.agents[ELLA].lleva(PRENADA):
            return sim
    raise AssertionError("no llegó a concebir")


# --- la edad (D-070) ----------------------------------------------------------


def test_age_counts_the_same_for_who_was_here_and_who_arrived() -> None:
    """Quien empieza la partida guarda un `nacido_en` NEGATIVO, y por eso la
    fórmula es una sola. Con dos —una para los del pack y otra para los nacidos
    en marcha— el día que alguien olvidara una, media población envejecería el
    doble."""
    sim = Simulation(nacer_pack(), seed=1)
    assert sim.state.agents[EL].nacido_en == -10_000
    assert sim.state.agents[EL].edad(sim.state.tick) == 10_000
    sim.run(50)
    assert sim.state.agents[EL].edad(sim.state.tick) == 10_050


def test_a_world_that_declares_no_ages_still_means_what_it_meant() -> None:
    """Estrenar la edad no puede mover ningún contrato ya medido: sin
    `edad_inicial` todo el mundo nace en el tick cero y ninguna puerta la mira."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1"},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1"},
    ]})
    assert all(a.edad_inicial == 0 for a in pack.agents)
    sim = Simulation(pack, seed=1)
    sim.run(30)
    assert len(sim.state.agents) == 2, "sin nadie que cruce la mayoría, no nace nadie"


def test_a_minor_cannot_do_what_needs_years() -> None:
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(30)
    assert not sim.state.agents[ELLA].lleva(PRENADA)


def test_nor_can_it_be_done_to_a_minor() -> None:
    """La otra mitad de la puerta. Con una sola se escribiría media regla, y la
    mitad que falta no se ve en el log: sale una acción que ocurre y ya está."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10, "traits": {"mujer": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(30)
    assert not sim.state.agents[ELLA].lleva(PRENADA)


def test_growing_up_opens_the_gate_on_its_own() -> None:
    """Nadie tiene que tocar nada: la puerta se abre porque pasa el tiempo."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": MAYORIA - 10, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(5)
    assert not sim.state.agents[ELLA].lleva(PRENADA), "todavía no los cumple"
    sim.run(30)
    assert sim.state.agents[ELLA].lleva(PRENADA)


# --- hacen falta dos, y no cualquiera dos ------------------------------------


def test_it_takes_two_and_the_other_one_has_to_be_the_other_one() -> None:
    """Dos varones en la misma sala no conciben: la puerta de rasgos del
    destinatario es lo único que puede decirlo, porque el rasgo de quien actúa
    no dice nada del otro."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Otro", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(30)
    assert not any(a.lleva(PRENADA) for a in sim.state.agents.values())


def test_alone_nobody_conceives() -> None:
    pack = nacer_pack(**{"places": [
        {"id": "p1", "label": "p1", "affordances": ["sitio"], "neighbors": {"p2": 1}},
        {"id": "p2", "label": "p2", "affordances": ["sitio"], "neighbors": {"p1": 1}},
    ]})
    sim = Simulation(pack, seed=1)
    for _ in range(30):
        sim.state.agents[EL].at = P1
        sim.state.agents[ELLA].at = PlaceId("p2")
        sim.run(1)
    assert not sim.state.agents[ELLA].lleva(PRENADA)


def test_whoever_is_already_expecting_is_not_a_candidate_again() -> None:
    """`forbids_condition` es la única puerta en negativo del motor. Sin ella
    habría que modelar "está disponible" con un eje que baje a cero, que es un
    número donde lo que hay es un sí o un no."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    ella = sim.state.agents[ELLA]
    hasta = next(c.hasta for c in ella.condiciones if c.situacion == PRENADA)

    sim.run(3)
    sigue = next(c for c in ella.condiciones if c.situacion == PRENADA)
    assert sigue.hasta == hasta, "un segundo intento le habría alargado el plazo"
    assert sigue.gravedad == 1.0, "ni agravado"


# --- el parto (D-071) ---------------------------------------------------------


def test_the_wait_lasts_what_the_pack_says_and_then_somebody_is_there() -> None:
    sim = gestando(Simulation(nacer_pack(), seed=1))
    concebido = sim.state.tick
    assert len(sim.state.agents) == 2

    sim.run(GESTACION - 1)
    assert len(sim.state.agents) == 2, "todavía no"

    sim.run(2)
    assert len(sim.state.agents) == 3
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    assert sim.state.agents[nacido].nacido_en >= concebido + GESTACION


def test_the_newborn_is_in_the_census_and_the_census_is_the_authority() -> None:
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    assert nacido in sim.state.censo
    assert sim.state.censo[nacido].home == P1, "se cría donde se crió quien lo llevaba"


def test_a_birth_is_announced_once_and_says_of_whom() -> None:
    """Al revés que una muerte, que se emite una vez por superviviente que la
    sufre: nacer no le pasa a nadie más que a quien nace."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    partos = sim.log.of_kind(EventKind.AGENT_BORN)
    assert len(partos) == 1
    assert partos[0].subject == ELLA
    assert partos[0].data["otro"] == str(EL)


def test_the_newborn_is_family_on_both_sides() -> None:
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))

    cria = sim.state.agents[nacido]
    assert ELLA in cria.relations[RELACION_PORTADORA]
    assert EL in cria.relations[RELACION_CAUSANTE]
    # Y el otro lado lo puso `inverse`, sin que el pack declarara nada más.
    assert nacido in sim.state.agents[ELLA].relations[MADRE]
    assert nacido in sim.state.agents[EL].relations[PADRE]


def test_it_takes_after_both_of_them() -> None:
    """Con `ruido` a 0 la media es exacta, y es lo que hace comprobable que
    hereda de los DOS: 0.8 y 0.2 dan 0.5, que no es el valor de ninguno."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    assert sim.state.agents[nacido].traits[FUERZA] == pytest.approx(0.5)


def test_what_is_drawn_is_drawn_whole() -> None:
    """De un grupo excluyente sale exactamente uno. Sortear cada rasgo por
    separado dejaría a alguien siendo las dos cosas, o ninguna."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    suyos = sim.state.agents[nacido].traits
    assert {suyos[VARON], suyos[MUJER]} == {0.0, 1.0}


def test_the_same_seed_begets_the_same_person() -> None:
    uno = gestando(Simulation(nacer_pack(), seed=7))
    uno.run(GESTACION + 2)
    otro = gestando(Simulation(nacer_pack(), seed=7))
    otro.run(GESTACION + 2)

    def ficha(sim: Simulation) -> tuple[str, tuple[tuple[str, float], ...]]:
        quien = next(a for a in sim.state.agents if a not in (EL, ELLA))
        return str(quien), tuple(sorted(
            (str(t), v) for t, v in sim.state.agents[quien].traits.items()
        ))

    assert ficha(uno) == ficha(otro)


def test_an_orphan_is_born_anyway() -> None:
    """El causante pudo morir durante la espera, y nueve meses son tiempo de
    sobra en un mundo violento. No es un error: hereda solo del portador y se
    queda sin esa relación."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.morir(EL)
    sim.run(GESTACION + 2)

    nacido = next(a for a in sim.state.agents if a != ELLA)
    cria = sim.state.agents[nacido]
    assert ELLA in cria.relations[RELACION_PORTADORA]
    assert RELACION_CAUSANTE not in cria.relations
    # Y hereda el valor del portador a secas, no su mitad: quedarse sin padre no
    # rebaja a nadie.
    assert cria.traits[FUERZA] == pytest.approx(0.2)


def test_the_newborn_is_awake_from_the_first_tick() -> None:
    """Nace en el paso del DECAIMIENTO, así que no decae ni sufre nada ese tick
    -- pero el paso en que cada cual resuelve su ocupación vuelve a pedir la
    lista de agentes, y para entonces ya está. Delibera desde el instante en que
    aparece, y lo que pueda hacer recién llegado es cosa de las puertas de edad
    que ponga el pack, no del motor."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    nacimiento = sim.state.agents[nacido].nacido_en
    assert any(
        e.actor == nacido and e.tick == nacimiento
        for e in sim.log.of_kind(EventKind.ACTION_STARTED)
    )


# --- lo que el pack no puede declarar ------------------------------------------


def test_a_birth_hanging_off_a_world_situation_does_not_load() -> None:
    with pytest.raises(ValidationError, match="no es `personal`"):
        nacer_pack(**{"situations": [
            {"id": "prenada", "label": "prenada",
             "al_expirar": {"relacion_con_portador": "hijo_de_portadora"}},
        ]})


def test_a_birth_that_never_expires_does_not_load() -> None:
    """El plazo no lo pone la situación sino quien la pega, así que la puerta
    tiene que mirar ahí: una condición sin `lasts` no se pasa sola, no expira, y
    lo que colgaba de ella no ocurre nunca."""
    with pytest.raises(ValidationError, match="sin `lasts`"):
        nacer_pack(**{"actions": [
            {"id": "engendrar", "label": "engendrar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "requires_traits": {"varon": 0.5},
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "target": {"gives": {"vinculo": 0.10},
                        "inflicts": {"situation": "prenada"}}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ]})


def test_a_draw_between_one_option_does_not_load() -> None:
    with pytest.raises(ValidationError, match="no sortea nada"):
        nacer_pack(**{"situations": [
            {"id": "prenada", "label": "prenada", "personal": True,
             "al_expirar": {"sortea_traits": [["varon"]]}},
        ]})


# --- persistencia ---------------------------------------------------------------


def test_who_was_born_in_play_survives_save_and_resume(tmp_path: Path) -> None:
    """De los del pack basta con guardar el estado, porque su ficha se
    reconstruye del YAML. De estos no hay ficha en ningún sitio: o se guarda
    entera o al reanudar no existen."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    antes = sim.state.agents[nacido]
    sim.save(tmp_path / "s.json")

    otra = Simulation.resume(tmp_path / "s.json", nacer_pack())
    assert nacido in otra.state.agents
    assert otra.state.agents[nacido].traits == antes.traits
    assert otra.state.agents[nacido].nacido_en == antes.nacido_en
    assert otra.state.censo[nacido].home == P1


def test_the_wait_survives_save_and_resume(tmp_path: Path) -> None:
    """Y con ella de quién es. Sin `por_quien` guardado, reanudar a mitad del
    plazo dejaría un huérfano de padre vivo."""
    sim = gestando(Simulation(nacer_pack(), seed=1))
    sim.save(tmp_path / "s.json")

    otra = Simulation.resume(tmp_path / "s.json", nacer_pack())
    esperando = next(
        c for c in otra.state.agents[ELLA].condiciones if c.situacion == PRENADA
    )
    assert esperando.por_quien == EL
    otra.run(GESTACION + 2)
    nacido = next(a for a in otra.state.agents if a not in (EL, ELLA))
    assert EL in otra.state.agents[nacido].relations[RELACION_CAUSANTE]


def test_it_can_be_written_from_either_side() -> None:
    """La versión espejo: actúa ELLA, y la espera se la queda ella misma por
    `ActionSpec.inflicts` en vez de por `target.inflicts`. Sigue sabiendo de
    quién es, porque una condición que te queda de algo hecho CON otro tiene por
    autor a ese otro. Sin eso, la mitad de los partos serían de padre
    desconocido por haber escrito la acción desde el otro lado."""
    pack = nacer_pack(**{"actions": [
        {"id": "engendrar", "label": "engendrar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_company": 1,
         "requires_traits": {"mujer": 0.5},
         "forbids_condition": "prenada",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "inflicts": {"situation": "prenada", "lasts": GESTACION},
         "target": {"gives": {"vinculo": 0.10},
                    "requires_traits": {"varon": 0.5}}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    sim = gestando(Simulation(pack, seed=1))
    esperando = next(
        c for c in sim.state.agents[ELLA].condiciones if c.situacion == PRENADA
    )
    assert esperando.por_quien == EL

    sim.run(GESTACION + 2)
    nacido = next(a for a in sim.state.agents if a not in (EL, ELLA))
    assert EL in sim.state.agents[nacido].relations[RELACION_CAUSANTE]


def test_what_you_do_to_yourself_has_no_author() -> None:
    """La contraparte: una condición que uno se deja encima sin nadie delante no
    apunta a nadie, y sigue sin apuntar a nadie."""
    pack = nacer_pack(**{"actions": [
        {"id": "engendrar", "label": "recluirse", "duration_ticks": 1,
         "requires_affordance": "sitio",
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "inflicts": {"situation": "prenada", "lasts": GESTACION}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ]})
    sim = gestando(Simulation(pack, seed=1))
    esperando = next(
        c for c in sim.state.agents[ELLA].condiciones if c.situacion == PRENADA
    )
    assert esperando.por_quien is None
