"""Cómo la personalidad se convierte en números de decisión.

Separado de `decide.py` a propósito: componer la disposición y usarla son cosas
distintas y cambian por motivos distintos. Aquí se responde "quién es este
agente en números"; allí, "qué hace con ellos".

Todo lo de este módulo es **derivado**: se calcula a partir de rasgos y gustos,
y hay que recomponerlo cuando esos cambian. `AgentState` es el dueño de esa
sincronía.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from agora.engine.ontology import NeedId, TasteSpec, TemperamentKnob, TraitId
from agora.engine.pack import ContentPack

_MIN_TEMPERATURE = 1e-6
"""Suelo de la temperatura. Un valor metódico extremo es legítimo —equivale a
elegir siempre lo mejor— pero cero sería una división por cero en el softmax."""


def compose_need_weights(
    pack: ContentPack, traits: Mapping[TraitId, float]
) -> dict[NeedId, float]:
    """Cuánto le importa a este agente cada necesidad.

    La intensidad entra como exponente, no como interpolación:

        factor = multiplicador ** intensidad

    Con intensidad 0 el rasgo no hace nada (M**0 == 1) y con -1 invierte exacto
    (M**-1 == 1/M). La interpolación lineal daría factores negativos para
    multiplicadores mayores que 2, que no significan nada.

    Efecto secundario elegante: al ser potencias, componer rasgos es **sumar en
    espacio logarítmico**, y por eso componen limpiamente entre sí.

    Los rasgos se recorren **ordenados por id**. La multiplicación es
    conmutativa pero en coma flotante no es asociativa, así que sin un orden
    fijo dos corridas idénticas podrían diferir en el último bit según cómo
    quedara el diccionario. Cuesta nada y cierra esa puerta.
    """
    weights: dict[NeedId, float] = {need.id: need.base_weight for need in pack.needs}
    for trait_id in sorted(traits):
        trait = pack.trait_by_id[trait_id]
        intensity = traits[trait_id]
        for need_id, multiplier in trait.need_weight_multipliers.items():
            weights[need_id] *= multiplier**intensity
    return weights


@dataclass(frozen=True, slots=True)
class Temperament:
    """Cómo decide este agente, ya compuesto sobre los valores del mundo.

    Inmutable: es un valor derivado. Cuando un rasgo cambia se construye uno
    nuevo, no se parchea el viejo.
    """

    temperature: float
    loss_aversion: float
    critical_need_threshold: float
    travel_discount: float


def compose_temperament(pack: ContentPack, traits: Mapping[TraitId, float]) -> Temperament:
    """Combina el temperamento del mundo con el del agente.

    Composición multiplicativa: el pack dice cómo es el mundo, el rasgo cuánto
    se desvía esta persona. Un mundo donde viajar es caro y alguien que además
    odia salir son dos cosas que se acumulan.

    **Cada perilla tiene su propio rango válido**, y ahí está el trabajo real de
    esta función. Multiplicar sin acotar produce valores que no significan nada:

    - `travel_discount` por encima de 1 haría que la distancia AUMENTARA el
      atractivo — un agente que cuanto más lejos, más le apetece.
    - `critical_need_threshold` por encima de 1 dejaría a un agente en pánico
      permanente, incluso con las necesidades llenas.
    - `temperature` en 0 sería una división por cero en el softmax.

    `loss_aversion` no necesita techo: pesar el precio diez veces más de la
    cuenta describe a alguien paralizado por el gasto, que es un carácter
    válido. Y si el mundo lo puso a 0 (costes desactivados), ningún rasgo puede
    resucitarlo, que también es lo correcto.
    """
    factors: dict[TemperamentKnob, float] = dict.fromkeys(TemperamentKnob, 1.0)

    # Orden fijo por id: la multiplicación en coma flotante no es asociativa.
    for trait_id in sorted(traits):
        trait = pack.trait_by_id[trait_id]
        intensity = traits[trait_id]
        for knob, multiplier in trait.temperament_multipliers.items():
            factors[knob] *= multiplier**intensity

    tuning = pack.tuning
    return Temperament(
        temperature=max(
            _MIN_TEMPERATURE, tuning.temperature * factors[TemperamentKnob.TEMPERATURE]
        ),
        loss_aversion=tuning.loss_aversion * factors[TemperamentKnob.LOSS_AVERSION],
        critical_need_threshold=min(
            1.0,
            tuning.critical_need_threshold * factors[TemperamentKnob.CRITICAL_THRESHOLD],
        ),
        travel_discount=min(
            1.0, tuning.travel_discount * factors[TemperamentKnob.TRAVEL_DISCOUNT]
        ),
    )


def compose_tastes(tastes: Iterable[TasteSpec]) -> dict[str, float]:
    """Predilecciones y aversiones, colapsadas por objetivo.

    Clave `str` y no `ActionId`/`PlaceId`/`AgentId`: un gusto puede apuntar a
    cualquiera de los tres espacios, y `pack.py` ya garantizó que no colisionan
    entre sí. Aquí se comparan al nivel en el que la búsqueda ocurre de verdad.

    Dos gustos hacia el mismo objetivo se multiplican en vez de pisarse. Así una
    aversión heredada y una predilección aprendida se combinan en vez de que
    gane la última declarada.
    """
    result: dict[str, float] = {}
    for taste in tastes:
        key = str(taste.target)
        result[key] = result.get(key, 1.0) * taste.multiplier
    return result
