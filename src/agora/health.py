"""Salud de un mundo: mide un pack y comprueba lo que él mismo promete.

Sirve a dos cosas a la vez, y es deliberado:

- **Calibrando**, da el panel de números sobre el que decidir qué mover.
- **En la batería de tests**, verifica que un pack sigue cumpliendo su
  contrato. Sin esto, un cambio en un YAML puede romper una propiedad que
  dábamos por buena y nadie se entera hasta leer un log entero.

Vive por encima de `engine/` porque usa el motor y la deliberación a la vez.

Las bandas no están aquí: las declara cada pack en su sección `health`. Un test
con los umbrales clavados pelearía contra la calibración —cambiar un decay lo
rompería aunque el cambio fuera bueno— y además una aldea acomodada y un mundo
al borde del colapso no tienen por qué querer lo mismo.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations

from agora.agents.decide import critical_needs
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.state import Ledger
from agora.engine.world import Simulation


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Lo medido. Todo son medias sobre las semillas del contrato."""

    days: int
    seeds: tuple[int, ...]
    agents: int

    crisis_time: float
    """Fracción del tiempo con al menos una necesidad bajo el umbral propio."""

    simultaneous_critical: float
    abort_ratio: float
    transit_time: float
    differentiation: float
    """Distancia L1 media entre los perfiles de actividad de cada par."""

    geography: float = 0.0
    """Lo mismo, pero sobre **dónde pasa el tiempo cada quién**.

    Mide una pregunta que `differentiation` no puede: dos habitantes que hacen
    exactamente lo mismo en sitios distintos salen idénticos en actividad y
    distintos aquí. Sin este número, un mapa que no decide nada es invisible —
    veinticinco lugares que se usan igual son veinticinco copias del mismo sitio,
    y el mismo diagnóstico que destapó el vínculo muerto se aplica tal cual.

    Se muestrea la **ocupación por tick**, no los eventos. Quien duerme ocho
    horas en un sitio y hace cinco recados fuera está, sobre todo, en su cama;
    contar eventos diría lo contrario.
    """

    muertes: int = 0
    """Cuánta gente no llegó al final, sumando semillas.

    Existe porque sin este número **el resto del panel miente en silencio** en
    cuanto un pack declara algo letal. La diferenciación, la geografía y el
    tiempo en tránsito se calculan sobre quien vive; si la mitad del mundo se
    muere el tercer día, los números salen preciosos y describen a los seis
    supervivientes.

    Con muertes, un panel sano deja de significar lo mismo. Léase siempre este
    primero.
    """

    completed: int = 0
    aborted: int = 0
    stalls: int = 0
    unused: frozenset[ActionId] = field(default_factory=frozenset)

    eventful_time: float = 0.0
    """Fracción del tiempo con al menos una situación **eventual** encendida.

    Las periódicas no cuentan: son función del reloj, así que preguntarlo sería
    preguntar si amanece. Lo que este número mide es si al mundo le **pasa** algo
    que no estuviera en el calendario.

    Hoy vale 0.0 en los cuatro packs, y no es un fallo de medición: nada llama a
    `begin_situation`. Es la línea base contra la que se calibrarán los
    disparadores de la raíz 3.
    """

    never_happened: frozenset[SituationId] = field(default_factory=frozenset)
    """Situaciones eventuales que el pack declara y que no ocurrieron nunca.

    Tercer miembro de la misma familia que `unused` y `deserted`, y el mismo
    defecto: la ciudad escribe `contrato_del_gremio` a 2.2 durante la oleada y
    `velar_el_fuego` a 2.0 durante la ventisca, y ninguna de las dos situaciones
    ha ocurrido jamás. Once acciones llevan multiplicadores para situaciones que
    no pasan.

    Tampoco entra en el contrato, por lo mismo que `deserted`: mientras no haya
    disparadores, que una eventual no ocurra es lo esperado, no un defecto.
    """

    deserted: frozenset[PlaceId] = field(default_factory=frozenset)
    """Lugares donde no estuvo nadie ni un tick. El gemelo geográfico de
    `unused`, y el mismo defecto: lo que el pack escribió alrededor de ese sitio
    —sus affordances, sus horarios, sus vecinos— es decorado.

    No entra en el contrato. Un lugar puede estar legítimamente desierto porque
    es solo un cruce de caminos, y exigir lo contrario obligaría a declarar
    excepciones en los cuatro packs por un instrumento que acaba de nacer. Se
    informa; decidir si molesta es de quien calibra.
    """

    out_of_bounds: tuple[str, ...] = ()

    supply: dict[NeedId, float] = field(default_factory=dict)
    """Oferta/demanda de cada eje: cuánto se repuso frente a cuánto decayó.

    **La medida que faltaba, y la que habría cantado el problema del vínculo el
    primer día.** `crisis_time` es un agregado: un eje que nunca aprieta se
    esconde detrás de los que sí, y el panel se ve sano mientras media docena de
    mecanismos están muertos.

    Se lee como un ratio. 1.0 es un eje al filo. Por encima de ~1.3 el eje está
    resuelto y **no está decidiendo nada**: lo que el pack escribió alrededor de
    él —las acciones que lo satisfacen, los rasgos que lo pesan— es decorado.

    Un eje de progresión no tiene demanda y sale como infinito; se marca aparte
    en vez de ensuciar la columna con un número sin sentido.
    """

    lonely: dict[NeedId, float] = field(default_factory=dict)
    """Qué fracción de la oferta de cada eje llega **sin cumplir la condición
    que el pack dice que importa**: el alivio pasivo por estar en la sala, más
    los efectos base de acciones sociales que no exigen a nadie.

    Es la columna que dice DÓNDE cortar. Un eje con oferta alta y `de gorra`
    alto no se arregla encareciéndolo: mientras la oferta sea incondicional,
    subir el precio solo hace que la gente se quede quieta en la multitud que
    ya tiene."""

    def lines(self) -> list[str]:
        """Panel legible. Es lo que se mira mientras se calibra."""
        salida = [
            f"  {self.days} días · {self.agents} agentes · semillas {list(self.seeds)}",
            "",
            # Primero, y por eso rompe el orden del resto: si hay muertes, todo
            # lo de abajo describe a los supervivientes.
            f"  muertes                 {self.muertes:6}"
            + ("   <-- el resto del panel es de quien queda" if self.muertes else ""),
            f"  tiempo en crisis        {self.crisis_time:6.1%}",
            f"  críticas simultáneas    {self.simultaneous_critical:6.2f}",
            f"  abandonos/completadas   {self.aborted:5}/{self.completed:<6}"
            f" {self.abort_ratio:.1%}",
            f"  tiempo en tránsito      {self.transit_time:6.1%}",
            f"  diferenciación          {self.differentiation:6.3f}",
            f"  difer. geográfica       {self.geography:6.3f}",
            f"  bloqueos                {self.stalls:6}",
            f"  acciones sin usar       {sorted(self.unused) if self.unused else '—'}",
            f"  lugares desiertos       {sorted(self.deserted) if self.deserted else '—'}",
            f"  tiempo con imprevisto   {self.eventful_time:6.1%}",
            f"  nunca pasan             "
            f"{sorted(self.never_happened) if self.never_happened else '—'}",
        ]
        if self.supply:
            salida += ["", "  oferta/demanda por eje   (>1.3 = el eje no decide nada)"]
            for need, ratio in sorted(self.supply.items(), key=lambda kv: -kv[1]):
                pasivo = self.lonely.get(need, 0.0)
                nota = f"   de gorra {pasivo:.0%}" if pasivo > 0.0 else ""
                marca = "  <-- muerto" if ratio > 1.3 else ""
                salida.append(f"    {need!s:<14} {ratio:6.2f}{nota}{marca}")
        return salida


def measure(pack: ContentPack, days: int | None = None, seeds: tuple[int, ...] | None = None
            ) -> HealthReport:
    """Corre el mundo y devuelve sus números.

    El umbral de crisis es el de cada agente, no el del mundo: quien aguanta
    más tarda más en considerar que algo es una emergencia, y medirlo con una
    vara común daría un número que no le pasa a nadie.
    """
    spec = pack.health
    days = days if days is not None else spec.days
    seeds = seeds if seeds is not None else spec.seeds
    ticks = days * pack.clock.ticks_per_day
    population = len(pack.agents)

    crisis = 0
    critical_count = 0
    samples = 0
    completed = 0
    aborted = 0
    stalls = 0
    transit = 0
    used: set[ActionId] = set()
    profiles: dict[AgentId, Counter[ActionId]] = {a.id: Counter() for a in pack.agents}
    where: dict[AgentId, Counter[PlaceId]] = {a.id: Counter() for a in pack.agents}
    out_of_bounds: list[str] = []
    muertes = 0
    eventful = 0
    ocurridas: set[SituationId] = set()

    libros: list[Ledger] = []
    for seed in seeds:
        sim = Simulation(pack, seed=seed)
        # Se enciende la contabilidad. Solo aqui: una corrida de juego no paga
        # por instrumentarse, y una de calibracion tiene que poder responder si
        # un eje decide algo o es decorado.
        for agent in sim.state.agents_in_order():
            agent.ledger = Ledger()
        for _ in range(ticks):
            sim.tick()
            # `state.situations` guarda SOLO las eventuales: las periódicas se
            # calculan del reloj y no viven ahí. Así que preguntar si está vacío
            # es exactamente preguntar si al mundo le está pasando algo que no
            # tocaba por calendario.
            if sim.state.situations:
                eventful += 1
                ocurridas.update(sim.state.situations)
            for agent in sim.state.agents_in_order():
                urgent = critical_needs(sim.state, agent)
                critical_count += len(urgent)
                samples += 1
                if urgent:
                    crisis += 1
                # Dónde está, muestreado por tick. Va aquí y no en `Recuento`
                # porque la ocupación no se emite: es estado, no suceso. Quien
                # duerme ocho horas en un sitio y hace cinco recados fuera está
                # sobre todo en su cama, y contar eventos diría lo contrario.
                #
                # El bucle ya recorre a todos los agentes cada tick para el
                # triaje, así que esto no añade recorrido — solo un contador.
                where[agent.spec_id][agent.at] += 1

        # Del recuento y no de los eventos: son los totales de la corrida entera
        # aunque el log conserve solo una ventana. Recorrer dos millones de
        # eventos para sacar treinta números tampoco tenía defensa.
        recuento = sim.log.recuento
        completed += recuento.por_tipo[EventKind.ACTION_COMPLETED]
        aborted += recuento.por_tipo[EventKind.ACTION_ABORTED]
        stalls += recuento.por_tipo[EventKind.IDLE_STALLED]
        transit += recuento.ticks_de_viaje
        for actor, acciones in recuento.por_agente_accion.items():
            profiles[actor].update(acciones)
            used.update(acciones)

        muertes += population - len(sim.state.agents)
        for agent in sim.state.agents_in_order():
            for need, value in agent.needs.items():
                if not 0.0 <= value <= 1.0:
                    out_of_bounds.append(f"{agent.spec_id}.{need} = {value}")
            if agent.ledger is not None:
                libros.append(agent.ledger)

    return HealthReport(
        days=days,
        seeds=tuple(seeds),
        agents=population,
        crisis_time=crisis / max(samples, 1),
        simultaneous_critical=critical_count / max(samples, 1),
        abort_ratio=aborted / max(completed, 1),
        # `samples` y no `ticks * population * len(seeds)`: son los tick-agente
        # que de verdad ocurrieron. Con muertes, el producto cuenta los turnos de
        # quien ya no está y el tránsito sale rebajado sin que nada lo diga.
        transit_time=transit / max(samples, 1),
        muertes=muertes,
        differentiation=_differentiation(profiles),
        geography=_differentiation(where),
        completed=completed,
        aborted=aborted,
        stalls=stalls,
        unused=frozenset(a.id for a in pack.actions) - used,
        deserted=frozenset(p.id for p in pack.places)
        - {sitio for visitados in where.values() for sitio in visitados},
        eventful_time=eventful / max(ticks * len(seeds), 1),
        never_happened=frozenset(s.id for s in pack.situations if not s.periodic)
        - ocurridas,
        out_of_bounds=tuple(out_of_bounds),
        **_supply_and_demand(pack, libros),
    )


def _supply_and_demand(
    pack: ContentPack, libros: list[Ledger]
) -> dict[str, dict[NeedId, float]]:
    """Oferta frente a demanda, eje por eje.

    Un eje de progresion no tiene demanda —solo sube— asi que dividir daria
    infinito. Se omite en vez de ensuciar la columna con un numero sin sentido:
    la pregunta "decide algo?" no aplica a un eje que nadie puede perder.
    """
    demanda: dict[NeedId, float] = {}
    pasivo: dict[NeedId, float] = {}
    activo: dict[NeedId, float] = {}
    gratis: dict[NeedId, float] = {}
    for libro in libros:
        for destino, origen in ((demanda, libro.demanda), (pasivo, libro.pasivo),
                                (activo, libro.activo), (gratis, libro.incondicional)):
            for need, cuanto in origen.items():
                destino[need] = destino.get(need, 0.0) + cuanto

    supply: dict[NeedId, float] = {}
    lonely: dict[NeedId, float] = {}
    for spec in pack.needs:
        if spec.progression:
            continue
        pide = demanda.get(spec.id, 0.0)
        if pide <= 0.0:
            continue
        da = pasivo.get(spec.id, 0.0) + activo.get(spec.id, 0.0)
        supply[spec.id] = da / pide
        if da > 0.0:
            sin_condicion = pasivo.get(spec.id, 0.0) + gratis.get(spec.id, 0.0)
            lonely[spec.id] = sin_condicion / da
    return {"supply": supply, "lonely": lonely}


def _differentiation[K: (ActionId, PlaceId)](
    profiles: Mapping[AgentId, Counter[K]],
) -> float:
    """Distancia L1 media entre los perfiles de cada par. 0 = todos iguales.

    Genérica en la clave a propósito, y **acotada a dos**: acciones y lugares.
    Nació midiendo qué hace cada quién y sirve igual para medir dónde está —es
    la misma pregunta, *¿os distingue esto?*, sobre otro eje—. Dos varas
    distintas para lo mismo divergirían, y comparar los dos números dejaría de
    significar nada.

    Acotada y no libre porque son las dos preguntas que el panel sabe
    interpretar. Una tercera clave necesitaría su propia lectura, no solo su
    propio número.

    El techo teórico es 2 —no comparten ni una entrada— pero el real está mucho
    más abajo en ambos ejes: dormir y comer son obligatorios para todos, y todo
    el mundo pasa la noche en su cama.
    """
    vectors: list[dict[K, float]] = []
    for counts in profiles.values():
        total = sum(counts.values())
        # Un perfil VACÍO no es una biografía distinta, es una biografía que no
        # existe — y como vector es máximamente distinto de todos, así que quien
        # muriera antes de hacer nada subiría la cifra por no haber vivido. Sin
        # esta línea, matar gente mejora la diferenciación.
        if not total:
            continue
        vectors.append({k: v / total for k, v in counts.items()})

    pairs = [
        sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))
        for a, b in combinations(vectors, 2)
    ]
    return sum(pairs) / len(pairs) if pairs else 0.0


# -----------------------------------------------------------------------------
# Divergencia entre semillas
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DivergenceReport:
    """Cuánto cambia la vida de la MISMA persona entre dos corridas del MISMO
    mundo. El eje sobre el que se calibrará la raíz 3.

    El peligro que los disparadores traen está escrito en el plan: *si se les da
    demasiada cuerda, el mundo pasa de vivo a aleatorio, y eso destruye la
    legibilidad*. Vivo y aleatorio no son puntos, son un eje, y hasta ahora nada
    lo medía.

    Se lee así:

    - **Cerca de 0** — el mundo está guionizado. Cambiar la semilla no cambia
      nada, así que nada de lo que pasa era evitable ni sorprendente.
    - **Alto** — el mundo es ruido. La misma persona vive dos vidas ajenas según
      un número que nadie ve, y ninguna conducta se puede explicar.

    Dónde está el punto bueno no lo dice esta clase: lo dirá calibrar. Lo que
    esta clase da es el número, que antes no existía.
    """

    seeds: tuple[int, ...]
    days: int

    lives: float
    """Distancia L1 media entre el perfil de actividad del mismo agente bajo dos
    semillas distintas, promediada sobre todos los agentes y todos los pares.

    **La misma vara que `differentiation`**, girada noventa grados: aquella
    compara a dos personas dentro de una corrida, esta compara a una persona
    consigo misma entre corridas. Que sea la misma función es lo que permite
    leer los dos números juntos — si la divergencia entre semillas se acerca a
    la diferenciación entre personas, el azar pesa tanto como el carácter.
    """

    differentiation: float = 0.0
    """La diferenciación entre personas, promediada sobre las semillas. Sale
    gratis de los mismos perfiles que ya hay que recoger, y sin ella el número de
    arriba no se puede leer: 0.388 es mucho o poco según contra qué."""

    eventful_time: float = 0.0
    """Fracción de ticks con alguna situación eventual, promediada. Duplica el
    campo del panel a propósito: aquí se mira mientras se gira la perilla de los
    disparadores, y tener que cruzar dos informes para eso sería absurdo."""

    @property
    def ratio(self) -> float:
        """**El número que hay que mirar.** Divergencia entre corridas dividida
        por diferenciación entre personas.

        Se lee como *cuánto de lo que distingue a dos habitantes podría
        explicarlo la moneda en vez de quiénes son*:

        - **cerca de 0** — el carácter manda; el azar apenas roza la vida.
        - **cerca de 1** — la moneda pesa tanto como la persona, y ninguna
          conducta se puede explicar señalando a un rasgo.

        Medido antes de que existieran los disparadores, 7 días, tres semillas:
        aldea 0.29, barrio 0.39, ciudad 0.41 — el carácter manda por dos y medio
        a tres y medio. `dark_fantasy` sale 0.80, y es coherente con lo demás que
        sabemos de ese pack: lo poco que distingue a sus dos agentes es casi todo
        ruido.

        Si al encender los disparadores esto sube hacia 1, el mundo se volvió
        aleatorio. Es el freno cuantitativo que el plan pedía y no tenía.
        """
        return self.lives / self.differentiation if self.differentiation else 0.0

    def lines(self) -> list[str]:
        return [
            f"  {self.days} días · semillas {list(self.seeds)}",
            "",
            f"  divergencia entre vidas {self.lives:6.3f}",
            f"  diferenciación          {self.differentiation:6.3f}",
            f"  azar frente a carácter  {self.ratio:6.2f}   (→1 = mundo aleatorio)",
            f"  tiempo con imprevisto   {self.eventful_time:6.1%}",
        ]


def divergence(
    pack: ContentPack, seeds: tuple[int, ...], days: int | None = None
) -> DivergenceReport:
    """Corre el mismo mundo con varias semillas y mide cuánto difieren las vidas.

    **No usa `measure`, y no es duplicación.** `measure` promedia las semillas —
    justo lo que aquí se quiere conservar— y además enciende la contabilidad de
    los libros y muestrea el triaje en cada tick, que aquí no hacen falta. Correr
    lo mínimo sale más barato que llamar a `measure` una vez por semilla y tirar
    lo que sobra.

    Tampoco entra en el contrato de ningún pack. La ciudad declara **una** sola
    semilla, y por una razón escrita: tres costarían dos minutos por cada
    `--health`. Esto es una herramienta de calibración que se invoca a propósito,
    con las semillas que haga falta, no un número que se paga en cada corrida.
    """
    if len(seeds) < 2:
        raise ValueError(
            f"la divergencia compara corridas entre sí y se pidieron {len(seeds)} "
            f"semillas. Con una no hay con qué comparar."
        )
    days = days if days is not None else pack.health.days
    ticks = days * pack.clock.ticks_per_day

    por_semilla: list[dict[AgentId, Counter[ActionId]]] = []
    eventful = 0
    for seed in seeds:
        sim = Simulation(pack, seed=seed)
        for _ in range(ticks):
            sim.tick()
            if sim.state.situations:
                eventful += 1
        por_semilla.append(
            {a.id: Counter(sim.log.recuento.por_agente_accion.get(a.id, Counter()))
             for a in pack.agents}
        )

    # Un agente contra sí mismo, semilla contra semilla. Se reusa la misma
    # función que mide la diferenciación entre personas: si fueran dos varas,
    # los dos números no se podrían comparar y la lectura interesante —¿pesa más
    # el azar o el carácter?— dejaría de existir.
    distancias = [
        _differentiation({AgentId("uno"): una[agente], AgentId("otro"): otra[agente]})
        for una, otra in combinations(por_semilla, 2)
        for agente in una
    ]
    return DivergenceReport(
        seeds=seeds,
        days=days,
        lives=sum(distancias) / len(distancias) if distancias else 0.0,
        # De los mismos perfiles, sin correr nada más: es lo que hace legible al
        # número de arriba.
        differentiation=sum(_differentiation(p) for p in por_semilla) / len(por_semilla),
        eventful_time=eventful / max(ticks * len(seeds), 1),
    )


def check(pack: ContentPack, report: HealthReport | None = None) -> list[str]:
    """Contrasta lo medido con lo que el pack promete. Vacío = todo en orden.

    Los tres primeros son **invariantes universales**: no dependen de lo que el
    pack declare, porque un mundo donde alguien se queda sin opciones o donde
    un valor se sale de rango está roto se proponga lo que se proponga.
    """
    report = report if report is not None else measure(pack)
    spec = pack.health
    problems: list[str] = []

    if report.stalls:
        problems.append(
            f"{report.stalls} bloqueos: algún agente se quedó sin ninguna opción válida"
        )
    if report.out_of_bounds:
        problems.append(f"valores fuera de [0,1]: {report.out_of_bounds[:3]}")
    if report.completed == 0:
        problems.append("nadie completó ninguna acción en toda la corrida")
    if spec.max_muertes is not None and report.muertes > spec.max_muertes:
        problems.append(
            f"{report.muertes} muertes por encima del máximo {spec.max_muertes}: "
            f"lo de abajo describe a quien queda, no al mundo que se escribió"
        )

    if spec.min_crisis is not None and report.crisis_time < spec.min_crisis:
        problems.append(
            f"tiempo en crisis {report.crisis_time:.1%} por debajo del mínimo "
            f"{spec.min_crisis:.1%}: sin presión, el carácter deja de notarse"
        )
    if spec.max_crisis is not None and report.crisis_time > spec.max_crisis:
        problems.append(
            f"tiempo en crisis {report.crisis_time:.1%} por encima del máximo "
            f"{spec.max_crisis:.1%}: la emergencia aplasta al carácter"
        )
    if spec.max_abort_ratio is not None and report.abort_ratio > spec.max_abort_ratio:
        problems.append(
            f"abandonos {report.abort_ratio:.1%} por encima del máximo "
            f"{spec.max_abort_ratio:.1%}"
        )
    if spec.max_transit is not None and report.transit_time > spec.max_transit:
        problems.append(
            f"tránsito {report.transit_time:.1%} por encima del máximo "
            f"{spec.max_transit:.1%}"
        )
    if spec.min_differentiation is not None and report.differentiation < spec.min_differentiation:
        problems.append(
            f"diferenciación {report.differentiation:.3f} por debajo del mínimo "
            f"{spec.min_differentiation:.3f}: las vidas están colapsando entre sí"
        )

    huerfanas = report.unused - spec.may_go_unused
    if huerfanas:
        problems.append(
            f"acciones declaradas que nunca ocurren: {sorted(huerfanas)}. "
            f"Si es intencional, decláralas en `health.may_go_unused`"
        )

    return problems
