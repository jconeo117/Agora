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

import math
import string
from enum import StrEnum
from typing import Annotated, Literal, NewType

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
FactionId = NewType("FactionId", str)
FactionKindId = NewType("FactionKindId", str)
ActionId = NewType("ActionId", str)
PlaceId = NewType("PlaceId", str)
AgentId = NewType("AgentId", str)
PropertyId = NewType("PropertyId", str)
Affordance = NewType("Affordance", str)
Tag = NewType("Tag", str)
ItemId = NewType("ItemId", str)
ArcId = NewType("ArcId", str)
CounterId = NewType("CounterId", str)
ArrivalId = NewType("ArrivalId", str)

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

Example = Annotated[str, Field(min_length=1, max_length=120)]
"""Una frase de ejemplo con la que un jugador pediría algo (unidad 14)."""

ContentTag = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z_]+$")]
"""Una etiqueta de contenido («violencia»), para las líneas y los velos de la
mesa (unidad 17). El motor no sabe qué significa ninguna: solo las compara."""




class Spec(BaseModel):
    """Base de toda definición que viene del pack. Inmutable y estricta."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class NarrationSpec(Spec):
    """Cómo se cuenta algo, en las tres formas que el narrador necesita
    (unidad 17). `{a}` es quien actúa, `{o}` sobre quién y `{d}` cuánto daño
    en palabras («, un buen golpe»), si la escena lo sabe. Son a la vez el
    hecho que recibe el modelo y el respaldo sin modelo: con la etiqueta de la
    acción, «rematar a un herido contra Zetu», los dos 70B del banco entendieron
    «un herido que luchaba contra Zetu»."""

    you: str = Field(min_length=1, max_length=160)
    """Cuando actúa el jugador: «rematas a {o}»."""
    them: str = Field(min_length=1, max_length=160)
    """Cuando actúa otro: «{a} remata a {o}»."""
    at_you: str | None = Field(default=None, min_length=1, max_length=160)
    """Cuando otro actúa sobre el jugador: «{a} te remata». Sin esto, la forma
    de tercera persona con su nombre."""

    @model_validator(mode="after")
    def _known_fields(self) -> NarrationSpec:
        # Un `{objetivo}` mal escrito reventaría al narrar, en mitad de una
        # partida y lejos de quien escribió el pack.
        for forma in (self.you, self.them, self.at_you or ""):
            campos = {c for _, c, _, _ in string.Formatter().parse(forma) if c is not None}
            if campos - {"a", "o", "d"}:
                raise ValueError(f"narration: «{forma}» usa {sorted(campos - {'a', 'o', 'd'})}; "
                                 "solo valen {a}, {o} y {d}")
        return self


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

    from_items: dict[Tag, PositiveFactor] = Field(default_factory=dict)
    """El eje sale de lo que se lleva encima (unidad 16b): cada objeto con una
    de estas etiquetas suma su valor, y el tope es 1. Un eje así no decae, y
    ninguna acción lo gasta ni lo da en `effects`, `costs` o `target.gives`:
    subirlo es coger cosas y bajarlo es gastarlas o perderlas, y el pack no carga
    si se pide otra cosa. Vacío = un eje como los de siempre."""

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

    regret_multiplier: PositiveFactor = 1.0
    """Cuánto le dura el RENCOR en particular. Compone sobre `memory_multipliers`,
    no lo sustituye — ver el docstring de `grief_multiplier`, que explica el
    patrón compartido de los cuatro lentes (D-045)."""

    fear_multiplier: PositiveFactor = 1.0
    """Cuánto le dura el MIEDO en particular. Mismo patrón que `grief_multiplier`
    (D-045)."""

    grief_multiplier: PositiveFactor = 1.0
    """Cuánto le dura el DUELO en particular, por encima de `memory_multipliers`.

    **El motivo por el que existen los cuatro lentes.** `memory_multipliers` dice
    cuánto le dura a alguien la memoria EN CONJUNTO, pero una persona real no
    olvida todo a la misma velocidad: el duelo por quien de verdad quiso puede
    durarle años mientras el rencor por un mal trato cualquiera se le pasa en
    semanas — o al revés. Un solo canal general no puede expresar esa asimetría;
    partirlo por los CUATRO ÍNDICES que el motor ya define (rencor, miedo, duelo,
    agravio) sí, porque son un conjunto cerrado y no un eje abierto que el pack
    tenga que inventar (por eso no contradice la razón por la que
    `memory_multipliers` sigue siendo un número suelto y no un diccionario por
    necesidad).

    Compone MULTIPLICANDO sobre el general, nunca sustituyéndolo — así "propio de
    cada índice" y "propio de la persona" son la misma fórmula en dos capas:

        fade_del_duelo = base ** (1 / (memory_multipliers · grief_multiplier))

    En 1.0 (el defecto) el duelo de esa persona dura exactamente lo que ya
    determinaba `memory_multipliers`, así que declarar el rasgo sin tocar estos
    cuatro campos no cambia nada.
    """

    grudge_multiplier: PositiveFactor = 1.0
    """Cuánto le dura el AGRAVIO en particular. Mismo patrón que
    `grief_multiplier` (D-045)."""

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


class DebtSpec(Spec):
    """Lo que una acción dirigida deja DEBIENDO al otro: una `Propiedad` de
    tipo DEUDA creada en marcha, a favor de quien actúa.

    **Es la primera entidad que el motor crea durante la partida.** Hasta aquí
    todo lo que existía en un mundo estaba escrito en el pack antes de
    arrancar — los agentes, los lugares, las propiedades — y lo único que
    cambiaba era su estado. Prestar no se podía escribir así: quién le debe a
    quién es justamente lo que la simulación tiene que descubrir, no lo que se
    declara de antemano.

    Dos campos y ninguno es opcional, porque una deuda sin los dos no es una
    deuda:

    - `renta`: el goteo por tick, lo mismo que ya cobra cualquier propiedad —
      del bolsillo del deudor al del acreedor (D-063).
    - `saldo`: cuánto queda por devolver **en total**. Cada tick baja lo que
      la renta transfiere, y al llegar a cero la deuda se extingue: deja de
      cobrarse y desaparece de `WorldState.propiedades`.

    Sin `saldo` esto no sería prestar sino someter: un goteo perpetuo que solo
    para cuando alguien muere, y que en un mundo con préstamos dinámicos
    acumularía deudas para siempre sin que ninguna se saldase nunca. Las
    cuatro deudas escritas a mano de un pack pueden permitirse ser perpetuas
    (`PropertySpec.saldo` vacío) porque las escribió alguien a sabiendas; una
    que nace sola, no.

    **El interés se escribe, no se calcula.** El motor no relaciona `saldo`
    con lo que `gives` entrega: prestar 0.30 y declarar un saldo de 0.36 es un
    préstamo con interés, y declarar 0.30 es uno sin él. Derivar el interés
    aquí obligaría al motor a saber qué eje es "dinero", que es exactamente lo
    que no puede saber.
    """

    renta: dict[NeedId, float]
    """Cuánto se transfiere por tick, del deudor al acreedor. Mismas claves que
    `saldo`."""

    saldo: dict[NeedId, float]
    """Cuánto queda por devolver en total. Mismas claves que `renta`.

    Prestar dos veces a la misma persona no abre una segunda deuda: la que ya
    hay crece (`renta` y `saldo` se suman). Una sola deuda por par
    acreedor/deudor y acción mantiene la identidad estable, que es lo que
    `por_deuda` y la persistencia necesitan para no depender de cuántas veces
    se prestó.
    """

    @model_validator(mode="after")
    def _renta_y_saldo_hablan_de_lo_mismo(self) -> DebtSpec:
        """Las dos mitades tienen que nombrar los mismos ejes, y ninguna puede
        ser cero.

        Un eje con renta y sin saldo no se amortiza nunca —la perpetuidad por
        la puerta de atrás, que es justo lo que este spec existe para evitar—
        y uno con saldo y sin renta no se cobra jamás: las dos formas se leen
        como una deuda viva y ninguna de las dos lo es.
        """
        if not self.renta or not self.saldo:
            raise ValueError("una deuda necesita `renta` y `saldo`, los dos")
        if set(self.renta) != set(self.saldo):
            raise ValueError(
                f"`renta` y `saldo` nombran ejes distintos: "
                f"{sorted(self.renta)} contra {sorted(self.saldo)}"
            )
        malos = sorted(
            need
            for need, valor in {**self.renta, **self.saldo}.items()
            if valor <= 0.0
        )
        if malos:
            raise ValueError(
                f"una deuda se cobra hacia un lado solo: {malos} no son > 0"
            )
        return self


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

    combate: bool = False
    """Si el jugador está en uno de los dos lados, esto se resuelve como una
    escena con las reglas de la mesa (unidad 13, D-161), y no con `gives`.
    Entre NPCs no cambia nada: la utilidad, como siempre."""

    quita_por_pericia: NeedId | None = None
    """Qué aptitud de QUIEN ACTÚA escala la parte NEGATIVA de `gives` (I-008).

    El gemelo de `gives_por_pericia`, que solo escala lo que se da (D-059). Sin
    él, cuando dos agentes pelean sin el jugador delante, un golpe hace el mismo
    daño lo dé quien lo dé, y un flaco gana a un robusto tan a menudo como al
    revés. Con él, el daño se multiplica por la aptitud de quien golpea en ese
    eje (`AgentState.gains`), y después el temple de quien lo recibe
    (`cost_multipliers`) lo reduce en `endure`: las dos se componen, como en la
    ayuda. Las stats pesan sin dados y sin iniciativa.
    """

    gives_por_pericia: NeedId | None = None
    """Qué aptitud de QUIEN ACTÚA escala la parte POSITIVA de `gives` (D-059).

    `None` (el defecto) dice lo de siempre: lo que el otro recibe se escala
    solo por SU propia aptitud, dentro de `apply` — correcto para curar, donde
    es el cuerpo de quien recibe el que decide cuánto le ayuda un tratamiento.

    Declarado, dice otra cosa: la calidad de lo que se ofrece depende de quien
    lo ofrece, no de quien lo recibe. Un cazador experimentado enseña mejor
    que uno novato — no porque el motor sepa qué es enseñar bien, sino porque
    `gain_multipliers` ya sabe decir cuánto le cunde algo a cada cual, y aquí
    se aplica al OTRO LADO de la acción por primera vez.

    **Las dos escalas se COMPONEN, nunca se sustituyen.** Lo que sale de aquí
    multiplica lo declarado, y ese resultado todavía pasa por `apply`, que lo
    vuelve a escalar por la aptitud del receptor. Un maestro excelente con un
    alumno dotado rinde más que cualquiera de los dos por separado, y es
    exactamente lo que se pediría de cualquier otro canal del motor: aquí no
    hay caso especial, solo dos multiplicadores de sitios distintos.
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

    requires_traits: dict[TraitId, float] = Field(default_factory=dict)
    """Solo vale sobre quien SEA esto. `{}` = sobre cualquiera (D-070).

    El espejo de `ActionSpec.requires_traits`, que hasta aquí solo sabía
    preguntar quién eres TÚ. Hacía falta para lo que necesita dos partes que no
    son intercambiables: engendrar pide que quien actúa sea de una clase y
    quien recibe de otra, y con una sola mitad de la puerta no se puede
    escribir — un rasgo del actor no dice nada del otro.

    Es una puerta dura y se comprueba donde se elige al destinatario, no al
    puntuar: se ve **quién es** alguien que tienes delante, igual que se ve una
    condición. Lo que no se ve es el valor de sus necesidades.
    """

    misma_faccion: FactionKindId | None = None
    """Solo sobre quien comparta contigo un grupo de esta clase (D-090)."""

    otra_faccion: FactionKindId | None = None
    """Solo sobre quien tenga un grupo de esta clase y NO sea el tuyo.

    No es la negación de la anterior: quien no pertenece a ninguno tampoco vale.
    Un asalto entre gremios pide que haya DOS gremios, no que al otro le falte
    el tuyo.
    """

    faccion_enemiga: bool = False
    """Solo sobre quien pertenezca a un grupo declarado enemigo del tuyo.

    Es lo que convierte grupos en política: la violencia deja de ser personal
    —`por_agravio` mira lo que TE hicieron— y pasa a ser de bando. Los dos ejes
    conviven: se puede odiar a alguien del bando propio y respetar a alguien del
    contrario.
    """

    enemista: bool = False
    """Hacerlo enemista a los dos grupos, si son de la misma clase y distintos.

    Las enemistades no se declaran en el pack por lo mismo que las facciones no
    se declaran: en un mundo donde los grupos los funda la gente, quién odia a
    quién es lo que la simulación descubre.
    """

    mueve_traits: dict[TraitId, float] = Field(default_factory=dict)
    """Cuánto mueve cada rasgo DEL DESTINATARIO, en [-2, 2] (D-131).

    Enseñar un oficio, dejar una cicatriz, doblegar a alguien. Es lo que
    convierte un linaje en una escuela: un asesino que entrena a su hijo le
    empuja el rasgo, y en tres generaciones la casa entera lo lleva **sin que
    la sangre lo transmita** — se hereda el temperamento y las afinidades
    (D-072), no la clase (D-073), así que la única forma de que un oficio pase
    de padres a hijos es que lo enseñen.

    Estrena `AgentState.drift_trait`, que llevaba desde F1 con el docstring
    *«todavía no lo llama nadie; es la puerta que este paso existe para abrir:
    cicatrices, aprendizaje y rampancia entran por aquí»*. Entra el aprendizaje.

    Recompone lo derivado del rasgo movido (pesos, aptitud, temperamento), así
    que enseñar cambia de verdad cómo decide quien aprende, no solo un número
    en su ficha.
    """

    suma_a_faccion: FactionKindId | None = None
    """Hacerlo mete al destinatario en TU grupo de esta clase. Reclutar.

    Del actor al destinatario y no al revés: quien recluta es quien ya está
    dentro. Si quien actúa no pertenece a ninguno de esa clase, no pasa nada —
    callar y no reventar, como `crea_relacion` con un lazo exclusivo ocupado.
    """

    requires_edad: int = Field(default=0, ge=0)
    """Edad mínima del destinatario, en ticks. 0 = cualquiera.

    Espejo de `ActionSpec.requires_edad`, y por la misma razón que
    `requires_traits`: hay cosas que exigen que las DOS partes lleven un tiempo
    en el mundo, y con la puerta puesta solo en quien actúa se escribiría la
    mitad de la regla.
    """

    forbids_condition: SituationId | None = None
    """No vale sobre quien lleve esto. `None` = sobre cualquiera.

    Negativo de `requires_condition`, y no es lo mismo con otro nombre: la
    afirmativa dice *a quién SÍ* (curar al herido) y esta dice *a quién ya
    no hace falta* (no dejar en estado a quien ya lo está). Sin ella, la
    única forma de escribirlo sería una condición "disponible" que hubiera que
    quitar y devolver a mano, y eso son dos puertas donde hay una.
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

    por_desconocido: bool = False
    """Esta acción se dirige **a quien menos conoces**, no a quien más aprecias
    ni a quien más te debe. Tercer modo (D-101), y hacía falta uno: ni
    `por_agravio` ni el modo por defecto sirven para la violencia por CODICIA
    (bandidaje, robo) — la primera no puede empezar sin una deuda previa, y el
    defecto golpearía al mejor amigo por diseño.

    Cambia el desempate igual que `por_agravio`: en vez de maximizar el
    aprecio, lo minimiza. La puerta es `max_regard`, no `min_regard` — un
    bandido no descarta por poco aprecio, descarta por DEMASIADO.

    Mutuamente excluyente con `por_agravio`; el pack no carga si declara los
    dos a la vez, porque no hay forma de leer "a quien menos conoces, y de
    esos a quien más te debe" sin inventar un tercer criterio de desempate
    que nadie pidió.

    No lleva un `_weight` propio: a diferencia de aprecio y agravio, la
    codicia no se mide por CUÁNTO de desconocido es alguien, solo por serlo o
    no. `disposicion` devuelve 1.0 sin encoger nada.
    """

    max_regard: float = Field(default=1.0, ge=-1.0, le=1.0)
    """Aprecio máximo para que valga como desconocido. Solo con
    `por_desconocido`. 1.0 = cualquiera vale, que es el defecto -- igual que
    `min_regard` en 0.0 deja la puerta abierta por defecto para el modo
    normal."""

    por_deuda: bool = False
    """Esta acción se dirige **a quien te debe**, según una `Propiedad` tipo
    DEUDA de la que eres dueño -- no a quien más aprecias, ni a quien te
    agravió (`por_agravio` mira la memoria, no la propiedad; son ejes
    distintos y pueden coincidir sin ser lo mismo).

    Cuarto modo, mismo patrón que los otros tres: la puerta es objetiva
    (`min_deuda`, cuánto te tiene que deber) y el desempate subjetivo (a
    quien más te deba, `deuda_weight` en la recompensa). Mutuamente
    excluyente con `por_agravio` y `por_desconocido` -- el pack no carga si
    declara dos a la vez, por la misma razón que esos dos: no hay forma de
    leer "a quien más te debe, y de esos a quien menos aprecias" sin
    inventar un criterio que nadie pidió.

    `deudas` llega ya resuelto por deliberación (una consulta sobre
    `WorldState.propiedades`, no una por candidato) -- mismo motivo que
    `agravio`.
    """

    min_deuda: float = Field(default=0.0, ge=0.0)
    """Cuánto te tiene que deber, como mínimo, para molestarte. Puerta dura,
    solo con `por_deuda`. En la misma unidad que la `renta` de la deuda, no
    una fracción [0,1] -- una deuda no está acotada como un aprecio."""

    deuda_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto depende de CUÁNTO te deba. Espejo exacto de `agravio_weight`,
    sobre el monto de la deuda en vez del agravio acumulado."""

    acerca: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Cuánto sube el aprecio MUTUO de golpe al hacerlo. 0.0 = nada (D-086).

    Todo lo demás llega al aprecio a plazos: `remember_company` persigue un
    premio con un ritmo, y ese es el mecanismo correcto para el trato. Pero
    algunos vínculos no se van cocinando — **pasan**, y el motor no tenía forma
    de decirlo. Es `acercar` (D-078), que hasta hoy solo usaba el parto,
    ofrecido al pack.

    Mutuo y no dirigido: los dos estaban ahí. El amor no correspondido pide dos
    números y no uno, y no se puede escribir todavía — queda anotado.

    Se suma sobre lo que hubiera, así que dos que ya se querían acaban más
    arriba que dos desconocidos: al revés que `remember_company`, donde un
    suceso único casi no mueve a quien ya está cerca del premio.
    """

    crea_relacion: RelationId | None = None
    """Esta acción ANUDA este lazo entre quien actúa y el destinatario (D-082).

    `begin_relation` era API pública desde la capa relacional y **ningún
    contenido la llamaba**: las relaciones de un mundo se decidían en el tick 0
    y no volvían a cambiar. El parto abrió la primera grieta (D-071), pero solo
    sabe anudar sangre; esto deja que un lazo nazca de algo que alguien HIZO —
    apadrinar a un crío, tomar un discípulo, hacerse de alguien.

    El otro lado lo pone `inverse` como siempre, así que se declara una sola
    dirección. Si el lazo ya estaba, no pasa nada; si es `exclusive` y quien
    actúa ya tiene uno, tampoco — **no se rompe el que hubiera**. Cambiar de
    pareja no puede ser un efecto colateral de una acción que hablaba de otra
    cosa, y romper lazos es una decisión de diseño que este motor no ha tomado.

    Combina bien con `min_regard`: un lazo que nace de la nada es un accidente,
    y uno que pide aprecio previo es una consecuencia.
    """

    crea_deuda: DebtSpec | None = None
    """Esta acción deja al otro DEBIENDO: crea una `Propiedad` DEUDA a favor de
    quien actúa, en marcha (D-065).

    Es el otro extremo de `por_deuda`, que hasta aquí solo sabía cobrar deudas
    que el pack hubiera escrito antes de arrancar. Con esto la deuda deja de
    ser decorado del mundo inicial y pasa a ser consecuencia de algo que
    alguien hizo.

    **Lo que se presta va en `gives`, no aquí.** Prestar es dar ahora y cobrar
    después, y las dos mitades ya tienen su sitio: `gives` (más `costs` de la
    acción, que es lo que le cuesta al prestamista) entrega el préstamo, y
    esto anota la devolución. Meter el monto aquí duplicaría `gives` con la
    diferencia de que el motor tendría que saber que son lo mismo.

    Se crea solo si el destinatario sigue delante al terminar, como todo lo
    demás de `TargetSpec`: una promesa que no llega a decirse no obliga a
    nada.
    """


class ItemSlot(StrEnum):
    """Dónde se lleva un objeto. Cerrado y del motor: el motor sabe que un arma y
    una armadura ocupan huecos distintos, no qué es cada una. `ninguno` se lleva
    pero no se equipa."""

    ARMA = "arma"
    ARMADURA = "armadura"
    NINGUNO = "ninguno"


class ItemSpec(Spec):
    """Un tipo de objeto que puede tener alguien o un sitio (unidad 16a).

    Un objeto concreto es una `Propiedad` de tipo OBJETO cuyo `objeto` es este
    id: una sola puerta para «quién tiene qué», en vez de un inventario aparte.

    `gains` y `costs` son los dos puentes con la aptitud. Un arma multiplica lo
    que rinde quien la lleva en su eje (el combate); una armadura multiplica lo
    que le cuesta un golpe (la salud), por el mismo camino del temple. Sin ellos
    un objeto es decorado, y el motor no cambiaría una decisión por llevarlo.
    """

    id: ItemId
    label: str
    tags: frozenset[Tag] = Field(default_factory=frozenset)
    slot: ItemSlot
    gains: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Lo que multiplica la aptitud de quien lo lleva EQUIPADO."""
    costs: dict[NeedId, PositiveFactor] = Field(default_factory=dict)
    """Lo que multiplica lo que le cuesta a quien lo lleva EQUIPADO recibir algo."""
    narration: str | None = None
    """Cómo se nombra en la escena («una lanza corta»). Sin esto, la etiqueta."""

    @property
    def valor(self) -> float:
        """Lo que vale como «mejor»: el producto de lo que multiplica la aptitud.
        Una armadura, que solo tiene `costs`, vale 1.0 y empata con todas: por eso
        el desempate por id decide, y no hay una armadura «mejor» que otra."""
        return math.prod(self.gains.values())


class ItemWhere(StrEnum):
    """Dónde mira una consulta de objeto. `None` en la consulta = lo de siempre:
    el suelo sin destinatario, lo que lleva el objetivo con destinatario."""

    SUELO = "suelo"
    OBJETIVO = "objetivo"
    ENCIMA = "encima"


class ItemQuery(Spec):
    """Qué objeto hace falta o se mueve: un hueco, unas etiquetas, o ambos.

    Vacía = cualquier objeto. Es lo que separa «hay una arma» de «hay una
    lanza»: el pack escribe la consulta y el motor solo la compara con los tags.
    """

    slot: ItemSlot | None = None
    tags: frozenset[Tag] = frozenset()
    where: ItemWhere | None = None
    """Dónde se busca. Lo que se gasta (`consumes`) solo puede ser `encima`."""

    def admits(self, item: ItemSpec) -> bool:
        """Única forma de preguntar si un objeto cumple: la usan la puerta, el
        «mejor» de `takes_item` y el de `gives_item`, y si cada una comparara por
        su cuenta, dos de ellas podrían decidir distinto sobre el mismo objeto."""
        return (self.slot is None or item.slot is self.slot) and self.tags <= item.tags


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
    examples: tuple[Example, ...] = ()
    """Cómo lo diría un jugador (unidad 14, D-163). Ni el motor ni los NPCs lo
    leen: solo el intérprete de la prosa del jugador, que con la etiqueta sola
    no reconoce «le reviento la cabeza» como atacar. Va en el pack y no en el
    código porque es vocabulario del mundo."""
    narration: NarrationSpec | None = None
    """Cómo la cuenta el narrador (unidad 17). Sin esto, con la etiqueta."""
    content: tuple[ContentTag, ...] = ()
    """Qué hay en ella que una mesa podría no querer ver narrado (D-167)."""
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

    requires_faccion: FactionKindId | None = None
    """Solo un miembro de un grupo de esta clase puede intentarlo (D-090).

    Duodécima puerta dura, y la primera que pregunta por algo que no es tuyo
    sino de un grupo. Es lo que separa una facción de una etiqueta: si
    pertenecer no cierra ni abre una puerta, no cambia una sola decisión y el
    grupo es decoración.

    Pregunta por la CLASE, no por un grupo concreto: *un contrato del gremio*
    vale en cualquier gremio, y el motor no puede saber cuáles habrá si los
    funda la gente en marcha.
    """

    requires_prestigio: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto prestigio tiene que tener el grupo. Solo con `requires_faccion`.

    Lo que solo puede hacer alguien de una casa con nombre. Es la puerta que
    evita que el prestigio sea un número decorativo — si no abre nada, no
    cambia una sola decisión.
    """

    requires_lealtad: float = Field(default=0.0, ge=0.0, le=1.0)
    """Con cuánta lealtad al grupo, como mínimo. Solo con `requires_faccion`.

    Es el rango interno sin declarar rangos: lo que un recién llegado no puede
    hacer y un veterano sí.
    """

    lealtad: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Cuánta lealtad mueve hacerlo, en el grupo que la puerta pidió.

    Positiva para lo que se hace POR el grupo, negativa para lo que se le hace
    en contra. Sin esto la lealtad sería un número que solo baja con el tiempo.
    """

    forbids_faccion: FactionKindId | None = None
    """No se puede intentar siendo ya de un grupo de esta clase (D-127).

    Negativo de `requires_faccion`, y hace falta por lo que se midió al soltar
    los gremios: sin él, fundar competía con unirse en igualdad y ganaba
    siempre, porque fundar no depende de que nadie te acepte. Salieron 137
    gremios para 247 personas, 68 de ellos de un solo miembro. Quien ya tiene
    gremio no funda otro, y con eso unirse deja de tener rival.
    """

    funda_faccion: FactionKindId | None = None
    """Hacerlo funda un grupo nuevo de esta clase, con quien actúa dentro.

    Tercera entidad que el motor crea en marcha, después de la deuda (D-065) y
    de la persona (D-071), y con la misma lección: **el id se deriva de quién y
    cuándo, nunca de un contador**, porque un contador depende del orden en que
    se resuelvan los agentes y ese orden depende de quién estaba dónde.
    """

    requires_edad: int = Field(default=0, ge=0)
    """Cuánto tiene que llevar en el mundo quien lo intente, en ticks. 0 = da
    igual, y es el defecto (D-070).

    Décima puerta dura. Es la única que no mira lo que tienes, lo que eres ni
    dónde estás, sino **cuánto llevas**: `tick - nacido_en`. En ticks y no en
    días por lo mismo que todo lo demás que el pack declara en tiempo — cambiar
    la duración del tick no puede cambiar lo que significa una regla.

    No es un rasgo. Un rasgo se declara y se queda; esto crece solo, para todo
    el mundo, sin que nadie lo toque. Y no es un eje de progresión: un eje se
    gana haciendo algo y este no se gana, se cumple.
    """

    forbids_condition: SituationId | None = None
    """No se puede intentar llevando esto encima. `None` = da igual.

    La contraria de `ActionSpec.cures`, que quita una condición: esta la usa
    como candado. Existe porque hay estados que se excluyen a sí mismos —quien
    ya está en uno no puede volver a entrar— y sin ella habría que modelarlo
    con un eje de necesidad que baje a cero, que es un número donde lo que hay
    es un sí o un no.
    """

    requires_condition: SituationId | None = None
    """Solo se puede intentar llevando esto encima. `None` = da igual.

    La afirmativa de `forbids_condition`, sobre quien actúa. Existe para que una
    acción sea de un bando sin que el bando sea un rasgo: `asaltar` lo hacen los
    llegados hostiles (23b-1), y un candado en negativo solo sabría decir a
    quién no dejar atacar. Sin esta puerta, la misma acción estaría en el menú
    de todo el mundo.
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

    vulnerable: bool = False
    """Quien lo está haciendo está desprevenido: si le atacan en una escena,
    actúa al final de la primera ronda (§9.1, D-165). Dormir, por ejemplo."""

    tags: frozenset[Tag] = Field(default_factory=frozenset)
    """Válvula de escape para lo que el motor no modela: "violenta", "ilegal",
    "ruidosa". Los packs declaran qué significan; el motor solo las compara."""

    requires_item: ItemQuery | None = None
    """Puerta dura: hace falta un objeto que cumpla, en el suelo del sitio o, si
    la acción tiene `target`, en lo que lleva el objetivo."""

    takes_item: ItemQuery | None = None
    """Al terminar, pasa al actor el mejor objeto que cumpla: del suelo, o del
    objetivo si la acción tiene `target`."""

    gives_item: ItemQuery | None = None
    """Al terminar, pasa del actor al objetivo el mejor objeto que cumpla. Exige
    `target`: sin a quién darlo no hay transferencia."""

    consumes: ItemQuery | None = None
    """Al terminar, el actor gasta el objeto de id menor que cumpla y lo quita del
    mundo (unidad 16b). Si ya no lo tiene, la acción no llega a su efecto: se
    registra como abortada, con `sin_objeto`. Solo `where: encima`."""


# ---------------------------------------------------------------------------
# Lugares: nodos del grafo del mundo
# ---------------------------------------------------------------------------
class RegrowSpec(Spec):
    """Cuánto de un objeto puede haber en el suelo, y cada cuántos ticks se repone
    (unidad 16b). Determinista: sin azar, cada `every` ticks aparece uno si hay
    menos de `max`."""

    max: int = Field(ge=1)
    every: int = Field(ge=1)


class PlaceSpec(Spec):
    id: PlaceId
    label: str
    description: str | None = Field(default=None, min_length=1, max_length=300)
    """Cómo es, en una o dos frases (unidad 17). El narrador ambienta con esto y
    con nada más: sin descripción, un modelo se inventa el río que no hay."""

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

    items: dict[ItemId, int] = Field(default_factory=dict)
    """Cuántos de cada objeto hay en el suelo al empezar la partida."""

    regrow: dict[ItemId, RegrowSpec] = Field(default_factory=dict)
    """Qué vuelve a aparecer en el suelo, y cada cuánto (unidad 16b). Un forraje
    que se agota por la recolección se repone solo; sin esto, el sitio se acaba."""

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

    **El aviso que llevaba aquí desde F1.9 ya no vale, y conviene saber por
    qué.** Decía: *nada crea ni deshace relaciones en marcha, así que esta
    condición se decide en el tick 0 y no vuelve a cambiar; no escribas un arco
    que dependa de ella*. Desde D-071 el parto anuda lazos, así que esta es la
    única vara que se puede cumplir por algo que PASA y no por algo que se
    acumula — y de paso la única que expresa querer algo que depende de otra
    persona.

    Sigue en pie la otra mitad: el validador avisa cuando la meta ya está
    cumplida de salida, porque eso sigue siendo contenido muerto.
    """

    requires_edad: int = Field(default=0, ge=0)
    """No empieza hasta que su dueño tenga esta edad, en ticks. 0 = desde el
    primer día (D-081).

    **Un recién nacido no quiere nada**, y hasta aquí el motor no sabía decirlo:
    toda meta que no esperase a otra nacía ACTIVE, así que una criatura salía
    del parto con las ambiciones de un adulto puestas. Se nota poco porque las
    puertas de las acciones ya le impiden perseguirlas — y ese es justo el
    problema: un empujón que no puede atenderse escora el eje sin que nada lo
    resuelva.

    Bloquea igual que `requires_goal`, y por eso comparte estado (`LOCKED`) y
    consecuencia: **una meta bloqueada no se cierra NI SE PIERDE**, así que el
    plazo no corre mientras se espera. Al revés, quien nace con una meta a diez
    años y un plazo de tres la habría perdido antes de entenderla.

    Las dos condiciones se pueden combinar, a diferencia de las cuatro varas de
    logro: no son dos formas de medir lo mismo, son dos motivos distintos para
    no haber empezado todavía.
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

    prestigio: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto prestigio le da a SUS GRUPOS conseguirlo (D-133).

    **Con rendimiento decreciente** (D-136): lo que aporta se aplica sobre lo
    que le FALTA al grupo, `prestigio += aporte · (1 - prestigio)`. Así el
    primer héroe hace el nombre y el décimo apenas lo mueve, que es lo que un
    apellido significa — y no hay techo que alcanzar, así que no puede quedarse
    clavado arriba y dejar de decir nada. Sumando y recortando, una casa llegó
    a 1.000 en dos años de corrida.

    *«Fue un héroe reconocido, y desde entonces su apellido pesa.»* Es la única
    forma que tiene este motor de decir eso: el prestigio de una casa no se
    declara, se acumula con lo que logran los suyos. Y como decae solo
    (`FactionKindSpec.prestigio_por_tick`), mantenerlo es trabajo de cada
    generación — un apellido no se hereda hecho.

    Va en la meta y no en la acción a propósito: lo que da nombre a una casa no
    es lo que sus miembros hacen todos los días, es lo que consiguen.
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
    initial_rank: dict[NeedId, int] = Field(default_factory=dict)
    """Cuántos rangos lleva rotos al empezar la partida (D-135).

    Sin esto, los doscientos de un pack arrancan a rango 0 tengan diecisiete
    años o sesenta y uno, y eso miente en todo lo que mire el rango. Se vio con
    la vejez (D-084): los cincuenta que ya pasaban de esa edad recibían la
    condición con gravedad 1.000 **todos**, porque la ablanda el rango y ninguno
    tenía ninguno — la diferenciación por biografía solo aparecía en quien
    cumplía los cincuenta dentro de la corrida.

    Es el hermano de `edad_inicial` y va con él: un pack que declara edades y no
    rangos está diciendo que sus mayores no han hecho nada con su vida.

    Solo sobre ejes con `rank_slowdown`, y el validador lo comprueba: en un eje
    sin rangos el número no significaría nada.
    """

    edad_inicial: int = Field(default=0, ge=0)
    """Cuántos ticks lleva en el mundo cuando empieza la partida (D-070).

    El pack lo declara y el estado guarda su inverso: `nacido_en = -edad_inicial`,
    para que la edad sea siempre `tick - nacido_en` y no haya dos fórmulas según
    si alguien estaba al principio o nació después. Un nacido en marcha entra
    con `nacido_en` igual al tick del parto y cae en la misma cuenta.

    0 es un mundo sin edades, y es el defecto: los cuatro packs anteriores a
    esto siguen significando lo mismo. Ojo con dejarlo a 0 en un pack CON
    puertas de edad — todo el reparto sería recién nacido.
    """

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


class EndingSpec(Spec):
    """Cómo acaba una partida (unidad 19). Sin la sección, el mundo no acaba nunca
    y ningún camino nuevo se activa.

    `last_standing`: queda uno y gana. Con esto, morir no mata al último que queda:
    es la única puerta, y el mundo siempre tiene un ganador.
    """

    last_standing: bool = False


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

    se_rompe_sin_verse: int = Field(default=0, ge=0)
    """Tras cuántos ticks sin cruzarse deja de ser. 0 = nunca (D-087).

    **Invierte lo que el README decía**: *una relación con nombre no se disuelve
    nunca*. Valía mientras las únicas relaciones fueran de sangre y de oficio,
    donde es cierto —un hermano al que no ves en un año sigue siendo tu
    hermano—, pero deja de valer en cuanto un mundo tiene noviazgos: alguien a
    quien no ves desde hace meses no es tu novio, y sostener que lo es no es
    conservador, es falso.

    Por eso lo decide el PACK relación a relación, como el suelo de aprecio
    (D-034), y no el motor: la sangre declara 0 y no se rompe jamás.

    Es el hermano de `bond_horizon`, que olvida a quien no ves — y `forget_bonds`
    protege a los tuyos de ese olvido justamente porque son tuyos. Cuando esto
    rompe el lazo, la protección se cae con él y el olvido sigue su curso, que es
    el orden correcto: primero dejas de ser algo suyo, después se te olvida.
    """

    se_rompe_bajo: float | None = Field(default=None, ge=-1.0, le=1.0)
    """Aprecio por debajo del cual deja de ser. `None` = nunca (D-087).

    Mira el aprecio **desdibujado** (`Bond.regard_at`), no el crudo ni el que
    devuelve `regard_for`, y las dos exclusiones importan:

    - **No el crudo**, que fue el primer intento y salió inerte. El valor crudo
      solo lo mueve compartir algo, así que la ausencia no lo baja: una pareja
      que deja de verse conservaba su aprecio intacto para siempre. Medido, 120
      días de `confluencia`: cero rupturas por esta vía y ni un solo vínculo del
      mundo por debajo del umbral.
    - **No el de `regard_for`**, que aplica el suelo de la relación. Con el
      suelo puesto, una pareja con `regard_floor` no podría romperse jamás por
      desamor — que es justo lo que un suelo NO quiere decir. **El suelo
      gobierna cómo tratas a alguien mientras es tuyo; esto, si lo sigue
      siendo.**

    Así las dos causas dicen lo mismo a dos escalas: `se_rompe_sin_verse` es el
    corte duro y esto la cuesta abajo. Con el desdibujado de `confluencia`
    (0.9997 por tick), un aprecio de 0.5 tarda unos 56 días en caer a 0.1.
    """

    hereda: bool = False
    """Quien tenga esta relación con un difunto puede heredar sus propiedades
    (D-055, propiedad).

    No hace falta esperar a que exista el nacimiento para tener herencia: la
    relación ya es un hecho declarado en el pack, y "quién puede heredar" es
    exactamente la misma pregunta que "quién es tu familia", que las
    relaciones ya contestan. Un pack sin ninguna relación con `hereda: true`
    no pierde nada — sus propiedades simplemente se quedan sin dueño al morir
    quien las tenía, que es un estado tan legítimo como cualquier otro.

    Con varios candidatos, se lleva la propiedad ENTERA quien tenga mayor
    aprecio hacia el difunto (`regard_for`, la misma función que ya decide
    cuánto duele una muerte) — no se reparte fraccionada, porque una
    propiedad indivisible partida en trozos deja de significar lo que
    significaba.
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
# Propiedad: quién tiene qué
# ---------------------------------------------------------------------------
class PropertyKind(StrEnum):
    """Qué clase de cosa es una propiedad. Cerrado y del motor, como
    `TemperamentKnob`: el motor necesita distinguir una PERSONA de las otras
    cuatro para saber CÓMO rinde (renta pasiva o tributo sobre lo que gana),
    pero no necesita saber qué es una granja, un objeto o un título.
    """

    LUGAR = "lugar"
    PERSONA = "persona"
    OBJETO = "objeto"
    TITULO = "titulo"
    DEUDA = "deuda"


class PropertySpec(Spec):
    """Algo que alguien puede poseer, y lo que le rinde a quien lo tenga.

    Una sola forma para las cinco clases — no cinco primitivas — porque solo
    hay DOS formas de rendir, y las cinco se reparten entre ellas:

    - `renta`: ingreso pasivo por tick, ajeno a lo que haga nadie. Es lo que
      significa poseer un LUGAR, un OBJETO, un TÍTULO o una DEUDA — una
      tierra da lo mismo la trabaje quien la trabaje, y una deuda cobra
      aunque el deudor no haga nada ese tick.
    - `tributo`: una fracción — no un monto fijo — de lo que GANA el objeto
      poseído con sus propias acciones. Solo tiene sentido sobre una
      PERSONA: a diferencia de una tierra, decide por sí misma y gana algo
      distinto cada vez, así que no hay "lo mismo" que rendir de antemano.

    Deliberadamente NO restringe qué puede poseerse. En un mundo con
    esclavitud una persona es tan propiedad como una granja, y el motor no
    necesita saber la diferencia moral entre las dos — solo la mecánica, que
    es esta. Que sea injusto, o legal, o motivo de venganza, es contenido y
    cultura (un código moral por facción), no motor: el mismo principio que
    ya sostiene `gives` negativo, aplicado un nivel más arriba.

    Hoy es puramente económica y a propósito (primera pasada): posee a
    alguien y no le tocas la voluntad, solo una parte de lo que gana. No
    restringe qué puede hacer ni dónde puede ir — eso, si llega, es la capa
    de coerción que pertenece al futuro frente de ética, no a esta.
    """

    id: PropertyId
    label: str
    tipo: PropertyKind

    objeto: str
    """A quién o qué se refiere. Un `AgentId` si `tipo` es PERSONA, un
    `PlaceId` si es LUGAR — y se validan como tales. Para OBJETO, TITULO y
    DEUDA es libre: el motor no tiene una primitiva para lo que no vive en el
    mapa ni en el censo, y forzarle una sería inventar precisión que nadie
    puede escribir.
    """

    dueño_inicial: AgentId | None = None
    """Quién la tiene al empezar la partida. `None` = nace sin dueño.

    Una propiedad de un GRUPO no se declara aquí: los grupos los funda la gente
    (D-123), así que ninguno existe cuando el pack se carga. Se llega a ella
    heredando (D-130).
    """

    renta: dict[NeedId, float] = Field(default_factory=dict)
    """Cuánto rinde por tick a quien la tenga, ajeno a lo que haga. Vacío en
    una PERSONA: ver `tributo`."""

    tributo: dict[NeedId, float] = Field(default_factory=dict)
    """Qué fracción [0, 1] de cada eje que GANE el `objeto` (si es una
    PERSONA) se redirige también a quien la posee. Vacío en las otras cuatro
    clases: ver `renta`."""

    saldo: dict[NeedId, float] = Field(default_factory=dict)
    """Cuánto queda por cobrar en total antes de que la propiedad se extinga.
    **Vacío = perpetua**, que es el defecto y lo que eran las cinco clases
    hasta aquí (D-065).

    Solo tiene sentido en una DEUDA, y el pack no carga si lo declara otra
    clase: una deuda se salda y deja de existir, mientras que un lugar o un
    título siguen siendo lo que son cuando dejan de rendir. Un yacimiento que
    se agota es una idea distinta —la propiedad sigue ahí, vacía— y merecerá
    su propio campo el día que un mundo lo pida; darle este significaría que
    la mina desaparece del mapa al agotarse.

    Las mismas claves que `renta`, por lo mismo que en `DebtSpec`: un eje con
    renta y sin saldo no se amortizaría nunca.
    """


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


class Progenitor(StrEnum):
    """De cuál de los dos se hereda algo al nacer (D-129).

    El motor conoce a los dos por su papel en la condición —quién la llevaba y
    quién se la pegó— y no sabe cuál es cuál en el mundo. Que un apellido venga
    del padre, de la madre o del que tenga uno es una convención de cada
    cultura, y por eso lo dice el pack.
    """

    PORTADOR = "portador"
    CAUSANTE = "causante"


class HerenciaDeFaccion(Spec):
    """De quién hereda el nacido su pertenencia a un grupo de esta clase.

    `de` es un ORDEN DE PREFERENCIA, no una elección única, y ahí está todo el
    diseño: `[causante, portador]` es un apellido paterno **con la madre como
    respaldo**, que es lo que hace falta para que el hijo de padre desconocido
    no se quede sin casa. Con una sola opción habría que elegir entre una regla
    que deja huérfanos sin apellido y otra que no expresa la convención.
    """

    tipo: FactionKindId
    de: tuple[Progenitor, ...] = (Progenitor.PORTADOR,)


class FactionKindSpec(Spec):
    """Qué CLASE de grupo es este: un gremio, una casa, un país (D-090).

    El pack declara las clases, no los grupos. Es la diferencia que hace posible
    que emerjan: un mundo puede empezar sin una sola facción y llenarse de
    gremios, y el motor sabe qué es un gremio sin que ninguno esté escrito.

    Es el mismo reparto que ya rige en otras dos capas de este motor: el pack
    dice qué es una `pareja` y el mundo dice quién es pareja de quién; el pack
    dice qué es una DEUDA y el mundo dice quién le debe a quién. Aquí el pack
    dice qué es un gremio y el mundo dice cuáles hay.

    **Lo que un grupo NO es**: un rasgo compartido. `enano` y `guerrero` ya
    reparten a la población y ya gatean acciones, y les falta exactamente lo que
    hace que un grupo sea un grupo — que tenga identidad propia, que se entre y
    se salga, que posea cosas y que sus intereses choquen con los de otro. Un
    número en una ficha no puede tener nada de eso.
    """

    id: FactionKindId
    label: str

    exclusive: bool = False
    """Como mucho una de esta clase por persona. Un país sí, un gremio quizá no.

    Mismo campo y mismo significado que en una relación, y por el mismo motivo:
    hay pertenencias que se contradicen entre sí y otras que se acumulan.
    """

    company_multiplier: PositiveFactor = 1.0
    """Cuánto pesa la presencia de alguien de tu mismo grupo, sobre el aprecio
    que ya le tengas.

    Espejo exacto de `RelationSpec.company_multiplier`, un escalón más arriba:
    aquello dice que un hermano no es un desconocido cualquiera, y esto que un
    hermano de gremio tampoco. Se componen — ser las dos cosas pesa más.
    """

    lealtad_inicial: float = Field(default=0.5, ge=0.0, le=1.0)
    """Con cuánta lealtad entra quien entra."""

    lealtad_minima: float = Field(default=0.0, ge=0.0, le=1.0)
    """Por debajo de esto se le expulsa. 0.0 = no se expulsa a nadie.

    **Pertenecer es tener lealtad**, literalmente: la lealtad de alguien en una
    facción ES su pertenencia, así que expulsar es borrar ese número y no hay
    dos sitios que puedan contradecirse sobre quién es miembro. Una lista de
    miembros aparte sería la segunda puerta del mismo mecanismo.
    """

    prestigio_por_tick: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto prestigio pierde el grupo por tick. 0.0 = no se pierde nunca.

    Que un apellido mantenga su peso entre generaciones tiene que ser trabajo
    de los hijos, no una propiedad del apellido: sin desgaste, una sola hazaña
    sostiene un linaje para siempre — el mismo error que las parejas eternas de
    antes de D-087 y que la lealtad sin enfriar de antes de D-125.
    """

    hereda: bool = False
    """Si un grupo de esta clase recibe lo que un miembro deja sin heredero
    (D-130).

    **Cierra D-057**, que llevaba abierta desde la propiedad: sin una entidad
    colectiva, lo que alguien dejaba sin nadie que calificara se quedaba sin
    dueño y se evaporaba. Con esto el patrimonio se acumula en el linaje, que es
    lo que hace que unas casas sean ricas y otras pobres — y sin eso un título
    de nobleza no tendría nada que reconocer.

    Va detrás de la herencia por sangre, no delante: primero los tuyos, y la
    casa solo cuando no queda ninguno. Al revés, un padre con hijos vivos les
    dejaría todo a los primos.
    """

    lealtad_por_tick: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánta lealtad se pierde por tick sin hacer nada por el grupo.

    Es lo que hace que la pertenencia haya que sostenerla: sin esto, entrar una
    vez es ser de los suyos para siempre, que es el mismo error que las parejas
    eternas de antes de D-087.
    """


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
    content: tuple[ContentTag, ...] = ()
    """Como el de las acciones: para las líneas y los velos (unidad 17)."""

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

    visible: bool = False
    """Si se ve a simple vista que la lleva (unidad 18). Una herida sí; una
    infección o un veneno, no. Lo lee la escena, no la simulación."""

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

    desde_edad: int = Field(default=0, ge=0)
    """Edad a la que esta condición personal se pega SOLA, en ticks. 0 = nunca,
    y es el defecto (D-084).

    El quinto sitio que inflige algo, y el primero que no lo causa nadie: los
    otros cuatro salen de una acción, de una situación del mundo, de lo que otro
    te hace o de nacer. Esto sale de estar vivo.

    Solo tiene sentido en una `personal`, y sin plazo: lo que llega con la edad
    no se pasa. Se pega una vez —`afligir` agrava si ya la llevaba, así que
    comprobar antes no es una optimización sino la diferencia entre envejecer y
    envejecer cada tick— y desde entonces hace lo que la situación diga: drenar
    un eje, rebajar lo que rinde el trabajo, quitar ganas de viajar.

    **Alcanza a todo el mundo por igual y a la vez**, incluido quien ya nació
    viejo: el primer tick pega la condición a quien ya pase de la edad, que es
    lo correcto — un pack no declara a un anciano diciendo que es joven.
    """

    gravedad_por_rango: dict[NeedId, float] = Field(default_factory=dict)
    """Qué rangos ABLANDAN esta condición al pegarse, y cuánto.

        gravedad = 1 / (1 + Σ peso · rango)

    Es lo que hace que la vejez no le caiga igual a todo el mundo, y que la
    diferencia sea **lo que hiciste con tu vida** y no con lo que naciste: un
    rango solo se rompe trabajando el eje. Quien nunca trabajó ninguno lleva
    rango 0 y la gravedad entera; quien llegó lejos la lleva a la mitad o a un
    tercio, y se muere mucho más tarde.

    El rasgo ya tenía su canal para esto —`cost_multipliers`, el temple, que
    `endure` aplica— y no sirve aquí: el temple es de nacimiento y esto es
    biografía. Los dos se componen, que es lo correcto: nacer fuerte y además
    haber vivido activo.

    Se calcula UNA vez, al pegarse. Lo que fuiste hasta entonces decide cómo
    envejeces; entrenar después no deshace los años, y esa es una regla que se
    lee sola.
    """

    al_expirar: BirthSpec | None = None
    """Qué nace cuando esta condición se pasa sola (D-071). `None` = nada, y es
    el defecto.

    Solo tiene sentido en una `personal` con `lasts` — una condición que no se
    pasa nunca no llega a expirar, y una del mundo no la lleva nadie encima, así
    que no habría de quién heredar. El pack no carga si lo declara otra cosa.

    Se dispara donde ya se anunciaba que la condición terminaba, no en un paso
    nuevo del tick: expirar y dar fruto son el mismo instante, y separarlos
    dejaría un tick en que la condición ya no está y lo que dejó todavía no.
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
class BirthSpec(Spec):
    """Lo que aparece cuando una condición personal se pasa sola: **un agente
    nuevo** (D-071).

    Es la segunda entidad que el motor sabe crear en marcha, después de la
    deuda (D-065), y la que de verdad cambia lo que un mundo puede contar: un
    reparto cerrado se convierte en un reparto que se renueva. Cuelga de la
    situación y no de la acción a propósito — entre causar algo y que ese algo
    dé fruto pasa tiempo, y la única pieza del motor que sabe esperar es una
    condición con `lasts`.

    Quién lo tiene son dos personas, y el motor las conoce sin que nadie se lo
    diga: el **portador** es quien lleva la condición encima y el **causante**
    es quien se la pegó (`Condicion.por_quien`). Nada aquí dice cuál de los dos
    es qué en el mundo — eso lo dicen los rasgos que el pack sortea y las
    relaciones que declara.

    El causante puede no estar: pudo morir durante la espera, y nueve meses son
    tiempo de sobra en un mundo violento. Entonces el nacido hereda solo del
    portador y se queda sin esa relación. **No es un caso de error**: es un
    huérfano, y el motor no tiene por qué impedirlo.
    """

    hereda_traits: tuple[TraitId, ...] = ()
    """Qué rasgos se mezclan de los dos progenitores: la media, más un ruido
    sorteado por clave dentro de `ruido`.

    La media y no uno de los dos porque un hijo no es la copia de nadie, y el
    ruido porque sin él dos hermanos con los mismos padres serían idénticos y
    la línea de sangre no explicaría nada que no explicara ya el apellido. Con
    un solo progenitor conocido, la media es su valor a secas.
    """

    hereda_faccion: tuple[HerenciaDeFaccion, ...] = ()
    """Qué pertenencias hereda el nacido, y de quién (D-129).

    **Es lo que separa una casa de un gremio.** Sin esto, un grupo cuya
    pertenencia solo se recluta no es un linaje: es un club al que hay que
    apuntarse, y entonces no tiene sentido que sea exclusivo ni que no se salga
    de él. Con esto, los linajes que el parto ya crea —hay padre y madre
    registrados en cada nacimiento— se convierten en apellidos que se propagan.
    """

    funda_faccion: FactionKindId | None = None
    """Y si NINGUNO de los dos tiene una de esa clase, el nacimiento funda una,
    con los dos progenitores dentro (D-129).

    Un apellido no se decide: empieza cuando hay a quien pasárselo. Colgarlo del
    parto y no de una acción es lo que lo hace posible — una acción tendría que
    ganar una deliberación contra `charlar`, y este mundo lleva cinco
    mecanismos perdiendo esa pelea (E-009). Aquí no hay nada que elegir: la
    línea empieza porque continuó.

    Se funda en nombre del PORTADOR, que es el único de los dos que seguro
    está: el causante pudo morir durante la espera.
    """

    hereda_goals: bool = False
    """Si el nacido hereda las metas de sus progenitores (D-132).

    **Es lo que hace que una casa tenga costumbres sin declararlas.** Un agente
    no tiene políticas: delibera por utilidad cada tick, y lo único que expresa
    *«esto es lo que persigo»* es una meta. Así que una casa que transmite su
    oficio no es una bandera en la facción — es que sus hijos quieren lo que
    querían sus padres, y los de la casa de al lado no.

    Se heredan las de los DOS, sin repetir, y con el estado de partida que les
    tocaría por su cuenta: una meta lograda por el padre no nace lograda en el
    hijo, que sería regalarle una vida.
    """

    hereda_tastes: bool = False
    """Si el nacido hereda los gustos de sus progenitores, promediados (D-086).

    Sin esto la atracción se acaba en una generación: los gustos son la única
    forma de que a alguien le atraiga alguien, y un nacido en marcha no tiene
    ninguno porque no hay YAML donde escribírselos. Se promedian los dos como
    los rasgos, y con un solo progenitor conocido son los suyos a secas.

    Es aprendido y no genético, y el motor no distingue: aquí lo que importa es
    que se transmita, no por qué.
    """

    ruido: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto puede apartarse de la media, arriba o abajo. 0.0 = clavado a ella.

    Se sortea por clave (`blake2b(semilla, ...)`) como todo lo demás: dos
    procesos con la misma semilla tienen que engendrar a la misma persona.
    """

    sortea_traits: tuple[tuple[TraitId, ...], ...] = ()
    """Grupos de rasgos EXCLUYENTES entre sí: de cada grupo se enciende
    exactamente uno, a 1.0, y los demás a 0.0.

    Es lo que hace falta para lo que no se hereda mezclado sino que sale a cara
    o cruz. Un grupo y no un rasgo suelto porque la exclusividad es la mitad del
    significado: sortear dos veces por separado deja a alguien siendo las dos
    cosas o ninguna.
    """

    traits: dict[TraitId, float] = Field(default_factory=dict)
    """Lo que TODO nacido lleva igual, herede lo que herede. Se aplica después
    de la mezcla y del sorteo, así que también sirve para fijar a la fuerza algo
    que el pack no quiera dejar al azar."""

    initial_needs: dict[NeedId, float] = Field(default_factory=dict)
    """Con qué empieza cada eje. Lo que no se nombre entra con el `initial` de
    la necesidad, igual que cualquier agente del pack."""

    goals: tuple[GoalId, ...] = ()
    """Qué metas trae puestas, del catálogo que el pack ya declara en algún
    agente. Vacío = nace sin arcos, que es lo que pasaba hasta hoy con quien
    nacía en marcha (ver `AgentState.metas_activas`)."""

    relacion_con_portador: RelationId | None = None
    """Qué es el nacido DE quien lo llevaba. El otro lado lo pone `inverse`.

    Del nacido hacia el progenitor y no al revés porque es la dirección que
    siempre existe: hay un nacido, y puede no haber causante.
    """

    relacion_con_causante: RelationId | None = None
    """Qué es el nacido de quien causó la condición. Se omite si no se sabe
    quién fue o si ya no está."""

    inflicts: AflictionSpec | None = None
    """Qué condición trae puesta el nacido. `None` = ninguna.

    Cuarto sitio que infligia algo, y el primero sobre alguien que acaba de
    aparecer. Es lo que hace escribible la niñez: una condición con `lasts` que
    dura lo que el pack diga, que puede cambiar lo que rinde y cómo se decide
    mientras dura, y —sobre todo— que **se ve estando delante**, así que
    `TargetSpec.requires_condition` puede apuntar a ella. Sin eso no hay forma
    de escribir una acción que solo valga sobre un crío: el motor sabe exigir
    una edad MÍNIMA al destinatario, no una máxima.
    """

    regard_buscado: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Con cuánto aprecio arranca hacia el nacido el progenitor que LO BUSCABA
    (D-076).

    "Buscarlo" no es un campo nuevo: es tener una meta cuyo `at_kin` nombre la
    relación que este parto le crea. El motor ya sabía decir *quiero tener a los
    míos*, y hasta hoy no había forma de que nada lo cumpliera; ahora sí, y de
    paso contesta lo que un suelo de aprecio por relación no puede — no todo el
    que se convierte en padre quiere a su hijo igual, y la diferencia es si lo
    quiso ANTES.
    """

    regard_no_buscado: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Y el que no lo buscaba. Puede ser bajo sin ser negativo: quien no lo
    quería no arranca odiándolo, arranca sin nada — y a partir de ahí el aprecio
    sube conviviendo, como el de cualquiera. Un padre que no lo buscaba puede
    acabar queriéndolo si está presente, y no si no lo está."""

    regard_hacia_progenitores: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Con cuánto aprecio arranca el nacido hacia ellos. Uno solo para los dos:
    un recién nacido no sabe quién lo quiso."""

    regard_entre_progenitores: float = Field(default=0.0, ge=0.0, le=1.0)
    """Cuánto sube el aprecio MUTUO entre los dos cuando LOS DOS lo buscaban.

    Es lo que un premio hacia la cría no puede decir: haber conseguido juntos lo
    que los dos querían es un hecho entre ELLOS. Solo cuando los dos —con uno
    solo no hay nada compartido que celebrar— y se suma al aprecio que ya
    hubiera, así que una pareja que ya se quería acaba más arriba que dos
    desconocidos que coincidieron.
    """

    label: str = ""
    """Con qué nombre aparece en el log. Vacío = su propio id.

    El motor no sabe componer un nombre —eso es ambientación— así que lo más
    honesto que puede hacer es repetir el id y dejar que el pack ponga un
    prefijo legible delante.
    """


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

    lod_focus_radius: int | None = Field(default=None, ge=0)
    """Hasta cuántos ticks de viaje del foco se simula fino (D-152). `None`
    apaga el LOD, y es el defecto: un mundo que no lo pide se simula entero,
    como siempre, haya foco o no.

    Quien queda más lejos delibera sobre un menú corto (`lod_menu_radius`). Es
    la percepción limitada aplicada a la simulación: el motor sabe con detalle
    lo que pasa cerca de quien mira, y el resto lo resuelve más barato.
    """

    lod_menu_radius: int = Field(default=3, ge=0)
    """Cuántos ticks de viaje abarca el menú de quien está lejos del foco. A su
    menú se añade siempre su casa, aunque quede más lejos.

    Medido en `confluencia` (D-151): con solo el lugar actual, quien está en un
    sitio sin comida ni cama no puede irse y las muertes se multiplican por
    cinco. Con 3 ticks más la casa, el tiempo baja un 38 % y las muertes pasan
    de 2 a 4 en una semana. Sin `lod_focus_radius` no se lee.
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

    perception_days: int = Field(default=14, ge=1)
    """Hasta cuántos días atrás guarda cada persona lo que vio delante (unidad 23-0)."""
    perception_max: int = Field(default=300, ge=1)
    """Cuántos hechos presenciados guarda cada persona, como mucho. Pasado el tope se
    descartan los más viejos."""

    plot_lean_max: float = Field(default=1.5, ge=1.0)
    """Tope de cualquier multiplicador de inclinación de una trama, en los dos sentidos
    (unidad 23a): ni un lugar ni una acción pueden dominar la utilidad."""

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

    agravio_de_oidas: float = Field(default=0.3, ge=0.0, le=1.0)
    """Cuánto pesa en `agravio()` lo que uno oyó de otro, frente a lo que vivió.

    Un rumor copia el recuerdo con su `por_quien` (`oir`), y sin esto el rencor
    se contagiaba entero: quien oye que insultaste a otro te cuenta un agravio.
    Medido en `confluencia` con cuatro semillas (4271, 1, 2, 3), inyectando lo
    oído como agravio al 100 % (lo de antes), al 0 % y al 30 %:

        peso de lo oído   muertes   crisis   salud   desafíos
        100 %                40     23.6 %    0.47      6298
        0 %                  50     22.9 %    0.53      5374
        30 %                 39     22.6 %    0.51         —

    Con 0 % las muertes suben un 25 %, todas por `salud`, con menos desafíos:
    el mecanismo no está trazado, y por eso no se elige. Con 30 % se queda donde
    estaba. 1.0 es el comportamiento anterior a la unidad 15b."""


class Tone(StrEnum):
    """Cómo suena una réplica. Deliberadamente pobre, como `Outcome`: la regla
    del respaldo tiene que saber qué significa cada uno, y un tono que el pack
    inventara no lo sabría elegir nadie. El matiz lo pone la prosa."""

    FRIENDLY = "amable"
    CURT = "seco"
    HOSTILE = "hostil"
    SAD = "triste"
    AFRAID = "asustado"


class SocialAct(StrEnum):
    """Lo que alguien le hace a otro hablándole (unidad 15, D-164). Cerrado y
    del motor, como `Tone`: la recepción tiene que saber qué es cada uno, y un
    acto que inventara el pack no lo sabría recibir nadie. Lo que se dijo
    exactamente lo pone la voz, y no se guarda.

    `ASK` y `AFFIRM` no pesan por sí mismos: lo que mueven lo decide
    comparar lo afirmado con lo que el otro sabe (unidad 15b). Mentir no es un
    acto: una afirmación es verdadera o falsa según el motor, se diga como se
    diga."""

    GREET = "saludar"
    CHAT = "charlar"
    FLATTER = "halagar"
    JOKE = "bromear"
    COURT = "cortejar"
    APOLOGIZE = "disculparse"
    CONFESS = "confesar"
    INSULT = "insultar"
    THREATEN = "amenazar"
    ASK = "preguntar"
    AFFIRM = "afirmar"
    GIVE = "dar"
    ASK_FOR = "pedir"


class ClaimKind(StrEnum):
    """Lo que el jugador puede afirmar y el motor comprobar (unidad 15b)."""

    AT = "esta_en"
    ALIVE = "vive"
    DEAD = "ha_muerto"
    HARMED = "hizo_dano"


class QuestionKind(StrEnum):
    WHERE = "donde_esta"
    ABOUT = "que_sabes"


class SocialActSpec(Spec):
    """Cuánto pesa un acto, antes de quién lo recibe. Calibración del mundo,
    no del motor: en una corte un insulto pesa más que en un cuartel."""

    regard: float = Field(ge=-1.0, le=1.0)
    """Cuánto mueve el aprecio de quien lo recibe hacia quien habla, sobre la
    escala de cada mundo (en `confluencia`, el p90 del aprecio es 0.10)."""
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    """Cómo le sienta, para su memoria: lo negativo con nombre es agravio."""
    importance: float = Field(default=0.0, ge=0.0, lt=1.0)
    """Cuánto se le queda grabado. A cero, no lo recuerda."""


def _default_social_acts() -> dict[SocialAct, SocialActSpec]:
    """Medidos contra el aprecio de `confluencia` (p90 0.10, máximo 0.78) y el
    umbral del tono hostil de la voz (-0.2): dos insultos seguidos lo cruzan,
    un halago solo no hace amigos."""
    return {
        SocialAct.GREET: SocialActSpec(regard=0.01, valence=0.1, importance=0.05),
        SocialAct.CHAT: SocialActSpec(regard=0.02, valence=0.2, importance=0.1),
        SocialAct.FLATTER: SocialActSpec(regard=0.04, valence=0.3, importance=0.2),
        SocialAct.JOKE: SocialActSpec(regard=0.03, valence=0.3, importance=0.15),
        SocialAct.COURT: SocialActSpec(regard=0.05, valence=0.4, importance=0.3),
        SocialAct.APOLOGIZE: SocialActSpec(regard=0.03, valence=0.2, importance=0.2),
        SocialAct.CONFESS: SocialActSpec(regard=0.03, valence=0.2, importance=0.3),
        SocialAct.INSULT: SocialActSpec(regard=-0.08, valence=-0.5, importance=0.4),
        SocialAct.THREATEN: SocialActSpec(regard=-0.12, valence=-0.7, importance=0.6),
        SocialAct.ASK: SocialActSpec(regard=0.0),
        SocialAct.AFFIRM: SocialActSpec(regard=0.0),
        SocialAct.GIVE: SocialActSpec(regard=0.05, valence=0.4, importance=0.3),
        SocialAct.ASK_FOR: SocialActSpec(regard=0.0),
    }


class SocialSpec(Spec):
    """Cómo se habla en este mundo (unidad 15). Omitir la sección usa los
    valores por defecto; lo único que el pack tiene que decir para que hablar
    cueste tiempo es `action`."""

    action: ActionId | None = None
    """La acción que ocupa a quien conversa al cerrar la conversación («charlar»).
    Sin ella, hablar es gratis: el mundo no sabe qué es conversar."""
    max_acts: int = Field(default=6, ge=1)
    """Tope de actos por conversación: después, el otro se despide."""
    repeat_decay: float = Field(default=0.5, gt=0.0, le=1.0)
    """Lo que vale repetir el mismo acto en la misma conversación, por vez:
    el tercer halago seguido pesa un cuarto del primero."""
    leave_below: float = Field(default=-0.3, ge=-1.0, le=0.0)
    """Por debajo de este aprecio hacia quien le habla, el otro se va."""
    acts: dict[SocialAct, SocialActSpec] = Field(default_factory=_default_social_acts)
    trust_above: float = 0.05
    """Aprecio desde el que alguien te cuenta lo que sabe (o una relación)."""
    caught: SocialActSpec = SocialActSpec(regard=-0.10, valence=-0.5, importance=0.4)
    """Lo que cuesta que te pillen en una mentira: se aplica en lugar del peso
    del acto, y se recuerda con quien habló como culpable."""
    doubt: float = -0.02
    """Lo que baja el aprecio hacia quien habla cuando se le cree a medias (un
    éxito con coste en la tirada)."""
    accuse: float = 0.15
    """Cuánto baja el aprecio hacia el acusado de dañar a alguien, por unidad de
    aprecio a la víctima (si la víctima es el oyente, por 1)."""
    give_above: float = Field(default=0.15, ge=-1.0, le=1.0)
    """Aprecio mínimo del oyente hacia quien pide un objeto para dárselo. Por
    debajo, se niega. Un objeto equipado nunca se pide: sin él no hay pelea."""

    @model_validator(mode="after")
    def _all_acts(self) -> SocialSpec:
        # Un pack que calibra solo los insultos no puede dejar sin peso el
        # resto: se completa con los valores por defecto.
        faltan = {k: v for k, v in _default_social_acts().items() if k not in self.acts}
        if faltan:
            object.__setattr__(self, "acts", {**faltan, **self.acts})
        return self


class VoiceSpec(Spec):
    """Lo que un mundo dice de su gente cuando habla (unidad 07).

    Solo lo lee la capa de voz: la simulación no sabe que existe. Sin esta
    sección un pack corre igual; lo único que no puede hacer es hablar sin
    modelo, porque no tiene con qué.
    """

    identity_traits: tuple[TraitId, ...] = ()
    """Los rasgos que dicen QUIÉN es (pueblo, oficio, género). Se nombran si los
    tiene. Van aparte de los de carácter porque ningún campo del rasgo los
    distingue, y en castellano además deciden la concordancia."""

    character_traits: tuple[TraitId, ...] = ()
    """Los rasgos que dicen CÓMO es. Se nombran los tres más marcados de los que
    tenga a 0.3 o más."""

    fallback: dict[Tone, tuple[str, ...]] = Field(default_factory=dict)
    """Frases neutras por tono, para cuando el modelo falla o no se usa. El
    motor elige el tono; el mundo pone las palabras."""


class NewcomerSpec(Spec):
    """Con qué llega al mundo quien viene de fuera: el forastero que crea el
    jugador (unidad 10).

    Lo declara el pack y no el motor porque cuánto dinero trae un recién
    llegado, o dónde duerme la primera noche, es ambientación. La ficha del
    jugador gana a esto campo a campo; lo que la ficha no diga, lo pone el
    pack, y lo que tampoco diga el pack, el `initial` de cada necesidad.
    """

    home: PlaceId | None = None
    start_at: PlaceId | None = None
    initial_needs: dict[NeedId, float] = Field(default_factory=dict)
    traits: dict[TraitId, float] = Field(default_factory=dict)
    edad_inicial: int = Field(default=0, ge=0)


class CreationGroupSpec(Spec):
    """Un grupo de rasgos del que se elige uno (sexo, especie, oficio), o cero si
    el grupo es opcional. Los grupos no comparten rasgos: un rasgo en dos sitios
    sería una elección que el mundo no sabe cuadrar (D-175)."""

    id: str
    label: str
    traits: tuple[TraitId, ...]
    required: bool = True


class PotentialsSpec(Spec):
    """Los potenciales: números entre `min` y `max`, de `step` en `step`, que se
    compran con puntos o se tiran. Lo que cuesta una cifra lo dice el presupuesto
    de la dificultad, no el potencial en sí."""

    traits: tuple[TraitId, ...]
    min: float = Field(ge=0.0, le=1.0)
    max: float = Field(ge=0.0, le=1.0)
    step: float = Field(gt=0.0)


class RareSpec(Spec):
    """Un rasgo raro: nadie lo elige. Al crear, un sorteo con `chance` decide si
    se otorga, con una intensidad uniforme en `[min, max]`. Es lo que hace que un
    personaje sea distinto sin que el jugador lo haya pedido."""

    chance: float = Field(gt=0.0, le=1.0)
    min: float
    max: float


class CreationSpec(Spec):
    """Cómo puede el jugador crear su propio personaje (unidad 21a). Opcional: sin
    ella, la ficha se escribe a mano como siempre. El motor hace cumplir estas
    reglas; las cifras las pone el pack, porque cuántos puntos vale un potencial
    es del mundo y no del motor."""

    groups: tuple[CreationGroupSpec, ...] = ()
    potentials: PotentialsSpec | None = None
    budgets: dict[str, float] = Field(default_factory=dict)
    """Presupuesto de puntos por dificultad: `{id de dificultad: puntos}`. Vacío =
    el mundo no deja crear con puntos."""
    character: dict[TraitId, tuple[float, float]] = Field(default_factory=dict)
    """Lo que se elige gratis dentro de sus rangos: `{rasgo: [min, max]}`."""
    rare: dict[TraitId, RareSpec] = Field(default_factory=dict)


class WorldLore(Spec):
    """Lo que el mundo es, en texto, para que la primera escena no sea genérica
    (unidad 22). Lo redacta un autor fuera de la partida y lo aprueba quien juega:
    queda en el pack, fijo, y la partida no inventa el mundo.

    Nada de esto lo lee el motor. Lo leen el narrador y la página; por eso vive en
    `mundo.yaml` y no en el `pack.yaml` que genera `generar.py`."""

    premise: str = Field(min_length=1, max_length=4000)
    """Qué es este mundo, en uno a tres párrafos."""
    tone: str = Field(min_length=1, max_length=300)
    """Cómo se cuenta: una línea."""
    known: tuple[str, ...] = ()
    """Lo que todo el mundo sabe (quién manda, la magia, las tensiones), frases sueltas."""
    places: dict[PlaceId, str] = Field(default_factory=dict)
    """Descripciones para los lugares que el pack no describe. Un lugar descrito en
    el pack no se describe aquí: es error tener las dos."""


# ---------------------------------------------------------------------------
# Tramas personales (unidad 23a, D-178)
#
# Una trama vive en la cabeza de su protagonista. Los demás son referencias: el
# motor solo les mira lo que el protagonista puede ver, oír o recordar (23-0),
# y nunca lo que sienten. Por eso el vocabulario de condiciones se parte en dos
# listas cerradas, una para cada lado, y la carga rechaza lo que se salga.
# ---------------------------------------------------------------------------
MarkId = NewType("MarkId", str)
PlotId = NewType("PlotId", str)
StepId = NewType("StepId", str)
TestId = NewType("TestId", str)


class BeatKind(StrEnum):
    """Lo que puede pasar y que una trama espera (A.3). Vocabulario cerrado: un latido
    que el pack invente no lo reconocería ningún hecho del motor."""

    TALKED_WITH = "talked_with"
    HELPED_BY = "helped_by"
    SEEN_WITH = "seen_with"
    WON_AGAINST = "won_against"
    LOST_TO = "lost_to"
    REF_RANK_UP = "ref_rank_up"
    DECLARED_TO = "declared_to"
    REF_DIED = "ref_died"
    ARRIVED = "arrived"
    SITUATION_BEGAN = "situation_began"
    PROTECTED_BY = "protected_by"
    """La referencia combatió contra un llegado hostil delante del protagonista
    (23b-1, A.3). Lo mira `saw` sobre un `COMBAT`: no es un hecho de la trama."""


PROTAGONIST_KINDS = frozenset({
    "trait", "relation", "regard_to", "grudge_to", "rank", "need", "mark", "fame", "age",
    "situation", "place", "phase", "recent_event", "debt", "newcomer",
})
"""Lo que se puede leer del protagonista: todo lo suyo (A.2)."""

REF_KINDS = frozenset({
    "relation", "group", "creation", "fame", "age", "visible", "alive",
    "seen_together", "saw", "heard", "with",
})
"""Lo que se puede leer de una referencia: solo lo observable (A.2, §3.5). Un aprecio,
un agravio, una necesidad o una marca ajena no están en esta lista, y la carga lo rechaza."""

GLOBAL_KINDS = frozenset({"situation", "phase", "arc_phase"})
"""Lo que puede ir en `when`: lo que es del mundo, no de una persona. `arc_phase` es
una fase de un arco en curso (23b-1): la siembra de una trama solo puede empezar ahí."""


class ArcPhaseRef(Spec):
    """Una fase concreta de un arco (23b-1): para `when` de una trama, la siembra."""

    arc: ArcId
    phase: PhaseId


class PlotCondition(Spec):
    """Una condición de trama. Exactamente una clave del vocabulario por condición
    (`{trait: sociable, min: 0.6}`); `min`, `max` y `days` acotan la de la clave.

    Un campo por clave y no un diccionario libre a propósito: `extra="forbid"` hace que
    una clave fuera del vocabulario no cargue, en lugar de no hacer nada en silencio."""

    trait: TraitId | None = None
    relation: RelationId | None = None
    regard_to: str | None = None
    grudge_to: str | None = None
    rank: NeedId | None = None
    need: NeedId | None = None
    mark: MarkId | None = None
    fame: bool | None = None
    age: bool | None = None
    situation: SituationId | None = None
    personal: bool = False
    place: PlaceId | None = None
    phase: PhaseId | None = None
    recent_event: str | None = None
    """Un `EventKind` del motor por su valor. Lo valida el pack: `events.py` importa
    de aquí, así que este módulo no puede nombrar ese tipo."""
    debt: Literal["debe", "le_deben"] | None = None
    newcomer: int | None = Field(default=None, ge=0)
    group: bool | None = None
    creation: TraitId | None = None
    visible: SituationId | None = None
    alive: bool | None = None
    seen_together: str | None = None
    saw: str | None = None
    heard: bool | None = None
    with_: bool | None = Field(default=None, alias="with")
    min: float | None = None
    max: float | None = None
    days: int | None = Field(default=None, ge=1)
    arc_phase: ArcPhaseRef | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    def kind(self) -> str:
        """La clave del vocabulario que usa esta condición. Exactamente una."""
        usadas = [k for k, campo in _CLAVES_ORDENADAS if getattr(self, campo) is not None]
        if len(usadas) != 1:
            raise ValueError(
                "una condición lleva exactamente una clave del vocabulario, "
                f"no {usadas or 'ninguna'}"
            )
        return usadas[0]

    @model_validator(mode="after")
    def _one_kind(self) -> PlotCondition:
        self.kind()
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min es mayor que max")
        return self


def _campo(kind: str) -> str:
    """`with` es palabra reservada en Python: su campo se llama `with_`."""
    return "with_" if kind == "with" else kind


_CLAVES_ORDENADAS = tuple(
    (k, _campo(k)) for k in sorted(PROTAGONIST_KINDS | REF_KINDS | GLOBAL_KINDS)
)
"""Las claves del vocabulario y su campo, en orden fijo. Se calcula una vez: `kind()` se
llama por persona y por día, y rehacer el conjunto cada vez era un tercio del coste."""


class Leaning(Spec):
    """Una inclinación mientras un paso espera (A.5): un multiplicador suave sobre la
    utilidad del protagonista, por un lugar donde vio a la referencia o por una acción
    con una etiqueta. Nunca toca a la referencia."""

    where_seen: str | None = None
    action_tag: ContentTag | None = None
    multiplier: float = Field(gt=0.0)

    @model_validator(mode="after")
    def _one(self) -> Leaning:
        if (self.where_seen is None) == (self.action_tag is None):
            raise ValueError(
                "una inclinación va por `where_seen` o por `action_tag`, no por las dos"
            )
        return self


class Beat(Spec):
    """Lo que un paso de espera aguarda (A.3)."""

    kind: BeatKind = Field(alias="beat")
    ref: str | None = None
    tag: ContentTag | None = None
    """Solo para `helped_by`: la etiqueta que el pack pone a una acción de ayuda."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _shape(self) -> Beat:
        necesita_ref = self.kind is not BeatKind.SITUATION_BEGAN
        if necesita_ref and self.ref is None:
            raise ValueError(f"el latido {self.kind.value} necesita una referencia")
        if not necesita_ref and self.ref is not None:
            raise ValueError("situation_began no mira a ninguna referencia")
        if self.tag is not None and self.kind is not BeatKind.HELPED_BY:
            raise ValueError("solo helped_by lleva etiqueta")
        return self


class EffectSpec(Spec):
    """Un efecto de vocabulario cerrado (A.6). Solo toca al protagonista, y lo que toca a
    otro pasa por el mundo (una acción dirigida), nunca por aquí. Una clave por efecto."""

    mark: MarkId | None = None
    fame: bool | None = None
    regard: str | None = None
    memory: bool | None = None
    need: NeedId | None = None
    condition: SituationId | None = None
    goal: GoalId | None = None
    debt: str | None = None
    direction: Literal["presto", "pido"] | None = None
    """Para `debt`: `presto` = la persona presta a la referencia; `pido` = la
    referencia le presta a ella."""
    forgive: str | None = None
    item: ItemId | None = None
    delta: float | None = None
    valence: float | None = Field(default=None, ge=-1.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0)
    por_quien: str | None = None
    about: str | None = None
    action: ActionId | None = None
    """Para `debt`: la acción de préstamo del pack que abre la deuda (la puerta de
    deudas existente)."""
    days: int | None = Field(default=None, ge=1)
    factor: float | None = Field(default=None, gt=0.0, le=1.0)
    """Para `forgive`: qué parte del agravio queda."""
    arc_tally: ArcTallySpec | None = None
    """Suma al contador de un arco en curso, atribuido a quien vive la trama (23b-1, A.3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _one(self) -> EffectSpec:
        claves = [
            k for k in ("mark", "fame", "regard", "memory", "need", "condition", "goal",
                        "debt", "forgive", "item", "arc_tally")
            if getattr(self, k) is not None and getattr(self, k) is not False
        ]
        if len(claves) != 1:
            raise ValueError(f"un efecto lleva exactamente una clave, no {claves or 'ninguna'}")
        if claves[0] in ("mark", "fame", "need", "regard") and self.delta is None:
            raise ValueError(f"el efecto {claves[0]} necesita `delta`")
        if self.mark is not None and self.delta is not None and not float(self.delta).is_integer():
            raise ValueError(f"una marca cambia en enteros, no en {self.delta}")
        if self.memory and (self.valence is None or self.importance is None or self.about is None):
            raise ValueError("un efecto memory necesita valence, importance y about")
        if self.debt is not None and (self.action is None or self.direction is None):
            raise ValueError("un efecto debt necesita la acción de préstamo y el sentido")
        if self.forgive is not None and self.factor is None:
            raise ValueError("un efecto forgive necesita `factor`")
        return self


class TestUse(Spec):
    """Una prueba enfrentada en un paso (A.4). `vs` es la referencia con la que se tira,
    si la hay; sin ella, la prueba es contra la dificultad que declara el pack."""

    id: TestId
    vs: str | None = None
    on_success: tuple[EffectSpec, ...] = ()
    on_failure: tuple[EffectSpec, ...] = ()


class ActUse(Spec):
    """Una acción del pack dirigida a una referencia (A.4). La ejecuta el motor por sus
    puertas, no la trama."""

    action: ActionId
    to: str
    within_days: int = Field(ge=1)
    """Cuánto espera la intención a que la acción esté en el menú del protagonista."""
    on_timeout: StepId | None = None
    """Adónde pasa la trama si la intención caduca. `None` = la trama acaba."""


class Choice(Spec):
    """Una opción de un paso de decisión (A.1): exactamente uno de `effects`, `test` o
    `act`, y luego `next`."""

    label: str = Field(min_length=1, max_length=160)
    requires: tuple[PlotCondition, ...] = ()
    appeal: dict[TraitId, float] = Field(default_factory=dict)
    default: bool = False
    effects: tuple[EffectSpec, ...] | None = None
    test: TestUse | None = None
    act: ActUse | None = None
    next: StepId | None = None

    @model_validator(mode="after")
    def _one(self) -> Choice:
        usos = [x for x in (self.effects, self.test, self.act) if x is not None]
        if len(usos) != 1:
            raise ValueError(
                f"la opción {self.label!r} lleva exactamente uno de effects, test o act"
            )
        return self


class Step(Spec):
    """Un paso: de espera (`expects`) o de decisión (`choices`), nunca de los dos."""

    id: StepId
    expects: Beat | None = None
    within_days: int | None = Field(default=None, ge=1)
    on_timeout: StepId | None = None
    leanings: tuple[Leaning, ...] = ()
    next: StepId | None = None
    """Tras el latido, en un paso de espera. `None` = la trama acaba."""
    choices: tuple[Choice, ...] = ()
    tint: dict[str, Beat] = Field(default_factory=dict)
    """Tinte por fase de arco (23b-1, A.3): `{"arco.fase": latido}`. Mientras esa fase
    está activa, el paso espera ese latido en vez del suyo. Sin fase activa, el suyo."""

    @model_validator(mode="after")
    def _shape(self) -> Step:
        if (self.expects is None) == (not self.choices):
            raise ValueError(f"el paso {self.id!r} es de espera o de decisión, no de las dos")
        if self.expects is not None and self.within_days is None:
            raise ValueError(f"el paso de espera {self.id!r} necesita within_days")
        if self.expects is None and self.leanings:
            raise ValueError(f"solo un paso de espera lleva inclinaciones ({self.id!r})")
        if self.expects is None and self.tint:
            raise ValueError(f"solo un paso de espera lleva tinte ({self.id!r})")
        if self.choices and sum(1 for c in self.choices if c.default) > 1:
            raise ValueError(f"el paso {self.id!r} tiene más de una opción default")
        return self


class RefSpec(Spec):
    """Una referencia: a quién mira la trama, nombrada, y las condiciones que cumple
    desde el protagonista. Sus condiciones son del lado de referencia."""

    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z_]+$")
    when: tuple[PlotCondition, ...] = ()


class PlotSpec(Spec):
    """Una trama subjetiva (A.1). `protagonist` mira a quien la vive; `refs`, a quienes
    conoce; `when`, al mundo (situación, fase)."""

    id: PlotId
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=40)
    content: tuple[ContentTag, ...] = ()
    when: tuple[PlotCondition, ...] = ()
    protagonist: tuple[PlotCondition, ...] = ()
    refs: tuple[RefSpec, ...] = ()
    chance: float = Field(gt=0.0, le=1.0)
    cooldown_days: int = Field(default=0, ge=0)
    once: bool = False
    may_go_unused: bool = False
    """Que el panel de salud no avise si la trama no sale nunca: una trama que depende de
    algo raro (una muerte, un festival) puede no dispararse en una corrida."""
    steps: tuple[Step, ...] = Field(min_length=1)


class MarkSpec(Spec):
    """Una marca de persona: un entero ≥ 0 (A.1). `hidden` = no se ve en la hoja."""

    id: MarkId
    label: str = Field(min_length=1, max_length=80)
    hidden: bool = False
    max: int | None = Field(default=None, ge=1)


class FameOn(Spec):
    """Qué hechos del motor suben o bajan la fama, y cuánto (A.1)."""

    rank_up: float = 0.0
    goal_achieved: float = 0.0
    action: dict[ActionId, float] = Field(default_factory=dict)


class FameSpec(Spec):
    """La fama: un valor en [0, 1] por persona, que baja cada día (A.1)."""

    label: str = Field(min_length=1, max_length=80)
    decay_per_day: float = Field(ge=0.0, le=1.0)
    on: FameOn = Field(default_factory=FameOn)

    @model_validator(mode="before")
    @classmethod
    def _la_clave_on(cls, datos: object) -> object:
        """YAML 1.1 lee una clave `on` sin comillas como el booleano `True`. El pack la
        escribe como dice el contrato, sin comillas, y aquí se recoloca."""
        if isinstance(datos, dict) and True in datos and "on" not in datos:
            datos = {**{k: v for k, v in datos.items() if k is not True}, "on": datos[True]}
        return datos


class TestSpec(Spec):
    """Una prueba enfrentada del pack (A.4). El pack dice qué rasgos cuentan si no hay
    sistema de rol; el enlace del sistema dice con qué competencias se tira (D-159)."""

    label: str = Field(min_length=1, max_length=120)
    actor: TraitId
    against: TraitId | None = None


class PlotBook(Spec):
    """`tramas.yaml`, junto al pack (A.1). Marcas, fama, pruebas y las tramas."""

    marks: tuple[MarkSpec, ...] = ()
    fame: FameSpec | None = None
    tests: dict[TestId, TestSpec] = Field(default_factory=dict)
    plots: tuple[PlotSpec, ...] = ()
    strict_marks: bool = False
    """Con él, una marca consumida que nadie produce (o al revés) no carga: error, y no
    aviso."""



# -----------------------------------------------------------------------------
# Arcos del mundo (23b-1, D-179): fases que cambian el escenario, gente que llega,
# contadores que agregan lo que hace la gente y un reconocimiento al cerrar. Lo
# declara `arcos.yaml`, junto al pack, y lo valida `ContentPack` contra el resto.
# -----------------------------------------------------------------------------


class ArcScale(StrEnum):
    """Tamaño de un arco. Es una etiqueta para quien lo lee: el motor no cambia nada
    por ella. `era` se declara pero aún no carga: no hay grupos que la sostengan."""

    EVENT = "event"
    CRISIS = "crisis"
    ERA = "era"


class ArcSide(StrEnum):
    """Los dos bandos de un combate de arco. Un llegado es hostil mientras lleve la
    condición de la plantilla; cualquier otro es residente."""

    RESIDENTS = "residents"
    ARRIVALS = "arrivals"


class ArcResult(StrEnum):
    WON = "won"
    LOST = "lost"


class ArcPeople(Spec):
    """Un grupo de personas, para una condición relativa (23b-1-fix, A.1). Exactamente una
    forma: `condition` (quien lo llevó durante el arco), `zone` (quien estaba en la zona del
    arco al empezar la fase) o `all` (quien vive ahora)."""

    condition: SituationId | None = None
    zone: bool | None = None
    all: bool | None = None

    @model_validator(mode="after")
    def _one(self) -> ArcPeople:
        formas = [k for k in ("condition", "zone", "all") if getattr(self, k) is not None]
        if len(formas) != 1:
            raise ValueError(
                f"un grupo de personas lleva exactamente una forma, no {formas or 'ninguna'}"
            )
        if (self.zone is not None and self.zone is not True) or (
            self.all is not None and self.all is not True
        ):
            raise ValueError("`zone` y `all` solo valen como `true`")
        return self


class ArcRatio(Spec):
    """`total(counter) ≥ at_least · total(over)`, y/o `≤ at_most · total(over)`. Relativo: el
    umbral sigue a la población del pack, no a un número escrito a mano (23b-1-fix, A.1)."""

    counter: CounterId
    over: CounterId
    at_least: float | None = Field(default=None, gt=0.0)
    at_most: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _some(self) -> ArcRatio:
        if self.at_least is None and self.at_most is None:
            raise ValueError(f"ratio de {self.counter!r}: pide at_least, at_most o los dos")
        return self


class ArcPer(Spec):
    """`total(counter) ≥ at_least · n` (y/o `≤ at_most · n`), con `n` = personas del grupo.
    Con `n = 0` la condición es falsa: nadie a quien medir no cuenta como cumplido."""

    counter: CounterId
    people: ArcPeople
    at_least: float | None = Field(default=None, gt=0.0)
    at_most: float | None = Field(default=None, gt=0.0)

    @model_validator(mode="after")
    def _some(self) -> ArcPer:
        if self.at_least is None and self.at_most is None:
            raise ValueError(f"per de {self.counter!r}: pide at_least, at_most o los dos")
        return self


class CounterCond(Spec):
    """Una condición sobre contadores, en una de cuatro formas, exactamente una:

    - rango absoluto: `counter` con `min` o `max` (umbral escrito);
    - `mas_que`: `counter` por delante de otro contador;
    - `ratio`: relativa a otro contador (`total(a) ≥ x · total(b)`);
    - `per`: relativa a un grupo de personas (`total(a) ≥ x · n`).

    Las relativas existen porque un umbral escrito a mano deja de significar nada cuando la
    población cambia: un pack con 200 personas y uno con 50 no pueden decir «30 heridos»."""

    counter: CounterId | None = None
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)
    mas_que: CounterId | None = None
    ratio: ArcRatio | None = None
    per: ArcPer | None = None

    @model_validator(mode="after")
    def _shape(self) -> CounterCond:
        absoluta = self.counter is not None
        acota = self.min is not None or self.max is not None
        formas = []
        if absoluta and (acota or self.mas_que is not None):
            formas.append("absoluta")
        if self.ratio is not None:
            formas.append("ratio")
        if self.per is not None:
            formas.append("per")
        if len(formas) != 1 or (formas[0] == "absoluta" and (acota == (self.mas_que is not None))):
            raise ValueError(
                "una condición de contador es exactamente una forma: rango (counter + min/max), "
                "mas_que, ratio o per"
            )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"condición sobre {self.counter!r}: min es mayor que max")
        return self


class ArcFeed(Spec):
    """Qué hecho del log suma a un contador. Exactamente una de las formas.

    Cada aporte se atribuye a quien lo hizo: el ganador de un combate, quien mata, quien
    supera la prueba, quien ejecuta la acción. Por eso el reconocimiento puede nombrar
    a una persona y no solo contar."""

    combat: ArcSide | None = None
    """Un combate del arco que gana o pierde este bando. Con `result`."""
    result: ArcResult | None = None
    death: ArcSide | None = None
    """Muere alguien de este bando, y lo mata quien tiene autor en la condición."""
    trial: ArcResult | None = None
    """Una prueba de una trama sembrada por este arco, ganada o perdida."""
    action: ActionId | None = None
    """Una acción del pack hecha en un lugar del arco."""

    @model_validator(mode="after")
    def _one(self) -> ArcFeed:
        formas = [k for k in ("combat", "death", "trial", "action") if getattr(self, k) is not None]
        if len(formas) != 1:
            raise ValueError(f"un aporte lleva exactamente una forma, no {formas or 'ninguna'}")
        if self.combat is not None and self.result is None:
            raise ValueError("un aporte de combate necesita `result`: won o lost")
        if self.combat is None and self.result is not None:
            raise ValueError("`result` solo va con `combat`")
        return self


class ArcCounter(Spec):
    id: CounterId
    label: str = Field(min_length=1, max_length=80)
    """Solo para quien depura. Nada del arco llega al narrador: ni su nombre ni sus
    contadores (A.4)."""
    feeds: tuple[ArcFeed, ...] = Field(min_length=1)


class ArcTallySpec(Spec):
    """El efecto `arc_tally` de una trama: suma `n` al contador de un arco en curso."""

    counter: CounterId
    n: int = Field(default=1, ge=1)


class ArcDays(Spec):
    min: int = Field(ge=1)
    max: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> ArcDays:
        if self.min > self.max:
            raise ValueError(f"días entre {self.min} y {self.max}: rango al revés")
        return self


class ArrivalGroup(Spec):
    """Una tanda de llegados que entra al empezar la fase. `depart` dice si se va al
    acabar esa fase; si no, se va al cerrar el arco. Nadie queda al cerrar."""

    template: ArrivalId
    count: tuple[int, int]
    at: PlaceId
    depart: bool = False

    @model_validator(mode="after")
    def _count(self) -> ArrivalGroup:
        minimo, maximo = self.count
        if not 1 <= minimo <= maximo:
            raise ValueError(f"llegadas de {self.template!r}: cuenta {self.count} inválida")
        return self


class ArcBranch(Spec):
    """Una rama de salida de una fase. `if` sobre contadores; la rama sin `if` es la de
    por defecto y va la última."""

    if_: CounterCond | None = Field(default=None, alias="if")
    to: PhaseId

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ArcPhase(Spec):
    """Una fase: dura unos días o hasta que un contador lo dice. Al entrar activa sus
    situaciones y sus llegadas; al salir las retira y hace partir a quien debe."""

    id: PhaseId
    label: str = Field(min_length=1, max_length=80)
    days: ArcDays | None = None
    until: CounterCond | None = None
    situations: tuple[SituationId, ...] = ()
    """Situaciones eventuales del pack que la fase enciende (y apaga al salir). Las
    periódicas no: van por su calendario y el arco solo las observa."""
    places: tuple[PlaceId, ...] = ()
    """Dónde se presencia la fase. Vacío = los lugares de sus situaciones."""
    arrivals: tuple[ArrivalGroup, ...] = ()
    seeds: tuple[PlotId, ...] = ()
    """Tramas que solo pueden empezar en esta fase. La trama lo declara en su `when`."""
    next: tuple[ArcBranch, ...] = ()

    @model_validator(mode="after")
    def _shape(self) -> ArcPhase:
        if (self.days is None) == (self.until is None):
            raise ValueError(f"fase {self.id!r}: lleva exactamente uno de days o until")
        if self.next:
            *condicionadas, por_defecto = self.next
            if por_defecto.if_ is not None:
                raise ValueError(
                    f"fase {self.id!r}: la última rama tiene que ser la de por defecto"
                )
            if any(r.if_ is None for r in condicionadas):
                raise ValueError(f"fase {self.id!r}: solo la última rama va sin `if`")
        return self


class ArcCalendar(Spec):
    """El arco empieza cada `every_days` días, desde `start_day` (días del reloj)."""

    every_days: int = Field(ge=1)
    start_day: int = Field(default=0, ge=0)


class ArcRecent(Spec):
    """Al menos `n` hechos del tipo `event` en los últimos `days` días."""

    event: str
    """Un `EventKind` por su valor. Lo valida el pack."""
    n: int = Field(default=1, ge=1)
    days: int = Field(ge=1)


class ArcEnded(Spec):
    """Un arco terminado en la rama `branch`: la condición que leen otros arcos."""

    arc: ArcId
    branch: PhaseId


class ArcCondition(Spec):
    """Una condición del mundo para que un arco pueda empezar. Exactamente una."""

    situation: SituationId | None = None
    clock_phase: PhaseId | None = None
    recent: ArcRecent | None = None
    ended: ArcEnded | None = None

    @model_validator(mode="after")
    def _one(self) -> ArcCondition:
        usadas = [k for k in ("situation", "clock_phase", "recent", "ended")
                  if getattr(self, k) is not None]
        if len(usadas) != 1:
            raise ValueError(
                f"una condición de arco lleva exactamente una, no {usadas or 'ninguna'}"
            )
        return self


class ArcTrigger(Spec):
    """Un modo de empezar. Un arco tiene uno o varios; basta que uno se cumpla."""

    calendar: ArcCalendar | None = None
    conditions: tuple[ArcCondition, ...] = ()
    """Todas tienen que cumplirse. Con `chance`, la probabilidad diaria de empezar."""
    chance: float = Field(default=1.0, gt=0.0, le=1.0)
    expected_per_year: float = Field(default=0.0, ge=0.0)
    """Veces por año, como `TriggerSpec`. Lo que el director no gobierna: para ritmo del
    mundo, `director` (23b-2)."""
    director: DirectorTrigger | None = None
    """Lo empieza el director de ritmo (23b-2), entre los arcos así marcados que cumplen sus
    condiciones. Con él, `conditions` es opcional: sirven de filtro, no de disparo."""
    cooldown_days: int = Field(default=0, ge=0)
    """Días desde que el arco terminó hasta que puede volver a empezar por este modo.
    Obligatorio sin calendario ni director: es el freno que impide que un arco vuelva al día
    siguiente. Con director, lo frena el propio director (`min_gap_days`)."""

    @model_validator(mode="after")
    def _one_mode(self) -> ArcTrigger:
        # Con director, `conditions` es un filtro; sin él, son el disparo y no pueden faltar.
        modos = [
            self.calendar is not None,
            self.director is not None,
            self.expected_per_year > 0.0,
            bool(self.conditions) and self.director is None,
        ]
        if sum(modos) != 1:
            raise ValueError(
                "un disparador lleva exactamente uno de calendar, director, expected_per_year "
                "o conditions"
            )
        if self.calendar is None and self.director is None and self.cooldown_days < 1:
            raise ValueError(
                "un disparador sin calendario ni director necesita cooldown_days: sin freno, el "
                "arco volvería al día siguiente"
            )
        return self


class DirectorTrigger(Spec):
    """El modo `director` de un arco (23b-2, A.1): el peso con que el director lo elige entre
    los que cumplen. Un peso mayor sale más a menudo; el sorteo es por clave, no por orden."""

    weight: float = Field(gt=0.0)


class ArcResidue(Spec):
    """Lo que deja una rama final. Se aplica a quienes aportaron, salvo las situaciones,
    que son del mundo."""

    marks: dict[MarkId, int] = Field(default_factory=dict)
    fame: float = Field(default=0.0, ge=0.0, le=1.0)
    situations: dict[SituationId, int] = Field(default_factory=dict)
    """Situaciones eventuales que quedan encendidas `días` días tras el cierre."""

    @model_validator(mode="after")
    def _days(self) -> ArcResidue:
        if any(dias < 1 for dias in self.situations.values()):
            raise ValueError("una situación residual dura al menos 1 día")
        return self


class ArcRecognition(Spec):
    """A quien más aportó a estos contadores, al cerrar el arco: una marca y fama."""

    counters: tuple[CounterId, ...] = Field(min_length=1)
    mark: MarkId
    fame: float = Field(default=0.0, ge=0.0, le=1.0)
    top: Literal[1] = 1


class ArcSpec(Spec):
    """Un arco del mundo (23b-1). Fases, llegadas, contadores, ramas, residuos y
    reconocimiento. El motor no sabe qué es un festival: sabe fases, días y contadores."""

    id: ArcId
    label: str = Field(min_length=1, max_length=80)
    scale: ArcScale
    content: tuple[ContentTag, ...] = ()
    trigger: tuple[ArcTrigger, ...] = Field(min_length=1)
    phases: tuple[ArcPhase, ...] = Field(min_length=1)
    counters: tuple[ArcCounter, ...] = ()
    residues: dict[PhaseId, ArcResidue] = Field(default_factory=dict)
    """Por rama final: la fase en la que termina el arco."""
    recognition: ArcRecognition | None = None


class ArrivalTemplate(Spec):
    """Cómo es alguien que llega desde fuera por un arco (23b-1). El id de cada llegado
    se deriva por clave (arco, fase, índice, semilla), nunca de un contador."""

    id: ArrivalId
    label: str = Field(min_length=1, max_length=120)
    """Con `{nombre}`: el nombre sale de `nombres` por sorteo con clave."""
    nombres: tuple[str, ...] = Field(min_length=1)
    traits: dict[TraitId, tuple[float, float]] = Field(default_factory=dict)
    """Rasgo -> rango [mínimo, máximo] en -1..1, del que se sortea cada llegado."""
    home: PlaceId
    condition: SituationId
    """La condición personal con la que llega (`hostil`)."""

    @model_validator(mode="after")
    def _shape(self) -> ArrivalTemplate:
        if "{nombre}" not in self.label:
            raise ValueError(f"plantilla {self.id!r}: el label necesita {{nombre}}")
        for rasgo, (minimo, maximo) in self.traits.items():
            if not -1.0 <= minimo <= maximo <= 1.0:
                raise ValueError(f"plantilla {self.id!r}: rango de {rasgo!r} inválido")
        return self


class ArcBook(Spec):
    """`arcos.yaml`, junto al pack (23b-1). Arcos y las plantillas de sus llegados."""

    arcs: tuple[ArcSpec, ...] = ()
    templates: tuple[ArrivalTemplate, ...] = ()


class DirectorProfile(Spec):
    """Un perfil de ritmo (23b-2, A.1). Los números son del pack: el motor no decide cuánto
    es «mucho»; solo sabe gastar un presupuesto y medir un ritmo."""

    min_gap_days: int = Field(ge=1)
    """Días que tienen que pasar desde el último arco (de cualquier modo) para que el director
    empiece otro."""
    budget_per_day: float = Field(gt=0.0)
    """Intensidad que se recarga cada día. Cada arco que empieza gasta su `cost`."""
    cost: dict[ArcScale, float]
    """Lo que cuesta empezar un arco de cada escala. Una crisis cuesta más que un evento."""
    calm_events: float = Field(ge=0.0)
    """Hechos de ritmo por día (muertes, combates, rupturas, enfrentamientos) que se consideran
    calma. Por encima de esto, el mundo está revuelto y el director no echa más leña."""

    @model_validator(mode="after")
    def _costs(self) -> DirectorProfile:
        if set(self.cost) != set(ArcScale):
            raise ValueError(
                f"cost lleva una cifra por escala: {sorted(a.value for a in ArcScale)}"
            )
        if any(v < 0.0 for v in self.cost.values()):
            raise ValueError("un coste no puede ser negativo")
        return self


class CronicaSpec(Spec):
    """Qué entra en la crónica del mundo (23b-2, A.2). Los umbrales son del pack; el motor
    fija solo el vocabulario de qué puede entrar."""

    muerte_fama_min: float = Field(default=0.3, ge=0.0, le=1.0)
    """Una muerte entra si la víctima tenía al menos esta fama."""
    muerte_deudos_min: int = Field(default=3, ge=1)
    """…o si la lloraron al menos tantos: quien le apreciaba y sobrevivió."""
    nacimiento_prestigio_min: float = Field(default=0.5, ge=0.0, le=1.0)
    """Un nacimiento entra si la casa del recién nacido tiene al menos este prestigio."""
    ascenso_rango_min: int = Field(default=5, ge=1)
    """Un ascenso entra si el rango alcanzado es al menos este."""
    relaciones: tuple[RelationId, ...] = ()
    """Qué relaciones cuentan como parejas (al empezar) y rupturas (al acabar)."""
    relacion_aprecio_min: float = Field(default=0.5, ge=-1.0, le=1.0)
    """Una pareja o una ruptura entra solo si quien la lleva aprecia de verdad a la otra
    persona (aprecio al día de hoy). Sin esto, el mundo hace cien parejas en dos meses y la
    crónica deja de decir cuáles importan."""


class DirectorSpec(Spec):
    """`director` del pack (23b-2, A.1). Sin él, no hay director ni crónica, y el mundo sigue
    como antes: los packs sin este bloque tienen log idéntico."""

    profile: str = "equilibrado"
    """El perfil que corre en este pack. Por defecto, el equilibrado."""
    profiles: dict[str, DirectorProfile]
    cronica: CronicaSpec = Field(default_factory=CronicaSpec)

    @model_validator(mode="after")
    def _profile_exists(self) -> DirectorSpec:
        if self.profile not in self.profiles:
            raise ValueError(f"el perfil {self.profile!r} no está declarado en profiles")
        return self
