"""Pruebas de la capa de consulta (Ficha y carencias)."""

from __future__ import annotations

from typing import Any

import pytest

from agora.engine.consulta import Lack, banda, ficha
from agora.engine.events import EventKind
from agora.engine.memory import Recuerdo
from agora.engine.ontology import AgentId, NeedId, RelationId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.state import WorldState
from agora.engine.world import Simulation
from tests.test_reanudar import foto


def pack_con_voz(**overrides: Any) -> ContentPack:
    data: dict[str, Any] = {
        "id": "voz_pack",
        "label": "Pack con Voz",
        "clock": {"ticks_per_day": 24, "days_per_year": 1},
        "needs": [
            {"id": "salud", "label": "Salud", "decay_per_tick": 0.01},
            {"id": "energia", "label": "Energía", "decay_per_tick": 0.01},
            {"id": "diversion", "label": "Diversión", "decay_per_tick": 0.01},
            {
                "id": "experiencia",
                "label": "Experiencia",
                "decay_per_tick": 0.0,
                "progression": True,
            },
        ],
        "traits": [
            {"id": "varon", "label": "Varón"},
            {"id": "mujer", "label": "Mujer"},
            {"id": "audaz", "label": "Audaz"},
            {"id": "constante", "label": "Constante"},
            {"id": "impulsivo", "label": "Impulsivo"},
            {"id": "curioso", "label": "Curioso"},
            {"id": "docil", "label": "Dócil"},
        ],
        "places": [
            {
                "id": "posada",
                "label": "Posada",
                "affordances": ["descansar"],
                "neighbors": {},
            }
        ],
        "actions": [
            {
                "id": "descansar",
                "label": "Descansar",
                "duration_ticks": 1,
                "satisfies": {"energia": 1.0},
            }
        ],
        "relations": [
            {
                "id": "amigos",
                "label": "Amigos",
                "regard_floor": 0.2,
                "exclusive": False,
            }
        ],
        "voice": {
            "identity_traits": ["varon", "mujer"],
            "character_traits": ["audaz", "constante", "impulsivo", "curioso", "docil"],
            "fallback": {
                "amable": [f"Qué tal {i}." for i in range(20)],
                "seco": ["Déjame."],
                "hostil": ["Fuera."],
                "triste": ["Mal día."],
                "asustado": ["Socorro."],
            },
        },
        "agents": [
            {
                "id": "agente_a",
                "label": "Agente A",
                "home": "posada",
                "start_at": "posada",
                "traits": {"varon": 1.0, "audaz": 0.9, "constante": 0.5, "impulsivo": 0.35},
            },
            {
                "id": "agente_b",
                "label": "Agente B",
                "home": "posada",
                "start_at": "posada",
                "traits": {"mujer": 1.0, "curioso": 0.8},
            },
        ],
    }
    data.update(overrides)
    return ContentPack.model_validate(data)


def test_la_ficha_no_cambia_el_mundo() -> None:
    pack = pack_con_voz()
    sim = Simulation(pack, seed=42)
    foto_antes = foto(sim)
    _ = ficha(sim.state, AgentId("agente_a"))
    foto_despues = foto(sim)
    assert foto_antes == foto_despues


def test_las_carencias_son_las_dos_mas_bajas_en_orden() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    a = world.agents[AgentId("agente_a")]
    # experiencia tiene 0.01 pero es progression=True -> no debe salir
    a.needs[NeedId("experiencia")] = 0.01
    a.needs[NeedId("salud")] = 0.30
    a.needs[NeedId("energia")] = 0.05
    a.needs[NeedId("diversion")] = 0.80

    f = ficha(world, AgentId("agente_a"))
    # Las dos más bajas sin progresión son energia (0.05) y salud (0.30)
    assert len(f.carencias) == 2
    assert f.carencias[0] == ("Energía", Lack.DESPERATE)
    assert f.carencias[1] == ("Salud", Lack.MODERATE)


def test_las_bandas() -> None:
    assert banda(0.09) is Lack.DESPERATE
    assert banda(0.1) is Lack.SEVERE
    assert banda(0.249) is Lack.SEVERE
    assert banda(0.25) is Lack.MODERATE
    assert banda(0.449) is Lack.MODERATE
    assert banda(0.45) is Lack.MILD
    assert banda(0.9) is Lack.MILD


def test_el_caracter_son_los_tres_mas_marcados_desde_0_3() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    a = world.agents[AgentId("agente_a")]
    a.traits[TraitId("audaz")] = 0.90
    a.traits[TraitId("constante")] = 0.50
    a.traits[TraitId("impulsivo")] = 0.30
    a.traits[TraitId("curioso")] = 0.29
    a.traits[TraitId("docil")] = 0.20
    # Identidad con valor alto: no debe salir en caracter
    a.traits[TraitId("varon")] = 1.0

    f = ficha(world, AgentId("agente_a"))
    assert f.caracter == ("Audaz", "Constante", "Impulsivo")
    assert "Varón" not in f.caracter
    assert "Dócil" not in f.caracter


def test_la_identidad_sale_si_la_tiene() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    f_a = ficha(world, AgentId("agente_a"))
    assert "Varón" in f_a.identidad
    assert "Mujer" not in f_a.identidad

    f_b = ficha(world, AgentId("agente_b"))
    assert "Mujer" in f_b.identidad
    assert "Varón" not in f_b.identidad


def test_sin_voice_no_se_nombra_ningun_rasgo() -> None:
    pack = pack_con_voz(voice=None)
    world = WorldState.new(pack, seed=42)
    f = ficha(world, AgentId("agente_a"))
    assert f.identidad == ()
    assert f.caracter == ()


def test_con_interlocutor_los_recuerdos_son_sobre_el() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag_a = AgentId("agente_a")
    ag_b = AgentId("agente_b")

    # Grabar un recuerdo sobre ag_b y otro sobre alguien desconocido
    rec_b = Recuerdo(
        tick=1,
        kind=EventKind.ENCOUNTER,
        action=None,
        place=None,
        about=ag_b,
        valencia=0.5,
        importancia=0.8,
        seq=1,
    )
    rec_otro = Recuerdo(
        tick=2,
        kind=EventKind.ENCOUNTER,
        action=None,
        place=None,
        about=AgentId("otro"),
        valencia=-0.2,
        importancia=0.9,
        seq=2,
    )
    world.memoria.cargar(ag_a, [rec_otro, rec_b])

    f_sin = ficha(world, ag_a)
    assert len(f_sin.recuerdos) == 2

    # Con interlocutor ag_b, la pista filtra/prioriza los recuerdos sobre ag_b
    f_con = ficha(world, ag_a, interlocutor=ag_b)
    assert len(f_con.recuerdos) >= 1
    assert f_con.recuerdos[0].persona == world.censo[ag_b].label


def test_aprecia_y_detesta() -> None:
    from agora.engine.state import Bond

    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    ag_a = AgentId("agente_a")
    ag_b = AgentId("agente_b")
    ag_c = AgentId("agente_c")

    # Agente A tiene vínculo con B y suelo de amigos (0.2)
    world.agents[ag_a].bonds[ag_b] = Bond(regard=0.0)
    world.agents[ag_a].relations[RelationId("amigos")] = {ag_b}

    # Agente A tiene vínculo negativo con C
    world.agents[ag_a].bonds[ag_c] = Bond(regard=-0.5)

    f = ficha(world, ag_a)
    assert world.censo[ag_b].label in f.aprecia
    assert "agente_c" in f.detesta
    assert world.censo[ag_b].label not in f.detesta


def test_un_muerto_no_tiene_ficha() -> None:
    pack = pack_con_voz()
    world = WorldState.new(pack, seed=42)
    with pytest.raises(KeyError):
        ficha(world, AgentId("no_existe"))
