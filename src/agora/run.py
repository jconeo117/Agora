"""Punto de entrada: corre una simulación y escupe el log.

    uv run agora
    uv run agora --days 3 --seed 99
    uv run agora --jsonl corrida.jsonl

Sin UI y sin colores a propósito. En F0 la única forma de saber si el mundo
funciona es leer texto y comparar corridas con `diff`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from agora.engine.pack import describe_pack, load_pack
from agora.engine.render import render_activity_summary, render_log, render_state
from agora.engine.world import Simulation

DEFAULT_PACK = Path("packs/dark_fantasy/pack.yaml")


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
    args = parser.parse_args()

    pack = load_pack(args.pack)
    sim = Simulation(pack, seed=args.seed)
    ticks = args.days * pack.clock.ticks_per_day

    print(f"# pack   {pack.label}  {dict(describe_pack(pack))}")
    print(f"# seed   {args.seed}")
    print(f"# corrida {args.days} días = {ticks} ticks")
    print()
    for line in render_state(sim.state):
        print(line)
    print()

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

    if args.jsonl is not None:
        args.jsonl.write_text("\n".join(sim.log.to_jsonl()) + "\n", encoding="utf-8")
        print(f"# log crudo -> {args.jsonl}")


if __name__ == "__main__":
    main()
