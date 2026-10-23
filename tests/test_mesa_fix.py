"""Tests para los arreglos de la mesa (plan 18-fix).

Verifica la sección §B del contrato 18-fix-mesa.md:
- B.1.1: atajos con «hablar» al final si hay gente presente, y sin gente no está.
- B.1.2: «hablar» lista a los presentes y un número abre conversación, «adiós» la cierra.
- B.1.3: «opciones» pagina en `page` entradas y «más» muestra las siguientes.
- B.1.4: los seis casos de cierre de hilos (§2.3) con Narrator en dos ventanas.
- B.1.5: fin de acción dirigida del jugador no es hecho; inicio sí; no dirigida sí al fin.
- B.1.6: cabecera (# ..., tick ...) aparece antes de la escena en la salida.
"""

from __future__ import annotations

import io
from pathlib import Path

from agora.agents.decide import options
from agora.cognition.narrador import Hilos, Narrator, Sighting, Table, select
from agora.engine.events import Event, EventKind
from agora.engine.ontology import ActionId, AgentId, PlaceId
from agora.engine.pack import load_pack
from agora.engine.world import Simulation
from agora.play import HABLAR, VERBOS, Terminal

ISLA_PACK = Path("packs/isla/pack.yaml")


def test_verbos_con_presentes_hablar_al_final_y_sin_presentes_no() -> None:
    # B.1.1: `_verbos` con gente presente: «hablar» es el último y hay como mucho
    # `VERBOS`; sin nadie, no está. Cubre M1.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    t = Terminal(sim, io.StringIO(), io.StringIO())

    # Con 24 personas presentes en pedestal_1
    presentes = t._presentes(w, agent)
    assert len(presentes) > 0, "debe haber agentes presentes"
    verbos = t._verbos(w, agent, opts)
    assert len(verbos) <= VERBOS, f"como mucho {VERBOS} verbos"
    assert verbos[-1] == HABLAR, f"el último verbo debe ser {HABLAR}"
    assert HABLAR in verbos

    # Sin nadie presente en el lugar
    agent.at = PlaceId("selva_1_0")
    assert len(t._presentes(w, agent)) == 0, "no debe haber nadie presente"
    opts_solo = tuple(options(w, agent))
    verbos_solo = t._verbos(w, agent, opts_solo)
    assert HABLAR not in verbos_solo, "sin nadie presente no debe estar «hablar»"
    assert len(verbos_solo) <= VERBOS


def test_hablar_solo_lista_presentes_y_numero_abre_conversacion() -> None:
    # B.1.2: `hablar` solo lista a los presentes; el número abre la conversación
    # con ese (proveedor léxico/respaldo, «adiós» la cierra).
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    out = io.StringIO()
    # Flujo: escribir «hablar», elegir «1», despedirse con «adiós», y «salir»
    t = Terminal(sim, io.StringIO("hablar\n1\nadiós\nsalir\n"), out)
    elegida = t.choose(w, agent, opts)
    assert elegida is None, "salir tras adiós no elige acción de juego"

    texto = out.getvalue()
    presentes = t._presentes(w, agent)
    assert len(presentes) > 0

    # «hablar» solo lista a los presentes numerados
    primer_presente = presentes[0]
    nombre_primero = w.censo[primer_presente.spec_id].label
    assert f"1. {nombre_primero} ({primer_presente.spec_id})" in texto
    assert str(agent.spec_id) not in [str(p.spec_id) for p in presentes]

    # El número 1 abrió la conversación con ese personaje
    assert f"hablas con {nombre_primero} («adiós» para terminar)" in texto


def test_opciones_pagina_y_mas_siguiente_pagina_con_seleccion() -> None:
    # B.1.3: `opciones` enseña `page` líneas numeradas y `más` las siguientes, con
    # números que siguen eligiendo lo que se ve. Cubre M2.
    sim = Simulation(load_pack(ISLA_PACK), seed=1)
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    # Caso A: opciones enseña solo `page` (12) líneas y deja el resto para «más»
    out_a = io.StringIO()
    t_a = Terminal(sim, io.StringIO("opciones\nsalir\n"), out_a, page=12)
    t_a.choose(w, agent, opts)
    assert len(t_a._mostrada) == 12, "debe mostrar solo la primera página de 12"
    assert len(t_a._resto) > 0, "deben quedar opciones en el resto"
    total_vista = len(t_a._vista(w, opts))
    assert len(t_a._mostrada) + len(t_a._resto) == total_vista

    # Un número fuera de la página vista (ej. 13) no se puede elegir todavía
    out_b = io.StringIO()
    t_b = Terminal(sim, io.StringIO("opciones\n13\nsalir\n"), out_b, page=12)
    elegida_invalida = t_b.choose(w, agent, opts)
    assert elegida_invalida is None, "el número 13 no es elegible en la primera página"

    # Caso B: «más» enseña la siguiente página y ahora el número 13 sí elige
    out_c = io.StringIO()
    t_c = Terminal(sim, io.StringIO("opciones\nmás\n13\n"), out_c, page=12)
    elegida_c = t_c.choose(w, agent, opts)
    assert elegida_c is not None, "tras «más», el número 13 debe poder elegirse"
    assert elegida_c == opts[t_c._mostrada[12]]
    assert len(t_c._mostrada) == 24


def test_cierre_hilos_seis_casos_dos_ventanas_narrator() -> None:
    # B.1.4: Los seis casos de §2.3, uno por uno, con eventos hechos a mano en dos
    # ventanas seguidas del mismo `Narrator`. Cubre M3, M4, M5.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    w = sim.state
    player = "elor_d1"
    actor = AgentId("renna_d1")
    here = PlaceId(str(w.agents[AgentId(player)].at))

    e_start = Event(
        seq=1, tick=1, kind=EventKind.ACTION_STARTED,
        actor=actor, place=here, action=ActionId("atacar"), data={"target": player},
    )
    e_done = Event(
        seq=2, tick=2, kind=EventKind.ACTION_COMPLETED,
        actor=actor, place=here, action=ActionId("atacar"), data={},
    )
    e_abort = Event(
        seq=2, tick=2, kind=EventKind.ACTION_ABORTED,
        actor=actor, place=here, action=ActionId("atacar"), data={},
    )
    e_wound = Event(
        seq=3, tick=2, kind=EventKind.SITUATION_BEGAN,
        actor=AgentId(player), place=here, action=None,
        data={"situation": "herida", "por_quien": str(actor)},
    )

    # 1. En esta ventana: empezó y terminó en la misma ventana -> solo el inicio
    nar1 = Narrator((), Table())
    told1 = nar1.world(w, [e_start, e_done], player)
    assert "Renna te ataca" in told1.text
    assert "termina" not in told1.text
    assert "sigue yendo a por ti" not in told1.text
    assert "desiste" not in told1.text

    # 2. En esta ventana: empezó y sigue en esta ventana -> solo el inicio (no «sigue»)
    nar2 = Narrator((), Table())
    told2 = nar2.world(w, [e_start], player)
    assert "Renna te ataca" in told2.text
    assert "sigue yendo a por ti" not in told2.text, "no debe decir sigue si empezó en esta ventana"

    # 3. En esta ventana: empezó y lo dejó -> inicio y «desiste»
    nar3 = Narrator((), Table())
    told3 = nar3.world(w, [e_start, e_abort], player)
    assert "Renna te ataca" in told3.text
    assert "Renna desiste" in told3.text

    # 4. Empezó antes (v1) y terminó sin herida (v2) -> forma at_you («Renna te ataca»)
    nar4 = Narrator((), Table())
    nar4.world(w, [e_start], player)
    told4 = nar4.world(w, [e_done], player)
    assert "Renna te ataca" in told4.text, "debe usar tell(at_you)"
    assert "termina" not in told4.text, "no debe decir termina: etiqueta"
    assert "sigue yendo a por ti" not in told4.text

    # 5. Empezó antes (v1) y terminó con herida tuya por él (v2) -> nada más (la herida)
    nar5 = Narrator((), Table())
    nar5.world(w, [e_start], player)
    told5 = nar5.world(w, [e_done, e_wound], player)
    assert "Empieza para ti: herida" in told5.text
    assert "Renna te ataca" not in told5.text, "con herida no se repite el ataque"
    assert "termina" not in told5.text

    # 6. Empezó antes (v1) y lo dejó (v2) -> «desiste»
    nar6 = Narrator((), Table())
    nar6.world(w, [e_start], player)
    told6 = nar6.world(w, [e_abort], player)
    assert "Renna desiste" in told6.text
    assert "Renna te ataca" not in told6.text

    # 7 (sigue antes): Empezó antes (v1) y sigue (v2) -> «sigue yendo a por ti»
    nar7 = Narrator((), Table())
    nar7.world(w, [e_start], player)
    told7 = nar7.world(w, [], player)
    assert "Renna sigue yendo a por ti" in told7.text


def test_accion_dirigida_jugador_inicio_si_fin_no_y_no_dirigida_si() -> None:
    # B.1.5: Una acción dirigida del jugador: su inicio es un hecho y su fin no;
    # una no dirigida sí se cuenta al terminar. Cubre M6.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    w = sim.state
    player = "elor_d1"
    target = "gara_d1"
    here = str(w.agents[AgentId(player)].at)

    # 1. Acción dirigida del jugador (aliarse): inicio sí es hecho, fin no
    e_dirigida_start = Event(
        seq=1, tick=1, kind=EventKind.ACTION_STARTED,
        actor=AgentId(player), place=PlaceId(here), action=ActionId("aliarse"),
        data={"target": target},
    )
    facts_start = select(w, [e_dirigida_start], player, Sighting(here), Table(), Hilos())
    assert len(facts_start) == 1, "el inicio de acción dirigida debe ser un hecho"
    assert "Gara" in facts_start[0].text
    assert facts_start[0].mine is True

    e_dirigida_done = Event(
        seq=2, tick=2, kind=EventKind.ACTION_COMPLETED,
        actor=AgentId(player), place=PlaceId(here), action=ActionId("aliarse"),
        data={},
    )
    facts_done = select(w, [e_dirigida_done], player, Sighting(here), Table(), Hilos())
    assert len(facts_done) == 0, "el fin de acción dirigida del jugador no debe ser un hecho"

    # 2. Acción no dirigida del jugador (beber): fin sí se cuenta al terminar
    e_no_dirigida_done = Event(
        seq=3, tick=2, kind=EventKind.ACTION_COMPLETED,
        actor=AgentId(player), place=PlaceId(here), action=ActionId("beber"),
        data={},
    )
    facts_no_dirigida = select(
        w, [e_no_dirigida_done], player, Sighting(here), Table(), Hilos(),
    )
    assert len(facts_no_dirigida) == 1, "el fin de acción no dirigida debe ser un hecho"
    assert "bebes" in facts_no_dirigida[0].text
    assert facts_no_dirigida[0].mine is True


def test_cabecera_aparece_antes_que_la_escena() -> None:
    # B.1.6: La cabecera aparece antes que el texto de la escena en la salida. Cubre M7.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    w = sim.state
    agent = w.agents[AgentId("elor_d1")]
    opts = tuple(options(w, agent))

    out = io.StringIO()
    t = Terminal(sim, io.StringIO("salir\n"), out, narrator=Narrator((), Table()))
    t.choose(w, agent, opts)
    texto = out.getvalue()

    cabecera = f"# {w.censo[agent.spec_id].label}, tick {w.tick}"
    assert cabecera in texto, "la cabecera debe estar en la salida"
    assert "Estás en " in texto or "Sigues en " in texto, "la escena debe estar en la salida"

    idx_cabecera = texto.index(cabecera)
    idx_escena = texto.index("Estás en ") if "Estás en " in texto else texto.index("Sigues en ")
    assert idx_cabecera < idx_escena, (
        f"la cabecera (pos {idx_cabecera}) debe aparecer antes que la escena (pos {idx_escena})"
    )
