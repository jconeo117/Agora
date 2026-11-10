"""Pruebas de la interfaz web y el servidor local de la mesa (unidad 20b, §B).

Verifica:
- B.1 Sesión:
  - B.1.1: WebPresenter: cada método del protocolo produce su evento con los campos
    de su vista; `ask` bloquea hasta la entrada y devuelve el texto.
  - B.1.2: Una partida corta en la sesión (sin modelo, entradas por la cola) graba un
    guion que, reproducido con `Script`, da el mismo log.
  - B.1.3: La historia de eventos: pedir `desde=N` da exactamente los de después.
  - B.1.4: Cerrar la sesión desbloquea un `ask` pendiente con «salir».
- B.2 Servidor:
  - B.2.1: Las rutas responden con servidor en un hilo en puerto libre/0 (GET `/`,
    GET `/api/mundos`, GET `/api/mundos/<id>/personajes`, POST `/api/partida`,
    GET `/api/eventos`, POST `/api/entrada`).
  - B.2.2: Intentos de path traversal como `/static/../pyproject.toml` devuelven 404.
  - B.2.3: Escucha en `127.0.0.1` (no en `0.0.0.0`).
  - B.2.4: Ninguna respuesta incluye la clave (con API key ficticia en env var).
"""

from __future__ import annotations

import http.client
import io
import json
import threading
import time
from collections.abc import Callable, Generator
from dataclasses import asdict
from pathlib import Path

import pytest

from agora.cognition.narrador import Told
from agora.engine.ontology import AgentId
from agora.engine.pack import load_pack
from agora.engine.ports import Outcome
from agora.engine.world import Simulation
from agora.play import Script, Terminal, TerminalCombat
from agora.present import FighterView, RollView, SheetView, roll_line
from agora.run import build_parser, correr_partida
from agora.ui.server import Servidor
from agora.ui.session import Game, WebPresenter


def _esperar_hasta(cond: Callable[[], bool], plazo: float = 3.0, paso: float = 0.01) -> bool:
    limite = time.monotonic() + plazo
    while time.monotonic() < limite:
        if cond():
            return True
        time.sleep(paso)
    return cond()


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


# ---------------------------------------------------------------------------
# B.1 — Sesión
# ---------------------------------------------------------------------------


def test_web_presenter_cada_metodo_produce_evento_con_campos_y_ask_bloquea(
    tmp_path: Path,
) -> None:
    # B.1.1: WebPresenter: cada método del protocolo produce su evento con los campos
    # de su vista; `ask` bloquea hasta la entrada y devuelve el texto.
    args = build_parser().parse_args(["--pack", "packs/isla/pack.yaml", "--seed", "1"])
    sim = Simulation(load_pack(Path("packs/isla/pack.yaml")), seed=1)
    sim.set_player(AgentId("elor_d1"))
    partida = Game(args, sim, tmp_path / "partida.jsonl")
    presenter = WebPresenter(partida)

    # turn
    presenter.turn("Elor", 5)
    assert partida.historia[-1] == {"tipo": "turno", "nombre": "Elor", "tick": 5}

    # told
    presenter.told(Told(text="Relato con narrador", by=0), chain=False)
    assert partida.historia[-1] == {
        "tipo": "relato",
        "texto": "Relato con narrador",
        "de_modelo": True,
        "sin_narrador": False,
    }
    presenter.told(Told(text="Relato plantilla", by=None), chain=True)
    assert partida.historia[-1] == {
        "tipo": "relato",
        "texto": "Relato plantilla",
        "de_modelo": False,
        "sin_narrador": True,
    }

    # event
    presenter.event("Un suceso relevante")
    assert partida.historia[-1] == {"tipo": "suceso", "texto": "Un suceso relevante"}

    # note
    presenter.note("   Aviso recortado   ")
    assert partida.historia[-1] == {"tipo": "aviso", "texto": "Aviso recortado"}

    # prompt
    presenter.prompt(["mirar", "esperar"])
    assert partida.historia[-1] == {"tipo": "atajos", "atajos": ["mirar", "esperar"]}

    # options
    presenter.options([(1, "Ir al mercado"), (2, "Hablar")])
    assert partida.historia[-1] == {
        "tipo": "opciones",
        "items": [{"n": 1, "texto": "Ir al mercado"}, {"n": 2, "texto": "Hablar"}],
    }

    # people
    presenter.people([(1, "Beto", "beto_1")])
    assert partida.historia[-1] == {
        "tipo": "gente",
        "items": [{"n": 1, "nombre": "Beto", "id": "beto_1"}],
    }

    # look
    presenter.look("Plaza", [("ag1", "Carlos", "guardia")])
    assert partida.historia[-1] == {
        "tipo": "mirar",
        "cabecera": "Plaza",
        "filas": [{"id": "ag1", "nombre": "Carlos", "que": "guardia"}],
    }

    # sheet
    sheet_v = SheetView(
        nombre="Elor",
        necesidades=(("hambre", 0.4, False),),
        condiciones=(("cansado", 0.5),),
        objetos=((1, "daga", True),),
        lineas=("Línea 1",),
        propia=True,
    )
    presenter.sheet(sheet_v)
    assert partida.historia[-1] == {"tipo": "ficha", **asdict(sheet_v)}

    # status
    presenter.status(sheet_v)
    assert partida.historia[-1] == {"tipo": "estado", **asdict(sheet_v)}

    # speech
    presenter.speech("Ada", "Buenos días", "cordial", False)
    assert partida.historia[-1] == {
        "tipo": "dicho",
        "quien": "Ada",
        "dice": "Buenos días",
        "tono": "cordial",
        "respaldo": False,
    }

    # roll
    roll_v = RollView(
        actor="Elor",
        pool_label="Destreza",
        dice=(5, 6),
        opposing=None,
        opposing_label=None,
        opposing_dice=(),
        outcome=Outcome.SUCCESS,
    )
    presenter.roll(roll_v)
    assert partida.historia[-1] == {
        "tipo": "tirada",
        **asdict(roll_v),
        "linea": roll_line(roll_v),
    }

    # fighters
    fighter_v = FighterView(
        label="Bandido",
        vitality=6,
        vitality_max=10,
        fatigue=2,
        fatigue_max=6,
        stress=1,
        stress_max=4,
        status="activo",
    )
    presenter.fighters([fighter_v])
    assert partida.historia[-1] == {
        "tipo": "combate",
        "filas": [asdict(fighter_v)],
    }

    # beat
    presenter.beat("Ronda 2")
    assert partida.historia[-1] == {"tipo": "ronda", "texto": "Ronda 2"}

    # ended
    presenter.ended("victoria", 120, ["Ganó el jugador"])
    assert partida.historia[-1] == {
        "tipo": "final",
        "razon": "victoria",
        "ticks": 120,
        "lineas": ["Ganó el jugador"],
    }

    # pensando
    presenter.pensando(True)
    assert partida.historia[-1] == {"tipo": "pensando", "activo": True}

    # pick: pregunta y bloquea hasta respuesta
    res_pick: list[int | None] = []
    hilo_pick = threading.Thread(
        target=lambda: res_pick.append(presenter.pick("¿A quién?", ["Beto", "Carlos"]))
    )
    hilo_pick.start()
    assert _esperar_hasta(lambda: partida._esperando, plazo=2.0)
    assert partida.historia[-1] == {
        "tipo": "elige",
        "pregunta": "¿A quién?",
        "textos": ["Beto", "Carlos"],
    }
    assert partida.entrada("a")
    hilo_pick.join(timeout=2.0)
    assert not hilo_pick.is_alive()
    assert res_pick == [0]

    # confirm
    res_conf: list[bool] = []
    hilo_conf = threading.Thread(target=lambda: res_conf.append(presenter.confirm("¿Seguro?")))
    hilo_conf.start()
    assert _esperar_hasta(lambda: partida._esperando, plazo=2.0)
    assert partida.historia[-1] == {"tipo": "confirma", "texto": "¿Seguro?", "defecto": True}
    assert partida.entrada("s")
    hilo_conf.join(timeout=2.0)
    assert not hilo_conf.is_alive()
    assert res_conf == [True]

    # yes_no
    res_yn: list[bool] = []
    hilo_yn = threading.Thread(
        target=lambda: res_yn.append(presenter.yes_no("¿Aceptar?", defecto=False))
    )
    hilo_yn.start()
    assert _esperar_hasta(lambda: partida._esperando, plazo=2.0)
    assert partida.historia[-1] == {"tipo": "confirma", "texto": "¿Aceptar?", "defecto": False}
    assert partida.entrada("n")
    hilo_yn.join(timeout=2.0)
    assert not hilo_yn.is_alive()
    assert res_yn == [False]

    # ask: bloquea hasta la entrada y devuelve el texto ingresado
    res_ask: list[str] = []
    hilo_ask = threading.Thread(target=lambda: res_ask.append(presenter.ask("¿Qué haces?")))
    hilo_ask.start()

    # Comprobar que mientras no haya entrada, ask sigue bloqueado
    assert _esperar_hasta(lambda: partida._esperando, plazo=2.0)
    assert hilo_ask.is_alive()
    assert len(res_ask) == 0
    assert partida.historia[-1] == {"tipo": "pide", "texto": "¿Qué haces?"}

    # Proveer entrada y verificar desbloqueo con el texto exacto
    assert partida.entrada("mirar")
    hilo_ask.join(timeout=2.0)
    assert not hilo_ask.is_alive()
    assert res_ask == ["mirar"]


def test_partida_sesion_graba_guion_y_reproduce_mismo_log(tmp_path: Path) -> None:
    # B.1.2: Una partida corta en la sesión (sin modelo, entradas por la cola) graba un
    # guion que, reproducido con `Script`, da el mismo log.
    guion_path = tmp_path / "partida.jsonl"
    pack_path = Path("packs/isla/pack.yaml")
    args = build_parser().parse_args([
        "--pack",
        str(pack_path),
        "--seed",
        "42",
        "--sin-llm",
        "--sin-narrador",
        "--sin-interprete",
        "--days",
        "1",
    ])
    pack = load_pack(pack_path)
    sim1 = Simulation(pack, seed=42)
    sim1.set_player(AgentId("elor_d1"))

    partida = Game(args, sim1, guion_path)
    partida.empezar()

    # Esperar al primer turno y pedir opciones
    assert _esperar_hasta(lambda: partida._esperando, plazo=3.0)
    assert partida.entrada("opciones")

    # Esperar y elegir comer (acción pacífica que no desencadena combate)
    assert _esperar_hasta(lambda: partida._esperando, plazo=3.0)
    items = [e for e in partida.historia if e.get("tipo") == "opciones"][-1]["items"]
    opt_comer = next(it["n"] for it in items if "comer" in it["texto"])
    assert partida.entrada(str(opt_comer))

    # Esperar a que concluya la acción y termine el siguiente turno
    assert _esperar_hasta(lambda: partida._esperando, plazo=3.0)
    assert partida.entrada("salir")

    # El hilo debe terminar limpiamente
    partida._hilo.join(timeout=3.0)
    assert not partida._hilo.is_alive()

    # El guion grabado no debe estar vacío
    lineas = [
        linea for linea in guion_path.read_text(encoding="utf-8").splitlines() if linea.strip()
    ]
    assert len(lineas) > 0

    # Reproducción con Script sobre sim2 idéntica
    sim2 = Simulation(pack, seed=42)
    sim2.set_player(AgentId("elor_d1"))
    script = Script(lineas, sim=sim2)
    combate = TerminalCombat(io.StringIO(), io.StringIO(), None, None, lambda: sim2.state)
    correr_partida(
        sim2,
        args,
        sim1.state.tick,
        fuente=script,
        combate=combate,
        escena=None,
        terminal=None,
        grabar=None,
    )

    # Mismo log byte a byte
    assert list(sim1.log) == list(sim2.log)


def test_historia_eventos_desde_n_da_exactamente_los_de_despues(tmp_path: Path) -> None:
    # B.1.3: La historia de eventos: pedir `desde=N` da exactamente los de después.
    args = build_parser().parse_args(["--pack", "packs/isla/pack.yaml", "--seed", "1"])
    sim = Simulation(load_pack(Path("packs/isla/pack.yaml")), seed=1)
    sim.set_player(AgentId("elor_d1"))
    partida = Game(args, sim, tmp_path / "partida.jsonl")

    # Insertar 5 eventos conocidos
    for i in range(5):
        partida.publicar({"tipo": "suceso", "n": i})

    # desde=0 entrega los 5 eventos
    evs_0, cerrada = partida.leer(0, espera=0.1)
    assert not cerrada
    assert [e["n"] for e in evs_0] == [0, 1, 2, 3, 4]

    # desde=2 entrega exactamente los eventos con índice >= 2
    evs_2, _ = partida.leer(2, espera=0.1)
    assert [e["n"] for e in evs_2] == [2, 3, 4]

    # desde=4 entrega únicamente el último evento
    evs_4, _ = partida.leer(4, espera=0.1)
    assert [e["n"] for e in evs_4] == [4]

    # desde=5 (al día con la historia) devuelve lista vacía tras el plazo
    evs_5, _ = partida.leer(5, espera=0.01)
    assert evs_5 == []


def test_cerrar_sesion_desbloquea_ask_pendiente_con_salir(tmp_path: Path) -> None:
    # B.1.4: Cerrar la sesión desbloquea un `ask` pendiente con «salir».
    args = build_parser().parse_args(["--pack", "packs/isla/pack.yaml", "--seed", "1"])
    sim = Simulation(load_pack(Path("packs/isla/pack.yaml")), seed=1)
    sim.set_player(AgentId("elor_d1"))
    partida = Game(args, sim, tmp_path / "partida.jsonl")
    terminal = Terminal(sim, io.StringIO(), io.StringIO(), presenter=partida.presentador)

    resultado: list[str] = []

    def _pedir() -> None:
        resultado.append(terminal._leer("> "))

    hilo = threading.Thread(target=_pedir)
    hilo.start()

    # Esperar a que la terminal quede bloqueada pidiendo entrada
    assert _esperar_hasta(lambda: partida._esperando, plazo=2.0)
    assert hilo.is_alive()

    # Cerrar la sesión debe desbloquear inmediatamente
    partida.cerrar()
    hilo.join(timeout=2.0)
    assert not hilo.is_alive()

    assert resultado == ["salir"]
    assert terminal.quit is True


# ---------------------------------------------------------------------------
# B.2 — Servidor
# ---------------------------------------------------------------------------


def test_servidor_rutas_responden_en_puerto_libre(servidor_local: tuple[Servidor, int]) -> None:
    # B.2.1: Las rutas responden con servidor en un hilo en puerto libre/0
    # (GET /, GET /api/mundos, GET /api/mundos/<id>/personajes, POST /api/partida,
    # GET /api/eventos, POST /api/entrada).
    servidor, puerto = servidor_local
    conn = http.client.HTTPConnection("127.0.0.1", puerto)

    # 1. GET /
    conn.request("GET", "/")
    res = conn.getresponse()
    assert res.status == 200
    assert "text/html" in res.getheader("Content-Type", "")
    cuerpo_html = res.read()
    assert b"<!DOCTYPE html>" in cuerpo_html or b"<html" in cuerpo_html

    # 2. GET /api/mundos
    conn.request("GET", "/api/mundos")
    res = conn.getresponse()
    assert res.status == 200
    assert "application/json" in res.getheader("Content-Type", "")
    mundos_data = json.loads(res.read())
    assert isinstance(mundos_data, list)
    assert any(m["id"] == "isla" for m in mundos_data)

    # 3. GET /api/mundos/isla/personajes
    conn.request("GET", "/api/mundos/isla/personajes")
    res = conn.getresponse()
    assert res.status == 200
    pers_data = json.loads(res.read())
    assert "personajes" in pers_data
    assert "forasteros" in pers_data
    assert any(p["id"] == "elor_d1" for p in pers_data["personajes"])

    # 4. POST /api/partida
    cuerpo_partida = json.dumps({
        "mundo": "isla",
        "personaje": "elor_d1",
        "semilla": 1,
        "modelo": False,
    }).encode("utf-8")
    conn.request("POST", "/api/partida", cuerpo_partida, {"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 200
    assert json.loads(res.read()) == {"ok": True}

    # 5. GET /api/eventos (SSE)
    conn_sse = http.client.HTTPConnection("127.0.0.1", puerto)
    conn_sse.request("GET", "/api/eventos?desde=0")
    res_sse = conn_sse.getresponse()
    assert res_sse.status == 200
    assert "text/event-stream" in res_sse.getheader("Content-Type", "")
    primera_linea = res_sse.fp.readline()
    assert primera_linea.startswith(b"id: 0") or primera_linea.startswith(b":")
    conn_sse.close()

    # 6. POST /api/entrada
    partida = servidor.partidas.actual
    assert partida is not None
    assert _esperar_hasta(lambda: partida._esperando, plazo=3.0)

    cuerpo_entrada = json.dumps({"texto": "esperar"}).encode("utf-8")
    conn.request("POST", "/api/entrada", cuerpo_entrada, {"Content-Type": "application/json"})
    res = conn.getresponse()
    assert res.status == 200
    assert json.loads(res.read()) == {"ok": True}

    conn.close()


def test_servidor_path_traversal_devuelve_404(servidor_local: tuple[Servidor, int]) -> None:
    # B.2.2: Intentos de path traversal como /static/../pyproject.toml devuelven 404.
    _, puerto = servidor_local
    conn = http.client.HTTPConnection("127.0.0.1", puerto)

    rutas_traversal = [
        "/static/../pyproject.toml",
        "/static/../../pyproject.toml",
        "/static/../../../pyproject.toml",
        "/static/..%2fpyproject.toml",
        "/static/../web/index.html",
        "/static/../../../../etc/passwd",
        "/static//etc/passwd",
    ]
    for ruta in rutas_traversal:
        conn.request("GET", ruta)
        res = conn.getresponse()
        _ = res.read()
        assert res.status == 404, f"Se esperaba 404 para {ruta}, recibido {res.status}"

    conn.close()


def test_servidor_escucha_en_localhost_no_en_cero() -> None:
    # B.2.3: Escucha en 127.0.0.1 (no en 0.0.0.0).
    servidor = Servidor(0)
    try:
        ip = servidor.server_address[0]
        assert ip == "127.0.0.1"
        assert ip != "0.0.0.0"
    finally:
        servidor.server_close()


def test_servidor_ninguna_respuesta_incluye_la_clave(
    servidor_local: tuple[Servidor, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    # B.2.4: Ninguna respuesta incluye la clave (con API key ficticia en env var).
    clave_falsa = "CLAVE_OPENROUTER_SUPER_SECRETA_999888"
    monkeypatch.setenv("OPENROUTER_API_KEY", clave_falsa)

    _, puerto = servidor_local
    conn = http.client.HTTPConnection("127.0.0.1", puerto)

    rutas_a_probar: list[tuple[str, str, bytes | None]] = [
        ("GET", "/", None),
        ("GET", "/static/app.js", None),
        ("GET", "/static/style.css", None),
        ("GET", "/api/mundos", None),
        ("GET", "/api/mundos/isla/personajes", None),
        (
            "POST",
            "/api/partida",
            json.dumps({
                "mundo": "isla",
                "personaje": "elor_d1",
                "semilla": 1,
                "modelo": True,
            }).encode("utf-8"),
        ),
        ("POST", "/api/entrada", json.dumps({"texto": "opciones"}).encode("utf-8")),
        ("GET", "/ruta_inexistente", None),
    ]

    for metodo, ruta, cuerpo in rutas_a_probar:
        headers = {"Content-Type": "application/json"} if cuerpo else {}
        conn.request(metodo, ruta, cuerpo, headers)
        res = conn.getresponse()
        datos = res.read()
        cabeceras_str = str(res.getheaders())

        assert clave_falsa.encode() not in datos, f"Clave filtrada en cuerpo de {metodo} {ruta}"
        assert clave_falsa not in cabeceras_str, f"Clave filtrada en cabeceras de {metodo} {ruta}"

    conn.close()
