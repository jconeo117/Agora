"""Qué obtiene de verdad un agente, y qué aprende de la diferencia.

Simétrico a `disposition.py`: allí se responde "quién es este agente en
números", aquí "qué le pasó y qué concluye".

El problema que este módulo resuelve es previo al aprendizaje. Con `effects`
como constantes del pack, el mundo **no tiene sorpresas**: lo prometido y lo
recibido coinciden siempre, el error de predicción es cero por construcción, y
cualquier maquinaria de aprendizaje quedaría inerte. Hace falta primero que el
resultado dependa del contexto.

La fuente de varianza es la compañía. Charlar con una persona no da lo mismo que
charlar con cuatro, y entre decidir ir a la plaza y llegar, la gente se mueve. De
ahí sale el "fui al café y estaba vacío", y de ahí sale que haya algo que
aprender.
"""

from __future__ import annotations

from collections.abc import Mapping

from agora.engine.ontology import ActionSpec, NeedId


def company_saturation(company: int) -> float:
    """Rendimiento decreciente de la compañía, en [0, 1).

    Uno da la mitad del máximo, tres tres cuartos, una multitud nunca más que el
    tope. Sin saturar, una sala llena volvería cualquier efecto social absurdo.

    Vive aquí y no repetido en dos sitios porque la curva la usan el alivio
    pasivo de las necesidades y la escala de los efectos, y tienen que ser la
    misma o dos mecanismos que dicen medir lo mismo divergen.
    """
    crowd = max(0, company)
    return crowd / (crowd + 1) if crowd else 0.0


def contextual_effects(action: ActionSpec, company: int) -> dict[NeedId, float]:
    """Lo que la acción da REALMENTE, dadas las circunstancias.

    El pack declara un efecto base y, opcionalmente, cuánto añade la compañía.
    Una conversación con cuatro personas rinde más que con una, y eso es lo que
    hace que exista una diferencia entre lo esperado y lo obtenido.

    Sin `effects_per_company`, devuelve los efectos tal cual: una acción cuyo
    resultado no depende de nadie no gana nada por pasar por aquí.
    """
    if not action.effects_per_company:
        return dict(action.effects)

    bonus = company_saturation(company)
    result = dict(action.effects)
    for need_id, extra in action.effects_per_company.items():
        result[need_id] = result.get(need_id, 0.0) + extra * bonus
    return result


def learn(
    beliefs: dict[NeedId, float],
    action: ActionSpec,
    received: Mapping[NeedId, float],
    before: Mapping[NeedId, float],
    rate: float,
) -> None:
    """Corrige las expectativas con lo que acaba de pasar. Muta `beliefs`.

        creencia <- creencia + alfa * (recibido/prometido - creencia)

    La creencia es un **multiplicador sobre `satisfies`**, no un sustituto: el
    pack sigue diciendo de qué va la acción, y el agente aprende cuánto fiarse.
    Empieza en 1.0 (se fía del pack) y deriva con la experiencia.

    Dos cosas que NO se aprenden, y son las que hacen que el mecanismo enseñe la
    lección correcta:

    **No se aprende de lo que no cabía.** Si comes con el estómago casi lleno,
    el efecto se recorta por el techo de la necesidad y no porque la comida fuera
    mala. Aprender de ahí produciría agentes convencidos de que comer no sirve
    justo por haber comido bien. Se salta el caso.

    **No se aprende de lo que no se perseguía.** Trabajar sube el vínculo de
    rebote, pero el agente no fue a trabajar por eso, y su expectativa sobre esa
    necesidad no debería moverse por un efecto colateral. Solo se actualiza lo
    que aparece en `satisfies`.

    `rate` a 0 desactiva el aprendizaje sin código condicional en el motor.
    """
    if rate <= 0.0:
        return

    for need_id, promised in action.effects.items():
        if need_id not in action.satisfies or promised <= 0.0:
            continue

        room = 1.0 - before[need_id]
        if room < promised:
            continue  # el techo recortó; de esto no se aprende nada

        realized = received.get(need_id, 0.0) / promised
        current = beliefs.get(need_id, 1.0)
        beliefs[need_id] = current + rate * (realized - current)
