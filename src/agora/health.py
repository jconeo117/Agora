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
from dataclasses import dataclass, field
from itertools import combinations

from agora.agents.decide import critical_needs
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, NeedId
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

    completed: int
    aborted: int
    stalls: int
    unused: frozenset[ActionId] = field(default_factory=frozenset)
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
    """Qué fracción de la oferta de cada eje llega SIN hacer nada, por
    `company_relief`. Alto significa que la necesidad se cubre por estar en la
    sala, y entonces ninguna acción social decide nada."""

    def lines(self) -> list[str]:
        """Panel legible. Es lo que se mira mientras se calibra."""
        salida = [
            f"  {self.days} días · {self.agents} agentes · semillas {list(self.seeds)}",
            "",
            f"  tiempo en crisis        {self.crisis_time:6.1%}",
            f"  críticas simultáneas    {self.simultaneous_critical:6.2f}",
            f"  abandonos/completadas   {self.aborted:5}/{self.completed:<6}"
            f" {self.abort_ratio:.1%}",
            f"  tiempo en tránsito      {self.transit_time:6.1%}",
            f"  diferenciación          {self.differentiation:6.3f}",
            f"  bloqueos                {self.stalls:6}",
            f"  acciones sin usar       {sorted(self.unused) if self.unused else '—'}",
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
    out_of_bounds: list[str] = []

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
            for agent in sim.state.agents_in_order():
                urgent = critical_needs(sim.state, agent)
                critical_count += len(urgent)
                samples += 1
                if urgent:
                    crisis += 1

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
        transit_time=transit / max(ticks * population * len(seeds), 1),
        differentiation=_differentiation(profiles),
        completed=completed,
        aborted=aborted,
        stalls=stalls,
        unused=frozenset(a.id for a in pack.actions) - used,
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
    for libro in libros:
        for destino, origen in ((demanda, libro.demanda), (pasivo, libro.pasivo),
                                (activo, libro.activo)):
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
            lonely[spec.id] = pasivo.get(spec.id, 0.0) / da
    return {"supply": supply, "lonely": lonely}


def _differentiation(profiles: dict[AgentId, Counter[ActionId]]) -> float:
    """Distancia L1 media entre los perfiles de actividad de cada par.

    0 = todos viven igual. 2 = no comparten ni una actividad. En la práctica el
    techo real está mucho más abajo, porque dormir y comer son obligatorios
    para todos y ocupan la mayor parte del día.
    """
    vectors: list[dict[ActionId, float]] = []
    for counts in profiles.values():
        total = sum(counts.values()) or 1
        vectors.append({k: v / total for k, v in counts.items()})

    pairs = [
        sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))
        for a, b in combinations(vectors, 2)
    ]
    return sum(pairs) / len(pairs) if pairs else 0.0


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
