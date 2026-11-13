"""El presentador: lo que se enseña al jugador, separado de cómo se enseña (D-174).

`play.py` decide qué pasa y qué se pregunta; este módulo decide cómo se ve. La
terminal de hoy es `TextPresenter`, y reproduce byte a byte lo que escribía
`play.py` antes de existir esta capa. Una web (20b) será otro presentador con
los mismos métodos: ningún método de aquí sabe de texto de pantalla, solo de
qué clase de cosa se enseña.

Las vistas son datos congelados, construidos desde el estado por funciones de
este módulo. Leerlas no cambia el mundo (regla 1), y no tocan el RNG.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TextIO

from agora.agents.decide import critical_needs
from agora.cognition.narrador import Told
from agora.engine.consulta import ficha
from agora.engine.ontology import AgentId, ItemId
from agora.engine.ports import Outcome
from agora.engine.state import AgentState, Propiedad, WorldState
from agora.rules.encounter import Fighter

SIN_MODELO = "  (el intérprete no contestó: entiende el léxico)"
"""Como el «(respaldo)» de la voz: que el jugador sepa por qué de pronto se
le entiende peor. Sin esto, una API sin créditos pasaba por un léxico mudo."""

SIN_NARRADOR = "  (el narrador no contestó: lo cuenta la plantilla)"

PALABRAS_TIRADA = {
    Outcome.FAILURE: "falla",
    Outcome.SUCCESS_AT_COST: "éxito con coste",
    Outcome.SUCCESS: "éxito",
    Outcome.CRITICAL: "crítico",
}


# -- vistas -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SheetView:
    """La hoja de alguien, lista para enseñarse. `propia`: si es la del jugador,
    con sus objetos; la de otro no los enseña."""

    nombre: str
    necesidades: tuple[tuple[str, float, bool], ...]
    """(etiqueta, valor de 0 a 1, si está bajo el umbral crítico), en el orden del pack."""
    condiciones: tuple[tuple[str, float], ...]
    """(etiqueta de la situación, gravedad)."""
    objetos: tuple[tuple[int, str, bool], ...]
    """(número para `equipar N`, nombre, si va puesto), en el orden de `objetos_de`."""
    lineas: tuple[str, ...]
    """Lo que dice `ficha()`, línea a línea."""
    propia: bool


@dataclass(frozen=True, slots=True)
class RollView:
    """Una tirada, con los campos de `dice_line`. La línea sale de aquí y de nada más."""

    actor: str
    pool_label: str
    dice: tuple[int, ...]
    opposing: str | None
    opposing_label: str | None
    opposing_dice: tuple[int, ...]
    outcome: Outcome


@dataclass(frozen=True, slots=True)
class FighterView:
    """Cómo está un combatiente en la escena: PV, fatiga, estrés y estado."""

    label: str
    vitality: int
    vitality_max: int
    fatigue: int
    fatigue_max: int
    stress: int
    stress_max: int
    status: str


def nombre_objeto(world: WorldState, p: Propiedad) -> str:
    """Cómo se nombra un objeto en pantalla: lo que el pack dice de su tipo."""
    spec = world.pack.item_by_id[ItemId(p.objeto)]
    return spec.narration or spec.label


def sheet_view(world: WorldState, agent: AgentState, otro: AgentId | None = None) -> SheetView:
    """La hoja de `agent`, o de `otro` mirado desde `agent`. Solo lee."""
    pack = world.pack
    criticas = {str(n) for n in critical_needs(world, agent)}
    propia = otro is None
    objetos: tuple[tuple[int, str, bool], ...] = ()
    if propia:
        objetos = tuple(
            (n, nombre_objeto(world, p), p.equipado)
            for n, p in enumerate(world.objetos_de(agent.spec_id), start=1)
        )
    sujeto = agent if otro is None else world.agents.get(otro, agent)
    return SheetView(
        nombre=world.censo[sujeto.spec_id].label,
        necesidades=tuple(
            (spec.label, sujeto.needs[spec.id], str(spec.id) in criticas)
            for spec in pack.needs
        ),
        condiciones=tuple(
            (pack.situation_by_id[c.situacion].label, c.gravedad) for c in sujeto.condiciones
        ),
        objetos=objetos,
        lineas=tuple(ficha(world, sujeto.spec_id, None if propia else agent.spec_id).lines()),
        propia=propia,
    )


def fighter_view(f: Fighter) -> FighterView:
    """Un combatiente de la escena, como vista."""
    return FighterView(
        label=f.spec.label,
        vitality=f.vitality,
        vitality_max=f.spec.vitality,
        fatigue=f.fatigue,
        fatigue_max=f.spec.fatigue,
        stress=f.stress,
        stress_max=f.spec.stress,
        status=f.status.value,
    )


def dice_line(
    actor: str, pool_label: str, dice: Sequence[int], opposing: str | None,
    opposing_label: str | None, opposing_dice: Sequence[int], outcome: Outcome,
) -> str:
    """Los dados a la vista, en una línea (unidad 18): quién tiró cuántos contra
    qué, y cómo acabó. `opposing_label` es la frase entera antes del nombre
    («la defensa de»), porque cada sistema lo dice a su manera."""
    tiros = f"[{' '.join(str(d) for d in dice)}]"
    cuerpo = f"{actor}, {pool_label} ({len(dice)})"
    if opposing is not None:
        cuerpo += f" contra {opposing_label} {opposing} ({len(opposing_dice)})"
        tiros += f" contra [{' '.join(str(d) for d in opposing_dice)}]"
    return f"🎲 {cuerpo}: {tiros} → {PALABRAS_TIRADA[outcome]}"


def roll_line(v: RollView) -> str:
    return dice_line(v.actor, v.pool_label, v.dice, v.opposing, v.opposing_label,
                     v.opposing_dice, v.outcome)


# -- el protocolo -------------------------------------------------------------


class Presenter(Protocol):
    """Lo que se enseña y se pregunta al jugador, por clase de cosa.

    Un método por clase, no por línea: una interfaz gráfica puede pintar un
    turno entero a partir de `turn`, `status`, `told`, `prompt` y `options`
    sin leer una sola línea de texto.
    """

    def turn(self, nombre: str, tick: int) -> None:
        """Empieza tu turno."""

    def told(self, told: Told, chain: bool) -> None:
        """La prosa del narrador. `chain`: si había algún modelo al que preguntar."""

    def opening(self, told: Told, chain: bool) -> None:
        """La apertura (unidad 22): el mundo, dónde llegas y quién eres, y lo que se
        mueve. Se cuenta una vez, antes del primer turno de una partida nueva. Por
        defecto no se enseña: un presentador que no la quiera no tiene que decirlo."""
        return None

    def event(self, texto: str) -> None:
        """Un suceso que te toca, sin narrador (lo que dice el log)."""

    def note(self, texto: str) -> None:
        """Un aviso del sistema: no te entiendo, eso no se puede, un cuarto de hora."""

    def prompt(self, atajos: Sequence[str]) -> None:
        """«¿Qué haces?» y los atajos que se enseñan junto."""

    def options(self, items: Sequence[tuple[int, str]]) -> None:
        """Opciones numeradas: (número, texto)."""

    def people(self, items: Sequence[tuple[int, str, str]]) -> None:
        """Las personas de `hablar`: (número, nombre, id)."""

    def look(self, cabecera: str, filas: Sequence[tuple[str, str, str]]) -> None:
        """`mirar`: la cabecera del sitio, y (id, nombre, qué hace) por cada cual."""

    def sheet(self, vista: SheetView) -> None:
        """La ficha que se pidió, con los objetos si es la tuya."""

    def status(self, vista: SheetView) -> None:
        """La hoja a la vista, al principio de cada turno, sin que se pida."""

    def speech(self, quien: str, dice: str, tono: str, respaldo: bool) -> None:
        """Lo que dice un NPC. `respaldo`: si no lo dijo un modelo."""

    def roll(self, vista: RollView) -> None:
        """Una tirada a la vista."""

    def fighters(self, filas: Sequence[FighterView]) -> None:
        """El estado de la escena de combate, uno por combatiente."""

    def beat(self, texto: str) -> None:
        """Una línea de la pelea (una ronda, un golpe)."""

    def ended(self, razon: str, ticks: int, lineas: Sequence[str]) -> None:
        """La partida acaba: por qué, cuántos ticks, y el resumen."""

    def ask(self, texto: str) -> str:
        """Lee una línea. Devuelve «» al cerrarse la entrada."""

    def pick(self, pregunta: str, textos: Sequence[str]) -> int | None:
        """Elegir entre candidatas por letra. `None` si no es ninguna."""

    def confirm(self, texto: str) -> bool:
        """El eco de lo entendido, contra alguien. Enter es que sí."""

    def yes_no(self, pregunta: str, defecto: bool) -> bool:
        """Una pregunta de sí o no con su defecto."""


# -- la terminal de texto -----------------------------------------------------


def show(out: TextIO, told: Told, chain: bool) -> None:
    """La prosa del narrador, a lo ancho de una terminal."""
    for linea in textwrap.wrap(told.text, width=88):
        out.write(f"  {linea}\n")
    if chain and told.by is None:
        out.write(SIN_NARRADOR + "\n")
    out.flush()


def confirms(inp: TextIO, out: TextIO, texto: str) -> bool:
    """El eco de lo entendido cuando va contra alguien. En el banco, «me ocupo
    de Vidan» acabó en rematarle con los dos modelos de 70B. Enter es que sí."""
    out.write(f"  entiendo: {texto}. ¿Sí? [S/n] ")
    out.flush()
    return not inp.readline().strip().lower().startswith("n")


def picks(inp: TextIO, out: TextIO, pregunta: str, textos: Sequence[str]) -> int | None:
    """Elegir entre las candidatas del intérprete por letra, para no chocar con
    los números del menú. Cualquier otra cosa es ninguna."""
    letras = "abc"[: len(textos)]
    out.write(pregunta + "\n")
    for letra, texto in zip(letras, textos, strict=False):
        out.write(f"    {letra}) {texto}\n")
    out.write("  ¿cuál? ")
    out.flush()
    r = inp.readline().strip().lower()
    return letras.index(r) if len(r) == 1 and r in letras else None


class TextPresenter:
    """La terminal de texto: lo mismo que escribía `play.py`, carácter a carácter.

    Es la única clase del proyecto que escribe en pantalla o lee del teclado para
    la partida. Si cambia algo aquí, cambia la salida de la terminal: por eso lo
    fijan los tests del presentador.
    """

    def __init__(self, inp: TextIO, out: TextIO) -> None:
        self.inp = inp
        self.out = out

    def _linea(self, texto: str) -> None:
        self.out.write(texto + "\n")
        self.out.flush()

    def turn(self, nombre: str, tick: int) -> None:
        self._linea(f"\n# {nombre}, tick {tick}")

    def told(self, told: Told, chain: bool) -> None:
        show(self.out, told, chain)

    def opening(self, told: Told, chain: bool) -> None:
        """Como `show`, pero con los párrafos de la apertura en su sitio: `show` los
        funde en uno, y aquí el mundo, la llegada y quién eres son partes distintas."""
        self.out.write("\n")
        for parrafo in told.text.split("\n\n"):
            for linea in textwrap.wrap(parrafo.replace("\n", " "), width=88):
                self.out.write(f"  {linea}\n")
            self.out.write("\n")
        if chain and told.by is None:
            self.out.write(SIN_NARRADOR + "\n")
        self.out.flush()

    def event(self, texto: str) -> None:
        self._linea("  " + texto)

    def note(self, texto: str) -> None:
        self._linea(texto)

    def prompt(self, atajos: Sequence[str]) -> None:
        self._linea("¿Qué haces?")
        self._linea("  atajos: " + " · ".join(atajos))

    def options(self, items: Sequence[tuple[int, str]]) -> None:
        for n, texto in items:
            self._linea(f"  {n:>3}. {texto}")

    def people(self, items: Sequence[tuple[int, str, str]]) -> None:
        for n, nombre, pid in items:
            self._linea(f"  {n}. {nombre} ({pid})")

    def look(self, cabecera: str, filas: Sequence[tuple[str, str, str]]) -> None:
        self._linea(cabecera)
        for pid, nombre, que in filas:
            self._linea(f"    {pid:<24} {nombre}: {que}")

    def sheet(self, vista: SheetView) -> None:
        for linea in vista.lineas:
            self._linea(linea)
        if vista.propia:
            if not vista.objetos:
                self._linea("  no llevas nada")
            for n, nombre, puesto in vista.objetos:
                marca = " (puesto)" if puesto else ""
                self._linea(f"  {n}. {nombre}{marca}")

    def status(self, vista: SheetView) -> None:
        """La terminal no enseña la hoja sin que se pida: nada que escribir."""

    def speech(self, quien: str, dice: str, tono: str, respaldo: bool) -> None:
        self._linea(f"  {quien}: «{dice}»  [{tono}]" + ("  (respaldo)" if respaldo else ""))

    def roll(self, vista: RollView) -> None:
        self._linea(roll_line(vista))

    def fighters(self, filas: Sequence[FighterView]) -> None:
        for f in filas:
            self._linea(f"    {f.label:<24} {f.vitality:>3}/{f.vitality_max} PV"
                        f"  fatiga {f.fatigue}/{f.fatigue_max}  estrés {f.stress}/{f.stress_max}"
                        f"  {f.status}")

    def beat(self, texto: str) -> None:
        self._linea(texto)

    def ended(self, razon: str, ticks: int, lineas: Sequence[str]) -> None:
        self._linea(f"\n# fin de la partida: {razon}, {ticks} ticks jugados")
        for linea in lineas:
            self._linea(linea)

    def ask(self, texto: str) -> str:
        self.out.write(texto)
        self.out.flush()
        return self.inp.readline()

    def pick(self, pregunta: str, textos: Sequence[str]) -> int | None:
        return picks(self.inp, self.out, pregunta, textos)

    def confirm(self, texto: str) -> bool:
        return confirms(self.inp, self.out, texto)

    def yes_no(self, pregunta: str, defecto: bool) -> bool:
        self.out.write(pregunta + (" [S/n] " if defecto else " [s/N] "))
        self.out.flush()
        linea = self.inp.readline().strip().lower()
        return defecto if not linea else linea.startswith("s")
