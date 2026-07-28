"""Aleatoriedad reproducible y derivable por clave.

Un único generador consumido en orden es la forma obvia de sembrar una
simulación, y es la que impide simular el mundo por partes: su posición depende
de todo lo que se sorteó antes, así que no se puede avanzar la región B sin
haber avanzado la A, ni saltarse el tiempo que un agente pasó dormido.

Aquí cada sorteo sale de un flujo derivado de una clave:

    world.rng.stream("decide", agente, tick)

El resultado es **función pura de (semilla, clave)**. Dos consecuencias que
importan más adelante:

- Se puede avanzar cualquier parte del mundo sin haber avanzado el resto.
- Indexando la clave por tiempo ABSOLUTO (y no por intervalo transcurrido),
  ponerse al día de golpe desde t=100 hasta t=1000 da exactamente lo mismo que
  hacerlo en dos tramos. La historia no depende del itinerario del observador.

Nota de implementación que no es opcional: **no se usa `hash()`**. Python
aleatoriza el hash de las cadenas en cada proceso salvo que se fije
`PYTHONHASHSEED`, así que una simulación no sería reproducible entre
ejecuciones. `blake2b` es estable por definición.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

type KeyPart = str | int
"""Las claves son escalares planos a propósito: van a acabar en logs y en
mensajes de error, y tienen que ser legibles por un humano que depura."""

_SEPARATOR = "\x1f"
"""Separador de unidad ASCII. Evita que ("ab", "c") y ("a", "bc") colisionen,
que es el fallo silencioso clásico de concatenar claves."""


@dataclass(frozen=True, slots=True)
class RngSource:
    """Fábrica de generadores independientes a partir de una semilla."""

    seed: int

    def stream(self, *key: KeyPart) -> random.Random:
        """Un generador propio para esta clave.

        Llamarlo dos veces con la misma clave devuelve dos generadores que
        producen la misma secuencia. Claves distintas dan secuencias sin
        correlación aprovechable.

        Coste: un hash corto más la construcción de un `Random`, del orden de
        microsegundos. Frente a los ~100 us que cuesta una deliberación es
        ruido, y a cambio se puede sortear en cualquier orden.
        """
        material = _SEPARATOR.join([str(self.seed), *(str(part) for part in key)])
        digest = hashlib.blake2b(material.encode("utf-8"), digest_size=8).digest()
        return random.Random(int.from_bytes(digest, "big"))
