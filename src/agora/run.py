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
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from agora.cognition.ollama import OllamaProvider
from agora.cognition.voz import hablar
from agora.engine.consulta import ficha
from agora.engine.lod import error_de_lod
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import AgentId
from agora.engine.pack import ContentPack, describe_pack, load_pack
from agora.engine.render import render_activity_summary, render_log, render_state
from agora.engine.timeskip import saltar
from agora.engine.world import Simulation
from agora.health import check, divergence, measure
from agora.play import (
    CombatRecorder,
    Recorder,
    Script,
    ScriptCombat,
    Terminal,
    TerminalCombat,
    play,
)
from agora.rules.binding import BindingSpec, load_binding
from agora.rules.derive import census, derive, duel
from agora.rules.encounter import Policy
from agora.rules.montecarlo import pool_table
from agora.rules.pool import PoolResolver
from agora.rules.scene import load_scenario
from agora.rules.simulator import account, check_calibration, fight, simulate
from agora.rules.system import Ruleset, load_ruleset
from agora.rules.world_combat import WorldCombat

if TYPE_CHECKING:
    from typing import TextIO

    from agora.engine.ports import DecisionSource

DEFAULT_PACK = Path("packs/barrio/pack.yaml")
"""El mundo de trabajo. `dark_fantasy` existe para probar el agnosticismo del
motor, no para jugarse, así que hay que pedirlo explícitamente."""

DEFAULT_RULES = Path("rules/base/rules.yaml")
"""El sistema de rol de la mesa (D-153). Hoy hay uno: el borrador 1."""


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
    parser.add_argument(
        "--foco", default=None, metavar="AGENTE",
        help="simula fino alrededor de este agente (D-152). Sin lod_focus_radius "
        "en el tuning del pack, no cambia nada",
    )
    parser.add_argument(
        "--error-lod", action="store_true",
        help="con --foco: corre --days entero y con LOD desde el mismo arranque y "
        "dice cuánto se aparta. No corre la simulación normal",
    )
    parser.add_argument(
        "--ficha-mecanica", default=None, metavar="AGENTE",
        help="al terminar, la ficha mecánica de este agente en el sistema de --reglas, "
        "derivada de quién es (unidad 11). Con --contra, también lo que siente por él",
    )
    parser.add_argument("--contra", default=None, metavar="AGENTE",
                        help="con --ficha-mecanica o --duelo: el rival")
    parser.add_argument("--fichas", action="store_true",
                        help="al terminar, cómo se reparten las fichas de todos los vivos")
    parser.add_argument(
        "--duelo", default=None, metavar="AGENTE",
        help="al terminar, enfrenta a este agente con --contra en el simulador, "
        "--combates veces (100 si no se dice)",
    )
    parser.add_argument(
        "--consultar", default=None, metavar="AGENTE",
        help="al terminar, la ficha de este agente: lo que se puede saber de él "
        "ahora mismo. No usa ningún modelo",
    )
    parser.add_argument(
        "--hablar", default=None, metavar="AGENTE",
        help="al terminar, este agente contesta a «qué tal te va». Con un LLM "
        "local (Ollama) si responde; si no, con las frases del pack",
    )
    parser.add_argument("--con", default=None, metavar="AGENTE",
                        help="con --hablar: quién le habla. Sin esto, un desconocido")
    parser.add_argument("--sin-llm", action="store_true",
                        help="con --hablar: no llamar al modelo, solo el respaldo")
    parser.add_argument(
        "--jugar", default=None, metavar="AGENTE",
        help="juegas tú con este agente: el mundo se para cuando queda ocioso y "
        "eliges entre lo que él podría hacer. Es también el foco",
    )
    parser.add_argument(
        "--jugar-ficha", type=Path, default=None, metavar="F",
        help="juegas con un forastero nuevo, descrito en esta ficha; lo que no "
        "diga lo pone la sección newcomer del pack",
    )
    parser.add_argument("--guion", type=Path, default=None, metavar="F",
                        help="las decisiones del jugador salen de este archivo, no del teclado")
    parser.add_argument("--grabar", type=Path, default=None, metavar="F",
                        help="graba las decisiones del jugador como guion")
    parser.add_argument("--modelo", default="llama3.2:latest")
    parser.add_argument("--llm-url", default="http://localhost:11434")
    parser.add_argument(
        "--reglas", type=Path, default=DEFAULT_RULES, metavar="SISTEMA",
        help="el sistema de rol de la mesa (rules/<sistema>/rules.yaml)",
    )
    parser.add_argument(
        "--montecarlo", type=int, default=0, metavar="N",
        help="tira N veces cada reserva de 0 a 6 con el sistema de --reglas y "
        "compara lo medido con la probabilidad exacta. No corre la simulación",
    )
    parser.add_argument(
        "--combates", type=int, default=0, metavar="N",
        help="simula N encuentros de cada escenario que el sistema de --reglas "
        "promete en su calibration y dice si CUMPLE. Con --escenario, solo ese",
    )
    parser.add_argument("--escenario", type=Path, default=None, metavar="F",
                        help="con --combates: simula este escenario y da su informe")
    parser.add_argument(
        "--relato", type=int, default=None, metavar="I",
        help="con --escenario: cuenta el encuentro número I, hecho a hecho",
    )
    args = parser.parse_args()

    if args.montecarlo:
        _report_montecarlo(load_ruleset(args.reglas), args.montecarlo, args.seed)
        return
    # Con --duelo, --combates cuenta los combates del duelo, no los de la calibración.
    if (args.combates or args.relato is not None) and args.duelo is None:
        _report_combates(args)
        return

    pack = load_pack(args.pack)

    if args.health:
        _report_health(pack)
        return
    if args.divergence:
        _report_divergence(pack, args.divergence, args.seed, args.days)
        return
    if args.error_lod:
        if args.foco is None:
            parser.error("--error-lod necesita --foco")
        _report_error_lod(pack, args)
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
    if args.foco is not None:
        _fijar_foco(sim, args.foco)
    if args.jugar_ficha is not None:
        recien = newcomer_spec(pack, load_sheet(args.jugar_ficha), sim.state.censo)
        sim.arrive(recien)
        sim.set_player(recien.id)
    elif args.jugar is not None:
        sim.set_player(_vivo(sim, args.jugar, "--jugar"))
    ticks = args.days * pack.clock.ticks_per_day

    print(f"# pack   {pack.label}  {dict(describe_pack(pack))}")
    print(f"# seed   {args.seed}")
    print(f"# corrida {args.days} días = {ticks} ticks")
    print()
    for line in render_state(sim.state):
        print(line)
    print()

    if sim.state.player is not None:
        if args.skip > 1:
            raise SystemExit("--skip no se puede jugar: el salto decidiría por el jugador")
        _jugar(sim, args, ticks)
    elif args.skip > 1:
        salto = saltar(sim, args.days, args.skip)
        print(f"# salto x{salto.factor}: {salto.dias_simulados} dias simulados "
              f"de {salto.dias_pedidos}  ({salto.ahorro:.1f}x)")
    else:
        sim.run(ticks)

    if not args.quiet:
        for line in render_log(pack, sim.log, sim.state.censo):
            print(line)
        print()

    for line in render_state(sim.state):
        print(line)
    print()
    for line in render_activity_summary(pack, sim.log, sim.state.censo):
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

    if args.ficha_mecanica is not None or args.fichas or args.duelo is not None:
        _mecanica(sim, args)
    if args.consultar is not None:
        _consultar(sim, args.consultar)
    if args.hablar is not None:
        _hablar(sim, args)


def _jugar(sim: Simulation, args: argparse.Namespace, ticks: int) -> None:
    """Si la partida tiene jugador, se juega: también al reanudarla."""
    terminal: Terminal | None = None
    escena: TerminalCombat | None = None

    def ahora() -> int:
        return sim.state.tick

    if args.guion is not None:
        lineas = args.guion.read_text(encoding="utf-8").splitlines()
        fuente: DecisionSource = Script(lineas)
        combate: Policy = ScriptCombat(lineas, ahora)
    else:
        proveedor = None if args.sin_llm else OllamaProvider(url=args.llm_url, modelo=args.modelo)
        terminal = Terminal(sim, sys.stdin, sys.stdout, proveedor)
        fuente = terminal
        escena = TerminalCombat(sys.stdin, sys.stdout)
        combate = escena
    with ExitStack() as stack:
        if args.grabar is not None:
            grabacion = stack.enter_context(args.grabar.open("a", encoding="utf-8"))
            fuente = Recorder(fuente, grabacion)
            combate = CombatRecorder(combate, grabacion, ahora)
        sim.encounter_resolver = _resolutor(sim, args, combate, escena)
        resultado = play(sim, fuente, ticks, terminal)
    print(f"\n# fin de la partida: {resultado.reason}, {resultado.ticks} ticks jugados")


def _resolutor(
    sim: Simulation, args: argparse.Namespace, combate: Policy, escena: TerminalCombat | None
) -> WorldCombat | None:
    """Las peleas del jugador con las reglas de la mesa (unidad 13). Sin enlace
    entre este mundo y el sistema, se resuelven por utilidad, como antes."""
    sistema = load_ruleset(args.reglas)
    ruta = args.pack.parent / "reglas" / f"{sistema.id}.yaml"
    if not ruta.exists():
        print(f"# sin {ruta}: tus peleas se resuelven por utilidad, sin escena")
        return None
    return WorldCombat(sistema, load_binding(ruta, sim.state.pack, sistema), combate,
                       None if escena is None else escena.report)


def _fijar_foco(sim: Simulation, foco: str) -> None:
    if AgentId(foco) not in sim.state.agents:
        raise SystemExit(f"--foco: {foco!r} no está vivo en esta partida")
    sim.state.focus = AgentId(foco)
    if sim.pack.tuning.lod_focus_radius is None:
        print("# aviso: el pack no declara lod_focus_radius; el foco no cambia nada")


def _report_error_lod(pack: ContentPack, args: argparse.Namespace) -> None:
    """Cuánto miente el LOD sobre este mundo, antes de fiarse de él."""
    sim = (
        Simulation.resume(args.load, pack) if args.load is not None
        else Simulation(pack, seed=args.seed)
    )
    _fijar_foco(sim, args.foco)
    print(f"# error del LOD en {pack.label}, {args.days} días, foco {args.foco}")
    for line in error_de_lod(sim, args.days, AgentId(args.foco)).lines():
        print(line)


def _vivo(sim: Simulation, quien: str, opcion: str) -> AgentId:
    if AgentId(quien) not in sim.state.agents:
        raise SystemExit(f"{opcion}: {quien!r} no está vivo en esta partida")
    return AgentId(quien)


def _enlace(sim: Simulation, args: argparse.Namespace) -> tuple[Ruleset, BindingSpec]:
    """El enlace del pack con el sistema de --reglas vive junto al pack, en
    `reglas/<sistema>.yaml` (D-159)."""
    sistema = load_ruleset(args.reglas)
    ruta = args.pack.parent / "reglas" / f"{sistema.id}.yaml"
    if not ruta.exists():
        raise SystemExit(f"este mundo no tiene enlace con el sistema {sistema.id!r}: falta {ruta}")
    return sistema, load_binding(ruta, sim.state.pack, sistema)


def _mecanica(sim: Simulation, args: argparse.Namespace) -> None:
    sistema, enlace = _enlace(sim, args)
    rival = None if args.contra is None else _vivo(sim, args.contra, "--contra")
    if args.ficha_mecanica is not None:
        quien = _vivo(sim, args.ficha_mecanica, "--ficha-mecanica")
        hoja = derive(sim.state, quien, sistema, enlace, () if rival is None else (rival,))
        print(f"\n# ficha mecánica de {quien}  (tick {sim.state.tick})")
        for line in hoja.lines(sistema):
            print(line)
    if args.fichas:
        print()
        for line in census(sim.state, sistema, enlace):
            print(line)
    if args.duelo is not None:
        if rival is None:
            raise SystemExit("--duelo necesita --contra")
        escenario = duel(sim.state, _vivo(sim, args.duelo, "--duelo"), rival, sistema, enlace)
        print()
        for line in simulate(escenario, sistema, args.combates or 100, args.seed).lines():
            print(line)


def _consultar(sim: Simulation, quien: str) -> None:
    print(f"\n# ficha de {quien}  (tick {sim.state.tick})")
    for line in ficha(sim.state, _vivo(sim, quien, "--consultar")).lines():
        print(line)


def _hablar(sim: Simulation, args: argparse.Namespace) -> None:
    agente = _vivo(sim, args.hablar, "--hablar")
    otro = None if args.con is None else _vivo(sim, args.con, "--con")
    proveedor = None if args.sin_llm else OllamaProvider(url=args.llm_url, modelo=args.modelo)
    habla, del_modelo, texto = hablar(sim.state, agente, otro, proveedor)
    print(f"\n# {args.hablar} habla  (tick {sim.state.tick})")
    if not args.quiet:
        print(texto)
    print(f"  » {habla.dice}  [{habla.tono}]  ({'modelo' if del_modelo else 'respaldo'})")


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


def _report_montecarlo(ruleset: Ruleset, tiradas: int, seed: int) -> None:
    print(f"# {ruleset.label}: {tiradas} tiradas simples por reserva, semilla {seed}")
    print("  reserva    ≥1 éxito medido/exacto   pleno medido/exacto   crítico medido/exacto")
    for fila in pool_table(PoolResolver.from_ruleset(ruleset), tiradas, seed):
        print(fila.line())


def _report_combates(args: argparse.Namespace) -> None:
    ruleset = load_ruleset(args.reglas)
    if args.escenario is not None:
        escenario = load_scenario(args.escenario, ruleset)
        if args.relato is not None:
            print(f"# {escenario.label}, encuentro {args.relato}, semilla {args.seed}")
            for line in account(escenario, fight(escenario, ruleset, args.seed, args.relato)):
                print(line)
            return
        for line in simulate(escenario, ruleset, args.combates, args.seed).lines():
            print(line)
        return
    if args.relato is not None:
        raise SystemExit("--relato necesita --escenario")
    comprobaciones = check_calibration(
        ruleset, args.reglas.parent / "escenarios", args.combates, args.seed
    )
    print(f"# {ruleset.label}: {args.combates} encuentros por escenario, semilla {args.seed}")
    for c in comprobaciones:
        print(c.line())
    print(f"  contrato: {'CUMPLE' if all(c.ok for c in comprobaciones) else 'NO CUMPLE'}")


if __name__ == "__main__":
    main()
