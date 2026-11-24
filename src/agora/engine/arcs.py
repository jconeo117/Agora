"""Los arcos del mundo (unidad 23b-1, D-179): una historia que dura unos días y cambia el
escenario —situaciones que se encienden, gente que llega y se marcha, contadores que
agregan lo que hace cada cual— y al cerrar reconoce a quien más aportó.

Quién decide qué, y por dónde entra cada cosa:

- `pasar_dia` corre una vez por día, en el límite, antes de las tramas. Un arco en curso
  pasa a la siguiente fase cuando se cumplen sus días o su `until`; un arco que puede
  empezar se sortea con clave. Ningún arco toca a una persona: mueve el escenario, y lo
  que la gente hace con él lo cuentan los contadores.
- `alimentar` lee cada hecho del log al emitirse, por la única puerta de `World._registrar`,
  y suma al contador que corresponde, atribuido a quien lo hizo. Así el arco no pregunta:
  mira lo que ya pasó, igual que el reconocimiento de las tramas.
- Lo que el arco hace al mundo pasa por las puertas que ya existían: `begin_situation`,
  `end_situation`, `arrive`, `afligir`, `partir`, `_marcar`, `_mover_fama`. Este módulo
  decide y guarda su propio `ArcRun`; no escribe en ningún otro sitio.

Dos decisiones que no son obvias y que el tester tiene que conocer:

- Los llegados se derivan por clave (semilla, arco, tick de inicio, fase, tanda, índice).
  Usar el tick de inicio es lo que deja que el mismo arco salga otro día sin repetir ids.
- Un arco sin días fijos (`until`) no tiene reloj: el único freno es su contador. Por eso
  ningún pack de confluencia lo usa todavía; la carga lo admite porque el vocabulario lo
  pide, no porque ningún arco lo necesite.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    AgentId,
    AgentSpec,
    ArcCondition,
    ArcFeed,
    ArcId,
    ArcPeople,
    ArcPhase,
    ArcResult,
    ArcSide,
    ArcSpec,
    ArrivalGroup,
    ArrivalTemplate,
    CounterCond,
    CounterId,
    PhaseId,
    PlaceId,
    SituationId,
)
from agora.engine.state import ArcRun, WorldState

if TYPE_CHECKING:
    from agora.engine.pack import ContentPack
    from agora.engine.world import Simulation as World


# -----------------------------------------------------------------------------
# Lectura: quién es quién, dónde pasa el arco y qué lleva cada uno.
# -----------------------------------------------------------------------------


def _arco(pack: ContentPack, arco: ArcId) -> ArcSpec:
    libro = pack.arcs
    if libro is None:
        raise KeyError(arco)
    for spec in libro.arcs:
        if spec.id == arco:
            return spec
    raise KeyError(arco)


def _fase(arco: ArcSpec, fase: PhaseId) -> ArcPhase:
    for spec in arco.phases:
        if spec.id == fase:
            return spec
    raise KeyError(fase)


def _plantilla(pack: ContentPack, plantilla: str) -> ArrivalTemplate:
    libro = pack.arcs
    if libro is not None:
        for spec in libro.templates:
            if spec.id == plantilla:
                return spec
    raise KeyError(plantilla)


def _condiciones_de_llegada(pack: ContentPack) -> frozenset[SituationId]:
    libro = pack.arcs
    return frozenset() if libro is None else frozenset(t.condition for t in libro.templates)


def bando(state: WorldState, quien: AgentId) -> ArcSide:
    """A qué bando pertenece alguien en este momento: un llegado hostil lleva la condición
    de su plantilla, y cualquier otro es residente. Solo se pregunta por quien vive."""
    agente = state.agents.get(quien)
    if agente is not None and any(
        agente.lleva(c) for c in _condiciones_de_llegada(state.pack)
    ):
        return ArcSide.ARRIVALS
    return ArcSide.RESIDENTS


def _zona_de_fase(pack: ContentPack, fase: ArcPhase) -> frozenset[PlaceId] | None:
    """Dónde se presencia una fase. `None` = en todo el mundo, porque una de sus
    situaciones no tiene lugares. Vacío = la fase no se da en ningún sitio concreto."""
    if fase.places:
        return frozenset(fase.places)
    lugares: set[PlaceId] = set()
    for sit in fase.situations:
        spec = pack.situation_by_id[sit]
        if not spec.places:
            return None
        lugares |= spec.places
    return frozenset(lugares)


def _zona(pack: ContentPack, arco: ArcSpec) -> frozenset[PlaceId] | None:
    """Dónde pasa el arco entero: la unión de sus fases. Un hecho cuenta para el arco si
    ocurre en esta zona; `None` = en cualquier parte."""
    zona: set[PlaceId] = set()
    for fase in arco.phases:
        parcial = _zona_de_fase(pack, fase)
        if parcial is None:
            return None
        zona |= parcial
    return frozenset(zona)


def _en(zona: frozenset[PlaceId] | None, lugar: PlaceId | None) -> bool:
    return zona is None or (lugar is not None and lugar in zona)


def _sembradas(arco: ArcSpec) -> frozenset[str]:
    return frozenset(str(t) for f in arco.phases for t in f.seeds)


def _total(run: ArcRun, contador: CounterId) -> int:
    return sum(run.aportes.get(contador, {}).values())


def _personas(run: ArcRun, grupo: ArcPeople, mundo: World | None) -> int:
    """Cuántas personas forman el grupo ahora: quien llevó la condición durante el arco, quien
    estaba en la zona al entrar en la fase, o quien vive. Solo quien vive necesita el mundo."""
    if grupo.condition is not None:
        return len(run.llevaron.get(grupo.condition, ()))
    if grupo.zone:
        return len(run.en_zona)
    if mundo is None:
        raise ValueError("contar a quien vive pide el mundo")
    return len(mundo.state.agents)


def _cumple_contador(run: ArcRun, c: CounterCond, mundo: World | None = None) -> bool:
    """Una condición de contador en su forma (23b-1-fix, A.1). Las relativas se comparan con
    el total multiplicado por un número declarado: con `n = 0`, las de grupo son falsas."""
    if c.ratio is not None:
        r = c.ratio
        a, b = _total(run, r.counter), _total(run, r.over)
        return (r.at_least is None or a >= r.at_least * b) and (
            r.at_most is None or a <= r.at_most * b
        )
    if c.per is not None:
        p = c.per
        n = _personas(run, p.people, mundo)
        if n == 0:
            return False
        a = _total(run, p.counter)
        return (p.at_least is None or a >= p.at_least * n) and (
            p.at_most is None or a <= p.at_most * n
        )
    if c.counter is None:  # pragma: no cover - `CounterCond` valida que haya una forma
        raise ValueError("condición de contador sin forma")
    if c.mas_que is not None:
        return _total(run, c.counter) > _total(run, c.mas_que)
    total = _total(run, c.counter)
    return (c.min is None or total >= c.min) and (c.max is None or total <= c.max)


def _sumar_a(run: ArcRun, contador: CounterId, quien: AgentId, n: int) -> None:
    """La única escritura de un aporte: suma `n` al contador, atribuido a `quien`."""
    atribuciones = run.aportes.setdefault(contador, {})
    atribuciones[quien] = atribuciones.get(quien, 0) + n


def _arco_que_cuenta(run_arcos: dict[ArcId, ArcRun], pack: ContentPack,
                     contador: CounterId) -> ArcRun | None:
    """El arco en curso que declara este contador, si hay alguno."""
    for arco_id in sorted(run_arcos):
        if any(c.id == contador for c in _arco(pack, arco_id).counters):
            return run_arcos[arco_id]
    return None


# -----------------------------------------------------------------------------
# El día: arrancar, avanzar y cerrar.
# -----------------------------------------------------------------------------


def pasar_dia(mundo: World) -> None:
    """Lo que los arcos hacen una vez al día (23b-1, A.2). Va en el límite de día, con el
    mundo en un solo estado, igual que las tramas."""
    libro = mundo.pack.arcs
    if libro is None:
        return
    s = mundo.state
    for arco_id in sorted(s.arcos):
        if arco_id in s.arcos:
            _avanzar(mundo, _arco(mundo.pack, arco_id), s.arcos[arco_id])
    dia = s.tick // mundo.pack.clock.ticks_per_day
    for arco in libro.arcs:
        if arco.id not in s.arcos and _puede_empezar(mundo, arco, dia):
            comenzar(mundo, arco, porque="disparador")


def _puede_empezar(mundo: World, arco: ArcSpec, dia: int) -> bool:
    """Si algún modo de empezar se cumple hoy. El sorteo sale de una sola clave por arco y
    día: dos modos no tiran dos dados, y el resultado no depende de cuántos modos haya."""
    s = mundo.state
    tpd = mundo.pack.clock.ticks_per_day
    cerrado = s.arcos_terminados.get(arco.id)
    tirada: float | None = None
    for disparo in arco.trigger:
        if disparo.calendar is not None:
            cal = disparo.calendar
            if dia >= cal.start_day and (dia - cal.start_day) % cal.every_days == 0:
                return True
            continue
        if cerrado is not None and s.tick - cerrado[1] < disparo.cooldown_days * tpd:
            continue
        if disparo.conditions and not all(_cumple(mundo, c) for c in disparo.conditions):
            continue
        if tirada is None:
            tirada = s.rng.stream("arco", arco.id, dia).random()
        if disparo.conditions:
            probabilidad = disparo.chance
        else:
            probabilidad = disparo.expected_per_year / mundo.pack.clock.days_per_year
        if tirada < probabilidad:
            return True
    return False


def _cumple(mundo: World, c: ArcCondition) -> bool:
    s = mundo.state
    if c.situation is not None:
        return c.situation in s.active_situations()
    if c.clock_phase is not None:
        return mundo.pack.clock.phase_at(s.tick) == c.clock_phase
    if c.recent is not None:
        corte = s.tick - c.recent.days * mundo.pack.clock.ticks_per_day
        tipo = EventKind(c.recent.event)
        veces = sum(1 for e in mundo.log.since(corte) if e.kind is tipo)
        return veces >= c.recent.n
    if c.ended is not None:
        cerrado = s.arcos_terminados.get(c.ended.arc)
        return cerrado is not None and cerrado[0] == c.ended.branch
    return False


def comenzar(mundo: World, arco: ArcSpec, porque: str) -> None:
    """Empieza un arco en su primera fase. `porque` va al log: un arco es una decisión del
    disparador o de alguien a mano, y el log tiene que decir cuál."""
    s = mundo.state
    inicial = arco.phases[0]
    run = ArcRun(arco=arco.id, empezo=s.tick, fase=inicial.id, desde=s.tick, hasta=None)
    s.arcos[arco.id] = run
    mundo._registrar(
        tick=s.tick, kind=EventKind.ARC_BEGAN,
        data={"arco": str(arco.id), "fase": str(inicial.id), "porque": porque},
    )
    _entrar(mundo, arco, run, inicial)


def comenzar_por_id(mundo: World, arco: ArcId, porque: str) -> None:
    """Empieza un arco por su id. Si ya está en curso, no hace nada: como con las
    situaciones, encender lo que ya pasa no es un error de quien llama."""
    if arco in mundo.state.arcos:
        return
    comenzar(mundo, _arco(mundo.pack, arco), porque)


def _avanzar(mundo: World, arco: ArcSpec, run: ArcRun) -> None:
    fase = _fase(arco, run.fase)
    if not _fase_cumplida(mundo, run, fase):
        return
    _salir(mundo, run, fase)
    destino = _rama(run, fase, mundo)
    if destino is None:
        _cerrar(mundo, arco, run, fase.id)
        return
    _entrar(mundo, arco, run, _fase(arco, destino))


def _fase_cumplida(mundo: World, run: ArcRun, fase: ArcPhase) -> bool:
    if fase.days is not None:
        return run.hasta is not None and mundo.state.tick >= run.hasta
    return fase.until is not None and _cumple_contador(run, fase.until, mundo)


def _rama(run: ArcRun, fase: ArcPhase, mundo: World | None = None) -> PhaseId | None:
    """La primera rama cuyo `if` se cumple; la de por defecto va la última. Sin ramas, el
    arco acaba aquí."""
    for rama in fase.next:
        if rama.if_ is None or _cumple_contador(run, rama.if_, mundo):
            return rama.to
    return None


def _dias(mundo: World, arco: ArcSpec, run: ArcRun, fase: ArcPhase) -> int:
    dias = fase.days
    if dias is None:  # pragma: no cover - `ArcPhase` valida que haya días o `until`
        raise ValueError(f"fase {fase.id!r} sin días")
    if dias.min == dias.max:
        return dias.min
    return mundo.state.rng.stream("arco-dias", arco.id, run.empezo, fase.id).randint(
        dias.min, dias.max,
    )


def _entrar(mundo: World, arco: ArcSpec, run: ArcRun, fase: ArcPhase) -> None:
    """Entra en una fase: enciende sus situaciones, hace sus llegadas y lo presencia quien
    está allí. La siembra de las tramas no hace nada aquí: lee la fase en su `when`."""
    s = mundo.state
    # Quién está en la zona ANTES de que lleguen los de esta fase: es lo que cuenta la
    # condición `people: {zone}` (23b-1-fix, A.1).
    zona = _zona(mundo.pack, arco)
    run.en_zona = frozenset(
        agente.spec_id for agente in s.agents_in_order() if zona is None or agente.at in zona
    )
    run.fase = fase.id
    run.desde = s.tick
    run.hasta = None if fase.days is None else s.tick + _dias(mundo, arco, run, fase) * (
        mundo.pack.clock.ticks_per_day
    )
    encendidas: list[SituationId] = []
    for sit in fase.situations:
        if sit not in s.situations:
            mundo.begin_situation(sit, None, porque=f"arco {arco.id}")
            encendidas.append(sit)
    run.encendidas = tuple(encendidas)
    llegados: list[AgentId] = []
    for indice, grupo in enumerate(fase.arrivals):
        llegados += _llegar(mundo, arco, run, fase, indice, grupo)
    _presenciar(mundo, arco, fase, llegados)


def _salir(mundo: World, run: ArcRun, fase: ArcPhase) -> None:
    """Sale de una fase: apaga lo que encendió y hace partir a quien debe irse al acabarla."""
    s = mundo.state
    for sit in run.encendidas:
        mundo.end_situation(sit)
    run.encendidas = ()
    for quien in sorted(q for q, se_va in run.llegados.items() if se_va):
        if quien in s.agents:
            mundo.partir(quien)
        del run.llegados[quien]


def _cerrar(mundo: World, arco: ArcSpec, run: ArcRun, rama: PhaseId) -> None:
    """Acaba el arco en `rama`: se van los que quedan, se aplican los residuos a quien
    aportó, se reconoce a quien más aportó y se deja constancia (23b-1, A.2)."""
    s = mundo.state
    tpd = mundo.pack.clock.ticks_per_day
    for quien in sorted(run.llegados):
        if quien in s.agents:
            mundo.partir(quien)
    run.llegados.clear()

    residuo = arco.residues.get(rama)
    aportantes = sorted({q for atribuidos in run.aportes.values() for q in atribuidos})
    if residuo is not None:
        for quien in aportantes:
            if quien not in s.agents:
                continue
            for marca, delta in sorted(residuo.marks.items()):
                mundo._marcar(quien, marca, delta)
            if residuo.fame > 0.0:
                mundo._mover_fama(quien, residuo.fame)
        for sit, dias in sorted(residuo.situations.items()):
            mundo.begin_situation(sit, dias * tpd, porque=f"arco {arco.id}")

    # Las tramas de arco de quien quedó sin arco acaban aquí, y su hueco se libera.
    mundo._cerrar_tramas_de_arco(arco.id)
    reconocido = _reconocer(mundo, arco, run)
    del s.arcos[arco.id]
    s.arcos_terminados[arco.id] = (rama, s.tick)
    mundo._registrar(
        tick=s.tick, kind=EventKind.ARC_ENDED,
        data={
            "arco": str(arco.id),
            "rama": str(rama),
            "reconocido": "" if reconocido is None else str(reconocido),
        },
    )


def _reconocer(mundo: World, arco: ArcSpec, run: ArcRun) -> AgentId | None:
    """A quien más aportó a los contadores del reconocimiento, si sigue vivo. El empate lo
    decide un sorteo con clave, nunca el orden de los ids."""
    rec = arco.recognition
    if rec is None:
        return None
    s = mundo.state
    totales: dict[AgentId, int] = {}
    for contador in rec.counters:
        for quien, n in run.aportes.get(contador, {}).items():
            totales[quien] = totales.get(quien, 0) + n
    vivos = [q for q in sorted(totales) if q in s.agents and totales[q] > 0]
    if not vivos:
        return None
    mejor = max(totales[q] for q in vivos)
    elegido = min(
        (q for q in vivos if totales[q] == mejor),
        key=lambda q: (
            s.rng.stream("arco-reconocido", arco.id, run.empezo, q).random(), str(q),
        ),
    )
    mundo._marcar(elegido, rec.mark, 1)
    mundo._mover_fama(elegido, rec.fame)
    return elegido


# -----------------------------------------------------------------------------
# Llegadas y presencia.
# -----------------------------------------------------------------------------


def _llegar(
    mundo: World, arco: ArcSpec, run: ArcRun, fase: ArcPhase, indice: int, grupo: ArrivalGroup,
) -> list[AgentId]:
    """Hace entrar una tanda. Cada llegado sale de su clave: nombre, rasgos e id dependen de
    la semilla, del arco, del tick de inicio, de la fase y del índice, nunca de un contador."""
    s = mundo.state
    plantilla = _plantilla(mundo.pack, grupo.template)
    minimo, maximo = grupo.count
    cuantos = s.rng.stream("arco-llegada", arco.id, run.empezo, fase.id, indice).randint(
        minimo, maximo,
    )
    entraron: list[AgentId] = []
    for k in range(cuantos):
        clave = s.rng.stream("arco-llegado", arco.id, run.empezo, fase.id, indice, k)
        nombre = clave.choice(plantilla.nombres)
        rasgos = {
            rasgo: round(clave.uniform(lo, hi), 4)
            for rasgo, (lo, hi) in sorted(plantilla.traits.items())
        }
        sello = _digest(s.rng.seed, arco.id, run.empezo, fase.id, indice, k)
        ident = AgentId(f"{plantilla.id}-{sello}")
        mundo.arrive(AgentSpec(
            id=ident,
            label=plantilla.label.replace("{nombre}", nombre),
            home=plantilla.home,
            start_at=grupo.at,
            traits=rasgos,
        ))
        mundo.afligir(ident, plantilla.condition, porque=f"arco {arco.id}")
        run.llegados[ident] = grupo.depart
        entraron.append(ident)
    return entraron


def _digest(semilla: int, *partes: object) -> str:
    material = "\x1f".join([str(semilla), *(str(p) for p in partes)]).encode("utf-8")
    return hashlib.blake2b(material, digest_size=5).hexdigest()


def _presenciar(
    mundo: World, arco: ArcSpec, fase: ArcPhase, llegados: list[AgentId],
) -> None:
    """Un `ARC_PHASE` por situación y lugar donde se presencia la fase. Quien está allí lo
    recuerda; de ahí sale como rumor por lo que ya existe (`_contar`). Sin lugares, el
    hecho ocurre y nadie lo presencia. Lleva a los llegados de la fase: el narrador solo
    cuenta por su nombre a los que siguen delante."""
    s = mundo.state
    zona = _zona_de_fase(mundo.pack, fase)
    lugares: list[PlaceId | None] = []
    if zona:
        lugares.extend(sorted(zona))
    if not lugares:
        lugares = [None]
    nombres_llegados = ",".join(sorted(str(q) for q in llegados))
    for sit in fase.situations or (None,):
        for lugar in lugares:
            evento = mundo._registrar(
                tick=s.tick, kind=EventKind.ARC_PHASE, place=lugar,
                data={
                    "arco": str(arco.id),
                    "fase": str(fase.id),
                    "situacion": "" if sit is None else str(sit),
                    "llegados": nombres_llegados,
                },
            )
            if lugar is None:
                continue
            for agente in s.agents_in_order():
                if agente.at == lugar:
                    mundo._grabar(agente, evento, urgencia=1.0, sorpresa=1.0)


# -----------------------------------------------------------------------------
# Aportes: lo que el log dice que alguien hizo dentro de un arco.
# -----------------------------------------------------------------------------


def alimentar(mundo: World, evento: Event) -> None:
    """Lee un hecho recién emitido y suma lo que aporta a los contadores de los arcos en
    curso. Lo llama `World._registrar`, la única puerta por la que entra un hecho al log."""
    s = mundo.state
    if not s.arcos:
        return
    for arco_id in sorted(s.arcos):
        arco = _arco(mundo.pack, arco_id)
        run = s.arcos[arco_id]
        # Quién llevó cada condición personal mientras el arco corre: lo mira `people`.
        if (evento.kind is EventKind.SITUATION_BEGAN and evento.data.get("personal") is True
                and evento.actor is not None):
            run.llevaron.setdefault(
                SituationId(str(evento.data.get("situation"))), set()
            ).add(evento.actor)
        zona = _zona(mundo.pack, arco)
        sembradas = _sembradas(arco)
        for contador in arco.counters:
            for feed in contador.feeds:
                quien = _aportante(feed, evento, zona, sembradas)
                if quien is not None:
                    _sumar_a(run, contador.id, quien, 1)


def _aportante(
    feed: ArcFeed, evento: Event, zona: frozenset[PlaceId] | None, sembradas: frozenset[str],
) -> AgentId | None:
    """Quién se lleva el aporte de este hecho según el aporte, o `None` si el hecho no lo
    cuenta. Las muertes no pasan por aquí: `alimentar_muerte` las atribuye al autor."""
    if feed.combat is not None:
        if evento.kind is not EventKind.COMBAT or not _en(zona, evento.place):
            return None
        gana_actor = evento.data.get("gana") == "actor"
        bando_ganador = evento.data.get("bando_actor" if gana_actor else "bando_otro")
        ganador = evento.actor if gana_actor else evento.subject
        if ganador is None:  # pragma: no cover - un combate siempre tiene dos
            return None
        if feed.result is ArcResult.WON:
            return ganador if str(feed.combat) == bando_ganador else None
        return ganador if str(feed.combat) != bando_ganador else None
    if feed.trial is not None:
        if evento.kind is not EventKind.PLOT_STEP or str(evento.data.get("plot")) not in sembradas:
            return None
        desenlace = evento.data.get("desenlace")
        if desenlace not in ("exito", "fallo"):
            return None
        if (feed.trial is ArcResult.WON) != (desenlace == "exito"):
            return None
        return evento.actor
    if feed.action is not None:
        if evento.kind is not EventKind.ACTION_COMPLETED or evento.action != feed.action:
            return None
        if not _en(zona, evento.place):
            return None
        # La copia que recibe el otro la emite el receptor; quien la hizo es el sujeto.
        return evento.subject if evento.data.get("recibido") else evento.actor
    return None


def alimentar_muerte(mundo: World, quien: AgentId, lugar: PlaceId, autor: AgentId | None) -> None:
    """Una muerte que cuenta para un arco se atribuye a quien la causó. Va desde `morir`,
    antes de borrar al difunto, porque su bando se mira mientras aún está en el reparto."""
    s = mundo.state
    if not s.arcos or autor is None or autor == quien:
        return
    lado = bando(s, quien)
    for arco_id in sorted(s.arcos):
        arco = _arco(mundo.pack, arco_id)
        run = s.arcos[arco_id]
        zona = _zona(mundo.pack, arco)
        for contador in arco.counters:
            for feed in contador.feeds:
                if feed.death is not None and feed.death is lado and _en(zona, lugar):
                    _sumar_a(run, contador.id, autor, 1)


def sumar_de_trama(mundo: World, quien: AgentId, contador: CounterId, n: int) -> None:
    """El efecto `arc_tally` de una trama: suma `n` al contador del arco que lo declara, a
    nombre de quien vive la trama. Si ningún arco en curso lo declara, no suma nada."""
    run = _arco_que_cuenta(mundo.state.arcos, mundo.pack, contador)
    if run is not None:
        _sumar_a(run, contador, quien, n)
