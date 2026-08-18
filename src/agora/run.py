"""Punto de entrada: corre una simulación y escupe el log.

    uv run agora
    uv run agora --days 3 --seed 99
    uv run agora --jsonl corrida.jsonl
    uv run agora --days 180 --save ano1.json
    uv run agora --load ano1.json --days 180 --save ano2.json
    uv run agora --days 1800 --skip 7 --quiet --save graduados.json
    uv run agora --days 1800 --skip 14 --window 7 --jsonl cinco-anos.jsonl

Sin UI y sin colores a propósito. En F0 la única forma de saber si el mundo
funciona es leer texto y comparar corridas con `diff`.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from agora.engine.pack import ContentPack, describe_pack, load_pack
from agora.engine.render import render_activity_summary, render_log, render_state
from agora.engine.timeskip import saltar
from agora.engine.world import Simulation
from agora.health import check, divergence, measure

if TYPE_CHECKING:
    from typing import TextIO

DEFAULT_PACK = Path("packs/barrio/pack.yaml")
"""El mundo de trabajo. `dark_fantasy` existe para probar el agnosticismo del
motor, no para jugarse, así que hay que pedirlo explícitamente."""


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador social Agora")
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--seed", type=int, default=1312)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=None,
        help="vierte el log crudo segun ocurre, para comparar dos corridas byte "
        "a byte. Se escribe en streaming: no se retiene nada para escribirlo",
    )
    parser.add_argument("--quiet", action="store_true", help="solo el resumen")
    parser.add_argument(
        "--load", type=Path, default=None,
        help="reanuda una partida guardada en vez de empezar en el tick cero",
    )
    parser.add_argument(
        "--skip", type=int, default=1, metavar="N",
        help="salto temporal: simula un dia de cada N y da la zancada a los ejes "
        "de progresion. 1 = sin atajo",
    )
    parser.add_argument(
        "--window", type=int, default=0, metavar="DIAS",
        help="el log conserva solo los ultimos DIAS y descarta lo viejo. "
        "0 = sin limite. Combinado con --jsonl no se pierde nada: la historia "
        "entera va al fichero y la memoria queda acotada",
    )
    parser.add_argument(
        "--save", type=Path, default=None,
        help="guarda el estado al terminar, para seguir desde ahi",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="mide la salud del mundo sobre varias semillas y contrasta el "
        "contrato que el pack declara; no corre la simulación normal",
    )
    parser.add_argument(
        "--divergence",
        type=int,
        default=0,
        metavar="N",
        help="corre el mundo con N semillas y mide cuánto difiere la vida de la "
        "MISMA persona entre corridas. Es el eje vivo/aleatorio: si el azar "
        "empieza a pesar tanto como el carácter, ninguna conducta se explica. "
        "No corre la simulación normal",
    )
    args = parser.parse_args()

    pack = load_pack(args.pack)

    if args.health:
        _report_health(pack)
        return
    if args.divergence:
        _report_divergence(pack, args.divergence, args.seed, args.days)
        return
    ventana = args.window * pack.clock.ticks_per_day if args.window > 0 else None
    # El fichero se abre ANTES de correr y se cierra después: el log se vierte
    # según ocurre. Volcarlo al final obligaría a retenerlo entero para escribirlo,
    # que es justo lo que la ventana viene a evitar.
    with ExitStack() as stack:
        sink = (
            stack.enter_context(args.jsonl.open("w", encoding="utf-8"))
            if args.jsonl is not None
            else None
        )
        _correr(args, pack, ventana, sink)


def _correr(
    args: argparse.Namespace,
    pack: ContentPack,
    ventana: int | None,
    sink: TextIO | None,
) -> None:
    if args.load is not None:
        sim = Simulation.resume(args.load, pack, log_window=ventana, log_sink=sink)
        print(f"# reanudado desde {args.load}  (tick {sim.state.tick})")
    else:
        sim = Simulation(pack, seed=args.seed, log_window=ventana, log_sink=sink)
    ticks = args.days * pack.clock.ticks_per_day

    print(f"# pack   {pack.label}  {dict(describe_pack(pack))}")
    print(f"# seed   {args.seed}")
    print(f"# corrida {args.days} días = {ticks} ticks")
    print()
    for line in render_state(sim.state):
        print(line)
    print()

    if args.skip > 1:
        salto = saltar(sim, args.days, args.skip)
        print(f"# salto x{salto.factor}: {salto.dias_simulados} dias simulados "
              f"de {salto.dias_pedidos}  ({salto.ahorro:.1f}x)")
    else:
        sim.run(ticks)

    if not args.quiet:
        for line in render_log(pack, sim.log):
            print(line)
        print()

    for line in render_state(sim.state):
        print(line)
    print()
    for line in render_activity_summary(pack, sim.log):
        print(line)
    # Si la ventana descarto algo hay que decirlo: un log recortado en silencio
    # se lee igual que uno completo, y no lo es.
    if sim.log.desalojados:
        print(f"\n# {sim.log.emitidos} eventos  ({len(sim.log)} en ventana, "
              f"{sim.log.desalojados} descartados)")
    else:
        print(f"\n# {len(sim.log)} eventos")

    if args.save is not None:
        sim.save(args.save)
        print(f"# partida -> {args.save}  (tick {sim.state.tick})")

    if args.jsonl is not None:
        print(f"# log crudo -> {args.jsonl}  ({sim.log.emitidos} lineas)")


def _report_health(pack: ContentPack) -> None:
    """Panel de calibración: los números y si el pack cumple lo que promete."""
    report = measure(pack)
    print(f"# salud de {pack.label}")
    print()
    for line in report.lines():
        print(line)
    print()

    problems = check(pack, report)
    if not problems:
        print("  contrato: CUMPLE")
        return
    print("  contrato: INCUMPLE")
    for problem in problems:
        print(f"    - {problem}")


def _report_divergence(pack: ContentPack, cuantas: int, seed: int, days: int) -> None:
    """Cuánto cambia la misma vida al cambiar la moneda.

    Las semillas salen de `seed` y las siguientes consecutivas, no de un sorteo:
    dos invocaciones iguales tienen que dar el mismo número, o el instrumento no
    sirve para comparar antes y después de girar una perilla.
    """
    if cuantas < 2:
        print("  --divergence necesita al menos 2 semillas: compara corridas entre sí")
        return
    report = divergence(pack, seeds=tuple(seed + i for i in range(cuantas)), days=days)
    print(f"# divergencia de {pack.label}")
    print()
    for line in report.lines():
        print(line)


if __name__ == "__main__":
    main()
