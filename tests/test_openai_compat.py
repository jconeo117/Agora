"""Pruebas del proveedor compatible con la API de OpenAI (unidad 14, §B.4)."""

from __future__ import annotations

import http.server
import json
import socket
import threading
import time
from typing import Any

import pytest
from pydantic import BaseModel

from agora.cognition.openai_compat import _WORKS, OpenAICompatibleProvider, _connect


class DummyPayload(BaseModel):
    mensaje: str


@pytest.fixture(autouse=True)
def _local_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")


def test_sin_clave_no_abre_conexion() -> None:
    # 1. Sin la variable de la clave, think devuelve None sin abrir conexión
    # (servidor que cuenta peticiones: 0).
    peticiones = 0

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal peticiones
            peticiones += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        provider = OpenAICompatibleProvider(
            modelo="test-model",
            url=f"http://127.0.0.1:{port}",
            clave_env="CLAVE_INEXISTENTE_XYZ",
        )
        res = provider.think("hola", DummyPayload, 123)
        assert res is None
        assert peticiones == 0
    finally:
        server.shutdown()


def test_respuesta_valida_y_parametros_en_cuerpo(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2. Servidor que contesta un choices[0].message.content válido: devuelve el
    # modelo validado; el cuerpo recibido lleva response_format.json_schema,
    # seed y provider.require_parameters.
    cuerpo_recibido: dict[str, Any] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            nonlocal cuerpo_recibido
            length = int(self.headers.get("Content-Length", 0))
            cuerpo_recibido = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"mensaje": "saludo recibido"})
                        }
                    }
                ]
            }
            self.wfile.write(json.dumps(resp).encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test-12345")
        provider = OpenAICompatibleProvider(
            modelo="test-model",
            url=f"http://127.0.0.1:{port}",
            clave_env="TEST_OPENAI_KEY",
        )
        res = provider.think("hola", DummyPayload, 42)
        assert isinstance(res, DummyPayload)
        assert res.mensaje == "saludo recibido"

        assert cuerpo_recibido.get("seed") == 42
        assert cuerpo_recibido.get("provider") == {"require_parameters": True}
        assert "response_format" in cuerpo_recibido
        assert cuerpo_recibido["response_format"].get("type") == "json_schema"
        assert "json_schema" in cuerpo_recibido["response_format"]
    finally:
        server.shutdown()


def test_servidor_lento_respeta_plazo(monkeypatch: pytest.MonkeyPatch) -> None:
    # 3. Servidor que tarda 3 s; plazo=0.5: None en menos de 1,5 s.
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            for _ in range(10):
                time.sleep(0.2)
                try:
                    self.wfile.write(b" ")
                    self.wfile.flush()
                except OSError:
                    break

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test")
        provider = OpenAICompatibleProvider(
            modelo="test-model",
            url=f"http://127.0.0.1:{port}",
            clave_env="TEST_OPENAI_KEY",
            plazo=0.5,
        )
        t0 = time.perf_counter()
        res = provider.think("hola", DummyPayload, 1)
        dur = time.perf_counter() - t0
        assert res is None
        assert dur < 1.5
    finally:
        server.shutdown()


def test_errores_http_y_esquema_devuelven_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # 4. Servidor que devuelve 402, 429 o JSON fuera de esquema: None.
    codigo_respuesta = 402
    contenido_respuesta = ""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(codigo_respuesta)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if contenido_respuesta:
                self.wfile.write(contenido_respuesta.encode())

        def log_message(self, format: str, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        monkeypatch.setenv("TEST_OPENAI_KEY", "sk-test")
        provider = OpenAICompatibleProvider(
            modelo="test-model",
            url=f"http://127.0.0.1:{port}",
            clave_env="TEST_OPENAI_KEY",
            plazo=1.0,
        )

        # 402 Payment Required
        codigo_respuesta = 402
        assert provider.think("hola", DummyPayload, 1) is None

        # 429 Too Many Requests
        codigo_respuesta = 429
        assert provider.think("hola", DummyPayload, 1) is None

        # 200 pero fuera de esquema (clave distinta esperada por DummyPayload)
        codigo_respuesta = 200
        contenido_respuesta = json.dumps({
            "choices": [{"message": {"content": json.dumps({"clave_rara": 999})}}]
        })
        assert provider.think("hola", DummyPayload, 1) is None
    finally:
        server.shutdown()


def test_connect_memoriza_familia_exitosa(monkeypatch: pytest.MonkeyPatch) -> None:
    # 5. _connect: con socket.getaddrinfo sustituido por dos direcciones (una
    # que falla al conectar, otra a un servidor local), conecta; y la siguiente
    # llamada prueba primero la familia que funcionó (_WORKS).
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(5)
    host, port = server_sock.getsockname()

    # Limpiar estado previo de _WORKS
    _WORKS.pop(host, None)

    # getaddrinfo devuelve primero una dirección que falla (AF_INET6 ::1 en puerto inexistente)
    # y segundo la dirección real que funciona (AF_INET 127.0.0.1 en port)
    fallo = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 65534, 0, 0))
    exito = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))

    def fake_getaddrinfo(h: str, p: int, type: int = 0) -> list[Any]:
        return [fallo, exito]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # 1. Primera llamada: prueba fallo, luego éxito, y registra _WORKS[host] = AF_INET
    s1 = _connect((host, port), timeout=1.0)
    s1.close()
    assert _WORKS.get(host) == socket.AF_INET

    # 2. Segunda llamada: ahora addrs.sort sitúa primero AF_INET porque coincide con _WORKS[host]
    llamadas_socket: list[int] = []
    orig_socket = socket.socket

    def track_socket(family: int, *args: Any, **kwargs: Any) -> socket.socket:
        llamadas_socket.append(family)
        return orig_socket(family, *args, **kwargs)

    monkeypatch.setattr(socket, "socket", track_socket)

    s2 = _connect((host, port), timeout=1.0)
    s2.close()
    # La primera familia probada fue AF_INET porque fue ordenada antes
    assert llamadas_socket[0] == socket.AF_INET
    server_sock.close()
