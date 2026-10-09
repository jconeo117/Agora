"""Pruebas del proveedor OllamaProvider contra servidor HTTP simulado."""

from __future__ import annotations

import json
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any, ClassVar

import pytest

from agora.cognition.ollama import OllamaProvider
from agora.cognition.voz import Habla
from agora.engine.ontology import Tone


@pytest.fixture(autouse=True)
def _aislar_red(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")


class ServidorOllamaSimulado(BaseHTTPRequestHandler):
    respuesta_cuerpo: ClassVar[bytes] = b""
    codigo_estado: ClassVar[int] = 200
    ultima_peticion: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        longitud = int(self.headers.get("Content-Length", 0))
        datos = self.rfile.read(longitud)
        if datos:
            try:
                ServidorOllamaSimulado.ultima_peticion = json.loads(datos)
            except Exception:
                ServidorOllamaSimulado.ultima_peticion = {}
        self.send_response(self.codigo_estado)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.respuesta_cuerpo)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Silenciar logs en tests


def iniciar_servidor(
    respuesta: dict[str, Any], codigo: int = 200
) -> tuple[socketserver.TCPServer, str]:
    ServidorOllamaSimulado.respuesta_cuerpo = json.dumps(respuesta).encode("utf-8")
    ServidorOllamaSimulado.codigo_estado = codigo
    ServidorOllamaSimulado.ultima_peticion = {}

    httpd = socketserver.TCPServer(("127.0.0.1", 0), ServidorOllamaSimulado)
    puerto = httpd.server_address[1]
    url = f"http://127.0.0.1:{puerto}"

    hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
    hilo.start()
    return httpd, url


def test_una_respuesta_buena_se_valida() -> None:
    respuesta = {"response": json.dumps({"dice": "hola", "tono": "seco"})}
    httpd, url = iniciar_servidor(respuesta)
    try:
        proveedor = OllamaProvider(url=url, timeout=5.0)
        resultado = proveedor.think("briefing de prueba", Habla, semilla=12345)
        assert isinstance(resultado, Habla)
        assert resultado.dice == "hola"
        assert resultado.tono is Tone.CURT

        # Comprobar que options.seed viajó al servidor con la semilla dada
        peticion = ServidorOllamaSimulado.ultima_peticion
        assert peticion.get("options", {}).get("seed") == 12345
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_json_roto_es_none() -> None:
    # La clave response trae JSON no parseable
    respuesta = {"response": "{esto no es json valido"}
    httpd, url = iniciar_servidor(respuesta)
    try:
        proveedor = OllamaProvider(url=url, timeout=5.0)
        resultado = proveedor.think("briefing", Habla, semilla=1)
        assert resultado is None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_fuera_de_esquema_es_none() -> None:
    # Tono no existente en Tone enum
    respuesta = {"response": json.dumps({"dice": "hola", "tono": "inventado"})}
    httpd, url = iniciar_servidor(respuesta)
    try:
        proveedor = OllamaProvider(url=url, timeout=5.0)
        resultado = proveedor.think("briefing", Habla, semilla=1)
        assert resultado is None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_sin_respuesta_es_none() -> None:
    # Falta la clave response
    respuesta = {"otra_cosa": 123}
    httpd, url = iniciar_servidor(respuesta)
    try:
        proveedor = OllamaProvider(url=url, timeout=5.0)
        resultado = proveedor.think("briefing", Habla, semilla=1)
        assert resultado is None
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_un_servidor_caido_es_none_y_no_revienta() -> None:
    # Puerto sin nadie escuchando
    url_muerta = "http://127.0.0.1:1"
    proveedor = OllamaProvider(url=url_muerta, timeout=2.0)
    t0 = time.perf_counter()
    resultado = proveedor.think("briefing", Habla, semilla=1)
    duracion = time.perf_counter() - t0

    assert resultado is None
    # No debe bloquear más de timeout + 1 s
    assert duracion < 3.0
