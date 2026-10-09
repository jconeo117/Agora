"""Pruebas de la voz de un NPC (hablar, briefing y respaldo sin red)."""

from __future__ import annotations

import sys
from typing import Any

import pytest

import agora.run
from agora.cognition.voz import SIN_VOZ, Habla, hablar, tono_de_respaldo
from agora.engine.consulta import Ficha, Lack
from agora.engine.ontology import AgentId, NeedId, Tone
from agora.engine.state import PerformingAction, WorldState
from agora.engine.world import Simulation
from tests.test_consulta import pack_con_voz
from tests.test_reanudar import foto


class ProveedorFalso:
    """Proveedor que devuelve lo que se le pida y registra llamadas."""

    def __init__(self, respuesta: object) -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[str, int]] = []

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        self.llamadas.append((briefing, semilla))
        return self.respuesta


def test_si_el_modelo_responde_habla_el_modelo() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag = AgentId("agente_a")
    esperado = Habla(dice="Todo marcha bien.", tono=Tone.FRIENDLY)
    proveedor = ProveedorFalso(esperado)

    habla, del_modelo, _ = hablar(world, ag, proveedor=proveedor)
    assert del_modelo is True
    assert habla == esperado


def test_si_el_modelo_falla_habla_el_respaldo() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag = AgentId("agente_a")
    proveedor = ProveedorFalso(None)

    habla, del_modelo, _ = hablar(world, ag, proveedor=proveedor)
    assert del_modelo is False
    assert habla.dice in pack.voice.fallback[habla.tono]  # type: ignore[union-attr]


def test_si_el_modelo_devuelve_otra_cosa_habla_el_respaldo() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag = AgentId("agente_a")
    proveedor = ProveedorFalso({"dice": "un dict", "tono": "amable"})

    habla, del_modelo, _ = hablar(world, ag, proveedor=proveedor)
    assert del_modelo is False
    assert habla.dice in pack.voice.fallback[habla.tono]  # type: ignore[union-attr]


def test_la_regla_del_tono() -> None:
    ag_a = AgentId("agente_a")

    # 1. Hostil si aprecio <= -0.2 (frontera inclusiva -0.2)
    f_hostil = Ficha(
        agente=ag_a,
        nombre="A",
        identidad=(),
        caracter=(),
        lugar="L",
        fase=None,
        actividad=None,
        de_camino_a=None,
        carencias=(("salud", Lack.DESPERATE),),
        recuerdos=(),
        aprecia=(),
        detesta=(),
        interlocutor="B",
        aprecio_al_interlocutor=-0.2,
        relaciones_con_interlocutor=(),
    )
    # HOSTILE gana incluso a carencia DESPERATE
    assert tono_de_respaldo(f_hostil) is Tone.HOSTILE

    # 2. Triste si carencia desesperada (sin aprecio negativo)
    f_triste = Ficha(
        agente=ag_a,
        nombre="A",
        identidad=(),
        caracter=(),
        lugar="L",
        fase=None,
        actividad=None,
        de_camino_a=None,
        carencias=(("salud", Lack.DESPERATE),),
        recuerdos=(),
        aprecia=(),
        detesta=(),
        interlocutor="B",
        aprecio_al_interlocutor=0.0,
        relaciones_con_interlocutor=(),
    )
    assert tono_de_respaldo(f_triste) is Tone.SAD

    # 3. Seco si carencia severa (mucha)
    f_seco = Ficha(
        agente=ag_a,
        nombre="A",
        identidad=(),
        caracter=(),
        lugar="L",
        fase=None,
        actividad=None,
        de_camino_a=None,
        carencias=(("salud", Lack.SEVERE),),
        recuerdos=(),
        aprecia=(),
        detesta=(),
        interlocutor="B",
        aprecio_al_interlocutor=0.0,
        relaciones_con_interlocutor=(),
    )
    assert tono_de_respaldo(f_seco) is Tone.CURT

    # 4. Amable si carencias moderadas o leves
    f_amable = Ficha(
        agente=ag_a,
        nombre="A",
        identidad=(),
        caracter=(),
        lugar="L",
        fase=None,
        actividad=None,
        de_camino_a=None,
        carencias=(("salud", Lack.MODERATE),),
        recuerdos=(),
        aprecia=(),
        detesta=(),
        interlocutor="B",
        aprecio_al_interlocutor=0.0,
        relaciones_con_interlocutor=(),
    )
    assert tono_de_respaldo(f_amable) is Tone.FRIENDLY


def test_el_respaldo_es_reproducible() -> None:
    pack = pack_con_voz()
    world1 = WorldState.new(pack, seed=42)
    world2 = WorldState.new(pack, seed=42)
    ag = AgentId("agente_a")

    for _ in range(5):
        habla1, _, _ = hablar(world1, ag)
        habla2, _, _ = hablar(world2, ag)
        assert habla1 == habla2
        assert habla1.dice in pack.voice.fallback[habla1.tono]  # type: ignore[union-attr]


def test_sin_voice_y_sin_modelo_no_se_inventa_nada() -> None:
    pack = pack_con_voz(voice=None)
    world = WorldState.new(pack, seed=42)
    habla, del_modelo, _ = hablar(world, AgentId("agente_a"))
    assert del_modelo is False
    assert habla.dice == SIN_VOZ


def test_la_semilla_es_la_de_la_partida() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag = AgentId("agente_a")
    proveedor = ProveedorFalso(None)

    hablar(world, ag, proveedor=proveedor)
    assert len(proveedor.llamadas) == 1
    semilla_tick0 = proveedor.llamadas[0][1]

    # La semilla esperada se deriva por clave
    semilla_esperada = world.rng.stream("voz-semilla", ag, world.tick).randrange(2**31)
    assert semilla_tick0 == semilla_esperada

    # Cambia con el tick
    world.tick += 1
    hablar(world, ag, proveedor=proveedor)
    assert len(proveedor.llamadas) == 2
    semilla_tick1 = proveedor.llamadas[1][1]
    assert semilla_tick1 != semilla_tick0


def test_el_briefing_lleva_cada_hecho_de_la_ficha() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag_a = AgentId("agente_a")
    ag_b = AgentId("agente_b")

    a = world.agents[ag_a]
    a.busy = PerformingAction(action=pack.actions[0].id, ticks_remaining=10)
    a.needs[NeedId("energia")] = 0.05
    from agora.engine.state import Bond
    a.bonds[ag_b] = Bond(regard=0.5)

    _habla, _, texto = hablar(world, ag_a, interlocutor=ag_b)
    # Nombre
    assert "Agente A" in texto
    # Lugar
    assert "Posada" in texto
    # Actividad
    assert "Descansar" in texto
    # Carencias
    assert "desesperada Energía" in texto
    # Interlocutor
    assert "Agente B" in texto
    # Aprecia
    assert "Agente B" in texto


def test_hablar_no_cambia_el_mundo() -> None:
    pack = pack_con_voz()
    sim = Simulation(pack, seed=42)
    foto_antes = foto(sim)
    proveedor = ProveedorFalso(Habla(dice="Hola.", tono=Tone.FRIENDLY))
    _ = hablar(sim.state, AgentId("agente_a"), proveedor=proveedor)
    foto_despues = foto(sim)
    assert foto_antes == foto_despues


# -----------------------------------------------------------------------------
# B.4 — Pack y CLI
# -----------------------------------------------------------------------------


def test_un_rasgo_de_voz_desconocido_no_carga() -> None:
    # identity_traits con rasgo inexistente
    with pytest.raises(ValueError, match=r"voice.identity_traits"):
        pack_con_voz(voice={
            "identity_traits": ["rasgo_inexistente"],
            "character_traits": ["audaz"],
            "fallback": {"amable": ["Hola."]},
        })

    # character_traits con rasgo inexistente
    with pytest.raises(ValueError, match=r"voice.character_traits"):
        pack_con_voz(voice={
            "identity_traits": ["varon"],
            "character_traits": ["fantasma"],
            "fallback": {"amable": ["Hola."]},
        })


def test_un_tono_sin_frases_no_carga() -> None:
    with pytest.raises(ValueError, match=r"voice.fallback.amable: sin frases"):
        pack_con_voz(voice={
            "identity_traits": ["varon"],
            "character_traits": ["audaz"],
            "fallback": {"amable": []},
        })


def test_hablar_sin_llm_por_la_linea_de_ordenes(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Agente vivo con --sin-llm
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            "packs/confluencia/pack.yaml",
            "--days",
            "1",
            "--quiet",
            "--hablar",
            "eris_cenizal",
            "--sin-llm",
        ],
    )
    agora.run.main()
    out = capsys.readouterr().out
    assert "(respaldo)" in out
    assert "eris_cenizal habla" in out

    # 2. Agente muerto o inexistente -> SystemExit
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            "packs/confluencia/pack.yaml",
            "--days",
            "1",
            "--quiet",
            "--hablar",
            "no_existe",
            "--sin-llm",
        ],
    )
    with pytest.raises(SystemExit, match="--hablar: 'no_existe' no está vivo"):
        agora.run.main()


def test_hablar_no_cambia_el_log(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    ruta1 = tmp_path / "sin_hablar.jsonl"
    ruta2 = tmp_path / "con_hablar.jsonl"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            "packs/confluencia/pack.yaml",
            "--days",
            "1",
            "--quiet",
            "--jsonl",
            str(ruta1),
        ],
    )
    agora.run.main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            "packs/confluencia/pack.yaml",
            "--days",
            "1",
            "--quiet",
            "--jsonl",
            str(ruta2),
            "--hablar",
            "eris_cenizal",
            "--sin-llm",
        ],
    )
    agora.run.main()

    assert ruta1.read_bytes() == ruta2.read_bytes()
