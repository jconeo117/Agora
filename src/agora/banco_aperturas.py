"""El banco de aperturas (unidad 22, A.6): cuántas aperturas acepta el modelo, cuánto
tarda, y por qué cae en plantilla las que no. Mide la misma apertura que vería el
jugador: sin log, como una partida que empieza.

Los casos (qué mundo, quién juegas, desde qué estado) viven en un archivo de datos
(`packs/banco-aperturas.yaml`), no en el código: son de ambientación.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from agora.cognition.narrador import (
    Table,
    narrate_con_motivos,
    opening_moment,
    semilla_de_apertura,
)
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import AgentId
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.world import Simulation


@dataclass(frozen=True, slots=True)
class CasoApertura:
    nombre: str
    mundo: Path
    """El `pack.yaml`."""
    guardado: Path | None
    """Un estado guardado (`mundos/*.json`), o `None` para el mundo nuevo."""
    personaje: str | None
    """Un residente vivo, por su id."""
    ficha: Path | None
    """O un forastero, por su ficha."""
    semilla: int


@dataclass(frozen=True, slots=True)
class ResultadoApertura:
    caso: str
    aceptada: bool
    motivos: tuple[str, ...]
    palabras: int
    segundos: float
    texto: str


def cargar_casos(ruta: Path) -> list[CasoApertura]:
    """Los casos de un archivo; las rutas, relativas a él."""
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    base = ruta.parent
    casos: list[CasoApertura] = []
    for c in datos.get("casos", []):
        casos.append(CasoApertura(
            nombre=str(c["nombre"]),
            mundo=base / c["mundo"],
            guardado=None if c.get("guardado") is None else base / c["guardado"],
            personaje=None if c.get("personaje") is None else str(c["personaje"]),
            ficha=None if c.get("ficha") is None else base / c["ficha"],
            semilla=int(c.get("semilla", 1)),
        ))
    return casos


def _abrir(caso: CasoApertura) -> tuple[Simulation, str]:
    pack = load_pack(caso.mundo)
    if caso.guardado is None:
        sim = Simulation(pack, seed=caso.semilla)
    else:
        sim = Simulation.resume(caso.guardado, pack)
    if caso.ficha is not None:
        recien = newcomer_spec(pack, load_sheet(caso.ficha), sim.state.censo)
        sim.arrive(recien)
        quien = str(recien.id)
    else:
        quien = str(AgentId(caso.personaje or ""))
    sim.set_player(AgentId(quien))
    return sim, quien


def run_opening_bank(
    casos: Sequence[CasoApertura], cadena: Sequence[CognitionProvider]
) -> list[ResultadoApertura]:
    resultados: list[ResultadoApertura] = []
    for caso in casos:
        sim, quien = _abrir(caso)
        m = opening_moment(sim.state, quien, [], Table())
        t0 = time.perf_counter()
        told, motivos = narrate_con_motivos(m, cadena, semilla_de_apertura(sim.state, quien))
        segundos = time.perf_counter() - t0
        resultados.append(ResultadoApertura(
            caso=caso.nombre, aceptada=told.by is not None, motivos=motivos,
            palabras=len(told.text.split()), segundos=segundos, texto=told.text,
        ))
    return resultados


def lineas(resultados: Sequence[ResultadoApertura]) -> list[str]:
    salida = []
    for r in resultados:
        estado = "modelo" if r.aceptada else "plantilla"
        por_que = "; ".join(r.motivos) if r.motivos else ""
        salida.append(f"{r.caso:<34} {estado:<9} {r.palabras:>4} palabras "
                      f"{r.segundos:6.2f} s  {por_que}".rstrip())
    if resultados:
        aceptadas = sum(r.aceptada for r in resultados)
        mediana = statistics.median(r.segundos for r in resultados)
        palabras = [r.palabras for r in resultados if r.aceptada]
        rango = f"{min(palabras)}-{max(palabras)}" if palabras else "-"
        salida.append("")
        salida.append(f"aceptadas {aceptadas}/{len(resultados)}; mediana {mediana:.2f} s; "
                      f"palabras (modelo) {rango}")
        for r in resultados:
            if r.aceptada:
                salida += ["", f"--- ejemplo de modelo: {r.caso}", r.texto]
                break
        for r in resultados:
            if not r.aceptada:
                salida += ["", f"--- ejemplo de plantilla: {r.caso}", r.texto]
                break
    return salida
