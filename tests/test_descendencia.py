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
    GoalId,
    GoalStatus,
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
OTRO = AgentId("otro")

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
                 "regard_buscado": 0.6,
                 "regard_no_buscado": 0.05,
                 "regard_hacia_progenitores": 0.4,
                 "regard_entre_progenitores": 0.3,
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


# --- quién lo quería (D-076) ---------------------------------------------------
#
# No todo el que se convierte en padre quiere a su hijo igual, y la diferencia no
# la puede decir un suelo de aprecio por relación: un suelo se lo pone a todo el
# mundo por igual, y lo que separa a un padre de otro es si lo quiso ANTES.
#
# "Quererlo antes" no necesita un campo nuevo. Querer algo ya se escribe de una
# sola manera en este motor —una meta— y `at_kin` es la vara que cuenta
# parientes. Lo que faltaba era que algo pudiera CUMPLIRLA: hasta el parto, nada
# anudaba un lazo en marcha, y el propio docstring de `at_kin` avisaba de que no
# se escribiera un arco que dependiera de ella.


def buscado_pack(quien: str = "ella", **overrides: Any) -> ContentPack:
    """`quien` lleva la meta de tener descendencia. El otro, no."""
    metas = {
        "ella": {"id": "ser_madre", "label": "ser madre", "need": "vinculo",
                 "at_kin": {"madre": 1}},
        "el": {"id": "ser_padre", "label": "ser padre", "need": "vinculo",
               "at_kin": {"padre": 1}},
    }
    fichas = [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0, "fuerza": 0.8}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0, "fuerza": 0.2}},
    ]
    for ficha in fichas:
        if ficha["id"] in quien.split("+"):
            ficha["goals"] = [metas[str(ficha["id"])]]
    data: dict[str, Any] = {"agents": fichas}
    data.update(copy.deepcopy(overrides))
    return nacer_pack(**data)


def parir(pack: ContentPack, seed: int = 1) -> tuple[Simulation, AgentId]:
    sim = gestando(Simulation(pack, seed=seed))
    sim.run(GESTACION + 2)
    return sim, next(a for a in sim.state.agents if a not in (EL, ELLA))


def test_whoever_wanted_it_starts_loving_it() -> None:
    sim, nacido = parir(buscado_pack("ella"))
    assert sim.state.agents[ELLA].bonds[nacido].regard == pytest.approx(0.6)


def test_whoever_did_not_starts_at_almost_nothing() -> None:
    """Bajo, no negativo: quien no lo quería no arranca odiándolo, arranca sin
    nada. A partir de ahí sube conviviendo, como el de cualquiera."""
    sim, nacido = parir(buscado_pack("ella"))
    assert sim.state.agents[EL].bonds[nacido].regard == pytest.approx(0.05)


def test_two_parents_of_the_same_child_can_feel_differently_about_it() -> None:
    """Lo que un suelo de aprecio por relación no puede decir: el mismo hijo,
    los mismos dos padres, y dos afectos distintos."""
    sim, nacido = parir(buscado_pack("ella"))
    assert (
        sim.state.agents[ELLA].bonds[nacido].regard
        > sim.state.agents[EL].bonds[nacido].regard
    )


def test_nobody_wanted_it_and_it_is_born_anyway() -> None:
    """No hay forma de interrumpir una concepción, y eso es a propósito: el hijo
    no buscado tiene que poder existir."""
    sim, nacido = parir(buscado_pack("nadie"))
    assert sim.state.agents[ELLA].bonds[nacido].regard == pytest.approx(0.05)
    assert sim.state.agents[EL].bonds[nacido].regard == pytest.approx(0.05)


def test_achieving_it_together_brings_them_closer() -> None:
    """Un hecho entre ELLOS DOS, que ningún premio hacia la criatura puede
    decir."""
    solo_ella, _ = parir(buscado_pack("ella"))
    ambos, _ = parir(buscado_pack("el+ella"))

    assert ambos.state.agents[ELLA].bonds[EL].regard > (
        solo_ella.state.agents[ELLA].bonds[EL].regard
    )
    assert ambos.state.agents[EL].bonds[ELLA].regard > (
        solo_ella.state.agents[EL].bonds[ELLA].regard
    )


def test_the_newborn_loves_them_both_the_same() -> None:
    """Un recién nacido no sabe quién lo quiso."""
    sim, nacido = parir(buscado_pack("ella"))
    cria = sim.state.agents[nacido]
    assert cria.bonds[ELLA].regard == pytest.approx(0.4)
    assert cria.bonds[EL].regard == pytest.approx(0.4)


def test_a_bond_that_already_existed_is_not_reset_by_a_birth() -> None:
    """Estrena, no acumula: dos que ya se conocían no vuelven a empezar porque
    haya nacido alguien."""
    pack = buscado_pack("ella")
    sim = Simulation(pack, seed=1)
    for t in range(30):
        sim.state.agents[ELLA].remember_company([EL], premium=0.9, rate=0.5, tick=t)
    antes = sim.state.agents[ELLA].bonds[EL].regard
    gestando(sim)
    sim.run(GESTACION + 2)
    assert sim.state.agents[ELLA].bonds[EL].regard >= antes


def test_wanting_it_is_read_from_the_goal_and_nothing_else() -> None:
    """Sin `at_kin` que nombre la relación, la misma meta no dice nada: lo que
    se pregunta es si quería ESTO, no si tenía ambiciones."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0},
         "goals": [{"id": "otra_cosa", "label": "otra cosa", "need": "vinculo",
                    "at_least": 0.95}]},
    ]})
    sim, nacido = parir(pack)
    assert sim.state.agents[ELLA].bonds[nacido].regard == pytest.approx(0.05)


# --- que un nacido pueda querer a su vez (D-077) --------------------------------


def test_the_newborn_can_carry_goals_of_its_own() -> None:
    """El hilo que `pursuing` dejaba señalado desde F1.14. Sin esto, la segunda
    generación no puede querer nada: la meta está escrita en su ficha del censo,
    el bucle que la cierra la ve —lee del censo— y el que la hace EMPUJAR no,
    porque preguntaba al pack. La meta existía y no pesaba."""
    pack = buscado_pack("ella", **{"situations": [
        {"id": "prenada", "label": "prenada", "personal": True,
         "al_expirar": {
             "goals": ["ser_madre"],
             "sortea_traits": [["varon", "mujer"]],
             "relacion_con_portador": "hijo_de_portadora",
             "relacion_con_causante": "hijo_de_causante",
         }},
    ]})
    sim, nacido = parir(pack)
    cria = sim.state.agents[nacido]
    assert [str(m.id) for m in cria.metas] == ["ser_madre"]
    assert [str(m.id) for m in cria.pursuing(pack)] == ["ser_madre"]


def test_goals_of_the_newborn_survive_save_and_resume(tmp_path: Path) -> None:
    pack = buscado_pack("ella", **{"situations": [
        {"id": "prenada", "label": "prenada", "personal": True,
         "al_expirar": {
             "goals": ["ser_madre"],
             "sortea_traits": [["varon", "mujer"]],
             "relacion_con_portador": "hijo_de_portadora",
             "relacion_con_causante": "hijo_de_causante",
         }},
    ]})
    sim, nacido = parir(pack)
    sim.save(tmp_path / "s.json")

    otra = Simulation.resume(tmp_path / "s.json", pack)
    assert [str(m.id) for m in otra.state.agents[nacido].metas] == ["ser_madre"]


# --- la edad de querer (D-081) -------------------------------------------------
#
# Un recién nacido no quiere nada. Hasta aquí toda meta que no esperase a otra
# nacía ACTIVE, así que una criatura salía del parto con las ambiciones de un
# adulto puestas — y como las puertas de las acciones ya le impiden
# perseguirlas, lo que quedaba era un empujón que no podía atenderse.


def con_edad_pack(requires_edad: int, edad_inicial: int = 10_000) -> ContentPack:
    return nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": edad_inicial, "traits": {"mujer": 1.0},
         "goals": [{"id": "ser_madre", "label": "ser madre", "need": "vinculo",
                    "at_kin": {"madre": 1}, "requires_edad": requires_edad}]},
    ]})


def test_a_goal_you_are_too_young_for_starts_locked() -> None:
    sim = Simulation(con_edad_pack(50_000), seed=1)
    assert sim.state.agents[ELLA].goals[GoalId("ser_madre")] is GoalStatus.LOCKED
    assert sim.state.agents[ELLA].pursuing(sim.pack) == ()


def test_it_opens_by_itself_when_the_age_arrives() -> None:
    """Nadie tiene que tocar nada: se abre porque pasa el tiempo."""
    sim = Simulation(con_edad_pack(10_020), seed=1)
    sim.run(5)
    assert sim.state.agents[ELLA].goals[GoalId("ser_madre")] is GoalStatus.LOCKED
    sim.run(30)
    # Ya no espera. Puede incluso haberla cerrado: lo que se comprueba es que la
    # edad la abrió, no en qué acabó.
    assert sim.state.agents[ELLA].goals[GoalId("ser_madre")] is not GoalStatus.LOCKED
    assert sim.log.of_kind(EventKind.GOAL_UNLOCKED)


def test_being_old_enough_already_needs_no_unlocking() -> None:
    sim = Simulation(con_edad_pack(500), seed=1)
    assert sim.state.agents[ELLA].goals[GoalId("ser_madre")] is GoalStatus.ACTIVE


def test_a_goal_locked_by_age_does_not_count_as_wanting_it() -> None:
    """Lo que aún no se entiende no se quiere: quien no llega a la edad no puede
    haberlo buscado, y su hijo lo nota."""
    pack = nacer_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0},
         "goals": [{"id": "ser_madre", "label": "ser madre", "need": "vinculo",
                    "at_kin": {"madre": 1}, "requires_edad": 999_999}]},
    ]})
    sim, nacido = parir(pack)
    assert sim.state.agents[ELLA].bonds[nacido].regard == pytest.approx(0.05)


def test_the_clock_does_not_run_while_you_are_too_young() -> None:
    """Misma regla que una meta que espera a otra (D-121): no se puede perder lo
    que aún no habías empezado. Al revés, quien nace con una meta a diez años y
    un plazo de tres la habría perdido antes de entenderla."""
    sim = Simulation(con_edad_pack(50_000), seed=1)
    sim.run(60)
    assert sim.state.agents[ELLA].goals[GoalId("ser_madre")] is GoalStatus.LOCKED
    assert not sim.log.of_kind(EventKind.GOAL_FAILED)


def test_a_deadline_that_expires_before_you_can_start_does_not_load() -> None:
    """Se quedaría LOCKED para siempre, el plazo ni siquiera correría, y no
    pasaría nada nunca — el peor de los contenidos muertos, porque ni falla."""
    with pytest.raises(ValidationError, match="nunca llegaría a estar activa"):
        nacer_pack(**{"agents": [
            {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
             "edad_inicial": 10_000, "traits": {"varon": 1.0}},
            {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
             "edad_inicial": 0, "traits": {"mujer": 1.0},
             "goals": [{"id": "ser_madre", "label": "ser madre", "need": "vinculo",
                        "at_kin": {"madre": 1}, "requires_edad": 5000,
                        "deadline": 400}]},
        ]})


def test_the_newborn_is_born_wanting_nothing() -> None:
    pack = buscado_pack("ella", **{"situations": [
        {"id": "prenada", "label": "prenada", "personal": True,
         "al_expirar": {
             "goals": ["ser_madre"],
             "sortea_traits": [["varon", "mujer"]],
             "relacion_con_portador": "hijo_de_portadora",
             "relacion_con_causante": "hijo_de_causante",
         }},
    ], "agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0},
         "goals": [{"id": "ser_madre", "label": "ser madre", "need": "vinculo",
                    "at_kin": {"madre": 1}, "requires_edad": 5000}]},
    ]})
    sim, nacido = parir(pack)
    cria = sim.state.agents[nacido]
    assert cria.goals[GoalId("ser_madre")] is GoalStatus.LOCKED
    assert cria.pursuing(pack) == ()


# --- lazos que nacen de algo que alguien hizo (D-082) --------------------------


def apadrinar_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "relations": [
            {"id": "hijo_de_portadora", "label": "hijo de", "inverse": "madre"},
            {"id": "madre", "label": "madre", "inverse": "hijo_de_portadora"},
            {"id": "hijo_de_causante", "label": "hijo de", "inverse": "padre"},
            {"id": "padre", "label": "padre", "inverse": "hijo_de_causante"},
            {"id": "padrino", "label": "padrino de", "inverse": "ahijado"},
            {"id": "ahijado", "label": "ahijado de", "inverse": "padrino"},
        ],
        "actions": [
            {"id": "engendrar", "label": "apadrinar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
             "target": {"gives": {"vinculo": 0.10}, "crea_relacion": "padrino"}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return nacer_pack(**data)


def test_an_action_can_tie_a_bond_that_was_not_in_the_pack() -> None:
    """`begin_relation` existía desde la capa relacional y ningún contenido la
    llamaba: los lazos de un mundo se decidían en el tick 0."""
    sim = Simulation(apadrinar_pack(), seed=1)
    sim.run(4)
    padrinos = [
        (quien, sorted(a.relations.get(RelationId("padrino"), ())))
        for quien, a in sorted(sim.state.agents.items())
        if a.relations.get(RelationId("padrino"))
    ]
    assert padrinos, "nadie apadrinó a nadie"
    quien, ahijados = padrinos[0]
    # Y el otro lado lo puso `inverse`, sin declarar nada más.
    assert quien in sim.state.agents[ahijados[0]].relations[RelationId("ahijado")]


def test_tying_a_bond_twice_is_silent() -> None:
    sim = Simulation(apadrinar_pack(), seed=1)
    sim.run(30)
    for agente in sim.state.agents.values():
        for quienes in agente.relations.values():
            assert len(quienes) == len(set(quienes))


def test_an_exclusive_bond_that_is_taken_is_left_alone() -> None:
    """Cambiar de pareja no puede ser el efecto colateral de una acción que
    hablaba de otra cosa, y romper un lazo es una decisión que este motor
    todavía no ha tomado."""
    pack = apadrinar_pack(**{"relations": [
        {"id": "hijo_de_portadora", "label": "hijo de", "inverse": "madre"},
        {"id": "madre", "label": "madre", "inverse": "hijo_de_portadora"},
        {"id": "hijo_de_causante", "label": "hijo de", "inverse": "padre"},
        {"id": "padre", "label": "padre", "inverse": "hijo_de_causante"},
        {"id": "padrino", "label": "padrino de", "symmetric": True, "exclusive": True},
    ], "actions": [
        {"id": "engendrar", "label": "apadrinar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_company": 1,
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.30},
         "target": {"gives": {"vinculo": 0.10}, "crea_relacion": "padrino"}},
        {"id": "nada", "label": "nada", "duration_ticks": 1},
    ], "agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0},
         "relations": {"padrino": ["otro"]}},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0}},
        {"id": "otro", "label": "Otro", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0}},
    ]})
    sim = Simulation(pack, seed=1)
    sim.run(20)
    assert sim.state.agents[EL].relations[RelationId("padrino")] == {OTRO}


def test_a_bond_tied_in_play_makes_an_at_kin_goal_reachable() -> None:
    """El validador rechazaba toda meta `at_kin` no cumplida porque nada anudaba
    lazos en marcha. Ahora comprueba que ALGO pueda anudar esa relación."""
    apadrinar_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"varon": 1.0},
         "goals": [{"id": "tener_ahijado", "label": "tener un ahijado",
                    "need": "vinculo", "at_kin": {"padrino": 1}}]},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 10_000, "traits": {"mujer": 1.0}},
    ]})


def test_a_goal_about_a_bond_nothing_can_tie_still_does_not_load() -> None:
    """La mitad del aviso que sigue en pie: si nada del pack anuda esa relación,
    la meta no se puede cumplir y es contenido muerto igual que antes."""
    with pytest.raises(ValidationError, match="anuda"):
        apadrinar_pack(**{"relations": [
            {"id": "hijo_de_portadora", "label": "hijo de", "inverse": "madre"},
            {"id": "madre", "label": "madre", "inverse": "hijo_de_portadora"},
            {"id": "hijo_de_causante", "label": "hijo de", "inverse": "padre"},
            {"id": "padre", "label": "padre", "inverse": "hijo_de_causante"},
            {"id": "padrino", "label": "padrino de", "inverse": "ahijado"},
            {"id": "ahijado", "label": "ahijado de", "inverse": "padrino"},
            {"id": "rival", "label": "rival", "symmetric": True},
        ], "agents": [
            {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
             "edad_inicial": 10_000, "traits": {"varon": 1.0},
             "goals": [{"id": "tener_rival", "label": "tener un rival",
                        "need": "vinculo", "at_kin": {"rival": 1}}]},
            {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
             "edad_inicial": 10_000, "traits": {"mujer": 1.0}},
        ]})


# --- la vejez (D-084) ----------------------------------------------------------
#
# El quinto sitio del motor que pega una condición, y el único sin autor: los
# otros cuatro salen de una acción, de una situación del mundo, de lo que otro te
# hace, o de nacer. Esto sale de estar vivo.
#
# Y lo que la hace algo más que un reloj: no le cae igual a todo el mundo, y la
# diferencia es lo que HICISTE con tu vida, no con lo que naciste. Un rango solo
# se rompe trabajando el eje.

VEJEZ = SituationId("vejez")


def vejez_pack(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "needs": [
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.2},
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0,
             "initial": 1.0, "lethal_after": 8},
            {"id": "dominio", "label": "dominio", "decay_per_tick": 0.0,
             "initial": 0.0, "progression": True, "rank_slowdown": 1.0, "cap": 0.5},
        ],
        "situations": [
            {"id": "vejez", "label": "viejo", "personal": True,
             "desde_edad": 10_000,
             "gravedad_por_rango": {"dominio": 0.5},
             "effects": {"salud": -0.01}},
        ],
        "actions": [
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "agents": [
            {"id": "el", "label": "Viejo", "home": "p1", "start_at": "p1",
             "edad_inicial": 20_000},
            {"id": "ella", "label": "Joven", "home": "p1", "start_at": "p1",
             "edad_inicial": 100},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return nacer_pack(**data)


def test_old_age_arrives_without_anyone_causing_it() -> None:
    sim = Simulation(vejez_pack(), seed=1)
    sim.run(1)
    assert sim.state.agents[EL].lleva(VEJEZ)
    assert not sim.state.agents[ELLA].lleva(VEJEZ)


def test_whoever_was_already_old_gets_it_on_the_first_tick() -> None:
    """Un pack no declara a un anciano diciendo que es joven."""
    sim = Simulation(vejez_pack(), seed=1)
    sim.run(1)
    empezó = sim.log.of_kind(EventKind.SITUATION_BEGAN)
    assert [e.data["porque"] for e in empezó if e.actor == EL] == ["edad"]


def test_it_arrives_by_itself_when_the_age_comes() -> None:
    sim = Simulation(vejez_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 9_980},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 100},
    ]}), seed=1)
    sim.run(5)
    assert not sim.state.agents[EL].lleva(VEJEZ)
    sim.run(30)
    assert sim.state.agents[EL].lleva(VEJEZ)


def test_growing_old_happens_once_and_not_every_tick() -> None:
    """`afligir` AGRAVA cuando le llega una idéntica, así que sin la guarda
    envejecer sería envejecer un poco más cada tick: a los cien ticks de cumplir
    la edad, la gravedad sería cien."""
    sim = Simulation(vejez_pack(), seed=1)
    sim.run(40)
    cond = [c for c in sim.state.agents[EL].condiciones if c.situacion == VEJEZ]
    assert len(cond) == 1
    assert cond[0].gravedad == pytest.approx(1.0)


def test_having_gone_far_softens_it() -> None:
    """Y divide en vez de restar: llegar lejos no hace a nadie inmortal, lo hace
    envejecer más despacio."""
    sim = Simulation(vejez_pack(**{"agents": [
        {"id": "el", "label": "El", "home": "p1", "start_at": "p1",
         "edad_inicial": 9_990},
        {"id": "ella", "label": "Ella", "home": "p1", "start_at": "p1",
         "edad_inicial": 100},
    ]}), seed=1)
    sim.state.agents[EL].rango[NeedId("dominio")] = 6
    sim.run(30)
    cond = next(c for c in sim.state.agents[EL].condiciones if c.situacion == VEJEZ)
    # 1 / (1 + 0.5 * 6)
    assert cond.gravedad == pytest.approx(0.25)


def test_the_sedentary_one_dies_first() -> None:
    """La frase entera del mecanismo, medida: dos personas de la misma edad, una
    con rangos y otra sin ellos, y la vida que les queda no es la misma."""
    def hasta_morir(rango: int) -> int:
        sim = Simulation(vejez_pack(), seed=1)
        sim.state.agents[EL].rango[NeedId("dominio")] = rango
        for tick in range(1, 4000):
            sim.run(1)
            if EL not in sim.state.agents:
                return tick
        return 4000

    sedentario = hasta_morir(0)
    veterano = hasta_morir(8)
    assert sedentario < veterano, "el rango no alargó ni un tick"
    assert veterano > sedentario * 2


def test_what_you_do_after_does_not_undo_the_years() -> None:
    """La gravedad se calcula UNA vez, al pegarse: lo que fuiste hasta entonces
    decide cómo envejeces."""
    sim = Simulation(vejez_pack(), seed=1)
    sim.run(2)
    sim.state.agents[EL].rango[NeedId("dominio")] = 20
    sim.run(20)
    cond = next(c for c in sim.state.agents[EL].condiciones if c.situacion == VEJEZ)
    assert cond.gravedad == pytest.approx(1.0)


def test_an_age_that_the_world_cannot_have_does_not_load() -> None:
    with pytest.raises(ValidationError, match="no es `personal`"):
        vejez_pack(**{"situations": [
            {"id": "vejez", "label": "viejo", "desde_edad": 10_000,
             "effects": {"salud": -0.01}},
        ]})


def test_softening_by_an_axis_without_ranks_does_not_load() -> None:
    """Sin rangos el número nunca sube, así que la gravedad sería la misma para
    todo el mundo y el campo estaría mintiendo."""
    with pytest.raises(ValidationError, match="no tiene"):
        vejez_pack(**{"situations": [
            {"id": "vejez", "label": "viejo", "personal": True,
             "desde_edad": 10_000,
             "gravedad_por_rango": {"vinculo": 0.5},
             "effects": {"salud": -0.01}},
        ]})
