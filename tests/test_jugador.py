"""Pruebas del jugador en el motor (unidad 10, §B.1)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

import agora.agents.decide
from agora.agents.decide import Decision, decide, options
from agora.engine.events import EventKind
from agora.engine.ontology import ActionId, AgentId, AgentSpec, NeedId, PlaceId
from agora.engine.pack import load_pack
from agora.engine.persistence import load
from agora.engine.ports import PlotView
from agora.engine.state import AgentState, PerformingAction, WorldState
from agora.engine.world import Simulation

CIUDAD_PACK = Path("packs/ciudad/pack.yaml")
CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")

type ChoiceFn = Callable[[WorldState, AgentState, tuple[Decision, ...]], Decision | None]


class _SpySource:
    def __init__(
        self,
        choice_fn: ChoiceFn | None = None,
        interrupt_val: bool = False,
    ) -> None:
        self.choice_fn = choice_fn
        self.interrupt_val = interrupt_val
        self.choose_calls: list[tuple[AgentId, tuple[Decision, ...]]] = []
        self.interrupt_calls: list[tuple[AgentId, str]] = []

    def choose(
        self, world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
    ) -> Decision | None:
        self.choose_calls.append((agent.spec_id, opts))
        if self.choice_fn is not None:
            return self.choice_fn(world, agent, opts)
        return opts[0] if opts else None

    def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
        self.interrupt_calls.append((agent.spec_id, str(need)))
        return self.interrupt_val

    def choose_plot(self, world: WorldState, agent: AgentState, vista: PlotView) -> int | None:
        return None


def test_sin_jugador_el_mundo_no_cambia() -> None:
    # ciudad a 1 día, el log con y sin la unidad es el mismo.
    # Se comprueba contra una corrida con player=None: ningún tick llama a la fuente.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    source = _SpySource()
    sim.player_source = source

    assert sim.state.player is None
    sim.run(96)
    assert len(source.choose_calls) == 0
    assert len(source.interrupt_calls) == 0


def test_options_es_el_menu_de_decide() -> None:
    # para varios agentes y ticks, decide() devuelve siempre una de las
    # candidate_pool primeras de options(), y options(..., must_address)
    # solo trae acciones que atienden esa necesidad.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    sim.run(5)

    candidate_pool = pack.tuning.candidate_pool
    agentes = list(sim.state.agents.values())[:3]
    for agent in agentes:
        opts = options(sim.state, agent)
        assert len(opts) > 0
        choice = decide(sim.state, agent)
        if choice is not None:
            assert choice in opts[:candidate_pool]

        for need in pack.needs:
            opts_need = options(sim.state, agent, must_address=need.id)
            for o in opts_need:
                satisfies = pack.action_by_id[o.action].satisfies.get(need.id, 0.0)
                assert satisfies > 0.0


def test_el_jugador_decide_desde_fuera(monkeypatch: pytest.MonkeyPatch) -> None:
    # con set_player, decide no se llama para él (monkeypatch que revienta
    # si se le pasa el jugador) y su acción es la que eligió la fuente.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    player = sim.state.agents[pid]
    player.busy = None

    orig_decide = agora.agents.decide.decide

    def fail_if_player(
        world: WorldState, agent: AgentState, must_address: NeedId | None = None
    ) -> Decision | None:
        assert agent.spec_id != sim.state.player, "decide() fue llamado para el jugador"
        return orig_decide(world, agent, must_address)

    monkeypatch.setattr("agora.engine.world.decide", fail_if_player)

    chosen_decision: Decision | None = None

    def pick_first(
        world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
    ) -> Decision | None:
        nonlocal chosen_decision
        chosen_decision = opts[0]
        return chosen_decision

    source = _SpySource(choice_fn=pick_first)
    sim.player_source = source

    sim.tick()
    assert chosen_decision is not None
    assert len(source.choose_calls) >= 1
    # El jugador tomó la decisión de la fuente
    if chosen_decision.travel_ticks == 0:
        busy = sim.state.agents[pid].busy
        assert isinstance(busy, PerformingAction)
        assert busy.action == chosen_decision.action


def test_el_menu_del_jugador_es_el_de_un_npc() -> None:
    # lo que recibe la fuente es exactamente tuple(options(world, agente)).
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    player = sim.state.agents[pid]
    player.busy = None

    menu_recibido: tuple[Decision, ...] | None = None

    def capture_menu(
        world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
    ) -> Decision | None:
        nonlocal menu_recibido
        menu_recibido = opts
        assert opts == tuple(options(world, agent))
        return opts[0] if opts else None

    source = _SpySource(choice_fn=capture_menu)
    sim.player_source = source
    sim.tick()

    assert menu_recibido is not None
    assert len(source.choose_calls) >= 1


def test_lo_que_no_esta_en_el_menu_no_se_hace() -> None:
    # una fuente que devuelve una Decision inventada → ValueError.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    sim.state.agents[pid].busy = None

    invented = Decision(
        action=ActionId("inventada"),
        place=PlaceId("inventado"),
        utility=0.0,
        target=None,
        travel_ticks=0,
    )
    source = _SpySource(choice_fn=lambda w, a, opts: invented)
    sim.player_source = source

    with pytest.raises(ValueError, match="no está entre sus opciones"):
        sim.tick()


def test_esperar_no_deja_rastro() -> None:
    # una fuente que siempre devuelve None: el jugador sigue ocioso, no hay ningún
    # evento suyo y se le vuelve a preguntar el tick siguiente.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    sim.run(2)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    player = sim.state.agents[pid]
    player.busy = None

    source = _SpySource(choice_fn=lambda w, a, opts: None)
    sim.player_source = source

    seq_antes = sim.log.siguiente_seq
    sim.tick()

    assert player.busy is None
    assert len(source.choose_calls) == 1

    eventos_jugador = [e for e in sim.log if e.seq >= seq_antes and e.actor == pid]
    assert len(eventos_jugador) == 0

    # Siguiente tick: vuelve a preguntar
    sim.tick()
    assert len(source.choose_calls) == 2
    assert player.busy is None


def test_sin_fuente_no_se_juega() -> None:
    # con jugador y player_source=None, el primer tick en que queda ocioso →
    # RuntimeError con el mensaje.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    sim.state.agents[pid].busy = None
    sim.player_source = None

    with pytest.raises(RuntimeError, match=r"la partida tiene jugador .* y nadie decide por él"):
        sim.tick()


def test_la_urgencia_se_le_pregunta() -> None:
    # un jugador ocupado con una necesidad que cruza el umbral: la fuente recibe
    # interrupt con esa necesidad; si dice que no, sigue con lo suyo; si dice que
    # sí, aborta y el siguiente menú solo trae acciones que la atienden. A un NPC
    # no se le pregunta.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)
    player = sim.state.agents[pid]

    # Ponemos al jugador ocupado en una acción larga que NO atiende descanso
    urgent_need = pack.needs[0].id
    action_no_urgent = next(
        a.id for a in pack.actions if urgent_need not in a.satisfies
    )
    player.busy = PerformingAction(action=action_no_urgent, ticks_remaining=10, total_ticks=10)
    # Hacemos que la necesidad cruce el umbral crítico
    player.needs[urgent_need] = pack.tuning.critical_need_threshold + 0.1

    # 1. Fuente dice que NO interrumpe (interrupt devuelve False)
    source_no = _SpySource(interrupt_val=False)
    sim.player_source = source_no

    lo_deja = sim._lo_deja(player, urgent_need)
    assert lo_deja is False
    assert len(source_no.interrupt_calls) == 1
    assert source_no.interrupt_calls[0] == (pid, str(urgent_need))

    # 2. Fuente dice que SÍ interrumpe (interrupt devuelve True)
    source_si = _SpySource(interrupt_val=True)
    sim.player_source = source_si

    lo_deja_si = sim._lo_deja(player, urgent_need)
    assert lo_deja_si is True
    assert len(source_si.interrupt_calls) == 1

    # 3. Comprobar que a un NPC no se le pregunta
    npc_id = next(a for a in sim.state.agents if a != pid)
    npc = sim.state.agents[npc_id]
    source_npc = _SpySource()
    sim.player_source = source_npc
    assert sim._lo_deja(npc, urgent_need) is True
    assert len(source_npc.interrupt_calls) == 0

    # 4. Cuando aborta, el menú de begin solo trae acciones que atienden la necesidad
    source_menu = _SpySource(choice_fn=lambda w, a, opts: opts[0] if opts else None)
    sim.player_source = source_menu
    sim._begin_player(player, must_address=urgent_need)
    assert len(source_menu.choose_calls) == 1
    recibidas = source_menu.choose_calls[0][1]
    for opcion in recibidas:
        assert pack.action_by_id[opcion.action].satisfies.get(urgent_need, 0.0) > 0.0


def test_el_jugador_es_el_foco() -> None:
    # set_player pone state.focus. Un agente que no está vivo → KeyError.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))

    sim.set_player(pid)
    assert sim.state.player == pid
    assert sim.state.focus == pid

    with pytest.raises(KeyError, match="no está vivo en esta partida"):
        sim.set_player(AgentId("fantasma_inexistente"))


def test_el_jugador_viaja_en_el_guardado(tmp_path: Path) -> None:
    # guardar y reanudar conserva state.player; un guardado sin la clave se lee
    # sin jugador; si el jugador murió, se lee sin jugador.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    pid = next(iter(sim.state.agents.keys()))
    sim.set_player(pid)

    ruta = tmp_path / "partida.json"
    sim.save(ruta)

    # Reanudar conserva el jugador
    w_cargado, _, _ = load(ruta, pack)
    assert w_cargado.player == pid

    # Guardado sin clave "player" se lee sin jugador
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    del datos["player"]
    ruta_sin_player = tmp_path / "sin_player.json"
    ruta_sin_player.write_text(json.dumps(datos), encoding="utf-8")
    w_sin, _, _ = load(ruta_sin_player, pack)
    assert w_sin.player is None

    # Si el jugador murió, se lee sin jugador
    sim.morir(pid, porque="test")
    assert pid not in sim.state.agents
    sim.save(ruta)
    w_muerto, _, _ = load(ruta, pack)
    assert w_muerto.player is None


def test_admit_es_la_puerta_del_parto() -> None:
    # un nacimiento sigue dando el mismo nacido_en (el tick) y el mismo agente que antes;
    # admit de una ficha con edad_inicial E en el tick T deja nacido_en == T - E.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)
    sim.state.tick = 100

    spec = AgentSpec(
        id=AgentId("nuevo_admitido"),
        label="Nuevo Admitido",
        home=pack.places[0].id,
        start_at=pack.places[0].id,
        edad_inicial=20,
    )
    agente = sim.admit(spec)
    assert agente.spec_id == spec.id
    assert agente.nacido_en == 100 - 20
    assert sim.state.censo[spec.id] == spec
    assert sim.state.agents[spec.id] is agente


def test_el_forastero_llega() -> None:
    # arrive emite AGENT_ARRIVED con su lugar, lo mete en el censo y en el reparto,
    # y sin relaciones ni vínculos. Un id que ya está en el censo (también el de un muerto)
    # → ValueError.
    pack = load_pack(CIUDAD_PACK)
    sim = Simulation(pack, seed=1312)

    spec = AgentSpec(
        id=AgentId("forastero_test"),
        label="Forastero de Prueba",
        home=pack.places[0].id,
        start_at=pack.places[0].id,
    )
    agente = sim.arrive(spec)
    assert agente.spec_id == spec.id
    assert spec.id in sim.state.censo
    assert spec.id in sim.state.agents
    assert len(agente.relations) == 0
    assert len(agente.bonds) == 0

    ultimo_evento = list(sim.log)[-1]
    assert ultimo_evento.kind == EventKind.AGENT_ARRIVED
    assert ultimo_evento.actor == spec.id
    assert ultimo_evento.place == spec.start_at

    # Un id que ya está en el censo levanta ValueError
    with pytest.raises(ValueError, match="ya está en el censo"):
        sim.arrive(spec)

    # También si el agente murió
    pid = next(iter(sim.state.agents.keys()))
    sim.morir(pid, porque="test")
    muerto_spec = sim.state.censo[pid]
    with pytest.raises(ValueError, match="ya está en el censo"):
        sim.arrive(muerto_spec)
