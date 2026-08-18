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
        sim.run(ticks_dia)

        for agente in sim.state.agents_in_order():
            # La zancada: lo que subio hoy, otras `factor - 1` veces. Pasa por
            # `restore` y no por asignacion directa para que respete el techo y
            # la deuda, como cualquier otra ganancia.
            previo = antes[agente.spec_id]
            for eje in amplificar:
                ganado = agente.needs[eje] - previo[eje]
                if ganado > 0.0:
                    agente.restore(eje, ganado * (tramo - 1))

        _adelantar_reloj(sim, (tramo - 1) * ticks_dia)
        restantes -= tramo

    return Salto(dias, dias_simulados, factor, amplificar)


def _adelantar_reloj(sim: Simulation, ticks: int) -> None:
    """Mueve el reloj sin simular, arrastrando lo que depende de el.

    Los avistamientos y los vinculos guardan CUANDO se vieron, y caducan solos.
    Sin adelantar sus marcas con el reloj, un salto de seis meses los invalidaria
    todos de golpe: nadie recordaria un sitio y `forget_bonds` borraria la ciudad
    entera el primer tick despues del salto.
    """
    sim.state.tick += ticks
    for agente in sim.state.agents_in_order():
        for bond in agente.bonds.values():
            bond.last_seen += ticks
        agente.sightings = {
            sitio: (visto + ticks, quienes)
            for sitio, (visto, quienes) in agente.sightings.items()
        }
    # Los disparadores tambien cobran su zancada, y por la misma razon que los
    # avistamientos: dependen del reloj, y adelantarlo sin darsela los deja
    # evaluandose una vez cada `factor` dias. Con --skip 14 el mundo tendria
    # catorce veces menos imprevistos sin que nada lo dijera. Ver `_fire_triggers`.
    sim._fire_triggers(span=ticks)


def error_de_salto(sim_base: Simulation, dias: int, factor: int = 7) -> dict[NeedId, float]:
    """Cuanto miente el salto. Desviacion de la MEDIA POBLACIONAL, eje por eje.

    Se compara la media y no agente por agente, y la distincion importa: dos
    mundos sanos pueden tener a la misma persona en distinto punto de su ciclo de
    sueno sin que ninguno este mal. Lo que dice si el salto sirve es si la
    POBLACION quedo donde habria quedado.

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
        media_salto = sum(a.needs[need.id] for a in saltado.state.agents_in_order()) / poblacion
        salida[need.id] = abs(media_real - media_salto)
    return salida
