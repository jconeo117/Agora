"""Tests de la memoria episódica.

El log ya guardaba todo lo que pasó. Lo que aquí se comprueba es la diferencia
entre un registro y una memoria: **el olvido y la importancia**. Un archivo
perpetuo donde todo pesa igual no produce biografía, y sin biografía dos agentes
con la misma ficha siguen siendo el mismo agente.

Tres afirmaciones del diseño se prueban explícitamente porque cada una se tomó
contra una alternativa más simple que estaba mal:

- el recuerdo **sobrevive a la ventana del log** (no es un puntero)
- se olvida **por valor, no por antigüedad** (o se olvida justo lo importante)
- la relevancia **multiplica**, no suma (o el trauma contamina toda pregunta)
"""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from agora.engine.events import Event, EventKind, EventLog, EventoDesalojadoError
from agora.engine.memory import Cue, MemoriaEpisodica, Recuerdo, importancia_de
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, SituationId
from agora.engine.outcome import learn
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
ACT = ActionId("act")
OTRA = ActionId("otra")

PESOS: dict[str, float] = {
    "peso_urgencia": 1.0,
    "peso_sorpresa": 1.0,
    "peso_testigos": 0.5,
    "escala": 1.0,
}


def evento(seq: int, tick: int = 0, **kw: Any) -> Event:
    return Event(seq=seq, tick=tick, kind=EventKind.ACTION_COMPLETED, actor=AG1, **kw)


def recuerdo(seq: int, tick: int = 0, importancia: float = 0.5, **kw: Any) -> Recuerdo:
    return Recuerdo(
        seq=seq, tick=tick, kind=EventKind.ACTION_COMPLETED, importancia=importancia, **kw
    )


# --- el recuerdo como dato ---------------------------------------------------


def test_valor_fades_like_a_bond() -> None:
    """Misma curva que `Bond.regard_at`, y a propósito la misma: dos mecanismos
    que dicen medir el paso del tiempo no pueden medirlo distinto."""
    r = recuerdo(seq=0, tick=10, importancia=1.0)
    assert r.valor(tick=10, fade=0.9) == pytest.approx(1.0)
    assert r.valor(tick=13, fade=0.9) == pytest.approx(0.729)


def test_fade_of_one_never_forgets() -> None:
    assert recuerdo(seq=0, tick=0, importancia=1.0).valor(tick=10**6, fade=1.0) == 1.0


def test_a_memory_from_the_future_does_not_grow() -> None:
    """El `max(0, ...)` del exponente. Sin él, un recuerdo posterior al tick que
    se pregunta valdría MÁS que su importancia."""
    assert recuerdo(seq=0, tick=50, importancia=1.0).valor(tick=10, fade=0.5) == 1.0


# --- el cue ------------------------------------------------------------------


def test_cue_counts_matches() -> None:
    r = recuerdo(seq=0, place=P1, action=ACT, about=AG2)
    assert Cue(place=P1).relevance(r) == 1
    assert Cue(place=P1, action=ACT).relevance(r) == 2
    assert Cue(place=P1, action=ACT, about=AG2).relevance(r) == 3


def test_cue_that_does_not_match_is_zero() -> None:
    r = recuerdo(seq=0, place=P1)
    assert Cue(place=P2).relevance(r) == 0
    assert Cue(action=ACT).relevance(r) == 0


def test_empty_cue_is_not_a_match_of_zero() -> None:
    """Un cue vacío significa "lo más saliente que tengas", no "nada casa"."""
    assert Cue().vacio is True
    assert Cue(place=P1).vacio is False


# --- la regla de importancia -------------------------------------------------


def test_importance_grows_with_urgency() -> None:
    poca = importancia_de(0.1, 0.0, 0, **PESOS)
    mucha = importancia_de(0.9, 0.0, 0, **PESOS)
    assert mucha > poca > 0.0


def test_importance_grows_with_surprise() -> None:
    poca = importancia_de(0.0, 0.1, 0, **PESOS)
    mucha = importancia_de(0.0, 0.9, 0, **PESOS)
    assert mucha > poca > 0.0


def test_surprise_is_absolute() -> None:
    """Marca igual que algo salga mucho mejor de lo previsto que mucho peor. El
    signo es cosa del arrepentimiento y se guarda aparte."""
    assert importancia_de(0.0, 0.5, 0, **PESOS) == importancia_de(0.0, -0.5, 0, **PESOS)


def test_witnesses_saturate() -> None:
    """La diferencia entre solo y acompañado es enorme; la que va de cuatro a
    cinco personas no existe."""
    salto = importancia_de(0.0, 0.0, 1, **PESOS) - importancia_de(0.0, 0.0, 0, **PESOS)
    meseta = importancia_de(0.0, 0.0, 5, **PESOS) - importancia_de(0.0, 0.0, 4, **PESOS)
    assert salto > meseta > 0.0


def test_importance_is_bounded() -> None:
    """Acotada a [0, 1) por la misma curva que la compañía y el aprecio. Sin el
    techo, `memory_capacity` significaría cosas distintas en cada pack."""
    assert 0.0 <= importancia_de(1.0, 1000.0, 1000, **PESOS) < 1.0


def test_nothing_at_all_marks_nothing() -> None:
    assert importancia_de(0.0, 0.0, 0, **PESOS) == 0.0


# --- el almacén --------------------------------------------------------------


def test_capacity_zero_is_off() -> None:
    """Apagada por defecto, como `bond_rate` y `sighting_horizon`: estrenar el
    mecanismo no puede mover ningún contrato ya medido."""
    m = MemoriaEpisodica(capacidad=0)
    assert m.remember(AG1, evento(0), 0.9) is None
    assert len(m) == 0


def test_the_unremarkable_is_not_stored() -> None:
    """Se descarta en el sitio. Sin el umbral, la capacidad se llena de rutina y
    el olvido tiene que hacer el trabajo que debió hacer esto."""
    m = MemoriaEpisodica(capacidad=10)
    assert m.remember(AG1, evento(0), 0.0) is None
    assert len(m) == 0


def test_forgetting_drops_the_least_valuable_not_the_oldest() -> None:
    """**La afirmación central del olvido.** Con FIFO, el día que te rompieron el
    brazo queda enterrado por doscientas cenas."""
    m = MemoriaEpisodica(capacidad=2, fade=1.0)
    m.remember(AG1, evento(0, tick=0), 0.9)  # viejo pero intenso
    m.remember(AG1, evento(1, tick=10), 0.1)  # reciente y trivial
    m.remember(AG1, evento(2, tick=20), 0.5)  # desborda

    quedan = {r.seq for r in m.de(AG1)}
    assert quedan == {0, 2}, "sobrevive lo intenso, se va lo trivial"


def test_fade_can_make_the_old_lose_anyway() -> None:
    """El desdibujado es lo que impide que un recuerdo intenso bloquee la
    capacidad para siempre: con el tiempo suficiente, pierde igual."""
    m = MemoriaEpisodica(capacidad=2, fade=0.5)
    m.remember(AG1, evento(0, tick=0), 0.9)
    m.remember(AG1, evento(1, tick=30), 0.4)
    m.remember(AG1, evento(2, tick=30), 0.5)

    assert {r.seq for r in m.de(AG1)} == {1, 2}


def test_memory_is_owner_scoped() -> None:
    """El bug de omnisciencia, imposible por construcción: no hay forma de
    consultar memoria sin decir de quién es."""
    m = MemoriaEpisodica(capacidad=10)
    m.remember(AG1, evento(0), 0.9)
    assert m.recall(AG2, Cue(), limit=10) == ()
    assert m.de(AG2) == ()


def test_the_subject_of_a_memory_is_the_other_one() -> None:
    """Desde dentro del recuerdo, `subject` no es el sujeto de nada: es de quién
    va. Para el dueño, el otro es siempre el otro."""
    m = MemoriaEpisodica(capacidad=10)
    encuentro = Event(seq=0, tick=0, kind=EventKind.ENCOUNTER, actor=AG1, subject=AG2)

    mio = m.remember(AG1, encuentro, 0.5)
    suyo = m.remember(AG2, encuentro, 0.5)
    assert mio is not None and mio.about == AG2
    assert suyo is not None and suyo.about == AG1


# --- recuperar ---------------------------------------------------------------


def test_what_is_not_relevant_does_not_come_up() -> None:
    m = MemoriaEpisodica(capacidad=10)
    m.remember(AG1, evento(0, place=P1), 0.9)
    assert m.recall(AG1, Cue(place=P2), limit=5) == ()


def test_relevance_multiplies_it_does_not_add() -> None:
    """**La segunda afirmación central.** Con suma, el trauma más intenso de la
    biografía saldría en respuesta a cualquier pregunta."""
    m = MemoriaEpisodica(capacidad=10, fade=1.0)
    m.remember(AG1, evento(0, tick=0, place=P2), 0.99)  # intensísimo, ajeno
    m.remember(AG1, evento(1, tick=0, place=P1), 0.10)  # tibio, pertinente

    salen = m.recall(AG1, Cue(place=P1), limit=5)
    assert [r.seq for r in salen] == [1]


def test_more_matches_outrank_more_intensity() -> None:
    """A igual pertinencia manda la intensidad; a distinta pertinencia manda la
    pertinencia. Es lo que hace que un cue preciso sirva de algo."""
    m = MemoriaEpisodica(capacidad=10, fade=1.0)
    m.remember(AG1, evento(0, tick=0, place=P1), 0.60)  # casa 1
    m.remember(AG1, evento(1, tick=0, place=P1, action=ACT), 0.40)  # casa 2

    salen = m.recall(AG1, Cue(place=P1, action=ACT), limit=5)
    assert [r.seq for r in salen] == [1, 0]


def test_an_empty_cue_returns_the_most_salient() -> None:
    """Lo que querrá el narrador de F5 para abrir una escena."""
    m = MemoriaEpisodica(capacidad=10, fade=1.0)
    m.remember(AG1, evento(0, tick=0), 0.2)
    m.remember(AG1, evento(1, tick=0), 0.8)
    assert [r.seq for r in m.recall(AG1, Cue(), limit=1)] == [1]


def test_recall_respects_the_limit() -> None:
    m = MemoriaEpisodica(capacidad=10)
    for i in range(5):
        m.remember(AG1, evento(i), 0.5)
    assert len(m.recall(AG1, Cue(), limit=2)) == 2
    assert m.recall(AG1, Cue(), limit=0) == ()


def test_recall_is_total_and_stable() -> None:
    """Dos recuerdos con el mismo peso se ordenan por `seq`, que es único. Sin
    el desempate, dos procesos con la misma semilla podrían divergir."""
    m = MemoriaEpisodica(capacidad=10, fade=1.0)
    m.remember(AG1, evento(7, tick=0), 0.5)
    m.remember(AG1, evento(3, tick=0), 0.5)
    assert [r.seq for r in m.recall(AG1, Cue(), limit=5)] == [7, 3]


# --- el recuerdo sobrevive al log --------------------------------------------


def test_a_memory_outlives_the_log_window() -> None:
    """**La tercera afirmación central, y la que hundió la firma del puerto.**

    Con ventana, el evento se desaloja y `log[seq]` revienta. Si el recuerdo
    fuera un id, la memoria episódica se vaciaría sola cada semana simulada.
    """
    log = EventLog(window=5)
    m = MemoriaEpisodica(capacidad=10)

    viejo = log.emit(tick=0, kind=EventKind.NEED_CRITICAL, actor=AG1, place=P1)
    m.remember(AG1, viejo, 0.9)

    # Desborda el lote de purga para forzar el desalojo.
    for i in range(5000):
        log.emit(tick=100 + i, kind=EventKind.ACTION_COMPLETED, actor=AG2)

    with pytest.raises(EventoDesalojadoError):
        log[viejo.seq]

    guardado = m.recall(AG1, Cue(place=P1), limit=1)
    assert len(guardado) == 1
    assert guardado[0].seq == viejo.seq
    assert guardado[0].place == P1


# --- integración con el mundo ------------------------------------------------


def memory_pack(**overrides: Any) -> ContentPack:
    """Un mundo mínimo con memoria encendida y una necesidad que aprieta."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {
                "id": "n1",
                "label": "n1",
                "decay_per_tick": 0.02,
                "initial": 0.5,
                "urgency_exponent": 2.0,
            }
        ],
        "actions": [
            {
                "id": "act",
                "label": "act",
                "duration_ticks": 2,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.3},
                "effects_per_company": {"n1": 0.3},
            },
            {"id": "otra", "label": "otra", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "ag2", "home": "p2", "start_at": "p2"},
        ],
        "tuning": {
            "learning_rate": 0.2,
            "memory_capacity": 20,
            "memory_scale": 0.5,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def test_a_run_leaves_memories() -> None:
    sim = Simulation(memory_pack(), seed=7)
    sim.run(200)
    assert len(sim.state.memoria) > 0


def test_capacity_is_never_exceeded() -> None:
    sim = Simulation(memory_pack(**{"tuning": {"memory_capacity": 5}}), seed=7)
    sim.run(400)
    for owner in sim.state.memoria.duenyos():
        assert len(sim.state.memoria.de(owner)) <= 5


def test_memory_off_leaves_nothing() -> None:
    """El contrato de los cuatro packs ya medidos depende de esto."""
    sim = Simulation(memory_pack(**{"tuning": {"memory_capacity": 0}}), seed=7)
    sim.run(200)
    assert len(sim.state.memoria) == 0


def test_same_seed_same_memories() -> None:
    """El determinismo alcanza también a la biografía. Sin esto, reproducir un
    fallo del día cinco deja de ser posible en cuanto la memoria decida algo."""
    uno = Simulation(memory_pack(), seed=11)
    otro = Simulation(memory_pack(), seed=11)
    uno.run(150)
    otro.run(150)

    for owner in uno.state.memoria.duenyos():
        assert uno.state.memoria.de(owner) == otro.state.memoria.de(owner)


def test_memories_survive_a_save(tmp_path: Path) -> None:
    """La deuda que dejó escrita `persistence.py`: al reanudar, el mundo era el
    mismo pero *nadie recordaba cómo llegó ahí*."""
    pack = memory_pack()
    sim = Simulation(pack, seed=3)
    sim.run(200)
    antes = {o: sim.state.memoria.de(o) for o in sim.state.memoria.duenyos()}
    assert antes, "el test no prueba nada si no se recordó nada"

    destino = tmp_path / "partida.json"
    sim.save(destino)
    vuelto = Simulation.resume(destino, pack)

    despues = {o: vuelto.state.memoria.de(o) for o in vuelto.state.memoria.duenyos()}
    assert despues == antes


def test_an_older_save_loads_as_someone_who_remembers_nothing(tmp_path: Path) -> None:
    """Un guardado sin el campo se lee entero. Rechazarlo invalidaría todas las
    partidas existentes por un campo que solo añade."""
    import json

    pack = memory_pack()
    sim = Simulation(pack, seed=3)
    sim.run(100)
    destino = tmp_path / "vieja.json"
    sim.save(destino)

    datos = json.loads(destino.read_text(encoding="utf-8"))
    for agente in datos["agents"]:
        del agente["memorias"]
    destino.write_text(json.dumps(datos), encoding="utf-8")

    vuelto = Simulation.resume(destino, pack)
    assert len(vuelto.state.memoria) == 0


def test_a_deleted_place_does_not_erase_the_memory(tmp_path: Path) -> None:
    """Aquí la reconciliación va al revés que en el resto del módulo: a un lugar
    borrado no lo indexa nadie dentro de un recuerdo, así que dejar caer el
    recuerdo entero costaría biografía sin ganar nada."""
    import json

    pack = memory_pack()
    sim = Simulation(pack, seed=3)
    sim.run(200)
    destino = tmp_path / "partida.json"
    sim.save(destino)

    datos = json.loads(destino.read_text(encoding="utf-8"))
    tocados = 0
    for agente in datos["agents"]:
        for fila in agente["memorias"]:
            fila[3] = "lugar_que_ya_no_existe"
            tocados += 1
    assert tocados > 0
    destino.write_text(json.dumps(datos), encoding="utf-8")

    vuelto = Simulation.resume(destino, pack)
    assert len(vuelto.state.memoria) == tocados
    for owner in vuelto.state.memoria.duenyos():
        assert all(r.place is None for r in vuelto.state.memoria.de(owner))


# --- la sorpresa que `learn` ya calculaba ------------------------------------


def test_learn_reports_the_prediction_error() -> None:
    """Ese número se calculaba desde F1.5 y se tiraba."""
    pack = memory_pack()
    action = pack.action_by_id[ACT]
    n1 = NeedId("n1")

    gain: dict[NeedId, float] = {}
    cost: dict[NeedId, float] = {}
    # Recibe la mitad de lo prometido sobre una creencia de 1.0: salió PEOR.
    sorpresa = learn(gain, cost, action, {n1: 0.15}, {n1: 0.0}, rate=0.5)
    assert sorpresa == pytest.approx(-0.5)


def test_better_than_expected_is_positive() -> None:
    """El signo se lee siempre igual: positivo es mejor de lo que creía."""
    pack = memory_pack()
    n1 = NeedId("n1")
    sorpresa = learn({}, {}, pack.action_by_id[ACT], {n1: 0.45}, {n1: 0.0}, rate=0.5)
    assert sorpresa == pytest.approx(0.5)


def test_the_cost_side_has_its_sign_normalised() -> None:
    """**La trampa del módulo.** En la vía de los costes, `realized` sale de
    `-recibido/gasto`, así que gastar de más da un error positivo — y gastar de
    más es peor. Sin normalizar, la mitad de los arrepentimientos serían
    alegrías."""
    caro = ContentPack.model_validate(
        {
            **{
                k: v
                for k, v in memory_pack().model_dump(mode="json").items()
                if k not in {"actions", "tuning"}
            },
            "tuning": {"learning_rate": 0.2},
            "actions": [
                {
                    "id": "act",
                    "label": "act",
                    "duration_ticks": 1,
                    "costs": {"n1": 1.0},
                    "effects": {"n1": -0.2},
                },
                {"id": "otra", "label": "otra", "duration_ticks": 1},
            ],
        }
    )
    n1 = NeedId("n1")
    # Prometía costar 0.2 y costó 0.4: el doble de caro, y eso es PEOR.
    sorpresa = learn({}, {}, caro.action_by_id[ACT], {n1: -0.4}, {n1: 1.0}, rate=0.5)
    assert sorpresa < 0.0


def test_no_learning_no_surprise() -> None:
    pack = memory_pack()
    assert learn({}, {}, pack.action_by_id[ACT], {}, {NeedId("n1"): 0.0}, rate=0.0) == 0.0


# --- el arrepentimiento ------------------------------------------------------


def guardar(m: MemoriaEpisodica, seq: int, valencia: float, **kw: Any) -> None:
    m.remember(AG1, evento(seq, **kw), 0.8, valencia)


def test_a_memory_without_a_sign_is_not_a_regret() -> None:
    """0.0 es lo normal: algo que pasó, ni bueno ni malo."""
    m = MemoriaEpisodica(capacidad=10)
    guardar(m, 0, 0.0, action=ACT)
    assert m.rencor(AG1, tick=0, escala=1.0) == {}


def test_a_bad_outcome_leaves_regret_against_that_action() -> None:
    m = MemoriaEpisodica(capacidad=10)
    guardar(m, 0, -0.9, action=ACT)
    r = m.rencor(AG1, tick=0, escala=1.0)
    assert r[ACT] > 0.0
    assert OTRA not in r


def test_joy_leaves_no_regret() -> None:
    """Solo cuenta lo negativo. Lo que salió mejor de lo esperado ya subió
    `gain_beliefs` y desde ahí empuja el beneficio: sumarlo aquí sería contar
    dos veces el mismo suceso."""
    m = MemoriaEpisodica(capacidad=10)
    guardar(m, 0, 0.9, action=ACT)
    assert m.rencor(AG1, tick=0, escala=1.0) == {}


def test_regret_accumulates_over_repeated_burns() -> None:
    m = MemoriaEpisodica(capacidad=10)
    guardar(m, 0, -0.5, action=ACT)
    una = m.rencor(AG1, tick=0, escala=1.0)[ACT]
    guardar(m, 1, -0.5, action=ACT)
    dos = m.rencor(AG1, tick=0, escala=1.0)[ACT]
    assert dos > una


def test_regret_is_bounded() -> None:
    """Acotado a [0, 1), que es lo que convierte `regret_weight` en el tope que
    impide el veto."""
    m = MemoriaEpisodica(capacidad=200)
    for i in range(200):
        guardar(m, i, -1.0, action=ACT)
    assert 0.0 < m.rencor(AG1, tick=0, escala=1.0)[ACT] < 1.0


def test_regret_fades_with_time() -> None:
    """Se cura por el tiempo, no por la repetición. Es justo lo contrario que
    `cost_beliefs`, que se cura promediando."""
    m = MemoriaEpisodica(capacidad=10, fade=0.99)
    guardar(m, 0, -0.9, tick=0, action=ACT)
    fresco = m.rencor(AG1, tick=0, escala=1.0)[ACT]
    viejo = m.rencor(AG1, tick=300, escala=1.0)[ACT]
    assert viejo < fresco


def test_a_regret_without_an_action_blames_nobody() -> None:
    """Una meta fallada y un hundimiento no llevan `action`: repartir la culpa
    entre lo que se hiciera mientras tanto sería inventar una atribución que
    nadie puede sostener."""
    m = MemoriaEpisodica(capacidad=10)
    m.remember(
        AG1,
        Event(seq=0, tick=0, kind=EventKind.GOAL_FAILED, actor=AG1, place=P1),
        0.9,
        -1.0,
    )
    assert m.rencor(AG1, tick=0, escala=1.0) == {}


def test_regret_is_owner_scoped_too() -> None:
    m = MemoriaEpisodica(capacidad=10)
    guardar(m, 0, -0.9, action=ACT)
    assert m.rencor(AG2, tick=0, escala=1.0) == {}


# --- el arrepentimiento cambia lo que se decide ------------------------------


def escarmentado_pack(**overrides: Any) -> ContentPack:
    """Dos acciones intercambiables en el mismo sitio.

    La simetría es lo que aísla el efecto: si un agente prefiere una de las dos,
    no puede ser por la distancia ni por lo que rinde.
    """
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {
                "id": "n1",
                "label": "n1",
                "decay_per_tick": 0.02,
                "initial": 0.5,
                "urgency_exponent": 2.0,
            }
        ],
        "actions": [
            {
                "id": "act",
                "label": "act",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.3},
            },
            {
                "id": "otra",
                "label": "otra",
                "duration_ticks": 1,
                "requires_affordance": "aff",
                "satisfies": {"n1": 1.0},
                "effects": {"n1": 0.3},
            },
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [{"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {}}],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        # La red de seguridad que el pack exige. No satisface nada, así que vale
        # ~0 y no compite: lo que se mide sigue siendo la elección entre las dos
        # que sí sirven. Y es justo lo que hace honesto al test del veto — si el
        # escarmiento vetara, el agente se refugiaría aquí y se dejaría morir.
        "tuning": {
            "memory_capacity": 20,
            "memory_scale": 1.0,
            "regret_weight": 2.0,
            "regret_scale": 0.5,
            "candidate_pool": 1,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def utilidad_de(world: Any, agent: Any, accion: ActionId) -> float:
    from agora.agents.decide import candidates

    return next(c.utility for c in candidates(world, agent) if c.action == accion)


def test_regret_makes_the_burnt_option_worse() -> None:
    """**La afirmación del frente.** Dos acciones idénticas dejan de serlo en
    cuanto una de ellas salió mal una vez."""
    sim = Simulation(escarmentado_pack(), seed=5)
    agent = sim.state.agents[AG1]

    antes_act = utilidad_de(sim.state, agent, ACT)
    antes_otra = utilidad_de(sim.state, agent, OTRA)
    assert antes_act == pytest.approx(antes_otra), "sin biografía son la misma acción"

    sim.state.memoria.remember(
        AG1, evento(0, tick=0, action=ACT, place=P1), 0.9, valencia=-0.9
    )

    assert utilidad_de(sim.state, agent, ACT) < antes_act
    assert utilidad_de(sim.state, agent, OTRA) == pytest.approx(antes_otra)


def test_regret_weight_zero_changes_nothing() -> None:
    """Apagado por defecto: estrenar el mecanismo no puede mover un contrato."""
    sim = Simulation(escarmentado_pack(**{"tuning": {"memory_capacity": 20}}), seed=5)
    agent = sim.state.agents[AG1]
    antes = utilidad_de(sim.state, agent, ACT)

    sim.state.memoria.remember(
        AG1, evento(0, tick=0, action=ACT, place=P1), 0.9, valencia=-1.0
    )
    assert utilidad_de(sim.state, agent, ACT) == pytest.approx(antes)


def solo_una_accion(**tuning: Any) -> ContentPack:
    base = {"memory_capacity": 20, "memory_scale": 1.0, "regret_scale": 0.5,
            "candidate_pool": 1}
    return escarmentado_pack(
        **{
            "actions": [
                {
                    "id": "act",
                    "label": "act",
                    "duration_ticks": 1,
                    "requires_affordance": "aff",
                    "satisfies": {"n1": 1.0},
                    "effects": {"n1": 0.3},
                },
                {"id": "nada", "label": "nada", "duration_ticks": 1},
            ],
            "tuning": {**base, **tuning},
        }
    )


def escarmentar(sim: Simulation, cuantos: int = 20) -> None:
    for i in range(cuantos):
        sim.state.memoria.remember(
            AG1, evento(i, tick=0, action=ACT, place=P1), 0.9, valencia=-1.0
        )


def test_desperation_beats_trauma() -> None:
    """**Lo que impide el veto, y no es lo que parecía.**

    El tope del rencor NO basta: lo que salva es que el beneficio crece con la
    urgencia y el escarmiento es fijo. Con la única acción útil del mundo
    escarmentada al máximo, el agente vuelve a ella cuando le hace falta.
    """
    sim = Simulation(solo_una_accion(regret_weight=0.5), seed=5)
    escarmentar(sim)
    sim.run(200)
    assert sim.log.recuento.por_agente_accion[AG1][ACT] > 0
    assert sim.state.agents[AG1].needs[NeedId("n1")] > 0.0


def test_too_much_weight_does_veto_and_that_is_the_calibration_limit() -> None:
    """El otro lado de lo mismo, y por qué `regret_weight` tiene una restricción
    dura. Por encima del beneficio máximo alcanzable el escarmiento gana siempre,
    ni la desesperación lo levanta, y el agente prefiere hundirse.

    Se prueba para que el límite quede escrito en algo que se ejecuta, no solo
    en un docstring que nadie relee.
    """
    sim = Simulation(solo_una_accion(regret_weight=2.0), seed=5)
    escarmentar(sim)
    sim.run(200)
    hechas = sim.log.recuento.por_agente_accion.get(AG1)
    assert hechas is None or hechas[ACT] == 0


# --- el miedo a lugares ------------------------------------------------------


TORMENTA = SituationId("tormenta")


def sufrir(m: MemoriaEpisodica, seq: int, **kw: Any) -> None:
    """Un recuerdo de algo que te PASÓ: sin acción, con lugar y con culpable."""
    m.remember(
        AG1,
        Event(seq=seq, tick=kw.pop("tick", 0), kind=EventKind.NEED_CRITICAL,
              actor=AG1, place=kw.pop("place", P1)),
        0.8,
        kw.pop("valencia", -0.9),
        kw.pop("culpable", TORMENTA),
    )


def test_a_crisis_nobody_caused_teaches_no_fear() -> None:
    """**La línea por la que este frente se abandonó una vez.**

    Un `NEED_CRITICAL` se dispara donde uno esté de pie, y el hambre cruza su
    umbral donde uno pasa más tiempo: su cama. Medido en la ciudad sobre 180
    días, los cuatro sitios con más recuerdos malos eran dormitorios y aulas.
    Sin `culpable`, este mecanismo enseña a temer tu propia casa.
    """
    m = MemoriaEpisodica(capacidad=10)
    sufrir(m, 0, culpable=None)
    assert m.miedo(AG1, tick=0, escala=1.0) == {}


def test_a_crisis_the_world_caused_does_teach_fear() -> None:
    m = MemoriaEpisodica(capacidad=10)
    sufrir(m, 0)
    assert m.miedo(AG1, tick=0, escala=1.0)[P1] > 0.0


def test_fear_and_regret_split_the_memory() -> None:
    """Los dos índices parten la memoria y no la comparten: un recuerdo es o algo
    que hiciste o algo que te pasó. Así no se cuenta dos veces el mismo suceso."""
    m = MemoriaEpisodica(capacidad=10)
    # Algo que hizo, y le salió mal, en P1.
    m.remember(AG1, evento(0, place=P1, action=ACT), 0.8, -0.9, TORMENTA)
    assert m.rencor(AG1, tick=0, escala=1.0), "debería pesar como escarmiento"
    assert m.miedo(AG1, tick=0, escala=1.0) == {}, "y no además como miedo"


def test_a_good_memory_leaves_no_fear() -> None:
    m = MemoriaEpisodica(capacidad=10)
    sufrir(m, 0, valencia=0.9)
    assert m.miedo(AG1, tick=0, escala=1.0) == {}


def test_fear_is_per_place() -> None:
    m = MemoriaEpisodica(capacidad=10)
    sufrir(m, 0, place=P1)
    temido = m.miedo(AG1, tick=0, escala=1.0)
    assert P1 in temido
    assert P2 not in temido


def test_fear_accumulates_and_is_bounded() -> None:
    m = MemoriaEpisodica(capacidad=200)
    sufrir(m, 0)
    una = m.miedo(AG1, tick=0, escala=1.0)[P1]
    for i in range(1, 100):
        sufrir(m, i)
    muchas = m.miedo(AG1, tick=0, escala=1.0)[P1]
    assert una < muchas < 1.0


def test_fear_fades() -> None:
    m = MemoriaEpisodica(capacidad=10, fade=0.99)
    sufrir(m, 0, tick=0)
    assert m.miedo(AG1, tick=300, escala=1.0)[P1] < m.miedo(AG1, tick=0, escala=1.0)[P1]


def test_fear_is_owner_scoped() -> None:
    m = MemoriaEpisodica(capacidad=10)
    sufrir(m, 0)
    assert m.miedo(AG2, tick=0, escala=1.0) == {}


# --- el miedo cambia a dónde se va -------------------------------------------


def temeroso_pack(**overrides: Any) -> ContentPack:
    """Dos sitios intercambiables. La simetría aísla el efecto: si alguien
    prefiere uno, no puede ser por la distancia ni por lo que rinde allí."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.02, "initial": 0.5,
             "urgency_exponent": 2.0}
        ],
        "actions": [
            {"id": "act", "label": "act", "duration_ticks": 1,
             "requires_affordance": "aff", "satisfies": {"n1": 1.0},
             "effects": {"n1": 0.3}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["aff"], "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["aff"], "neighbors": {"p1": 1}},
        ],
        "agents": [{"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"}],
        "tuning": {
            "memory_capacity": 20, "memory_scale": 1.0,
            "fear_weight": 0.5, "fear_scale": 0.5, "candidate_pool": 1,
        },
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def utilidad_en(world: Any, agent: Any, lugar: PlaceId) -> float:
    from agora.agents.decide import candidates

    return next(c.utility for c in candidates(world, agent) if c.place == lugar)


def test_fear_makes_a_place_less_appealing() -> None:
    sim = Simulation(temeroso_pack(), seed=5)
    agent = sim.state.agents[AG1]
    antes = utilidad_en(sim.state, agent, P2)

    sim.state.memoria.remember(
        AG1,
        Event(seq=0, tick=0, kind=EventKind.NEED_CRITICAL, actor=AG1, place=P2),
        0.9, -0.9, TORMENTA,
    )
    assert utilidad_en(sim.state, agent, P2) < antes


def test_fear_weight_zero_changes_nothing() -> None:
    sim = Simulation(temeroso_pack(**{"tuning": {"memory_capacity": 20}}), seed=5)
    agent = sim.state.agents[AG1]
    antes = utilidad_en(sim.state, agent, P2)

    sim.state.memoria.remember(
        AG1,
        Event(seq=0, tick=0, kind=EventKind.NEED_CRITICAL, actor=AG1, place=P2),
        0.9, -1.0, TORMENTA,
    )
    assert utilidad_en(sim.state, agent, P2) == pytest.approx(antes)


def test_fear_moves_you_elsewhere_it_does_not_stop_you() -> None:
    """**La conducta que ninguna otra perilla sabe expresar.** Quien teme la
    plaza no deja de socializar: socializa en otro sitio. Una aversión a la
    acción no puede hacer eso — mataría la actividad, no la reubicaría.
    """
    sim = Simulation(temeroso_pack(), seed=5)
    for i in range(8):
        sim.state.memoria.remember(
            AG1,
            Event(seq=i, tick=0, kind=EventKind.NEED_CRITICAL, actor=AG1, place=P1),
            0.9, -1.0, TORMENTA,
        )
    sim.run(300)

    # Sigue haciendo lo suyo...
    assert sim.log.recuento.por_agente_accion[AG1][ACT] > 0
    # ...pero se ha mudado.
    sitios = Counter(e.place for e in sim.log if e.place is not None)
    assert sitios[P2] > sitios[P1]


def test_two_identical_agents_with_different_pasts_diverge() -> None:
    """La prueba que el plan exige: *dos agentes con la misma ficha y distinta
    biografía tienen que decidir distinto*. Si no, el mecanismo es decorado."""
    pack = escarmentado_pack(
        **{
            "agents": [
                {"id": "ag1", "label": "ag1", "home": "p1", "start_at": "p1"},
                {"id": "ag2", "label": "ag2", "home": "p1", "start_at": "p1"},
            ]
        }
    )
    sim = Simulation(pack, seed=5)
    # Misma ficha, misma semilla, mismo sitio. Solo a uno le salió mal.
    for i in range(6):
        sim.state.memoria.remember(
            AG1, evento(i, tick=0, action=ACT, place=P1), 0.9, valencia=-1.0
        )
    sim.run(300)

    perfil = sim.log.recuento.por_agente_accion
    assert perfil[AG1][ACT] < perfil[AG2][ACT], "el escarmentado evita lo que le dolió"
