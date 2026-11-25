"""Pruebas de creación de personaje: reglas, azar y partida (plan 21a, §B)."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import yaml

from agora.engine.newcomer import (
    CreationChoice,
    CreationError,
    build_sheet,
    load_sheet,
    newcomer_spec,
    roll_potentials,
)
from agora.engine.ontology import TraitId
from agora.engine.pack import PackError, load_pack
from agora.engine.world import Simulation
from agora.ui.server import Servidor
from agora.ui.session import Partidas, creacion

CONFLUENCIA = Path("packs/confluencia/pack.yaml")
CIUDAD = Path("packs/ciudad/pack.yaml")


@pytest.fixture
def servidor_local() -> Generator[tuple[Servidor, int], None, None]:
    servidor = Servidor(0)
    puerto = servidor.server_address[1]
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield servidor, puerto
    finally:
        if servidor.partidas.actual is not None:
            servidor.partidas.actual.cerrar()
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=2.0)


# ===========================================================================
# B.1 — Reglas
# ===========================================================================


def test_b1_1_puntos_presupuesto_exacto_y_exceso() -> None:
    # B.1.1: Puntos: pasarse del presupuesto de la dificultad -> CreationError con la cifra;
    # justo en el presupuesto -> vale.
    pack = load_pack(CONFLUENCIA)
    assert pack.creation is not None

    grupos_base = (TraitId("varon"), TraitId("humano"), TraitId("guerrero"))
    # En dificultad "dificil", el presupuesto es 3.10.
    # 6 potenciales a 0.50 (3.00) + 1 potencial a 0.10 = 3.10 exactos.
    pots_exactos = {
        TraitId("fuerza"): 0.5,
        TraitId("agilidad"): 0.5,
        TraitId("ingenio"): 0.5,
        TraitId("instinto"): 0.5,
        TraitId("voluntad"): 0.5,
        TraitId("presencia"): 0.5,
        TraitId("resonancia"): 0.1,
    }
    eleccion_exacta = CreationChoice(
        name="Exacto",
        mode="points",
        difficulty="dificil",
        groups=grupos_base,
        potentials=pots_exactos,
    )
    ficha, _ = build_sheet(pack, eleccion_exacta, seed=1)
    assert ficha.label == "Exacto"
    assert ficha.traits[TraitId("fuerza")] == 0.5
    assert ficha.traits[TraitId("resonancia")] == 0.1

    # Pasarse del presupuesto: 3.15 gastados frente a 3.10 de presupuesto
    pots_exceso = dict(pots_exactos)
    pots_exceso[TraitId("resonancia")] = 0.15
    eleccion_exceso = CreationChoice(
        name="Excedido",
        mode="points",
        difficulty="dificil",
        groups=grupos_base,
        potentials=pots_exceso,
    )
    with pytest.raises(CreationError) as exc_info:
        build_sheet(pack, eleccion_exceso, seed=1)

    error_msg = str(exc_info.value)
    assert "3.15" in error_msg
    assert "3.10" in error_msg
    assert "presupuesto" in error_msg


def test_b1_2_modo_libre_sin_presupuesto_pero_fuera_de_rango_falla() -> None:
    # B.1.2: Libre: sin presupuesto, pero fuera de rango -> error.
    pack = load_pack(CONFLUENCIA)
    assert pack.creation is not None
    assert pack.creation.potentials is not None
    grupos_base = (TraitId("varon"), TraitId("humano"), TraitId("guerrero"))

    # Libre sin límite de presupuesto: todos al máximo 1.0 (suma = 7.0) se acepta
    pots_maximos = {t: 1.0 for t in pack.creation.potentials.traits}
    eleccion_alta = CreationChoice(
        name="Poderoso",
        mode="free",
        groups=grupos_base,
        potentials=pots_maximos,
    )
    ficha, _ = build_sheet(pack, eleccion_alta, seed=1)
    assert ficha.traits[TraitId("fuerza")] == 1.0

    # Potencial fuera de rango superior (> max 1.0)
    eleccion_pot_alto = CreationChoice(
        name="Invalido",
        mode="free",
        groups=grupos_base,
        potentials={TraitId("fuerza"): 1.2},
    )
    with pytest.raises(CreationError, match=r"no vale; va de 0\.1 a 1\.0"):
        build_sheet(pack, eleccion_pot_alto, seed=1)

    # Potencial fuera de rango inferior (< min 0.1)
    eleccion_pot_bajo = CreationChoice(
        name="Invalido",
        mode="free",
        groups=grupos_base,
        potentials={TraitId("fuerza"): 0.05},
    )
    with pytest.raises(CreationError, match=r"no vale; va de 0\.1 a 1\.0"):
        build_sheet(pack, eleccion_pot_bajo, seed=1)

    # Potencial fuera de paso (no múltiplo de step 0.05)
    eleccion_paso = CreationChoice(
        name="Invalido",
        mode="free",
        groups=grupos_base,
        potentials={TraitId("fuerza"): 0.33},
    )
    with pytest.raises(CreationError, match=r"en pasos de 0\.05"):
        build_sheet(pack, eleccion_paso, seed=1)

    # Carácter fuera del rango declarado por el mundo (audacia en confluencia [-0.85, 0.91])
    eleccion_caracter_fuera = CreationChoice(
        name="Invalido",
        mode="free",
        groups=grupos_base,
        character={TraitId("audacia"): 0.99},
    )
    with pytest.raises(CreationError, match=r"audacia: 0\.99 queda fuera de"):
        build_sheet(pack, eleccion_caracter_fuera, seed=1)


def test_b1_3_grupo_obligatorio_sin_elegir_dos_del_mismo_y_rasgo_ajeno() -> None:
    # B.1.3: Grupo obligatorio sin elegir, dos del mismo grupo, un rasgo que no está
    # en ningún sitio (ej. nombrado) -> error.
    pack = load_pack(CONFLUENCIA)
    assert pack.creation is not None

    # 1. Grupo obligatorio sin elegir (falta "oficio")
    eleccion_sin_oficio = CreationChoice(
        name="Incompleto",
        mode="free",
        groups=(TraitId("varon"), TraitId("humano")),
    )
    with pytest.raises(CreationError, match="falta elegir «oficio»"):
        build_sheet(pack, eleccion_sin_oficio, seed=1)

    # 2. Dos del mismo grupo ("varon" y "mujer" en sexo)
    eleccion_dos_sexos = CreationChoice(
        name="Doble",
        mode="free",
        groups=(TraitId("varon"), TraitId("mujer"), TraitId("humano"), TraitId("guerrero")),
    )
    with pytest.raises(CreationError, match="en «sexo» se elige uno, y elegiste 2"):
        build_sheet(pack, eleccion_dos_sexos, seed=1)

    # 3. Un rasgo que no está en la sección de creación (ej. "nombrado") en grupos
    eleccion_nombrado_en_grupo = CreationChoice(
        name="Ajeno",
        mode="free",
        groups=(
            TraitId("varon"),
            TraitId("humano"),
            TraitId("guerrero"),
            TraitId("nombrado"),
        ),
    )
    with pytest.raises(CreationError, match="'nombrado' no es una elección de este mundo"):
        build_sheet(pack, eleccion_nombrado_en_grupo, seed=1)

    # 4. Un rasgo ajeno (ej. "nombrado") en character
    eleccion_nombrado_en_char = CreationChoice(
        name="Ajeno",
        mode="free",
        groups=(TraitId("varon"), TraitId("humano"), TraitId("guerrero")),
        character={TraitId("nombrado"): 0.5},
    )
    with pytest.raises(CreationError, match="'nombrado' no se elige al crear"):
        build_sheet(pack, eleccion_nombrado_en_char, seed=1)


def test_b1_4_pack_con_creation_mal_formada_no_carga(tmp_path: Path) -> None:
    # B.1.4: Pack con creation mal formada no carga (grupos que se solapan, chance 0,
    # presupuesto imposible).
    raw_text = CONFLUENCIA.read_text(encoding="utf-8")
    base: dict[str, Any] = yaml.safe_load(raw_text)

    # 1. Grupos que se solapan: dos grupos comparten el rasgo "varon"
    p1 = dict(base)
    cre1 = dict(base["creation"])
    cre1["groups"] = [
        *base["creation"]["groups"],
        {"id": "otro_grupo", "label": "otro", "traits": ["varon"], "required": False},
    ]
    p1["creation"] = cre1
    f1 = tmp_path / "solapado.yaml"
    f1.write_text(yaml.safe_dump(p1), encoding="utf-8")
    with pytest.raises(PackError, match="el rasgo 'varon' aparece en"):
        load_pack(f1)

    # 2. Chance 0 en rare (violación de validación del modelo gt=0.0)
    p2 = dict(base)
    cre2 = dict(base["creation"])
    cre2["rare"] = dict(base["creation"]["rare"])
    cre2["rare"]["talento"] = {"chance": 0.0, "min": 0.4, "max": 0.8}
    p2["creation"] = cre2
    f2 = tmp_path / "chance_cero.yaml"
    f2.write_text(yaml.safe_dump(p2), encoding="utf-8")
    with pytest.raises(PackError, match="chance"):
        load_pack(f2)

    # 3. Presupuesto imposible: mayor que max * n (7 * 1.0 = 7.00)
    p3 = dict(base)
    cre3 = dict(base["creation"])
    cre3["budgets"] = dict(base["creation"]["budgets"])
    cre3["budgets"]["imposible"] = 10.0
    p3["creation"] = cre3
    f3 = tmp_path / "presupuesto_imposible.yaml"
    f3.write_text(yaml.safe_dump(p3), encoding="utf-8")
    with pytest.raises(PackError, match="quedan fuera de"):
        load_pack(f3)


# ===========================================================================
# B.2 — Azar
# ===========================================================================


def test_b2_1_tirada_reproducible_por_semilla_nombre_y_pythonhashseed() -> None:
    # B.2.1: Tirada: misma semilla y nombre -> mismos potenciales; otra semilla -> otros.
    # Con PYTHONHASHSEED variable, iguales.
    pack = load_pack(CONFLUENCIA)

    t1 = roll_potentials(pack, "Aventurero", 100)
    t2 = roll_potentials(pack, "Aventurero", 100)
    t_otra_semilla = roll_potentials(pack, "Aventurero", 200)
    t_otro_nombre = roll_potentials(pack, "Mercenario", 100)

    # Misma semilla y nombre -> idénticos
    assert t1 == t2
    # Otra semilla -> otros
    assert t1 != t_otra_semilla
    # Mismo seed pero otro nombre -> otros
    assert t1 != t_otro_nombre

    # Subproceso con PYTHONHASHSEED variable (0 y 1)
    codigo_hijo = """
import sys
from pathlib import Path
from agora.engine.pack import load_pack
from agora.engine.newcomer import roll_potentials
pack = load_pack(Path(sys.argv[1]))
pots = roll_potentials(pack, "Aventurero", 100)
print(sorted(pots.items()))
"""
    src_dir = str(Path(__file__).resolve().parents[1] / "src")
    pack_path = str(CONFLUENCIA.resolve())
    salidas = [
        subprocess.run(
            [sys.executable, "-c", codigo_hijo, pack_path],
            env={**os.environ, "PYTHONHASHSEED": hseed, "PYTHONPATH": src_dir},
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        for hseed in ("0", "1")
    ]
    assert salidas[0] == salidas[1]


def test_b2_2_frecuencia_de_raros_y_no_elegibles_a_mano() -> None:
    # B.2.2: Raros: frecuencia en 10 000 creaciones a ±30 % de lo declarado;
    # un raro no puede elegirse a mano.
    pack = load_pack(CONFLUENCIA)
    assert pack.creation is not None

    grupos_base = (TraitId("varon"), TraitId("humano"), TraitId("guerrero"))

    # 1. Un raro no puede elegirse a mano (character, groups o potentials)
    with pytest.raises(CreationError, match="'talento' no se elige al crear"):
        build_sheet(
            pack,
            CreationChoice(
                name="Trampa",
                mode="free",
                groups=grupos_base,
                character={TraitId("talento"): 0.6},
            ),
            seed=1,
        )

    with pytest.raises(CreationError, match="'prodigio' no es una elección de este mundo"):
        build_sheet(
            pack,
            CreationChoice(
                name="Trampa",
                mode="free",
                groups=(*grupos_base, TraitId("prodigio")),
            ),
            seed=1,
        )

    with pytest.raises(CreationError, match="'dureza' no es un potencial de este mundo"):
        build_sheet(
            pack,
            CreationChoice(
                name="Trampa",
                mode="free",
                groups=grupos_base,
                potentials={TraitId("dureza"): 0.5},
            ),
            seed=1,
        )

    # 2. Frecuencia en 10 000 creaciones a ±30 % de lo declarado
    # talento: 0.015 -> 150 esperado [105, 195]
    # prodigio: 0.030 -> 300 esperado [210, 390]
    # dureza: 0.050 -> 500 esperado [350, 650]
    eleccion = CreationChoice(
        name="Muestra",
        mode="free",
        groups=grupos_base,
        potentials={TraitId("fuerza"): 0.5},
    )
    conteo: dict[TraitId, int] = {t: 0 for t in pack.creation.rare}
    for seed in range(10000):
        _, otorgados = build_sheet(pack, eleccion, seed)
        for t in otorgados:
            conteo[t] += 1

    t_talento = conteo[TraitId("talento")]
    t_prodigio = conteo[TraitId("prodigio")]
    t_dureza = conteo[TraitId("dureza")]

    assert 105 <= t_talento <= 195, f"talento {t_talento} fuera de rango [105, 195]"
    assert 210 <= t_prodigio <= 390, f"prodigio {t_prodigio} fuera de rango [210, 390]"
    assert 350 <= t_dureza <= 650, f"dureza {t_dureza} fuera de rango [350, 650]"


def test_b2_3_tirada_en_confluencia_media_de_la_suma() -> None:
    # B.2.3: Tirada en confluencia: media de la suma a 3.65 ± 0.1.
    pack = load_pack(CONFLUENCIA)

    n_muestras = 10000
    suma_total = sum(
        sum(roll_potentials(pack, "Personaje", s).values())
        for s in range(n_muestras)
    )
    media = suma_total / n_muestras
    assert 3.55 <= media <= 3.75, f"media de tirada {media:.4f} fuera de 3.65 ± 0.1"


# ===========================================================================
# B.3 — Partida
# ===========================================================================


def test_b3_1_ficha_creada_entra_por_newcomer_spec_con_elegidos_y_raros() -> None:
    # B.3.1: La ficha creada entra por newcomer_spec; el personaje aparece con rasgos
    # elegidos más los raros.
    pack = load_pack(CONFLUENCIA)

    # La semilla 8 otorga 'dureza' (0.5199) para el nombre "Valeroso"
    eleccion = CreationChoice(
        name="Valeroso",
        mode="points",
        difficulty="normal",
        groups=(
            TraitId("varon"),
            TraitId("humano"),
            TraitId("guerrero"),
            TraitId("afin_fuego"),
        ),
        potentials={
            TraitId("fuerza"): 0.6,
            TraitId("agilidad"): 0.55,
            TraitId("ingenio"): 0.5,
            TraitId("instinto"): 0.5,
            TraitId("voluntad"): 0.5,
            TraitId("presencia"): 0.5,
            TraitId("resonancia"): 0.5,
        },
        character={TraitId("audacia"): 0.4},
    )
    ficha, raros = build_sheet(pack, eleccion, seed=8)
    assert TraitId("dureza") in raros
    assert ficha.traits[TraitId("dureza")] == raros[TraitId("dureza")]

    sim = Simulation(pack, seed=8)
    agente_spec = newcomer_spec(pack, ficha, taken=sim.state.censo)
    sim.arrive(agente_spec)

    agente = sim.state.agents[agente_spec.id]
    # Rasgos de grupo a 1.0
    assert agente.traits[TraitId("varon")] == 1.0
    assert agente.traits[TraitId("humano")] == 1.0
    assert agente.traits[TraitId("guerrero")] == 1.0
    assert agente.traits[TraitId("afin_fuego")] == 1.0
    # Potencial elegido
    assert agente.traits[TraitId("fuerza")] == 0.6
    # Carácter elegido
    assert agente.traits[TraitId("audacia")] == 0.4
    # Raro otorgado por azar
    assert agente.traits[TraitId("dureza")] == raros[TraitId("dureza")]


def test_b3_2_guardada_en_partidas_y_cargada_con_jugar_ficha() -> None:
    # B.3.2: Guardada en partidas/ y cargada con --jugar-ficha: mismo personaje.
    pack = load_pack(CONFLUENCIA)
    partidas = Partidas()

    pedido: dict[str, Any] = {
        "mundo": "confluencia",
        "semilla": 42,
        "modelo": False,
        "crear": {
            "name": "Arturo",
            "mode": "free",
            "groups": ["varon", "humano", "guerrero"],
            "potentials": {"fuerza": 0.7, "agilidad": 0.6},
            "character": {"audacia": 0.3},
        },
    }
    partida = partidas.empezar(pedido)
    ficha_path = (
        partida.grabar.parent / "ficha.yaml"
        if (partida.grabar.parent / "ficha.yaml").exists()
        else partida.grabar.with_suffix(".ficha.yaml")
    )

    try:
        assert ficha_path.exists(), f"La ficha no se guardó en {ficha_path}"
        ficha_cargada = load_sheet(ficha_path)
        assert ficha_cargada.label == "Arturo"
        assert ficha_cargada.traits[TraitId("varon")] == 1.0
        assert ficha_cargada.traits[TraitId("fuerza")] == 0.7

        # Otra simulación iniciada cargando esa ficha (como hace --jugar-ficha)
        sim_otra = Simulation(pack, seed=42)
        spec_otra = newcomer_spec(pack, ficha_cargada, taken=sim_otra.state.censo)
        sim_otra.arrive(spec_otra)

        agente_creado = partida.sim.state.agents[spec_otra.id]
        agente_cargado = sim_otra.state.agents[spec_otra.id]

        assert agente_creado.traits == agente_cargado.traits
    finally:
        partida.cerrar()
        if partida.grabar.exists():
            partida.grabar.unlink()
        if ficha_path.exists():
            ficha_path.unlink()


def test_b3_3_api_creacion_sin_seccion_y_creation_error_400(
    servidor_local: tuple[Servidor, int],
) -> None:
    # B.3.3: API: creacion de un mundo sin sección -> no se ofrece; CreationError -> 400.
    _, puerto = servidor_local
    conn = http.client.HTTPConnection("127.0.0.1", puerto)

    # 1. Función de consulta: mundo sin creación (ciudad) -> disponible False
    assert creacion("ciudad") == {"disponible": False}

    # 2. GET /api/mundos/ciudad/creacion -> {"disponible": False}
    conn.request("GET", "/api/mundos/ciudad/creacion")
    res_ciudad = conn.getresponse()
    assert res_ciudad.status == 200
    assert json.loads(res_ciudad.read()) == {"disponible": False}

    # 3. GET /api/mundos/confluencia/creacion -> disponible con grupos y potenciales
    conn.request("GET", "/api/mundos/confluencia/creacion")
    res_conf = conn.getresponse()
    assert res_conf.status == 200
    data_conf = json.loads(res_conf.read())
    assert data_conf["disponible"] is True
    assert len(data_conf["grupos"]) >= 3
    assert data_conf["potenciales"] is not None

    # 4. POST /api/tirada -> dados sorteados
    conn.request(
        "POST",
        "/api/tirada",
        json.dumps({"mundo": "confluencia", "nombre": "Prueba", "semilla": 1}).encode("utf-8"),
    )
    res_tirada = conn.getresponse()
    assert res_tirada.status == 200
    tirada_data = json.loads(res_tirada.read())
    assert len(tirada_data["potenciales"]) == 7

    # 5. POST /api/partida con CreationError -> código 400 y mensaje
    bad_crear = {
        "mundo": "confluencia",
        "semilla": 1,
        "modelo": False,
        "crear": {
            "name": "Ilegal",
            "mode": "points",
            "difficulty": "dificil",
            "groups": ["varon", "humano", "guerrero"],
            "potentials": {
                "fuerza": 1.0,
                "agilidad": 1.0,
                "ingenio": 1.0,
                "instinto": 1.0,
                "voluntad": 1.0,
                "presencia": 1.0,
                "resonancia": 1.0,
            },
        },
    }
    conn.request(
        "POST",
        "/api/partida",
        json.dumps(bad_crear).encode("utf-8"),
    )
    res_bad = conn.getresponse()
    assert res_bad.status == 400
    cuerpo_error = json.loads(res_bad.read())
    assert "presupuesto" in cuerpo_error.get("error", "")
