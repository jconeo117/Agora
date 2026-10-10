"""Pruebas de la ficha del forastero y su integración con el pack (unidad 10, §B.2)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from agora.engine.newcomer import (
    NewcomerError,
    NewcomerSheet,
    load_sheet,
    newcomer_spec,
)
from agora.engine.ontology import (
    ActionId,
    AgentId,
    NeedId,
    PlaceId,
    TasteSpec,
    TraitId,
)
from agora.engine.pack import ContentPack, PackError, load_pack
from agora.engine.state import AgentState

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
CIUDAD_PACK = Path("packs/ciudad/pack.yaml")
FORASTERO_YAML = Path("packs/confluencia/forastero.yaml")


def test_la_ficha_gana_al_pack() -> None:
    # con newcomer en el pack, lo que la ficha dice gana campo a campo y,
    # en initial_needs y traits, clave a clave; lo que ninguno dice sale
    # del initial de la necesidad.
    pack = load_pack(CONFLUENCIA_PACK)
    assert pack.newcomer is not None

    sheet = NewcomerSheet(
        id=AgentId("viajero"),
        label="El Viajero",
        home=PlaceId("posada_central"),
        start_at=PlaceId("plaza_mayor"),  # Gana al start_at del pack (puerta_norte)
        traits={TraitId("audacia"): 0.9, TraitId("curiosidad"): 0.8},
        initial_needs={NeedId("dinero"): 0.50},  # Gana a dinero 0.25 del pack
        edad_inicial=35,
    )

    spec = newcomer_spec(pack, sheet, taken=set())

    # Campos simples: gana la ficha
    assert spec.start_at == PlaceId("plaza_mayor")
    assert spec.edad_inicial == 35

    # En traits: mezcla, gana la ficha clave a clave
    assert spec.traits[TraitId("audacia")] == 0.9
    assert spec.traits[TraitId("curiosidad")] == 0.8
    # Trait que solo estaba en pack.newcomer
    if pack.newcomer.traits:
        for t, v in pack.newcomer.traits.items():
            if t not in sheet.traits:
                assert spec.traits[t] == v

    # En initial_needs: mezcla, gana la ficha
    assert spec.initial_needs[NeedId("dinero")] == 0.50

    # Lo que ninguno dice sale del initial de la necesidad al crear el agente
    agente = AgentState.from_spec(pack, spec)
    assert agente.needs[NeedId("dinero")] == 0.50
    sustento_id = NeedId("sustento")
    sustento_spec = pack.need_by_id[sustento_id]
    if (
        sustento_id not in sheet.initial_needs
        and (pack.newcomer is None or sustento_id not in pack.newcomer.initial_needs)
    ):
        assert agente.needs[sustento_id] == sustento_spec.initial


def test_sin_hogar_no_se_llega() -> None:
    # ni la ficha ni el pack dicen home → NewcomerError. Sin start_at, empieza en casa.
    pack = load_pack(CIUDAD_PACK)  # Ciudad no tiene newcomer configurado
    assert pack.newcomer is None

    # 1. Ni ficha ni pack dicen home -> NewcomerError
    sheet_sin_hogar = NewcomerSheet(id=AgentId("sin_casa"), label="Sin Casa")
    with pytest.raises(NewcomerError, match=r"ni la ficha ni el pack.*dicen dónde vive"):
        newcomer_spec(pack, sheet_sin_hogar, taken=set())

    # 2. Sin start_at, empieza en casa
    lugar_valido = pack.places[0].id
    sheet_con_hogar = NewcomerSheet(
        id=AgentId("con_casa"),
        label="Con Casa",
        home=lugar_valido,
        start_at=None,
    )
    spec = newcomer_spec(pack, sheet_con_hogar, taken=set())
    assert spec.home == lugar_valido
    assert spec.start_at == lugar_valido


def test_la_ficha_pasa_la_puerta_del_pack() -> None:
    # un rasgo, un lugar, una necesidad o un gusto desconocidos → NewcomerError
    # con el mensaje del pack. Un id ya usado → NewcomerError.
    pack = load_pack(CONFLUENCIA_PACK)

    # 1. Id ya usado
    id_existente = pack.agents[0].id
    sheet_id_usado = NewcomerSheet(id=id_existente, label="Clon")
    with pytest.raises(NewcomerError, match="ya existe en esta partida"):
        newcomer_spec(pack, sheet_id_usado, taken={id_existente})

    # 2. Rasgo desconocido
    sheet_rasgo_raro = NewcomerSheet(
        id=AgentId("raro1"), label="Raro", traits={TraitId("rasgo_inexistente"): 1.0}
    )
    with pytest.raises(NewcomerError, match="no cabe en el pack"):
        newcomer_spec(pack, sheet_rasgo_raro, taken=set())

    # 3. Lugar desconocido en home
    sheet_lugar_raro = NewcomerSheet(
        id=AgentId("raro2"), label="Raro", home=PlaceId("lugar_fantasma")
    )
    with pytest.raises(NewcomerError, match="no cabe en el pack"):
        newcomer_spec(pack, sheet_lugar_raro, taken=set())

    # 4. Necesidad desconocida en initial_needs
    sheet_need_rara = NewcomerSheet(
        id=AgentId("raro3"), label="Raro", initial_needs={NeedId("magia"): 0.5}
    )
    with pytest.raises(NewcomerError, match="no cabe en el pack"):
        newcomer_spec(pack, sheet_need_rara, taken=set())

    # 5. Gusto hacia objetivo desconocido
    gusto = TasteSpec(target=ActionId("accion_fantasma"), multiplier=0.5)
    sheet_gusto_raro = NewcomerSheet(
        id=AgentId("raro4"), label="Raro", tastes=(gusto,)
    )
    with pytest.raises(NewcomerError, match="no cabe en el pack"):
        newcomer_spec(pack, sheet_gusto_raro, taken=set())


def test_newcomer_se_valida_al_cargar() -> None:
    # un newcomer con un lugar, una necesidad o un rasgo desconocidos hace que el pack no cargue.
    pack = load_pack(CONFLUENCIA_PACK)
    base_data = pack.model_dump()

    # Lugar desconocido
    data_lugar = copy.deepcopy(base_data)
    data_lugar["newcomer"] = {"home": "lugar_invalido"}
    with pytest.raises((PackError, ValidationError), match="lugar desconocid"):
        ContentPack.model_validate(data_lugar)

    # Rasgo desconocido
    data_rasgo = copy.deepcopy(base_data)
    data_rasgo["newcomer"] = {
        "home": "posada_central",
        "traits": {"rasgo_invalido": 1.0},
    }
    with pytest.raises((PackError, ValidationError), match="rasgo desconocid"):
        ContentPack.model_validate(data_rasgo)

    # Necesidad desconocida
    data_need = copy.deepcopy(base_data)
    data_need["newcomer"] = {
        "home": "posada_central",
        "initial_needs": {"necesidad_invalida": 0.5},
    }
    with pytest.raises((PackError, ValidationError), match="necesidad desconocid"):
        ContentPack.model_validate(data_need)


def test_la_ficha_de_ejemplo_de_confluencia() -> None:
    # forastero.yaml da un agente con hogar posada_central, empieza en puerta_norte,
    # dinero a 0.25 y los rasgos de la ficha.
    pack = load_pack(CONFLUENCIA_PACK)
    sheet = load_sheet(FORASTERO_YAML)

    spec = newcomer_spec(pack, sheet, taken=set())
    assert spec.id == AgentId("forastero")
    assert spec.home == PlaceId("posada_central")
    assert spec.start_at == PlaceId("puerta_norte")
    assert spec.initial_needs.get(NeedId("dinero")) == 0.25

    agente = AgentState.from_spec(pack, spec)
    assert agente.needs[NeedId("dinero")] == 0.25
    assert agente.traits[TraitId("curiosidad")] == 0.7
    assert agente.traits[TraitId("audacia")] == 0.6
    assert agente.traits[TraitId("humano")] == 1.0
    assert agente.traits[TraitId("varon")] == 1.0
