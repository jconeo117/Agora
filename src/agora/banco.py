"""El banco de intenciones: cuánto entiende el intérprete, medido (unidad 14).

Es la métrica de la unidad, como `--health` lo es de un pack: la 14 no mueve
ningún renglón de salud porque no toca el mundo. Cada caso es una frase con lo
que debería entenderse, sobre el menú real de un agente en un tick concreto
(o sobre las acciones legales de una escena, escritas en el caso). Sin modelo
mide el léxico, y eso es determinista: el número es un contrato.

Lo que más importa no es el acierto sino los falsos sí: entender una acción
equivocada y hacerla. Un «no encaja» con la buena entre las candidatas cuesta
una tecla; un falso sí puede costar la vida de alguien en la isla.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agora.agents.decide import options
from agora.cognition.intencion import Kind, Menu, Reading, interpret, same_place
from agora.cognition.narrador import Moment, moment_from_json, narrate
from agora.engine.ontology import AgentId
from agora.engine.pack import ContentPack
from agora.engine.ports import CognitionProvider
from agora.engine.world import Simulation
from agora.play import legal_menu, world_menu
from agora.rules.system import Ruleset


@dataclass(frozen=True, slots=True)
class Case:
    prosa: str
    semilla: int
    tick: int
    agente: str
    tipo: tuple[str, ...]
    accion: tuple[str, ...] = ()
    lugar: str | None = None
    destinatario: str | None = None
    orden: str | None = None
    cruda: bool = False
    escena: tuple[tuple[str, str | None, bool], ...] = ()
    """Las acciones legales de la escena, (acción, objetivo, forzar). Vacío:
    el caso es en el mundo."""


def load_bank(path: Path) -> list[Case]:
    casos = []
    for linea in path.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        d: dict[str, Any] = json.loads(linea)
        casos.append(Case(
            prosa=d["prosa"], semilla=d["semilla"], tick=d["tick"], agente=d["agente"],
            tipo=tuple(d["tipo"]), accion=tuple(d.get("accion") or ()),
            lugar=d.get("lugar"), destinatario=d.get("destinatario"), orden=d.get("orden"),
            cruda=bool(d.get("cruda", False)),
            escena=tuple((a, o, bool(f)) for a, o, f in d.get("escena", ())),
        ))
    return casos


def _hits(menu: Menu, r: Reading, c: Case) -> bool:
    if r.kind.value not in c.tipo:
        return False
    if r.kind is Kind.ACTION and r.entry is not None:
        e = menu.entries[r.entry]
        return ((not c.accion or e.action in c.accion)
                and (c.lugar is None or same_place(menu, e.place, c.lugar))
                and (c.destinatario is None or e.target == c.destinatario))
    if r.kind is Kind.ORDER:
        return r.order == c.orden and (c.destinatario is None or r.about == c.destinatario)
    return True


@dataclass
class BankReport:
    casos: int = 0
    aciertos: int = 0
    rescatables: int = 0
    """Fallos con la buena entre las candidatas: el jugador la elige con una letra."""
    falsos_si: int = 0
    sin_modelo: int = 0
    """Veces que se pidió al modelo y respondió el léxico (falló, tardó o no valió)."""
    crudas: int = 0
    crudas_bien: int = 0
    latencias: list[float] = field(default_factory=list)
    fallos: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        n = max(self.casos, 1)
        lat = sorted(self.latencias) or [0.0]
        return [
            f"acierto      {self.aciertos}/{self.casos} ({100 * self.aciertos // n} %)",
            f"rescatables  {self.rescatables} (la buena, entre las candidatas)",
            f"falsos sí    {self.falsos_si}",
            f"sin modelo   {self.sin_modelo}",
            f"crudas       {self.crudas_bien}/{self.crudas}",
            f"latencia     p50 {lat[len(lat) // 2]:.2f} s, p90 {lat[int(len(lat) * 0.9)]:.2f} s, "
            f"máx {lat[-1]:.2f} s",
            *self.fallos,
        ]


def run_bank(pack: ContentPack, ruleset: Ruleset, casos: Sequence[Case],
             provider: CognitionProvider | None) -> BankReport:
    informe = BankReport()
    mundos: dict[tuple[int, int, str], tuple[Menu, dict[str, str]]] = {}
    for i, c in enumerate(casos):
        clave = (c.semilla, c.tick, c.agente)
        if clave not in mundos:
            sim = Simulation(pack, seed=c.semilla)
            while sim.state.tick < c.tick:
                sim.tick()
            w = sim.state
            labels = {str(a): w.censo[a].label for a in w.agents}
            mundos[clave] = (world_menu(w, options(w, w.agents[AgentId(c.agente)])), labels)
        menu, labels = mundos[clave]
        if c.escena:
            ejemplos = ruleset.combat.examples if ruleset.combat is not None else {}
            menu = legal_menu(ejemplos, labels, c.escena)
        t0 = time.perf_counter()
        r = interpret(menu, c.prosa, provider, 1000 + i)
        informe.latencias.append(time.perf_counter() - t0)
        bien = _hits(menu, r, c)
        informe.casos += 1
        informe.aciertos += bien
        informe.sin_modelo += provider is not None and not r.by_model
        informe.crudas += c.cruda
        informe.crudas_bien += c.cruda and bien
        if not bien:
            informe.falsos_si += r.kind is Kind.ACTION
            informe.rescatables += any(
                _hits(menu, Reading(Kind.ACTION, j), c) for j in r.candidates)
            informe.fallos.append(f"  ✗ «{c.prosa}» → {_describe(menu, r)}")
    return informe


def _describe(menu: Menu, r: Reading) -> str:
    if r.kind is Kind.ACTION and r.entry is not None:
        e = menu.entries[r.entry]
        return f"{e.action} {e.target or ''} {e.place or ''}".strip()
    if r.kind is Kind.ORDER and r.order is not None:
        return f"orden {r.order.value} {r.about or ''}".strip()
    return f"{r.kind.value} {[menu.entries[j].action for j in r.candidates]}"


# --- El banco de narración (unidad 17) -------------------------------------------


@dataclass
class TellReport:
    momentos: int = 0
    del_modelo: int = 0
    """Narraciones que contó un modelo de la cadena: válidas y sin nombres de
    fuera del briefing (si no, las cuenta la plantilla y no suman aquí)."""
    por_modelo: list[int] = field(default_factory=list)
    hechos: int = 0
    hechos_contados: int = 0
    """Hechos cuyas personas aparecen en la prosa: si el narrador se come un
    hecho, se come a quien lo protagoniza."""
    tuyos: int = 0
    tuyos_contados: int = 0
    """Lo mismo, solo de los hechos del jugador: estos no se pueden resumir."""
    latencias: list[float] = field(default_factory=list)
    muestras: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        n = max(self.momentos, 1)
        lat = sorted(self.latencias) or [0.0]
        return [
            f"momentos     {self.momentos}",
            f"del modelo   {self.del_modelo}/{self.momentos} (por modelo: {self.por_modelo})",
            f"plantilla    {self.momentos - self.del_modelo}",
            f"cobertura    {self.hechos_contados}/{self.hechos} hechos con nombre; "
            f"tuyos {self.tuyos_contados}/{self.tuyos}",
            f"latencia     p50 {lat[len(lat) // 2]:.2f} s, p90 {lat[int(len(lat) * 0.9)]:.2f} s, "
            f"máx {lat[-1]:.2f} s ({100 * self.del_modelo // n} % del modelo)",
        ]


def load_moments(path: Path) -> list[Moment]:
    return [moment_from_json(json.loads(linea))
            for linea in path.read_text(encoding="utf-8").splitlines() if linea.strip()]


def run_tell_bank(moments: Sequence[Moment], providers: Sequence[CognitionProvider]) -> TellReport:
    informe = TellReport(por_modelo=[0] * len(providers))
    for i, m in enumerate(moments):
        t0 = time.perf_counter()
        told = narrate(m, providers, 1000 + i)
        informe.latencias.append(time.perf_counter() - t0)
        informe.momentos += 1
        if told.by is not None:
            informe.del_modelo += 1
            informe.por_modelo[told.by] += 1
        for f in m.facts:
            nombres = [n for n in f.names if n != m.player]
            if nombres:
                dicho = all(re.search(rf"\b{re.escape(n)}\b", told.text) for n in nombres)
                informe.hechos += 1
                informe.hechos_contados += dicho
                informe.tuyos += f.mine
                informe.tuyos_contados += f.mine and dicho
        hechos = "\n".join(f"    {j}. {f.text}" for j, f in enumerate(m.facts, 1)) or (
            f"    pregunta: {m.question}")
        quien = "plantilla" if told.by is None else f"modelo {told.by}"
        informe.muestras.append(f"## {i} · {m.kind.value} · {m.place} · {quien}\n{hechos}\n\n"
                                f"> {told.text}\n")
    return informe
