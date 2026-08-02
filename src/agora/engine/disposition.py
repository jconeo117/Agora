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


def urgency(value: float, exponent: float) -> float:
    """Cuánto apremia una necesidad, dado lo llena que está.

    La curva es el motivo de que los agentes no parezcan termostatos. Con
    exponente 1 todo compite linealmente y el agente atiende cinco cosas a
    medias; con exponente 2.5 una necesidad es casi irrelevante hasta que de
    pronto es tiránica, que es como se comporta el hambre de verdad.

    Vive aquí y no en `decide.py` porque no es deliberación: es "cuánto le
    importa esto a este agente ahora mismo", la misma familia que `compute_strain`
    y `compose_need_weights`. Y desde aquí la puede usar también `outcome.py`,
    que necesita valorar lo ocurrido con la misma vara con que se decidió — si
    fueran dos curvas distintas, el agente aprendería con un criterio que no es
    el suyo.
    """
    # `float(...)` explícito: para typeshed, `**` puede devolver un complejo
    # (base negativa, exponente fraccionario). El `max` ya lo impide aquí.
    return float(max(0.0, 1.0 - value) ** exponent)


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


def compute_strain(pack: ContentPack, needs: Mapping[NeedId, float]) -> float:
    """Desgaste cognitivo en [0, 1]. 0 entero, 1 al límite.

    Media ponderada de la urgencia de las necesidades que el pack marca como
    desgastantes. **Reutiliza la curva de urgencia a propósito**, en vez de
    añadir un parámetro nuevo: `urgency_exponent` ya dice cuán bruscamente esa
    necesidad empieza a doler, que es exactamente lo que hace falta aquí.

    Y no es un detalle cosmético. Con desgaste lineal, el barrio sano —
    necesidades en torno a 0.55 — daría un desgaste de 0.45: un mundo entero
    permanentemente medio roto, y el mecanismo perdería todo su recorrido. Con
    la curva convexa el mismo mundo da ~0.15, y el desgaste solo aparece cuando
    de verdad algo va mal.

    Devuelve 0.0 si el pack no marca ninguna necesidad como desgastante, lo que
    desactiva el mecanismo entero sin código condicional.
    """
    total = 0.0
    weights = 0.0
    for need in pack.needs:
        if need.strain_weight <= 0.0:
            continue
        pressure = urgency(needs[need.id], need.urgency_exponent)
        total += need.strain_weight * pressure
        weights += need.strain_weight
    return total / weights if weights else 0.0


def compose_temperament(
    pack: ContentPack, traits: Mapping[TraitId, float], strain: float = 0.0
) -> Temperament:
    """Combina el temperamento del mundo, el del agente y su estado actual.

    Tres capas multiplicativas sobre las mismas perillas:

        mundo (tuning)  *  rasgos ^ intensidad  *  desgaste ^ strain

    El pack dice cómo es el mundo, el rasgo cuánto se desvía esta persona, y el
    desgaste cómo está hoy. Un mundo donde viajar es caro, alguien que además
    odia salir, y encima agotado: tres cosas distintas que se acumulan.

    La capa de estado es la que produce los "días malos" sin tocar la
    personalidad. El mismo NPC decide distinto según cómo esté, y sigue siendo
    él — que es justo lo contrario de cambiarle los rasgos.

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

    for knob, multiplier in pack.tuning.strain_multipliers.items():
        factors[knob] *= multiplier**strain

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
