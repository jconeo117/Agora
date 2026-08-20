"""Acciones con destinatario: la mitad que le faltaba a la capa social.

Hasta aquí `satisfies`, `effects` y `costs` caían **siempre** sobre quien actúa.
El motor eran ciento veintisiete personas actuando sobre sí mismas en presencia
de otras. `requires_company` y `requires_relation` parecen sociales y no lo son:
son puertas, dicen quién tiene que ESTAR, no a quién le pasa nada.

Eso dejaba cuatro cosas sin poder escribirse, y las cuatro se habían pedido:

    curar a un herido que no puede curarse solo
    que un recuerdo vaya sobre alguien   (`about` salía al 0 % medido)
    que un rumor lleve noticias de personas y no expectativas
    que exista el rencor hacia alguien

**Y el motor no necesita saber qué es el altruismo.** Ayudar paga lo que el pack
diga: la acción satisface algo de QUIEN ACTÚA, y por eso se hace. Un motor de
utilidad no necesita una primitiva para la generosidad — necesita que la
generosidad tenga precio y premio, como todo lo demás.

Dos decisiones que abaratan el mecanismo, y las dos se sostienen sin el
argumento del coste:

- **El destinatario se elige donde estás.** Meterlo en la deliberación
  multiplicaría el espacio por la población, pero es que además sería falso: no
  puedes saber que alguien sangra desde el otro lado del pueblo.
- **El aprecio encoge la recompensa, no la veta.** Es la respuesta literal a
  *poco probable, no completamente improbable*: a un mendigo herido se le ayuda
  cuando no hay nada mejor que hacer.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.agents.decide import candidates
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.state import PerformingAction
from agora.engine.world import Simulation

SANADOR = AgentId("sanador")
HERIDO = AgentId("herido")
OTRO = AgentId("otro")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
SANGRE = NeedId("sangre")
VINCULO = NeedId("vinculo")
HERIDA = SituationId("herida")
CURAR = ActionId("curar")


def dirigido_pack(**overrides: Any) -> ContentPack:
    """Curar a otro paga en `vinculo`: así es como el altruismo tiene premio sin
    que el motor sepa qué es."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "sangre", "label": "sangre", "decay_per_tick": 0.0,
             "initial": 1.0, "lethal_after": 8},
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.3},
        ],
        "situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.05}},
        ],
        "actions": [
            {"id": "curar", "label": "curar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
             "target": {"cures": ["herida"], "gives": {"sangre": 0.30},
                        "requires_condition": "herida"}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"],
             "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["sitio"],
             "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "sanador", "label": "Sanador", "home": "p1",
             "start_at": "p1"},
            {"id": "herido", "label": "Herido", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 20, "memory_scale": 1.0,
                   "bond_rate": 0.3, "bond_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


# --- lo que el pack puede declarar -------------------------------------------


def test_pointing_at_someone_without_doing_anything_is_dead_content() -> None:
    """Sale en el log, se elige un destinatario, y no pasa nada. Igual que una
    situación que no multiplica nada."""
    with pytest.raises(ValueError, match="no le hace nada"):
        dirigido_pack(**{"actions": [
            {"id": "curar", "label": "curar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
             "target": {}},
            {"id": "nada", "label": "nada", "duration_ticks": 1}]})


def test_a_targeted_action_must_ask_for_company() -> None:
    """Sin exigirlo sería elegible a solas y se caería en la puerta de
    destinatario cada vez. Que lo diga el pack es más barato y más honesto."""
    with pytest.raises(ValueError, match="no exige compañía"):
        dirigido_pack(**{"actions": [
            {"id": "curar", "label": "curar", "duration_ticks": 1,
             "requires_affordance": "sitio",
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
             "target": {"gives": {"sangre": 0.30}}},
            {"id": "nada", "label": "nada", "duration_ticks": 1}]})


def test_you_cannot_inflict_the_weather_on_someone() -> None:
    with pytest.raises(ValueError, match=r"target\.inflicts.*no es una situación personal"):
        dirigido_pack(**{
            "situations": [
                {"id": "herida", "label": "herida", "personal": True,
                 "effects": {"sangre": -0.05}},
                {"id": "invierno", "label": "invierno",
                 "effects": {"sangre": -0.001}}],
            "actions": [
                {"id": "curar", "label": "curar", "duration_ticks": 1,
                 "requires_affordance": "sitio", "requires_company": 1,
                 "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
                 "target": {"inflicts": {"situation": "invierno"}}},
                {"id": "nada", "label": "nada", "duration_ticks": 1}]})


# --- a quién ------------------------------------------------------------------


def test_help_reaches_the_one_who_needs_it() -> None:
    """La puerta objetiva: solo vale sobre quien lleva la condición. Una herida
    **se ve** cuando estás delante; el valor exacto de sus necesidades, no."""
    sim = Simulation(dirigido_pack(), seed=1)
    sim.afligir(HERIDO, HERIDA, marca="brazo")
    sim.run(30)

    assert not sim.state.agents[HERIDO].condiciones, "nadie lo curó"


def test_nobody_is_healed_who_is_not_hurt() -> None:
    sim = Simulation(dirigido_pack(), seed=1)
    sim.run(30)
    assert not sim.log.of_kind(EventKind.ACTION_COMPLETED) or all(
        e.action != CURAR for e in sim.log.of_kind(EventKind.ACTION_COMPLETED)
    )


def test_you_help_the_one_you_care_most_about() -> None:
    """El filtro es objetivo y el desempate subjetivo. Al revés —ordenar por
    quién está peor— obligaría a leer la ficha interna de todo el mundo."""
    pack = dirigido_pack(**{"agents": [
        {"id": "sanador", "label": "Sanador", "home": "p1", "start_at": "p1"},
        {"id": "herido", "label": "Herido", "home": "p1", "start_at": "p1"},
        {"id": "otro", "label": "Otro", "home": "p1", "start_at": "p1"},
    ]})
    sim = Simulation(pack, seed=1)
    sim.afligir(HERIDO, HERIDA)
    sim.afligir(OTRO, HERIDA)
    for t in range(40):
        sim.state.agents[SANADOR].meet(OTRO, tick=t)
        sim.state.agents[SANADOR].remember_company([OTRO], premium=0.6,
                                                   rate=0.4, tick=t)

    elegido = sim.state.agents[SANADOR].elegir_destinatario(
        [sim.state.agents[HERIDO], sim.state.agents[OTRO]],
        pack.action_by_id[CURAR].target,  # type: ignore[arg-type]
    )
    assert elegido is not None and elegido.spec_id == OTRO


def test_you_cannot_help_someone_across_town() -> None:
    """No se puede saber que alguien sangra desde el otro lado del pueblo. La
    acción dirigida solo es candidata donde el agente está.

    Se mira la lista de candidatos y no el resultado de correr el mundo: los dos
    se mueven, así que dejarlos sueltos treinta ticks solo comprueba que acaban
    coincidiendo. La primera versión de este test hacía eso y fallaba con razón.
    """
    sim = Simulation(dirigido_pack(), seed=1)
    sim.state.agents[HERIDO].at = P2
    sim.afligir(HERIDO, HERIDA)

    opciones = candidates(sim.state, sim.state.agents[SANADOR])
    assert not [d for d in opciones if d.action == CURAR], "lo vio desde P1"

    sim.state.agents[HERIDO].at = P1
    opciones = candidates(sim.state, sim.state.agents[SANADOR])
    assert [d for d in opciones if d.action == CURAR], "teniéndolo delante, sí"


def test_walking_off_mid_bandage_means_no_bandage() -> None:
    """Se comprueba que siga delante, no que siga existiendo. Es la misma
    verdad-en-la-mano que el chasco de llegada, en el otro extremo."""
    pack = dirigido_pack(**{"actions": [
        {"id": "curar", "label": "curar", "duration_ticks": 4,
         "requires_affordance": "sitio", "requires_company": 1,
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
         "target": {"cures": ["herida"], "gives": {"sangre": 0.30},
                    "requires_condition": "herida"}},
        {"id": "nada", "label": "nada", "duration_ticks": 1}]})
    sim = Simulation(pack, seed=1)
    sim.afligir(HERIDO, HERIDA)
    sim.run(1)
    curando = sim.state.agents[SANADOR].busy
    assert isinstance(curando, PerformingAction) and curando.target == HERIDO

    # Se marcha a mitad del vendaje, y se le retiene fuera hasta que termine.
    for _ in range(6):
        sim.state.agents[HERIDO].at = P2
        sim.run(1)

    assert sim.state.agents[HERIDO].lleva(HERIDA), "lo curó desde otro sitio"


# --- el mendigo ---------------------------------------------------------------


def test_a_stranger_is_helped_less_eagerly_but_not_never() -> None:
    """**La regla del mendigo, y la razón de que `regard_weight` encoja en vez de
    vetar.**

    Lo que se pidió fue *poco probable, no completamente improbable*. Una puerta
    dura lo haría imposible; encoger la recompensa hace que ocurra cuando no hay
    nada mejor que hacer, que es exactamente lo que le pasa a un herido en una
    calle con gente ocupada.
    """
    pack = dirigido_pack(**{"actions": [
        {"id": "curar", "label": "curar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_company": 1,
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
         "target": {"cures": ["herida"], "gives": {"sangre": 0.30},
                    "requires_condition": "herida", "regard_weight": 1.0}},
        {"id": "nada", "label": "nada", "duration_ticks": 1}]})
    destino = pack.action_by_id[CURAR].target
    assert destino is not None

    sim = Simulation(pack, seed=1)
    sanador = sim.state.agents[SANADOR]

    a_un_extranyo = sanador.disposicion(HERIDO, destino)
    for t in range(40):
        sanador.meet(HERIDO, tick=t)
        sanador.remember_company([HERIDO], premium=0.6, rate=0.4, tick=t)
    a_un_querido = sanador.disposicion(HERIDO, destino)

    assert a_un_extranyo == 0.0, "con peso 1.0 un extraño no compensa nada"
    assert a_un_querido > 0.0, "a quien se aprecia, sí"


def test_a_service_pays_the_same_to_everyone() -> None:
    """Con `regard_weight` a 0 se comporta como un servicio: vender pan a un
    extraño paga lo mismo que vendérselo a tu hermano."""
    pack = dirigido_pack()
    destino = pack.action_by_id[CURAR].target
    assert destino is not None
    sim = Simulation(pack, seed=1)
    assert sim.state.agents[SANADOR].disposicion(HERIDO, destino) == 1.0


def test_the_loved_one_is_helped_sooner_and_oftener_than_the_beggar() -> None:
    """**El escenario entero, de una pieza.** Mismo mundo, misma herida, misma
    semilla. Lo único que cambia es si alguien le tiene aprecio.

    Es la mitad social de la regla pedida: *si los de alrededor están dispuestos
    a ayudarlo*. La otra mitad —*si tiene capacidad de curarse solo*— ya tenía
    test desde las condiciones.

    **Y hace falta que la calle esté ocupada**, que es la parte que la primera
    versión de este test se dejó. Sin un `trabajar` que compita, las dos únicas
    acciones del mundo son curar y nada, así que *no hay nada mejor que hacer*
    es cierto siempre y hasta el mendigo recibe ayuda. El motor hacía lo
    correcto y el escenario era mío: `regard_weight` no impide ayudar, hace que
    ayudar pierda contra cualquier otra cosa que sí compense.

    **Y se mide la prontitud, no la muerte**, que fue el segundo intento fallido.
    Medido en este mundo: al mendigo lo atienden en el tick 10 y al querido en el
    3, cuatro veces frente a dos. Esa es la garantía del motor. Que la diferencia
    entre esperar diez ticks y esperar tres sea la diferencia entre vivir y
    morir depende de lo deprisa que sangre uno, y eso lo escribe el pack —
    apretar este mundo de juguete hasta que salga un muerto sería calibrar el
    entorno para que el motor luzca, que es exactamente lo que no se hace aquí.
    """
    pack = dirigido_pack(**{
        "needs": [
            {"id": "sangre", "label": "sangre", "decay_per_tick": 0.0,
             "initial": 1.0, "lethal_after": 8},
            {"id": "vinculo", "label": "vinculo", "decay_per_tick": 0.02,
             "initial": 0.3},
            {"id": "dinero", "label": "dinero", "decay_per_tick": 0.05,
             "initial": 0.3},
        ],
        "actions": [
            {"id": "curar", "label": "curar", "duration_ticks": 1,
             "requires_affordance": "sitio", "requires_company": 1,
             "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
             "target": {"cures": ["herida"], "gives": {"sangre": 0.30},
                        "requires_condition": "herida", "regard_weight": 1.0}},
            {"id": "trabajar", "label": "trabajar", "duration_ticks": 1,
             "requires_affordance": "sitio", "satisfies": {"dinero": 1.0},
             "effects": {"dinero": 0.15}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ]})

    solo = Simulation(pack, seed=4)
    solo.afligir(HERIDO, HERIDA, marca="torso")
    solo.run(60)

    querido = Simulation(pack, seed=4)
    for t in range(40):
        querido.state.agents[SANADOR].meet(HERIDO, tick=t)
        querido.state.agents[SANADOR].remember_company([HERIDO], premium=0.6,
                                                       rate=0.4, tick=t)
    querido.afligir(HERIDO, HERIDA, marca="torso")
    querido.run(60)

    def atenciones(sim: Simulation) -> list[int]:
        return [
            e.tick
            for e in sim.log.of_kind(EventKind.ACTION_COMPLETED)
            if e.action == CURAR and e.actor == SANADOR
        ]

    al_mendigo, al_querido = atenciones(solo), atenciones(querido)
    assert al_mendigo and al_querido, "a alguno no lo atendieron nunca"
    assert al_querido[0] < al_mendigo[0], "al querido lo atienden antes"
    assert len(al_querido) > len(al_mendigo), "y más veces"


# --- lo que desbloquea --------------------------------------------------------


def test_what_someone_does_to_you_is_remembered_with_a_name() -> None:
    """**El campo que la medición encontró al 0 %.** Sin `about`, `duelo()` no
    tenía de qué alimentarse y los rumores solo podían llevar expectativas."""
    sim = Simulation(dirigido_pack(), seed=1)
    sim.afligir(HERIDO, HERIDA)
    sim.run(30)

    sobre_alguien = [r for r in sim.state.memoria.de(HERIDO) if r.about is not None]
    assert sobre_alguien, "lo que le hicieron no dejó nombre"
    assert sobre_alguien[0].about == SANADOR


def test_being_helped_is_filed_as_something_that_happened_to_you() -> None:
    """Lo que te hacen no lo decidiste tú, así que no puede ensuciar tus
    creencias sobre lo que rinde cada acción."""
    sim = Simulation(dirigido_pack(), seed=1)
    sim.afligir(HERIDO, HERIDA)
    sim.run(30)
    assert sim.state.memoria.rencor(HERIDO, sim.state.tick, escala=1.0) == {}


def test_hurting_is_giving_with_the_sign_flipped() -> None:
    """No hace falta una primitiva para agredir: quitarle sangre a alguien es lo
    mismo que darle de comer, con el signo cambiado."""
    pack = dirigido_pack(**{"actions": [
        {"id": "curar", "label": "curar", "duration_ticks": 1,
         "requires_affordance": "sitio", "requires_company": 1,
         "satisfies": {"vinculo": 1.0}, "effects": {"vinculo": 0.20},
         "target": {"gives": {"sangre": -0.30},
                    "inflicts": {"situation": "herida", "marca": "torso"}}},
        {"id": "nada", "label": "nada", "duration_ticks": 1}]})
    sim = Simulation(pack, seed=1)
    sim.run(4)

    victima = sim.state.agents[HERIDO]
    assert victima.needs[SANGRE] < 1.0
    assert victima.lleva(HERIDA)


def test_a_pack_without_targets_pays_nothing_for_this() -> None:
    """Estrenar esto no puede mover ningún contrato ya medido: sin acciones
    dirigidas ni siquiera se construye la lista de presentes."""
    pack = dirigido_pack(**{"actions": [
        {"id": "descansar", "label": "descansar", "duration_ticks": 1,
         "requires_affordance": "sitio", "satisfies": {"vinculo": 1.0},
         "effects": {"vinculo": 0.20}},
        {"id": "nada", "label": "nada", "duration_ticks": 1}]})
    assert all(a.target is None for a in pack.actions)
    sim = Simulation(pack, seed=1)
    sim.run(50)
    assert len(sim.state.agents) == 2
