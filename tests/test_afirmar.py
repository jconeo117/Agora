"""Pruebas de afirmar, mentir y preguntar (plan 15b, §B).

Verdad, contradicción, tirada e información.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from agora.agents.decide import options
from agora.cognition.conversa import interpret_said
from agora.engine.events import Event, EventKind
from agora.engine.memory import MemoriaEpisodica
from agora.engine.ontology import (
    ActionId,
    AgentId,
    ClaimKind,
    PlaceId,
    QuestionKind,
    RelationId,
    RelationSpec,
    SocialAct,
    Tone,
)
from agora.engine.outcome import signed_saturation
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider, Outcome
from agora.engine.rng import RngSource
from agora.engine.social import (
    Belief,
    Claim,
    Conversation,
    contradicts,
    trusts,
    truth,
)
from agora.engine.world import Simulation
from agora.play import Recorder, Script, Terminal
from agora.rules.binding import load_binding
from agora.rules.derive import derive
from agora.rules.system import Ruleset, load_ruleset
from agora.rules.world_social import WorldSocial

BASE_RULES = Path("rules/base/rules.yaml")
ISLA_PACK = Path("packs/isla/pack.yaml")
ISLA_BINDING = Path("packs/isla/reglas/base.yaml")


# ==============================================================================
# B.1.1 — La tabla de §A.3, fila a fila: truth y contradicts
# ==============================================================================


def test_tabla_truth_y_contradicts_at() -> None:
    # 1. AT: truth y contradicts caso a caso. Cubre M2 (ignorar avistamientos).
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    world = sim.state
    gara = AgentId("gara_d1")
    renna = AgentId("renna_d1")
    vidan = AgentId("vidan_d1")

    # Colocar a Renna en pedestal_1 y a Gara en pedestal_2
    world.agents[renna].at = PlaceId("pedestal_1")
    world.agents[gara].at = PlaceId("pedestal_2")

    # TRUTH
    # Renna viva en pedestal_1
    assert truth(world, Claim(ClaimKind.AT, renna, PlaceId("pedestal_1"))) is True
    assert truth(world, Claim(ClaimKind.AT, renna, PlaceId("cornucopia"))) is False
    # Renna muerta
    del world.agents[renna]
    assert truth(world, Claim(ClaimKind.AT, renna, PlaceId("pedestal_1"))) is False

    # Restaurar a Renna
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    world = sim.state
    world.agents[renna].at = PlaceId("pedestal_1")
    world.agents[gara].at = PlaceId("pedestal_2")

    # CONTRADICTS
    # Oyente (Gara) en pedestal_2. Afirmación: Vidan en pedestal_2. Vidan no está allí.
    assert world.agents[vidan].at != PlaceId("pedestal_2")
    assert contradicts(world, gara, Claim(ClaimKind.AT, vidan, PlaceId("pedestal_2"))) is True

    # Oyente (Gara) en pedestal_2, sin avistamientos fuera. Afirmación: Vidan en cornucopia.
    world.agents[gara].sightings.clear()
    assert contradicts(world, gara, Claim(ClaimKind.AT, vidan, PlaceId("cornucopia"))) is False

    # Avistamiento dentro de sighting_horizon (192 en isla) en otro sitio más reciente (Cubre M2)
    world.tick = 10
    world.agents[gara].sightings[PlaceId("pedestal_1")] = (8, frozenset({vidan}))
    # Afirmar que Vidan está en cornucopia choca con el avistamiento reciente en pedestal_1
    assert contradicts(world, gara, Claim(ClaimKind.AT, vidan, PlaceId("cornucopia"))) is True

    # Si además Gara recuerda la muerte de Vidan
    world.agents[gara].sightings.clear()
    evento_muerte = sim.log.emit(
        tick=5, kind=EventKind.AGENT_DIED, actor=vidan, place=PlaceId("cornucopia"), subject=vidan
    )
    sim.state.memoria.remember(gara, evento_muerte, 0.8, -0.9)
    assert contradicts(world, gara, Claim(ClaimKind.AT, vidan, PlaceId("cornucopia"))) is True


def test_tabla_truth_y_contradicts_alive_dead() -> None:
    # 2. ALIVE y DEAD: truth y contradicts caso a caso.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    world = sim.state
    gara = AgentId("gara_d1")
    renna = AgentId("renna_d1")

    # ALIVE: verdad si vivo
    assert truth(world, Claim(ClaimKind.ALIVE, renna)) is True
    # ALIVE: contradice si el oyente recuerda su muerte
    assert contradicts(world, gara, Claim(ClaimKind.ALIVE, renna)) is False
    ev = sim.log.emit(
        tick=1, kind=EventKind.AGENT_DIED, actor=renna, place=PlaceId("cornucopia"), subject=renna
    )
    sim.state.memoria.remember(gara, ev, 0.8, -0.9)
    assert contradicts(world, gara, Claim(ClaimKind.ALIVE, renna)) is True

    # Matar a Renna del mundo
    del world.agents[renna]
    assert truth(world, Claim(ClaimKind.ALIVE, renna)) is False

    # DEAD: verdad si en censo y no vivo
    assert truth(world, Claim(ClaimKind.DEAD, renna)) is True

    # Para alguien vivo, DEAD es falso
    assert truth(world, Claim(ClaimKind.DEAD, gara)) is False

    # DEAD contradice si el oyente lo tiene delante ahora mismo
    vidan = AgentId("vidan_d1")
    world.agents[gara].at = PlaceId("pedestal_2")
    world.agents[vidan].at = PlaceId("pedestal_1")
    # No están en el mismo sitio
    assert contradicts(world, gara, Claim(ClaimKind.DEAD, vidan)) is False
    # Están en el mismo sitio
    world.agents[vidan].at = PlaceId("pedestal_2")
    assert contradicts(world, gara, Claim(ClaimKind.DEAD, vidan)) is True


def test_tabla_truth_y_contradicts_harmed() -> None:
    # 3. HARMED: truth y contradicts caso a caso. Cubre M3 (truth HARMED: de_oidas).
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    world = sim.state
    gara = AgentId("gara_d1")
    renna = AgentId("renna_d1")
    vidan = AgentId("vidan_d1")

    # Víctima muerta -> None
    del world.agents[renna]
    assert truth(world, Claim(ClaimKind.HARMED, vidan, victim=renna)) is None

    # Restaurar
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    world = sim.state

    # Víctima (Renna) tiene un recuerdo de daño vivido (de_oidas == 0) de Vidan
    ev1 = sim.log.emit(
        tick=2,
        kind=EventKind.ACTION_COMPLETED,
        actor=vidan,
        action=ActionId("atacar"),
        place=PlaceId("cornucopia"),
        subject=renna,
    )
    sim.state.memoria.remember(renna, ev1, 0.8, -0.8, por_quien=vidan)
    assert truth(world, Claim(ClaimKind.HARMED, vidan, victim=renna)) is True
    assert truth(world, Claim(ClaimKind.HARMED, gara, victim=renna)) is False

    # Cubre M3: si la víctima solo tiene recuerdo de oídas (de_oidas > 0), truth debe ser False
    ev2 = sim.log.emit(
        tick=3,
        kind=EventKind.ACTION_COMPLETED,
        actor=gara,
        action=ActionId("atacar"),
        place=PlaceId("cornucopia"),
        subject=renna,
    )
    rec_base = sim.state.memoria.remember(vidan, ev2, 0.8, -0.8, por_quien=gara)
    assert rec_base is not None
    sim.state.memoria.oir(renna, rec_base, 0.5)
    # Renna tiene recuerdo de que Gara hizo daño pero de_oidas == 1
    assert truth(world, Claim(ClaimKind.HARMED, gara, victim=renna)) is False

    # CONTRADICTS:
    # Si la víctima NO es el oyente, contradicts es siempre False
    assert contradicts(world, gara, Claim(ClaimKind.HARMED, vidan, victim=renna)) is False

    # Si la víctima ES el oyente (Renna): sabe quién le hizo daño (tiene recuerdo con Vidan)
    # y la afirmación acusa a Gara -> contradicts True
    assert contradicts(world, renna, Claim(ClaimKind.HARMED, gara, victim=renna)) is True
    # Acusa al verdadero causante (Vidan) -> contradicts False
    assert contradicts(world, renna, Claim(ClaimKind.HARMED, vidan, victim=renna)) is False
    # Oyente sin recuerdos de daño -> contradicts False
    assert contradicts(world, gara, Claim(ClaimKind.HARMED, vidan, victim=gara)) is False


# ==============================================================================
# B.1.2 — Verdadera -> creída sin tirada (M4)
# ==============================================================================


def test_verdadera_creida_sin_tirada() -> None:
    # 2. Verdadera -> creída sin tirada (resolver fingido que falla si se le llama). Cubre M4.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    sim.state.agents[speaker].at = sim.state.agents[listener].at

    class FailingResolver:
        def deceive(
            self, world: Any, liar: AgentId, listener_id: AgentId, key: str
        ) -> Outcome | None:
            raise AssertionError("No debe tirar si la afirmación es verdadera")

    sim.social_resolver = FailingResolver()
    talk = Conversation(listener)

    # Claim verdadero: Renna vive
    claim = Claim(ClaimKind.ALIVE, listener)
    r = sim.apply_social(speaker, listener, SocialAct.AFFIRM, None, talk, claim=claim)
    assert r.belief is Belief.BELIEVED


# ==============================================================================
# B.1.3 — Contradicha -> pillada sin tirada
# ==============================================================================


def test_contradicha_pillada_sin_tirada() -> None:
    # 3. Contradicha -> pillada sin tirada; aprecio caught.regard * loss_aversion, recuerdo.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    sim.state.agents[speaker].at = sim.state.agents[listener].at

    class FailingResolver:
        def deceive(
            self, world: Any, liar: AgentId, listener_id: AgentId, key: str
        ) -> Outcome | None:
            raise AssertionError("No debe tirar si la afirmación contradice lo que sabe")

    sim.social_resolver = FailingResolver()
    talk = Conversation(listener)

    # Contradicción: afirmar que Vidan está aquí (donde está listener), pero no está
    vidan = AgentId("vidan_d1")
    sim.state.agents[vidan].at = PlaceId("cornucopia")
    claim = Claim(ClaimKind.AT, vidan, place=sim.state.agents[listener].at)

    r = sim.apply_social(speaker, listener, SocialAct.AFFIRM, None, talk, claim=claim)
    assert r.belief is Belief.CAUGHT

    oyente = sim.state.agents[listener]
    caught = sim.pack.social.caught
    assert r.regard == pytest.approx(caught.regard * oyente.temperament.loss_aversion)
    assert r.valence == caught.valence
    assert r.importance == caught.importance

    # Recuerdo registrado en oyente con por_quien = speaker
    recuerdos = sim.state.memoria.de(listener)
    assert len(recuerdos) > 0
    ultimo = recuerdos[-1]
    assert ultimo.por_quien == speaker
    assert ultimo.valencia == caught.valence


# ==============================================================================
# B.1.4 — Ni verdadera ni contradicha: tirada con resolver (M5)
# ==============================================================================


def test_tirada_con_resolver_distintos_desenlaces() -> None:
    # 4. Ni verdadera ni contradicha: resolver fingido da cada resultado. Cubre M5.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    vidan = AgentId("vidan_d1")
    sim.state.agents[speaker].at = PlaceId("pedestal_1")
    sim.state.agents[listener].at = PlaceId("pedestal_1")
    sim.state.agents[vidan].at = PlaceId("cornucopia")
    sim.state.agents[listener].sightings.clear()

    # Claim no comprobable de inmediato ni verdadero: Vidan en ruinas_1_0
    claim = Claim(ClaimKind.AT, vidan, place=PlaceId("ruinas_1_0"))

    class MockResolver:
        resultado: Outcome = Outcome.SUCCESS

        def deceive(
            self, world: Any, liar: AgentId, listener_id: AgentId, key: str
        ) -> Outcome | None:
            return self.resultado

    mock = MockResolver()
    sim.social_resolver = mock

    # SUCCESS -> creída
    mock.resultado = Outcome.SUCCESS
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.BELIEVED

    # CRITICAL -> creída
    mock.resultado = Outcome.CRITICAL
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.BELIEVED

    # SUCCESS_AT_COST -> dudosa, aprecio doubt (Cubre M5)
    mock.resultado = Outcome.SUCCESS_AT_COST
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.DOUBTFUL
    assert r.regard == pytest.approx(sim.pack.social.doubt)
    assert r.tone == Tone.CURT

    # FAILURE -> pillada
    mock.resultado = Outcome.FAILURE
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.CAUGHT


# ==============================================================================
# B.1.5 — Sin resolver: decide el aprecio (M6)
# ==============================================================================


def test_sin_resolver_decide_aprecio() -> None:
    # 5. Sin resolver: creída con aprecio >= 0, pillada con aprecio < 0. Cubre M6.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    vidan = AgentId("vidan_d1")
    sim.state.agents[speaker].at = PlaceId("pedestal_1")
    sim.state.agents[listener].at = PlaceId("pedestal_1")
    sim.state.agents[vidan].at = PlaceId("cornucopia")
    sim.state.agents[listener].sightings.clear()
    sim.state.agents[listener].relations.clear()
    sim.social_resolver = None

    claim = Claim(ClaimKind.AT, vidan, place=PlaceId("ruinas_1_0"))

    # Aprecio positivo (>= 0) -> creída
    sim.state.agents[listener].acercar(speaker, 0.4, sim.state.tick)
    r_pos = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r_pos.belief is Belief.BELIEVED

    # Aprecio negativo (< 0) -> pillada (Cubre M6)
    sim.state.agents[listener].acercar(speaker, -1.0, sim.state.tick)
    r_neg = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r_neg.belief is Belief.CAUGHT


# ==============================================================================
# B.1.6 — Creída AT: quita de otros sitios y pone en Z (M7)
# ==============================================================================


def test_creida_at_actualiza_avistamientos() -> None:
    # 6. Creída AT: el oyente tiene a X solo en Z, con el tick de ahora. Cubre M7.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    vidan = AgentId("vidan_d1")
    sim.state.agents[speaker].at = PlaceId("pedestal_1")
    sim.state.agents[listener].at = PlaceId("pedestal_1")
    sim.state.agents[listener].acercar(speaker, 0.5, sim.state.tick)
    sim.social_resolver = None

    # El oyente tenía un avistamiento previo de Vidan en selva_1_0 y playa_1_0 en tick 1
    sim.state.agents[listener].sightings[PlaceId("selva_1_0")] = (1, frozenset({vidan, speaker}))
    sim.state.agents[listener].sightings[PlaceId("playa_1_0")] = (1, frozenset({vidan}))

    # Tick actual posterior al horizonte (192 en isla): 300 - 1 > 192, no contradice
    tick_actual = 300
    sim.state.tick = tick_actual
    claim = Claim(ClaimKind.AT, vidan, place=PlaceId("ruinas_1_0"))

    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.BELIEVED

    oyente_sightings = sim.state.agents[listener].sightings
    # Vidan fue quitado de selva_1_0 y de playa_1_0 (Cubre M7)
    assert vidan not in oyente_sightings[PlaceId("selva_1_0")][1]
    assert vidan not in oyente_sightings[PlaceId("playa_1_0")][1]
    # Y puesto solo en ruinas_1_0 con el tick de ahora
    assert vidan in oyente_sightings[PlaceId("ruinas_1_0")][1]
    assert oyente_sightings[PlaceId("ruinas_1_0")][0] == tick_actual


# ==============================================================================
# B.1.7 — Creída HARMED: baja el aprecio hacia el acusado
# ==============================================================================


def test_creida_harmed_mueve_aprecio() -> None:
    # 7. Creída HARMED: el aprecio del oyente hacia X baja accuse * aprecio a Y.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    victima = AgentId("elka_d1")
    acusado = AgentId("vidan_d1")
    sim.state.agents[speaker].at = PlaceId("pedestal_1")
    sim.state.agents[listener].at = PlaceId("pedestal_1")
    sim.state.agents[listener].relations.clear()
    sim.social_resolver = None
    sim.state.agents[listener].acercar(speaker, 0.5, sim.state.tick)

    # Aprecio del oyente hacia la víctima: 0.4
    sim.state.agents[listener].acercar(victima, 0.4, sim.state.tick)
    fade = sim.state.agents[listener].temperament.bond_fade
    piso = sim.state.agents[listener].relation_floor(sim.pack, victima)
    aprecio_y = sim.state.agents[listener].regard_for(victima, sim.state.tick, fade, piso)

    piso_acusado = sim.state.agents[listener].relation_floor(sim.pack, acusado)
    antes_acusado = sim.state.agents[listener].regard_for(
        acusado, sim.state.tick, fade, piso_acusado
    )

    claim = Claim(ClaimKind.HARMED, acusado, victim=victima)
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.BELIEVED

    despues_acusado = sim.state.agents[listener].regard_for(
        acusado, sim.state.tick, fade, piso_acusado
    )
    esperado_delta = -sim.pack.social.accuse * aprecio_y
    assert (despues_acusado - antes_acusado) == pytest.approx(esperado_delta, abs=1e-4)

    # Si la víctima es el oyente mismo: baja -accuse entero
    antes_oyente = sim.state.agents[listener].regard_for(
        acusado, sim.state.tick, fade, piso_acusado
    )
    claim_propio = Claim(ClaimKind.HARMED, acusado, victim=listener)
    r_propio = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim_propio
    )
    assert r_propio.belief is Belief.BELIEVED
    despues_oyente = sim.state.agents[listener].regard_for(
        acusado, sim.state.tick, fade, piso_acusado
    )
    assert (despues_oyente - antes_oyente) == pytest.approx(-sim.pack.social.accuse, abs=1e-4)


# ==============================================================================
# B.1.8 — DEAD verdadera: llega el recuerdo real de la muerte
# ==============================================================================


def test_dead_verdadera_transmite_recuerdo_real() -> None:
    # 8. DEAD verdadera: el oyente recibe el recuerdo real de la muerte (de_oidas 1).
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    muerto = AgentId("vidan_d1")
    testigo = AgentId("elka_d1")

    # Registrar muerte real vivida por el testigo
    evento = sim.log.emit(
        tick=sim.state.tick,
        kind=EventKind.AGENT_DIED,
        actor=muerto,
        place=sim.state.agents[muerto].at,
        subject=muerto,
    )
    sim.state.memoria.remember(testigo, evento, 0.9, -0.9)
    del sim.state.agents[muerto]

    sim.state.agents[speaker].at = sim.state.agents[listener].at
    claim = Claim(ClaimKind.DEAD, muerto)
    r = sim.apply_social(
        speaker, listener, SocialAct.AFFIRM, None, Conversation(listener), claim=claim
    )
    assert r.belief is Belief.BELIEVED

    recuerdos = sim.state.memoria.de(listener)
    muerte_rec = [
        rec for rec in recuerdos if rec.kind is EventKind.AGENT_DIED and rec.about == muerto
    ]
    assert len(muerte_rec) == 1
    assert muerte_rec[0].de_oidas == 1


# ==============================================================================
# B.1.9 — Preguntar WHERE y trusts (M8, M9)
# ==============================================================================


def test_preguntar_where_confianza_y_avistamientos() -> None:
    # 9. Preguntar WHERE sin confianza: nada cambia; con confianza: copia solo si más fresco.
    # Cubre M8 (WHERE: copiar si es más viejo) y M9 (trusts: ignorar relaciones).
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    tercero = AgentId("vidan_d1")
    sim.state.agents[speaker].at = sim.state.agents[listener].at
    sim.state.agents[listener].relations.clear()

    # Sin confianza (aprecio bajo y sin relación)
    sim.state.agents[listener].acercar(speaker, -0.8, sim.state.tick)
    assert trusts(sim.state, listener, speaker) is False
    r_seco = sim.apply_social(
        speaker,
        listener,
        SocialAct.ASK,
        tercero,
        Conversation(listener),
        question=QuestionKind.WHERE,
    )
    assert r_seco.tone == Tone.CURT
    assert r_seco.info == ()

    # Cubre M9: si tienen relación, trusts es True aunque el aprecio sea bajo (-0.8 < trust_above)
    rel_id = RelationId("amigo")
    sim.pack.relation_by_id[rel_id] = RelationSpec(id=rel_id, label="amigo", regard_floor=None)
    sim.state.agents[listener].relations[rel_id] = {speaker}
    assert trusts(sim.state, listener, speaker) is True

    # El oyente tiene avistamiento de Vidan en cornucopia en tick 10
    sim.state.tick = 15
    sim.state.agents[listener].sightings[PlaceId("cornucopia")] = (10, frozenset({tercero}))

    # Caso A: El hablante tenía avistamiento más viejo (tick 5) -> se actualiza a tick 10
    sim.state.agents[speaker].sightings[PlaceId("cornucopia")] = (5, frozenset({tercero}))
    r_info = sim.apply_social(
        speaker,
        listener,
        SocialAct.ASK,
        tercero,
        Conversation(listener),
        question=QuestionKind.WHERE,
    )
    assert len(r_info.info) == 1
    assert "hace 5 cuartos" in r_info.info[0]
    assert sim.state.agents[speaker].sightings[PlaceId("cornucopia")][0] == 10

    # Caso B (Cubre M8): El hablante tiene avistamiento MÁS RECIENTE (tick 12) -> no se sobreescribe
    sim.state.agents[speaker].sightings[PlaceId("cornucopia")] = (12, frozenset({tercero}))
    sim.apply_social(
        speaker,
        listener,
        SocialAct.ASK,
        tercero,
        Conversation(listener),
        question=QuestionKind.WHERE,
    )
    assert sim.state.agents[speaker].sightings[PlaceId("cornucopia")][0] == 12


# ==============================================================================
# B.1.10 — Preguntar ABOUT: memoria transmitida por oir
# ==============================================================================


def test_preguntar_about_recuerda_y_da_info() -> None:
    # 10. Preguntar ABOUT: el recuerdo llega por oir con la importancia del ayudante común.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    speaker = AgentId("gara_d1")
    listener = AgentId("renna_d1")
    tercero = AgentId("vidan_d1")
    sim.state.agents[speaker].at = sim.state.agents[listener].at
    sim.state.agents[listener].acercar(speaker, 0.5, sim.state.tick)

    # El oyente tiene un recuerdo sobre el tercero
    ev = sim.log.emit(
        tick=sim.state.tick,
        kind=EventKind.ACTION_COMPLETED,
        actor=tercero,
        action=ActionId("atacar"),
        place=sim.state.agents[listener].at,
        subject=tercero,
    )
    sim.state.memoria.remember(listener, ev, 0.7, -0.6)

    r = sim.apply_social(
        speaker,
        listener,
        SocialAct.ASK,
        tercero,
        Conversation(listener),
        question=QuestionKind.ABOUT,
    )
    assert len(r.info) == 1
    assert "de Vidan:" in r.info[0]

    # Hablante recibió el recuerdo con de_oidas > 0
    recuerdos_hablante = sim.state.memoria.de(speaker)
    assert len(recuerdos_hablante) == 1
    assert recuerdos_hablante[0].about == tercero
    assert recuerdos_hablante[0].de_oidas == 1


# ==============================================================================
# B.1.11 — Tirada por clave en WorldSocial (M10)
# ==============================================================================


def test_tirada_es_por_clave_y_reproducible(monkeypatch: pytest.MonkeyPatch) -> None:
    # 11. La tirada es por clave: dos procesos con la misma semilla, el mismo resultado. Cubre M10.
    ruleset = load_ruleset(BASE_RULES)
    sim1 = Simulation(load_pack(ISLA_PACK), seed=42)
    sim2 = Simulation(load_pack(ISLA_PACK), seed=42)
    binding1 = load_binding(ISLA_BINDING, sim1.state.pack, ruleset)
    binding2 = load_binding(ISLA_BINDING, sim2.state.pack, ruleset)

    ws1 = WorldSocial(ruleset, binding1)
    ws2 = WorldSocial(ruleset, binding2)

    liar = AgentId("gara_d1")
    listener = AgentId("renna_d1")

    # Mismo resultado con misma clave y misma semilla
    out1 = ws1.deceive(sim1.state, liar, listener, "clave_1")
    out2 = ws2.deceive(sim2.state, liar, listener, "clave_1")
    assert out1 == out2

    # Cubre M10: verificar que key se pasa a stream("enganyo", key, liar, listener)
    llamadas_stream: list[tuple[Any, ...]] = []
    stream_original = RngSource.stream

    def spy_stream(self_rng: Any, *args: Any) -> Any:
        llamadas_stream.append(args)
        return stream_original(self_rng, *args)

    monkeypatch.setattr(RngSource, "stream", spy_stream)
    ws1.deceive(sim1.state, liar, listener, "clave_especifica")
    assert ("enganyo", "clave_especifica", liar, listener) in llamadas_stream


# ==============================================================================
# B.2 — Agravio de oídas (M1)
# ==============================================================================


def test_agravio_pesa_de_oidas() -> None:
    # B.2: agravio de oídas pesa de_oidas (0.3). Cubre M1.
    mem = MemoriaEpisodica(capacidad=20)
    owner = AgentId("oyente")
    culpable = AgentId("acusado")
    tick = 10

    ev = Event(seq=1, tick=tick, kind=EventKind.ACTION_COMPLETED, actor=culpable, subject=owner)

    # Recuerdo vivido (de_oidas == 0)
    rec_vivido = mem.remember(owner, ev, importancia=1.0, valencia=-0.5, por_quien=culpable)
    assert rec_vivido is not None
    agravio_vivido = mem.agravio(owner, tick, escala=1.0, de_oidas=0.3)[culpable]
    assert agravio_vivido == pytest.approx(signed_saturation(0.5, 1.0))

    # Recuerdo de oídas (de_oidas == 1)
    mem_oidas = MemoriaEpisodica(capacidad=20)
    rec_original = mem.remember(
        AgentId("otro"), ev, importancia=1.0, valencia=-0.5, por_quien=culpable
    )
    assert rec_original is not None
    mem_oidas.oir(owner, rec_original, importancia=1.0)
    assert mem_oidas.de(owner)[0].de_oidas == 1

    # Con de_oidas=0.3, agravio es saturación(0.5 * 0.3, 1.0) = saturación(0.15, 1.0) (Cubre M1)
    agravio_oido = mem_oidas.agravio(owner, tick, escala=1.0, de_oidas=0.3)[culpable]
    assert agravio_oido == pytest.approx(signed_saturation(0.15, 1.0))


# ==============================================================================
# B.3 — WorldSocial
# ==============================================================================


def test_world_social_pools_y_validacion() -> None:
    # 1. Reservas = grado + nivel de porte / alerta con fichas de la isla.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, sim.state.pack, ruleset)
    ws = WorldSocial(ruleset, binding)
    gara = AgentId("gara_d1")

    ficha_gara = derive(sim.state, gara, ruleset, binding).combatant
    # porte (deceive)
    attr_porte = next(s.attribute for s in ruleset.skills if s.id == "porte")
    esp_porte = ruleset.grade(ficha_gara.attributes[attr_porte]) + ficha_gara.skills.get("porte", 0)
    assert ws.pool(sim.state, gara, "porte") == esp_porte

    # alerta (notice)
    attr_alerta = next(s.attribute for s in ruleset.skills if s.id == "alerta")
    esp_alerta = (
        ruleset.grade(ficha_gara.attributes[attr_alerta]) + ficha_gara.skills.get("alerta", 0)
    )
    assert ws.pool(sim.state, gara, "alerta") == esp_alerta

    # 2. Sin ruleset.social, None.
    ruleset_sin_social = ruleset.model_copy(update={"social": None})
    ws_sin_social = WorldSocial(ruleset_sin_social, binding)
    assert ws_sin_social.deceive(sim.state, gara, AgentId("renna_d1"), "k") is None

    # 3. Un sistema con social.deceive que no es una competencia no carga.
    raw = yaml.safe_load(BASE_RULES.read_text(encoding="utf-8"))
    raw["social"]["deceive"] = "competencia_inventada_inexistente"
    with pytest.raises(ValidationError):
        Ruleset.model_validate(raw)


# ==============================================================================
# B.4 — Intérprete y terminal (M11)
# ==============================================================================


def test_interpret_said_esquema_anidado() -> None:
    # 1. Esquema anidado: con proveedor fingido, cada tipo se convierte en Claim o QuestionKind.
    class MockProvider(CognitionProvider):
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data

        def think(self, prompt: str, schema: type[Any], seed: int) -> Any:
            return schema.model_validate(self.data)

    people = [("gara_d1", "Gara"), ("renna_d1", "Renna"), ("jugador", "yo")]
    places = [("arroyo", "arroyo"), ("cornucopia", "cornucopia")]

    # AT
    p1 = MockProvider({
        "tipo": "afirmar",
        "afirmacion": {"que": "esta_en", "persona": "renna_d1", "lugar": "arroyo"},
    })
    s1 = interpret_said(people, places, "Renna está en el arroyo", p1, 1)
    assert s1 is not None
    assert s1.claim == Claim(ClaimKind.AT, AgentId("renna_d1"), place=PlaceId("arroyo"))

    # HARMED con jugador como víctima válida
    p2 = MockProvider(
        {
            "tipo": "afirmar",
            "afirmacion": {"que": "hizo_dano", "persona": "renna_d1", "victima": "jugador"},
        }
    )
    s2 = interpret_said(people, places, "Renna me hirió", p2, 1)
    assert s2 is not None
    assert s2.claim == Claim(
        ClaimKind.HARMED, AgentId("renna_d1"), victim=AgentId("jugador")
    )

    # ALIVE
    p3 = MockProvider(
        {"tipo": "afirmar", "afirmacion": {"que": "vive", "persona": "renna_d1"}}
    )
    s3 = interpret_said(people, places, "Renna vive", p3, 1)
    assert s3 is not None and s3.claim == Claim(ClaimKind.ALIVE, AgentId("renna_d1"))

    # DEAD
    p4 = MockProvider(
        {"tipo": "afirmar", "afirmacion": {"que": "ha_muerto", "persona": "renna_d1"}}
    )
    s4 = interpret_said(people, places, "Renna murió", p4, 1)
    assert s4 is not None and s4.claim == Claim(ClaimKind.DEAD, AgentId("renna_d1"))

    # WHERE
    p5 = MockProvider(
        {"tipo": "preguntar", "pregunta": {"que": "donde_esta", "persona": "renna_d1"}}
    )
    s5 = interpret_said(people, places, "¿dónde está Renna?", p5, 1)
    assert s5 is not None and s5.question == (QuestionKind.WHERE, AgentId("renna_d1"))

    # ABOUT
    p6 = MockProvider(
        {"tipo": "preguntar", "pregunta": {"que": "que_sabes", "persona": "renna_d1"}}
    )
    s6 = interpret_said(people, places, "¿qué sabes de Renna?", p6, 1)
    assert s6 is not None and s6.question == (QuestionKind.ABOUT, AgentId("renna_d1"))

    # OTRO
    p7 = MockProvider({"tipo": "otro"})
    s7 = interpret_said(people, places, "hola", p7, 1)
    assert s7 is not None and s7.claim is None and s7.question is None


def test_terminal_conversar_sin_modelo_no_afirma() -> None:
    # 2. Sin modelo, «Renna está en el arroyo» no se aplica y la terminal lo dice. Cubre M11.
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    yo = AgentId("gara_d1")
    otro = AgentId("renna_d1")
    sim.set_player(yo)
    sim.state.agents[yo].at = PlaceId("ruinas_3_7")
    sim.state.agents[otro].at = PlaceId("ruinas_3_7")
    for a in sim.state.agents.values():
        if a.spec_id not in (yo, otro) and a.at == PlaceId("ruinas_3_7"):
            a.at = PlaceId("cornucopia")

    opts = tuple(options(sim.state, sim.state.agents[yo]))
    inp = io.StringIO("hablar renna_d1\nRenna está en el arroyo, la he visto\na\nadiós\n1\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None, interpreter=None)
    terminal.choose(sim.state, sim.state.agents[yo], opts)

    output = out.getvalue()
    assert "no sé qué afirmas; dilo de otra forma" in output

    # Cubre M11: no se debe haber emitido ningún SOCIAL_ACT de afirmación
    social_acts = [
        e for e in sim.log if e.kind is EventKind.SOCIAL_ACT and e.data.get("act") == "afirmar"
    ]
    assert len(social_acts) == 0


def test_recorder_y_script_con_afirmar_y_preguntar() -> None:
    # 3. Guion: grabar conversación con afirmación y pregunta y reproducirla da el mismo log.
    sim1 = Simulation(load_pack(ISLA_PACK), seed=3)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, sim1.state.pack, ruleset)
    sim1.social_resolver = WorldSocial(ruleset, binding)

    yo1 = AgentId("gara_d1")
    otro1 = AgentId("renna_d1")
    sim1.set_player(yo1)
    sim1.state.agents[yo1].at = sim1.state.agents[otro1].at

    class FakeTerminalSource:
        def choose(self, world: Any, agent: Any, opts: Any) -> Any:
            talk = Conversation(otro1)
            sim1.apply_social(
                yo1,
                otro1,
                SocialAct.AFFIRM,
                None,
                talk,
                claim=Claim(ClaimKind.AT, AgentId("vidan_d1"), place=PlaceId("cornucopia")),
            )
            sim1.apply_social(
                yo1, otro1, SocialAct.ASK, AgentId("vidan_d1"), talk, question=QuestionKind.WHERE
            )
            return opts[0]

    buf = io.StringIO()
    rec = Recorder(FakeTerminalSource(), buf, sim=sim1)  # type: ignore[arg-type]
    opts1 = tuple(options(sim1.state, sim1.state.agents[yo1]))
    elegida1 = rec.choose(sim1.state, sim1.state.agents[yo1], opts1)

    lines_raw = buf.getvalue().splitlines()

    # Reproducción en sim2 con Script
    sim2 = Simulation(load_pack(ISLA_PACK), seed=3)
    sim2.social_resolver = WorldSocial(ruleset, binding)
    yo2 = AgentId("gara_d1")
    otro2 = AgentId("renna_d1")
    sim2.set_player(yo2)
    sim2.state.agents[yo2].at = sim2.state.agents[otro2].at
    opts2 = tuple(options(sim2.state, sim2.state.agents[yo2]))

    script = Script(lines_raw, sim=sim2)
    elegida2 = script.choose(sim2.state, sim2.state.agents[yo2], opts2)

    assert elegida1 == elegida2
    assert list(sim1.log) == list(sim2.log)
