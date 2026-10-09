"""Daño y Vitalidad (unidad 08), en enteros.

El borrador pide que la lógica no use coma flotante, y no hace falta: el
multiplicador de cada paso de efecto es exactamente `pasos / 2`, así que basta
con multiplicar y dividir una vez, al final.
"""

from __future__ import annotations

from enum import StrEnum

from agora.engine.ports import Effect
from agora.rules.system import VitalitySpec


def damage(base: int, grade: int, effect: int, protection: int, piercing: int) -> int:
    """`(base + grado) * pasos // 2 - max(0, protección - perforación)`, y al
    menos 1 si el efecto no es nulo.

    Se redondea al multiplicar y la protección se resta después, que es como
    salen los ejemplos del borrador (§21.3, el oso: 7 // 2 = 3, menos 2, da 1).
    El mínimo de 1 es lo que hace que acertar siempre cuente: la protección
    frena, pero no vuelve a nadie intocable. Para eso está el tier.
    """
    if effect <= Effect.NONE:
        return 0
    return max(1, (base + grade) * effect // 2 - max(0, protection - piercing))


class VitalityBand(StrEnum):
    HEALTHY = "sano"
    WOUNDED = "herido"
    GRAVE = "grave"
    DOWN = "caído"


def vitality_band(current: int, maximum: int, spec: VitalitySpec) -> VitalityBand:
    """Se compara `current * 100` con `maximum * umbral`, sin dividir. Justo en
    el umbral se sigue en la banda de arriba: el borrador dice «50 % o más»."""
    if current <= 0:
        return VitalityBand.DOWN
    if current * 100 < maximum * spec.grave_below:
        return VitalityBand.GRAVE
    if current * 100 < maximum * spec.wounded_below:
        return VitalityBand.WOUNDED
    return VitalityBand.HEALTHY
