"""Cuánto miente el LOD (D-152), con el mismo instrumento que el salto.

Existe antes de fiarse del LOD por lo mismo que `error_de_salto` existió antes
de fiarse del salto: una aproximación que no dice cuánto se aparta acaba
tratándose como exacta (D-088). Y se mide también por nivel, porque lo que
importa es que cerca del foco el mundo sea el de verdad.
"""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass

from agora.engine.ontology import AgentId, NeedId
from agora.engine.state import DetailLevel
from agora.engine.timeskip import Fidelidad, comparar
from agora.engine.world import Simulation


@dataclass(frozen=True, slots=True)
class FidelidadLod:
    """La desviación general, la de cada nivel y lo que costó cada mundo."""

    general: Fidelidad
    por_nivel: dict[DetailLevel, dict[NeedId, float]]
    """Desviación media de cada eje entre las MISMAS personas, agrupadas por el
    nivel que tenían al final de la corrida con LOD."""

    cuantos: dict[DetailLevel, int]
    segundos: tuple[float, float]
    """(entero, con LOD). No es determinista: es un reloj."""

    def lines(self) -> list[str]:
        salida = [
            f"  tiempo        {self.segundos[0]:.1f} s entero · {self.segundos[1]:.1f} s con LOD "
            f"({self.segundos[1] / max(self.segundos[0], 1e-9):.0%})",
            f"  agentes       {dict(sorted(self.cuantos.items()))}",
        ]
        salida += [
            f"  {n:12}  real {r:4}  lod {a:4}" for n, (r, a) in self.general.sucesos().items()
        ]
        for nivel, ejes in sorted(self.por_nivel.items()):
            peor = max(ejes.values(), default=0.0)
            salida.append(f"  ejes {nivel:6}   desviación máxima {peor:.3f}")
        salida += [f"    {eje:14} {d:.3f}" for eje, d in sorted(self.general.ejes.items())]
        return salida


def error_de_lod(sim_base: Simulation, dias: int, foco: AgentId) -> FidelidadLod:
    """Corre el mismo arranque dos veces, entero y con el LOD alrededor de
    `foco`, y compara."""
    ticks = dias * sim_base.pack.clock.ticks_per_day

    real = deepcopy(sim_base)
    real.state.focus = None
    t0 = time.perf_counter()
    real.run(ticks)
    t_real = time.perf_counter() - t0

    con_lod = deepcopy(sim_base)
    con_lod.state.focus = foco
    t0 = time.perf_counter()
    con_lod.run(ticks)
    t_lod = time.perf_counter() - t0

    niveles = {a.spec_id: con_lod.state.detail_level(a) for a in con_lod.state.agents_in_order()}
    por_nivel: dict[DetailLevel, dict[NeedId, float]] = {}
    cuantos: dict[DetailLevel, int] = {}
    for nivel in DetailLevel:
        ids = [i for i, n in niveles.items() if n is nivel and i in real.state.agents]
        cuantos[nivel] = len(ids)
        if not ids:
            continue
        por_nivel[nivel] = {
            need.id: sum(
                abs(real.state.agents[i].needs[need.id] - con_lod.state.agents[i].needs[need.id])
                for i in ids
            ) / len(ids)
            for need in sim_base.pack.needs
        }
    return FidelidadLod(
        general=comparar(real, con_lod), por_nivel=por_nivel,
        cuantos=cuantos, segundos=(t_real, t_lod),
    )
