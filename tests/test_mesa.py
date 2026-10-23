"""Pruebas de la mesa (plan 18, §B).

Escena, hilos, dados y atajos.
"""

from __future__ import annotations

import io
from pathlib import Path

from agora.agents.decide import options
from agora.cognition.narrador import (
    Fact,
    Hilos,
    Kind,
    Moment,
    Narrator,
    Notable,
    Scene,
    Sighting,
    Table,
    briefing,
    fallback,
    scene_of,
    select,
)
from agora.engine.events import Event, EventKind
from agora.engine.ontology import (
    ActionId,
    AgentId,
    PlaceId,
    RelationId,
    SituationId,
    SituationSpec,
)
from agora.engine.pack import load_pack
from agora.engine.ports import Contest, Outcome, Resolution
from agora.engine.rng import RngSource
from agora.engine.state import Condicion, PerformingAction
from agora.engine.world import Simulation
from agora.play import Terminal, TerminalCombat, dice_line
from agora.rules.binding import load_binding
from agora.rules.encounter import Encounter
from agora.rules.policy import StylePolicy
from agora.rules.scene import load_scenario
from agora.rules.system import load_ruleset
from agora.rules.world_social import WorldSocial
from tests.test_reglas_tirada import Dados

ISLA_PACK = Path("packs/isla/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
ISLA_BINDING = Path("packs/isla/reglas/base.yaml")
ESCENARIO_LOBO = Path("rules/base/escenarios/aria_lobo.yaml")


# ==============================================================================
# B.1 — Escena
# ==============================================================================


def test_scene_of_orden_tope_y_modo() -> None:
    # 1. scene_of: orden §3.2 (involucrado > aprecio > herido > nombre, desempate por id);
    # tope 5 y others; full al cambiar de sitio, primera decisión o tras combate; breve si no.
    # Cubre M1 y M2.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    w = sim.state
    yo = AgentId("elor_d1")
    w.agents[yo].bonds.clear()
    w.agents[yo].relations.clear()
    w.agents[yo].at = PlaceId("cornucopia")

    for a in w.agents.values():
        if a.spec_id != yo:
            a.at = PlaceId("selva_1_0")
            a.bonds.clear()
            a.relations.clear()
            a.condiciones.clear()

    # 7 agentes en la cornucopia para verificar orden y tope 5:
    # - Vidan: involucrado (empieza por V, debe quedar primero por involucrado)
    # - Renna: apreciada (empieza por R, debe quedar segunda por relación/aprecio)
    # - Coka: herido (herida visible, debe quedar tercero por herido sobre sanos)
    # - Dandri: sano, nombre D (cuarto por nombre)
    # - Gara: sano, nombre G (quinto por nombre)
    # - Lobel y Naia: sanos (quedan fuera del tope 5, en others=2)
    siete = ["vidan_d1", "renna_d1", "coka_d1", "dandri_d1", "gara_d1", "lobel_d2", "naia_d2"]
    for aid in siete:
        w.agents[AgentId(aid)].at = PlaceId("cornucopia")

    w.agents[yo].relations[RelationId("del_distrito")] = {AgentId("renna_d1")}
    w.agents[AgentId("coka_d1")].condiciones.append(Condicion(situacion=SituationId("herida")))

    # Escena con Vidan involucrado
    s = scene_of(w, "elor_d1", Sighting("cornucopia"), frozenset({"vidan_d1"}), False, 0)

    # Orden exacto esperado: Vidan > Renna > Coka > Dandri > Gara
    nombres = [n.name for n in s.notables]
    assert nombres == ["Vidan", "Renna", "Coka", "Dandri", "Gara"], (
        "el orden debe ser involucrado > aprecio > herido > nombre"
    )
    assert s.others == 2

    # Desempate por id si dos agentes tienen el mismo nombre
    a1 = AgentId("naia_d2")
    a2 = AgentId("lobel_d2")
    for aid in siete:
        w.agents[AgentId(aid)].at = PlaceId("selva_1_0")
    w.agents[a1].at = PlaceId("cornucopia")
    w.agents[a2].at = PlaceId("cornucopia")
    w.censo[a1] = w.censo[a1].model_copy(update={"label": "Clon, del distrito 2"})
    w.censo[a2] = w.censo[a2].model_copy(update={"label": "Clon, del distrito 2"})
    w.agents[a2].busy = PerformingAction(action=ActionId("atacar"), ticks_remaining=1)
    s_clones = scene_of(w, "elor_d1", Sighting("cornucopia"), frozenset(), False, 0)
    assert len(s_clones.notables) == 2
    # lobel_d2 < naia_d2 alfabéticamente por id
    assert s_clones.notables[0].doing == "atacar"

    # Modos full vs breve:
    # Primera decisión (seen.place is None) -> full
    s_primera = scene_of(w, "elor_d1", Sighting(None), frozenset(), False, 0)
    assert s_primera.full is True

    # Cambia de sitio (seen.place != actual) -> full
    s_cambio = scene_of(w, "elor_d1", Sighting("selva_1_0"), frozenset(), False, 0)
    assert s_cambio.full is True

    # Tras combate (last_was_fight is True) -> full
    s_combate = scene_of(w, "elor_d1", Sighting("cornucopia"), frozenset(), True, 0)
    assert s_combate.full is True

    # Mismo sitio sin combate -> breve (full is False)
    s_breve = scene_of(w, "elor_d1", Sighting("cornucopia"), frozenset(), False, 0)
    assert s_breve.full is False


def test_situacion_visible_cuenta_como_herido() -> None:
    # 2. herida visible cuenta como herido; una situación no visible, no. Cubre M10.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    w = sim.state
    yo = AgentId("elor_d1")
    w.agents[yo].bonds.clear()
    w.agents[yo].relations.clear()
    w.agents[yo].at = PlaceId("cornucopia")

    # Registrar una situación con visible=False en el pack
    invis_id = SituationId("veneno_oculto")
    w.pack.situation_by_id[invis_id] = SituationSpec(
        id=invis_id,
        label="veneno oculto",
        personal=True,
        visible=False,
    )

    a_visible = AgentId("gara_d1")
    a_invis = AgentId("renna_d1")
    for a in w.agents.values():
        if a.spec_id != yo:
            a.at = PlaceId("selva_1_0")
            a.bonds.clear()
            a.relations.clear()
            a.condiciones.clear()

    w.agents[a_visible].at = PlaceId("cornucopia")
    w.agents[a_invis].at = PlaceId("cornucopia")

    # Gara tiene herida (visible: True en pack.yaml)
    w.agents[a_visible].condiciones.append(Condicion(situacion=SituationId("herida")))
    # Renna tiene situación no visible (visible: False)
    w.agents[a_invis].condiciones.append(Condicion(situacion=invis_id))

    s = scene_of(w, "elor_d1", Sighting("cornucopia"), frozenset(), False, 0)
    notables_por_nombre = {n.name: n for n in s.notables}
    assert notables_por_nombre["Gara"].wounded is True, "herida visible debe contar como herido"
    assert notables_por_nombre["Renna"].wounded is False, (
        "situación no visible no debe contar como herido"
    )


def test_briefing_con_escena() -> None:
    # 3. briefing con escena: sin «AQUÍ HAY», notables presentes, «HA PASADO» solo si elapsed >= 4.
    # Cubre M3.
    scene = Scene(
        full=True,
        notables=(
            Notable(name="Gara", wounded=True, doing="atacar"),
            Notable(name="Renna", wounded=False, doing="sin hacer nada"),
        ),
        others=2,
        elapsed=5,
    )
    m = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description="Un cuerno enorme",
        phase="tarde",
        present=("Gara", "Renna"),
        state=(),
        facts=(Fact(5, 1, "Renna te ataca", mine=True),),
        veils=(),
        question=None,
        knowledge=(),
        everyone=("Elor", "Gara", "Renna"),
        scene=scene,
    )

    txt = briefing(m)
    # Cubre M3: con escena NO se escribe «AQUÍ HAY»
    assert "AQUÍ HAY" not in txt
    assert "ESCENA AHORA (completa):" in txt
    assert "  - Gara: herido, atacar" in txt
    assert "  - Renna: sin hacer nada" in txt
    assert "  - y otros 2" in txt
    assert "HA PASADO: 5 cuartos de hora" in txt

    # Si elapsed < 4, no aparece HA PASADO:
    scene_poco = Scene(full=True, notables=scene.notables, others=0, elapsed=3)
    m_poco = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description=None,
        phase=None,
        present=(),
        state=(),
        facts=(),
        veils=(),
        question=None,
        knowledge=(),
        everyone=(),
        scene=scene_poco,
    )
    assert "HA PASADO:" not in briefing(m_poco)

    # Si elapsed >= 8, se expresa en horas
    scene_horas = Scene(full=True, notables=(), others=0, elapsed=8)
    m_horas = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description=None,
        phase=None,
        present=(),
        state=(),
        facts=(),
        veils=(),
        question=None,
        knowledge=(),
        everyone=(),
        scene=scene_horas,
    )
    txt_horas = briefing(m_horas)
    assert "HA PASADO: 2 horas" in txt_horas
    assert "  - nadie más" in txt_horas


def test_fallback_completa_y_breve_literal() -> None:
    # 4. fallback completa y breve literal.
    scene_full = Scene(
        full=True,
        notables=(
            Notable("Gara", True, "atacar"),
            Notable("Renna", False, "sin hacer nada"),
        ),
        others=3,
        elapsed=0,
    )
    m_full = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description="Un cuerno de metal junto al lago.",
        phase=None,
        present=(),
        state=(),
        facts=(Fact(5, 1, "alcanzas a Renna", mine=True),),
        veils=(),
        question=None,
        knowledge=(),
        everyone=(),
        scene=scene_full,
    )
    # Completa: hechos + Estás en {lugar}. {descripción} Aquí: {lista}.
    esperado_full = (
        "Alcanzas a Renna. Estás en la cornucopia. Un cuerno de metal junto al lago. "
        "Aquí: Gara (herido), Renna y otros 3."
    )
    assert fallback(m_full) == esperado_full

    # Breve: hechos + Sigues en {lugar}.
    scene_brief = Scene(full=False, notables=(), others=0, elapsed=0)
    m_brief = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description="Un cuerno de metal junto al lago.",
        phase=None,
        present=(),
        state=(),
        facts=(Fact(5, 1, "alcanzas a Renna", mine=True),),
        veils=(),
        question=None,
        knowledge=(),
        everyone=(),
        scene=scene_brief,
    )
    esperado_brief = "Alcanzas a Renna. Sigues en la cornucopia."
    assert fallback(m_brief) == esperado_brief

    # Completa sin nadie: Aquí: nadie más.
    scene_vacia = Scene(full=True, notables=(), others=0, elapsed=0)
    m_vacia = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="la cornucopia",
        description=None,
        phase=None,
        present=(),
        state=(),
        facts=(),
        veils=(),
        question=None,
        knowledge=(),
        everyone=(),
        scene=scene_vacia,
    )
    assert fallback(m_vacia) == "Estás en la cornucopia. Aquí: nadie más."


def test_narrator_world_produce_momento_siempre() -> None:
    # 5. Narrator.world produce momento siempre (incluso sin hechos).
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    narrator = Narrator((), Table())
    told = narrator.world(sim.state, events=(), player="elor_d1")
    assert told.text != "", "debe producir narración incluso sin eventos"
    assert "Estás en " in told.text or "Sigues en " in told.text
    assert narrator.last_tick == sim.state.tick
    assert narrator.seen.place == str(sim.state.agents[AgentId("elor_d1")].at)


# ==============================================================================
# B.3 — Hilos y dados
# ==============================================================================


def test_select_hilos_termina_desiste_sigue() -> None:
    # 1. Alguien empieza contra jugador en ventana y termina en siguiente:
    # «termina»; si desistió «desiste»; si sigue «sigue yendo a por ti». Cubre M4.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    world = sim.state
    yo = "elor_d1"
    here = str(world.agents[AgentId(yo)].at)

    hilos = Hilos()
    e_start = Event(
        kind=EventKind.ACTION_STARTED,
        tick=1,
        seq=1,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={"target": yo},
    )
    # Ventana 1: Renna empieza a atacar
    select(world, [e_start], yo, Sighting(here), Table(), hilos)
    assert "renna_d1" in hilos.pending

    # Caso A: en la siguiente ventana Renna completa la acción -> «termina»
    hilos_a = Hilos(pending=dict(hilos.pending))
    e_complete = Event(
        kind=EventKind.ACTION_COMPLETED,
        tick=2,
        seq=2,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={},
    )
    facts_a = select(world, [e_complete], yo, Sighting(here), Table(), hilos_a)
    assert any("Renna termina: atacar" in f.text for f in facts_a), (
        "debe contar «Renna termina: atacar»"
    )
    assert "renna_d1" not in hilos_a.pending

    # Caso B: en la siguiente ventana Renna aborta la acción -> «desiste»
    hilos_b = Hilos(pending=dict(hilos.pending))
    e_abort = Event(
        kind=EventKind.ACTION_ABORTED,
        tick=2,
        seq=2,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={},
    )
    facts_b = select(world, [e_abort], yo, Sighting(here), Table(), hilos_b)
    assert any("Renna desiste" in f.text for f in facts_b), "debe contar «Renna desiste»"
    assert "renna_d1" not in hilos_b.pending

    # Caso C: la acción sigue sin terminar -> «sigue yendo a por ti»
    hilos_c = Hilos(pending=dict(hilos.pending))
    facts_c = select(world, [], yo, Sighting(here), Table(), hilos_c)
    assert any("Renna sigue yendo a por ti" in f.text for f in facts_c), (
        "debe contar «Renna sigue yendo a por ti»"
    )
    assert "renna_d1" in hilos_c.pending


def test_select_termina_y_herida_un_solo_hecho() -> None:
    # 2. Termina y deja herida: un solo hecho. Cubre M5.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    world = sim.state
    yo = "elor_d1"
    here = str(world.agents[AgentId(yo)].at)

    hilos = Hilos()
    hilos.pending["renna_d1"] = ("atacar", "1")

    e_done = Event(
        kind=EventKind.ACTION_COMPLETED,
        tick=2,
        seq=1,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={},
    )
    e_wound = Event(
        kind=EventKind.SITUATION_BEGAN,
        tick=2,
        seq=2,
        actor=AgentId(yo),
        place=PlaceId(here),
        data={"situation": "herida", "por_quien": "renna_d1"},
    )

    facts = select(world, [e_done, e_wound], yo, Sighting(here), Table(), hilos)
    # Debe haber solo un hecho (la herida), no «termina» repetido
    assert len(facts) == 1
    assert "herida" in facts[0].text
    assert not any("termina" in f.text for f in facts)


def test_select_accion_dirigida_jugador_usa_my_target() -> None:
    # 3. Acción dirigida del jugador que empezó antes de la ventana se cuenta
    # con destinatario (my_target). Cubre M6.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    world = sim.state
    yo = "elor_d1"
    here = str(world.agents[AgentId(yo)].at)

    hilos = Hilos()
    # Ventana 1: Elor empieza a pactar (aliarse) con Gara
    e_start = Event(
        kind=EventKind.ACTION_STARTED,
        tick=1,
        seq=1,
        actor=AgentId(yo),
        place=PlaceId(here),
        action=ActionId("aliarse"),
        data={"target": "gara_d1"},
    )
    select(world, [e_start], yo, Sighting(here), Table(), hilos)
    assert hilos.my_target == "gara_d1"

    # Ventana 2: Elor completa la acción sin target en el evento
    e_done = Event(
        kind=EventKind.ACTION_COMPLETED,
        tick=2,
        seq=2,
        actor=AgentId(yo),
        place=PlaceId(here),
        action=ActionId("aliarse"),
        data={},
    )
    facts = select(world, [e_done], yo, Sighting(here), Table(), hilos)
    assert any("Gara" in f.text for f in facts), (
        "la narración debe incluir al destinatario guardado en my_target"
    )
    assert not any("terminas: aliarse" in f.text for f in facts)


def test_beat_copia_dados_resolution() -> None:
    # 4. Beat de ataque lleva dados de Resolution. Cubre M7.
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIO_LOBO, ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    enc._attack(lobo, aria, False, Dados(5, 4, 3, 2, 1, 1, 5, 4, 3, 2), StylePolicy(), True)

    beats_ataque = [b for b in enc.beats if b.kind == "atacar"]
    assert beats_ataque, "debe haber al menos un beat de ataque"
    b = beats_ataque[0]
    assert len(b.dice) > 0, "beat debe copiar los dados de la tirada"
    assert len(b.opposing_dice) > 0, "beat debe copiar los dados del rival"
    assert b.dice == (5, 4, 3, 2, 1)


def test_dice_line_cuatro_desenlaces_literal() -> None:
    # 5. dice_line literal con 4 resultados (falla, éxito con coste, éxito, crítico).
    # Falla
    l1 = dice_line(
        "Elor", "ataque", (5, 3, 2), "Iaga", "la defensa de", (6, 1, 4, 2), Outcome.FAILURE
    )
    esp1 = "🎲 Elor, ataque (3) contra la defensa de Iaga (4): [5 3 2] contra [6 1 4 2] → falla"
    assert l1 == esp1

    # Éxito con coste
    l2 = dice_line(
        "Elor", "ataque", (5, 3, 2), "Iaga", "la defensa de", (4, 2), Outcome.SUCCESS_AT_COST
    )
    esp2 = (
        "🎲 Elor, ataque (3) contra la defensa de Iaga (2): [5 3 2] contra [4 2] → éxito con coste"
    )
    assert l2 == esp2

    # Éxito (sin oponente)
    l3 = dice_line("Elor", "primeros auxilios", (5, 4), None, None, (), Outcome.SUCCESS)
    assert l3 == "🎲 Elor, primeros auxilios (2): [5 4] → éxito"

    # Crítico
    l4 = dice_line("Elor", "ataque", (6, 6), "Iaga", "la defensa de", (3,), Outcome.CRITICAL)
    assert l4 == "🎲 Elor, ataque (2) contra la defensa de Iaga (1): [6 6] contra [3] → crítico"


def test_mesa_yaml_dice_false_oculta_dados() -> None:
    # 6. mesa.yaml con dice: false oculta líneas de dados. Cubre M8.
    ruleset = load_ruleset(BASE_RULES)
    esc = load_scenario(ESCENARIO_LOBO, ruleset)
    enc = Encounter(esc, ruleset, RngSource(1312), "test")
    aria = enc.fighters["aria"]
    lobo = enc.fighters["lobo"]
    enc._attack(lobo, aria, False, Dados(5, 4, 3, 2, 1, 1, 5, 4, 3, 2), StylePolicy(), True)

    sim = Simulation(load_pack(ISLA_PACK), seed=1)

    # Con table.dice = True se muestran las líneas con 🎲
    out_con = io.StringIO()
    narrator_con = Narrator((), Table(dice=True))
    tc_con = TerminalCombat(io.StringIO(), out_con, narrator=narrator_con, world=lambda: sim.state)
    tc_con._novedades(enc, aria)
    assert "🎲" in out_con.getvalue()

    # Con table.dice = False se ocultan las líneas con 🎲 (Cubre M8)
    out_sin = io.StringIO()
    narrator_sin = Narrator((), Table(dice=False))
    tc_sin = TerminalCombat(io.StringIO(), out_sin, narrator=narrator_sin, world=lambda: sim.state)
    tc_sin._novedades(enc, aria)
    assert "🎲" not in out_sin.getvalue(), "dice: false debe ocultar todas las líneas con 🎲"


def test_world_social_deceive_devuelve_contest() -> None:
    # 7. WorldSocial.deceive devuelve Contest con «Porte» e «Instinto + Alerta».
    sim = Simulation(load_pack(ISLA_PACK), seed=3)
    ruleset = load_ruleset(BASE_RULES)
    binding = load_binding(ISLA_BINDING, sim.state.pack, ruleset)
    ws = WorldSocial(ruleset, binding)
    liar = AgentId("gara_d1")
    listener = AgentId("renna_d1")

    contest = ws.deceive(sim.state, liar, listener, "clave_test")
    assert contest is not None
    assert isinstance(contest, Contest)
    assert contest.actor_label == "Porte"
    assert contest.opposing_label == "Instinto + Alerta"
    assert isinstance(contest.resolution, Resolution)
    assert contest.resolution.outcome in (
        Outcome.FAILURE,
        Outcome.SUCCESS_AT_COST,
        Outcome.SUCCESS,
        Outcome.CRITICAL,
    )


# ==============================================================================
# B.4 — Terminal
# ==============================================================================


def test_terminal_atajos_y_numero_sin_lista() -> None:
    # 1. Escribir atajo lista solo sus opciones; número sin lista previa no elige nada. Cubre M9.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    while sim.state.tick < 7:
        sim.tick()
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    # Número sin lista previa no elige nada (devuelve None tras salir)
    t = Terminal(sim, io.StringIO("1\nsalir\n"), io.StringIO())
    assert t.choose(w, agent, opts) is None, "un número sin lista previa no debe elegir nada"

    # Escribir atajo lista solo sus opciones, y luego el número sí elige
    verbos = t._verbos(w, opts)
    primer_verbo = verbos[0]
    out = io.StringIO()
    t2 = Terminal(sim, io.StringIO(f"{primer_verbo}\n1\n"), out)
    elegida = t2.choose(w, agent, opts)
    assert elegida is not None
    assert w.pack.action_by_id[elegida.action].label == primer_verbo


def test_terminal_opciones_lista_menu_entero_agrupado() -> None:
    # 2. opciones lista menú entero agrupado.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    while sim.state.tick < 7:
        sim.tick()
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    out = io.StringIO()
    t = Terminal(sim, io.StringIO("opciones\nsalir\n"), out)
    t.choose(w, agent, opts)
    texto = out.getvalue()
    assert "1. " in texto
    assert len(t._mostrada) == len(t._vista(w, opts))


def test_terminal_que_haces_aparece_siempre() -> None:
    # 3. «¿Qué haces?» aparece siempre antes de leer.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    w = sim.state
    agent = next(iter(w.agents.values()))
    opts = tuple(options(w, agent))

    out = io.StringIO()
    t = Terminal(sim, io.StringIO("salir\n"), out)
    t.choose(w, agent, opts)
    texto = out.getvalue()
    assert "¿Qué haces?" in texto
    assert "  atajos:" in texto
