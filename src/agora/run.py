"""Punto de entrada: corre una simulación y escupe el log.

    uv run agora
    uv run agora --days 3 --seed 99
    uv run agora --jsonl corrida.jsonl
    uv run agora --days 180 --save ano1.json
    uv run agora --load ano1.json --days 180 --save ano2.json
    uv run agora --days 1800 --skip 7 --quiet --save graduados.json

Sin UI y sin colores a propósito. En F0 la única forma de saber si el mundo
funciona es leer texto y comparar corridas con `diff`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agora.engine.pack import ContentPack, describe_pack, load_pack
from agora.engine.render import render_activity_summary, render_log, render_state
from agora.engine.timeskip import saltar
from agora.engine.world import Simulation
from agora.health import check, measure

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
        help="vuelca el log crudo, para comparar dos corridas byte a byte",
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
        "--save", type=Path, default=None,
        help="guarda el estado al terminar, para seguir desde ahi",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="mide la salud del mundo sobre varias semillas y contrasta el "
        "contrato que el pack declara; no corre la simulación normal",
    )
    args = parser.parse_args()

    pack = load_pack(args.pack)

    if args.health:
        _report_health(pack)
        return
    if args.load is not None:
        sim = Simulation.resume(args.load, pack)
        print(f"# reanudado desde {args.load}  (tick {sim.state.tick})")
    else:
        sim = Simulation(pack, seed=args.seed)
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
    print(f"\n# {len(sim.log)} eventos")

    if args.save is not None:
        sim.save(args.save)
        print(f"# partida -> {args.save}  (tick {sim.state.tick})")

    if args.jsonl is not None:
        args.jsonl.write_text("\n".join(sim.log.to_jsonl()) + "\n", encoding="utf-8")
        print(f"# log crudo -> {args.jsonl}")


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


if __name__ == "__main__":
    main()
