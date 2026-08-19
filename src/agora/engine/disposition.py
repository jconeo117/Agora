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

from agora.engine.ontology import GoalSpec, NeedId, TasteSpec, TemperamentKnob, TraitId
from agora.engine.pack import ContentPack

_MIN_TEMPERATURE = 1e-6
"""Suelo de la temperatura. Un valor metódico extremo es legítimo —equivale a
elegir siempre lo mejor— pero cero sería una división por cero en el softmax."""


def compose_need_weights(
    pack: ContentPack,
    traits: Mapping[TraitId, float],
    pursuing: Iterable[GoalSpec] = (),
) -> dict[NeedId, float]:
    """Cuánto le importa a este agente cada necesidad.

    Dos capas sobre el peso base del pack: **quién es** (rasgos) y **qué quiere
    ahora** (metas en curso). Las metas entran por el mismo dial a propósito —
    no hacía falta un término nuevo en la fórmula, porque "cuánto me importa
    esto" ya existía y una meta es exactamente eso, subido un rato.

    Que multiplique en vez de sumar tiene consecuencia: una meta sobre algo que
    ya te importaba aprieta más que sobre algo que te daba igual. Querer irse
    del pueblo pesa distinto en un avaro que en un manirroto, y sale gratis.

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

    # Ordenadas por id, como los rasgos y por lo mismo: la multiplicación en
    # coma flotante no es asociativa y dos metas sobre el mismo eje darían
    # resultados distintos según cómo quedara la tupla.
    for goal in sorted(pursuing, key=lambda g: g.id):
        weights[goal.need] *= goal.weight_multiplier
    return weights


def compose_gains(
    pack: ContentPack, traits: Mapping[TraitId, float]
) -> dict[NeedId, float]:
    """La APTITUD de este agente en cada eje. 1.0 = del montón.

    Misma mecánica que `compose_need_weights`, y devuelve todas las necesidades
    del pack por el mismo motivo: un dict incompleto obligaría a cada consumidor
    a inventarse un default y acabarían siendo distintos en dos sitios.

    Ojo con no confundirlo con el peso, porque son la misma forma y significan
    cosas opuestas:

        need_weight_multipliers  ->  cuánto le IMPORTA
        gain_multipliers         ->  cuánto le CUNDE

    Alguien puede darle mucha importancia al descanso y recuperarlo despacio, o
    tener mano para el arcano y que le traiga sin cuidado. Las dos combinaciones
    describen personas concretas, y con un solo canal ninguna sería expresable.
    """
    gains: dict[NeedId, float] = {need.id: 1.0 for need in pack.needs}
    for trait_id in sorted(traits):
        trait = pack.trait_by_id[trait_id]
        intensity = traits[trait_id]
        for need_id, multiplier in trait.gain_multipliers.items():
            gains[need_id] *= multiplier**intensity
    return gains


def compose_costs(
    pack: ContentPack, traits: Mapping[TraitId, float]
) -> dict[NeedId, float]:
    """El TEMPLE de este agente en cada eje. 1.0 = del montón.

    Espejo exacto de `compose_gains`, sobre el otro lado del intercambio: aquella
    dice cuánto le cunde lo que gana, esta cuánto le duele lo que gasta.

        gain_multipliers  ->  cuánto le CUNDE
        cost_multipliers  ->  cuánto le DUELE

    Y son independientes a propósito, porque las cuatro combinaciones describen
    criaturas distintas y con un solo canal ninguna sería expresable: el enano
    que almacena mucho y repone despacio (temple alto, aptitud baja), el humano
    del montón (los dos a 1.0), el que se repone en un suspiro pero se vacía a la
    primera (aptitud alta, temple bajo).

    Devuelve todas las necesidades del pack por el mismo motivo que sus hermanas:
    un dict incompleto obligaría a cada consumidor a inventarse un default y
    acabarían siendo distintos en dos sitios.
    """
    costs: dict[NeedId, float] = {need.id: 1.0 for need in pack.needs}
    for trait_id in sorted(traits):
        trait = pack.trait_by_id[trait_id]
        intensity = traits[trait_id]
        for need_id, multiplier in trait.cost_multipliers.items():
            costs[need_id] *= multiplier**intensity
    return costs


def compose_caps(
    pack: ContentPack, traits: Mapping[TraitId, float]
) -> dict[NeedId, float]:
    """EL TECHO de este agente en cada eje. Parte del `cap` que declara el pack.

    Es el unico de los canales que NO arranca en 1.0: arranca en lo que la
    necesidad diga que alcanza cualquiera, y los rasgos lo suben desde ahi. Un
    mundo sin `cap` declarado se comporta como siempre, porque el defecto es 1.0.

    Se recorta a 1.0 al final. Un don enorme no saca a nadie del rango en que
    viven las necesidades, solo le deja llegar al final de el.
    """
    caps: dict[NeedId, float] = {need.id: need.cap for need in pack.needs}
    for trait_id in sorted(traits):
        trait = pack.trait_by_id[trait_id]
        intensity = traits[trait_id]
        for need_id, multiplier in trait.cap_multipliers.items():
            caps[need_id] *= multiplier**intensity
    return {need_id: min(1.0, tope) for need_id, tope in caps.items()}


def compose_memory_fade(
    pack: ContentPack, traits: Mapping[TraitId, float], base: float
) -> float:
    """Cuánto le **dura** a este agente lo que recuerda. Séptimo canal.

    Nació de una petición que el motor no podía cumplir: *que el duelo no esté
    encasillado — uno lo supera en dos semanas y otro cambia de vida*. Con un
    `memory_fade` único en el pack eso era imposible por construcción; los 127
    olvidaban al mismo ritmo, así que la única diferencia posible entre dos
    duelos era cuánto pesaban al empezar, nunca cuánto duraban.

    **Y no se compone multiplicando.** Es el primer canal que no puede, y por
    aritmética, no por gusto: un fade es la fracción que sobrevive cada tick, así
    que `0.9997 * 2` da 1.9994 — que no significa *recuerda el doble* sino *no
    olvida jamás*, y encima se sale del rango válido. Lo que hay que duplicar es
    la **media vida**, y eso es un exponente:

        fade_efectivo = base ** (1 / multiplicador)

    Con multiplicador 2 el recuerdo tarda el doble en desdibujarse; con 0.5, la
    mitad. En 1.0 no pasa nada. Es la misma respuesta que ya dio el motor cuando
    la intensidad de un rasgo tuvo que poder neutralizar e invertir un canal:
    cuando el efecto vive en un exponente, la composición también.

    Se recorta a `(0, 1]`: nadie recuerda mejor que perfectamente.
    """
    if base >= 1.0:
        # Un mundo sin desdibujado no lo estrena por tener rasgos: `1.0 ** x` es
        # 1.0 para cualquier x, pero decirlo aquí ahorra la duda al leerlo.
        return 1.0
    factor = 1.0
    for trait_id in sorted(traits):
        multiplier = pack.trait_by_id[trait_id].memory_multipliers
        if multiplier != 1.0:
            factor *= multiplier ** traits[trait_id]
    if factor <= 0.0:
        return base
    return min(1.0, float(base ** (1.0 / factor)))


def compose_phase_shift(pack: ContentPack, traits: Mapping[TraitId, float]) -> int:
    """Cuánto adelanta o atrasa el reloj interno de este agente, en ticks.

    Se **suma**, no se multiplica, y es la única disposición que compone así.
    Tiene sentido: los pesos son escalas y se acumulan multiplicando, pero un
    desfase es una traslación y dos desfases se suman como se sumarían dos husos
    horarios.

    Redondea al final y no rasgo a rasgo. Con dos rasgos a media intensidad,
    redondear antes perdería los dos medios ticks por separado en vez de
    convertirlos en uno.
    """
    if not pack.clock.phases:
        return 0
    total = sum(
        pack.trait_by_id[trait_id].phase_shift * traits[trait_id]
        for trait_id in sorted(traits)
    )
    return round(total) % pack.clock.ticks_per_day


def urgency(value: float, exponent: float, cap: float = 1.0) -> float:
    """Cuánto apremia una necesidad, dado lo llena que está **para quien es**.

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

    **`cap` es el techo de ESTE agente en ESTE eje**, y sin él un tope sería una
    trampa en vez de un limite. Con techo 0.5, alguien que ya esta en 0.5 lo ha
    dado todo — pero medido contra 1.0 seguiria sintiendo la mitad del apremio, y
    se pasaria la vida entrenando algo que no puede mejorar. Normalizado, llegar a
    tu techo se siente como llenarse: la urgencia cae a cero y el agente se
    dedica a otra cosa.

    Por defecto vale 1.0, que es el mundo de siempre. Solo lo pasan los sitios
    que tienen delante al agente y por tanto saben cual es su techo.
    """
    # `float(...)` explícito: para typeshed, `**` puede devolver un complejo
    # (base negativa, exponente fraccionario). El `max` ya lo impide aquí.
    if cap <= 0.0:
        return 0.0
    return float(max(0.0, 1.0 - value / cap) ** exponent)


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
    companionship_weight: float


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
        # Sin techo, como `loss_aversion`: que a alguien le tire el bullicio el
        # triple describe a un juerguista, que es un caracter valido. Y si el
        # mundo lo puso a 0, ningun rasgo puede resucitarlo — un mundo donde la
        # gente no atrae no se vuelve gregario porque alguien sea sociable.
        companionship_weight=tuning.companionship_weight
        * factors[TemperamentKnob.COMPANIONSHIP],
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
