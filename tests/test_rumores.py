"""Los rumores: un recuerdo que se copia, rebajado, y pesado por quien lo oye.

**Lo que costó decidir no fue el mecanismo, fue qué se cuenta.** La frase del
plan —*un rumor es un recuerdo que se copia*— resultó ser literal: mover un
`Recuerdo` de una cabeza a otra no necesita primitiva nueva. Lo que hubo que
medir tres veces fue qué merece contarse.

    ciudad, 21 días, 127 agentes, 5 080 recuerdos

    el 48% de lo que A recuerda, B no lo sabe        ← hay novedad de sobra
    0 parejas sin nada nuevo que contarse

    si cada cual cuenta su recuerdo MÁS SALIENTE:
        6 historias distintas · 51 personas dirían "cené en la taberna"
    si cuenta el que más le SORPRENDIÓ:
        20 historias distintas

`importancia_de` mezcla la urgencia del momento, y la urgencia es vívida para
quien la vive y aburrida para quien la oye. La sorpresa ya estaba guardada
aparte —`valencia` es el error de predicción con signo— y es la que separa una
noticia de una anécdota.

**Y una limitación medida que conviene tener escrita.** El motor no produce hoy
ni un solo hecho social: `ENCOUNTER` se emite y no llega a la memoria,
`RELATION_BEGAN` y `AGENT_DIED` son solo API, y los tres sitios que graban
recuerdos graban *lo que me pasó a mí*. Por eso `about` sale al 0% en los dos
mundos grandes. Los rumores llevan hoy **expectativas ajenas** —*la taberna
estaba vacía*— y llevarán noticias de personas en cuanto algo las produzca. La
misma primitiva, dos cargas.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.events import Event, EventKind
from agora.engine.memory import MemoriaEpisodica
from agora.engine.ontology import ActionId, AgentId, PlaceId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
AG3 = AgentId("ag3")
IDOLO = AgentId("idolo")
P1 = PlaceId("p1")
CHARLAR = ActionId("charlar")


def rumor_pack(**overrides: Any) -> ContentPack:
    """Tres personas en un sitio, y charlar es una acción compartida."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "compania", "label": "compania", "decay_per_tick": 0.03,
             "initial": 0.4},
        ],
        "actions": [
            {"id": "charlar", "label": "charlar", "duration_ticks": 1,
             "requires_affordance": "sitio", "satisfies": {"compania": 1.0},
             "effects": {"compania": 0.15},
             "effects_per_company": {"compania": 0.10}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"],
             "neighbors": {}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 30, "memory_fade": 1.0,
                   "memory_scale": 1.0, "bond_rate": 0.3, "bond_scale": 1.0,
                   "rumor_rate": 1.0, "rumor_decay": 0.5},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def hecho(seq: int, tick: int, quien: AgentId, *, about: AgentId | None = None,
          action: ActionId | None = None) -> Event:
    return Event(seq=seq, tick=tick, kind=EventKind.ACTION_COMPLETED,
                 actor=quien, place=P1, action=action, subject=about)


# --- qué se cuenta -----------------------------------------------------------


def test_routine_is_not_news() -> None:
    """Lo que salió como se esperaba tiene valencia 0.0 y no se cuenta. En la
    ciudad es un tercio de la memoria, y es correcto que no sea noticia."""
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(1, 0, AG1), importancia=0.9, valencia=0.0)
    assert memoria.contable(AG1, 0) is None


def test_you_tell_what_surprised_you_not_what_pressed_you() -> None:
    """**La decisión que salió de medir.** El recuerdo más importante y el más
    contable son distintos, y con el ranking por importancia salían seis
    historias en toda la ciudad."""
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(1, 0, AG1), importancia=0.95, valencia=0.05)
    memoria.remember(AG1, hecho(2, 0, AG1), importancia=0.30, valencia=0.90)

    contable = memoria.contable(AG1, 0)
    assert contable is not None and contable.seq == 2


def test_with_nothing_to_tell_you_say_nothing() -> None:
    assert MemoriaEpisodica(capacidad=30).contable(AG1, 0) is None


# --- la copia ----------------------------------------------------------------


def test_a_rumour_keeps_the_seq_so_you_know_you_know_it() -> None:
    """El `seq` es único y no se reutiliza, así que *¿ya me sé esto?* es comparar
    enteros. Sin eso haría falta una igualdad entre recuerdos."""
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.5, valencia=-0.8)
    historia = memoria.contable(AG1, 0)
    assert historia is not None

    assert not memoria.sabe(AG2, 7)
    assert memoria.oir(AG2, historia, importancia=0.25)
    assert memoria.sabe(AG2, 7)


def test_hearsay_is_marked_as_such() -> None:
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.5, valencia=-0.8)
    historia = memoria.contable(AG1, 0)
    assert historia is not None and historia.de_oidas == 0

    memoria.oir(AG2, historia, importancia=0.25)
    assert memoria.de(AG2)[0].de_oidas == 1


def test_the_chain_keeps_counting_mouths() -> None:
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.5, valencia=-0.8)
    memoria.oir(AG2, memoria.de(AG1)[0], importancia=0.25)
    memoria.oir(AG3, memoria.de(AG2)[0], importancia=0.12)
    assert memoria.de(AG3)[0].de_oidas == 2


def test_an_old_rumour_arrives_already_faded() -> None:
    """El `tick` no se reescribe: `valor` cuenta desde que PASÓ, no desde que me
    lo dijeron. Sale gratis y es lo que uno esperaría."""
    memoria = MemoriaEpisodica(capacidad=30, fade=0.99)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.8, valencia=-0.8)
    memoria.oir(AG2, memoria.de(AG1)[0], importancia=0.8)

    recien = memoria.de(AG2)[0]
    assert recien.tick == 0
    assert recien.valor(500, 0.99) < 0.01, "llega viejo, no recién estrenado"


def test_a_corner_of_eight_does_not_manufacture_certainty() -> None:
    """No se reescribe lo que ya se sabe. Sin esta guarda, ocho personas
    repitiéndose lo mismo empujarían el rumor hasta el tope — una máquina de
    fabricar certezas en vez de propagarlas."""
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.5, valencia=-0.8)
    historia = memoria.de(AG1)[0]

    assert memoria.oir(AG2, historia, importancia=0.25)
    for _ in range(8):
        assert not memoria.oir(AG2, historia, importancia=0.9)
    assert len(memoria.de(AG2)) == 1
    assert memoria.de(AG2)[0].importancia == pytest.approx(0.25)


def test_living_it_beats_being_told() -> None:
    """Quien estuvo delante no degrada su recuerdo porque se lo cuenten."""
    memoria = MemoriaEpisodica(capacidad=30, fade=1.0)
    memoria.remember(AG1, hecho(7, 0, AG1), importancia=0.9, valencia=-0.8)
    memoria.remember(AG2, hecho(7, 0, AG2), importancia=0.9, valencia=-0.8)

    assert not memoria.oir(AG1, memoria.de(AG2)[0], importancia=0.1)
    assert memoria.de(AG1)[0].importancia == pytest.approx(0.9)
    assert memoria.de(AG1)[0].de_oidas == 0


# --- quién pone el peso ------------------------------------------------------


def test_news_about_nobody_arrives_discounted_by_the_chain() -> None:
    sim = Simulation(rumor_pack(), seed=4)
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, action=CHARLAR),
                               importancia=0.8, valencia=-0.9)
    sim.run(6)

    oidos = [r for r in sim.state.memoria.de(AG2) if r.seq == 1]
    assert oidos, "no le llegó"
    assert oidos[0].importancia == pytest.approx(0.8 * 0.5)


def test_news_about_someone_is_weighed_by_the_listener() -> None:
    """**La petición literal: la noticia se recibe en base a la imagen que uno
    tenía de ese individuo.**

    Que a quien te lo cuenta se le caiga el mundo encima no te obliga a sentir
    nada — y al revés: te enteras de que murió tu ídolo por boca de alguien a
    quien le daba igual, y te destroza igual.
    """
    sim = Simulation(rumor_pack(), seed=4)
    # A ag1 le da igual el ídolo; a ag2 le importa mucho.
    for t in range(50):
        sim.state.agents[AG2].meet(IDOLO, tick=t)
        sim.state.agents[AG2].remember_company([IDOLO], premium=0.6, rate=0.4,
                                               tick=t)
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, about=IDOLO),
                               importancia=0.05, valencia=-0.9)
    sim.run(6)

    oidos = [r for r in sim.state.memoria.de(AG2) if r.seq == 1]
    assert oidos, "no le llegó"
    assert oidos[0].importancia > 0.20, (
        "el peso lo pone quien escucha, no quien cuenta"
    )


def test_gossip_about_a_stranger_does_not_stick() -> None:
    """Si no le suena de nada, se entera y no le mueve un pelo. Guardarlo con
    importancia cero sería ocupar sitio sin ser un recuerdo."""
    sim = Simulation(rumor_pack(), seed=4)
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, about=IDOLO),
                               importancia=0.9, valencia=-0.9)
    sim.run(6)

    assert not [r for r in sim.state.memoria.de(AG2) if r.seq == 1]


def test_news_about_your_own_is_never_gossip_about_a_stranger() -> None:
    """**El mismo arreglo que `morir`, en el otro sitio que lo tenía.**

    Este camino leía `Bond.regard` en crudo igual que la muerte, así que una
    noticia sobre tu pareja pesaba lo que pesaría la de un conocido cualquiera
    de igual trato — y sin trato, nada en absoluto: se descartaba como cotilleo
    sobre un extraño. `regard_floor` es lo que el pack escribió para decir que
    eso no puede pasar.
    """
    pack = rumor_pack(**{
        "relations": [{"id": "pareja", "label": "pareja", "symmetric": True,
                       "regard_floor": 0.45}],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1",
             "relations": {"pareja": ["idolo"]}},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
            {"id": "idolo", "label": "Ausente", "home": "p1",
             "start_at": "p1"},
        ],
    })
    sim = Simulation(pack, seed=4)
    # Cero trato compartido con nadie: el aprecio emergente de ag2 es 0.0.
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, about=IDOLO),
                               importancia=0.05, valencia=-0.9)
    sim.run(6)

    oidos = [r for r in sim.state.memoria.de(AG2) if r.seq == 1]
    assert oidos, "la noticia sobre su pareja no le llegó"
    assert oidos[0].importancia > 0.20


# --- en un mundo corriendo ---------------------------------------------------


def test_off_by_default_changes_nothing() -> None:
    """Como los disparadores y el resto: estrenarlo no puede mover un contrato ya
    medido."""
    pack = rumor_pack(**{"tuning": {"memory_capacity": 30, "memory_fade": 1.0,
                                    "memory_scale": 1.0, "bond_rate": 0.3,
                                    "bond_scale": 1.0}})
    assert pack.tuning.rumor_rate == 0.0
    sim = Simulation(pack, seed=4)
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, action=CHARLAR),
                               importancia=0.8, valencia=-0.9)
    sim.run(30)
    assert not [r for r in sim.state.memoria.de(AG2) if r.seq == 1]


def test_what_one_lived_ends_up_known_by_others() -> None:
    sim = Simulation(rumor_pack(), seed=4)
    sim.state.memoria.remember(AG1, hecho(1, 0, AG1, action=CHARLAR),
                               importancia=0.8, valencia=-0.9)
    sim.run(40)

    quienes = [q for q in (AG2, AG3) if sim.state.memoria.sabe(q, 1)]
    assert quienes, "nadie se enteró de nada en cuarenta ticks de charla"


def test_telling_does_not_break_determinism() -> None:
    """El sorteo lleva narrador y oyente en la clave, así que el orden en que se
    cuentan las cosas no altera ninguna."""
    def correr() -> list[tuple[str, int, int]]:
        sim = Simulation(rumor_pack(), seed=11)
        sim.state.memoria.remember(AG1, hecho(1, 0, AG1, action=CHARLAR),
                                   importancia=0.8, valencia=-0.9)
        sim.run(60)
        return [
            (str(d), r.seq, r.de_oidas)
            for d in sim.state.memoria.duenyos()
            for r in sim.state.memoria.de(d)
        ]

    assert correr() == correr()
