"""Pruebas de la recepción de actos sociales, apply_social, conversación y guion (plan 15a, §B)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.agents.decide import options
from agora.banco import load_acts_bank, load_bank, run_acts_bank, run_bank
from agora.cognition.conversa import (
    ABOUT,
    FAREWELL,
    talk_menu,
)
from agora.cognition.voz import Habla, Heard, hablar
from agora.engine.consulta import Lack, ficha
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, SocialAct, SocialSpec, Tone
from agora.engine.pack import PackError, load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.social import (
    GRUDGE,
    Conversation,
    Reaction,
    react,
)
from agora.engine.world import Simulation
from agora.play import Recorder, Script, Terminal
from agora.rules.system import load_ruleset

BASE_RULES = Path("rules/base/rules.yaml")
CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
ISLA_PACK = Path("packs/isla/pack.yaml")
ISLA_ACTS_BANK = Path("packs/isla/banco-actos.jsonl")
ISLA_INTENTIONS_BANK = Path("packs/isla/banco-intenciones.jsonl")


# ==============================================================================
# B.1 — tests/test_social.py: recepción y react
# ==============================================================================


def test_traza_de_react_en_confluencia() -> None:
    # 1. La traza de §A.11, número a número.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    for _ in range(40):
        sim.tick()
    ags = sim.state.agents_in_order()
    yo = next(a for a in ags if sum(1 for o in ags if o.at == a.at) >= 3)
    otros = [o for o in ags if o.at == yo.at and o is not yo]

    def ejecutar(
        oyente_id: AgentId, actos: list[SocialAct], about: AgentId | None = None
    ) -> list[Reaction]:
        talk = Conversation(oyente_id)
        reacciones = []
        for a in actos:
            if talk.over:
                break
            r = sim.apply_social(yo.spec_id, oyente_id, a, about, talk)
            reacciones.append(r)
        return reacciones

    # otros[0]: hurn_fuegolento
    res0 = ejecutar(otros[0].spec_id, [
        SocialAct.GREET, SocialAct.FLATTER, SocialAct.FLATTER,
        SocialAct.FLATTER, SocialAct.CHAT, SocialAct.JOKE,
    ])
    assert otros[0].spec_id == AgentId("hurn_fuegolento")
    assert len(res0) == 6
    assert round(res0[0].regard, 3) == 0.010 and round(res0[0].regard_after, 3) == 0.010
    assert res0[0].tone == Tone.FRIENDLY and not res0[0].leaves
    assert round(res0[1].regard, 3) == 0.040 and round(res0[1].regard_after, 3) == 0.050
    assert res0[1].tone == Tone.FRIENDLY and not res0[1].leaves
    assert round(res0[2].regard, 3) == 0.019 and round(res0[2].regard_after, 3) == 0.069
    assert res0[2].tone == Tone.FRIENDLY and not res0[2].leaves
    assert round(res0[3].regard, 3) == 0.009 and round(res0[3].regard_after, 3) == 0.078
    assert res0[3].tone == Tone.FRIENDLY and not res0[3].leaves
    assert round(res0[4].regard, 3) == 0.018 and round(res0[4].regard_after, 3) == 0.096
    assert res0[4].tone == Tone.FRIENDLY and not res0[4].leaves
    assert round(res0[5].regard, 3) == 0.027 and round(res0[5].regard_after, 3) == 0.123
    assert res0[5].tone == Tone.FRIENDLY and res0[5].leaves

    # otros[1]: sela_hierrogris
    res1 = ejecutar(otros[1].spec_id, [
        SocialAct.INSULT, SocialAct.INSULT, SocialAct.THREATEN, SocialAct.APOLOGIZE,
    ])
    assert otros[1].spec_id == AgentId("sela_hierrogris")
    assert len(res1) == 4
    assert round(res1[0].regard, 3) == -0.080 and round(res1[0].regard_after, 3) == -0.080
    assert res1[0].tone == Tone.CURT and not res1[0].leaves
    assert round(res1[1].regard, 3) == -0.040 and round(res1[1].regard_after, 3) == -0.120
    assert res1[1].tone == Tone.HOSTILE and not res1[1].leaves
    assert round(res1[2].regard, 3) == -0.120 and round(res1[2].regard_after, 3) == -0.240
    assert res1[2].tone == Tone.HOSTILE and not res1[2].leaves
    assert round(res1[3].regard, 3) == 0.015 and round(res1[3].regard_after, 3) == -0.225
    assert res1[3].tone == Tone.CURT and not res1[3].leaves

    # Agravio acumulado de sela_hierrogris hacia yo
    escala = sim.pack.tuning.grief_scale
    agravio_map = sim.state.memoria.agravio(otros[1].spec_id, sim.state.tick, escala)
    assert round(agravio_map[yo.spec_id], 3) == 0.621

    # otros[2]: orin_zarzal
    fav = max(otros[2].bonds, key=lambda k: otros[2].bonds[k].regard)
    res2 = ejecutar(otros[2].spec_id, [SocialAct.INSULT], about=fav)
    assert otros[2].spec_id == AgentId("orin_zarzal")
    assert len(res2) == 1
    assert round(res2[0].regard, 3) == -0.080 and round(res2[0].regard_after, 3) == -0.080
    assert res2[0].tone == Tone.CURT and not res2[0].leaves


def test_react_es_pura() -> None:
    # 2. react es pura: llamarla dos veces da lo mismo y no cambia el estado.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)
    r1 = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    bonds_before = {k: v.regard for k, v in sim.state.agents[listener].bonds.items()}
    recuerdos_count = len(sim.state.memoria.de(listener))

    r2 = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    bonds_after = {k: v.regard for k, v in sim.state.agents[listener].bonds.items()}

    assert r1 == r2
    assert bonds_before == bonds_after
    assert len(sim.state.memoria.de(listener)) == recuerdos_count


def test_lo_positivo_satura_con_aprecio_previo() -> None:
    # 3. Lo positivo satura: con aprecio previo 0.5, un halago mueve la mitad que a 0.
    # Cubre M1 (quitar *(1.0 - max(0.0, ahora))).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)
    r_cero = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)

    # Ahora situamos el aprecio previo exactamente en 0.5
    sim.state.agents[listener].acercar(speaker, 0.5, sim.state.tick)
    r_mitad = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)

    assert r_cero.regard > 0.0
    assert r_mitad.regard == pytest.approx(0.5 * r_cero.regard, rel=1e-3)


def test_agravio_reduce_lo_positivo_y_tono_seco() -> None:
    # 4. Con agravio > GRUDGE, lo positivo pesa la mitad y el tono es seco.
    # Cubre M2 (quitar if rencor > GRUDGE: delta *= 0.5).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)
    r_sin_agravio = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)

    # Añadir agravio en memoria > GRUDGE (0.2)
    ev = sim.log.emit(
        tick=sim.state.tick,
        kind=EventKind.SOCIAL_ACT,
        actor=speaker,
        place=ags[0].at,
        subject=listener,
        data={"act": SocialAct.INSULT.value, "regard": -0.08},
    )
    sim.state.memoria.remember(listener, ev, 0.8, -1.0, por_quien=speaker)
    escala = sim.pack.tuning.grief_scale
    rencor = sim.state.memoria.agravio(listener, sim.state.tick, escala).get(speaker, 0.0)
    assert rencor > GRUDGE

    r_con_agravio = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    assert r_con_agravio.regard == pytest.approx(0.5 * r_sin_agravio.regard, rel=1e-3)
    assert r_con_agravio.tone == Tone.CURT


def test_carencia_desesperada_reduce_lo_positivo_y_tono_triste() -> None:
    # 5. Con una carencia desesperada (ficha), lo positivo pesa la mitad y el tono es triste.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)
    r_normal = react(sim.state, listener, speaker, SocialAct.GREET, None, talk)

    # Forzar carencia desesperada en el oyente (satisfacción < 0.1)
    necesidad = next(n.id for n in sim.pack.needs if not n.progression)
    sim.state.agents[listener].needs[necesidad] = 0.05
    carencias = ficha(sim.state, listener).carencias
    assert carencias and carencias[0][1] is Lack.DESPERATE

    r_apurado = react(sim.state, listener, speaker, SocialAct.GREET, None, talk)
    assert r_apurado.regard == pytest.approx(0.5 * r_normal.regard, rel=1e-3)
    assert r_apurado.tone == Tone.SAD


def test_loss_aversion_pesa_en_lo_negativo() -> None:
    # 6. loss_aversion 1.8 hace un insulto 1.8 veces más dañino que 1.0.
    # Cubre M3 (delta = base en la rama negativa, sin loss_aversion).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)

    # Caso loss_aversion = 1.0
    object.__setattr__(sim.state.agents[listener].temperament, "loss_aversion", 1.0)
    r_10 = react(sim.state, listener, speaker, SocialAct.INSULT, None, talk)

    # Caso loss_aversion = 1.8
    object.__setattr__(sim.state.agents[listener].temperament, "loss_aversion", 1.8)
    r_18 = react(sim.state, listener, speaker, SocialAct.INSULT, None, talk)

    assert r_18.regard == pytest.approx(1.8 * r_10.regard, rel=1e-3)


def test_tercero_detestado_invierte_halago_e_insulto() -> None:
    # 7. Halagar a un tercero detestado baja aprecio; insultarlo lo sube.
    # Cubre M4 (no usar aprecio(about), tratar a un tercero como al oyente).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id
    third = ags[2].spec_id

    # El oyente detesta al tercero (aprecio negativo)
    sim.state.agents[listener].acercar(third, -0.2, sim.state.tick)
    talk = Conversation(listener)

    # Halagar al tercero detestado baja el aprecio hacia quien habla
    r_flatter = react(sim.state, listener, speaker, SocialAct.FLATTER, third, talk)
    assert r_flatter.regard < 0.0

    # Insultar al tercero detestado sube el aprecio hacia quien habla
    r_insult = react(sim.state, listener, speaker, SocialAct.INSULT, third, talk)
    assert r_insult.regard > 0.0


def test_broma_con_aprecio_negativo_resta_y_valencia_negativa() -> None:
    # 8. Una broma con aprecio negativo resta y se recuerda con valencia negativa.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    sim.state.agents[listener].acercar(speaker, -0.15, sim.state.tick)
    talk = Conversation(listener)

    r = react(sim.state, listener, speaker, SocialAct.JOKE, None, talk)
    assert r.regard < 0.0
    assert r.valence < 0.0


def test_repetir_acto_decae_por_repeat_decay() -> None:
    # 9. Repetir el mismo acto multiplica por repeat_decay cada vez; otro acto no.
    # Cubre M5 (quitar ** talk.said.get(act, 0)).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    decay = sim.pack.social.repeat_decay
    talk = Conversation(listener)

    # Primer halago
    r1 = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    talk.said[SocialAct.FLATTER] = 1

    # Segundo halago (sin mover el aprecio del estado para aislar decay)
    r2 = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    assert r2.regard == pytest.approx(r1.regard * decay, rel=1e-3)

    # Tercer halago
    talk.said[SocialAct.FLATTER] = 2
    r3 = react(sim.state, listener, speaker, SocialAct.FLATTER, None, talk)
    assert r3.regard == pytest.approx(r1.regard * (decay**2), rel=1e-3)

    # Otro acto (charlar) no decae
    r_chat = react(sim.state, listener, speaker, SocialAct.CHAT, None, talk)
    talk_limpio = Conversation(listener)
    r_chat_base = react(sim.state, listener, speaker, SocialAct.CHAT, None, talk_limpio)
    assert r_chat.regard == pytest.approx(r_chat_base.regard, rel=1e-3)


def test_max_acts_devuelve_leaves() -> None:
    # 10. max_acts: el acto número max_acts devuelve leaves.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    max_acts = sim.pack.social.max_acts
    talk = Conversation(listener, count=max_acts - 1)
    r = react(sim.state, listener, speaker, SocialAct.CHAT, None, talk)
    assert r.leaves is True


def test_amenaza_con_aprecio_mayor_que_hostil_asusta_y_se_va() -> None:
    # 11. Amenazar con el aprecio resultante por encima de -0.2 → asustado y se va.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    # Con aprecio base 0.0 y amenaza (-0.12 * loss_aversion 1.0 = -0.12),
    # el aprecio final -0.12 es > HOSTILE_AT (-0.20)
    object.__setattr__(sim.state.agents[listener].temperament, "loss_aversion", 1.0)
    talk = Conversation(listener)
    r = react(sim.state, listener, speaker, SocialAct.THREATEN, None, talk)

    assert r.tone == Tone.AFRAID
    assert r.leaves is True


def test_preguntar_afirmar_mentir_no_mueven_nada() -> None:
    # 12. preguntar, afirmar, mentir no mueven nada ni dejan recuerdo.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    speaker = ags[0].spec_id
    listener = ags[1].spec_id

    talk = Conversation(listener)
    for act in (SocialAct.ASK, SocialAct.AFFIRM, SocialAct.LIE):
        r = react(sim.state, listener, speaker, act, None, talk)
        assert r.regard == 0.0
        assert r.importance == 0.0
        assert r.regard_after == 0.0


# ==============================================================================
# B.2 — apply_social y lo que toca
# ==============================================================================


def test_apply_social_emite_evento_acerca_y_recuerda() -> None:
    # 1. Emite un SOCIAL_ACT con actor, subject, place y data; mueve el aprecio por acercar;
    # deja un recuerdo con por_quien = jugador solo si fue a peor.
    # Cubre M6 (por_quien=speaker siempre) y M7 (no incrementar talk.said).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    yo = next(a for a in ags if sum(1 for o in ags if o.at == a.at) >= 2)
    otro = next(o for o in ags if o.at == yo.at and o is not yo)

    talk = Conversation(otro.spec_id)
    seq_antes = sim.log.siguiente_seq

    # Acto positivo: FLATTER (valence > 0)
    r_pos = sim.apply_social(yo.spec_id, otro.spec_id, SocialAct.FLATTER, None, talk)
    assert talk.said[SocialAct.FLATTER] == 1
    assert talk.count == 1

    eventos = [e for e in sim.log if e.seq >= seq_antes]
    assert len(eventos) == 1
    ev_pos = eventos[0]
    assert ev_pos.kind is EventKind.SOCIAL_ACT
    assert ev_pos.actor == yo.spec_id
    assert ev_pos.subject == otro.spec_id
    assert ev_pos.place == otro.at
    assert ev_pos.data["act"] == SocialAct.FLATTER.value
    assert ev_pos.data["regard"] == round(r_pos.regard, 4)

    # Recuerdo positivo no tiene culpable
    recuerdos = sim.state.memoria.de(otro.spec_id)
    assert len(recuerdos) == 1
    assert recuerdos[0].por_quien is None  # Cubre M6

    # Acto negativo: INSULT (valence < 0)
    seq_antes = sim.log.siguiente_seq
    r_neg = sim.apply_social(yo.spec_id, otro.spec_id, SocialAct.INSULT, None, talk)
    assert r_neg.regard < 0.0
    assert talk.said[SocialAct.INSULT] == 1
    assert talk.count == 2

    recuerdos = sim.state.memoria.de(otro.spec_id)
    assert len(recuerdos) == 2
    assert recuerdos[-1].por_quien == yo.spec_id


def test_apply_social_value_error_en_distinto_lugar_o_conversacion_acabada() -> None:
    # 2. ValueError si no están en el mismo sitio o la conversación acabó.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    yo = ags[0]
    lejos = next(a for a in ags if a.at != yo.at)

    talk = Conversation(lejos.spec_id)
    with pytest.raises(ValueError, match="no puede hablar con"):
        sim.apply_social(yo.spec_id, lejos.spec_id, SocialAct.GREET, None, talk)

    # Mismo sitio pero conversación marcada como acabada
    aqui = next(a for a in ags[1:] if a.at == yo.at)
    talk_acabada = Conversation(aqui.spec_id, over=True)
    with pytest.raises(ValueError, match="no puede hablar con"):
        sim.apply_social(yo.spec_id, aqui.spec_id, SocialAct.GREET, None, talk_acabada)


def test_insultar_genera_agravio_en_memoria() -> None:
    # 3. Tras insultar, memoria.agravio(oyente) tiene al jugador.
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    yo = ags[0]
    otro = next(a for a in ags[1:] if a.at == yo.at)

    talk = Conversation(otro.spec_id)
    sim.apply_social(yo.spec_id, otro.spec_id, SocialAct.INSULT, None, talk)

    agravio = sim.state.memoria.agravio(otro.spec_id, sim.state.tick, sim.pack.tuning.grief_scale)
    assert yo.spec_id in agravio
    assert agravio[yo.spec_id] > 0.0


def test_pack_con_social_action_inexistente_falla(tmp_path: Path) -> None:
    # 4. Un pack con social.action inexistente no carga.
    # Cubre M11 (_check_social: devolver [] siempre).
    pack = load_pack(CONFLUENCIA_PACK)
    object.__setattr__(pack, "social", SocialSpec(action=ActionId("accion_fantasma")))
    errores = pack._check_social()
    assert "social.action: la acción «accion_fantasma» no existe" in errores

    pack_data = yaml.safe_load(CONFLUENCIA_PACK.read_text(encoding="utf-8"))
    pack_data["social"] = {"action": "accion_fantasma"}
    bad_pack = tmp_path / "bad_pack.yaml"
    bad_pack.write_text(yaml.safe_dump(pack_data), encoding="utf-8")
    with pytest.raises(PackError, match=r"social.action: la acción «accion_fantasma» no existe"):
        load_pack(bad_pack)


def test_sin_jugador_confluencia_mismo_log() -> None:
    # 5. Sin jugador, una partida de confluencia da el mismo log que antes.
    sim1 = Simulation(load_pack(CONFLUENCIA_PACK), seed=7)
    sim2 = Simulation(load_pack(CONFLUENCIA_PACK), seed=7)
    for _ in range(96):
        sim1.tick()
        sim2.tick()
    assert list(sim1.log) == list(sim2.log)


# ==============================================================================
# B.3 — Cognición y terminal
# ==============================================================================


def test_talk_menu_entradas_terceros_y_despedida() -> None:
    # 1. talk_menu: un FLATTER sin nadie y uno por tercero; despedirse está.
    gente = [("gara_d1", "Gara"), ("renna_d1", "Renna"), ("vidan_d1", "Vidan")]
    menu = talk_menu(gente, listener="gara_d1")

    acciones = [e.action for e in menu.entries]
    assert FAREWELL in acciones

    # Todos los actos sociales básicos presentes sin destinatario
    for act in SocialAct:
        assert any(e.action == act and e.target is None for e in menu.entries)

    # Para los actos con ABOUT (FLATTER, INSULT, ASK, AFFIRM, LIE):
    # deben existir entradas con target para renna_d1 y vidan_d1, pero NUNCA gara_d1
    for act in ABOUT:
        targets = [e.target for e in menu.entries if e.action == act]
        assert "renna_d1" in targets
        assert "vidan_d1" in targets
        assert "gara_d1" not in targets


def test_interpret_sin_template_mantiene_banco_14() -> None:
    # 2. interpret sin template da lo mismo que hoy (banco de la 14: 50/76 sin modelo).
    casos = load_bank(ISLA_INTENTIONS_BANK)
    pack = load_pack(ISLA_PACK)
    ruleset = load_ruleset(BASE_RULES)
    informe = run_bank(pack, ruleset, casos, None)
    assert informe.aciertos == 50
    assert informe.casos == 76
    assert informe.falsos_si == 5


def test_hablar_con_heard_corrige_tono_y_sin_heard_respaldo_identico() -> None:
    # 3. hablar(..., heard): el modelo fingido devuelve otro tono y sale el de heard;
    # sin heard, la frase del respaldo es la de antes (misma semilla).
    # Cubre M8 (hablar: no corregir el tono del modelo).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    ags = sim.state.agents_in_order()
    agente = ags[0].spec_id
    interlocutor = ags[1].spec_id

    class MockProvider(CognitionProvider):
        def think(self, prompt: str, schema: type[Any], seed: int) -> Any:
            # Devuelve hostil a pesar de que heard pide friendly
            return Habla(dice="Te miro fijamente.", tono=Tone.HOSTILE)

    oido = Heard(phrase="hola", act="saludar", tone=Tone.FRIENDLY, leaves=False, turn=0)
    habla_modelo, del_modelo, _ = hablar(
        sim.state, agente, interlocutor, proveedor=MockProvider(), heard=oido
    )

    assert del_modelo is True
    assert habla_modelo.dice == "Te miro fijamente."
    # El tono devuelto debe haber sido corregido al de heard (FRIENDLY), no HOSTILE (cubre M8)
    assert habla_modelo.tono == Tone.FRIENDLY

    # Sin heard, con proveedor=None devuelve respaldo determinista
    habla_resp1, _, _ = hablar(sim.state, agente, interlocutor, proveedor=None)
    habla_resp2, _, _ = hablar(sim.state, agente, interlocutor, proveedor=None)
    assert habla_resp1 == habla_resp2


def test_terminal_conversar_devuelve_charlar_y_cambia_aprecio() -> None:
    # 4. Terminal con hablar X, tres frases (léxico) y «adiós», en confluencia:
    # devuelve la decisión «charlar» y el aprecio de X hacia el jugador cambió.
    # Cubre M10 (_conversar: devolver (False, None) siempre al acabar).
    sim = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    for _ in range(40):
        sim.tick()
    yo = sim.state.agents[AgentId("adze_umbrio")]
    otro = sim.state.agents[AgentId("fror_vadohondo")]
    opts = tuple(options(sim.state, yo))

    fade = otro.temperament.bond_fade
    piso = otro.relation_floor(sim.pack, yo.spec_id)
    regard_antes = otro.regard_for(yo.spec_id, sim.state.tick, fade, piso)

    inp = io.StringIO("hablar fror_vadohondo\nbuenas\ncuéntame algo\neres muy hábil\nadiós\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None, interpreter=None)

    elegida = terminal.choose(sim.state, yo, opts)
    assert elegida is not None
    assert elegida.action == ActionId("charlar")
    assert elegida.travel_ticks == 0

    regard_despues = otro.regard_for(yo.spec_id, sim.state.tick, fade, piso)
    assert regard_despues > regard_antes


def test_recorder_y_script_conversacion_graban_y_reproducen_mismo_log() -> None:
    # 5. Recorder + Script: grabar esa partida y reproducirla da el mismo log.
    # Cubre M9 (Recorder: escribir las líneas hablar después de decidir).
    sim1 = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    for _ in range(40):
        sim1.tick()
    yo1 = sim1.state.agents[AgentId("adze_umbrio")]
    sim1.set_player(yo1.spec_id)
    opts1 = tuple(options(sim1.state, yo1))

    inp = io.StringIO("hablar fror_vadohondo\nbuenas\ncuéntame algo\neres muy hábil\nadiós\n")
    out = io.StringIO()
    terminal = Terminal(sim1, inp, out)

    buf = io.StringIO()
    rec = Recorder(terminal, buf, sim=sim1)
    elegida1 = rec.choose(sim1.state, yo1, opts1)
    assert elegida1 is not None

    # Verificar que las líneas hablar se grabaron ANTES de la línea decidir (cubre M9)
    lineas_raw = buf.getvalue().splitlines()
    lineas = [json.loads(line) for line in lineas_raw]
    indices_hablar = [i for i, item in enumerate(lineas) if "hablar" in item]
    indices_decidir = [i for i, item in enumerate(lineas) if "decidir" in item]
    assert len(indices_hablar) == 3
    assert len(indices_decidir) == 1
    assert max(indices_hablar) < min(indices_decidir)

    # Reproducción con Script
    sim2 = Simulation(load_pack(CONFLUENCIA_PACK), seed=3)
    for _ in range(40):
        sim2.tick()
    yo2 = sim2.state.agents[AgentId("adze_umbrio")]
    sim2.set_player(yo2.spec_id)
    opts2 = tuple(options(sim2.state, yo2))

    guion = Script(lineas_raw, sim=sim2)
    elegida2 = guion.choose(sim2.state, yo2, opts2)

    assert elegida2 == elegida1
    assert list(sim1.log) == list(sim2.log)


def test_banco_actos_sin_interprete_17_aciertos_y_1_falso_si() -> None:
    # 6. run_acts_bank(casos, None): 17/30, falsos sí 1 exactos.
    casos = load_acts_bank(ISLA_ACTS_BANK)
    reporte = run_acts_bank(casos, provider=None)
    assert reporte.casos == 30
    assert reporte.aciertos == 17
    assert reporte.falsos_si == 1
