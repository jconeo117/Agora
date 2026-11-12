"""Pruebas de la raíz del proyecto y forasteros en la UI (unidad 20b-fix, §B).

Verifica:
- B.1: Con monkeypatch.chdir(tmp_path): mundos() da los mismos que desde la raíz.
- B.2: Con una raíz falsa en tmp_path (con packs/ y rules/) y la carpeta actual
       dentro de ella, en un subdirectorio: se elige esa raíz, no la del repositorio.
- B.3: personajes('confluencia')['forasteros'] incluye forastero.yaml; un mundo
       con forastero.yaml y fichas/otro.yaml da los dos, sin repetir.
- B.4: Una partida empezada desde otra carpeta graba su guion en <raíz>/partidas/.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from agora.run import raiz_del_proyecto
from agora.ui.session import Partidas, mundos, personajes


def _esperar_hasta(cond: Callable[[], bool], plazo: float = 3.0, paso: float = 0.02) -> bool:
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(paso)
    return cond()


def test_mundos_desde_otra_carpeta_da_los_mismos_que_desde_la_raiz(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # B.1: Con monkeypatch.chdir(tmp_path): mundos() da los mismos que desde la raíz.
    mundos_raiz = mundos()
    assert len(mundos_raiz) > 0, "debe haber mundos registrados desde la raíz"

    monkeypatch.chdir(tmp_path)
    mundos_otra_carpeta = mundos()

    assert mundos_otra_carpeta == mundos_raiz
    assert len(mundos_otra_carpeta) == len(mundos_raiz)


def test_raiz_del_proyecto_elige_raiz_falsa_en_subdirectorio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # B.2: Con una raíz falsa en tmp_path (con packs/ y rules/) y la carpeta actual
    # dentro de ella, en un subdirectorio: se elige esa raíz, no la del repositorio.
    falsa_raiz = tmp_path / "falsa_raiz"
    (falsa_raiz / "packs").mkdir(parents=True)
    (falsa_raiz / "rules").mkdir(parents=True)

    sub = falsa_raiz / "sub" / "carpeta"
    sub.mkdir(parents=True)

    monkeypatch.chdir(sub)

    elegida = raiz_del_proyecto()
    raiz_repo = Path(__file__).resolve().parents[1]

    assert elegida.resolve() == falsa_raiz.resolve()
    assert elegida.resolve() != raiz_repo.resolve()


def test_personajes_confluencia_incluye_forastero_y_dos_fichas_sin_repetir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # B.3: personajes('confluencia')['forasteros'] incluye forastero.yaml; un mundo
    # con forastero.yaml y fichas/otro.yaml da los dos, sin repetir.

    # 1. En el mundo 'confluencia' del repositorio:
    confluencia_forasteros = personajes("confluencia")["forasteros"]
    ids_confluencia = [f["id"] for f in confluencia_forasteros]
    assert "forastero" in ids_confluencia, "confluencia debe incluir 'forastero' de forastero.yaml"
    ficha_forastero = next(f for f in confluencia_forasteros if f["id"] == "forastero")
    assert ficha_forastero["label"] == "el forastero"

    # 2. Un mundo con forastero.yaml y fichas/otro.yaml da los dos, sin repetir por id:
    falsa_raiz = tmp_path / "raiz_prueba"
    mundo_dir = falsa_raiz / "packs" / "prueba"
    (mundo_dir / "fichas").mkdir(parents=True)

    # Enlazar las reglas y pack válidos para que `personajes` pueda cargar la simulación
    repo_raiz = Path(__file__).resolve().parents[1]
    (falsa_raiz / "rules").symlink_to(repo_raiz / "rules")
    (mundo_dir / "pack.yaml").symlink_to(repo_raiz / "packs" / "isla" / "pack.yaml")

    # forastero.yaml en la raíz del pack
    (mundo_dir / "forastero.yaml").write_text(
        "id: aventurero\n"
        "label: El Aventurero\n"
        "traits: {audacia: 0.8}\n",
        encoding="utf-8",
    )

    # fichas/otro.yaml
    (mundo_dir / "fichas" / "otro.yaml").write_text(
        "id: explorador\n"
        "label: El Explorador\n"
        "traits: {curiosidad: 0.9}\n",
        encoding="utf-8",
    )

    # fichas/duplicado.yaml con el mismo id 'aventurero': no debe repetir ni pisar
    (mundo_dir / "fichas" / "duplicado.yaml").write_text(
        "id: aventurero\n"
        "label: Aventurero Falso Que No Debe Aparecer\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(falsa_raiz)
    resultado = personajes("prueba")["forasteros"]
    ids = [f["id"] for f in resultado]

    assert ids == ["aventurero", "explorador"], "debe incluir ambos sin duplicar el id aventurero"
    assert len(resultado) == 2
    # El primero mantiene el label del forastero.yaml original (gana el primero)
    assert resultado[0]["label"] == "El Aventurero"
    assert resultado[1]["label"] == "El Explorador"


def test_partida_desde_otra_carpeta_graba_guion_en_raiz_partidas(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # B.4: Una partida empezada desde otra carpeta graba su guion en <raíz>/partidas/.
    raiz = raiz_del_proyecto().resolve()
    sub = tmp_path / "otra" / "carpeta"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    gestor = Partidas()
    partida = gestor.empezar({
        "mundo": "isla",
        "personaje": "elor_d1",
        "semilla": 1,
        "modelo": False,
    })
    try:
        # La ruta del guion debe apuntar a la carpeta partidas de la raíz del proyecto
        assert partida.grabar.resolve().parent == raiz / "partidas"
        assert not (sub / "partidas").exists(), "no debe crearse partidas en la carpeta actual"

        # Esperar a que el archivo de guion se cree en disco
        assert _esperar_hasta(lambda: partida.grabar.is_file(), plazo=3.0)
        assert (raiz / "partidas" / partida.grabar.name).is_file()
    finally:
        partida.cerrar()
        partida._hilo.join(timeout=2.0)
        if partida.grabar.exists():
            partida.grabar.unlink()
