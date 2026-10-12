"""Pruebas del guion, grabación, terminal y bucle de juego (unidad 10, §B.3)."""

from __future__ import annotations

import io
import json
import math
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from agora.agents.decide import Decision, options
from agora.engine.newcomer import load_sheet, newcomer_spec
from agora.engine.ontology import ActionId, AgentId, NeedId
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.rng import RngSource
from agora.engine.state import AgentState, PerformingAction, WorldState
from agora.engine.world import Simulation
from agora.play import (
    SIN_MODELO,
    Recorder,
    Script,
    ScriptError,
    Terminal,
    TerminalCombat,
    hint,
    play,
)
from agora.rules.encounter import ActionKind, Encounter
from agora.rules.scene import load_scenario
from agora.rules.system import load_ruleset
from agora.run import main

CONFLUENCIA_PACK = Path("packs/confluencia/pack.yaml")
FORASTERO_SHEET = Path("packs/confluencia/forastero.yaml")
ISLA_PACK = Path("packs/isla/pack.yaml")


def test_grabar_y_volver_a_jugar_da_el_mismo_mundo(tmp_path: Path) -> None:
    # 18. forastero en confluencia, 192 ticks, fuente «la primera» envuelta en Recorder;
    # el mismo guion con Script da el mismo log byte a byte.
    pack = load_pack(CONFLUENCIA_PACK)
    sim1 = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim1.state.censo)
    sim1.arrive(spec)
    sim1.set_player(spec.id)

    class FirstSource:
        def choose(
            self, world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
        ) -> Decision | None:
            return opts[0] if opts else None

        def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
            return False

    script_path = tmp_path / "guion.jsonl"
    with script_path.open("w", encoding="utf-8") as f:
        rec = Recorder(FirstSource(), f)
        res1 = play(sim1, rec, 192)

    assert res1.ticks == 192
    lines = script_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 0
    # Al menos una decisión con destinatario para cubrir M14
    has_target = any("destinatario" in json.loads(line).get("decidir", {}) for line in lines)
    assert has_target, "El guion debe tener al menos una decisión con destinatario para cubrir M14"

    sim2 = Simulation(pack, seed=1312)
    sim2.arrive(spec)
    sim2.set_player(spec.id)
    guion = Script(lines)
    res2 = play(sim2, guion, 192)

    assert res2.ticks == 192
    assert list(sim1.log) == list(sim2.log)


def test_reanudar_con_guion_es_no_haber_parado(tmp_path: Path) -> None:
    # 19. el mismo guion, guardando en el tick 96 y reanudando: mismo log que sin parar.
    pack = load_pack(CONFLUENCIA_PACK)
    sheet = load_sheet(FORASTERO_SHEET)

    sim_rec = Simulation(pack, seed=1312)
    spec = newcomer_spec(pack, sheet, sim_rec.state.censo)
    sim_rec.arrive(spec)
    sim_rec.set_player(spec.id)

    class FirstSource:
        def choose(
            self, world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
        ) -> Decision | None:
            return opts[0] if opts else None

        def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
            return False

    script_buf = io.StringIO()
    rec = Recorder(FirstSource(), script_buf)
    play(sim_rec, rec, 192)
    guion_lines = script_buf.getvalue().splitlines()

    # Corrida ininterrumpida
    sink1 = io.StringIO()
    sim1 = Simulation(pack, seed=1312, log_sink=sink1)
    sim1.arrive(spec)
    sim1.set_player(spec.id)
    res1 = play(sim1, Script(guion_lines), 192)
    assert res1.ticks == 192

    # Corrida interrumpida a 96 ticks, guardada y reanudada
    save_path = tmp_path / "partida_96.json"
    sink2 = io.StringIO()
    sim2 = Simulation(pack, seed=1312, log_sink=sink2)
    sim2.arrive(spec)
    sim2.set_player(spec.id)
    res2_part1 = play(sim2, Script(guion_lines), 96)
    assert res2_part1.ticks == 96
    sim2.save(save_path)

    sim_resumed = Simulation.resume(save_path, pack, log_sink=sink2)
    res2_part2 = play(sim_resumed, Script(guion_lines), 96)
    assert res2_part2.ticks == 96

    assert sink1.getvalue() == sink2.getvalue()


def test_un_guion_imposible_se_para() -> None:
    # 20. una decisión que no está en el menú en su tick → ScriptError.
    # Una línea sin «decidir» ni «interrumpir» → ScriptError.
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)

    with pytest.raises(ScriptError, match="línea 1: ni «decidir», ni «interrumpir», ni de combate"):
        Script(['{"tick": 0, "algo_invalido": true}'])

    guion = Script([
        '{"tick": 0, "decidir": {"accion": "accion_fantasma", "lugar": "lugar_fantasma"}}'
    ])
    agent = sim.state.agents[spec.id]
    opts = tuple(options(sim.state, agent))
    with pytest.raises(ScriptError, match="no está entre las opciones"):
        guion.choose(sim.state, agent, opts)


def test_el_guion_identifica_por_contenido() -> None:
    # 21. la misma decisión en otra posición del menú se encuentra igual (cubre M13).
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)

    agent = sim.state.agents[spec.id]
    opts = options(sim.state, agent)
    assert len(opts) >= 3

    target_opt = opts[2]
    d_dict: dict[str, str] = {
        "accion": str(target_opt.action),
        "lugar": str(target_opt.place),
    }
    if target_opt.target is not None:
        d_dict["destinatario"] = str(target_opt.target)

    line = json.dumps({"tick": 0, "decidir": d_dict})
    guion = Script([line])

    # Se coloca target_opt en la posición 2
    reordered_opts = (opts[0], opts[1], target_opt)
    chosen = guion.choose(sim.state, agent, reordered_opts)
    assert chosen == target_opt

    # Se coloca target_opt en la posición 1
    reordered_opts2 = (opts[1], target_opt, opts[0])
    chosen2 = guion.choose(sim.state, agent, reordered_opts2)
    assert chosen2 == target_opt


def test_las_bandas() -> None:
    # 22. hint con peso 1, 0.5, 0.49, 0.1, 0.01 y menos, en sus fronteras (cubre M15).
    best = 0.0
    temp = 1.0

    # peso = 1.0
    assert hint(best, best, temp) == "te conviene mucho"

    # peso = 0.5 (frontera exacta de >= 0.5: cubre M15 si se muta a > 0.5)
    u_05 = math.log(0.5)
    assert hint(u_05, best, temp) == "te conviene mucho"

    # peso = 0.49
    u_049 = math.log(0.49)
    assert hint(u_049, best, temp) == "te conviene"

    # peso = 0.1
    u_01 = math.log(0.1)
    assert hint(u_01, best, temp) == "te conviene"

    # peso = 0.09
    u_009 = math.log(0.09)
    assert hint(u_009, best, temp) == "te conviene poco"

    # peso = 0.01
    u_001 = math.log(0.01)
    assert hint(u_001, best, temp) == "te conviene poco"

    # peso < 0.01
    u_menor = math.log(0.005)
    assert hint(u_menor, best, temp) == "no te conviene"


def test_la_terminal_elige_y_consulta() -> None:
    # 23. con entrada mirar, ficha, hablar <alguien presente>, 2: devuelve la segunda
    # opción y escribe la ficha y la réplica del respaldo. hablar a ausente da la ayuda.
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)

    # Buscar dos agentes en el mismo lugar y uno en otro
    agents = sim.state.agents_in_order()
    presente = agents[0]
    otro_aqui = next(a for a in agents[1:] if a.at == presente.at)
    ausente = next(a for a in agents if a.at != presente.at)

    opts = tuple(options(sim.state, presente))
    assert len(opts) >= 2

    # Entrada con consultas y elección final de la opción 2
    comandos = [
        "mirar",
        "ficha",
        f"hablar {otro_aqui.spec_id}",
        f"hablar {ausente.spec_id}",
        "2",
    ]
    inp = io.StringIO("\n".join(comandos) + "\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None)

    elegida = terminal.choose(sim.state, presente, opts)
    assert elegida == opts[1]

    texto_salida = out.getvalue()
    assert f"en {pack.place_by_id[presente.at].label}:" in texto_salida
    assert otro_aqui.spec_id in texto_salida
    assert "(respaldo)" in texto_salida
    assert "no hay nadie así aquí con quien hablar" in texto_salida


def test_esperar_n() -> None:
    # 24. esperar 3 devuelve None tres veces seguidas sin leer la entrada.
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = next(iter(sim.state.agents.values()))
    opts = tuple(options(sim.state, agent))

    inp = io.StringIO("esperar 3\n1\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out)

    # 1ª llamada: lee "esperar 3", programa 2 más y devuelve None
    assert terminal.choose(sim.state, agent, opts) is None
    assert terminal._esperar == 2

    # 2ª llamada: devuelve None sin leer entrada
    assert terminal.choose(sim.state, agent, opts) is None
    assert terminal._esperar == 1

    # 3ª llamada: devuelve None sin leer entrada
    assert terminal.choose(sim.state, agent, opts) is None
    assert terminal._esperar == 0

    # 4ª llamada: lee "1" de la entrada y devuelve opts[0]
    assert terminal.choose(sim.state, agent, opts) == opts[0]


def test_salir_es_entre_ticks() -> None:
    # 25. salir (o fin de entrada) hace que play acabe con reason="salir" al empezar
    # el tick siguiente, con el mundo entero en un tick completo (cubre M17).
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)

    inp = io.StringIO("salir\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out)

    res = play(sim, terminal, max_ticks=10, quitting=terminal)
    assert res.reason == "salir"
    assert res.ticks == 1
    assert sim.state.tick == 1

    # Si la terminal ya estaba en quit, se detiene antes del tick sin avanzar
    res0 = play(sim, terminal, max_ticks=10, quitting=terminal)
    assert res0.reason == "salir"
    assert res0.ticks == 0
    assert sim.state.tick == 1


def test_la_terminal_no_repregunta() -> None:
    # 26. decir que no a una interrupción hace que no se vuelva a preguntar por la misma
    # necesidad mientras siga con lo mismo (cubre M16).
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = next(iter(sim.state.agents.values()))
    agent.busy = PerformingAction(action=ActionId("comer"), ticks_remaining=3, total_ticks=4)

    # Solo una línea de respuesta disponible: "n\n"
    inp = io.StringIO("n\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out)

    need = next(iter(pack.need_by_id.keys()))
    # Primera interrupción: lee "n", rechaza, anota en _rechazos
    assert terminal.interrupt(sim.state, agent, need) is False
    assert (need, id(agent.busy)) in terminal._rechazos

    # Segunda interrupción: no debe leer la entrada
    assert terminal.interrupt(sim.state, agent, need) is False
    assert not terminal.quit


def test_la_muerte_acaba_la_partida() -> None:
    # 27. un jugador al que se mata con sim.morir → play devuelve reason="muerte".
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    sheet = load_sheet(FORASTERO_SHEET)
    spec = newcomer_spec(pack, sheet, sim.state.censo)
    sim.arrive(spec)
    sim.set_player(spec.id)

    class KillingSource:
        def choose(
            self, world: WorldState, agent: AgentState, opts: tuple[Decision, ...]
        ) -> Decision | None:
            sim.morir(agent.spec_id, porque="prueba de muerte")
            return opts[0] if opts else None

        def interrupt(self, world: WorldState, agent: AgentState, need: NeedId) -> bool:
            return False

    res = play(sim, KillingSource(), max_ticks=10)
    assert res.reason == "muerte"
    assert res.ticks == 1


def test_jugar_por_la_linea_de_ordenes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # 28. main() con --jugar <vivo> --guion vacío y --days 1 --quiet
    # acaba con «fin de la partida: fin»;
    # --jugar con alguien que no existe → SystemExit;
    # --skip 3 con jugador → SystemExit (cubre M20).
    empty_guion = tmp_path / "vacio.jsonl"
    empty_guion.write_text("", encoding="utf-8")

    vivo = "cyra_nieblalta"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--jugar",
            vivo,
            "--guion",
            str(empty_guion),
            "--days",
            "1",
            "--quiet",
        ],
    )
    main()
    out = capsys.readouterr().out
    assert "# fin de la partida: fin, 96 ticks jugados" in out

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--jugar",
            "nadie_existe",
            "--days",
            "1",
        ],
    )
    with pytest.raises(SystemExit, match="no está vivo"):
        main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agora",
            "--pack",
            str(CONFLUENCIA_PACK),
            "--jugar",
            vivo,
            "--skip",
            "3",
            "--days",
            "1",
        ],
    )
    with pytest.raises(SystemExit, match="--skip no se puede jugar"):
        main()


def test_prosa_sin_destinatario_con_lexico() -> None:
    # 1. Prosa sin destinatario con el léxico (interpreter=None): la terminal
    # devuelve esa Decision sin preguntar y escribe →.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = sim.state.agents[AgentId("elor_d1")]
    opts = tuple(options(sim.state, agent))

    inp = io.StringIO("me echo a dormir aquí mismo\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None, interpreter=None)
    elegida = terminal.choose(sim.state, agent, opts)

    assert elegida is not None
    assert elegida.action == ActionId("dormir_al_raso")
    assert elegida.target is None
    assert "→" in out.getvalue()


def test_prosa_contra_alguien_confirma() -> None:
    # 2. Prosa contra alguien (proveedor fingido que devuelve esa intención):
    # pregunta entiendo:; con n no decide y sigue leyendo; con Enter devuelve la decisión.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    while sim.state.tick < 7:
        sim.tick()
    agent = sim.state.agents[AgentId("elor_d1")]
    opts = tuple(options(sim.state, agent))
    atacar_renna = next(
        o for o in opts if o.action == ActionId("atacar") and o.target == AgentId("renna_d1")
    )

    class FakeProvider(CognitionProvider):
        def think(self, briefing: str, schema: type, semilla: int) -> object | None:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                return schema.model_validate(
                    {"tipo": "accion", "accion": "atacar", "destinatario": "renna_d1"}
                )
            return None

    # Primero 'n' rechaza y sigue en el bucle; luego Enter (línea vacía '\n') confirma.
    inp = io.StringIO("ataco a Renna\nn\nataco a Renna\n\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None, interpreter=FakeProvider())
    elegida = terminal.choose(sim.state, agent, opts)

    assert elegida == atacar_renna
    assert "entiendo:" in out.getvalue()


def test_no_fit_con_candidatas() -> None:
    # 3. NO_FIT con candidatas: con b devuelve la segunda candidata; con x no decide.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)
    while sim.state.tick < 7:
        sim.tick()
    agent = sim.state.agents[AgentId("elor_d1")]
    opts = tuple(options(sim.state, agent))

    class AmbiguousProvider(CognitionProvider):
        def think(self, briefing: str, schema: type, semilla: int) -> object | None:
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                return schema.model_validate({
                    "tipo": "ambigua",
                    "candidatas": [
                        {
                            "accion": str(opts[0].action),
                            "destinatario": str(opts[0].target) if opts[0].target else None,
                        },
                        {
                            "accion": str(opts[1].action),
                            "destinatario": str(opts[1].target) if opts[1].target else None,
                        },
                    ],
                })
            return None

    # Primero 'x' rechaza y sigue; luego 'b' elige la segunda candidata (opts[1]).
    inp = io.StringIO("algo ambiguo\nx\nalgo ambiguo\nb\n")
    out = io.StringIO()
    terminal = Terminal(sim, inp, out, provider=None, interpreter=AmbiguousProvider())
    elegida = terminal.choose(sim.state, agent, opts)

    assert elegida == opts[1]
    assert "¿cuál de estas?" in out.getvalue()


def test_proveedor_fingido_none_dice_sin_modelo() -> None:
    # 4. Proveedor fingido que devuelve None: la salida contiene SIN_MODELO.
    # Sin intérprete (None), no lo contiene.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1312)
    agent = sim.state.agents[AgentId("elor_d1")]
    opts = tuple(options(sim.state, agent))

    class NoneProvider(CognitionProvider):
        def think(self, briefing: str, schema: type, semilla: int) -> object | None:
            return None

    # Con intérprete que devuelve None:
    inp1 = io.StringIO("me echo a dormir aquí mismo\n")
    out1 = io.StringIO()
    term1 = Terminal(sim, inp1, out1, provider=None, interpreter=NoneProvider())
    term1.choose(sim.state, agent, opts)
    assert SIN_MODELO in out1.getvalue()

    # Sin intérprete (None):
    inp2 = io.StringIO("me echo a dormir aquí mismo\n")
    out2 = io.StringIO()
    term2 = Terminal(sim, inp2, out2, provider=None, interpreter=None)
    term2.choose(sim.state, agent, opts)
    assert SIN_MODELO not in out2.getvalue()


def test_quien_hay_aqui_con_lexico_como_mirar() -> None:
    # 5. «¿quién hay aquí?» con el léxico escribe lo mismo que mirar.
    pack = load_pack(CONFLUENCIA_PACK)
    sim = Simulation(pack, seed=1312)
    agents = sim.state.agents_in_order()
    presente = agents[0]
    opts = tuple(options(sim.state, presente))

    inp1 = io.StringIO("mirar\n1\n")
    out1 = io.StringIO()
    term1 = Terminal(sim, inp1, out1, provider=None, interpreter=None)
    term1.choose(sim.state, presente, opts)

    inp2 = io.StringIO("¿quién hay aquí?\n1\n")
    out2 = io.StringIO()
    term2 = Terminal(sim, inp2, out2, provider=None, interpreter=None)
    term2.choose(sim.state, presente, opts)

    lineas1 = [
        line for line in out1.getvalue().splitlines() if line.startswith("    ") or "más" in line
    ]
    lineas2 = [
        line for line in out2.getvalue().splitlines() if line.startswith("    ") or "más" in line
    ]
    assert lineas1 == lineas2


def test_escena_prosa_y_numero() -> None:
    # 6. Escena (TerminalCombat con una escena de rules/base/escenarios/):
    # «me cubro» devuelve Action(TOTAL_DEFENSE); el número sigue funcionando.
    ruleset = load_ruleset(Path("rules/base/rules.yaml"))
    esc = load_scenario(Path("rules/base/escenarios/aria_lobo.yaml"), ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]

    # Prosa "me cubro"
    inp1 = io.StringIO("me cubro\n")
    out1 = io.StringIO()
    tc1 = TerminalCombat(inp1, out1, interpreter=None)
    acc1 = tc1.choose(enc, aria)
    assert acc1.kind is ActionKind.TOTAL_DEFENSE

    # Número 1
    legales = list(enc.legal_actions(aria))
    inp2 = io.StringIO("1\n")
    out2 = io.StringIO()
    tc2 = TerminalCombat(inp2, out2, interpreter=None)
    acc2 = tc2.choose(enc, aria)
    assert acc2 == legales[0]


def test_recorder_y_script_con_prosa(tmp_path: Path) -> None:
    # 7. Recorder sobre una terminal que recibe prosa graba la línea
    # {"tick":…, "decidir":{…}} sin la prosa, y Script con esa línea
    # reproduce la misma decisión.
    pack = load_pack(ISLA_PACK)
    sim1 = Simulation(pack, seed=1312)
    sim1.set_player(AgentId("elor_d1"))
    grabacion = tmp_path / "guion_prosa.jsonl"

    inp = io.StringIO("me echo a dormir aquí mismo\nsalir\n")
    out = io.StringIO()
    term = Terminal(sim1, inp, out, provider=None, interpreter=None)

    with grabacion.open("w", encoding="utf-8") as f:
        rec = Recorder(term, f)
        play(sim1, rec, 1, term)

    lineas = grabacion.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    dato = json.loads(lineas[0])
    assert "prosa" not in dato
    assert dato["decidir"]["accion"] == "dormir_al_raso"

    script = Script(lineas)
    sim2 = Simulation(pack, seed=1312)
    sim2.set_player(AgentId("elor_d1"))
    res2 = play(sim2, script, 1, None)
    assert res2.ticks == 1
    busy = sim2.state.agents[AgentId("elor_d1")].busy
    assert isinstance(busy, PerformingAction)
    assert busy.action == ActionId("dormir_al_raso")
