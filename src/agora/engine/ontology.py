"""Ontología invariante del motor.

Estas son las ÚNICAS primitivas que el motor conoce. Ninguna sabe qué es una
espada, un hechizo o una nave: solo sabe que existen "necesidades", "acciones"
y "lugares" con ciertos números. La ambientación entra como datos (content
pack), nunca como código.

Distinción central:
    Spec  -> definición inmutable que viene del pack. No cambia en runtime.
    State -> valores mutables de una partida concreta. Vive en `state.py`.

Es la misma separación que en Unity entre un ScriptableObject y la instancia
que corre en escena, o en C# entre una clase de configuración y su objeto.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, NewType

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Identificadores.
#
# `NewType` da a mypy la misma protección que un tipo fuerte en C#: pasar un
# PlaceId donde se espera un AgentId es un error de compilación, aunque en
# runtime ambos sean `str`. Coste cero en ejecución.
# ---------------------------------------------------------------------------
NeedId = NewType("NeedId", str)
TraitId = NewType("TraitId", str)
ActionId = NewType("ActionId", str)
PlaceId = NewType("PlaceId", str)
AgentId = NewType("AgentId", str)
Affordance = NewType("Affordance", str)
Tag = NewType("Tag", str)

PositiveFactor = Annotated[float, Field(gt=0.0)]
"""Multiplicador estrictamente positivo.

Se usa donde un factor se eleva a una potencia. Un multiplicador de 0 o
negativo haría que `0 ** -1` reviente o que la utilidad cambie de signo, y
ninguna de las dos cosas tiene interpretación en el modelo.
"""

NonNegativeFactor = Annotated[float, Field(ge=0.0)]
"""Magnitud que nunca es negativa.

Se usa en los costes: un coste negativo sería un beneficio, y para eso ya
existe `satisfies`. Permitirlo dejaría dos formas de expresar lo mismo y haría
imposible leer una acción de un vistazo.
"""


class Spec(BaseModel):
    """Base de toda definición que viene del pack. Inmutable y estricta."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Necesidades
# ---------------------------------------------------------------------------
class NeedSpec(Spec):
    """Un eje de presión interna que decae con el tiempo.

    El motor no sabe si esto es "hambre" o "nivel de oxígeno". Solo sabe que
    baja sola y que ciertas acciones lo suben.
    """

    id: NeedId
    label: str
    """Nombre legible, solo para logs y narración. El motor nunca lo lee."""

    decay_per_tick: float = Field(gt=0.0, le=1.0)
    """Cuánto baja por tick. Calibrar esto ES el trabajo de F0."""

    initial: float = Field(default=1.0, ge=0.0, le=1.0)

    base_weight: float = Field(default=1.0, ge=0.0)
    """Importancia base antes de que la personalidad la modifique."""

    strain_weight: float = Field(default=0.0, ge=0.0)
    """Cuánto contribuye esta necesidad al desgaste cognitivo cuando escasea.

    El desgaste no es una emoción: es un modificador de CÓMO se decide. Estar
    agotado y con hambre no cambia lo que quieres —de eso ya se encarga la
    urgencia— sino que decides peor: más errático, y las distancias pesan más.

    Qué desgasta es propio de la ambientación. En un barrio, el descanso y el
    sustento; en una estación espacial, el oxígeno. Un 0 significa que esa
    necesidad puede estar a cero sin que la cabeza se resienta: el dinero
    aprieta, pero no te vuelve torpe.
    """

    company_relief: float = Field(default=0.0, ge=0.0)
    """Cuánto frena la compañía el decaimiento de esta necesidad, por tick.

    Estar rodeado de gente alivia la soledad aunque no hables con nadie, y da
    igual quién sea. Modela eso sin necesidad de relaciones.

    El alivio satura: `relief * n/(n+1)`. Una persona da la mitad del máximo,
    tres dan tres cuartos, y una multitud nunca da más que el tope. Sin saturar,
    una sala llena volvería la necesidad irrelevante.

    Puesto igual al `decay_per_tick`, la compañía **frena** la necesidad pero
    nunca la llena: para eso hay que actuar. Es la diferencia entre estar
    acompañado y estar acompañado por alguien.
    """

    urgency_exponent: float = Field(default=2.0, gt=0.0)
    """Curva de urgencia: urgencia = (1 - valor) ** exponente.

    Exponente 1 = lineal (el NPC oscila, atiende todo a medias).
    Exponente 2 = la necesidad es irrelevante hasta que de pronto es crítica.
    Subir esto por necesidad concreta permite que "dormir" apremie distinto
    que "socializar".
    """


# ---------------------------------------------------------------------------
# Temperamento
# ---------------------------------------------------------------------------
class TemperamentKnob(StrEnum):
    """Aspectos de CÓMO se decide que un rasgo puede modular.

    Conjunto cerrado a propósito: a diferencia de las necesidades o los lugares,
    esto no lo define la ambientación sino el motor. Son los cuatro puntos donde
    la maquinaria de decisión admite variación individual.

    El pack fija el valor del mundo (`TuningSpec`) y el agente lo modula. Un
    mundo donde viajar es peligroso Y una persona que odia salir de casa son dos
    cosas distintas que se componen, no que se sustituyen.
    """

    TEMPERATURE = "temperature"
    """Cuánto azar frente a criterio. Alto: errático. Bajo: metódico."""

    LOSS_AVERSION = "loss_aversion"
    """Cuánto pesa el precio. Alto: calculador. Bajo: vive el momento."""

    CRITICAL_THRESHOLD = "critical_need_threshold"
    """Cuándo cunde el pánico. Alto: se alarma pronto. Bajo: aguanta."""

    TRAVEL_DISCOUNT = "travel_discount"
    """Cuánto pesa la distancia. Alto: se mueve. Bajo: arraigado."""


# ---------------------------------------------------------------------------
# Rasgos: multiplicadores estables de personalidad
# ---------------------------------------------------------------------------
class TraitSpec(Spec):
    """Un rasgo no "hace" nada: reescala el peso de ciertas necesidades.

    Ahí está la emergencia. Dos NPCs con reglas idénticas y pesos distintos
    viven vidas distintas sin una sola línea de código específica para ellos.
    """

    id: TraitId
    label: str
    need_weight_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Multiplicador a intensidad plena (rasgo = 1.0). Un 1.0 aquí = sin efecto.

    La intensidad del agente (-1..1) se aplica como EXPONENTE, no como
    interpolación lineal:

        factor = multiplicador ** intensidad

    Así el 0 siempre neutraliza (M**0 == 1) y el -1 invierte exactamente
    (M**-1 == 1/M). Con interpolación lineal, un multiplicador de 2.2 y una
    intensidad de -1 daría un factor negativo, que no significa nada.
    """

    temperament_multipliers: dict[TemperamentKnob, PositiveFactor] = Field(
        default_factory=dict
    )
    """Segundo canal del rasgo: en vez de QUÉ le importa al agente, cambia CÓMO
    decide.

    Se compone igual que los pesos —el multiplicador elevado a la intensidad—
    y sobre el valor que el pack fijó para el mundo.

    Un rasgo puede usar los dos canales, uno, o ninguno. `impulsividad` solo
    toca temperamento; `codicia` solo toca pesos; nada impide que un rasgo haga
    ambas cosas.
    """


# ---------------------------------------------------------------------------
# Acciones
# ---------------------------------------------------------------------------
class ActionSpec(Spec):
    """Algo que un agente puede hacer durante N ticks.

    `effects` y `satisfies` parecen redundantes pero no lo son:
      - satisfies -> se usa ANTES, para puntuar la acción al deliberar.
      - effects   -> se usa DESPUÉS, para aplicar el resultado real.
    Separarlos permite que un NPC se equivoque: puede creer que algo lo va a
    saciar y que el efecto real sea menor. Eso es material narrativo gratis.
    """

    id: ActionId
    label: str
    duration_ticks: int = Field(ge=1)

    requires_affordance: Affordance | None = None
    """Si está puesto, la acción solo es válida en lugares que la ofrezcan."""

    requires: dict[NeedId, NonNegativeFactor] = Field(default_factory=dict)
    """Nivel mínimo de cada necesidad para poder siquiera intentarlo.

    Es el "no puedo permitírmelo". Sin esto, un agente con la despensa a cero
    cocina igual y el efecto negativo simplemente se recorta: el ritmo sale
    plausible pero la restricción no existe, y ninguna decisión cambia por
    estar arruinado.

    Puerta dura, no descuento. El coste ya modula el atractivo de gastar; esto
    es otra cosa: hay cosas que directamente no puedes hacer.

    Puesto a la altura de lo que la acción consume, el efecto deja de truncarse
    — y `pack.py` rechaza declararlo por debajo, porque entonces no impediría
    nada de lo que dice impedir.
    """

    requires_company: int = Field(default=0, ge=0)
    """Cuántos OTROS agentes hacen falta en el sitio para poder hacer esto.

    Sin esto, un agente "charla" solo en una plaza vacía — medido: el 68 % de
    las conversaciones del barrio no tenían a nadie delante.

    Es una puerta dura, no un descuento. Y se comprueba dos veces: al deliberar,
    para no elegir lo imposible, y **al llegar a destino**, porque entre que
    decides y llegas la gente se va. Ese segundo caso produce el "fui a la plaza
    y no había nadie", que es exactamente lo que se quiere.
    """

    satisfies: dict[NeedId, float] = Field(default_factory=dict)
    """Cuánto CREE el agente que esta acción atiende cada necesidad (0..1)."""

    costs: dict[NeedId, NonNegativeFactor] = Field(default_factory=dict)
    """Cuánto CREE el agente que esta acción le va a costar. Espejo de
    `satisfies`, y en la MISMA escala: "cuánto va esta acción de gastar eso".

    Ojo con la escala, porque es la trampa del modelo: `satisfies` y `costs`
    miden intención (0..1), mientras `effects` mide el delta real. Derivar los
    costes de los efectos negativos compararía unidades distintas y los
    aplastaría sistemáticamente. Por eso se declaran a mano.

    Un valor de 0.0 explícito significa "el agente no anticipa este coste" —
    útil para modelar imprudencia, y distinto de olvidarse de declararlo (que
    `pack.py` rechaza).
    """

    effects: dict[NeedId, float] = Field(default_factory=dict)
    """Delta real aplicado al completar. Puede ser negativo (trabajar cansa)."""

    saturation_gain: float = Field(default=0.0, ge=0.0)
    """Cuánto hastía una repetición de esto. 0 = nunca cansa.

    Que sea opcional y por acción es lo que impide que el mecanismo se pelee
    con la necesidad fisiológica: si `dormir` saturara, un agente evitaría
    dormir por repetitivo, y dormir cada día es lo correcto. Se declara solo
    en lo que de verdad aburre repetir.

    La recuperación es global (`TuningSpec.saturation_recovery`), así que este
    valor gobierna a la vez cuánto sube el hastío y cuánto tarda en pasarse.
    """

    tags: frozenset[Tag] = Field(default_factory=frozenset)
    """Válvula de escape para lo que el motor no modela: "violenta", "ilegal",
    "ruidosa". Los packs declaran qué significan; el motor solo las compara."""


# ---------------------------------------------------------------------------
# Lugares: nodos del grafo del mundo
# ---------------------------------------------------------------------------
class PlaceSpec(Spec):
    id: PlaceId
    label: str

    affordances: frozenset[Affordance] = Field(default_factory=frozenset)
    """Qué permite hacer aquí. Es el acoplamiento lugar <-> acción."""

    neighbors: dict[PlaceId, int] = Field(default_factory=dict)
    """Vecino -> ticks de viaje. El grafo es dirigido a propósito: bajar por un
    acantilado puede costar menos que subirlo."""

    tags: frozenset[Tag] = Field(default_factory=frozenset)
    """Atmósfera y control: "sagrado", "vigilado", "ruinoso"."""

    @model_validator(mode="after")
    def _no_self_loop(self) -> PlaceSpec:
        if self.id in self.neighbors:
            raise ValueError(f"lugar {self.id!r} es vecino de sí mismo")
        return self


# ---------------------------------------------------------------------------
# Gustos: modificadores por objetivo concreto
# ---------------------------------------------------------------------------
class TasteSpec(Spec):
    """Preferencia hacia un objetivo específico.

    Rasgos sesgan CATEGORÍAS de necesidad; los gustos sesgan INSTANCIAS.
    "Sociable" es un rasgo. "Odia la taberna del puerto" es un gusto.
    Sin esta capa todos los NPCs sociables se comportan igual.
    """

    target: ActionId | PlaceId | AgentId
    multiplier: float = Field(gt=0.0)
    """<1 aversión, >1 predilección. Multiplica la utilidad final."""


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------
class AgentSpec(Spec):
    id: AgentId
    label: str
    home: PlaceId
    start_at: PlaceId

    traits: dict[TraitId, float] = Field(default_factory=dict)
    """Rasgo -> intensidad en -1..1. Validado abajo."""

    tastes: tuple[TasteSpec, ...] = ()
    initial_needs: dict[NeedId, float] = Field(default_factory=dict)
    """Override del `initial` de cada NeedSpec. Lo que falte usa el default."""

    @model_validator(mode="after")
    def _traits_in_range(self) -> AgentSpec:
        for trait, value in self.traits.items():
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"rasgo {trait!r} = {value}, fuera de [-1, 1]")
        return self


# ---------------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------------
class HealthSpec(Spec):
    """Qué clase de mundo quiere ser este pack.

    No son parámetros de simulación: son **intención de diseño verificable**.
    "Aquí la gente vive bajo presión moderada, no en la miseria ni en la
    abundancia" es una afirmación sobre el mundo, y conviene que falle
    ruidosamente cuando deja de ser cierta.

    Están aquí y no en el test por dos motivos. Uno, un test con las bandas
    clavadas pelearía contra la calibración: cambiar un decay rompería el test
    aunque el cambio fuera bueno. Dos, cada ambientación quiere cosas
    distintas — una aldea acomodada y un mundo al borde del colapso no tienen
    por qué compartir umbral.

    Todo es opcional. Un pack sin `health` solo se somete a los invariantes
    universales: que nadie se bloquee y que ningún valor se salga de rango.
    """

    days: int = Field(default=7, ge=1)
    seeds: tuple[int, ...] = (1312, 7, 99)
    """Varias semillas porque una corrida es una muestra, no un resultado."""

    min_crisis: float | None = Field(default=None, ge=0.0, le=1.0)
    """Suelo de presión. Un mundo donde nadie pasa apuros nunca es un mundo
    donde el carácter no se nota: con todo resuelto, todos convergen en la
    opción óptima y las diferencias de personalidad dejan de verse."""

    max_crisis: float | None = Field(default=None, ge=0.0, le=1.0)
    """Techo de presión. Por encima, la emergencia aplasta al carácter."""

    max_abort_ratio: float | None = Field(default=None, ge=0.0)
    """Abandonos frente a acciones completadas."""

    max_transit: float | None = Field(default=None, ge=0.0, le=1.0)
    """Fracción del tiempo en tránsito."""

    min_differentiation: float | None = Field(default=None, ge=0.0)
    """Distancia media entre las vidas de cada par de agentes. Es la métrica
    que caza el colapso: fichas distintas que producen vidas idénticas."""

    may_go_unused: frozenset[ActionId] = Field(default_factory=frozenset)
    """Acciones que pueden no aparecer nunca sin que sea un fallo.

    La red de seguridad es el caso típico: en un mundo sano nadie debería
    necesitar recurrir a ella. Cualquier OTRA acción sin usar sí es un aviso —
    es contenido declarado que el mundo nunca ejerce.
    """


# ---------------------------------------------------------------------------
# Reloj
# ---------------------------------------------------------------------------
class ClockSpec(Spec):
    """Cómo se traduce un tick a tiempo del mundo.

    Vive en el pack porque no es universal: una aldea tiene días de 24 h, una
    estación espacial puede tener ciclos de 18, y un plano infernal puede no
    tener día en absoluto. El motor solo cuenta ticks; esto es lo único que
    sabe convertirlos a algo legible.
    """

    minutes_per_tick: int = Field(default=15, ge=1)
    ticks_per_day: int = Field(default=96, ge=1)


# ---------------------------------------------------------------------------
# Calibración
# ---------------------------------------------------------------------------
class TuningSpec(Spec):
    """Las perillas que gobiernan CÓMO se decide, no QUÉ existe.

    Viven en el pack y no en el código a propósito. Calibrar es un ciclo de
    decenas de iteraciones sobre el YAML; una constante enterrada en un módulo
    de Python es una perilla que no se puede girar.

    Además cambian con la ambientación: en un mundo donde viajar es caro y
    peligroso, `travel_discount` debería ser mucho más agresivo que en una
    aldea de cinco lugares.
    """

    travel_discount: float = Field(default=0.95, gt=0.0, le=1.0)
    """Se aplica una vez por tick de viaje: `descuento ** ticks`.

    1.0 = la distancia no importa, los agentes cruzan el mundo por un capricho.
    Valores bajos = agentes sedentarios que solo usan lo que tienen cerca.
    """

    candidate_pool: int = Field(default=3, ge=1)
    """Cuántas de las mejores opciones entran en el sorteo final.

    1 equivale a argmax puro (determinista y robótico). Subirlo aumenta la
    variedad, pero también la probabilidad de elegir algo claramente peor.
    """

    temperature: float = Field(default=0.15, gt=0.0)
    """Cuánto pesa el azar frente a la utilidad dentro del grupo de finalistas.

    Cerca de 0 = casi siempre gana el mejor. Alta = casi indiferente entre los
    finalistas. Es la perilla que separa "persona con criterio" de "veleta".
    """

    saturation_recovery: float = Field(default=0.004, ge=0.0)
    """Cuánto se pasa el hastío por tick. A 0.004, una saturación de 0.35 se
    disipa en unos 88 ticks — algo menos de un día."""

    novelty_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    """Cuánto castiga el hastío pleno:

        novedad = 1 - saturación * novelty_weight

    Acotado por debajo a `1 - novelty_weight`, y ahí está su razón de ser. Con
    novedad pura, una acción saturada al tope valdría cero aunque la necesitaras
    desesperadamente, y un agente hastiado de comer se moriría de hambre. A 0.6
    el hastío recorta como mucho un 40 %: suficiente para cambiar de plan, no
    para impedir lo imprescindible.

    0.0 desactiva el mecanismo por completo.
    """

    loss_aversion: float = Field(default=1.0, ge=0.0)
    """Cuánto pesa perder frente a ganar, en el término de coste.

    Viene de economía del comportamiento: la gente sufre las pérdidas alrededor
    del doble de lo que disfruta las ganancias equivalentes.

    1.0 neutral · 1.5-2.0 gente prudente · 0.5 gente que vive el momento.
    0.0 desactiva los costes y recupera el comportamiento anterior.

    Es global por ahora. Tiene más sentido como rasgo individual (prudencia
    frente a impulsividad), pero eso son dos cambios a la vez.
    """

    strain_multipliers: dict[TemperamentKnob, PositiveFactor] = Field(default_factory=dict)
    """Cómo cambia el temperamento estando al límite.

    Tercera capa sobre las mismas perillas: mundo * rasgos * estado. Se compone
    igual, con el desgaste (0..1) como exponente, así que un agente entero no se
    ve afectado y uno destrozado recibe el multiplicador completo.

    Produce los "días malos" sin tocar la personalidad: el mismo NPC decide
    distinto según cómo esté, y sigue siendo él.
    """

    switch_cost: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto protege lo ya invertido frente a una interrupción.

        umbral_efectivo = umbral * (1 - progreso * switch_cost)

    A mitad de una tarea el listón para abandonarla baja, y casi al final solo
    una catástrofe la corta. Produce el "ya que estoy, lo termino", que es de
    lo más humano que hay, y evita el desperdicio peor: medido antes de esto,
    seis veces por semana alguien tiraba algo que llevaba al 80 %.

    0.0 desactiva el mecanismo: se interrumpe igual con un tick hecho que con
    treinta.
    """

    critical_need_threshold: float = Field(default=0.15, ge=0.0, le=1.0)
    """Por debajo de este valor, una necesidad puede interrumpir lo que se esté
    haciendo. Solo interrumpe si la acción en curso NO la atiende: nadie
    abandona la comida por hambre.

    0.0 desactiva las interrupciones: los agentes terminan siempre lo que
    empiezan, aunque se estén muriendo.
    """
