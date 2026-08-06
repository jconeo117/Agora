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
GoalId = NewType("GoalId", str)
PhaseId = NewType("PhaseId", str)
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

    decay_per_tick: float = Field(ge=0.0, le=1.0)
    """Cuánto baja por tick. Calibrar esto ES el trabajo de F0.

    Un 0 describe un eje que no se pierde solo: solo cambia por lo que se hace.
    Ver `progression`.
    """

    progression: bool = False
    """Este eje solo sube: no es una carencia, es lo lejos que se ha llegado.

    Nivel, experiencia, reputación, dominio de un arte. La diferencia con una
    necesidad no es de grado sino de naturaleza: estar a 0.1 de sustento es una
    emergencia, y estar a 0.1 de experiencia es ser novato.

    Y por eso hace falta el campo, en vez de deducirlo de `decay_per_tick == 0`.
    **Un eje de progresión no puede entrar en crisis.** Un personaje que empieza
    abajo estaría por debajo del umbral crítico durante toda su escalada:
    soltaría lo que estuviera haciendo para ir a entrenar, y el contrato de salud
    del pack mediría una emergencia que no existe. Medido con una ganancia
    realista de 0.004 por sesión, el tiempo en crisis pasa de 0 % a 27.7 %, de
    sobra para reventar el contrato de un mundo sano.

    Lo que SÍ conserva es la urgencia, y ahí está lo bueno: `(1 - valor) ^ exp`
    hace que subir apremie mientras se es novato y deje de importar cerca del
    tope. Querer crecer no necesita un sistema de metas — la fórmula ya sabe
    querer, y esto solo le da un eje donde hacerlo.
    """

    urgent_when_low: bool = True
    """Si escasear esto es una emergencia que justifica soltarlo todo.

    `progression` lo apagaba de tapadillo, y eran dos conceptos distintos metidos
    en uno. Hay ejes que no son progresion y a los que tampoco les pega el pánico:
    un **inventario**. No llevar botin encima es lo normal, no una crisis, y
    tratarlo como tal produce un agente que interrumpe lo que sea para ir a por
    material — medido, una alumna de magia se fue a vivir al bosque el primer dia.

    La distincion es entre lo que se AGOTA y lo que se ACUMULA. El hambre a cero
    es una urgencia; la bolsa vacia es un martes.

    Apagarlo no toca la urgencia: sigue apeteciendo llenarlo, y con la misma
    curva. Solo pierde el poder de interrumpir.
    """

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

    max_debt: float = Field(default=0.0, ge=0.0)
    """Cuánto puede acumularse esta necesidad POR DEBAJO del suelo. 0 lo desactiva.

    Sin esto, el motor no sabe estar peor que vacío. Un guerrero que pelea tres
    días y otro que durmió mal una noche están los dos en 0.0 y son
    indistinguibles: el suelo recorta el decaimiento y la información se pierde.

    Con deuda, lo que el suelo recortaría se anota aparte, y **reponer paga la
    deuda antes de subir la necesidad**. El valor sigue viviendo en [0, 1], así
    que la urgencia, el desgaste, los requisitos y las métricas no se enteran de
    que esto existe: solo cambia cuánto tarda uno en recuperarse.

    De ahí sale el drama sin escribirlo. Con `decay_per_tick` 0.007, tres días
    sin dormir dejan una deuda de 1.00; pagarla y llenar el descanso son 2.00 a
    razón de 0.033 por tick, o sea **quince horas de sueño**. Y a quien lo
    despierten a las ocho se levanta con la deuda saldada y el descanso a 0.19,
    todavía hecho polvo. Días de esfuerzo cuestan días de recuperación.

    El tope es obligatorio: sin él, una campaña de un mes dejaría una deuda
    impagable. Y es la perilla que dice cómo de brutal es la ambientación —
    1.0 es "una noche mala se paga en una noche larga", 3.0 es "una campaña te
    deja roto una semana".
    """

    urgency_exponent: float = Field(default=2.0, gt=0.0)
    """Curva de urgencia: urgencia = (1 - valor) ** exponente.

    Exponente 1 = lineal (el NPC oscila, atiende todo a medias).
    Exponente 2 = la necesidad es irrelevante hasta que de pronto es crítica.
    Subir esto por necesidad concreta permite que "dormir" apremie distinto
    que "socializar".

    En un eje de progresión conviene lo contrario que en una necesidad: por
    debajo de 1 el ansia de crecer se mantiene alta hasta cerca del tope, y por
    encima de 1 se desinfla en cuanto se dan los primeros pasos.
    """

    @property
    def can_be_critical(self) -> bool:
        """Un eje de progresion nunca lo es, digan lo que digan sus campos."""
        return self.urgent_when_low and not self.progression

    @model_validator(mode="after")
    def _progression_is_coherent(self) -> NeedSpec:
        """Un eje de progresión no admite las mecánicas de la carencia.

        Ninguna de las tres significa nada aquí, y permitirlas en silencio dejaría
        packs con campos que parecen hacer algo y no lo hacen: no se "pierde
        nivel" con el tiempo, no se debe experiencia, y ser novato no nubla el
        juicio ni se cura estando acompañado.
        """
        if not self.progression:
            return self
        vetados = {
            "decay_per_tick": self.decay_per_tick,
            "max_debt": self.max_debt,
            "company_relief": self.company_relief,
            "strain_weight": self.strain_weight,
        }
        puestos = sorted(name for name, value in vetados.items() if value)
        if puestos:
            raise ValueError(
                f"eje de progresión {self.id!r}: {', '.join(puestos)} no significa "
                f"nada en algo que solo sube"
            )
        return self


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

    gain_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Cuarto canal: **aptitud**. Cuánto le cunde a esta persona lo que hace.

    Escala lo que un eje GANA, no lo que le importa. Y esa distinción es la que
    hace falta para modelar que algo se te dé bien:

        need_weight_multipliers  ->  cuánto le IMPORTA
        gain_multipliers         ->  cuánto le CUNDE

    Son cosas distintas y su combinación describe personas concretas. Quien le da
    mucha importancia al descanso y lo recupera despacio existe; quien tiene mano
    para el arcano y le trae sin cuidado, también.

    Sin esto, estudiar rinde lo mismo a todo el mundo y "se le da bien la magia"
    solo puede significar "le gusta más", que es la mitad de la idea.

    Se compone como los pesos —el multiplicador elevado a la intensidad— y
    multiplica cualquier efecto POSITIVO sobre ese eje: los de una acción
    terminada y el ritmo de las elásticas, que son la misma pregunta hecha dos
    veces. Antes eran dos campos (`elastic_rate_multipliers` decía esto mismo
    solo para el sueño) y dos mecanismos que significan lo mismo son uno de más.

    Y sigue siendo un RITMO, no un tope. "Duermo poco y me basta" es recuperarse
    deprisa, no tener un límite bajo; modelarlo como tope dejaría a esa persona
    sin poder dormir de más cuando de verdad lo necesitara.
    """

    phase_shift: int = Field(default=0)
    """Tercer canal: cuánto se desplaza el reloj INTERNO de esta persona.

        franja_subjetiva = franja_de(tick + phase_shift * intensidad)

    No es un multiplicador, y esa diferencia costó una medición. La primera
    versión daba a cada rasgo multiplicadores por franja, igual que a las
    necesidades. No funciona, por dos motivos que solo se ven corriendo:

    **Multiplicar amplifica cuando debería invertir.** Con `dormir` favorecido de
    noche y un rasgo nocturno que multiplica lo nocturno, el búho dormiría MÁS de
    noche — justo al revés. Y dejar el sueño neutro para esquivarlo deja el
    descanso sin ancla horaria: medido, la gente dormía a cualquier hora y la
    aldea tenía el mismo trasiego a las cuatro de la mañana que a mediodía.

    **Un cronotipo no es una preferencia, es un desfase.** Para un ave nocturna
    la noche no "vale más": la noche *es* su mañana. Rotando la franja percibida,
    todo lo demás cae solo — trabaja, come y socializa en su mañana subjetiva, y
    duerme en su noche subjetiva, que es tu tarde.

    Lo que NO se desplaza son los horarios de los lugares. La herrería cierra a
    la misma hora para todo el mundo: el horario del mundo es objetivo y el reloj
    del cuerpo es subjetivo. Ver `candidates`.
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
class ElasticSpec(Spec):
    """Una acción que dura lo que haga falta, no un bloque fijo.

    El modelo por defecto —duración constante y efecto al terminar— trata dormir
    como una transacción, y dormir es una **acumulación**. Se nota en dos sitios:
    quien está poco cansado tiene que comprometer las ocho horas enteras o nada,
    y a quien lo levantan a falta de un tick se queda sin absolutamente nada.

    Con esto, la duración sale del déficit y el efecto sale del tiempo:

        ticks  = acotado( déficit / ritmo )
        efecto = ritmo * ticks

    Y ya es por persona sin declarar nada por persona, porque el déficit es de
    cada cual: quien llega a 0.9 duerme una hora y quien llega a 0.1 duerme ocho.
    """

    need: NeedId
    """Qué eje se repone, y por tanto qué déficit fija la duración."""

    per_tick: float = Field(gt=0.0)
    """Ritmo base de reposición. Lo modulan los rasgos de quien lo hace y el
    lugar donde se hace (`elastic_rate_multipliers`), y ahí está toda la
    variación: dormir mal es tener mal ritmo, no tener un tope bajo.

    De aquí salen las quince horas del guerrero sin ningún caso especial. A 0.033
    en una buena cama son siete horas y media desde cero; al 0.45 de la
    intemperie, diecisiete.
    """

    min_ticks: int = Field(default=1, ge=1)
    """Suelo. Nadie se acuesta para quince minutos, aunque le sobre con eso."""


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
    """Cuánto dura. Con `elastic`, deja de ser la duración y pasa a ser el TOPE.

    Y entonces conviene que sea generoso: el máximo que un cuerpo aguanta de un
    tirón, no el típico. Un tope de ocho horas haría inexpresable al guerrero
    que necesita quince, porque mordería antes que el ritmo.
    """

    elastic: ElasticSpec | None = None
    """Si está puesto, `duration_ticks` es el tope y la duración sale del déficit."""

    interruptible: bool = True
    """Si es `False`, ninguna urgencia puede abortarla: se termina o no se empieza.

    Hoy cualquier cosa se suelta cuando una necesidad cruza su umbral, y hay
    actividades donde eso no tiene sentido: nadie deja una batalla a la mitad
    para echar una cabezada.

    Es además **lo que hace posible la deuda**. Mientras se pueda parar, un
    agente se autolimita y nunca llega al agotamiento extremo; la necesidad no
    se hunde y no hay nada que acumular. Los dos mecanismos se necesitan.

    Tiene filo, y es el punto: una acción larga e inabandonable con una urgencia
    que no atiende es una forma de matar a alguien.

    Solo protege lo que se está ejecutando, no el viaje hacia ello. Se puede dar
    media vuelta de camino a la batalla; lo que no se puede es abandonarla.
    """

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

    requires_traits: dict[TraitId, float] = Field(default_factory=dict)
    """Rasgo mínimo para poder siquiera intentarlo. Cuarta puerta dura.

    `requires` solo sabe mirar necesidades, y hay cosas que no dependen de lo que
    tengas sino de **quién eres**: un conjuro de fuego pide afinidad con el fuego,
    y ninguna cantidad de dinero ni de descanso la sustituye.

    Es lo que permite que las clases, los linajes y las afinidades sean rasgos
    —continuos, componibles, capaces de híbridos— en vez de obligar a inventarse
    una necesidad por cada categoría.

    Puerta dura, no descuento. Un gusto de 0.05 haría que casi nunca lo hicieras;
    esto hace que no puedas.
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

    effects_per_company: dict[NeedId, float] = Field(default_factory=dict)
    """Cuánto añade la compañía al efecto, con rendimiento decreciente.

    Es la fuente de varianza del mundo, y sin ella no habría nada que aprender:
    con `effects` como constantes, lo prometido y lo recibido coinciden siempre
    y el error de predicción es cero por construcción.

    Una conversación con cuatro personas rinde más que con una. Y como entre
    decidir ir a la plaza y llegar la gente se mueve, el agente se lleva
    sorpresas en los dos sentidos — que es de donde sale el aprendizaje.

    Satura como el alivio por compañía (`n/(n+1)`): el valor declarado es el
    tope, uno da la mitad, tres tres cuartos.
    """

    phase_multipliers: dict[PhaseId, PositiveFactor] = Field(default_factory=dict)
    """Cuánto rinde esto según el tramo del ciclo. Lo ausente vale 1.0.

    Multiplica el **beneficio**, como los gustos y el descuento de viaje, y por
    el mismo motivo: sobre el neto, una mala idea parecería menos mala por
    hacerse a deshora.

    **Cuidado con ponérselo a dormir.** Es tentador y es un error. Si dormir
    valiera el doble de noche, un agente nocturno —que multiplica lo nocturno—
    dormiría MÁS de noche, justo al revés de lo que se quiere. Deja el sueño
    neutro y suprime lo demás: se duerme porque hay poco que hacer y aprieta el
    cansancio, así que quien tiene vida nocturna acaba durmiendo de día. La
    conducta sale sola en vez de declararse.
    """

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

    tolls: dict[PlaceId, dict[NeedId, NonNegativeFactor]] = Field(default_factory=dict)
    """Lo que cuesta tomar esa arista, además del tiempo. Vacío = gratis.

    Es lo que separa un **servicio** de un atajo. Un porte del gremio que deja en
    la boca de la sima en un tick no es un camino corto: es algo por lo que se
    paga, y por eso hay quien lo toma y quien va andando. Sin precio siempre
    ganaría y todo el mundo iría en carro.

    Sirve para cualquier cosa que se cobre por pasar: pasajes, peajes de puente,
    sobornos a la guardia, portales arcanos. El motor no sabe cuál es cuál.

    **Se declara en el sentido en que se paga.** El grafo es dirigido, así que
    llevar es una arista y volver es otra, y nada obliga a que cuesten lo mismo:

        gremio:  neighbors: { boca: 1 }
                 tolls:     { boca: { dinero: 0.12 } }
        boca:    neighbors: { gremio: 7 }      # la vuelta, andando y gratis

    Dos advertencias sobre cómo se comporta. El peaje **entra en la deliberación**
    pesado por la urgencia, así que a quien va justo de dinero le duele mucho más
    —de ahí sale que el pobre camine y el sobrado pague—. Pero **no bloquea el
    paso**: quien acabe tomando la arista sin fondos paga lo que tenga y llega a
    cero. Bloquear obligaría a buscar ruta por agente, y eso es otro motor.
    """

    gain_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Cuánto cunde AQUÍ lo que se hace. Mismo idioma que la aptitud del agente.

    La regla completa, y es una sola:

        lo que rinde algo  =  base  *  aptitud de quien lo hace  *  calidad del sitio

    Es la otra mitad de la variación: duerme mal quien tiene mal sueño, quien
    duerme en mal sitio, y peor quien las dos cosas. Aquí es donde una cama de
    posada se distingue de una noche a la intemperie, sin que el motor sepa qué
    es una cama ni un bosque.
    """

    open_during: frozenset[PhaseId] = Field(default_factory=frozenset)
    """En qué tramos se puede hacer algo aquí. Vacío = siempre abierto.

    Puerta dura, como la affordance: la herrería cerrada de noche no es menos
    atractiva, es que no está. Es lo que impide que un mundo con franjas siga
    funcionando a pleno rendimiento de madrugada.

    **Cierra actividades, no el paso.** Un lugar cerrado se sigue cruzando: si
    cerrar cortara aristas, el mundo dejaría de estar fuertemente conectado a
    ciertas horas y alguien podría quedarse encerrado lejos de su cama.
    """

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
class GoalStatus(StrEnum):
    """En qué anda una meta. Tres estados y no hay más.

    Lo logrado y lo perdido son distintos aunque los dos dejen de empujar: mueven
    rasgos opuestos, y el narrador no puede contar igual a quien lo consiguió que
    a quien se quedó a las puertas.
    """

    ACTIVE = "active"
    ACHIEVED = "achieved"
    FAILED = "failed"


class GoalSpec(Spec):
    """Algo que esta persona quiere y todavía no tiene.

    Una necesidad y una meta no son lo mismo, y la diferencia es toda la gracia:
    la necesidad se agota y se mantiene, la meta se cumple **una vez**. Lo
    primero produce rutina; lo segundo, historia.

    Y no necesita maquinaria nueva en la fórmula. `need_weights` ya es el dial
    que dice cuánto le importa algo a alguien; una meta es un **empujón temporal
    y personal** sobre ese dial que se apaga al lograrse. Toda la urgencia, los
    costes y las creencias siguen funcionando igual, sin enterarse.

    La regla al escribirlas: **una meta sin obstáculo es una rutina.** "Quiere
    trabajar" no es meta, lo hace todos los días. "Quiere reunir lo suficiente
    para irse y no le llega" sí lo es. El obstáculo aquí es el umbral: si
    `at_least` está al alcance de la rutina normal, no has escrito una meta.
    """

    id: GoalId
    label: str

    need: NeedId
    """Qué eje mide el logro. Es la única forma de medirlo hoy.

    Cubre casi todo lo que se quiere de verdad —dinero, experiencia, despensa,
    lo que el pack declare— porque una ambición concreta casi siempre se cifra
    en algo. Lo que NO cubre todavía es querer algo de **alguien**: "que Karla
    vuelva a hablarle" necesitaría medir un vínculo, y eso llegará. El campo se
    llama `need` y no `target` para que ese día se vea qué había antes.
    """

    at_least: float = Field(gt=0.0, le=1.0)
    """Umbral que cuenta como logrado. **Es el obstáculo, en números.**"""

    weight_multiplier: PositiveFactor = 2.0
    """Cuánto empuja mientras dura, sobre el peso que ya tuviera ese eje.

    Se compone como los rasgos, multiplicando, así que una meta sobre algo que
    ya te importaba aprieta más que sobre algo que te daba igual — y eso es lo
    correcto: querer irse pesa distinto en un avaro que en un manirroto.
    """

    deadline: int | None = Field(default=None, ge=1)
    """Tick absoluto en que se da por perdida. `None` = de por vida.

    No es adorno. Una meta cuyo umbral no se alcanza nunca deja al agente
    permanentemente escorado hacia ese eje, y eso lo distorsiona sin que nada
    lo resuelva. El plazo es lo que convierte un empujón indefinido en un arco
    con final, aunque el final sea el malo.
    """

    on_success: dict[TraitId, float] = Field(default_factory=dict)
    """Qué le mueve conseguirlo, rasgo a rasgo. Delta en [-2, 2].

    **Esto es lo que separa un logro de un arco.** Sin ello el personaje llega a
    la meta y sigue siendo exactamente quien era, que es lo contrario de una
    historia. Se fue del barrio, así que ya no es el que no salía: `arraigo -0.6`.
    """

    on_failure: dict[TraitId, float] = Field(default_factory=dict)
    """Y qué le mueve perderlo. Suele ser el material más interesante."""

    @model_validator(mode="after")
    def _drifts_are_sane(self) -> GoalSpec:
        """Una deriva mayor que el rango entero del rasgo no significa nada.

        Los rasgos viven en [-1, 1], así que un delta de 2 ya lleva de un extremo
        al otro. Más que eso es una errata pasando por intensidad dramática.
        """
        for campo, derivas in (("on_success", self.on_success), ("on_failure", self.on_failure)):
            for trait, delta in sorted(derivas.items()):
                if not -2.0 <= delta <= 2.0:
                    raise ValueError(
                        f"meta {self.id!r}.{campo}[{trait!r}] = {delta}, fuera de [-2, 2]; "
                        f"los rasgos viven en [-1, 1] y un 2 ya cruza el rango entero"
                    )
        return self


class AgentSpec(Spec):
    id: AgentId
    label: str
    home: PlaceId
    start_at: PlaceId

    goals: tuple[GoalSpec, ...] = ()
    """Lo que esta persona quiere. Vacío = alguien sin arco, y es legítimo."""

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
class PhaseSpec(Spec):
    """Un tramo con nombre dentro del ciclo. El motor no sabe qué es "la noche".

    Sabe que el ciclo se parte en tramos y que las cosas rinden distinto en cada
    uno. Un pack puede declarar `manana/tarde/noche`, o `marea_alta/marea_baja`,
    o `ciclo_de_luz/ciclo_de_sombra`. La ambientación entra como datos.
    """

    id: PhaseId
    label: str
    starts_at: int = Field(ge=0)
    """Tick del ciclo en que empieza. El tramo dura hasta que empieza el siguiente.

    No hace falta que ninguno empiece en 0: lo anterior a la primera franja
    pertenece a la ÚLTIMA, que es como se modela una noche que cruza la
    medianoche sin partirla en dos.
    """


class ClockSpec(Spec):
    """Cómo se traduce un tick a tiempo del mundo.

    Vive en el pack porque no es universal: una aldea tiene días de 24 h, una
    estación espacial puede tener ciclos de 18, y un plano infernal puede no
    tener día en absoluto. El motor solo cuenta ticks; esto es lo único que
    sabe convertirlos a algo legible.
    """

    minutes_per_tick: int = Field(default=15, ge=1)
    ticks_per_day: int = Field(default=96, ge=1)

    phases: tuple[PhaseSpec, ...] = ()
    """Los tramos del ciclo, en orden. Vacío = el mundo no distingue momentos.

    Hasta que esto existió, el reloj era **decorativo**: solo lo leían el
    renderizador y el bucle para saber cuándo parar. Nada de la deliberación lo
    consultaba, así que el motor no sabía que era de noche y la gente se acostaba
    escalonada a cualquier hora, cuando el cansancio apretaba.
    """

    @model_validator(mode="after")
    def _phases_are_ordered_and_fit(self) -> ClockSpec:
        seen: set[PhaseId] = set()
        last = -1
        for phase in self.phases:
            if phase.id in seen:
                raise ValueError(f"franja {phase.id!r} declarada dos veces")
            seen.add(phase.id)
            if phase.starts_at >= self.ticks_per_day:
                raise ValueError(
                    f"franja {phase.id!r} empieza en {phase.starts_at}, "
                    f"fuera del ciclo de {self.ticks_per_day} ticks"
                )
            if phase.starts_at <= last:
                raise ValueError(
                    f"franja {phase.id!r} empieza en {phase.starts_at}, "
                    f"antes o a la vez que la anterior ({last}); decláralas en orden"
                )
            last = phase.starts_at
        return self

    def phase_at(self, tick: int) -> PhaseId | None:
        """En qué tramo del ciclo cae este tick. `None` si el pack no declara
        ninguno, y entonces todo lo que dependa de la franja queda inerte.

        Lo anterior a la primera franja pertenece a la última: así una noche
        declarada en el tick 80 cubre también del 0 al amanecer, sin partirla.
        """
        if not self.phases:
            return None
        moment = tick % self.ticks_per_day
        chosen = self.phases[-1]
        for phase in self.phases:
            if phase.starts_at > moment:
                break
            chosen = phase
        return chosen.id


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

    sighting_horizon: int = Field(default=0, ge=0)
    """Cuántos ticks vale lo que un agente vio en un sitio, antes de olvidarlo.

    Hoy, sin esto, cada agente sabe en tiempo real quién hay en los veintiún
    lugares del barrio. Con un horizonte, solo sabe lo que vio con sus ojos y
    hace cuánto — y lo que no recuerda, lo supone.

    Se supone **a favor**: un sitio del que no se sabe nada se da por bueno. Así
    el agente va a mirar y se lleva el chasco, que es donde estaba la gracia. Lo
    contrario —suponer vacío— haría que nadie fuera nunca a ningún sitio del que
    no tuviera noticia fresca.

    No hace falta maquinaria nueva para el chasco: la comprobación al llegar ya
    existe desde que la compañía es un requisito. Esto solo cambia con qué
    información se decide, no cómo se resuelve.

    0 desactiva el mecanismo y devuelve la omnisciencia.
    """

    bond_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto mueve un rato compartido el aprecio hacia quien estaba delante.

    Mismo error de predicción que `learning_rate`, pero atribuido a **personas**
    en vez de a acciones. La señal es el premio que aportó la compañía, pesado
    por lo mucho que al agente le hacía falta: quien estaba ahí cuando lo
    necesitabas se te queda grabado, y quien estaba ahí cuando no te daba igual.

    Que el premio se reparta entre todos los presentes por igual es deliberado y
    no una simplificación: nadie puede saber cuál de los cuatro hizo buena la
    velada. A base de repetir, la persona que sale en todas las veladas buenas
    acumula aprecio, y esa es exactamente la forma en que se forma el afecto de
    verdad. Nadie tuvo que escribir quién le cae bien a quién.

    0.0 desactiva el mecanismo: los vínculos se registran pero nunca cambian.
    """

    bond_scale: float = Field(default=1.0, gt=0.0)
    """Cuánto premio compartido equivale a medio aprecio.

        premio = bruto / (|bruto| + bond_scale)

    Existe porque el bruto está en las unidades del pack —pesos por urgencias
    por efectos— y el aprecio está acotado a [-1, 1]. Sin este divisor, el
    mecanismo es inerte en un pack de números pequeños y desbordado en uno de
    números grandes: medido en el barrio, los aprecios se estancaban en 0.001.

    Y es lo que mantiene honesto a `bond_weight`. Con la normalización, un
    aprecio de 0.5 significa lo mismo en el barrio que en un mundo de espadas;
    sin ella, cada ambientación tendría que recalibrar una perilla del motor,
    que es justo lo que este proyecto no se puede permitir.

    **Mídelo, no lo adivines.** Corre una semana con el rate puesto y mira dónde
    se estancan los aprecios; si se quedan cortos, baja la escala.
    """

    bond_weight: float = Field(default=0.0, ge=0.0)
    """Cuánto vale una persona apreciada frente a una desconocida, al contar
    compañía.

        peso_de_uno = 1 + bond_weight * aprecio

    Es la perilla que convierte "cuánta gente hay" en "quién hay". A 0 el mundo
    vuelve a ser anónimo y cuatro extraños valen lo mismo que cuatro amigos, que
    es como estaba el motor hasta ahora.

    Con aprecio negativo el peso baja de 1 y puede pasar de 0: la presencia de
    quien te repele no solo no acompaña, resta. Ver `company_saturation`, que
    está firmada para admitirlo.
    """

    bond_fade: float = Field(default=1.0, gt=0.0, le=1.0)
    """Cuánto se desdibuja el aprecio por cada tick sin ver a alguien.

        aprecio_ahora = aprecio * bond_fade ** (ticks sin verse)

    Se evalúa **al leer**, a partir de `last_seen`, y no recorriendo los
    vínculos cada tick. Con mil agentes, un bucle por tick sobre cada vínculo de
    cada uno es justo la clase de coste que hunde el sistema bajo su propio peso;
    esto es O(1) y da lo mismo.

    1.0 lo desactiva: lo que sentiste una vez lo sientes para siempre.
    """

    bond_horizon: int = Field(default=0, ge=0)
    """Tras cuántos ticks sin ver a alguien se borra el vínculo entero.

    Es el segundo mecanismo de olvido del motor, y aquí no es un adorno
    narrativo: sin él, cada agente acumula una entrada por cada persona con la
    que se ha cruzado alguna vez, y en un mundo de mil habitantes eso crece sin
    techo. Olvidar es lo que mantiene el estado acotado.

    Que además se lea bien —dejas de ver a alguien un año y se te borra— es la
    clase de coincidencia que indica que el modelo va por buen sitio.

    0 desactiva el borrado: nadie olvida a nadie nunca.
    """

    companionship_weight: float = Field(default=0.0, ge=0.0)
    """Cuánto atrae la compañía esperada, al deliberar.

        factor = 1 + companionship_weight * saturación(compañía_efectiva)

    Cubre un punto ciego real: hasta ahora, una acción social puntuaba **igual**
    en un sitio con una persona que en uno con cinco. La compañía era una puerta
    dura (`requires_company`) y nada más, así que nadie prefería la plaza llena a
    la plaza justa.

    Se aplica solo a las acciones a las que el pack dice que la gente les importa
    —las que declaran `effects_per_company` o exigen compañía—. Sin ese filtro,
    un agente preferiría dormir rodeado de gente.

    Multiplica el beneficio, nunca el neto, por el mismo motivo que el descuento
    de viaje: sobre el neto, una mala idea parecería menos mala por hacerse
    acompañado.

    0.0 lo desactiva.
    """

    learning_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto corrige el agente sus expectativas tras cada experiencia (alfa).

    Nunca alto. A 0.10, hacen falta unas veinte experiencias para que una
    creencia se asiente, que es lo que se quiere: un NPC que aprende deprisa
    tiene la memoria de un pez y cambia de opinión con cada anécdota.

    0.0 desactiva el aprendizaje y las expectativas se quedan en lo que dice el
    pack, igual para todos.
    """

    strain_multipliers: dict[TemperamentKnob, PositiveFactor] = Field(default_factory=dict)
    """Cómo cambia el temperamento estando al límite.

    Tercera capa sobre las mismas perillas: mundo * rasgos * estado. Se compone
    igual, con el desgaste (0..1) como exponente, así que un agente entero no se
    ve afectado y uno destrozado recibe el multiplicador completo.

    Produce los "días malos" sin tocar la personalidad: el mismo NPC decide
    distinto según cómo esté, y sigue siendo él.
    """

    duration_discount: float = Field(default=1.0, gt=0.0, le=1.0)
    """Cuánto resta atractivo comprometer tiempo. `descuento ** duración`.

    Cubre la única ceguera real que tenía la fórmula respecto a la duración:
    quien se mete en algo de treinta ticks **no puede atender nada más durante
    treinta ticks**, y ese coste de oportunidad no aparecía por ningún lado.

    Ojo con lo que NO es. Durante mucho tiempo arrastramos la idea de que la
    duración faltaba porque la siesta le ganaba al sueño; pero eso era
    aritmética del pack —0.30/8 rinde más por tick que 0.95/30— y meter la
    duración lo habría empeorado, castigando más a la acción larga. Aquello se
    arregla en el YAML; esto es otra cosa.

    Se aplica solo al beneficio, como el descuento por viaje: sobre el neto, una
    opción mala y larga parecería menos mala por durar. Y muy suave, o nadie
    dormiría nunca: a 0.995, treinta ticks cuestan un 14 % y ocho un 4 %.

    1.0 lo desactiva, y es el valor por defecto.
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
