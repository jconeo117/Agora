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
import itertools
import json
import os
import queue
import re
import sys
import threading
import traceback
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from agora.cognition.narrador import Diario, Narrator, Table, Told
from agora.engine.consulta import ficha
from agora.engine.newcomer import (
    NewcomerSheet,
    build_sheet,
    load_sheet,
    newcomer_spec,
    parse_choice,
    roll_potentials,
)
from agora.engine.ontology import AgentId, TraitId
from agora.engine.pack import ContentPack, load_pack
from agora.engine.ports import CognitionProvider, PlotView
from agora.engine.state import WorldState
from agora.engine.world import Simulation
from agora.play import Terminal, TerminalCombat
from agora.present import (
    FighterView,
    RollView,
    SheetView,
    TextPresenter,
    people_view,
    roll_line,
)
from agora.run import (
    Cableado,
    build_parser,
    cablear,
    correr_partida,
    enlace_del_mundo,
    raiz_del_proyecto,
    resumen_de_la_partida,
    seguir_sin_jugador,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

def _packs() -> Path:
    """Los mundos, en la raíz del proyecto y no en la carpeta desde la que se lanza:
    la pantalla de inicio no puede depender de dónde esté el usuario."""
    return raiz_del_proyecto() / "packs"


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
    ruta = _packs() / mundo / "pack.yaml"
    if not ruta.is_file():
        raise ValueError(f"mundo desconocido: {mundo!r}")
    return ruta


def mundos() -> list[dict[str, str]]:
    return [{"id": ruta.parent.name, "label": _cargar(ruta).label}
            for ruta in sorted(_packs().glob("*/pack.yaml"))]


NUEVO = "nuevo"
"""El mundo tal como lo escribió el pack, en el tick cero. Lo demás son estados guardados."""


def guardados(mundo: str) -> list[dict[str, str]]:
    """Desde dónde se puede empezar en este mundo: nuevo, o un estado guardado en
    `packs/<mundo>/mundos/*.json` (unidad 22). Un estado ilegible no se ofrece, y se dice
    por qué en el servidor (25, A.4): nunca rompe la pantalla de inicio."""
    ruta_del_mundo(mundo)  # valida el nombre
    carpeta = _packs() / mundo / "mundos"
    salida = [{"id": NUEVO, "label": "mundo nuevo"}]
    if carpeta.is_dir():
        salida += [{"id": p.stem, "label": p.stem.replace("-", " ")}
                   for p in sorted(carpeta.glob("*.json")) if _legible(p)]
    return salida


@functools.cache
def _legible_en(ruta: Path, mtime: int) -> str | None:
    """Por qué un estado guardado no sirve, o `None` si sirve. Se mira una vez por versión del
    archivo (ruta y fecha): un guardado de decenas de megas no se parsea en cada pantalla."""
    if not ruta.is_file() or ruta.stat().st_size == 0:
        return "vacío"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"no se lee ({exc.__class__.__name__})"
    if not isinstance(datos, dict) or "agents" not in datos or "formato" not in datos:
        return "no es un estado guardado"
    return None


def _legible(ruta: Path) -> bool:
    motivo = _legible_en(ruta, ruta.stat().st_mtime_ns)
    if motivo is not None:
        print(f"# estado guardado descartado: {ruta.name}: {motivo}", file=sys.stderr)
        return False
    return True


def _ruta_guardado(mundo: str, nombre: str) -> Path:
    if "/" in nombre or nombre.startswith(".") or not nombre:
        raise ValueError(f"estado guardado desconocido: {nombre!r}")
    ruta = _packs() / mundo / "mundos" / f"{nombre}.json"
    if not ruta.is_file():
        raise ValueError(f"estado guardado desconocido: {nombre!r}")
    return ruta


@functools.cache
def _simulacion_guardada(ruta: Path, ruta_pack: Path) -> Simulation:
    """Un estado guardado, reanudado una vez por ruta: la lista de personajes lo lee."""
    return Simulation.resume(ruta, _cargar(ruta_pack))


def personajes(mundo: str, guardado: str = NUEVO) -> dict[str, list[dict[str, str]]]:
    """Los agentes del pack (con su resumen) y, si el mundo trae fichas de forastero
    en `fichas/`, esas. Sin carpeta de fichas, no hay forasteros que ofrecer. Con un
    estado guardado, los personajes son los residentes **vivos** de ese estado."""
    ruta = ruta_del_mundo(mundo)
    pack = _cargar(ruta)
    forasteros: list[dict[str, str]] = []
    for nombre, ruta_ficha in _forasteros(mundo).items():
        sheet = load_sheet(ruta_ficha)
        forasteros.append({"id": nombre, "label": sheet.label,
                           "resumen": ", ".join(str(t) for t in sheet.traits) or "-"})
    if guardado in (None, "", NUEVO):
        resumen = _resumenes(ruta)
        gente = [(s.id, s.label) for s in pack.agents]
    else:
        sim = _simulacion_guardada(_ruta_guardado(mundo, guardado), ruta)
        resumen = {str(a): _resumen_de(sim.state, a) for a in sim.state.agents}
        gente = [(a, sim.state.censo[a].label) for a in sim.state.agents]
    return {
        "personajes": [{"id": str(a), "label": etiqueta, "resumen": resumen.get(str(a), "")}
                       for a, etiqueta in gente],
        "forasteros": forasteros,
    }


def _resumen_de(world: WorldState, agente: AgentId) -> str:
    f = ficha(world, agente)
    return f"{', '.join(f.caracter) or 'sin rasgos marcados'} · {f.lugar}"


def _forasteros(mundo: str) -> dict[str, Path]:
    """Las fichas de forastero del mundo, por su `id` (es el nombre que llega en el
    pedido). Primero `forastero.yaml`, luego `fichas/*.yaml`; si dos dicen el mismo
    `id`, gana la primera."""
    carpeta = _packs() / mundo
    candidatas = [carpeta / "forastero.yaml", *sorted((carpeta / "fichas").glob("*.yaml"))]
    fichas: dict[str, Path] = {}
    for ruta in candidatas:
        if ruta.is_file():
            fichas.setdefault(str(load_sheet(ruta).id), ruta)
    return fichas


def creacion(mundo: str) -> dict[str, Any]:
    """Lo que el mundo deja elegir al crear el personaje, con sus etiquetas para la
    página. Sin sección `creation`, la página no ofrece crear."""
    pack = _cargar(ruta_del_mundo(mundo))
    spec = pack.creation
    if spec is None:
        return {"disponible": False}

    def etiqueta(trait: TraitId) -> str:
        return pack.trait_by_id[trait].label

    potenciales = None
    if spec.potentials is not None:
        p = spec.potentials
        potenciales = {"min": p.min, "max": p.max, "step": p.step,
                       "rasgos": [{"id": str(t), "label": etiqueta(t)} for t in p.traits]}
    return {
        "disponible": True,
        "grupos": [{"id": g.id, "label": g.label, "obligatorio": g.required,
                    "rasgos": [{"id": str(t), "label": etiqueta(t)} for t in g.traits]}
                   for g in spec.groups],
        "potenciales": potenciales,
        "dificultades": [{"id": nombre, "presupuesto": puntos}
                         for nombre, puntos in sorted(spec.budgets.items(), key=lambda kv: -kv[1])],
        "caracter": [{"id": str(t), "label": etiqueta(t), "min": lo, "max": hi}
                     for t, (lo, hi) in sorted(spec.character.items())],
    }


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

    def opening(self, told: Told, chain: bool) -> None:
        self._partida.publicar({"tipo": "apertura", "texto": told.text,
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

    def plot(self, vista: PlotView) -> int | None:
        """Una decisión de trama (25, A.2): un momento destacado con un botón por opción. El
        botón manda su número (1-based); «lo que haría» manda vacío y se elige la de por defecto.
        Una respuesta que no es una opción también cae en la de por defecto."""
        respuesta = self._partida.preguntar({
            "tipo": "trama", "titulo": vista.plot,
            "opciones": [{"n": n, "texto": t} for n, t in enumerate(vista.options, start=1)],
            "defecto": None if vista.defecto is None else vista.defecto + 1,
        })
        if respuesta is None:
            return vista.defecto
        linea = respuesta.strip()
        if linea.isdigit() and 1 <= int(linea) <= len(vista.options):
            return int(linea) - 1
        return vista.defecto


def _carpeta_de_partidas() -> Path:
    """Las partidas del jugador, una carpeta por partida, junto a los guiones de siempre."""
    return raiz_del_proyecto() / "partidas"


def _sanear(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", texto).strip("-") or "x"


def _escribir_atomico(ruta: Path, escribir: Callable[[Path], None]) -> None:
    """Escribe a un temporal y lo renombra: un corte a mitad no deja un archivo roto (25, A.4).
    El anterior sigue válido hasta que el nuevo está entero."""
    temporal = ruta.with_name(ruta.name + ".tmp")
    escribir(temporal)
    os.replace(temporal, ruta)


def _contar_lineas(ruta: Path) -> int:
    if not ruta.is_file():
        return 0
    with ruta.open(encoding="utf-8") as f:
        return sum(1 for _ in f)


def _recortar_guion(ruta: Path, lineas: int) -> None:
    """Deja solo las primeras `lineas` del guion. Al continuar un guardado, lo que el guion
    tenía después de ese momento era de otra continuación y no debe reproducirse (25, A.4)."""
    if not ruta.is_file():
        return
    with ruta.open(encoding="utf-8") as f:
        guardadas = [linea for linea in itertools.islice(f, lineas)]

    def escribir(temporal: Path) -> None:
        temporal.write_text("".join(guardadas), encoding="utf-8")

    _escribir_atomico(ruta, escribir)


def _leer_diario(carpeta: Path, cual: str) -> Diario:
    """El diario que tenía el guardado `cual`. Sin fichero (guardado anterior al diario), vacío."""
    ruta = carpeta / "diario" / f"{cual}.json"
    if not ruta.is_file():
        return Diario()
    return Diario.de_dict(json.loads(ruta.read_text(encoding="utf-8")))


def _leer_meta(carpeta: Path) -> dict[str, Any] | None:
    """El `meta.json` de una partida, o `None` con el motivo en el servidor. Una partida sin meta
    legible no se ofrece para continuar."""
    ruta = carpeta / "meta.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"# partida descartada: {carpeta.name}: {exc.__class__.__name__}", file=sys.stderr)
        return None
    if not isinstance(datos, dict) or "mundo" not in datos or "personaje" not in datos:
        print(f"# partida descartada: {carpeta.name}: meta incompleta", file=sys.stderr)
        return None
    return datos


def partidas_guardadas() -> list[dict[str, Any]]:
    """Las partidas del jugador con su meta, la más reciente primero. Las que no se leen
    no salen."""
    carpeta = _carpeta_de_partidas()
    salida: list[dict[str, Any]] = []
    if not carpeta.is_dir():
        return salida
    for sub in sorted(carpeta.iterdir()):
        if not sub.is_dir():
            continue
        meta = _leer_meta(sub)
        if meta is None:
            continue
        cuales = [c.stem for c in sorted(sub.glob("*.json")) if c.stem != "meta"]
        salida.append({"id": sub.name, **meta, "cuales": cuales})
    salida.sort(key=lambda p: str(p.get("fecha", "")), reverse=True)
    return salida


class Game:
    """Una partida de la web: su historia, su cola de respuestas y su hilo.

    Al cerrarla (empezar otra), las preguntas pendientes se desbloquean con un
    «fin de entrada», que la terminal ya trata como salir. No se usa el texto
    «salir»: en mitad de una conversación no cerraría nada, y el bucle daría vueltas
    sin fin preguntando lo mismo."""

    def __init__(self, args: argparse.Namespace, sim: Simulation, grabar: Path,
                 carpeta: Path | None = None, meta: dict[str, Any] | None = None,
                 continuar: bool = False, diario: Diario | None = None) -> None:
        self.args = args
        self.sim = sim
        self.grabar = grabar
        self.ticks = args.days * sim.pack.clock.ticks_per_day
        self.carpeta = carpeta
        """Donde viven los guardados de esta partida (25, A.4). `None` = sin guardados."""
        self.meta: dict[str, Any] = meta if meta is not None else {}
        self.continuar = continuar
        """Si esta partida es la continuación de un guardado: no cuenta la apertura de nuevo,
        y en su lugar dice «la última vez» (25, A.5)."""
        self._dia_guardado: int | None = None
        self._dia_visto: int | None = None
        """El día que la página ya tiene: al cambiar, se cierra el anterior y se publica."""
        self.diario = Diario() if diario is None else diario
        """El diario del jugador (25b): lo escrito no se regenera; se guarda con cada guardado."""
        self._pedido_manual = threading.Event()
        self._manuales = 0
        self.historia: list[dict[str, Any]] = []
        self.cerrada = False
        self.cv = threading.Condition()
        self._respuestas: queue.Queue[str] = queue.Queue()
        self._esperando = False
        self.parada = threading.Event()
        """«Parar» de la página: el piloto (21b) la mira en cada decisión."""
        self.presentador = WebPresenter(self)
        cab: Cableado = cablear(args)
        self._voz = cab.voz
        self._interprete = cab.interprete
        self._narrador = None if cab.narrador is None else replace(
            cab.narrador,
            providers=tuple(_Pensando(p, self.presentador) for p in cab.narrador.providers),
            opening_providers=None if cab.narrador.opening_providers is None else tuple(
                _Pensando(p, self.presentador) for p in cab.narrador.opening_providers),
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

    def pedir_guardado(self) -> None:
        """«Guardar»: se hace en el siguiente punto seguro, entre dos ticks."""
        self._pedido_manual.set()

    def _entre_ticks(self, sim: Simulation) -> None:
        """El punto seguro de la partida (25, A.4): entre dos ticks, con el mundo en un solo
        estado. Guarda al empezar cada día de juego, y cuando alguien lo pide a mano. Antes de
        guardar cierra el día que acaba de pasar: el diario entra en el mismo guardado."""
        self._cerrar_dias(sim)
        if self.carpeta is None:
            return
        if self._pedido_manual.is_set():
            self._pedido_manual.clear()
            self._manuales += 1
            self._guardar(f"manual-{self._manuales}", "a mano")
        dia = sim.state.tick // sim.pack.clock.ticks_per_day
        if dia != self._dia_guardado:
            self._dia_guardado = dia
            self._guardar("auto", "día")

    def _cerrar_dias(self, sim: Simulation) -> None:
        """Al cambiar de día, escribe las entradas del diario de los días que acaban, y publica el
        diario y la gente a la página (25b, A.2 y A.3). Solo mira el mundo y el log."""
        jugador = sim.state.player
        if jugador is None:
            return
        dia = sim.state.tick // sim.pack.clock.ticks_per_day
        if dia == self._dia_visto:
            return
        self._dia_visto = dia
        narrador = self._narrador if self._narrador is not None else Narrator((), Table())
        if self.diario.pendiente(sim.state):
            self.diario.cerrar_dias(sim.state, list(sim.log), narrador, str(jugador))
        vista = people_view(sim.state, AgentId(str(jugador)))
        self.publicar({
            "tipo": "gente",
            "vivos": [asdict(f) for f in vista.vivos],
            "muertos": [asdict(f) for f in vista.muertos],
        })
        self.publicar({"tipo": "diario", "entradas": [asdict(e) for e in self.diario.entradas]})

    def _guardar(self, cual: str, motivo: str) -> None:
        """Escribe el estado, el diario y la meta de esta partida, cada uno a un temporal y con
        `rename`. El diario va en `diario/`, aparte: `guardados` no lo toma por otro guardado."""
        assert self.carpeta is not None
        self.carpeta.mkdir(parents=True, exist_ok=True)
        (self.carpeta / "diario").mkdir(exist_ok=True)
        _escribir_atomico(self.carpeta / f"{cual}.json", self.sim.save)
        datos = json.dumps(self.diario.a_dict(), ensure_ascii=False)
        def escribir_diario(temporal: Path) -> None:
            temporal.write_text(datos, encoding="utf-8")

        _escribir_atomico(self.carpeta / "diario" / f"{cual}.json", escribir_diario)
        dia = self.sim.state.tick // self.sim.pack.clock.ticks_per_day
        lineas = _contar_lineas(self.grabar)
        por_guardado = {**self.meta.get("lineas_por_guardado", {}), cual: lineas}
        meta = {
            **self.meta,
            "dia": dia,
            "tick": self.sim.state.tick,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "motivo": motivo,
            "guardado": cual,
            "lineas_por_guardado": por_guardado,
        }
        contenido = json.dumps(meta, ensure_ascii=False, indent=1)
        def escribir_meta(temporal: Path) -> None:
            temporal.write_text(contenido, encoding="utf-8")

        _escribir_atomico(self.carpeta / "meta.json", escribir_meta)
        self.meta = meta
        self.publicar({"tipo": "guardado", "cual": cual, "motivo": motivo, "dia": dia})

    def cerrar(self) -> None:
        with self.cv:
            self.cerrada = True
            self._esperando = False
            self.cv.notify_all()
        self._respuestas.put("")

    def _correr(self) -> None:
        # La terminal y la escena reciben flujos de texto que aquí no se usan: con
        # presentador, todo lo que se enseña y se pregunta pasa por él.
        # Una partida de la web siempre llega: se cuenta la apertura (unidad 22).
        terminal = Terminal(self.sim, io.StringIO(), io.StringIO(), self._voz,
                            interpreter=self._interprete, narrator=self._narrador,
                            presenter=self.presentador, parada=self.parada,
                            apertura=not self.continuar,
                            enlace=enlace_del_mundo(self.args, self.sim.state.pack))
        escena = TerminalCombat(io.StringIO(), io.StringIO(), self._interprete, self._narrador,
                                lambda: self.sim.state, presenter=self.presentador,
                                empezada=terminal.quitar_piloto)
        try:
            if self.continuar and self._narrador is not None and self.sim.state.player is not None:
                # La última vez (25, A.5): antes de seguir, lo que pasó desde el guardado.
                vuelta = self._narrador.vuelta(self.sim.state, str(self.sim.state.player),
                                               list(self.sim.log.previos))
                self.presentador.told(vuelta, chain=False)
            resultado = correr_partida(
                self.sim, self.args, self.ticks, fuente=terminal, combate=escena,
                escena=escena, terminal=terminal, grabar=self.grabar,
                entre_ticks=self._entre_ticks,
            )
            seguir_sin_jugador(self.sim, self.ticks, resultado, self.presentador.note)
            self.presentador.ended(resultado.reason, resultado.ticks,
                                   resumen_de_la_partida(self.sim))
        except Exception as exc:
            # Sin esto, la página esperaría para siempre a un hilo ya muerto.
            traceback.print_exc()
            self.publicar({"tipo": "error", "texto": str(exc)})


class Partidas:
    """El servidor tiene a lo sumo una partida: empezar otra cierra la anterior. Y a lo
    sumo una tirada de creación en preparación: la del personaje que se está creando."""

    def __init__(self) -> None:
        self.actual: Game | None = None
        self._cerrojo = threading.Lock()
        self._tirada: dict[str, Any] | None = None
        """La tirada de la preparación: mundo, nombre, semilla y potenciales."""

    def tirar(self, pedido: dict[str, Any]) -> dict[str, Any]:
        """Los dados de la creación. Una sola tirada por preparación: pedirla otra vez
        devuelve la misma, y pedirla para otro nombre o semilla sería volver a tirar, así
        que es un error. La preparación se cierra al empezar la partida."""
        mundo = str(pedido.get("mundo", ""))
        nombre = str(pedido.get("nombre", "")).strip()
        semilla = int(pedido["semilla"])
        if self._tirada is None or self._tirada["mundo"] != mundo:
            # Otro mundo es otra preparación: la tirada de antes no le sirve.
            if not nombre:
                raise ValueError("el personaje necesita un nombre antes de tirar")
            potenciales = roll_potentials(_cargar(ruta_del_mundo(mundo)), nombre, semilla)
            self._tirada = {"mundo": mundo, "nombre": nombre, "semilla": semilla,
                            "potenciales": potenciales}
        elif (self._tirada["mundo"], self._tirada["nombre"], self._tirada["semilla"]) != (
            mundo, nombre, semilla
        ):
            raise ValueError(
                f"ya se tiraron los dados para «{self._tirada['nombre']}»: "
                "esa tirada es la de este personaje"
            )
        return {"potenciales": self._tirada["potenciales"]}

    def parar(self) -> bool:
        """«Parar»: si el personaje vive sin decidir (21b), vuelve al control en su
        próxima decisión. `False` si no hay partida que parar."""
        partida = self.actual
        if partida is None or partida.cerrada:
            return False
        partida.parada.set()
        return True

    def guardar(self) -> None:
        """«Guardar»: la partida en curso guarda en su siguiente punto seguro (25, A.4)."""
        partida = self.actual
        if partida is None or partida.cerrada or partida.carpeta is None:
            raise ValueError("no hay partida que guardar")
        partida.pedir_guardado()

    def continuar(self, pedido: dict[str, Any]) -> Game:
        """Continúa una partida guardada (25, A.4): restaura el estado del guardado pedido, recorta
        el guion a lo que tenía entonces y la pone a correr. «La última vez» la cuenta el
        narrador al empezar (25, A.5)."""
        pid = str(pedido.get("id", ""))
        if not pid or "/" in pid or pid.startswith("."):
            raise ValueError(f"partida desconocida: {pid!r}")
        carpeta = _carpeta_de_partidas() / pid
        meta = _leer_meta(carpeta)
        if meta is None:
            raise ValueError(f"la partida {pid!r} no se puede leer")
        cual = str(pedido.get("cual", "auto"))
        ruta = carpeta / f"{cual}.json"
        if not ruta.is_file() or cual == "meta":
            raise ValueError(f"no hay guardado {cual!r} en esta partida")
        ruta_pack = ruta_del_mundo(str(meta["mundo"]))
        pack = _cargar(ruta_pack)
        sim = Simulation.resume(ruta, pack)
        modelo = bool(meta.get("modelo", False))
        args = build_parser().parse_args(
            ["--pack", str(ruta_pack), "--seed", str(meta["semilla"]),
             *([] if modelo else ["--sin-llm"])]
        )
        guion = carpeta / "guion.jsonl"
        lineas = int(dict(meta.get("lineas_por_guardado", {})).get(cual, 0))
        _recortar_guion(guion, lineas)
        diario = _leer_diario(carpeta, cual)
        partida = Game(args, sim, guion, carpeta=carpeta, meta=meta, continuar=True,
                       diario=diario)
        with self._cerrojo:
            if self.actual is not None:
                self.actual.cerrar()
            self.actual = partida
            self._tirada = None
        partida.empezar()
        return partida

    def empezar(self, pedido: dict[str, Any]) -> Game:
        """Crea la partida y la pone a correr. Lo que el pedido no cuadra con el mundo
        (un personaje muerto o inexistente, un forastero sin ficha, una creación que las
        reglas no admiten) es `ValueError`."""
        mundo = str(pedido.get("mundo", ""))
        ruta = ruta_del_mundo(mundo)
        semilla = int(pedido["semilla"])
        modelo = bool(pedido.get("modelo", False))
        args = build_parser().parse_args(
            ["--pack", str(ruta), "--seed", str(semilla), *([] if modelo else ["--sin-llm"])]
        )
        pack = _cargar(ruta)
        guardado = pedido.get("guardado")
        if guardado in (None, "", NUEVO):
            sim = Simulation(pack, seed=semilla)
        else:
            # Un mundo que ya tiene días: se reanuda el estado guardado, con el pack de
            # hoy (unidad 22). El log no viaja con el guardado: se guarda el estado.
            sim = Simulation.resume(_ruta_guardado(mundo, str(guardado)), pack)
        ficha_creada: NewcomerSheet | None = None
        raros: dict[TraitId, float] = {}
        if pedido.get("crear") is not None:
            eleccion = parse_choice(pedido["crear"])
            if eleccion.mode == "roll":
                tirada = self._tirada
                if tirada is None or (tirada["mundo"], tirada["nombre"], tirada["semilla"]) != (
                    mundo, eleccion.name.strip(), semilla
                ):
                    raise ValueError(
                        "tira los dados antes de empezar: la tirada es de este personaje "
                        "y esta semilla"
                    )
            ficha_creada, raros = build_sheet(pack, eleccion, semilla)
            recien = newcomer_spec(pack, ficha_creada, sim.state.censo)
            sim.arrive(recien)
            quien = recien.id
        elif pedido.get("ficha") is not None:
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
        # Cada partida se graba como guion en la raíz del proyecto (`--guion` la vuelve a
        # jugar), venga la petición de la carpeta que venga.
        cuando = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = _sanear(f"{mundo}-{quien}-{semilla}-{cuando}")
        carpeta = _carpeta_de_partidas() / base
        carpeta.mkdir(parents=True, exist_ok=True)
        meta = {
            "mundo": mundo, "personaje": sim.state.censo[quien].label,
            "personaje_id": str(quien), "semilla": semilla, "modelo": modelo,
            "dia": 0, "tick": sim.state.tick,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "motivo": "nueva", "guardado": None, "lineas_por_guardado": {},
        }
        partida = Game(args, sim, carpeta / "guion.jsonl", carpeta=carpeta, meta=meta)
        if ficha_creada is not None:
            # La ficha junto al guion: con `--jugar-ficha` y `--guion` se reproduce la partida.
            dato = ficha_creada.model_dump(mode="json", exclude_none=True)
            (carpeta / "ficha.yaml").write_text(
                yaml.safe_dump(dato, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
        if raros:
            # Al empezar, no después: el jugador se entera de lo que nació con él.
            partida.publicar(_nacio_con(pack, raros))
        with self._cerrojo:
            if self.actual is not None:
                self.actual.cerrar()
            self.actual = partida
            self._tirada = None
        partida.empezar()
        return partida


def _nacio_con(pack: ContentPack, raros: dict[TraitId, float]) -> dict[str, Any]:
    """Lo que se le cuenta a quien nació con un raro: el `label` del pack, no el id."""
    nombres = [pack.trait_by_id[t].label for t in sorted(raros)]
    return {"tipo": "relato", "texto": "Naciste con " + " y ".join(nombres) + ".",
            "de_modelo": False, "sin_narrador": False}
