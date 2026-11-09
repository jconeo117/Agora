"""La partida en el navegador (unidad 20b, D-174): una sesión por proceso.

La partida corre en un hilo, con el mismo cableado que la terminal (`run.py`) y un
`Presenter` que no escribe texto sino eventos. La historia es una lista con índice:
quien se conecta tarde, o recarga la página, la recibe entera. Lo que la página
responde a una pregunta vuelve por una cola, y la partida espera ahí: el mundo se
para entre ticks, como en la terminal.
"""

from __future__ import annotations

import argparse
import functools
import io
import queue
import threading
import traceback
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agora.cognition.narrador import Told
from agora.engine.consulta import ficha
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import AgentId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.world import Simulation
from agora.play import Terminal, TerminalCombat
from agora.present import FighterView, RollView, SheetView, TextPresenter, roll_line
from agora.run import (
    Cableado,
    build_parser,
    cablear,
    correr_partida,
    resumen_de_la_partida,
    seguir_sin_jugador,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

RAIZ = Path("packs")
"""Los mundos, como en la CLI: desde la raíz del proyecto."""

PARTIDAS = Path("partidas")
"""Cada partida de la web se graba aquí como guion (`--guion` la vuelve a jugar)."""

ESPERA_SSE = 15.0
"""Segundos sin novedades antes de mandar un comentario que mantenga viva la conexión."""


@functools.cache
def _cargar(ruta: Path) -> ContentPack:
    """Un pack por ruta, cargado una vez: la pantalla de inicio pregunta por todos."""
    return load_pack(ruta)


@functools.cache
def _resumenes(ruta: Path) -> dict[str, str]:
    """Una línea por personaje: su carácter y dónde empieza. Se calcula una vez por
    mundo, sobre una partida de semilla 1; el carácter sale del pack, no de la semilla."""
    pack = _cargar(ruta)
    sim = Simulation(pack, seed=1)
    resumen: dict[str, str] = {}
    for spec in pack.agents:
        if spec.id not in sim.state.agents:
            continue
        f = ficha(sim.state, spec.id)
        caracter = ", ".join(f.caracter) or "sin rasgos marcados"
        resumen[str(spec.id)] = f"{caracter} · {f.lugar}"
    return resumen


def ruta_del_mundo(mundo: str) -> Path:
    if not mundo or "/" in mundo or mundo.startswith("."):
        raise ValueError(f"mundo desconocido: {mundo!r}")
    ruta = RAIZ / mundo / "pack.yaml"
    if not ruta.is_file():
        raise ValueError(f"mundo desconocido: {mundo!r}")
    return ruta


def mundos() -> list[dict[str, str]]:
    return [{"id": ruta.parent.name, "label": _cargar(ruta).label}
            for ruta in sorted(RAIZ.glob("*/pack.yaml"))]


def personajes(mundo: str) -> dict[str, list[dict[str, str]]]:
    """Los agentes del pack (con su resumen) y, si el mundo trae fichas de forastero
    en `fichas/`, esas. Sin carpeta de fichas, no hay forasteros que ofrecer."""
    ruta = ruta_del_mundo(mundo)
    resumen = _resumenes(ruta)
    pack = _cargar(ruta)
    forasteros: list[dict[str, str]] = []
    for nombre, ruta_ficha in _forasteros(mundo).items():
        sheet = load_sheet(ruta_ficha)
        forasteros.append({"id": nombre, "label": sheet.label,
                           "resumen": ", ".join(str(t) for t in sheet.traits) or "-"})
    return {
        "personajes": [{"id": str(s.id), "label": s.label, "resumen": resumen.get(str(s.id), "")}
                       for s in pack.agents],
        "forasteros": forasteros,
    }


def _forasteros(mundo: str) -> dict[str, Path]:
    carpeta = RAIZ / mundo / "fichas"
    if not carpeta.is_dir():
        return {}
    return {p.stem: p for p in sorted(carpeta.glob("*.yaml"))}


def _como_linea(respuesta: str) -> TextPresenter:
    """Las preguntas que se responden con una línea (`pick`, `confirm`, `yes_no`)
    pasan por la misma puerta que en la terminal: la respuesta llega como si se
    hubiera escrito. Así la web no duplica cómo se lee un «s», una letra o un Enter."""
    return TextPresenter(io.StringIO(respuesta + "\n"), io.StringIO())


class _Pensando:
    """Un proveedor del narrador que avisa a la página mientras piensa. Solo envuelve
    la llamada: lo que devuelve es lo del proveedor de verdad."""

    def __init__(self, proveedor: CognitionProvider, presentador: WebPresenter) -> None:
        self._proveedor = proveedor
        self._presentador = presentador

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        self._presentador.pensando(True)
        try:
            return self._proveedor.think(briefing, schema, semilla)
        finally:
            self._presentador.pensando(False)


class WebPresenter:
    """El `Presenter` de la web: cada cosa que se enseña es un evento JSON en la
    historia, y cada pregunta espera la respuesta de la página. No escribe texto: la
    página decide cómo se ve cada evento."""

    def __init__(self, partida: Game) -> None:
        self._partida = partida

    def turn(self, nombre: str, tick: int) -> None:
        self._partida.publicar({"tipo": "turno", "nombre": nombre, "tick": tick})

    def told(self, told: Told, chain: bool) -> None:
        self._partida.publicar({"tipo": "relato", "texto": told.text,
                                "de_modelo": told.by is not None,
                                "sin_narrador": chain and told.by is None})

    def event(self, texto: str) -> None:
        self._partida.publicar({"tipo": "suceso", "texto": texto})

    def note(self, texto: str) -> None:
        self._partida.publicar({"tipo": "aviso", "texto": texto.strip()})

    def prompt(self, atajos: Sequence[str]) -> None:
        self._partida.publicar({"tipo": "atajos", "atajos": list(atajos)})

    def options(self, items: Sequence[tuple[int, str]]) -> None:
        self._partida.publicar({"tipo": "opciones",
                                "items": [{"n": n, "texto": t} for n, t in items]})

    def people(self, items: Sequence[tuple[int, str, str]]) -> None:
        self._partida.publicar({"tipo": "gente",
                                "items": [{"n": n, "nombre": nombre, "id": pid}
                                          for n, nombre, pid in items]})

    def look(self, cabecera: str, filas: Sequence[tuple[str, str, str]]) -> None:
        self._partida.publicar({"tipo": "mirar", "cabecera": cabecera,
                                "filas": [{"id": pid, "nombre": nombre, "que": que}
                                          for pid, nombre, que in filas]})

    def sheet(self, vista: SheetView) -> None:
        self._partida.publicar({"tipo": "ficha", **asdict(vista)})

    def status(self, vista: SheetView) -> None:
        self._partida.publicar({"tipo": "estado", **asdict(vista)})

    def speech(self, quien: str, dice: str, tono: str, respaldo: bool) -> None:
        self._partida.publicar({"tipo": "dicho", "quien": quien, "dice": dice,
                                "tono": tono, "respaldo": respaldo})

    def roll(self, vista: RollView) -> None:
        self._partida.publicar({"tipo": "tirada", **asdict(vista), "linea": roll_line(vista)})

    def fighters(self, filas: Sequence[FighterView]) -> None:
        self._partida.publicar({"tipo": "combate", "filas": [asdict(f) for f in filas]})

    def beat(self, texto: str) -> None:
        self._partida.publicar({"tipo": "ronda", "texto": texto})

    def ended(self, razon: str, ticks: int, lineas: Sequence[str]) -> None:
        self._partida.publicar({"tipo": "final", "razon": razon, "ticks": ticks,
                                "lineas": list(lineas)})

    def pensando(self, activo: bool) -> None:
        self._partida.publicar({"tipo": "pensando", "activo": activo})

    def ask(self, texto: str) -> str:
        respuesta = self._partida.preguntar({"tipo": "pide", "texto": texto})
        return "" if respuesta is None else respuesta

    def pick(self, pregunta: str, textos: Sequence[str]) -> int | None:
        respuesta = self._partida.preguntar({"tipo": "elige", "pregunta": pregunta,
                                             "textos": list(textos)})
        return None if respuesta is None else _como_linea(respuesta).pick(pregunta, textos)

    def confirm(self, texto: str) -> bool:
        respuesta = self._partida.preguntar({"tipo": "confirma", "texto": texto,
                                             "defecto": True})
        return False if respuesta is None else _como_linea(respuesta).confirm(texto)

    def yes_no(self, pregunta: str, defecto: bool) -> bool:
        respuesta = self._partida.preguntar({"tipo": "confirma", "texto": pregunta,
                                             "defecto": defecto})
        return False if respuesta is None else _como_linea(respuesta).yes_no(pregunta, defecto)


class Game:
    """Una partida de la web: su historia, su cola de respuestas y su hilo.

    Al cerrarla (empezar otra), las preguntas pendientes se desbloquean con un
    «fin de entrada», que la terminal ya trata como salir. No se usa el texto
    «salir»: en mitad de una conversación no cerraría nada, y el bucle daría vueltas
    sin fin preguntando lo mismo."""

    def __init__(self, args: argparse.Namespace, sim: Simulation, grabar: Path) -> None:
        self.args = args
        self.sim = sim
        self.grabar = grabar
        self.ticks = args.days * sim.pack.clock.ticks_per_day
        self.historia: list[dict[str, Any]] = []
        self.cerrada = False
        self.cv = threading.Condition()
        self._respuestas: queue.Queue[str] = queue.Queue()
        self._esperando = False
        self.presentador = WebPresenter(self)
        cab: Cableado = cablear(args)
        self._voz = cab.voz
        self._interprete = cab.interprete
        self._narrador = None if cab.narrador is None else replace(
            cab.narrador,
            providers=tuple(_Pensando(p, self.presentador) for p in cab.narrador.providers),
        )
        self._hilo = threading.Thread(target=self._correr, name="partida", daemon=True)

    def empezar(self) -> None:
        self._hilo.start()

    def publicar(self, evento: dict[str, Any]) -> None:
        with self.cv:
            self.historia.append(evento)
            self.cv.notify_all()

    def leer(self, desde: int, espera: float) -> tuple[list[dict[str, Any]], bool]:
        """Los eventos desde `desde`; si no hay ninguno, espera hasta `espera` segundos
        a que los haya. El segundo valor dice si la partida está cerrada: entonces no
        vendrá nada más."""
        with self.cv:
            self.cv.wait_for(lambda: desde < len(self.historia) or self.cerrada, timeout=espera)
            return self.historia[desde:], self.cerrada

    def preguntar(self, evento: dict[str, Any]) -> str | None:
        """Publica la pregunta y espera la respuesta. `None` si la partida está cerrada."""
        with self.cv:
            if self.cerrada:
                return None
            self._esperando = True
        self.publicar(evento)
        respuesta = self._respuestas.get()
        with self.cv:
            return None if self.cerrada else respuesta

    def entrada(self, texto: str) -> bool:
        """Una respuesta de la página. Solo vale si la partida está esperando una:
        una respuesta que llega cuando nadie pregunta se quedaría para la siguiente
        pregunta, y eso sería otra partida."""
        with self.cv:
            if not self._esperando or self.cerrada:
                return False
            self._esperando = False
        self._respuestas.put(texto)
        return True

    def cerrar(self) -> None:
        with self.cv:
            self.cerrada = True
            self._esperando = False
            self.cv.notify_all()
        self._respuestas.put("")

    def _correr(self) -> None:
        # La terminal y la escena reciben flujos de texto que aquí no se usan: con
        # presentador, todo lo que se enseña y se pregunta pasa por él.
        terminal = Terminal(self.sim, io.StringIO(), io.StringIO(), self._voz,
                            interpreter=self._interprete, narrator=self._narrador,
                            presenter=self.presentador)
        escena = TerminalCombat(io.StringIO(), io.StringIO(), self._interprete, self._narrador,
                                lambda: self.sim.state, presenter=self.presentador)
        try:
            resultado = correr_partida(
                self.sim, self.args, self.ticks, fuente=terminal, combate=escena,
                escena=escena, terminal=terminal, grabar=self.grabar,
            )
            seguir_sin_jugador(self.sim, self.ticks, resultado, self.presentador.note)
            self.presentador.ended(resultado.reason, resultado.ticks,
                                   resumen_de_la_partida(self.sim))
        except Exception as exc:
            # Sin esto, la página esperaría para siempre a un hilo ya muerto.
            traceback.print_exc()
            self.publicar({"tipo": "error", "texto": str(exc)})


class Partidas:
    """El servidor tiene a lo sumo una partida: empezar otra cierra la anterior."""

    def __init__(self) -> None:
        self.actual: Game | None = None
        self._cerrojo = threading.Lock()

    def empezar(self, pedido: dict[str, Any]) -> Game:
        """Crea la partida y la pone a correr. Lo que el pedido no cuadra con el mundo
        (un personaje muerto o inexistente, un forastero sin ficha) es `ValueError`."""
        mundo = str(pedido.get("mundo", ""))
        ruta = ruta_del_mundo(mundo)
        semilla = int(pedido["semilla"])
        modelo = bool(pedido.get("modelo", False))
        args = build_parser().parse_args(
            ["--pack", str(ruta), "--seed", str(semilla), *([] if modelo else ["--sin-llm"])]
        )
        pack = _cargar(ruta)
        sim = Simulation(pack, seed=semilla)
        if pedido.get("ficha") is not None:
            fichas = _forasteros(mundo)
            nombre = str(pedido["ficha"])
            if nombre not in fichas:
                raise ValueError(f"forastero desconocido: {nombre!r}")
            recien = newcomer_spec(pack, load_sheet(fichas[nombre]), sim.state.censo)
            sim.arrive(recien)
            quien = recien.id
        else:
            quien = AgentId(str(pedido.get("personaje", "")))
            if quien not in sim.state.agents:
                raise ValueError(f"{quien!r} no está vivo en este mundo")
        sim.set_player(quien)
        PARTIDAS.mkdir(exist_ok=True)
        cuando = datetime.now().strftime("%Y%m%d-%H%M%S")
        partida = Game(args, sim, PARTIDAS / f"{mundo}-{quien}-{semilla}-{cuando}.jsonl")
        with self._cerrojo:
            if self.actual is not None:
                self.actual.cerrar()
            self.actual = partida
        partida.empezar()
        return partida
