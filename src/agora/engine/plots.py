"""Las tramas personales (unidad 23a, D-178): lo que le pasa a una persona porque el
mundo está como está y porque los demás hacen lo que hacen.

Una trama vive en la cabeza de su protagonista. Las referencias son personas que él
conoce (23-0), y solo se le mira lo observable de ellas. Este módulo **decide** cuándo
empieza una trama, qué latido espera, qué opción elige y qué efectos tiene. No muta
nada por sí mismo: cada cambio pasa por una puerta de `World`, y la acción que una
trama pide a otro (`act`) la ejecuta el motor por sus propias puertas.

Todo el azar sale de `rng.stream` con clave: el mismo mundo, la misma semilla y las
mismas decisiones dan la misma historia. Nada se desempata por un `float` ni por el
orden de un set.

Un recuerdo de trama (`PLOT_STEP` sobre una referencia) cuenta como desenlace de un
duelo cuando su valencia es positiva o negativa. Por eso `won_against` y `lost_to`
leen esa memoria: lo que resultó de un paso con esa persona.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from agora.engine.events import EventKind
from agora.engine.ontology import (
    PROTAGONIST_KINDS,
    REF_KINDS,
    Beat,
    BeatKind,
    Choice,
    EffectSpec,
    PlotCondition,
    PlotSpec,
    PropertyKind,
    Step,
    StepId,
)
from agora.engine.perception import heard, knows, public_facts, saw, seen_together
from agora.engine.ports import Outcome, PlotView
from agora.engine.state import Intencion, PlotRun, WorldState

if TYPE_CHECKING:
    from agora.agents.decide import Decision
    from agora.engine.ontology import ActUse, AgentId, TestUse
    from agora.engine.state import AgentState

    # El motor se llama `Simulation` en world.py; aquí es solo el nombre para tipar.
    from agora.engine.world import Simulation as World


# -----------------------------------------------------------------------------
# Condiciones. Las del protagonista leen lo suyo; las de una referencia, solo lo
# observable (23-0: `public_facts`, `saw`, `heard`, `seen_together`). Ninguna lee el
# aprecio, el agravio, una necesidad o una marca de otro.
# -----------------------------------------------------------------------------


def _rango(valor: float, c: PlotCondition) -> bool:
    return (c.min is None or valor >= c.min) and (c.max is None or valor <= c.max)


def _ventana(mundo: World, c: PlotCondition) -> int:
    """Los días de una condición: los que diga, o la ventana de percepción del pack."""
    return c.days if c.days is not None else mundo.pack.tuning.perception_days


def _global(mundo: World, c: PlotCondition) -> bool:
    """Lo que va en `when`: una situación del mundo o una fase del reloj."""
    if c.situation is not None:
        return c.situation in mundo.state.active_situations()
    return mundo.pack.clock.phase_at(mundo.state.tick) == c.phase


def _del_protagonista(
    mundo: World, yo: AgentState, c: PlotCondition, refs: dict[str, AgentId],
) -> bool:
    """Una condición sobre quien vive la trama: todo lo suyo, incluido lo que siente."""
    s = mundo.state
    pack = mundo.pack
    tick = s.tick
    k = c.kind()
    if k not in PROTAGONIST_KINDS:
        # La carga ya lo rechaza. Llegado aquí, no cumple: no se le da el beneficio.
        return False
    if k == "trait":
        return c.trait is not None and _rango(yo.traits.get(c.trait, 0.0), c)
    if k == "relation":
        return c.relation is not None and bool(yo.relations.get(c.relation))
    if k in ("regard_to", "grudge_to"):
        otro = refs.get(c.regard_to or c.grudge_to or "")
        if otro is None:
            return False
        if k == "regard_to":
            aprecio = yo.regard_for(otro, tick, yo.temperament.bond_fade,
                                    yo.relation_floor(pack, otro))
            return _rango(aprecio, c)
        agravio = s.memoria.agravio(
            yo.spec_id, tick, pack.tuning.grief_scale, pack.tuning.agravio_de_oidas
        ).get(otro, 0.0)
        return _rango(agravio, c)
    if k == "rank":
        return c.rank is not None and _rango(float(yo.rango.get(c.rank, 0)), c)
    if k == "need":
        return c.need is not None and _rango(yo.needs.get(c.need, 0.0), c)
    if k == "mark":
        return c.mark is not None and _rango(
            float(s.marcas.get(yo.spec_id, {}).get(c.mark, 0)), c
        )
    if k == "fame":
        return _rango(s.fama.get(yo.spec_id, 0.0), c)
    if k == "age":
        return _rango(float(yo.edad(tick)), c)
    if k == "situation":
        if c.personal:
            return any(x.situacion == c.situation for x in yo.condiciones)
        return c.situation in s.active_situations() or any(
            x.situacion == c.situation for x in yo.condiciones
        )
    if k == "place":
        return yo.at == c.place
    if k == "phase":
        return pack.clock.phase_at(tick) == c.phase
    if k == "recent_event":
        corte = tick - _ventana(mundo, c) * pack.clock.ticks_per_day
        veces = sum(
            1 for r in s.memoria.de(yo.spec_id)
            if r.kind.value == c.recent_event and r.tick >= corte
        )
        return veces >= (c.min or 1)
    if k == "debt":
        deudas = [p for p in s.propiedades.values() if p.tipo is PropertyKind.DEUDA]
        if c.debt == "debe":
            return any(p.objeto == str(yo.spec_id) for p in deudas)
        return any(p.dueño == yo.spec_id for p in deudas)
    if k == "newcomer":
        llegada = s.llegadas.get(yo.spec_id)
        if llegada is None or c.newcomer is None:
            return False
        return (tick - llegada) / pack.clock.ticks_per_day <= c.newcomer
    return False


def _de_la_referencia(
    mundo: World, yo: AgentState, otro: AgentState, c: PlotCondition,
    refs: dict[str, AgentId],
) -> bool:
    """Una condición sobre otra persona, solo por lo que el protagonista sabe de ella.
    Quien llama ya ha comprobado que `yo` la conoce (`knows`)."""
    s = mundo.state
    pack = mundo.pack
    k = c.kind()
    if k not in REF_KINDS:
        return False
    if k == "with":
        return (otro.at == yo.at) == bool(c.with_)
    if k == "seen_together":
        ya = refs.get(c.seen_together or "")
        if ya is None:
            return False
        return seen_together(s, yo.spec_id, otro.spec_id, ya, _ventana(mundo, c)) >= (c.min or 1)
    if k == "saw":
        if c.saw is None:
            return False
        vistos = saw(s, yo.spec_id, kind=EventKind(c.saw), actor=otro.spec_id,
                     days=_ventana(mundo, c))
        return len(vistos) >= (c.min or 1)
    if k == "heard":
        oyo = bool(heard(s, yo.spec_id, about=otro.spec_id, days=_ventana(mundo, c)))
        return oyo == bool(c.heard)
    facts = public_facts(s, yo.spec_id, otro.spec_id)
    if facts is None:
        return False
    if k == "relation":
        relacion = pack.relation_by_id.get(c.relation) if c.relation is not None else None
        return relacion is not None and relacion.label in {
            etiqueta for etiqueta, _ in facts.relaciones
        }
    if k == "group":
        return bool(facts.grupos) == bool(c.group)
    if k == "creation":
        nombre = pack.trait_by_id[c.creation].label if c.creation in pack.trait_by_id else None
        return nombre in facts.rasgos
    if k == "fame":
        return facts.fama is not None and _rango(facts.fama, c)
    if k == "age":
        return facts.edad is not None and _rango(float(facts.edad), c)
    if k == "visible":
        nombre = pack.situation_by_id[c.visible].label if c.visible in pack.situation_by_id \
            else None
        return nombre in facts.condiciones
    if k == "alive":
        return facts.vivo == bool(c.alive)
    return False


def _cumple_la_referencia(
    mundo: World, yo: AgentState, otro: AgentState, conds: tuple[PlotCondition, ...],
    refs: dict[str, AgentId],
) -> bool:
    return all(_de_la_referencia(mundo, yo, otro, c, refs) for c in conds)


def _cumple(
    mundo: World, yo: AgentState, conds: tuple[PlotCondition, ...],
    refs: dict[str, AgentId],
) -> bool:
    return all(_del_protagonista(mundo, yo, c, refs) for c in conds)


def _mira_a_referencias(c: PlotCondition) -> bool:
    """Si una condición del protagonista necesita las referencias ya elegidas."""
    return c.kind() in ("regard_to", "grudge_to")


# -----------------------------------------------------------------------------
# Disparo: una vez al día por persona, sin trama activa, por sorteo con clave.
# -----------------------------------------------------------------------------


def _trama(mundo: World, trama_id: str) -> PlotSpec:
    libro = mundo.pack.plots
    if libro is None:
        raise KeyError(trama_id)
    for trama in libro.plots:
        if trama.id == trama_id:
            return trama
    raise KeyError(trama_id)


def _paso(trama: PlotSpec, paso_id: StepId) -> Step:
    for paso in trama.steps:
        if paso.id == paso_id:
            return paso
    raise KeyError(paso_id)


def _papeles(
    mundo: World, yo: AgentState, trama: PlotSpec, dia: int,
) -> dict[str, AgentId] | None:
    """A quién mira cada referencia: entre quienes conoce y cumplen, por hash con clave.
    Si un papel no tiene candidato, la trama no empieza (23a, A.2)."""
    s = mundo.state
    refs: dict[str, AgentId] = {}
    for ref in trama.refs:
        candidatos: list[AgentId] = []
        for otro in s.agents_in_order():
            if otro.spec_id == yo.spec_id or otro.spec_id in refs.values():
                continue
            if not knows(s, yo.spec_id, otro.spec_id):
                continue
            if _cumple_la_referencia(mundo, yo, otro, ref.when, refs):
                candidatos.append(otro.spec_id)
        if not candidatos:
            return None
        elegido = min(
            candidatos,
            key=lambda a: (
                s.rng.stream("trama-papel", yo.spec_id, trama.id, ref.name, dia, a).random(),
                str(a),
            ),
        )
        refs[ref.name] = elegido
    return refs


def _sembrar(mundo: World, yo: AgentState, dia: int) -> None:
    """Sortea, entre las tramas que cumplen, la de hoy para esta persona."""
    s = mundo.state
    libro = mundo.pack.plots
    if libro is None:
        return
    tpd = mundo.pack.clock.ticks_per_day
    vividas = s.tramas_vividas.get(yo.spec_id, {})
    candidatas: list[PlotSpec] = []
    for trama in libro.plots:
        ultimo = vividas.get(trama.id)
        if ultimo is not None and (trama.once or s.tick - ultimo < trama.cooldown_days * tpd):
            continue
        if not all(_global(mundo, c) for c in trama.when):
            continue
        # Lo que no mira a nadie, primero: es barato y descarta casi todo.
        if not _cumple(mundo, yo, tuple(c for c in trama.protagonist
                                        if not _mira_a_referencias(c)), {}):
            continue
        # El mismo `chance` para el jugador que para cualquiera (23a, B.2.4).
        if s.rng.stream("trama", yo.spec_id, trama.id, dia).random() < trama.chance:
            candidatas.append(trama)
    if not candidatas:
        return
    # Si salen varias, una sola, por hash con clave y nunca por el orden de la lista.
    candidatas.sort(key=lambda t: (
        s.rng.stream("trama-una", yo.spec_id, t.id, dia).random(), str(t.id),
    ))
    for trama in candidatas:
        refs = _papeles(mundo, yo, trama, dia)
        if refs is None:
            continue
        if not _cumple(mundo, yo, tuple(c for c in trama.protagonist
                                        if _mira_a_referencias(c)), refs):
            continue
        _empezar(mundo, yo, trama, refs)
        return


def _empezar(mundo: World, yo: AgentState, trama: PlotSpec, refs: dict[str, AgentId]) -> None:
    s = mundo.state
    s.tramas[yo.spec_id] = PlotRun(
        plot=trama.id, empezo=s.tick, refs=dict(refs), paso=trama.steps[0].id, desde=s.tick,
    )
    s.tramas_vividas.setdefault(yo.spec_id, {})[trama.id] = s.tick
    mundo._registrar(
        tick=s.tick, kind=EventKind.PLOT_BEGAN, actor=yo.spec_id, place=yo.at,
        data={"plot": str(trama.id), "refs": _papeles_texto(refs)},
    )


def _papeles_texto(refs: dict[str, AgentId]) -> str:
    return ",".join(f"{nombre}={refs[nombre]}" for nombre in sorted(refs))


# -----------------------------------------------------------------------------
# Latidos: se miran una vez al día, contra lo que el protagonista percibió desde que
# empezó el paso.
# -----------------------------------------------------------------------------


def _ocurrio(mundo: World, yo: AgentState, run: PlotRun, beat: Beat) -> bool:
    s = mundo.state
    pack = mundo.pack
    desde = run.desde
    dias = max(1, math.ceil((s.tick - desde) / pack.clock.ticks_per_day))
    me = yo.spec_id
    k = beat.kind
    if k is BeatKind.SITUATION_BEGAN:
        return any(r.kind is EventKind.SITUATION_BEGAN and r.tick >= desde
                   for r in s.memoria.de(me))
    ref = run.refs.get(beat.ref) if beat.ref is not None else None
    if ref is None:
        return False
    if k is BeatKind.ARRIVED:
        visto = yo.sightings.get(yo.at)
        return visto is not None and visto[0] >= desde and ref in visto[1]
    if k is BeatKind.REF_RANK_UP:
        return any(r.kind is EventKind.RANK_UP and r.about == ref and r.tick >= desde
                   for r in s.memoria.de(me))
    if k in (BeatKind.WON_AGAINST, BeatKind.LOST_TO):
        duelos = [r for r in s.memoria.de(me)
                  if r.kind is EventKind.PLOT_STEP and r.about == ref and r.tick >= desde]
        if k is BeatKind.WON_AGAINST:
            return any(r.valencia > 0.0 for r in duelos)
        return any(r.valencia < 0.0 for r in duelos)
    if k is BeatKind.REF_DIED:
        if any(p.target == ref for p in saw(s, me, kind=EventKind.AGENT_DIED, days=dias)
               if p.tick >= desde):
            return True
        return any(r.kind is EventKind.AGENT_DIED and r.about == ref and r.tick >= desde
                   for r in s.memoria.de(me))
    vistos = [p for p in saw(s, me, days=dias) if p.tick >= desde]
    if k is BeatKind.TALKED_WITH:
        return any(p.actor == ref and p.target == me for p in vistos)
    if k is BeatKind.DECLARED_TO:
        return any(p.actor == ref and p.target == me and p.acto == "cortejar" for p in vistos)
    if k is BeatKind.HELPED_BY:
        for p in vistos:
            if p.actor != ref or p.target != me:
                continue
            # Un objeto dado (sin acción) cuenta siempre; una acción, con su etiqueta.
            if p.action is None or (beat.tag is not None
                                    and beat.tag in pack.action_by_id[p.action].tags):
                return True
        return False
    if k is BeatKind.SEEN_WITH:
        for p in vistos:
            if p.target is None or ref not in (p.actor, p.target):
                continue
            otro = p.target if p.actor == ref else p.actor
            if otro not in (me, ref):
                return True
        return False


# -----------------------------------------------------------------------------
# Pasos, plazos y el fin de una trama.
# -----------------------------------------------------------------------------


def _ir_a(mundo: World, yo: AgentState, run: PlotRun, paso: StepId | None, motivo: str) -> None:
    """Avanza a otro paso, o acaba la trama si no hay ninguno."""
    if paso is None:
        _terminar(mundo, yo, run, motivo)
        return
    run.paso = paso
    run.desde = mundo.state.tick


def _terminar(mundo: World, yo: AgentState, run: PlotRun, motivo: str) -> None:
    s = mundo.state
    s.tramas.pop(yo.spec_id, None)
    mundo._registrar(
        tick=s.tick, kind=EventKind.PLOT_ENDED, actor=yo.spec_id, place=yo.at,
        data={"plot": str(run.plot), "motivo": motivo},
    )


def pasar_dia(mundo: World) -> None:
    """Lo que una trama hace una vez al día (23a, A.2 y A.3): la fama baja, los latidos
    se miran, los plazos caducan y las personas sin trama tiran los dados.

    Va al empezar el día del reloj, con el mundo ya en un solo estado (ver `tick`)."""
    s = mundo.state
    libro = mundo.pack.plots
    if libro is None:
        return
    dia = s.tick // mundo.pack.clock.ticks_per_day
    if libro.fame is not None:
        for quien in sorted(s.fama):
            s.fama[quien] = max(0.0, s.fama[quien] - libro.fame.decay_per_day)
    for yo in list(s.agents_in_order()):
        run = s.tramas.get(yo.spec_id)
        if run is None:
            _sembrar(mundo, yo, dia)
        else:
            _avanzar_dia(mundo, yo, run)


def _avanzar_dia(mundo: World, yo: AgentState, run: PlotRun) -> None:
    s = mundo.state
    tpd = mundo.pack.clock.ticks_per_day
    if run.intencion is not None:
        if s.tick > run.intencion.vence:
            siguiente = run.intencion.si_caduca
            run.intencion = None
            _caduca(mundo, yo, run)
            _ir_a(mundo, yo, run, siguiente, "caducada")
        return
    paso = _paso(_trama(mundo, run.plot), run.paso)
    if paso.expects is None:
        return  # un paso de decisión espera a que la persona quede ociosa
    if _ocurrio(mundo, yo, run, paso.expects):
        mundo._registrar(
            tick=s.tick, kind=EventKind.PLOT_BEAT, actor=yo.spec_id, place=yo.at,
            data={"plot": str(run.plot), "paso": str(paso.id),
                  "latido": paso.expects.kind.value},
        )
        _ir_a(mundo, yo, run, paso.next, "fin")
        return
    if paso.within_days is not None and s.tick - run.desde >= paso.within_days * tpd:
        _caduca(mundo, yo, run)
        _ir_a(mundo, yo, run, paso.on_timeout, "caducada")


def _caduca(mundo: World, yo: AgentState, run: PlotRun) -> None:
    """Un plazo que vence deja rastro, vaya adonde vaya la trama después. Sin esto, una
    espera que caducaba hacia otro paso no se veía, y «latidos a tiempo» contaba solo
    las que acababan la trama."""
    mundo._registrar(
        tick=mundo.state.tick, kind=EventKind.PLOT_STEP, actor=yo.spec_id, place=yo.at,
        data={"plot": str(run.plot), "paso": str(run.paso), "desenlace": "caducada"},
    )


# -----------------------------------------------------------------------------
# Decisiones: al quedar ociosa la persona. NPC por carácter; el jugador, por su fuente.
# -----------------------------------------------------------------------------


def al_quedar_ocioso(mundo: World, yo: AgentState) -> bool:
    """Lo que la trama de esta persona pide en su momento ocioso. Devuelve `True` si una
    acción de la trama ya se ejecutó en ese momento: entonces no se delibera otra cosa.
    Un paso de decisión se resuelve, y el momento sigue libre para deliberar."""
    run = mundo.state.tramas.get(yo.spec_id)
    if run is None:
        return False
    if run.intencion is not None:
        return _ejecutar_intencion(mundo, yo, run)
    trama = _trama(mundo, run.plot)
    paso = _paso(trama, run.paso)
    if not paso.choices:
        return False
    return _decidir(mundo, yo, run, trama, paso)


def _decidir(
    mundo: World, yo: AgentState, run: PlotRun, trama: PlotSpec, paso: Step,
) -> bool:
    disponibles = [c for c in paso.choices if _cumple(mundo, yo, c.requires, run.refs)]
    if not disponibles:
        _terminar(mundo, yo, run, "sin opciones")
        return False
    if yo.spec_id == mundo.state.player:
        elegida = _elige_jugador(mundo, yo, trama, disponibles)
    else:
        elegida = _elige_npc(mundo, yo, trama, paso, disponibles)
    return _aplicar_opcion(mundo, yo, run, paso, elegida)


def _elige_npc(
    mundo: World, yo: AgentState, trama: PlotSpec, paso: Step, disponibles: list[Choice],
) -> Choice:
    """Softmax sobre lo que la opción le aporta a su carácter (`appeal` · rasgos), con la
    temperatura de la persona. Misma semilla, misma opción."""
    s = mundo.state
    pesos = [
        math.exp(sum(peso * yo.traits.get(rasgo, 0.0) for rasgo, peso in c.appeal.items())
                 / yo.temperament.temperature)
        for c in disponibles
    ]
    dia = s.tick // mundo.pack.clock.ticks_per_day
    rng = s.rng.stream("trama-elige", yo.spec_id, trama.id, paso.id, dia)
    return rng.choices(disponibles, weights=pesos, k=1)[0]


def _elige_jugador(
    mundo: World, yo: AgentState, trama: PlotSpec, disponibles: list[Choice],
) -> Choice:
    defecto = next((i for i, c in enumerate(disponibles) if c.default), None)
    vista = PlotView(
        plot=trama.label,
        options=tuple(c.label for c in disponibles),
        defecto=defecto,
    )
    indice = mundo.pedir_trama(yo, vista)
    if indice is None:
        indice = defecto if defecto is not None else len(disponibles) - 1
    if not 0 <= indice < len(disponibles):
        raise ValueError(f"{yo.spec_id}: la opción de trama {indice} no existe")
    return disponibles[indice]


def _aplicar_opcion(
    mundo: World, yo: AgentState, run: PlotRun, paso: Step, opcion: Choice,
) -> bool:
    """Aplica la opción elegida. Devuelve `True` si era un `act` y se ejecutó ya."""
    s = mundo.state
    desenlace = "plano"
    if opcion.effects is not None:
        for e in opcion.effects:
            _efecto(mundo, yo, run, e)
    elif opcion.test is not None:
        exito = _probar(mundo, yo, run, opcion.test)
        desenlace = "exito" if exito else "fallo"
        # Un duelo con alguien deja su desenlace en la memoria de quien lo gana o pierde:
        # es lo que leen `won_against` y `lost_to`.
        rival = run.refs.get(opcion.test.vs or "")
        if rival is not None:
            mundo._recordar_de_trama(yo.spec_id, rival, 1.0 if exito else -1.0, 1.0, None)
        for e in (opcion.test.on_success if exito else opcion.test.on_failure):
            _efecto(mundo, yo, run, e)
    elif opcion.act is not None:
        mundo._registrar(
            tick=s.tick, kind=EventKind.PLOT_STEP, actor=yo.spec_id, place=yo.at,
            data={"plot": str(run.plot), "paso": str(paso.id), "opcion": opcion.label,
                  "desenlace": "intencion"},
        )
        return _empezar_intencion(mundo, yo, run, opcion.act, opcion.next)
    mundo._registrar(
        tick=s.tick, kind=EventKind.PLOT_STEP, actor=yo.spec_id, place=yo.at,
        data={"plot": str(run.plot), "paso": str(paso.id), "opcion": opcion.label,
              "desenlace": desenlace},
    )
    _ir_a(mundo, yo, run, opcion.next, "fin")
    return False


def _empezar_intencion(
    mundo: World, yo: AgentState, run: PlotRun, act: ActUse, siguiente: StepId | None,
) -> bool:
    """La acción queda pedida: se ejecuta cuando esté en el menú, y mientras tanto la
    inclina (A.5). Si el plazo se cumple sin que lo esté, la trama sigue por `on_timeout`.
    Devuelve `True` si ya estaba en el menú y se ejecutó."""
    run.intencion = Intencion(
        action=act.action,
        ref=run.refs[act.to],
        vence=mundo.state.tick + act.within_days * mundo.pack.clock.ticks_per_day,
        siguiente=siguiente,
        si_caduca=act.on_timeout,
    )
    return _ejecutar_intencion(mundo, yo, run)


def _ejecutar_intencion(mundo: World, yo: AgentState, run: PlotRun) -> bool:
    """Si la acción pedida está en el menú de la persona ahora, la ejecuta el motor por
    `hacer_de_trama`, con sus puertas. Devuelve `True` si lo hizo."""
    intencion = run.intencion
    if intencion is None:
        return False
    for decision in mundo.opciones_de(yo):
        if decision.action == intencion.action and decision.target == intencion.ref:
            # Antes que la acción: lo que la pidió va antes que lo que causa, como en el
            # log de una charla. Así se ve qué acción salió de una trama y cuál no.
            mundo._registrar(
                tick=mundo.state.tick, kind=EventKind.PLOT_STEP, actor=yo.spec_id,
                place=yo.at, subject=intencion.ref,
                data={"plot": str(run.plot), "paso": str(run.paso), "desenlace": "ejecutada"},
            )
            mundo.hacer_de_trama(yo, decision)
            run.intencion = None
            _ir_a(mundo, yo, run, intencion.siguiente, "fin")
            return True
    return False


def _efecto(mundo: World, yo: AgentState, run: PlotRun, e: EffectSpec) -> None:
    """Un efecto, por su puerta. Solo cambia al protagonista. Lo que toca a otro pasa por
    una acción del mundo (`act`), nunca por aquí; los efectos que nombran a una
    referencia lo hacen por lo que ella le debe o lo que él recuerda de ella."""
    if e.mark is not None:
        mundo._marcar(yo.spec_id, e.mark, int(e.delta or 0))
    elif e.fame is not None:
        mundo._mover_fama(yo.spec_id, e.delta or 0.0)
    elif e.need is not None:
        mundo._mover_necesidad(yo.spec_id, e.need, e.delta or 0.0)
    elif e.regard is not None:
        otro = run.refs.get(e.regard)
        if otro is not None:
            mundo._mover_aprecio(yo.spec_id, otro, e.delta or 0.0)
    elif e.memory:
        otro = run.refs.get(e.about or "")
        por = run.refs.get(e.por_quien or "")
        if otro is not None:
            mundo._recordar_de_trama(yo.spec_id, otro, e.valence or 0.0,
                                     e.importance or 0.0, por)
    elif e.condition is not None:
        mundo._condicion_de_trama(yo.spec_id, e.condition, e.days)
    elif e.goal is not None:
        mundo._asignar_meta(yo.spec_id, e.goal)
    elif e.debt is not None:
        otro = run.refs.get(e.debt)
        if otro is not None and e.action is not None:
            mundo._prestar_de_trama(yo.spec_id, otro, e.action,
                                    presta=e.direction == "presto")
    elif e.forgive is not None:
        otro = run.refs.get(e.forgive)
        if otro is not None:
            mundo._perdonar(yo.spec_id, otro, e.factor or 1.0)
    elif e.item is not None:
        mundo._soltar_de_trama(yo.spec_id, e.item)


def _probar(mundo: World, yo: AgentState, run: PlotRun, uso: TestUse) -> bool:
    """Una prueba enfrentada. Si el sistema de la mesa la sabe, tira él (`contest`); si
    no, la regla de respaldo compara los rasgos que el pack declara, con un sorteo por
    clave (23a, A.4)."""
    s = mundo.state
    libro = mundo.pack.plots
    if libro is None:
        return False
    declarada = libro.tests[uso.id]
    rival = run.refs.get(uso.vs or "")
    resolver = mundo.social_resolver
    contienda = None if resolver is None else resolver.contest(
        s, yo.spec_id, rival, str(uso.id), f"{run.plot}:{s.tick}",
    )
    if contienda is not None:
        return contienda.resolution.outcome is not Outcome.FAILURE
    a = yo.traits.get(declarada.actor, 0.0)
    if declarada.against is not None and rival is not None and rival in s.agents:
        b = s.agents[rival].traits.get(declarada.against, 0.0)
        p = 0.5 if a + b <= 0.0 else a / (a + b)
    else:
        p = min(1.0, max(0.0, a))
    return s.rng.stream("trama-prueba", yo.spec_id, uso.id, s.tick).random() < p


# -----------------------------------------------------------------------------
# Inclinación: lo que una trama empuja a la decisión de su protagonista (A.5).
# -----------------------------------------------------------------------------


def inclinacion(state: WorldState, yo: AgentState, opcion: Decision) -> float:
    """El multiplicador que la trama de `yo` da a una opción. Sin trama, 1. Nunca toca a
    la referencia: solo la utilidad del protagonista, con el tope de `tuning`."""
    run = state.tramas.get(yo.spec_id)
    if run is None:
        return 1.0
    tope = state.pack.tuning.plot_lean_max
    visto = yo.sightings.get(opcion.place)
    factor = 1.0
    if run.intencion is not None:
        # Una acción pedida inclina hacia donde se ve a la referencia, al tope.
        if visto is not None and run.intencion.ref in visto[1]:
            factor *= tope
    elif state.pack.plots is not None:
        trama = next((t for t in state.pack.plots.plots if t.id == run.plot), None)
        paso = None if trama is None else next(
            (p for p in trama.steps if p.id == run.paso), None
        )
        if paso is not None and paso.expects is not None:
            for lean in paso.leanings:
                if lean.where_seen is not None:
                    ref = run.refs.get(lean.where_seen)
                    if ref is not None and visto is not None and ref in visto[1]:
                        factor *= lean.multiplier
                elif lean.action_tag is not None and \
                        lean.action_tag in state.pack.action_by_id[opcion.action].tags:
                    factor *= lean.multiplier
    return min(tope, max(1.0 / tope, factor))
