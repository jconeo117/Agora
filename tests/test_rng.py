"""Tests de la fuente de aleatoriedad derivable."""

from __future__ import annotations

from agora.engine.rng import RngSource


def draw(source: RngSource, *key: str | int, n: int = 5) -> list[float]:
    stream = source.stream(*key)
    return [stream.random() for _ in range(n)]


def test_same_key_gives_the_same_sequence() -> None:
    source = RngSource(42)
    assert draw(source, "decide", "ag1", 10) == draw(source, "decide", "ag1", 10)


def test_different_keys_diverge() -> None:
    source = RngSource(42)
    assert draw(source, "decide", "ag1", 10) != draw(source, "decide", "ag2", 10)
    assert draw(source, "decide", "ag1", 10) != draw(source, "decide", "ag1", 11)
    assert draw(source, "decide", "ag1", 10) != draw(source, "dialogo", "ag1", 10)


def test_different_seeds_diverge() -> None:
    assert draw(RngSource(1), "decide", "ag1", 10) != draw(RngSource(2), "decide", "ag1", 10)


def test_key_parts_cannot_collide_by_concatenation() -> None:
    """("ab", "c") y ("a", "bc") concatenan igual. El separador lo impide, y es
    el fallo silencioso clásico de construir claves pegando cadenas."""
    source = RngSource(42)
    assert draw(source, "ab", "c") != draw(source, "a", "bc")


def test_order_of_consumption_does_not_matter() -> None:
    """La propiedad que justifica todo el módulo: sortear para el agente B sin
    haber sorteado antes para el A da el mismo resultado.

    Con un generador único consumido en orden, esto fallaría.
    """
    source = RngSource(7)

    en_orden = [draw(source, "decide", who, 5) for who in ("ag1", "ag2", "ag3")]
    salteado = [draw(source, "decide", who, 5) for who in ("ag3", "ag1", "ag2")]

    assert salteado[0] == en_orden[2]
    assert salteado[1] == en_orden[0]


def test_hashing_is_stable_across_processes() -> None:
    """Valor fijado a propósito.

    Si alguien cambia el algoritmo, el separador o el orden de la clave, todas
    las semillas guardadas dejan de reproducir sus corridas. Este test convierte
    ese cambio silencioso en un fallo ruidoso.

    Es también el guardián contra usar `hash()` de Python, que está aleatorizado
    por proceso y haría que este valor cambiara en cada ejecución.
    """
    assert RngSource(1312).stream("decide", "mira", 42).random() == 0.8769545171247954
