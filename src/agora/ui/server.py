"""El servidor de la mesa: la biblioteca estándar, atado a 127.0.0.1 y nunca a 0.0.0.0.

La clave del modelo se queda en el proceso: ninguna ruta devuelve el entorno, y la
página solo recibe eventos.
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from agora.ui.session import ESPERA_SSE, Partidas, creacion, mundos, personajes

WEB = Path(__file__).parent / "web"
"""Lo único que el servidor entrega de disco: la página, sus hojas de estilo y su código."""

TIPOS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, puerto: int) -> None:
        super().__init__(("127.0.0.1", puerto), Manejador)
        self.partidas = Partidas()


class Manejador(BaseHTTPRequestHandler):
    server: Servidor

    def do_GET(self) -> None:
        ruta = urlparse(self.path)
        if ruta.path == "/":
            self._archivo("index.html")
        elif ruta.path.startswith("/static/"):
            self._archivo(ruta.path[len("/static/"):])
        elif ruta.path == "/api/mundos":
            self._json(mundos())
        elif ruta.path.startswith("/api/mundos/") and ruta.path.endswith("/personajes"):
            self._consulta(lambda: personajes(ruta.path[len("/api/mundos/"):-len("/personajes")]))
        elif ruta.path.startswith("/api/mundos/") and ruta.path.endswith("/creacion"):
            self._consulta(lambda: creacion(ruta.path[len("/api/mundos/"):-len("/creacion")]))
        elif ruta.path == "/api/eventos":
            self._eventos(parse_qs(ruta.query))
        else:
            self._error(404, "no existe")

    def do_POST(self) -> None:
        ruta = urlparse(self.path).path
        if ruta == "/api/partida":
            self._consulta(lambda: self._empezar())
        elif ruta == "/api/tirada":
            self._consulta(lambda: self.server.partidas.tirar(self._cuerpo()))
        elif ruta == "/api/entrada":
            self._entrada()
        elif ruta == "/api/parar":
            if self.server.partidas.parar():
                self._json({"ok": True})
            else:
                self._error(409, "no hay partida que parar")
        else:
            self._error(404, "no existe")

    def _cuerpo(self) -> dict[str, Any]:
        largo = int(self.headers.get("Content-Length", "0"))
        dato = json.loads(self.rfile.read(largo) or b"{}")
        if not isinstance(dato, dict):
            raise ValueError("el cuerpo tiene que ser un objeto JSON")
        return dato

    def _empezar(self) -> dict[str, Any]:
        self.server.partidas.empezar(self._cuerpo())
        return {"ok": True}

    def _entrada(self) -> None:
        try:
            cuerpo = self._cuerpo()
        except ValueError as exc:
            self._error(400, str(exc))
            return
        partida = self.server.partidas.actual
        if partida is None or not partida.entrada(str(cuerpo.get("texto", ""))):
            self._error(409, "ahora no se espera ninguna respuesta")
            return
        self._json({"ok": True})

    def _consulta(self, hacer: Any) -> None:
        """Una ruta que puede fallar por lo que pidió quien llama: 400, con por qué."""
        try:
            resultado = hacer()
        except (ValueError, KeyError, TypeError) as exc:
            self._error(400, str(exc.args[0]) if isinstance(exc, KeyError) else str(exc))
            return
        self._json(resultado)

    def _archivo(self, relativa: str) -> None:
        if not relativa or ".." in relativa or relativa.startswith("/"):
            self._error(404, "no existe")
            return
        ruta = (WEB / relativa).resolve()
        if not ruta.is_relative_to(WEB.resolve()) or not ruta.is_file():
            self._error(404, "no existe")
            return
        datos = ruta.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", TIPOS.get(ruta.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def _json(self, datos: Any, estado: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, estado: int, motivo: str) -> None:
        self._json({"error": motivo}, estado)

    def _eventos(self, query: dict[str, list[str]]) -> None:
        """SSE: la historia desde `desde` y, después, lo nuevo. Sin partida, cierra."""
        try:
            desde = int(query.get("desde", ["0"])[0])
        except ValueError:
            self._error(400, "desde tiene que ser un número")
            return
        partida = self.server.partidas.actual
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            if partida is None:
                self.wfile.write(b": sin partida\n\n")
                self.wfile.flush()
                return
            n = desde
            while True:
                nuevos, cerrada = partida.leer(n, ESPERA_SSE)
                if nuevos:
                    for i, evento in enumerate(nuevos, start=n):
                        datos = json.dumps(evento, ensure_ascii=False)
                        self.wfile.write(f"id: {i}\ndata: {datos}\n\n".encode())
                    n += len(nuevos)
                elif cerrada:
                    return
                else:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return


def servir(puerto: int) -> None:
    """La mesa hasta Ctrl-C. Abre el navegador; si no hay, la URL queda en pantalla."""
    servidor = Servidor(puerto)
    url = f"http://127.0.0.1:{puerto}/"
    print(f"# la mesa en {url}  (Ctrl-C para cerrar)")
    webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        if servidor.partidas.actual is not None:
            servidor.partidas.actual.cerrar()
        servidor.server_close()
