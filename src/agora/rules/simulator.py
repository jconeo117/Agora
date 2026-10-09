"""El simulador de combates (unidad 09, §24 del borrador).

Es al sistema de la mesa lo que `--health` es a un mundo: enfrenta un
escenario miles de veces con el encuentro de verdad y comprueba las promesas
que el sistema declara en `calibration`. Cada valor que el borrador marca «a
calibrar» tiene que pasar por aquí antes de fijarse.

La iteración `i` es el encuentro `"<escenario>#<i>"` sobre la misma semilla
base: cualquier combate concreto se reproduce con su número (§24.3).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from agora.engine.ports import Outcome
from agora.engine.rng import RngSource
from agora.rules.encounter import ActionKind, Encounter, EncounterResult, Policy, Status
from agora.rules.policy import StylePolicy
from agora.rules.scene import ScenarioSpec, load_scenario
from agora.rules.system import CalibrationTarget, Ruleset


def encounter_id(scenario: ScenarioSpec, iteration: int) -> str:
    return f"{scenario.id}#{iteration}"


def fight(
    scenario: ScenarioSpec, ruleset: Ruleset, seed: int, iteration: int,
    policy: Policy | None = None,
) -> EncounterResult:
    encuentro = Encounter(scenario, ruleset, RngSource(seed), encounter_id(scenario, iteration))
    return encuentro.run(policy if policy is not None else StylePolicy())


@dataclass(frozen=True, slots=True)
class SimulationReport:
    scenario: str
    iterations: int
    wins: tuple[tuple[str, int], ...]
    draws: int
    rounds: tuple[int, ...]
    """Las rondas de cada encuentro, ordenadas."""
    outcomes: tuple[tuple[Outcome, int], ...]
    """Resultados de los ataques, incluidos los contraataques."""
    hits: int
    damage: int
    endings: tuple[tuple[Status, int], ...]
    """Cómo acabó cada combatiente, sumado sobre todas las iteraciones."""

    def win_rate(self, side: str) -> float:
        return dict(self.wins).get(side, 0) / self.iterations

    @property
    def median_rounds(self) -> int:
        return self.rounds[len(self.rounds) // 2]

    def lines(self) -> list[str]:
        ataques = sum(n for _, n in self.outcomes) or 1
        salida = [f"# {self.scenario}: {self.iterations} encuentros"]
        salida += [f"  gana {lado:<12} {n / self.iterations:6.1%}" for lado, n in self.wins]
        salida.append(f"  empate           {self.draws / self.iterations:6.1%}")
        p90 = self.rounds[min(len(self.rounds) - 1, len(self.rounds) * 9 // 10)]
        salida.append(f"  rondas           mediana {self.median_rounds}, p90 {p90}")
        salida.append("  ataques          " + "  ".join(
            f"{o.value} {n / ataques:.1%}" for o, n in self.outcomes))
        salida.append(f"  daño por acierto {self.damage / (self.hits or 1):.1f}")
        salida.append("  acaban           " + "  ".join(f"{s.value} {n}" for s, n in self.endings))
        return salida


def simulate(
    scenario: ScenarioSpec, ruleset: Ruleset, iterations: int, seed: int,
    policy: Policy | None = None,
) -> SimulationReport:
    victorias: Counter[str] = Counter()
    empates = 0
    rondas: list[int] = []
    resultados: Counter[Outcome] = Counter()
    finales: Counter[Status] = Counter()
    aciertos = dano = 0
    for i in range(iterations):
        r = fight(scenario, ruleset, seed, i, policy)
        if r.winner is None:
            empates += 1
        else:
            victorias[r.winner] += 1
        rondas.append(r.rounds)
        for b in r.beats:
            if b.kind == ActionKind.ATTACK and b.outcome is not None:
                resultados[b.outcome] += 1
                if b.damage > 0:
                    aciertos += 1
                    dano += b.damage
        finales.update(f.status for f in r.fighters)
    return SimulationReport(
        scenario=scenario.id,
        iterations=iterations,
        wins=tuple((s.id, victorias[s.id]) for s in scenario.sides),
        draws=empates,
        rounds=tuple(sorted(rondas)),
        outcomes=tuple((o, resultados[o]) for o in Outcome),
        hits=aciertos,
        damage=dano,
        endings=tuple((s, finales[s]) for s in Status if finales[s]),
    )


@dataclass(frozen=True, slots=True)
class CalibrationCheck:
    target: CalibrationTarget
    win_rate: float
    median_rounds: int

    @property
    def ok(self) -> bool:
        t = self.target
        gana = t.win_min <= self.win_rate * 100 <= t.win_max
        lento = t.rounds_min is not None and self.median_rounds < t.rounds_min
        largo = t.rounds_max is not None and self.median_rounds > t.rounds_max
        return gana and not lento and not largo

    def line(self) -> str:
        t = self.target
        rondas = (f"  rondas {self.median_rounds} en [{t.rounds_min or '-'}, {t.rounds_max or '-'}]"
                  if t.rounds_min is not None or t.rounds_max is not None else "")
        return (f"  {'CUMPLE   ' if self.ok else 'NO CUMPLE'}  {t.scenario:<24} {t.side:<10}"
                f" gana {self.win_rate:6.1%} en [{t.win_min}%, {t.win_max}%]{rondas}")


def check_calibration(
    ruleset: Ruleset, folder: Path, iterations: int, seed: int
) -> tuple[CalibrationCheck, ...]:
    """Cada escenario se simula una vez aunque lo citen varias promesas."""
    informes: dict[str, SimulationReport] = {}
    comprobaciones = []
    for t in ruleset.calibration:
        if t.scenario not in informes:
            escenario = load_scenario(folder / f"{t.scenario}.yaml", ruleset)
            informes[t.scenario] = simulate(escenario, ruleset, iterations, seed)
        informe = informes[t.scenario]
        comprobaciones.append(CalibrationCheck(t, informe.win_rate(t.side), informe.median_rounds))
    return tuple(comprobaciones)


def account(scenario: ScenarioSpec, result: EncounterResult) -> list[str]:
    """El relato de un encuentro para quien dirige: una línea por hecho, con
    los dados resumidos. Depuración y mesa, no narrador (como `render.py`)."""
    nombres = {c.id: c.label for side in scenario.sides for c in side.combatants}
    salida = []
    for b in result.beats:
        quien = nombres[b.actor]
        a_quien = f" a {nombres[b.target]}" if b.target is not None else ""
        que = f" → {b.outcome.value}" if b.outcome is not None else ""
        dano = f", {b.damage} de daño" if b.damage else ""
        nota = f" ({b.note})" if b.note else ""
        salida.append(f"  r{b.round:<3} {quien}: {b.kind}{a_quien}{que}{dano}{nota}")
    final = ", ".join(
        f"{nombres[f.id]} {f.status.value} ({f.vitality} PV)" for f in result.fighters
    )
    ganador = next((s.label for s in scenario.sides if s.id == result.winner), "nadie")
    salida.append(f"  gana {ganador} en {result.rounds} rondas: {final}")
    return salida
