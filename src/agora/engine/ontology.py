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
SituationId = NewType("SituationId", str)
RelationId = NewType("RelationId", str)
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

    El alivio satura: `relief * n/(n+company_scale)`. Con la escala a 1 una
    persona da la mitad del máximo y tres dan tres cuartos; en un mundo poblado
    hay que subirla, o una sala llena vuelve la necesidad irrelevante. **Ese fue
    exactamente el fallo del vínculo en la ciudad**: con ocupación media de 14.4
    y escala 1, el alivio pasivo cubría el 94% del decaimiento y la soledad no
    llegó a apretar ni una vez en 256 000 muestras.

    **Nunca por encima del `decay_per_tick`**, y lo comprueba el validador. Igual
    es el máximo útil: la compañía **frena** la necesidad pero nunca la llena, y
    para llenarla hay que actuar. Por encima, la necesidad SUBIRÍA sola por estar
    en una multitud, dejaría de ser satisfacible por acciones y el bucle social
    entero moriría sin que nada fallase.

    Es la diferencia entre estar acompañado y estar acompañado por alguien.
    """

    rank_slowdown: float = Field(default=0.0, ge=0.0)
    """Convierte este eje en **rangos numerados**. 0.0 lo desactiva.

    **Un eje con rangos no tiene techo.** El valor sigue viviendo en `[0, 1]` y
    significa *cuánto llevas de este rango*; al llenarlo, el rango sube uno y el
    valor vuelve a empezar. Siempre se puede ser más fuerte, y **siempre cuesta
    más que la vez anterior**.

    El número dice cuánto se frena, como exponente sobre el rango:

        ritmo(rango) = ritmo_base / (1 + rango) ** rank_slowdown

    Con 1.0 es **inversamente proporcional**: el rango 3 sube a un cuarto de
    velocidad que el 0. Con 0.5 la cuesta es suave; con 2.0, brutal.

    **Por qué frena, y no es una perilla de dificultad.** A un novato todo le es
    nuevo y cualquier cosa le enseña; a un maestro ya casi nada. La cuesta no
    modela que el mundo se ponga difícil: modela que **queda menos por
    aprender**.

    Y de aquí sale, sin sistema de niveles ni tabla de nombres, que el tiempo
    hasta el rango N crezca con el cuadrado de N. Con `rank_slowdown: 1.0` y un
    ritmo base que llene el primer rango en medio día:

        rango  5   ~8 días        rango 20   ~110 días       rango 50   ~2 años

    Nadie termina. Los rangos altos son raros porque cuestan, no porque un tope
    los prohíba — que es lo que un `cap` plano nunca pudo dar.

    **Reemplaza al techo plano para los ejes de progresión.** Medido: un `cap`
    fijo hacía que la gente llegara a su tope ANTES y el contenido que dependía
    del eje se muriera aún más deprisa. Ver `ERRORES` E-002.
    """

    lethal_after: int = Field(default=0, ge=0)
    """Cuántos ticks seguidos a cero puede aguantarse esto antes de morirse.
    **0 = nunca mata**, y es el defecto.

    **El motor no puede saber que el hambre mata.** Que un eje sea mortal es
    ambientación pura: en un mundo el sustento mata en tres días, en otro el
    aire mata en dos minutos y en otro nada mata a nadie. Por eso se declara por
    necesidad y aquí, en el pack, y por eso el motor no menciona ninguna.

    **En ticks y no en días** por lo mismo que `bond_horizon`: el reloj lo define
    el pack, y hablar en días obligaría a este archivo a saber cuántos ticks
    tiene uno.

    Se cuenta a **valor cero**, no por deuda. Los dos servían, y el valor gana
    por legible: *tres días sin comer y te mueres* es una regla que quien juega
    aprende, mientras que un umbral de deuda depende de `max_debt` y de la tasa
    de decaimiento, y no se puede contar en una frase. La deuda sigue midiendo
    **cuán hundido** estás; esto mide **cuánto llevas hundido**, que es otra cosa.

    Determinista y sin sorteo, a diferencia de los disparadores. Ahí el azar
    evita que el mundo sea un guion; aquí lo estropearía: una regla que a veces
    mata a los tres días y a veces a los cinco no se puede aprender, y la
    variedad ya está donde tiene que estar — en que cada cual llega a cero
    cuando llega, por sus decisiones y su suerte.
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

    cap: float = Field(default=1.0, gt=0.0, le=1.0)
    """Hasta dónde llega este eje para **quien no tiene nada especial**. 1.0 = sin
    techo, que es el mundo de siempre.

    Existe porque un ritmo no es un techo, y confundirlos rompe cualquier sistema
    de progresión en cuanto la corrida es larga. Con `gain_multipliers` bajo se
    tarda más en llegar a 1.0; con tiempo suficiente **todo el mundo llega**. Se
    midió: doscientos agentes, año y medio, y los doscientos acabaron al máximo
    del eje de dominio. Bajar la tasa solo habría movido la fecha.

    Un techo, en cambio, es escala-invariante: a los diez años la distribución
    sigue abierta, porque quién llega adonde deja de ser cuestión de tiempo y
    pasa a ser cuestión de quién eres.

    Se declara BAJO y los rasgos lo suben (`TraitSpec.cap_multipliers`), no al
    revés. Es lo que hace que el sistema diga lo que quiere decir: cualquiera
    puede aprender algo hasta cierto punto, y solo quien tiene el don lo pasa.
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

    COMPANIONSHIP = "companionship_weight"
    """Cuánto atrae la gente. Alto: busca el bullicio. Bajo: le da igual.

    Era la única de las cinco que el mundo fijaba **para todos por igual**: una
    taberna llena atraía exactamente lo mismo a un juerguista que a un ermitaño,
    y el pack no tenía forma de decir lo contrario. Con la soledad barata daba
    igual; en cuanto el eje social empieza a apretar, un empuje universal hacia
    el bullicio es la receta del rebaño.
    """

    # -- las cinco que eran del mundo y tenían que ser de la persona ----------
    #
    # Salieron de pasar el catálogo por la lista OCEAN, que como modelo de
    # personalidad no sirve aquí —es descriptivo, no generativo— pero como lista
    # de comprobación es excelente. El resultado:
    #
    #     E  Extraversión      entera             `companionship_weight`
    #     N  Neuroticismo      a medias           falta cuánto te marca lo malo
    #     C  Responsabilidad   a medias           faltaba `switch_cost`
    #     O  Apertura          NO SE PODÍA        faltaba `novelty_weight`
    #     A  Amabilidad        NO SE PODÍA        sigue faltando
    #
    # Dos de los cinco factores fallaban por la misma causa: perillas que
    # deberían ser del individuo se habían quedado siendo del mundo.

    NOVELTY = "novelty_weight"
    """Cuánto castiga el hastío. **Es la Apertura.**

    Alto: necesita variedad y se cansa de lo repetido. Bajo: hace lo mismo cada
    día sin aburrirse — y eso no es un defecto, es media población real.
    """

    SWITCH_COST = "switch_cost"
    """Cuánto protege lo ya invertido. **Es la Responsabilidad.**

    Alto: termina lo que empieza. Bajo: lo suelta en cuanto aparece algo mejor.
    """

    LEARNING_RATE = "learning_rate"
    """Cuánto corrige sus expectativas tras cada experiencia.

    Alto: se fía de lo último que le pasó. Bajo: **dogmático** — tarda mucho en
    aceptar que algo cambió. No es listura: es cuánto pesa la evidencia nueva
    frente a lo que ya creía.
    """

    BOND_RATE = "bond_rate"
    """Cuánto le mueve el aprecio un rato compartido. **Media del apego.**"""

    BOND_FADE = "bond_fade"
    """Cuánto conserva el aprecio sin ver a alguien. **La otra media.**

    Con `BOND_RATE` salen los estilos de apego casi literales, y sin escribir una
    sola regla de apego:

        ansioso     rate ↑↑  fade ↑     se engancha rápido y no suelta
        evitativo   rate ↓   fade ↓     tarda en querer y olvida pronto
        seguro      los dos al centro

    Ojo con la dirección: **más alto = olvida más despacio**, como
    `memory_multipliers`. Es la fracción que sobrevive por tick.
    """


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

    cost_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Quinto canal: **temple**. Cuánto le cuesta a esta persona lo que gasta.

    Espejo exacto de `gain_multipliers`, sobre el otro lado del intercambio:

        need_weight_multipliers  ->  cuánto le IMPORTA
        gain_multipliers         ->  cuánto le CUNDE lo que gana
        cost_multipliers         ->  cuánto le DUELE lo que gasta

    Faltaba, y su ausencia estaba escrita en el docstring de la aptitud: *"la
    aptitud escala lo que se GANA, no lo que cuesta"*. Eso deja sin expresar una
    familia entera de personas y de criaturas: quien aguanta el frío, quien
    trabaja sin cansarse, quien tiene una reserva grande.

    **Es la perilla que un sistema de maná pide por todas partes.** Reserva de
    maná no es más que "cada conjuro me drena menos"; una afinidad de nacimiento
    frente a una aprendida es lo mismo más barato; la resistencia de una raza al
    retroceso ambiental es esto sobre el eje que el retroceso muerde. Sin este
    canal, las tres solo se pueden fingir subiendo lo que se gana, que no es lo
    mismo y se nota en cuanto uno mira la contabilidad.

    Se compone como los demás —el multiplicador elevado a la intensidad— y de ahí
    sale gratis un detalle bonito: con `0.5` y un rasgo a intensidad plena el
    coste es la mitad; a intensidad 0.4 es 0.76. Una afinidad de nacimiento y una
    aprendida son **el mismo rasgo a distinta intensidad**, sin mecanismo nuevo.

    Multiplica cualquier efecto NEGATIVO sobre ese eje: lo que cuesta una acción
    y lo que te hace una situación. No toca los peajes —un porte vale lo que
    vale, no menos por ser tú— ni el decaimiento, que es el reloj del cuerpo y
    tiene su propio canal en la aptitud.
    """

    cap_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Sexto canal: **el don**. Hasta dónde puede llegar esta persona en un eje.

        need_weight_multipliers  ->  cuánto le IMPORTA
        gain_multipliers         ->  cuánto le CUNDE lo que gana
        cost_multipliers         ->  cuánto le DUELE lo que gasta
        cap_multipliers          ->  hasta DÓNDE puede llegar

    Multiplica el `cap` que declara la necesidad, y el resultado se recorta a 1.0
    — nadie pasa del tope del mundo por muy dotado que sea.

    **Sube un techo bajo; no baja uno alto**, y esa dirección es la que hace que
    el sistema diga lo que quiere decir. La necesidad declara lo que alcanza
    cualquiera con empeño; el rasgo dice quién lo pasa. Al revés —techo alto que
    los rasgos bajan— habría que enumerar en cada persona todo lo que NO se le da
    bien, que es infinito.

    Y de ahí sale, sin caso especial, la regla de una afinidad de nacimiento
    frente a una aprendida. Con `cap` 0.35 en el eje y un multiplicador de 2.8:

        de nacimiento (intensidad 1.00)  ->  0.35 * 2.8      = 0.98
        aprendida     (intensidad 0.35)  ->  0.35 * 2.8**.35 = 0.50

    El mismo rasgo, la misma aritmética de siempre —el multiplicador elevado a la
    intensidad— y el resultado es que con tu elemento llegas a lo más alto y con
    el que estudiaste te quedas a mitad de camino. Una raza mueve ese número
    encima, y ahí caben desde el humano hasta el demonio que no tiene techo.
    """

    memory_multipliers: PositiveFactor = 1.0
    """Séptimo canal: **cuánto le DURA**. Multiplica la media vida de lo que
    recuerda.

    Un número suelto y no un diccionario, a diferencia de los seis anteriores.
    Los otros canales dicen algo por eje —te importa el descanso, se te da bien
    pelear— pero olvidar despacio no es una propiedad de *qué* recuerdas: es
    tuya. Partirlo por eje sería inventar una precisión que nadie puede escribir.

    **Existe por una limitación real y medible.** `memory_fade` es un solo número
    del pack, así que hasta este canal los 127 habitantes olvidaban al mismo
    ritmo exacto. Con eso, dos duelos solo podían diferenciarse en cuánto pesaban
    el primer día —jamás en cuánto duraban— y quedaba fuera del motor la mitad
    de lo que significa perder a alguien: que uno lo supera en dos semanas y otro
    reordena su vida entera.

    Ojo con la dirección, porque es la contraria a la intuición: **más grande =
    recuerda más tiempo**. El multiplicador no escala el fade, escala la media
    vida; la aritmética vive en `compose_memory_fade` y es un exponente, no un
    producto, porque un fade multiplicado se sale de rango.

    En 1.0 no hace nada, que es el defecto y lo que garantiza que estrenar el
    canal no mueva ningún contrato ya medido.
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


class AflictionSpec(Spec):
    """Pegarle una condición a alguien. **Una sola forma para los tres sitios.**

    La usan `ActionSpec.inflicts` (lo que hacer algo te hace a ti), la de
    `SituationSpec` (lo que el mundo le hace a quien alcanza) y la de
    `TargetSpec` (lo que le haces a otro). Tres formas distintas para la misma
    idea habrían divergido —una con plazo, otra sin, una con marca, otra no— y
    entonces *infligir* dejaría de significar lo mismo según dónde se escriba.

    Es también lo que le faltaba a `TargetSpec`, que hasta aquí solo sabía pegar
    condiciones **permanentes**: no había forma de envenenar a alguien un rato.
    """

    situation: SituationId
    """Cuál. Tiene que ser `personal`; se valida en el pack."""

    marca: str = ""
    """Con qué marca. Ver `Condicion.marca`: dos idénticas agravan, distintas se
    apilan. Vacía para lo que no tiene partes."""

    gravedad_min: float = Field(default=1.0, gt=0.0)
    gravedad_max: float = Field(default=1.0, gt=0.0)
    """Cuán grave sale. Se sortea en ese rango cada vez.

    Con los dos iguales sale fija. Con rango, **un mismo brote reparte fiebres
    leves y fiebres que matan** — la misma enfermedad vivida de dos maneras, sin
    declarar `fiebre_leve` y `fiebre_grave` como cosas distintas.
    """

    lasts: int = Field(default=0, ge=0)
    """Cuánto dura, en ticks. **0 = hasta que alguien la quite.**

    Las dos formas hacen falta y no son intercambiables: un veneno se pasa, una
    infección no se pasa sola y por eso da miedo.
    """

    chance: float = Field(default=1.0, gt=0.0, le=1.0)
    """Con qué probabilidad. 1.0 = siempre, y es el defecto.

    Determinista por defecto **a propósito**, al revés que los disparadores: una
    acción que a veces te hiere y a veces no es más difícil de leer que una que
    siempre lo hace, y la legibilidad es la regla rectora. Bajar a la sima
    costando siempre una herida es una regla que quien juega aprende.

    Pero en una situación la lectura se invierte. Los efectos de una situación se
    aplican **cada tick**, así que a 1.0 una ventisca heriría noventa y seis
    veces al día. Ahí el número bajo no es azar decorativo: es *cuánto aguantas
    a la intemperie antes de que te pase algo*, y sale gratis que el riesgo
    crezca con la exposición.

    El sorteo va por clave —agente, tick y de qué viene— así que el orden en que
    se resuelven no altera ninguno.
    """


class TargetSpec(Spec):
    """A quién le hace algo una acción, y qué le hace.

    **Se elige donde estás, no al planificar**, y esa es la decisión que hace
    barato todo esto. Meter el destinatario en la deliberación llevaría el
    espacio de 32 acciones por 25 lugares a multiplicarlo por 127 personas. Pero
    que además sería falso: no puedes saber que alguien sangra desde el otro lado
    del pueblo. Que solo se pueda apuntar a quien tienes delante sale de la misma
    regla que `sightings` —se delibera sobre lo que se sabe— y de paso cuesta
    nada.
    """

    gives: dict[NeedId, float] = Field(default_factory=dict)
    """Lo que recibe **el otro**. Positivo da, negativo quita.

    Negativo es agredir, y no hace falta nada más para que exista: quitarle
    sangre a alguien es lo mismo que darle de comer, con el signo cambiado.
    """

    cures: dict[SituationId, float] = Field(default_factory=dict)
    """Cuánta gravedad le quita **al otro** en cada condición. Solo personales.

    Es la mitad que faltaba de la regla de las heridas: `ActionSpec.cures` te
    cura a ti, esto cura a quien no puede curarse solo.
    """

    inflicts: AflictionSpec | None = None
    """Qué condición se le pega **al otro**.

    Herir, envenenar, contagiar, maldecir. Con `gives` negativo se le hace daño
    ahora; con esto se le deja algo encima que sigue doliendo después.
    """

    requires_condition: SituationId | None = None
    """Solo vale sobre quien lleve esto encima. `None` = sobre cualquiera.

    Es cómo se escribe *curar al herido*, y de paso resuelve la única cuestión de
    percepción que había aquí: una condición **se ve** cuando estás delante —
    alguien sangrando se nota— mientras que el valor exacto de sus necesidades
    no. Apuntar por condición y no por "quien peor esté" evita que el motor lea
    la ficha interna de nadie.
    """

    por_agravio: bool = False
    """Esta acción se dirige **a quien te hizo algo**, no a quien aprecias.

    Cambia las dos mitades de la elección de destinatario a la vez, y por eso es
    un modo y no dos perillas sueltas: la puerta pasa a mirar `min_agravio` en
    vez de `min_regard`, y el desempate pasa a ser *al que más le debes* en vez
    de *al que más quieres*. Con dos perillas independientes se podría escribir
    «solo a quien odio, y de esos al que más quiero», que no significa nada.

    **Es lo que convierte la violencia en algo que ocurre.** Agredir ya se podía
    escribir —un `gives` negativo, D-066— pero no había forma de apuntar a quien
    te lo merecía: `elegir_destinatario` iba siempre al que más aprecias, así que
    una paliza salía dirigida a tu mejor amigo.
    """

    min_agravio: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto te tiene que deber para que vayas a por él. Solo con `por_agravio`.

    Puerta dura, como `min_regard` y con el mismo aviso: úsala para lo que de
    verdad exige una cuenta pendiente. La versión blanda —*más probable cuanto
    más te deba*— es `agravio_weight`.
    """

    agravio_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto depende de CUÁNTO te deba. Espejo exacto de `regard_weight`.

        factor = (1 - agravio_weight) + agravio_weight * agravio

    Encoge, no veta. A 0.6, pegarle a un desconocido sigue valiendo el 40 %: la
    gente se pelea con desconocidos, solo que menos.
    """

    min_regard: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Aprecio mínimo para molestarse. 0.0 = con cualquiera.

    Puerta dura, y por eso el defecto la deja abierta: úsala solo para lo que de
    verdad exige cercanía. Para *la gente está poco dispuesta a ayudar a un
    mendigo* la herramienta es la de abajo, no esta — una puerta dura lo haría
    imposible, y lo que se pidió fue improbable.
    """

    regard_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto depende de a QUIÉN. 0 = da igual; 1 = solo compensa con quien quieres.

        factor = (1 - regard_weight) + regard_weight * max(0, aprecio)

    **Es la respuesta a "poco probable, no completamente improbable".** No veta:
    encoge la recompensa. Ayudar a un desconocido sigue valiendo algo, así que
    ocurre cuando no hay nada mejor que hacer — que es exactamente lo que le pasa
    a un mendigo herido en una calle con gente ocupada.

    A 0 se comporta como un servicio: vender pan a un extraño paga lo mismo que
    vendérselo a tu hermano. A 1, como un favor.
    """


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

    requires_rank: dict[NeedId, int] = Field(default_factory=dict)
    """Rango mínimo en un eje con rangos. **Novena puerta dura.**

    Es lo que `requires` no puede decir en un eje sin techo. Pedir
    `dominio: 0.30` significaba *«que lleves el 30 % de tu rango actual»* — que
    es cierto para un novato y para un maestro por igual, y por tanto no dice
    nada. Lo que un conjuro difícil quiere es **rango 3**.

    Separado de `requires` a propósito: aquel mira lo que tienes ahora —y se
    gasta— y esto mira lo que has llegado a ser, que no se pierde.
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

    requires_relation: RelationId | None = None
    """Solo se puede hacer con alguien de los tuyos delante. `None` = con
    cualquiera, o a solas.

    Sexta puerta dura, hermana de `requires_company`, y la diferencia entre las
    dos es exactamente la que hay entre un vínculo y una relación: aquella
    cuenta CABEZAS —una fiesta necesita cuerpos— y esta pregunta QUIÉN. Cenar en
    familia no se arregla con más gente.

    Es lo que impide que la capa relacional se quede en tintar números. Sin una
    puerta, tener una pareja solo haría que ciertos sitios apeteciesen un poco
    más; con ella hay cosas que solo existen si esa persona está.
    """

    target: TargetSpec | None = None
    """A quién le hace algo. `None` = a nadie, que es todo lo que había hasta aquí.

    **La mitad que le faltaba a la capa social.** Hasta este campo, `satisfies`,
    `effects` y `costs` caían siempre sobre quien actúa: el motor eran ciento
    veintisiete personas actuando sobre sí mismas en presencia de otras.
    `requires_company` y `requires_relation` parecen sociales y no lo son — son
    puertas, dicen quién tiene que ESTAR, no a quién le pasa nada.

    Eso dejaba cuatro cosas sin poder escribirse, y las cuatro se pidieron:
    curar a un herido que no puede curarse solo, que un recuerdo vaya sobre
    alguien (`about` salía al 0 % en los dos mundos grandes), que un rumor lleve
    noticias de personas en vez de expectativas, y que exista el rencor hacia
    alguien.

    **Y no hace falta que el motor sepa qué es el altruismo.** Ayudar paga lo que
    el pack diga que paga: la acción satisface algo de QUIEN ACTÚA —vínculo,
    propósito, reputación— y por eso se hace. Un motor de utilidad no necesita
    una primitiva para la generosidad; necesita que la generosidad tenga precio y
    premio, como todo lo demás.
    """

    inflicts: AflictionSpec | None = None
    """Lo que hacer esto **te hace a ti**. Bajar a la sima te hiere.

    **El campo que faltaba para que la muerte pudiera existir**, y eso salió de
    medir tres mundos. La muerte por agotamiento no ocurre en un mundo calibrado
    para ser habitable: ciudad y confluencia están las dos ajustadas para que
    nadie se bloquee, así que ningún eje se queda vacío el tiempo suficiente para
    matar. Medido — en confluencia el maná no llega a cero **ni una vez** en
    catorce días, y el eje más castigado del mundo aguanta medio día.

    Para que la muerte exista hace falta algo que drene **desde fuera de las
    decisiones del agente**. Un `costs` no vale: se paga una vez y se acabó, y el
    agente deja de hacer la acción cuando le duele. Una condición sigue sangrando
    hagas lo que hagas, y por eso hay que ir a que te la quiten.

    Se aplica **al terminar**, como `cures`, y por lo mismo: media faena no
    cuenta. Quien abandona a mitad se libra, que es lo razonable — y lo
    inabandonable ya se declara con `interruptible`.
    """

    cures: dict[SituationId, float] = Field(default_factory=dict)
    """Cuánta GRAVEDAD le quita a cada condición al terminar. Solo personales.

    Un número y no una lista, y ahí está la mitad del diseño de las
    enfermedades: **curar deja de ser todo o nada**. Una noche de sueño baja
    0.15 de fiebre y no hace nada por una pierna rota; un curandero se lleva 3.0
    de golpe. La condición se va cuando su gravedad llega a cero.

    De aquí sale el oficio de curandero sin escribir una sola regla nueva: es
    quien tiene una acción que quita mucha gravedad, exige ser quien hay que ser,
    y cobra por ello.

    La mitad *por acción* de cómo se sale de una condición; la otra mitad es el
    plazo, y las dos hacen falta. Sin plazo, una infección que nadie sabe curar
    mata a todo el mundo; sin acción, curarse no es algo que se pueda decidir y
    la condición deja de ser un problema con solución.

    Quita **todas las marcas** de esa condición de golpe, no una. Vendar sabe
    vendar heridas, no la del brazo derecho: el motor no puede saber qué es un
    brazo, así que tampoco puede saber cuál elegir, y elegir por `seq` sería
    inventarse un criterio médico.

    Se aplica al que ACTÚA. Curar a otro no existe todavía —ninguna acción tiene
    destinatario— y es lo que hace falta para que alguien pueda ayudar a un
    herido que no puede ayudarse solo.
    """

    situation_multipliers: dict[SituationId, PositiveFactor] = Field(default_factory=dict)
    """Cuánto apetece esto según cómo esté el mundo. Lo ausente vale 1.0.

    Gemelo exacto de `phase_multipliers` —multiplica el beneficio, no el neto—
    con una diferencia: pueden aplicarse **varias a la vez**, y entonces se
    multiplican entre sí. Feria y tormenta el mismo día se pisan, y eso es lo
    correcto: la feria bajo la lluvia luce menos.

    Ojo con la misma trampa que las franjas: no se lo pongas a lo fisiológico.
    Si comer valiera más durante la hambruna, la gente comería más justo cuando
    hay menos. Lo que baja durante una hambruna es lo que la comida RINDE
    (`SituationSpec.gain_multipliers`), no las ganas de comer.
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

    closed_during: frozenset[SituationId] = Field(default_factory=frozenset)
    """Situaciones que cierran este sitio. Vacío = no lo cierra ninguna.

    Gemelo de `open_during` y con el mismo carácter: puerta dura, no desánimo.
    La mina derrumbada no es menos atractiva, es que no está.

    Se declara al revés que `open_during` —lo que CIERRA, no lo que abre— porque
    una situación es la excepción y una franja es la norma: un sitio está
    normalmente abierto y una crisis lo cierra, mientras que un horario dice
    cuándo se abre. Escribirlo del otro modo obligaría a listar en cada lugar
    todas las situaciones del mundo que no le afectan.
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
    """En qué anda una meta. Cuatro estados y no hay más.

    Lo logrado y lo perdido son distintos aunque los dos dejen de empujar: mueven
    rasgos opuestos, y el narrador no puede contar igual a quien lo consiguió que
    a quien se quedó a las puertas.
    """

    LOCKED = "locked"
    """Todavía no le toca: espera a que se cumpla la que la abre.

    **Es lo que convierte metas sueltas en un arco.** Sin este estado, las cuatro
    metas de una ambición larga estarían abiertas a la vez, empujarían todas sus
    ejes desde el primer día y se cerrarían en cualquier orden — que es una lista
    de deseos, no una historia.

    No empuja nada mientras dura: `pursuing` solo devuelve las activas, así que
    una meta bloqueada no toca ni un peso.
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

    at_least: float | None = Field(default=None, gt=0.0, le=1.0)
    """Umbral **sobre el valor del eje** que cuenta como logrado.

    **Es un MOMENTO, no un arco, y hay que escribirlo sabiéndolo.** Lee el valor
    de ahora mismo, y una necesidad está hecha para llenarse: sobre suficientes
    ticks, todo el que trabaje su eje lo toca alguna vez. Medido en confluencia
    con el umbral al filo del máximo alcanzable y plazo de ciento veinte días:
    **119 metas cumplidas de 119, cero falladas**. No se arregla subiendo el
    número — por encima del máximo pasa a ser una lotería en vez de un arco.

    Para una ambición larga, `at_rank`.
    """

    at_rank: int | None = Field(default=None, ge=1)
    """Cuántos rangos hay que haber roto. Alternativa a `at_least`.

    **La ambición arquetípica de un mundo con rangos, y era la única que no se
    podía escribir.** Con `rank_slowdown`, el valor del eje vuelve a cero cada
    vez que se rompe un rango, así que un `at_least` sobre él se cumple con el
    primero y no significa nada. El rango, en cambio, **solo sube y no se
    reinicia**: es el único número de este motor que puede sostener un arco.

    Y trae su propia dificultad graduada sin declararla. Con la cuesta
    cuadrática de `rank_slowdown: 1.0`, el tiempo hasta el rango N crece con N²:

        rango  5   ~8 días        rango 20   ~110 días       rango 50   ~2 años

    Así que `at_rank` es a la vez el qué y el cuánto cuesta. Un arco de tres
    metas —rango 5, rango 12, rango 30— es una carrera entera sin que el pack
    tenga que calibrar tres plazos distintos.

    Exige que el eje tenga `rank_slowdown` > 0. Sin rangos, el número nunca sube
    y la meta sería inalcanzable; lo comprueba el validador en vez de dejar a
    alguien escorado de por vida hacia algo imposible.
    """

    at_traits: dict[TraitId, float] = Field(default_factory=dict)
    """Ser quien hay que ser: cada rasgo, al menos a esta intensidad.

    Es una **conjunción**: hacen falta todos. *«Dominar una segunda afinidad»* se
    escribe nombrando la que le falta a esa persona concreta, que el generador sí
    sabe cuál es — el motor no tiene forma de decir «dos cualesquiera de estas
    cuatro» y no la necesita.

    **Solo es alcanzable si algo mueve ese rasgo**, y hoy lo único que lo hace es
    el `on_success`/`on_failure` de otra meta. Eso no es una limitación de este
    campo: es exactamente el caso de uso — *graduarse* concede el rasgo que abre
    la meta siguiente. Lo comprueba el validador.
    """

    at_kin: dict[RelationId, int] = Field(default_factory=dict)
    """Tener a los tuyos: al menos esta cantidad de cada relación.

    También conjunción. *«Tener tres discípulos»* es `{"discipulo": 3}`.

    ⚠️ **Hoy nada crea ni deshace relaciones en marcha.** `begin_relation` y
    `end_relation` son API pública y ningún contenido las llama, así que esta
    condición se decide en el tick 0 y no vuelve a cambiar. Se implementa
    igualmente —es correcta y son cuatro líneas— pero **no escribas un arco que
    dependa de ella** hasta que una acción pueda anudar un lazo. El validador
    avisa cuando la meta ya está cumplida de salida.
    """

    requires_goal: GoalId | None = None
    """No empieza hasta que esta otra se haya LOGRADO. **Esto es el arco.**

    Sin un orden, las metas de una ambición larga están abiertas a la vez,
    empujan sus ejes desde el primer día y se cierran en cualquier orden — que es
    una lista de deseos, no una historia.

    Mientras espera, la meta está en `LOCKED`: **no empuja ningún peso y no puede
    fallar**. Lo segundo es deliberado — no puedes perder lo que aún no habías
    empezado, y un plazo que corre mientras estás bloqueado castigaría por algo
    que no dependía de ti. El plazo sigue siendo absoluto, así que desbloquear
    tarde deja poco tiempo, y eso sí es del personaje.

    Si la que la abre se **pierde**, esta se queda bloqueada para siempre. Es
    correcto y es la mitad del drama: quien no se gradúa no llega a intentar lo
    que venía después.

    **El arco es una etiqueta, no una estructura.** Aquí solo se declara de quién
    depende cada meta; agruparlas en un objeto «arco» obligaría a duplicar las
    que sirven a dos historias — *«llegar a rango 10»* es el primer paso del
    guerrero y también del líder.
    """

    @model_validator(mode="after")
    def _one_way_to_measure_it(self) -> GoalSpec:
        """Exactamente una condición. Ni cero ni dos.

        Con dos, habría que decidir si se cumple con una o con ambas, y
        cualquiera de las respuestas sería una convención que nadie recuerda al
        leer el pack. Y con la conjunción ya cubierta dentro de cada condición
        —`at_traits` y `at_kin` piden todo lo que nombran— lo que quedaría fuera
        es mezclar clases distintas de medida, que es justo lo que `requires_goal`
        hace mejor: dos metas encadenadas en vez de una con dos varas.

        Con ninguna, la meta no se puede cerrar jamás.
        """
        cuantas = (
            (self.at_least is not None)
            + (self.at_rank is not None)
            + bool(self.at_traits)
            + bool(self.at_kin)
        )
        if cuantas != 1:
            raise ValueError(
                f"meta {self.id!r}: hace falta EXACTAMENTE una condición de "
                f"`at_least` (el valor del eje), `at_rank` (rangos rotos), "
                f"`at_traits` (ser quien hay que ser) o `at_kin` (los tuyos), "
                f"y hay {cuantas}"
            )
        if self.requires_goal == self.id:
            raise ValueError(f"meta {self.id!r}: se abre a sí misma")
        return self

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

    relations: dict[RelationId, frozenset[AgentId]] = Field(default_factory=dict)
    """De quién es qué. Se declara UNA vez y el motor pone la otra mitad.

    Simétricas e inversas se materializan solas al construir el mundo, así que
    escribir la hermandad de A con B ya hace a B hermano de A. Obligar a
    escribirlo dos veces garantizaría que antes o después falte una de las dos.
    """

    initial_bonds: dict[AgentId, float] = Field(default_factory=dict)
    """Aprecio de partida hacia otros. Vacío = el mundo empieza sin conocerse.

    Es la otra mitad de lo que hacía falta para un mundo con historia previa.
    Una relación dice QUÉ son el uno del otro; esto dice CÓMO se llevan, que no
    es lo mismo y a menudo no coincide: dos hermanos que se detestan son dos
    hermanos, y el pack tiene que poder escribirlo.

    Sin esto, cualquier mundo empezaba con todos siendo desconocidos entre sí,
    y las primeras semanas de cualquier corrida eran el mundo presentándose.
    """

    @model_validator(mode="after")
    def _traits_in_range(self) -> AgentSpec:
        for trait, value in self.traits.items():
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"rasgo {trait!r} = {value}, fuera de [-1, 1]")
        for other, regard in self.initial_bonds.items():
            if not -1.0 <= regard <= 1.0:
                raise ValueError(f"aprecio inicial hacia {other!r} = {regard}, fuera de [-1, 1]")
        for relation, quienes in self.relations.items():
            if self.id in quienes:
                raise ValueError(f"relación {relation!r}: {self.id!r} lo es de sí mismo")
        if self.id in self.initial_bonds:
            raise ValueError(f"agente {self.id!r}: aprecio inicial hacia sí mismo")
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

    max_muertes: int | None = Field(default=None, ge=0)
    """Cuántos pueden morirse antes de que el mundo esté roto. `None` no lo mira.

    Hace falta desde que existe `lethal_after`, y en las dos direcciones. Un
    mundo que mata a la mitad de sus habitantes en tres semanas no es peligroso,
    está mal calibrado — y sin este número el panel lo celebraría, porque la
    diferenciación y la geografía se calculan sobre quien queda.

    Se declara en absoluto y no en fracción a propósito: **cero es una respuesta
    legítima y la más común**, y `0.0` en un campo de fracción se confunde con
    *no lo he pensado*.
    """

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

    days_per_year: int = Field(default=360, ge=1)
    """Cuántos días tiene el año largo. De aquí cuelgan las estaciones.

    **Existía ya, pero sin nombre.** La ciudad declara el invierno con
    `every: 34560`, que son 360 por 96 — el año estaba escrito en un número
    multiplicado a mano dentro de una situación, y en ningún sitio decía que
    fuera un año. El día que alguien quisiera cambiarlo tendría que encontrar y
    recalcular cada `every` del pack.

    Lo estrena `TriggerSpec.expected_per_year`, que necesita saber contra qué
    período se cuenta. Un disparador declarado en probabilidad por tick sería
    incalibrable a ojo: tres ventiscas por invierno son 0.00035, y un pack lleno
    de números así no se puede leer ni discutir.
    """

    @property
    def ticks_per_year(self) -> int:
        return self.days_per_year * self.ticks_per_day

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
# Relaciones: qué es uno de otro
# ---------------------------------------------------------------------------
class RelationSpec(Spec):
    """Un lazo con nombre entre dos personas. El motor no sabe qué es un hermano.

    **Un vínculo es lo que sientes; una relación es lo que ERES de alguien.** La
    distinción es de fondo y por eso son dos cosas y no una:

    - `Bond` es emergente, asimétrico, gradual y se olvida. Sale de compartir
      ratos y se desdibuja si dejas de verte.
    - Una relación es un HECHO. No crece con el trato ni se disuelve por dejar
      de verse. Tu hermano sigue siendo tu hermano el año que no lo visitas, y
      lo sigue siendo el día que lo detestas.

    Meterlo dentro de `Bond` habría sido tentador y habría hecho imposible
    justamente eso: un aprecio con nombre se disolvería con el aprecio.

    De aquí salen la pareja, la familia, el maestro y el discípulo, la deuda y
    la enemistad declarada — y es la pieza que faltaba para que más adelante
    haya descendencia, porque nacer es exactamente crear dos relaciones.

    Una relación puede no hacer NADA mecánicamente y seguir siendo legítima.
    Eso la separa de una situación, que si no afecta a nada es contenido muerto:
    aquí el hecho ya vale por sí solo — es lo que el narrador necesita saber y
    lo que la descendencia va a leer.
    """

    id: RelationId
    label: str

    symmetric: bool = False
    """Si vale en los dos sentidos con el mismo nombre. Hermano sí, maestro no.

    Declararla una vez basta: el motor pone la otra mitad. Si no, el pack
    tendría que escribir cada hermandad dos veces y una de las dos acabaría
    faltando — un mundo donde A es hermano de B pero B no lo es de A.
    """

    inverse: RelationId | None = None
    """La que se crea del otro lado cuando es dirigida: maestro <-> discípulo.

    Alternativa a `symmetric`, no complemento: una relación o vale igual en
    ambos sentidos o se llama distinto en cada uno.
    """

    exclusive: bool = False
    """Como mucho una persona. Pareja sí, hermano no.

    Se comprueba al declararla y al crearla en marcha, porque es el invariante
    que va a sostener la descendencia: dos parejas simultáneas no es una regla
    moral, es un árbol genealógico que deja de poder leerse.
    """

    regard_floor: float | None = Field(default=None, ge=-1.0, le=1.0)
    """Suelo del aprecio hacia esa persona. `None` = ninguno.

    **`None` y `0.0` no son lo mismo**, y confundirlos costó un test: un suelo en
    cero aplasta el aprecio negativo, así que una relación sin suelo declarado
    haría imposible detestar a un hermano. `None` no toca nada; `0.0` es un
    suelo de verdad, el de quien nunca llega a caerte mal del todo.

    Es lo que hace que una relación se NOTE sin convertirla en un vínculo: el
    aprecio sigue subiendo y bajando con lo que se comparte, pero no cae por
    debajo de aquí. La familia se aguanta.

    También es el punto de partida: quien empieza siendo pareja de alguien no
    empieza siendo un desconocido.
    """

    company_multiplier: PositiveFactor = 1.0
    """Cuánto pesa su presencia frente a la de un desconocido de igual aprecio.

    Multiplica dentro de `effective_company`, así que un plan donde estará tu
    pareja atrae más que el mismo plan con alguien que te cae igual de bien. Es
    la diferencia entre apreciar a alguien y que ese alguien sea de los tuyos.
    """

    @model_validator(mode="after")
    def _one_way_of_being_two_sided(self) -> RelationSpec:
        if self.symmetric and self.inverse is not None:
            raise ValueError(
                f"relación {self.id!r}: es simétrica y además declara `inverse` "
                f"{self.inverse!r}. O vale igual en ambos sentidos, o se llama "
                f"distinto en cada uno"
            )
        if self.inverse == self.id:
            raise ValueError(
                f"relación {self.id!r}: su propia inversa. Eso es `symmetric: true`"
            )
        return self


# ---------------------------------------------------------------------------
# Situaciones: cómo está el mundo
# ---------------------------------------------------------------------------
class TriggerSpec(Spec):
    """Cuándo se enciende sola una situación eventual.

    **Es la primera pieza del motor que crea sucesos sin que nadie los decida**,
    y eso la hace peligrosa de una forma que ninguna otra lo es. El plan lo dejó
    escrito: *si se le da demasiada cuerda, el mundo pasa de vivo a aleatorio, y
    eso destruye la legibilidad*, que es la regla rectora del proyecto.

    De ahí los cuatro frenos, y ninguno es opcional:

    - **probabilidad baja**, declarada en veces por año y no por tick
    - **cooldown obligatorio**, validado aquí y no descubierto midiendo
    - **el log dice por qué** se encendió, no solo que se encendió
    - **apagado por defecto** (`expected_per_year = 0`), para que estrenarlo no
      pueda mover ningún contrato ya medido

    Y hay un quinto que no vive aquí sino en el panel: `--divergence` mide cuánto
    pesa el azar frente al carácter. Si al girar estas perillas ese número se
    acerca a 1, el mundo se volvió aleatorio y hay que apretar.
    """

    expected_per_year: float = Field(default=0.0, ge=0.0)
    """Cuántas veces se espera que ocurra en un año. **0.0 lo desactiva.**

    En veces por año y no en probabilidad por tick a propósito. Tres ventiscas
    por invierno son 0.00035 por tick, y un pack lleno de números así no se puede
    leer ni discutir: nadie sabe si 0.00035 es mucho. Tres al año sí se sabe.

    El motor divide entre `clock.ticks_per_year`. Como consecuencia, cambiar la
    duración del tick no cambia con qué frecuencia pasan las cosas — que es lo
    que uno espera y lo que la forma cruda no daba.

    **Ojo con el nombre cuando hay condición.** Es la tasa *como si el disparador
    estuviera siempre habilitado*. Con `requires_situations`, los ticks en que la
    condición no se cumple no cuentan, así que salen menos: una ventisca a 4 por
    año que solo pueda caer en invierno —tres meses de doce— sale a **una**. El
    cooldown recorta otro tanto. Calibrar es mirar el panel, no la aritmética.
    """

    lasts_min: int = Field(default=1, ge=1)
    lasts_max: int = Field(default=1, ge=1)
    """Cuánto dura, en ticks. Se sortea en el rango cada vez que enciende.

    Es un rango y no un número porque el peligro tiene dos lados. Una tormenta
    que siempre dura exactamente doscientos ticks no es aleatoria, es
    **guionizada**, y un mundo guionizado es tan ilegible como uno al azar: el
    jugador aprende el número y deja de haber sorpresa. Con `lasts_min` igual a
    `lasts_max` se recupera la duración fija, si un pack la quiere.
    """

    cooldown: int = Field(default=0, ge=0)
    """Ticks que tienen que pasar desde que encendió hasta que puede volver.

    Obligatorio cuando el disparador está activo, y validado abajo. Sin él, una
    situación que acaba de terminar puede reencenderse al tick siguiente, y lo
    que el pack escribió como *una oleada de vez en cuando* se convierte en una
    oleada permanente con parpadeos.

    Se cuenta desde el ENCENDIDO y no desde el final, así que tiene que ser mayor
    que `lasts_max` o no separa dos episodios: sería el cooldown corriendo
    mientras la cosa todavía pasa.
    """

    requires_situations: frozenset[SituationId] = Field(default_factory=frozenset)
    """Solo puede encenderse mientras TODAS estas están activas. Vacío = siempre.

    Con esto la ventisca solo cae en invierno, sin ningún mecanismo nuevo: es la
    misma composición que ya hacen `closed_during` y `situation_multipliers`.

    Y es lo que hace que salgan solos los **arcos del mundo** que el plan
    prometía: una oleada que enciende la tensión, y una tensión que —si dura—
    habilita la guerra. Encadenar disparadores no pide primitiva nueva, pide
    esta línea.
    """

    @model_validator(mode="after")
    def _the_brakes_are_on(self) -> TriggerSpec:
        if self.lasts_min > self.lasts_max:
            raise ValueError(
                f"disparador: dura entre {self.lasts_min} y {self.lasts_max} ticks, "
                f"que es un rango al revés"
            )
        if self.expected_per_year <= 0.0:
            return self  # apagado: lo demás da igual
        if self.cooldown <= 0:
            raise ValueError(
                "disparador activo sin cooldown: la situación se reencendería al "
                "tick siguiente de apagarse, y lo que el pack quiso decir con "
                "'de vez en cuando' sería 'siempre, con parpadeos'"
            )
        if self.cooldown <= self.lasts_max:
            raise ValueError(
                f"disparador: cooldown {self.cooldown} no supera la duración máxima "
                f"{self.lasts_max}. Se cuenta desde el encendido, así que expiraría "
                f"mientras la situación todavía está pasando y no separaría nada"
            )
        return self


class SituationSpec(Spec):
    """Un estado del mundo con nombre, que va y viene, y cambia lo que se hace.

    Una franja es una función del tick: cíclica, siempre hay exactamente una, y
    no se puede empezar ni terminar. Eso sirve para la noche y no sirve para una
    guerra. **Una situación es lo mismo un escalón más arriba: tiene principio y
    final, pueden coincidir varias, y algunas no se sabe cuándo llegan.**

    Con una sola primitiva salen el clima, las ferias, las cosechas, las crisis,
    las guerras y las oleadas de monstruos. El motor no sabe cuál es cuál: sabe
    que hay estados con nombre que multiplican cosas.

    Dos formas de estar activa, y hacen falta las dos:

    - **Periódica** (`every` + `lasts`): función del tick, igual que una franja.
      Las estaciones, la feria de cada primavera, la luna llena. No guarda
      estado, así que sale gratis y sobrevive al salto temporal sin tocar nada.
    - **Eventual** (ni `every` ni `lasts`): solo está activa si alguien la
      enciende. La guerra, el derrumbe, la oleada. Esa sí es estado mutable, se
      guarda en la partida y emite eventos al empezar y al acabar.

    Y tres formas de afectar, cada una copiada de donde ya existía:

    - `gain_multipliers`, igual que en un lugar o un rasgo: lo que de verdad
      rinde. Una hambruna hace que comer alimente menos, que es lo que ES una
      hambruna.
    - `ActionSpec.situation_multipliers`, igual que `phase_multipliers`: lo
      atractivo que resulta hacer algo. Durante la feria apetece salir.
    - `PlaceSpec.closed_during`, igual que `open_during`: puerta dura. La mina
      derrumbada no es menos atractiva, es que no está.
    """

    id: SituationId
    label: str

    places: frozenset[PlaceId] = Field(default_factory=frozenset)
    """Dónde alcanza. **Vacío = en todo el mundo**, como `open_during` vacío es
    siempre abierto.

    Es lo que separa una guerra —que lo tiñe todo— de una feria en la plaza. El
    alcance se declara aquí y no al encenderla: así el pack dice de una vez qué
    clase de cosa es, y encenderla es solo encenderla.

    No lo mira una situación `personal`: esas viajan con quien las lleva.
    """

    personal: bool = False
    """Esto le pasa a **alguien**, no a un sitio. Una herida, una infección, un
    veneno, una borrachera, una maldición.

    **No es una primitiva nueva, es un alcance nuevo para la que ya había.** Una
    situación ya era exactamente lo que hace falta —un estado con nombre, que va
    y viene, que multiplica lo que rinde y lo que cuesta, y que puede hacer daño—
    y lo único que le faltaba era poder pegarse a una persona en vez de a un
    lugar. Toda la maquinaria de aplicar el daño ya era por agente: el bucle del
    tick llama a `endure` uno por uno, y lo único que se consultaba por lugar era
    *cuáles te alcanzan*.

    Y de ahí sale, sin mecanismo de muerte nuevo, todo lo que no era agotamiento.
    Una hemorragia no es *morir de pérdida de sangre*: es un estado que llevas y
    que te drena, y morirse es lo que pasa si nadie lo para. Eso ya lo cobra
    `lethal_after`. Una sola regla de muerte y tantas causas como el pack quiera:

        herida       effects {sangre: -0.02}   lasts 200
        infeccion    effects {salud: -0.005}   lasts 0     hasta que la curen
        veneno       effects {salud: -0.05}    lasts 40
        atravesado   effects {sangre: -1.0}    lasts 1

    Incompatible con `places` y con `every`: lo que le pasa a una persona no
    ocurre en un sitio ni vuelve por calendario. Se valida en el pack.
    """

    every: int = Field(default=0, ge=0)
    """Cada cuántos ticks vuelve. 0 = no es periódica, hay que encenderla.

    Es `PhaseSpec.starts_at` a otra escala, y no es casualidad: una estación es
    una franja de un ciclo más largo. Por eso no hace falta un mecanismo nuevo.
    """

    lasts: int = Field(default=0, ge=0)
    """Cuánto dura cada vez que vuelve, en ticks. Solo cuenta si `every` > 0."""

    starts_at: int = Field(default=0, ge=0)
    """En qué punto del ciclo largo empieza. Para que el invierno no caiga
    siempre en el tick 0 del año."""

    gain_multipliers: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Cuánto cunde lo que se hace mientras esto pasa. Lo ausente vale 1.0.

    Cuarto y último factor de la regla que ya gobernaba el rendimiento:

        lo que rinde algo  =  base * aptitud de quien lo hace
                                   * calidad del sitio
                                   * cómo está el mundo
    """

    effects: dict[NeedId, float] = Field(default_factory=dict)
    """Lo que le hace, cada tick, a quien esté dentro de su alcance.

    **El cuarto canal, y el único que le pasa algo a alguien.** Los otros tres
    modulan: `gain_multipliers` cambia lo que rinde, `situation_multipliers`
    cambia lo que apetece, `closed_during` cierra un sitio. Ninguno puede hacer
    daño, y esa ausencia se veía sin mirar el código: una oleada de monstruos
    disparada sobre la sima significaba, exactamente, que apetecía más aceptar
    contratos del gremio.

    Deltas por tick, con la misma forma y el mismo signo que los de una acción:
    negativo quita, positivo da. Se aplican por `AgentState.endure`, que los
    archiva en el libro como demanda o como **pasivo** —lo que llega sin actuar—,
    nunca como activo.

    Van **por tick y no de una vez al empezar**, y la diferencia importa: una
    ventisca castiga mientras dura, así que huir de ella funciona y quedarse
    cuesta. Aplicarlos de golpe al encender premiaría llegar tarde.

    Ojo a la escala. Se multiplican por la duración: 0.002 durante trescientos
    ticks son 0.6 de necesidad, que es una catástrofe. Los números aquí son mucho
    más pequeños que los de una acción, que ocurre una vez.
    """

    temperament_multipliers: dict[TemperamentKnob, PositiveFactor] = Field(
        default_factory=dict
    )
    """Cómo decide quien la lleva encima. **Solo tiene sentido en las personales,
    y es lo que convierte una condición en un ESTADO DE ÁNIMO.**

    Hasta aquí, una condición solo sabía **drenar**. Podía quitarte salud día
    tras día, pero no podía cambiar en nada cómo decidías — así que enfadado,
    abatido y agotado eran indistinguibles: el mismo valor bajo en un eje.

    Y resulta que la forma ya estaba hecha. Una `Condicion` tiene **duración,
    gravedad y origen**; le faltaba hacer lo que un ánimo hace:

        E(id="abatido", personal=True, lasts=480,
          gain_multipliers={"vinculo": 0.6},
          temperament_multipliers={"companionship_weight": 0.5,
                                   "critical_need_threshold": 1.4})

    Te lo pega una muerte, dura cinco días, y mientras tanto rindes menos con la
    gente y te alarmas antes. **Sin primitiva nueva**: llega por `inflicts` desde
    cualquier evento o acción, se va por `lasts` o porque alguien lo cure, y la
    gravedad dice cuánto.

    De aquí sale la distinción que faltaba: **el rasgo es quién eres, el ánimo es
    cómo estás hoy.** Uno es fijo y el otro va y viene.

    **Se compone con la gravedad como exponente** —`multiplicador ** gravedad`—
    igual que la intensidad de un rasgo (D-030), y no como producto: con 0 el
    ánimo no hace nada y con el doble de gravedad invierte al cuadrado en vez de
    salirse de rango. Los `effects` sí van lineales, y es correcto que difieran:
    un daño se suma, un multiplicador se compone.
    """

    inflicts: AflictionSpec | None = None
    """Lo que le pega a quien alcanza. La ventisca te deja congelado.

    Quinto canal de las situaciones, y el que cierra el juego: hasta aquí una
    situación podía multiplicar lo que rinde, lo que apetece, cerrar un lugar y
    hacer daño **de golpe**. Lo que no podía era dejarte algo encima que siguiera
    doliendo después de que el temporal pasara.

    Y esa es la diferencia entre un mal rato y una consecuencia. Un `effects`
    negativo se recupera en cuanto la situación acaba; una condición te sigue a
    casa, y hay que ir a que te la quiten.

    **Ojo con `chance` aquí.** Los efectos de una situación se aplican cada tick,
    así que a 1.0 —el defecto— una ventisca te heriría noventa y seis veces al
    día. En una situación el número bajo no es azar decorativo: es *cuánto
    aguantas a la intemperie antes de que te pase algo*, y sale gratis que el
    riesgo crezca con la exposición.
    """

    trigger: TriggerSpec | None = None
    """Qué la enciende sola. `None` = solo se enciende llamando a la API.

    Vive dentro de la situación y no en una lista aparte de disparadores porque
    son la misma cosa vista dos veces, y separarlas crearía una clase entera de
    error —el disparador que apunta a una situación que ya no existe— por ningún
    beneficio: nadie ha pedido todavía dos disparadores para lo mismo.
    """

    @model_validator(mode="after")
    def _only_the_eventual_can_be_triggered(self) -> SituationSpec:
        """Una periódica con disparador es una contradicción, y silenciosa.

        `begin_situation` ya rechaza encender una periódica a mano por la misma
        razón: querría decir que quien la escribió cree que es eventual, y ese
        malentendido no se ve en el log — la situación iría sola de todos modos y
        el disparador parecería funcionar.
        """
        if self.trigger is not None and self.every:
            raise ValueError(
                f"situación {self.id!r}: es periódica (cada {self.every} ticks) y "
                f"además declara un disparador. Va sola; el disparador no haría "
                f"nada y daría a entender lo contrario"
            )
        return self

    @model_validator(mode="after")
    def _periodic_situations_actually_happen(self) -> SituationSpec:
        if self.every and not self.lasts:
            raise ValueError(
                f"situación {self.id!r}: vuelve cada {self.every} ticks pero dura 0, "
                f"así que no llega a ocurrir nunca"
            )
        if self.every and self.lasts >= self.every:
            raise ValueError(
                f"situación {self.id!r}: dura {self.lasts} y vuelve cada {self.every}, "
                f"así que no se apaga jamás; déjala eventual si es permanente"
            )
        if self.lasts and not self.every:
            raise ValueError(
                f"situación {self.id!r}: declara `lasts` sin `every`. Una situación "
                f"eventual dura lo que se le diga al encenderla"
            )
        return self

    @property
    def periodic(self) -> bool:
        return self.every > 0

    def reaches(self, place: PlaceId) -> bool:
        return not self.places or place in self.places

    def active_at(self, tick: int) -> bool:
        """Si es periódica, si toca ahora. Una eventual nunca lo está por sí sola.

        Se pregunta al tick y no se guarda: una situación periódica es una
        función del reloj, igual que una franja, así que no hay estado que
        persistir ni que arrastrar en un salto temporal.
        """
        if not self.periodic:
            return False
        return (tick - self.starts_at) % self.every < self.lasts


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

    company_scale: float = Field(default=1.0, gt=0.0)
    """Qué es "mucha gente" en ESTE mundo.

        saturación(n) = n / (|n| + company_scale)

    Gobierna las tres cosas que dependen de cuánta gente hay delante a la vez: el
    alivio pasivo de las necesidades, el tamaño de los efectos compartidos y lo
    que atrae un plan acompañado. Una sola perilla porque son la misma pregunta.

    Existe porque la curva estuvo clavada en 1.0 y **eso es una aldea**. Con esa
    escala, tres personas ya dan tres cuartos del máximo y a partir de ahí la
    curva es casi plana:

              personas    scale 1    scale 4    scale 8
                     2      0.667      0.333      0.200
                     5      0.833      0.556      0.385
                    14      0.933      0.778      0.636

    Medido en la ciudad, la ocupación media es de **14.4 personas**, así que todo
    lo social vivía pegado al techo: el pack distinguía con cuidado 0.25 por
    compañía en una comida y 0.50 en una charla, y las dos se multiplicaban por
    0.93. Las gradaciones no discriminaban nada. El síntoma medible era que el
    vínculo **nunca** llegó a ser urgente —cero veces en 256 000 muestras— y que
    `charlar` se completó nueve veces en tres semanas entre ciento veintisiete
    personas.

    A 1.0 no cambia absolutamente nada, así que ningún pack calibrado se mueve.
    Súbela en un mundo poblado hasta que la diferencia entre dos y diez personas
    vuelva a verse.

    **No toca el aprecio.** `bond_scale` normaliza una cantidad de utilidad, no
    personas, y por eso son dos perillas y dos funciones (`signed_saturation`
    frente a `company_saturation`). Compartirlas haría que decir "aquí una
    multitud son ocho" moviera de rebote la escala de los vínculos, en silencio.
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

    memory_capacity: int = Field(default=0, ge=0)
    """Cuántos recuerdos retiene cada agente. **0 desactiva la memoria episódica.**

    Apagada por defecto, como `bond_rate` y `sighting_horizon`: un pack que no la
    pide no paga por ella, y estrenar el mecanismo no puede mover ningún contrato
    de salud ya medido.

    Cuando se llena no se descarta el más viejo sino el de menor valor retenido
    —importancia por desdibujado—. Con FIFO, cualquier cosa memorable queda
    enterrada por la rutina de los días siguientes, que es justo al revés de como
    funciona una biografía.
    """

    memory_fade: float = Field(default=1.0, gt=0.0, le=1.0)
    """Cuánto se desdibuja un recuerdo por tick: `importancia * fade ** edad`.

    Misma forma y mismo significado que `bond_fade`, y a propósito: dos
    mecanismos que dicen medir el paso del tiempo tienen que medirlo igual.

    Ojo a la escala. Con 96 ticks por día, 0.999 deja un recuerdo al 91 % al día
    siguiente y al 53 % a la semana. 1.0 = nada se desvanece nunca.
    """

    memory_urgency_weight: float = Field(default=1.0, ge=0.0)
    """Cuánto pesa, al grabar, lo que apretaba la necesidad en ese momento.

    Comer con hambre se recuerda; picar algo por costumbre, no. Es la misma
    `urgency` con la que se decidió y con la que se valoró el rato: una sola vara
    en todo el motor.
    """

    memory_surprise_weight: float = Field(default=1.0, ge=0.0)
    """Cuánto pesa que algo se desvíe de lo esperado.

    Sale gratis: `learn` ya calcula ese error de predicción para corregir las
    creencias, y hasta ahora lo tiraba. Se toma en **valor absoluto** — marca
    igual que algo salga mucho mejor que mucho peor. El signo es cosa del
    arrepentimiento y se guarda aparte.
    """

    memory_witness_weight: float = Field(default=0.5, ge=0.0)
    """Cuánto pesa que hubiera alguien delante.

    Se satura antes de pesarse: la diferencia entre solo y acompañado es enorme,
    la que va de cuatro a cinco personas no existe.
    """

    memory_scale: float = Field(default=1.0, gt=0.0)
    """Cuánto bruto equivale a media importancia.

        importancia = bruto / (bruto + memory_scale)

    Existe por lo mismo que `bond_scale`: el bruto está en las unidades del pack
    y la importancia está acotada a [0, 1). Sin el divisor, el mecanismo sería
    inerte en un pack de números pequeños y estaría pegado al techo en uno de
    números grandes — y entonces `memory_capacity` significaría cosas distintas
    en cada ambientación, que es lo único que el motor no puede permitirse.

    **Mídelo, no lo adivines**: corre una semana y mira la distribución de
    importancias que salen.
    """

    regard_scale: float | None = Field(default=None, gt=0.0)
    """Cuánto APRECIO equivale a media importancia. `None` = usa `memory_scale`.

        importancia = aprecio / (aprecio + regard_scale)

    **Existe porque el aprecio y la saliencia no viven en la misma escala, y
    hasta que se midió nadie lo había escrito.** Un recuerdo corriente saca su
    importancia de un bruto que compone urgencia, sorpresa y testigos; un duelo
    y una noticia sobre alguien la sacan del aprecio, que es un número pequeño
    por construcción — sale de `bond_rate` moviendo poco a poco un valor acotado.

    Metidos los dos por el mismo divisor, el resultado era éste:

        importancia MEDIANA de lo guardado                 0.4422
        importancia MÍNIMA retenida, con la memoria llena  0.2394
        duelo típico   (aprecio 0.0746, escala 1.0)        0.0690
        duelo MÁXIMO   (aprecio 0.4564, escala 1.0)        0.3134

    Es como apuntar lo que marca cada cosa en una escala del 0 al 10 y apuntar
    lo que marca una muerte en una escala del 0 al 3: **la peor pérdida posible
    saca un 3 y una buena cena saca un 5**. El olvido por valor (`memoria` §32)
    tira lo más barato, así que el duelo se iba el mismo día. Medido: cinco
    muertes, y al día 75 **cero dolientes de 195 supervivientes**.

    Lo gobierna todo el rango que el aprecio alcanza en ESE mundo, y por eso es
    una perilla del pack y no una constante. Con el aprecio de confluencia:

        escala   duelo típico   duelo máximo   contra el listón 0.2394
        1.0          0.069          0.313       casi todo se tira
        0.5          0.130          0.477       lo típico se sigue tirando
        0.1          0.427          0.820       el conocido dura semanas,
                                                el querido se queda

    **`None` y no un número por defecto**, por lo mismo que todo lo demás: sin
    tocarlo, el motor hace exactamente lo que hacía. Ver `regard_for` — la otra
    mitad de este arreglo.
    """

    @property
    def escala_del_aprecio(self) -> float:
        """La que convierte aprecio en importancia. Una sola puerta.

        Los dos sitios que graban a partir del afecto —una muerte y una noticia
        sobre alguien— tienen que usar la misma, o el mismo aprecio pesaría una
        cosa al perder a alguien y otra al enterarse de algo suyo.
        """
        return self.memory_scale if self.regard_scale is None else self.regard_scale

    regret_weight: float = Field(default=0.0, ge=0.0)
    """Cuánto pesa el escarmiento al deliberar. **0.0 desactiva el mecanismo.**

        utilidad = beneficio · ... - aversión · (coste + peaje + rencor · regret_weight)

    Se suma al **coste** y no multiplica el beneficio, y no es una elección
    libre: es la misma doctrina que gobierna al descuento de viaje y a los
    gustos, escrita en `decide.py`. Si multiplicara, una acción muy apetecible
    quedaría castigada proporcionalmente más que una tibia, y un escarmiento no
    es un descuento porcentual — es un pavor de tamaño fijo.

    Que pase por `loss_aversion` sale gratis y es exactamente lo correcto: un
    agente prudente pesa más el daño recordado que uno temerario.

    **Lo que impide el veto no es este tope: es que la desesperación crece y el
    escarmiento no.** Conviene entenderlo bien porque no es evidente y se
    descubrió midiendo, con un test que fallaba.

    El rencor está acotado a [0, 1), así que la penalización nunca pasa de
    `regret_weight`. Pero es un número **fijo**, mientras que el beneficio de una
    acción crece con la urgencia según la necesidad se hunde. El agente vuelve a
    lo que le dolió cuando le hace suficiente falta, y eso es exactamente la
    conducta que se quiere.

    De ahí sale la **restricción de calibración**, que es dura: `regret_weight`
    tiene que quedar por debajo del beneficio máximo alcanzable de las acciones
    que escarmienta —del orden de `peso * satisfies` con la urgencia a tope—. Por
    encima de eso el escarmiento gana siempre, ni la desesperación lo levanta, y
    el agente prefiere hundirse antes que reintentar. Medido en un mundo de
    juguete con beneficio máximo 1.0: a 2.0 la acción no se ejecuta ni una vez en
    doscientos ticks; a 0.5 se evita mientras hay alternativa y se retoma cuando
    aprieta.

    Un rencor que veta impide reintentar, y quien no reintenta nunca descubre que
    la cosa mejoró — la aversión solo se curaría por el paso del tiempo.
    """

    regret_scale: float = Field(default=1.0, gt=0.0)
    """Cuánto escarmiento acumulado equivale a medio rencor.

        rencor = bruto / (bruto + regret_scale)

    Mismo papel que `bond_scale` y `memory_scale`: el bruto es una suma de
    valencias por valor, en las unidades que salgan, y el rencor tiene que estar
    acotado para que `regret_weight` signifique lo mismo en todos los packs.
    """

    fear_weight: float = Field(default=0.0, ge=0.0)
    """Cuánto pesa el miedo a un LUGAR al deliberar. **0.0 lo desactiva.**

        utilidad = beneficio · ... - aversión · (coste + rencor + peaje + miedo)

    Se suma junto al **peaje**, y el sitio no es casual: el peaje es literalmente
    *lo que cuesta llegar ahí*, y un miedo es lo mismo pagado en otra moneda. El
    escarmiento es un recargo sobre la acción; el miedo, sobre el lugar. Mismo
    esqueleto, ejes ortogonales.

    De ahí sale la conducta que ninguna otra perilla puede expresar: quien teme
    la plaza **no deja de socializar, socializa en otro sitio**. Una aversión a
    la acción no sabe hacer eso.

    **Ojo, el veto aquí es peor que con el arrepentimiento.** El pack exige que
    exista una acción sin affordance —la red de seguridad— pero NO exige que
    exista un lugar alternativo por affordance. Si el único sitio donde se puede
    dormir da miedo, no hay adónde ir: no existe un "lugar de refugio" análogo.
    Vale la misma regla —la desesperación crece y el miedo es fijo— pero con
    menos margen, así que este número quiere ser más conservador que
    `regret_weight`.
    """

    fear_scale: float = Field(default=1.0, gt=0.0)
    """Cuánto pavor acumulado equivale a medio miedo. Mismo papel que
    `regret_scale`, sobre el otro eje."""

    rumor_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    """Probabilidad de que alguien cuente algo al terminar algo compartido.
    **0.0 desactiva los rumores.**

    Se engancha ahí y no a la co-presencia a secas por lo mismo que `Bond.shared`
    existe: **cruzarse no es convivir**. Compartir sala mientras cada uno va a lo
    suyo no es ocasión de contar nada; una comida o una charla, sí. La guarda ya
    estaba escrita para los vínculos y aquí se reusa tal cual.

    Bajo por definición, y con el mismo cuidado que los disparadores: es la
    segunda pieza del motor que mueve información sin que nadie la decida.
    """

    rumor_decay: float = Field(default=0.5, gt=0.0, le=1.0)
    """Cuánto sobrevive a cada boca. 0.5 = de oídas pesa la mitad.

    Es el teléfono escacharrado, y hace falta que exista o un rumor daría vueltas
    por un corrillo ganando peso hasta volverse el suceso más importante de la
    biografía de todos. Con esto, cada salto lo achica y el rumor **muere solo**
    a los pocos saltos, sin tener que contar saltos ni podar nada.

    No se aplica cuando quien escucha tiene aprecio a la persona de la que se
    habla: ahí el peso lo pone el oyente, no la cadena. Ver `world.contar`.
    """

    grief_scale: float = Field(default=0.0, ge=0.0)
    """Cuánto dolor acumulado equivale a medio duelo. **0.0 desactiva `duelo()`.**

    Tercer eje, y el único de los tres que **no tiene un `_weight` al lado**. La
    ausencia es deliberada y es la mitad del diseño.

    `regret_weight` encarece una acción y `fear_weight` encarece un viaje: los
    dos existen porque de una acción y de un lugar uno puede apartarse. **De un
    ausente no.** Un `grief_weight` tendría que responder a *"¿el duelo encarece
    qué?"*, y cualquier respuesta que se escribiera aquí sería inventarse una
    forma única de vivirlo — justo lo que el motor no debe hacer.

    Lo que diferencia dos duelos no es una perilla del pack: es de qué viene
    acompañado el recuerdo y cuánto le dura a cada cual (`memory_multipliers`).
    Ver `MemoriaEpisodica.duelo`.

    Así que esto es una **lente**: mide lo que hay, para el panel de salud y para
    el narrador de F5, sin decidir por nadie.
    """
