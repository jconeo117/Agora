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
from agora.cognition.narrador import DiaryEntry, Told
from agora.engine.consulta import ficha
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, ItemId, PlaceId
from agora.engine.perception import public_facts, saw
from agora.engine.ports import Outcome, PlotView
from agora.engine.state import AgentState, Propiedad, WorldState
from agora.rules.binding import BindingSpec
from agora.rules.derive import derive
from agora.rules.encounter import Fighter
from agora.rules.system import Ruleset

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
class MechanicalView:
    """La ficha mecánica de la mesa, ya en datos (25, A.1): potenciales, competencias con su
    nivel, nivel, papel, arma y armadura. Solo existe si el mundo tiene sistema enlazado."""

    papel: str
    nivel: int
    atributos: tuple[tuple[str, int, int], ...]
    """(etiqueta, valor, potencial), en el orden del sistema."""
    competencias: tuple[tuple[str, int], ...]
    """(competencia, nivel), en orden alfabético."""
    arma: str
    armadura: str | None


@dataclass(frozen=True, slots=True)
class SheetView:
    """La hoja de alguien, lista para enseñarse. `propia`: si es la del jugador,
    con sus objetos; la de otro no los enseña. Los campos del final (ficha mecánica, fama,
    marcas y tramas) solo llegan a la hoja propia (25, A.1): la de otro no lleva nada de eso."""

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
    mecanica: MechanicalView | None = None
    """La ficha de la mesa, si el mundo tiene sistema enlazado. `None` si no."""
    fama: tuple[str, float] | None = None
    """(etiqueta, valor) de la fama, si el pack la declara."""
    marcas: tuple[tuple[str, int], ...] = ()
    """(etiqueta, cuenta) de las marcas visibles que la persona tiene. Las ocultas, nunca."""
    tramas: tuple[tuple[str, str], ...] = ()
    """(etiqueta de la trama, en qué va), personales y de arco."""


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


def sheet_view(
    world: WorldState, agent: AgentState, otro: AgentId | None = None,
    enlace: tuple[Ruleset, BindingSpec] | None = None,
) -> SheetView:
    """La hoja de `agent`, o de `otro` mirado desde `agent`. Solo lee. `enlace` es el sistema
    de la mesa y su enlace con el mundo, si los hay: sin él, la hoja no lleva ficha mecánica."""
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
        lineas=tuple(ficha(world, sujeto.spec_id, None if propia else agent.spec_id).lines())
        + (_lineas_de_tramas(world, agent) if propia else ()),
        propia=propia,
        mecanica=_mecanica_de(world, agent, enlace) if propia else None,
        fama=_fama_de(world, agent) if propia else None,
        marcas=_marcas_de(world, agent) if propia else (),
        tramas=_tramas_de(world, agent) if propia else (),
    )


def _mecanica_de(
    world: WorldState, agent: AgentState, enlace: tuple[Ruleset, BindingSpec] | None,
) -> MechanicalView | None:
    """La ficha de la mesa de la persona, con el sistema y el enlace de la partida. Sin enlace,
    `None`: el mundo no tiene reglas de mesa y la hoja no lo finge."""
    if enlace is None:
        return None
    sistema, binding = enlace
    hoja = derive(world, agent.spec_id, sistema, binding)
    c = hoja.combatant
    etiquetas = {a.id: a.label for a in sistema.attributes}
    return MechanicalView(
        papel=hoja.role,
        nivel=hoja.level,
        atributos=tuple(
            (etiquetas[a], v, hoja.potentials[a]) for a, v in c.attributes.items()
        ),
        competencias=tuple(sorted(c.skills.items())),
        arma=hoja.weapon.label,
        armadura=None if hoja.armor is None else hoja.armor.label,
    )


def _fama_de(world: WorldState, agent: AgentState) -> tuple[str, float] | None:
    libro = world.pack.plots
    if libro is None or libro.fame is None:
        return None
    return (libro.fame.label, world.fama.get(agent.spec_id, 0.0))


def _marcas_de(world: WorldState, agent: AgentState) -> tuple[tuple[str, int], ...]:
    libro = world.pack.plots
    if libro is None:
        return ()
    marcas = world.marcas.get(agent.spec_id, {})
    return tuple(
        (marca.label, marcas[marca.id])
        for marca in libro.marks
        if not marca.hidden and marcas.get(marca.id, 0) > 0
    )


def _tramas_de(world: WorldState, agent: AgentState) -> tuple[tuple[str, str], ...]:
    """Las tramas que lleva la persona, personal y de arco, con lo que pasa en ellas en palabras:
    si espera algo o si tiene una decisión por delante."""
    libro = world.pack.plots
    if libro is None:
        return ()
    salida: list[tuple[str, str]] = []
    for run in world.tramas_de(agent.spec_id):
        trama = next(t for t in libro.plots if t.id == run.plot)
        paso = next(p for p in trama.steps if p.id == run.paso)
        en_que = ("tiene una decisión por delante" if paso.expects is None
                  else "espera que pase algo")
        salida.append((trama.label, en_que))
    return tuple(salida)


def _lineas_de_tramas(world: WorldState, agent: AgentState) -> tuple[str, ...]:
    """Lo que la hoja propia lleva de tramas (23a, A.7): la fama, las marcas que se ven y la
    trama en curso. Las ocultas no salen nunca. La hoja de otro no lleva nada de esto: es
    lo que el protagonista guarda para sí."""
    libro = world.pack.plots
    if libro is None:
        return ()
    salida: list[str] = []
    if libro.fame is not None:
        salida.append(f"{libro.fame.label}: {world.fama.get(agent.spec_id, 0.0):.2f}")
    marcas = world.marcas.get(agent.spec_id, {})
    for marca in libro.marks:
        if not marca.hidden and marcas.get(marca.id, 0) > 0:
            salida.append(f"{marca.label}: {marcas[marca.id]}")
    for run in world.tramas_de(agent.spec_id):
        trama = next(t for t in libro.plots if t.id == run.plot)
        salida.append(f"En curso: {trama.label}")
    return tuple(salida)


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


# -- tu gente (25b, A.1) -------------------------------------------------------

TOPE_DE_GENTE = 40
"""Cuántas personas caben en «tu gente», vivas y muertas juntas (25b, A.1)."""

DIAS_DE_VISTO = 14
"""Hasta cuántos días atrás cuenta haber visto a alguien para que esté en «tu gente»."""

APRECIO_MINIMO = 0.1
"""Desde qué |aprecio| entra alguien en «tu gente» sin relación con nombre."""

RENCOR_MINIMO = 0.2
"""Desde qué agravio propio entra alguien en «tu gente» sin relación con nombre."""

RENCOR_PALABRA = 0.3
"""Desde qué agravio propio se nombra el rencor, y a partir de cuánto, no perdonar."""

RENCOR_HONDO = 0.6


@dataclass(frozen=True, slots=True)
class PersonRow:
    """Una persona de tu gente, en palabras. Nada de lo que ella siente por ti, nunca."""

    nombre: str
    vivo: bool
    relaciones: tuple[str, ...]
    """Las relaciones con nombre que tenéis, por su etiqueta del pack («tu pareja»)."""
    publico: tuple[str, ...]
    """Lo que cualquiera que la conozca sabe: grupos, rasgos de creación, condiciones visibles."""
    sientes: str
    """Lo que sientes por ella, en palabras (la tabla de `palabra_de_aprecio`)."""
    rencor: str | None
    """«le guardas rencor» o «no se lo perdonas», si tu agravio lo pide."""
    ultimo: str | None
    """Lo último que te hizo, de tu memoria: la acción del pack y hace cuánto."""
    visto: str | None
    """Cuándo y dónde la viste por última vez."""
    murio: str | None
    """Si ha muerto, cuándo (con la fecha que tú pudiste saber)."""


@dataclass(frozen=True, slots=True)
class PeopleView:
    vivos: tuple[PersonRow, ...]
    muertos: tuple[PersonRow, ...]


def palabra_de_aprecio(aprecio: float, vinculo: bool) -> str:
    """El aprecio en una palabra. Cada umbral pertenece a la palabra de arriba: el borde es suyo
    (25b, A.1). Sin vínculo, lo indiferente es «apenas le conoces», no «te es indiferente»."""
    if aprecio >= 0.6:
        return "le quieres mucho"
    if aprecio >= 0.3:
        return "le aprecias"
    if aprecio >= 0.1:
        return "te cae bien"
    if aprecio >= -0.1:
        return "te es indiferente" if vinculo else "apenas le conoces"
    if aprecio >= -0.3:
        return "te cae mal"
    return "le detestas"


def _hace(world: WorldState, tick: int) -> str:
    dias = (world.tick - tick) // world.pack.clock.ticks_per_day
    if dias <= 0:
        return "hoy"
    return "hace 1 día" if dias == 1 else f"hace {dias} días"


def _vistos(world: WorldState, yo: AgentId) -> dict[AgentId, tuple[int, PlaceId]]:
    """Por persona, la última vez que la viste dentro de la ventana: (tick, lugar). Se mira lo que
    presenciaste y lo que dejaste anotado al mirar el sitio donde estabas."""
    corte = world.tick - DIAS_DE_VISTO * world.pack.clock.ticks_per_day
    ultimos: dict[AgentId, tuple[int, PlaceId]] = {}

    def anotar(quien: AgentId, tick: int, lugar: PlaceId) -> None:
        previo = ultimos.get(quien)
        if previo is None or (tick, lugar) > previo:
            ultimos[quien] = (tick, lugar)

    for p in saw(world, yo, days=DIAS_DE_VISTO):
        for quien in (p.actor, p.target):
            if quien is not None and p.tick >= corte:
                anotar(quien, p.tick, p.place)
    a = world.agents[yo]
    for lugar, (tick, presentes) in sorted(a.sightings.items()):
        if tick < corte:
            continue
        for quien in presentes:
            anotar(quien, tick, lugar)
    return ultimos


def _fecha_de_muerte(world: WorldState, yo: AgentId, otro: AgentId) -> int | None:
    """Cuándo murió, según lo que `yo` pudo saber: la crónica (las muertes son públicas) o su
    propia memoria si estuvo delante. El motor no guarda la fecha, así que no se inventa."""
    fechas = [e.tick for e in world.cronica.entradas if e.tipo == "muerte" and otro in e.quienes]
    fechas += [
        r.tick for r in world.memoria.de(yo)
        if r.kind is EventKind.AGENT_DIED and r.about == otro
    ]
    return max(fechas, default=None)


def _ultimo_que_te_hizo(world: WorldState, yo: AgentId, otro: AgentId) -> str | None:
    """La última cosa que te hizo, de tu memoria, con su acción en palabras del pack."""
    hechas = [
        r for r in world.memoria.de(yo)
        if r.por_quien == otro and r.action is not None
    ]
    if not hechas:
        return None
    r = max(hechas, key=lambda x: (x.tick, x.seq))
    accion = world.pack.action_by_id[r.action].label if r.action is not None else ""
    return f"{accion}, {_hace(world, r.tick)}"


def _fila(
    world: WorldState, yo: AgentId, otro: AgentId, agravio: dict[AgentId, float],
    vistos: dict[AgentId, tuple[int, PlaceId]],
) -> PersonRow:
    pack = world.pack
    a = world.agents[yo]
    vivo = otro in world.agents
    aprecio = a.regard_for(otro, world.tick, a.temperament.bond_fade,
                           a.relation_floor(pack, otro))
    rencor = agravio.get(otro, 0.0)
    pf = public_facts(world, yo, otro) if vivo else None
    visto = vistos.get(otro)
    muerte = None if vivo else _fecha_de_muerte(world, yo, otro)
    return PersonRow(
        nombre=world.censo[otro].label,
        vivo=vivo,
        relaciones=tuple(pack.relation_by_id[r].label for r in a.related_to(otro)),
        publico=() if pf is None else pf.grupos + pf.rasgos + pf.condiciones,
        sientes=palabra_de_aprecio(aprecio, otro in a.bonds),
        rencor=("no se lo perdonas" if rencor >= RENCOR_HONDO
                else "le guardas rencor" if rencor >= RENCOR_PALABRA else None),
        ultimo=_ultimo_que_te_hizo(world, yo, otro),
        visto=None if visto is None else f"en {pack.place_by_id[visto[1]].label}, "
        f"{_hace(world, visto[0])}",
        murio=None if vivo else (
            "murió" if muerte is None else f"murió el día {muerte // pack.clock.ticks_per_day}"
        ),
    )


def people_view(world: WorldState, yo: AgentId) -> PeopleView:
    """Tu gente, en palabras (25b, A.1): quien tiene relación con nombre contigo, quien pesa por
    aprecio o agravio, y a quien viste hace poco. Como mucho `TOPE_DE_GENTE`, con los más cercanos
    primero; los muertos, aparte. Solo lee: lo de otro no entra más que como lo que tú sabes."""
    if yo not in world.agents:
        return PeopleView(vivos=(), muertos=())
    pack = world.pack
    a = world.agents[yo]
    agravio = world.memoria.agravio(yo, world.tick, pack.tuning.grief_scale,
                                    pack.tuning.agravio_de_oidas)
    vistos = _vistos(world, yo)
    conocidos: set[AgentId] = set(a.bonds) | set(agravio) | set(vistos)
    for quienes in a.relations.values():
        conocidos |= set(quienes)
    conocidos.discard(yo)
    # (clave de cercanía, persona): la clave acaba en el id, así que el orden es total.
    candidatas: list[tuple[tuple[int, float, int, str], AgentId]] = []
    for otro in sorted(conocidos):
        if otro not in world.censo:
            continue
        con_nombre = bool(a.related_to(otro))
        aprecio = a.regard_for(otro, world.tick, a.temperament.bond_fade,
                               a.relation_floor(pack, otro))
        rencor = agravio.get(otro, 0.0)
        visto = vistos.get(otro)
        if not (con_nombre or abs(aprecio) >= APRECIO_MINIMO or rencor >= RENCOR_MINIMO
                or visto is not None):
            continue
        clave = (0 if con_nombre else 1, -(abs(aprecio) + rencor),
                 -(visto[0] if visto else -1), str(otro))
        candidatas.append((clave, otro))
    candidatas.sort(key=lambda c: c[0])
    elegidas = [otro for _, otro in candidatas[:TOPE_DE_GENTE]]
    filas = [_fila(world, yo, otro, agravio, vistos) for otro in elegidas]
    return PeopleView(
        vivos=tuple(f for f in filas if f.vivo),
        muertos=tuple(f for f in filas if not f.vivo),
    )


def gente_lineas(vista: PeopleView) -> list[str]:
    """Tu gente para la terminal: una persona por bloque, y los muertos al final."""
    salida: list[str] = []
    for f in vista.vivos + vista.muertos:
        cabecera = f.nombre + (f" ({', '.join(f.relaciones)})" if f.relaciones else "")
        salida.append(cabecera + ("" if f.vivo else f" — {f.murio}"))
        salida.append(f"  {f.sientes}" + (f"; {f.rencor}" if f.rencor else ""))
        if f.publico:
            salida.append(f"  {', '.join(f.publico)}")
        if f.ultimo:
            salida.append(f"  lo último que te hizo: {f.ultimo}")
        if f.visto:
            salida.append(f"  la viste por última vez {f.visto}")
    if not salida:
        salida.append("nadie te es conocido todavía")
    return salida


def diario_lineas(entradas: Sequence[DiaryEntry], ultimas: int = 7) -> list[str]:
    """Las últimas entradas del diario, de la más antigua a la más reciente, para la terminal."""
    if not entradas:
        return ["todavía no hay nada en tu diario"]
    return [f"día {e.dia}: {e.texto}" for e in entradas[-ultimas:]]


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

    def plot(self, vista: PlotView) -> int | None:
        """Una trama le pregunta a la persona qué hace (23a, A.4; 25, A.2). Devuelve la opción
        elegida; vacío o sin respuesta, la de por defecto (que puede no existir: `None`).

        Por defecto, se pregunta como en texto: con `note` y `ask`. Así cualquier presentador
        que solo sabe escribir y leer líneas funciona sin cambios; la web lo sobrescribe."""
        self.note(f"  {vista.plot}:")
        for n, etiqueta in enumerate(vista.options, start=1):
            marca = "  (por defecto)" if vista.defecto == n - 1 else ""
            self.note(f"  {n}. {etiqueta}{marca}")
        while True:
            linea = (self.ask("  ¿Qué haces? ") or "").strip()
            if not linea:
                return vista.defecto
            if linea.isdigit() and 1 <= int(linea) <= len(vista.options):
                return int(linea) - 1
            self.note("  Elige un número de la lista.")


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

    def plot(self, vista: PlotView) -> int | None:
        """Lo de siempre, byte a byte: el título, las opciones con su «(por defecto)», y la
        pregunta hasta que la respuesta sea un número de la lista o vacía."""
        self.note(f"  {vista.plot}:")
        for n, etiqueta in enumerate(vista.options, start=1):
            marca = "  (por defecto)" if vista.defecto == n - 1 else ""
            self.note(f"  {n}. {etiqueta}{marca}")
        while True:
            linea = (self.ask("  ¿Qué haces? ") or "").strip()
            if not linea:
                return vista.defecto
            if linea.isdigit() and 1 <= int(linea) <= len(vista.options):
                return int(linea) - 1
            self.note("  Elige un número de la lista.")
