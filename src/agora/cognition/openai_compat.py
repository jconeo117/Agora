"""`CognitionProvider` contra una API compatible con la de OpenAI (OpenRouter
por defecto), con la biblioteca estándar, como `OllamaProvider`.

Todo fallo es `None`, y también tardar: el plazo es del total, no de cada
lectura. Con el timeout de urllib, que es por lectura, una llamada con 6 s de
plazo tardó 57 s en el banco, y el jugador espera delante de la terminal.
"""

from __future__ import annotations

import http.client
import json
import os
import queue
import socket
import ssl
import threading
import urllib.error
import urllib.request

from pydantic import BaseModel, ValidationError

CONNECT = 1.0
"""Plazo de conexión por dirección, aparte del de la respuesta. Con uno solo,
una IPv6 sin ruta se come el plazo entero antes de probar la IPv4: medido, 20 s
con 10 s de plazo y dos IPv6 delante, y con 3 s por dirección y 6 de plazo no
llegó a contestar ni una de 76."""

_TLS = ssl.create_default_context()

_WORKS: dict[str, int] = {}
"""La familia de direcciones que conectó la última vez, por host: se prueba la
primera, y solo la primera llamada paga las que no tienen ruta."""


def _connect(
    address: tuple[str, int], timeout: float | None = None,
    source_address: tuple[str, int] | None = None,
) -> socket.socket:
    host, port = address
    addrs = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    known = _WORKS.get(host)
    addrs.sort(key=lambda a: a[0] != known)
    error: OSError = OSError(f"{host}: sin direcciones")
    for family, kind, proto, _, sockaddr in addrs:
        sock = socket.socket(family, kind, proto)
        sock.settimeout(CONNECT)
        try:
            sock.connect(sockaddr)
        except OSError as e:
            sock.close()
            error = e
            continue
        _WORKS[host] = family
        sock.settimeout(timeout)
        return sock
    raise error


class _Connection(http.client.HTTPSConnection):
    """Sin túnel por proxy: lo que hace falta es elegir la dirección, y
    `HTTPConnection.connect` llama a `socket.create_connection` sin dejar
    cambiarla."""

    def connect(self) -> None:
        sock = _connect((self.host, self.port), self.timeout)
        self.sock = _TLS.wrap_socket(sock, server_hostname=self.host)


class _Handler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_Connection, req)


_open = urllib.request.build_opener(_Handler()).open


class OpenAICompatibleProvider:
    def __init__(
        self,
        modelo: str,
        url: str = "https://openrouter.ai/api/v1",
        clave_env: str = "OPENROUTER_API_KEY",
        plazo: float = 6.0,
        temperatura: float = 0.0,
        max_tokens: int = 200,
    ) -> None:
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.clave = os.environ.get(clave_env, "")
        self.plazo = plazo
        self.temperatura = temperatura
        self.max_tokens = max_tokens

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        if not self.clave:
            return None
        out: queue.Queue[object | None] = queue.Queue(maxsize=1)
        # Hilo demonio: si vence el plazo se abandona, y no retiene el cierre.
        threading.Thread(
            target=lambda: out.put(self._ask(briefing, schema, semilla)), daemon=True
        ).start()
        try:
            return out.get(timeout=self.plazo)
        except queue.Empty:
            return None

    def _ask(self, briefing: str, schema: type, semilla: int) -> object | None:
        cuerpo: dict[str, object] = {
            "model": self.modelo,
            "temperature": self.temperatura,
            "seed": semilla,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": briefing}],
            # Que OpenRouter solo mande la petición a quien respete el esquema.
            "provider": {"require_parameters": True},
        }
        modelo = schema if isinstance(schema, type) and issubclass(schema, BaseModel) else None
        if modelo is not None:
            cuerpo["response_format"] = {"type": "json_schema", "json_schema": {
                "name": modelo.__name__, "strict": False, "schema": modelo.model_json_schema()}}
        peticion = urllib.request.Request(
            f"{self.url}/chat/completions", data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.clave}"},
        )
        try:
            with _open(peticion, timeout=self.plazo) as r:
                texto = json.loads(r.read())["choices"][0]["message"]["content"]
            datos: object = json.loads(texto)
            return datos if modelo is None else modelo.model_validate(datos)
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, TypeError,
                json.JSONDecodeError, ValidationError):
            return None
