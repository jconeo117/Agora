"""Tests del registro de eventos."""

from __future__ import annotations

from agora.engine.events import EventKind, EventLog
from agora.engine.ontology import AgentId, PlaceId

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


def test_jsonl_is_stable_for_determinism_diffs() -> None:
    log = EventLog()
    log.emit(tick=1, kind=EventKind.ACTION_STARTED, actor=ALFA, data={"score": 0.5})
    lines = list(log.to_jsonl())
    assert len(lines) == 1
    assert '"seq":0' in lines[0]
    assert '"score":0.5' in lines[0]
