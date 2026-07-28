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

from agora.engine.ontology import NeedId, TasteSpec, TraitId
from agora.engine.pack import ContentPack


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
