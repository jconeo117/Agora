"""Salto temporal: avanzar meses sin simular cada cuarto de hora.

Una carrera de cinco anos son 172 800 ticks. Con ciento veintisiete habitantes
eso son horas de corrida continua, y casi todo es rutina: la gente come, duerme y
va a clase tres mil seiscientas veces.

LO QUE NO FUNCIONO, porque costo cuatro mediciones averiguarlo.

La idea evidente es proyectar: mides a que ritmo se mueve cada eje y multiplicas
por los dias que saltas. No sirve, y el motivo es de fondo — **un eje en
equilibrio tiene deriva cero, pero medida sobre catorce dias da un numero pequeno
distinto de cero, y multiplicado por ciento ochenta desplaza medio punto**. Se
probo comparando extremos, comparando las medias de dos mitades, y midiendo senal
contra ruido. Los tres dejaban el mundo saltado con desviaciones de 0.2 en ejes
como el vinculo o las provisiones: un mundo plausible, pero no ESE mundo.

LO QUE SI FUNCIONA es no adivinar nada:

    Se simulan dias DE VERDAD, solo que menos. Uno de cada `factor`. Y a los ejes
    que solo suben se les da el avance de los `factor` dias completos.

Con eso, todo lo que oscila —sustento, descanso, nucleo, vinculo— queda EXACTO,
porque no se estima: se simula. Lo unico aproximado es lo monotono, que es
precisamente lo suave y lo que aguanta que se le den zancadas.

Y el reloj avanza igual para todos: los avistamientos y los vinculos adelantan su
marca con el, o un salto de seis meses caducaria de golpe toda la memoria de la
ciudad y `forget_bonds` la borraria entera al tick siguiente.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from agora.engine.events import EventKind
from agora.engine.ontology import NeedId
from agora.engine.world import Simulation


@dataclass(frozen=True, slots=True)
class Salto:
    """Que se simulo de verdad y que se dio por hecho."""

    dias_pedidos: int
    dias_simulados: int
    factor: int
    amplificados: frozenset[NeedId]
    """Los ejes a los que se les dio la zancada. El resto se simulo tal cual."""

    @property
    def ahorro(self) -> float:
        """Cuantas veces mas rapido que simularlo entero."""
        return self.dias_pedidos / max(self.dias_simulados, 1)


def _amplificables(sim: Simulation) -> frozenset[NeedId]:
    """Los ejes que solo suben, y nada mas.

    `progression` es exactamente la garantia que hace falta: monotono, sin
    equilibrio al que volver y sin oscilacion que amplificar. Un eje que se mece
    NO entra aunque derive un poco — se simula, y asi no hay nada que estimar.

    Como efecto lateral, los que derivan sin ser progresion (en la ciudad,
    `estimulo` y `botin`) avanzan a velocidad normal y se quedan algo cortos. Es
    un error acotado y conocido, y muy preferible a inventarles un ritmo.
    """
    return frozenset(n.id for n in sim.pack.needs if n.progression)


def saltar(sim: Simulation, dias: int, factor: int = 7) -> Salto:
    """Avanza `dias` simulando uno de cada `factor`.

    `factor` a 1 es simular de verdad, sin atajo. Cuanto mas alto, mas rapido y
    mas gruesa la zancada de lo monotono: a 7 un dia representa una semana.

    Las metas se resuelven en el tick loop de siempre, asi que un arco que se
    cumpla a mitad del salto se cumple a mitad del salto —con la resolucion del
    factor, no la del salto entero—. Eso es lo que permite que lo que venga
    despues cuente ya con los rasgos cambiados.
    """
    if factor <= 1 or dias <= 0:
        sim.run(max(0, dias) * sim.pack.clock.ticks_per_day)
        return Salto(dias, max(0, dias), 1, frozenset())

    ticks_dia = sim.pack.clock.ticks_per_day
    amplificar = _amplificables(sim)
    dias_simulados = math.ceil(dias / factor)

    restantes = dias
    for _ in range(dias_simulados):
        # El ultimo tramo se recorta para caer EXACTO: con factor 7 y noventa
        # dias, doce zancadas completas y una de seis. Redondear hacia arriba
        # dejaria el reloj un dia por delante de lo pedido.
        tramo = min(factor, restantes)
        antes = {
            a.spec_id: {eje: a.needs[eje] for eje in amplificar}
            for a in sim.state.agents_in_order()
        }
        inicio = sim.state.tick
        sim.run(ticks_dia)

        for agente in sim.state.agents_in_order():
            # Quien no estaba al empezar el dia no cobra zancada: nacio a mitad
            # (D-071), y darsela seria adelantarle un progreso de dias en los
            # que no existia. Sale del mismo sitio que la agonia que se borra:
            # lo que no se simula, no se inventa.
            previo = antes.get(agente.spec_id)
            if previo is None:
                continue
            # La zancada: lo que subio hoy, otras `factor - 1` veces. Pasa por
            # `restore` y no por asignacion directa para que respete el techo y
            # la deuda, como cualquier otra ganancia.
            #
            # SOLO LOS MONOTONOS, y se intento lo contrario (D-089): darle la
            # zancada al NETO de todos los ejes -- lo que decayo menos lo que el
            # agente hizo para compensarlo-- para arreglar de un golpe los ejes
            # de decaimiento lento y las muertes violentas, que llegan por ese
            # mismo canal. Medido a 60 dias con factor 7: el error medio de eje
            # subio de 0.045 a 0.147, las muertes pasaron del 114% al 214% de
            # las reales y las rupturas EMPEORARON (del 31% al 12%). La premisa
            # de la rutina no aguanta la amplificacion: el neto de un solo dia
            # es un punto arbitrario del ciclo, y multiplicarlo por seis
            # convierte el ruido en deriva. Es la segunda vez que este modulo
            # mide eso y le sale lo mismo.
            for eje in amplificar:
                ganado = agente.needs[eje] - previo[eje]
                if ganado > 0.0:
                    agente.restore(eje, ganado * (tramo - 1))

        _adelantar_reloj(sim, (tramo - 1) * ticks_dia, visto_desde=inicio)
        restantes -= tramo

    return Salto(dias, dias_simulados, factor, amplificar)


def _adelantar_reloj(
    sim: Simulation, ticks: int, visto_desde: int | None = None
) -> None:
    """Mueve el reloj sin simular, arrastrando lo que depende de el.

    La EDAD no necesita nada de esto y conviene tenerlo escrito: `nacido_en` es
    un tick absoluto (D-070), asi que adelantar el reloj envejece a todo el
    mundo solo, y una espera con plazo (`Condicion.hasta`, tambien absoluto)
    vence al otro lado del hueco sin que nadie la empuje. Es la ventaja de
    guardar CUANDO paso algo en vez de cuanto lleva.

    **Lo que si cobra la zancada** es lo que una condicion personal drena: no es
    una estimacion sino aritmetica, porque una condicion aplica lo mismo cada
    tick, viaje donde viaje quien la lleva. Y con ella la agonia, que ya no se
    borra: avanza donde el eje sigue a cero despues de simular el dia.

    Los avistamientos y los vinculos guardan CUANDO se vieron, y caducan solos.
    Sin adelantar sus marcas con el reloj, un salto de seis meses los invalidaria
    todos de golpe: nadie recordaria un sitio y `forget_bonds` borraria la ciudad
    entera el primer tick despues del salto. Pero solo adelantan las de quien se
    vio EL DIA SIMULADO (D-088): a quien no viste, el hueco le cuenta entero.
    """
    sim.state.tick += ticks
    by_situation = sim.pack.situation_by_id
    need_specs = sim.pack.need_by_id
    for agente in sim.state.agents_in_order():
        # LO QUE UNA CONDICION DRENA SI COBRA LA ZANCADA, y es la unica cosa que
        # este salto extrapola. No contradice la regla de arriba —no se estima
        # una deriva medida— porque aqui no hay nada que medir: una condicion
        # personal drena `effects * gravedad` cada tick, viaja con quien la
        # lleva y no depende de donde este ni de lo que haga. Multiplicar por los
        # ticks saltados es aritmetica, no una suposicion.
        #
        # Las situaciones del LUGAR no entran, y la diferencia es justo esa:
        # dependen de donde este cada cual, y donde estuvo esos dias no se
        # simulo.
        drenaje: dict[NeedId, float] = {}
        for cond in agente.condiciones:
            for need_id, delta in by_situation[cond.situacion].effects.items():
                if delta < 0.0:
                    drenaje[need_id] = (
                        drenaje.get(need_id, 0.0) + delta * cond.gravedad * ticks
                    )
        if drenaje:
            agente.endure(drenaje, need_specs)

        # LA AGONIA avanza solo donde el eje SIGUE a cero al otro lado del hueco.
        #
        # Antes se borraba entera, y el razonamiento era bueno para lo que habia
        # entonces: cuenta ticks SEGUIDOS, adelantarla mataba a todo el que
        # estuviera a cero al saltar, y los dias simulados demuestran que esa
        # gente come. Pero esa objecion la contesta la propia condicion de
        # arriba: si comio, el dia simulado lo levanta del cero y esto no le
        # avanza nada. Si sigue a cero DESPUES de simular un dia entero y de
        # cobrar lo que sus condiciones drenan, decir que estuvo a cero todo el
        # hueco es la lectura mas fiel que hay — y borrarlo hacia imposible
        # morirse de nada bajo salto, que es peor que estimar de mas.
        #
        # CONSECUENCIA: una carrera de anyos con `--skip` ya produce muertes por
        # necesidad, y sobre todo por vejez (D-084), que es un drenaje constante
        # que nadie levanta. Lo que sigue sin producir son las muertes de quien
        # se hunde y se recupera dentro del hueco: eso no se simulo y no se
        # inventa.
        agente.agonia = {
            need_id: llevan + ticks
            for need_id, llevan in agente.agonia.items()
            if agente.needs[need_id] <= 0.0
        }
        # Las marcas de «cuándo lo vi» adelantan con el reloj, PERO SOLO LAS DE
        # QUIEN SE VIO EL DÍA SIMULADO (D-088).
        #
        # Antes adelantaban todas, y el motivo era bueno: sin eso, un salto de
        # seis meses caducaría de golpe toda la memoria del mundo y
        # `forget_bonds` la borraría entera al tick siguiente. Pero el
        # instrumento era romo — para no caducar los vínculos de la gente con la
        # que convives, congelaba también los de la gente a la que no ves, y con
        # ellos `tick - last_seen` no crecía nunca. Consecuencia medida: bajo
        # salto no se rompía ni una pareja por desapego (D-087) en 400 días,
        # contra 89 en 120 días sin salto.
        #
        # La corrección es fina y el miedo original desaparece solo: a quien ves
        # cada día lo ves también el día simulado, así que su marca queda fresca
        # y no caduca nada. A quien no viste, el hueco le cuenta entero — que es
        # lo cierto.
        for bond in agente.bonds.values():
            if visto_desde is None or bond.last_seen >= visto_desde:
                bond.last_seen += ticks
        agente.sightings = {
            sitio: ((visto + ticks, quienes)
                    if visto_desde is None or visto >= visto_desde
                    else (visto, quienes))
            for sitio, (visto, quienes) in agente.sightings.items()
        }
    # Los disparadores tambien cobran su zancada, y por la misma razon que los
    # avistamientos: dependen del reloj, y adelantarlo sin darsela los deja
    # evaluandose una vez cada `factor` dias. Con --skip 14 el mundo tendria
    # catorce veces menos imprevistos sin que nada lo dijera. Ver `_fire_triggers`.
    sim._fire_triggers(span=ticks)


@dataclass(frozen=True, slots=True)
class Fidelidad:
    """Cuanto miente el salto, en las dos monedas que hacen falta (D-088).

    `ejes` era todo lo que este instrumento medía, y por eso durante un tiempo
    dijo que el salto estaba sano mientras suprimía la mitad de las muertes del
    mundo: una media poblacional no ve un SUCESO. Lo que no ocurrió no desvía
    ninguna media — simplemente no está.
    """

    ejes: dict[NeedId, float]
    """Desviacion absoluta de la media poblacional, eje por eje."""

    muertes: tuple[int, int]
    """Cuantas hubo (real, saltado)."""

    partos: tuple[int, int]
    lazos_rotos: tuple[int, int]
    lazos_nuevos: tuple[int, int]
    poblacion: tuple[int, int]

    def sucesos(self) -> dict[str, tuple[int, int]]:
        """Los contadores juntos, para imprimirlos de una pasada."""
        return {
            "muertes": self.muertes,
            "partos": self.partos,
            "lazos rotos": self.lazos_rotos,
            "lazos nuevos": self.lazos_nuevos,
            "poblacion": self.poblacion,
        }


def error_de_salto(sim_base: Simulation, dias: int, factor: int = 7) -> Fidelidad:
    """Cuanto miente el salto: medias de eje Y RECUENTO DE SUCESOS.

    Se comparan las medias y no agente por agente, y la distincion importa: dos
    mundos sanos pueden tener a la misma persona en distinto punto de su ciclo de
    sueno sin que ninguno este mal. Lo que dice si el salto sirve es si la
    POBLACION quedo donde habria quedado.

    Y se cuentan los SUCESOS aparte, que es lo que faltaba (D-088). Una media
    poblacional no ve lo que no ocurrio: el salto suprimia las muertes violentas
    y todas las rupturas por desapego, y este instrumento decia que el mundo
    estaba sano porque los ejes cuadraban. Lo que no pasa no desvia ninguna
    media.

    Existe porque un salto es una aproximacion y ocultarlo seria peor que no
    tenerlo. Un pack donde esto salga alto no deberia saltar.
    """
    from copy import deepcopy

    saltado = deepcopy(sim_base)
    saltar(saltado, dias, factor)

    real = deepcopy(sim_base)
    real.run(dias * real.pack.clock.ticks_per_day)

    salida: dict[NeedId, float] = {}
    poblacion = len(real.state.agents)
    for need in real.pack.needs:
        media_real = sum(a.needs[need.id] for a in real.state.agents_in_order()) / poblacion
        media_salto = sum(
            a.needs[need.id] for a in saltado.state.agents_in_order()
        ) / max(len(saltado.state.agents), 1)
        salida[need.id] = abs(media_real - media_salto)

    def cuenta(sim: Simulation, kind: EventKind, relacion: bool = False) -> int:
        eventos = sim.log.of_kind(kind)
        if not relacion:
            # Una muerte se emite una vez por superviviente que la sufre, asi
            # que lo que se cuenta es a cuanta gente distinta le paso.
            return len({e.subject for e in eventos})
        return len(eventos)

    return Fidelidad(
        ejes=salida,
        muertes=(cuenta(real, EventKind.AGENT_DIED), cuenta(saltado, EventKind.AGENT_DIED)),
        partos=(len(real.log.of_kind(EventKind.AGENT_BORN)),
                len(saltado.log.of_kind(EventKind.AGENT_BORN))),
        lazos_rotos=(cuenta(real, EventKind.RELATION_ENDED, True),
                     cuenta(saltado, EventKind.RELATION_ENDED, True)),
        lazos_nuevos=(cuenta(real, EventKind.RELATION_BEGAN, True),
                      cuenta(saltado, EventKind.RELATION_BEGAN, True)),
        poblacion=(len(real.state.agents), len(saltado.state.agents)),
    )
