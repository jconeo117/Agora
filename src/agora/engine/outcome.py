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

from agora.engine.disposition import urgency
from agora.engine.ontology import ActionSpec, NeedId, NeedSpec


def signed_saturation(x: float, scale: float = 1.0) -> float:
    """La curva, a secas. Rendimiento decreciente firmado, en (-1, 1).

        saturación(x) = x / (|x| + escala)

    **Está firmada**, y el valor absoluto del denominador es lo que la hace
    simétrica en vez de aplastar el lado negativo. Que el resultado pueda ser
    negativo es lo que permite que una mala compañía haga daño en vez de
    simplemente no ayudar — un cuarto con alguien que no soportas es más
    solitario que un cuarto vacío.

    Es matemática pura y no sabe de qué se le pasa. Quien la usa le da sentido:
    `company_saturation` la aplica a la gente, `company_premium` la aplica a una
    cantidad de utilidad. **Son dos cosas distintas y por eso están separadas** —
    ver la nota en `company_saturation`.
    """
    return x / (abs(x) + scale)


def company_saturation(company: float, scale: float = 1.0) -> float:
    """Rendimiento decreciente de la COMPAÑÍA. `scale` = qué es una multitud aquí.

    Con `scale` a 1, uno da la mitad del máximo y tres tres cuartos. Ese era el
    único comportamiento posible hasta ahora, y se calibró para una aldea donde
    tres personas ya eran mucha gente. **Medido en la ciudad, la ocupación media
    es de 14.4**, y con la curva clavada en 1 eso da 0.933: todos los mecanismos
    sociales pegados a su techo, y las gradaciones que el pack escribe con
    cuidado —0.25 por compañía en una comida, 0.50 en una charla— dejan de
    discriminar porque el multiplicador es el mismo en ambos casos.

              personas    scale 1    scale 4    scale 8
                     2      0.667      0.333      0.200
                     5      0.833      0.556      0.385
                    14      0.933      0.778      0.636

    De ahí la perilla: **qué es "mucha gente" no es universal, es del mundo**. Un
    pueblo de diez y una ciudad de ciento veintisiete no pueden compartirla.

    Separada de `signed_saturation` a propósito. `company_premium` usa la misma
    curva para normalizar una cantidad de utilidad, que no es gente: si
    compartieran función, esta perilla se filtraría al aprecio en silencio y
    movería una calibración que costó una medición encontrar.

    Vive aquí y no repetida en tres sitios porque la curva la usan el alivio
    pasivo de las necesidades, la escala de los efectos y el atractivo de un
    plan acompañado. Tienen que ser la misma, o tres mecanismos que dicen medir
    lo mismo divergen.
    """
    return signed_saturation(company, scale)


def contextual_effects(
    action: ActionSpec, company: float, company_scale: float = 1.0
) -> dict[NeedId, float]:
    """Lo que la acción da REALMENTE, dadas las circunstancias.

    El pack declara un efecto base y, opcionalmente, cuánto añade la compañía.
    Una conversación con cuatro personas rinde más que con una, y eso es lo que
    hace que exista una diferencia entre lo esperado y lo obtenido.

    Sin `effects_per_company`, devuelve los efectos tal cual: una acción cuyo
    resultado no depende de nadie no gana nada por pasar por aquí.
    """
    if not action.effects_per_company:
        return dict(action.effects)

    bonus = company_saturation(company, company_scale)
    result = dict(action.effects)
    for need_id, extra in action.effects_per_company.items():
        result[need_id] = result.get(need_id, 0.0) + extra * bonus
    return result


def company_premium(
    action: ActionSpec,
    need_specs: Mapping[NeedId, NeedSpec],
    weights: Mapping[NeedId, float],
    before: Mapping[NeedId, float],
    company: float,
    scale: float,
    company_scale: float = 1.0,
) -> float:
    """Cuánto le aportó la compañía a ESTE agente, ya en escala de aprecio.

    El bruto es la diferencia entre lo que la acción dio acompañado y lo que
    habría dado a solas, pesada por lo que al agente le importa cada necesidad y
    por lo mucho que le apretaba en ese momento:

        bruto = Σ  peso * urgencia * effects_per_company * saturación(compañía)

    Los dos factores de delante son los que hacen que esto genere personalidad
    en vez de estadística de co-presencia. La misma conversación, con la misma
    gente, vale mucho para quien está muerto de soledad y casi nada para quien
    la tiene cubierta. De ahí sale que un agente sociable forme vínculos deprisa
    y uno reservado apenas los forme, sin una sola regla escrita para ello — y
    que quien te acompañó **cuando te hacía falta** pese más que quien te
    acompañó cuando te daba igual.

    Se mide con `before`, el estado ANTES de aplicar los efectos, por lo mismo
    que `learn`: lo que valió el rato lo decide la necesidad que traías, no la
    que te queda después de saciarla.

    Y luego se **normaliza**, que es la mitad del trabajo de esta función:

        premio = bruto / (|bruto| + scale)

    Sin normalizar, el bruto es una cantidad de utilidad en las unidades del
    pack —en el barrio salía del orden de 0.05— usada como objetivo de una
    variable acotada a [-1, 1]. Medido: el aprecio se estancaba en 0.001 y el
    mecanismo entero era inerte. Peor que inerte: `bond_weight` habría
    significado cosas distintas en cada ambientación, y eso rompe lo único que
    el motor no puede permitirse.

    La curva es la misma —`signed_saturation`— pero **no la misma función que la
    de la compañía**, y la distinción no es cosmética: aquí se satura una
    cantidad de UTILIDAD, allí se saturan PERSONAS. Compartir función haría que
    `company_scale`, que dice qué es una multitud, moviera de rebote la escala
    del aprecio. En silencio.

    `scale` se lee como "cuánto premio equivale a medio aprecio". Es un número de
    la escala del pack, así que vive en el pack. **Mídelo, no lo adivines**: pon
    el rate a lo que quieras, corre una semana y mira dónde se estancan los
    aprecios.

    Devuelve 0.0 para las acciones que no declaran `effects_per_company`. Estar
    en la misma sala mientras cada uno trabaja lo suyo no acerca a nadie, y eso
    es correcto: el pack declara qué actividades son compartidas de verdad.
    """
    if not action.effects_per_company or scale <= 0.0:
        return 0.0

    bonus = company_saturation(company, company_scale)
    total = 0.0
    for need_id, extra in action.effects_per_company.items():
        pressure = urgency(before[need_id], need_specs[need_id].urgency_exponent)
        total += weights[need_id] * pressure * extra * bonus
    return signed_saturation(total / scale)


def learn(
    gain_beliefs: dict[NeedId, float],
    cost_beliefs: dict[NeedId, float],
    action: ActionSpec,
    received: Mapping[NeedId, float],
    before: Mapping[NeedId, float],
    rate: float,
) -> float:
    """Corrige las expectativas con lo que acaba de pasar. Muta los dos dicts.

        creencia <- creencia + alfa * (recibido/prometido - creencia)

    **Devuelve la sorpresa**: el mayor error de predicción en valor absoluto,
    `max |recibido/prometido - creencia|` sobre lo que sí se aprendió. Ese número
    ya se calculaba aquí y se tiraba; es lo que la memoria episódica usa para
    decidir qué marca y qué no (`memory.importancia_de`).

    Se toma el **máximo y no la suma** por legibilidad: la suma crece con cuántas
    necesidades toque la acción, así que una acción compleja saldría siempre más
    sorprendente que una simple aunque nada la desviara. El máximo se puede
    señalar con el dedo — *esperaba esto de aquel eje y salió lo otro*.

    Devuelve 0.0 cuando no hay nada que aprender, que es también lo que
    corresponde: sin expectativa no hay sorpresa.

    Se aprende en las dos direcciones: cuánto da algo de verdad y cuánto cuesta
    de verdad. La creencia es un **multiplicador** sobre `satisfies` o sobre
    `costs`, no un sustituto — el pack sigue diciendo de qué va la acción y el
    agente aprende cuánto fiarse. Empieza en 1.0 y deriva con la experiencia.

    Los almacenes van separados porque una necesidad puede aparecer en los dos
    lados de la misma acción, y con un solo diccionario las dos creencias se
    pisarían.

    Tres cosas que NO se aprenden, y son las que hacen que la lección sea la
    correcta:

    **Nada de lo que no cabía.** Si comes con el estómago casi lleno, el efecto
    se recorta por el techo de la necesidad y no porque la comida fuera mala.
    Aprender de ahí produciría agentes convencidos de que comer no sirve justo
    por haber comido bien.

    **Nada de lo que no se podía pagar.** El espejo del anterior por abajo: si
    te quedan 0.05 y algo cuesta 0.30, gastas 0.05 y concluirías que es barato.

    **Nada de los efectos colaterales.** Trabajar sube el vínculo de rebote,
    pero nadie va a trabajar por eso. Solo se actualiza lo que el pack declara
    como perseguido (`satisfies`) o como precio (`costs`).

    `rate` a 0 desactiva el aprendizaje sin código condicional en el motor.
    """
    if rate <= 0.0:
        return 0.0

    sorpresa = 0.0
    for need_id, promised in action.effects.items():
        if promised > 0.0 and need_id in action.satisfies:
            room = 1.0 - before[need_id]
            if room < promised:
                continue  # el techo recortó; de esto no se aprende nada
            realized = received.get(need_id, 0.0) / promised
            store: dict[NeedId, float] = gain_beliefs

        elif promised < 0.0 and need_id in action.costs:
            spend = -promised
            if before[need_id] < spend:
                continue  # el suelo recortó; tampoco se aprende
            realized = -received.get(need_id, 0.0) / spend
            store = cost_beliefs

        else:
            continue  # efecto colateral: no se perseguía ni se anticipaba

        current = store.get(need_id, 1.0)
        error = realized - current
        sorpresa = max(sorpresa, abs(error))
        store[need_id] = current + rate * error

    return sorpresa
