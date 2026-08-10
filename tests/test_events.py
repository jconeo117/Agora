"""Tests del registro de eventos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agora.engine.events import EventKind, EventLog, EventoDesalojadoError
from agora.engine.ontology import ActionId, AgentId, PlaceId

ALFA = AgentId("alfa")
BETA = AgentId("beta")
NODO = PlaceId("nodo")


def test_seq_is_monotonic_from_zero() -> None:
    """`seq` es la clave con la que la memoria referenciará recuerdos: no puede
    saltar ni reutilizarse."""
    log = EventLog()
    events = [log.emit(tick=t, kind=EventKind.ACTION_STARTED, actor=ALFA) for t in range(3)]
    assert [e.seq for e in events] == [0, 1, 2]
    assert len(log) == 3


def test_encounter_is_remembered_by_both_participants() -> None:
    """El sujeto de un encuentro también lo vivió. Si solo se indexa al actor,
    en F1 uno de los dos NPCs recordaría el encuentro y el otro no."""
    log = EventLog()
    log.emit(tick=1, kind=EventKind.ENCOUNTER, actor=ALFA, subject=BETA, place=NODO)

    assert len(log.by_actor(ALFA)) == 1
    assert len(log.by_actor(BETA)) == 1


def test_place_index_collects_everything_that_happened_there() -> None:
    log = EventLog()
    log.emit(tick=1, kind=EventKind.ACTION_STARTED, actor=ALFA, place=NODO)
    log.emit(tick=2, kind=EventKind.ACTION_COMPLETED, actor=BETA, place=NODO)
    log.emit(tick=3, kind=EventKind.ACTION_STARTED, actor=ALFA, place=PlaceId("otro"))

    assert [e.seq for e in log.by_place(NODO)] == [0, 1]


def test_since_returns_only_recent_ticks() -> None:
    log = EventLog()
    for tick in (1, 1, 2, 3, 3):
        log.emit(tick=tick, kind=EventKind.ACTION_STARTED, actor=ALFA)

    assert [e.tick for e in log.since(3)] == [3, 3]
    assert [e.tick for e in log.since(2)] == [2, 3, 3]
    assert len(log.since(0)) == 5


def test_events_are_immutable() -> None:
    log = EventLog()
    event = log.emit(tick=1, kind=EventKind.ACTION_STARTED, actor=ALFA)
    try:
        event.tick = 99  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("el pasado no debería poder reescribirse")


def test_the_tally_matches_walking_the_log() -> None:
    """Mientras no haya ventana, contar al emitir y contar recorriendo tienen
    que dar lo mismo. Es lo que hace creíble al recuento cuando ya no se pueda
    comprobar así."""
    log = EventLog()
    log.emit(tick=1, kind=EventKind.ACTION_COMPLETED, actor=ALFA, action=ActionId("comer"))
    log.emit(tick=1, kind=EventKind.ACTION_COMPLETED, actor=ALFA, action=ActionId("comer"))
    log.emit(tick=2, kind=EventKind.ACTION_COMPLETED, actor=BETA, action=ActionId("comer"))
    log.emit(tick=2, kind=EventKind.ACTION_ABORTED, actor=BETA)
    log.emit(tick=3, kind=EventKind.TRAVEL_STARTED, actor=ALFA, data={"ticks": 4})
    log.emit(tick=4, kind=EventKind.TRAVEL_STARTED, actor=ALFA, data={"ticks": 6})

    recuento = log.recuento
    assert recuento.por_tipo[EventKind.ACTION_COMPLETED] == len(
        log.of_kind(EventKind.ACTION_COMPLETED)
    )
    assert recuento.por_tipo[EventKind.ACTION_ABORTED] == 1
    assert recuento.por_agente_accion[ALFA][ActionId("comer")] == 2
    assert recuento.por_agente_accion[BETA][ActionId("comer")] == 1
    assert recuento.ticks_de_viaje == 10


# --- la ventana --------------------------------------------------------------


def con_ventana(ticks: int, cuantos: int) -> EventLog:
    """Un log con ventana y `cuantos` eventos, uno por tick."""
    log = EventLog(window=ticks)
    for tick in range(cuantos):
        log.emit(tick=tick, kind=EventKind.ACTION_STARTED, actor=ALFA, place=NODO)
    return log


def test_the_window_discards_the_old() -> None:
    log = con_ventana(ticks=100, cuantos=20_000)
    assert log.emitidos == 20_000
    assert len(log) < 20_000
    assert log.desalojados == log.emitidos - len(log)


def test_seq_survives_the_window() -> None:
    """`seq` es la clave con la que F1 referenciará recuerdos. Si al desalojar
    se reiniciara la numeración, dos eventos distintos compartirían clave."""
    log = con_ventana(ticks=100, cuantos=20_000)
    ultimo = log.emit(tick=20_000, kind=EventKind.ACTION_STARTED, actor=ALFA)
    assert ultimo.seq == 20_000
    assert [e.seq for e in log] == list(range(log.desalojados, log.emitidos))


def test_asking_for_an_evicted_event_explodes() -> None:
    """La trampa que hacía peligrosa la ventana.

    `self._events[seq]` tras descartar la cabeza devolvía OTRO evento, en
    silencio. Vale mil veces más un error ruidoso.
    """
    log = con_ventana(ticks=100, cuantos=20_000)
    assert log.desalojados > 0
    with pytest.raises(EventoDesalojadoError):
        log[0]
    assert log[log.emitidos - 1].seq == log.emitidos - 1


def test_the_indexes_shrink_too() -> None:
    """Los índices guardan `seq`, no eventos. Sin podarlos la memoria seguiría
    creciendo aunque los eventos se fueran, y la ventana no serviría de nada."""
    log = con_ventana(ticks=100, cuantos=20_000)
    assert len(log.by_actor(ALFA)) == len(log)
    assert len(log.by_place(NODO)) == len(log)


def test_the_tally_ignores_the_window() -> None:
    """Lo que hace honesta a la ventana: los totales siguen siendo los de la
    corrida entera. Si no, el resumen mentiría en vez de fallar."""
    log = con_ventana(ticks=100, cuantos=20_000)
    assert log.recuento.por_tipo[EventKind.ACTION_STARTED] == 20_000
    assert len(log.of_kind(EventKind.ACTION_STARTED)) == len(log)  # el log, no


def test_without_a_window_nothing_changes() -> None:
    """Sin `window` no se desaloja nada, por largo que sea. Es el modo de una
    corrida de calibración, donde se quiere el log entero."""
    log = EventLog()
    for tick in range(20_000):
        log.emit(tick=tick, kind=EventKind.ACTION_STARTED, actor=ALFA)
    assert len(log) == log.emitidos == 20_000
    assert log.desalojados == 0
    assert log[0].seq == 0


# --- el vertido ---------------------------------------------------------------


def test_the_sink_gets_everything_the_window_throws_away(tmp_path: Path) -> None:
    """Lo que hace inocua a la ventana: descartar en memoria no es perder.

    Sin esto, acotar la memoria costaría historia. Con esto, el fichero lleva la
    corrida entera y en memoria solo vive lo reciente.
    """
    destino = tmp_path / "corrida.jsonl"
    with destino.open("w", encoding="utf-8") as fichero:
        log = EventLog(window=100, sink=fichero)
        for tick in range(20_000):
            log.emit(tick=tick, kind=EventKind.ACTION_STARTED, actor=ALFA)

    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 20_000 == log.emitidos
    assert len(log) < 20_000
    assert json.loads(lineas[0])["seq"] == 0
    assert json.loads(lineas[-1])["seq"] == 19_999


def test_the_sink_matches_what_the_dump_would_have_written(tmp_path: Path) -> None:
    """Verter según ocurre y volcar al final tienen que dar el mismo fichero."""
    destino = tmp_path / "corrida.jsonl"
    with destino.open("w", encoding="utf-8") as fichero:
        vertido = EventLog(sink=fichero)
        volcado = EventLog()
        for tick in range(50):
            for log in (vertido, volcado):
                log.emit(tick=tick, kind=EventKind.ENCOUNTER, actor=ALFA,
                         subject=BETA, place=NODO, data={"n": tick})

    assert destino.read_text(encoding="utf-8").splitlines() == list(volcado.to_jsonl())


def test_jsonl_is_stable_for_determinism_diffs() -> None:
    log = EventLog()
    log.emit(tick=1, kind=EventKind.ACTION_STARTED, actor=ALFA, data={"score": 0.5})
    lines = list(log.to_jsonl())
    assert len(lines) == 1
    assert '"seq":0' in lines[0]
    assert '"score":0.5' in lines[0]
