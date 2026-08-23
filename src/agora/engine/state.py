"""Estado mutable de una partida.

`ontology.py` define cómo ES el mundo (inmutable, viene del pack).
Este archivo define cómo ESTÁ el mundo ahora mismo (mutable, cambia por tick).

Regla que explica casi todas las decisiones de aquí: **pydantic en las
fronteras, dataclass en el interior**. Pydantic valida en cada construcción, y
esto se toca 672 veces por semana simulada por cada agente. Es el mismo
criterio que en C# separa un DTO validado en el borde de un struct interno que
ya nadie vuelve a comprobar.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from agora.engine.disposition import (
    Temperament,
    compose_caps,
    compose_costs,
    compose_gains,
    compose_memory_fade,
    compose_need_weights,
    compose_phase_shift,
    compose_tastes,
    compose_temperament,
    compute_strain,
)
from agora.engine.memory import MemoriaEpisodica
from agora.engine.ontology import (
    ActionId,
    AgentId,
    AgentSpec,
    GoalId,
    GoalSpec,
    GoalStatus,
    NeedId,
    NeedSpec,
    PlaceId,
    PlaceSpec,
    RelationId,
    SituationId,
    TargetSpec,
    TraitId,
)
from agora.engine.outcome import company_saturation
from agora.engine.pack import ContentPack
from agora.engine.rng import RngSource
from agora.engine.topology import TravelMap

# -----------------------------------------------------------------------------
# Qué está haciendo un agente: unión, no un flag.
#
# Estos dos SÍ son pydantic y SÍ son frozen. Son pequeños, se crean pocas veces
# (una por decisión, no una por tick) y ser inmutables elimina de raíz los bugs
# de aliasing: dos referencias al mismo objeto `Busy` decrementándolo dos veces.
# En un motor determinista ese bug es de los más caros de encontrar, porque no
# rompe nada — solo hace que el tiempo pase distinto para un agente.
# -----------------------------------------------------------------------------


class PerformingAction(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: ActionId
    ticks_remaining: int = Field(ge=0)

    target: AgentId | None = None
    """A quién se lo está haciendo. `None` en todo lo que no apunta a nadie.

    Se guarda al empezar y no se vuelve a elegir al terminar, y es deliberado:
    reelegir convertiría *vendar a mi hermano* en *vendar a quien quede*, y una
    acción que empieza dirigida a alguien tiene que acabar dirigida a esa persona
    o no acabar. Si se ha ido o se ha muerto, no le llega nada.
    """

    total_ticks: int = Field(default=0, ge=0)
    """Cuánto se planificó al empezar. Con las acciones elásticas ya no se puede
    leer del spec: la duración salió del déficit de este agente en este sitio.

    De aquí salen dos cosas que antes venían del pack: el progreso invertido (ver
    `commitment`) y cuánto se ha repuesto de verdad al terminar o al soltarlo."""


class Traveling(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: PlaceId
    """A dónde quiere llegar al final."""

    intent: ActionId
    """Qué piensa hacer al llegar.

    Consecuencia directa de deliberar sobre el mundo entero: si el agente
    elige "comer en la posada", el viaje no es la decisión, es la consecuencia
    de una decisión que hay que recordar.

    Sin este campo, un agente con hambre crítica que ya va camino de la comida
    abortaría el viaje en cada tick — porque "viajar" no satisface nada y la
    comprobación de urgencia no tendría forma de saber que ya está resolviendo
    el problema.
    """

    next_hop: PlaceId
    """El tramo actual. Un viaje largo son varios `Traveling` encadenados.

    Guardar el tramo y no la ruta entera es deliberado: al llegar a cada nodo se
    vuelve a preguntar `TravelMap.first_hop`, así que un cambio en el mundo (un
    camino cortado, un lugar cerrado de noche) se absorbe solo sin invalidar
    viajes en curso.
    """

    ticks_remaining: int = Field(ge=0)

    total_ticks: int = Field(default=0, ge=0)
    """Duración estimada del trayecto ENTERO al decidirlo, no del tramo.

    Se conserva de tramo en tramo para poder saber cuánto se lleva andado. Sin
    esto, el progreso solo se sabría dentro del tramo actual, y como los tramos
    son de uno o dos ticks, un agente que lleva cuatro ticks caminando parecería
    recién salido de casa cada vez que pisa un cruce.
    """


type Busy = PerformingAction | Traveling
"""Unión discriminada. Consúmela siempre con `match` + `assert_never`:

    match busy:
        case PerformingAction(): ...
        case Traveling():        ...
        case _:                  assert_never(busy)

Cuando en F1 añadas un tercer caso (huir, por ejemplo), mypy señalará cada sitio
que falta actualizar. En C# eso lo confiarías a un `default:` que revienta en
runtime; aquí falla antes de ejecutar.
"""


# -----------------------------------------------------------------------------
# Vínculos: lo que un agente sabe de otro
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class Condicion:
    """Algo que alguien lleva encima. Una herida, una infección, un veneno.

    No es una primitiva nueva: es una `SituationSpec` marcada como `personal`,
    pegada a una persona en vez de a un lugar. Lo que vive aquí es solo lo que
    distingue **esta** de otra igual.
    """

    situacion: SituationId

    marca: str = ""
    """Cuál de ellas. Discriminador **opaco**: el motor compara cadenas y nunca
    las interpreta.

    Existe porque tres heridas —brazo, pierna, torso— drenan por separado y no
    forman una herida mayor, mientras que dos en el mismo sitio sí empeoran. Sin
    marca, o todo se apila o todo se funde, y las dos son falsas.

    Y es opaco porque tiene que serlo: el motor no puede saber qué es un brazo.
    Un pack de naves diría `motor` y `casco`; uno de política, `reputación` y
    `salud`. La cadena vacía vale para lo que no tiene partes — una borrachera es
    una borrachera.
    """

    gravedad: float = 1.0
    """Cuán grave es **esta**. Multiplica los efectos, y baja al tratarla.

    Sustituye a un `veces: int` que solo contaba repeticiones, y eso dejaba fuera
    la mitad del problema: **con un contador solo se puede tener más de lo mismo,
    nunca algo peor**. Un corte en el costado y un desmembramiento eran la misma
    herida repetida, y una fiebre leve y una que te mata, la misma fiebre.

    Con un número:

    - **Un brote reparte fiebres distintas.** El evento sortea la gravedad en un
      rango, así que a uno le toca un 0.4 y a otro un 2.5, y son la misma
      enfermedad vivida de dos maneras.
    - **Dos idénticas siguen agravando**, que era la regla de siempre: ahora
      suman gravedad en vez de contar veces. Mismo comportamiento, mejor dicho.
    - **Y curar deja de ser todo o nada.** `cures` resta gravedad; al llegar a
      cero la condición se va sola. De ahí sale que una noche de sueño rebaje
      una fiebre y no haga nada por una pierna rota — sin escribir esa regla en
      ningún sitio.
    """

    hasta: int | None = None
    """Tick en que se pasa sola. `None` = hasta que alguien la quite.

    Las dos formas hacen falta. Un veneno se pasa; una infección no se pasa sola
    y por eso da miedo.
    """

    donde: PlaceId | None = None
    """**Dónde te la hicieron.** No dónde estás ahora.

    Existe por el único mecanismo del motor que llevaba dos campañas sin poder
    funcionar. `miedo()` pide un recuerdo con lugar y con culpable, y una herida
    ya da las dos cosas — pero el recuerdo se graba cuando la necesidad cruza su
    umbral, y un herido sangra durante días: cruza el umbral **en su posada**, o
    en el templo, o de camino. Sin este campo, la lección aprendida sería temer
    la propia cama.

    Es exactamente la contaminación que dejó el miedo parado la primera vez —
    entonces por los chascos sociales, que también ocurren donde uno pasa el
    tiempo— y por eso el arreglo tiene que ser este y no calibrar nada: **el
    lugar de un daño es donde lo causaron, no donde se nota**.

    `None` para lo que no tiene sitio: una maldición heredada, una enfermedad
    congénita, algo que se puso por API sin escena.
    """


@dataclass(slots=True)
class Bond:
    """Lo que un agente siente y recuerda de otro. Asimétrico a propósito.

    Cada uno guarda el suyo, y no tienen por qué coincidir. Que A aprecie a B
    más de lo que B aprecia a A es lo normal, no un caso raro, y un vínculo
    compartido lo haría imposible de expresar.

    Tres campos y ninguno de ellos es nuevo en el motor: un contador que crece
    con el trato (como `saturation`), un valor aprendido por error de predicción
    (como `gain_beliefs`) y una marca de tiempo que caduca (como `sightings`).
    La capa relacional es recombinación de lo que ya había.
    """

    regard: float = 0.0
    """Aprecio en [-1, 1]. 0 es un desconocido, y también alguien que te da
    exactamente igual: la diferencia entre ambos la marca `encounters`."""

    encounters: int = 0
    """Cuántas veces se han **cruzado**. Co-presencia, nada más.

    Está porque responde lo único que `regard` no puede: si os conocéis. Un
    aprecio de 0.0 es a la vez el desconocido y el vecino que te resulta
    indiferente, y el narrador de F5 no puede tratarlos igual.
    """

    shared: int = 0
    """Cuántas veces han **compartido algo**. Ni una sola por cruzarse.

    Cruzarse y convivir son cosas distintas, y con un solo contador no se pueden
    separar: dos que se ven cien veces sin dirigirse la palabra se distinguen —
    saben que el otro existe— y no hay nada más entre ellos; dos que se ven veinte
    y comparten diez tienen algo. Sin este campo, la única diferencia visible
    entre esos dos pares era el aprecio, que mezcla **cuánto** valió con
    **cuántas veces** ocurrió.

    Lo destapó una corrida larga: doscientos agentes, año y medio, y cada uno
    acababa con ciento noventa y nueve vínculos de aprecio +0.03. El motor estaba
    haciendo lo correcto —reconocer sin apreciar— y no había forma de leerlo.

    Solo lo toca `remember_company`, que se dispara al TERMINAR una acción que el
    pack declara compartida. `meet` no lo toca jamás.
    """

    last_seen: int = 0
    """Tick del último encuentro. De aquí salen el desdibujado y el olvido."""

    def regard_at(self, tick: int, fade: float) -> float:
        """El aprecio de HOY, desdibujado por el tiempo sin verse.

        Se calcula al leer y no se guarda actualizado. Un bucle por tick sobre
        cada vínculo de cada agente es exactamente el coste que hunde el sistema
        cuando el mundo crece; esto vale lo mismo y no cuesta nada.
        """
        if fade >= 1.0:
            return self.regard
        return self.regard * fade ** max(0, tick - self.last_seen)


@dataclass(slots=True)
class Ledger:
    """Cuánto se ofrece y cuánto se pide de cada eje. Solo para calibrar.

    Existe porque `crisis_time` es un agregado y **un eje que nunca aprieta se
    esconde detrás de los que sí**. El panel se ve sano mientras media docena de
    mecanismos están muertos, y eso ya pasó: el vínculo de la ciudad no llegó a
    ser urgente ni una vez en 256 000 muestras y nada lo decía.

    Se anota lo NOMINAL, no lo que cabe. Una reposición que se pierde contra el
    techo cuenta igual, porque la pregunta es cuánto hay en oferta — y el
    excedente es justamente la señal de que el eje está resuelto.

    Apagado por omisión (`ledger is None`): una corrida normal no paga por esto.
    """

    demanda: dict[NeedId, float] = field(default_factory=dict)
    """Lo que se pierde: decaimiento bruto más lo que cuestan las acciones."""

    pasivo: dict[NeedId, float] = field(default_factory=dict)
    """Lo que llega sin hacer nada, por `company_relief`. Puede ser negativo con
    mala compañía."""

    activo: dict[NeedId, float] = field(default_factory=dict)
    """Lo que llega por actuar. Es lo único que una decisión puede mover."""

    incondicional: dict[NeedId, float] = field(default_factory=dict)
    """La parte del `activo` que llega **sin cumplir la condición que el pack
    dice que importa**: efectos base sobre un eje social, en una acción que no
    exige ni compañía ni relación.

    Es el subconjunto que hace inerte a un eje sin que nada falle. Medido en la
    ciudad: siete de las diez acciones que dan vínculo lo daban a solas —beber
    solo curaba la soledad— y entre eso y el alivio pasivo, `charlar` era
    decorado. Que sea un contador aparte y no una resta es lo que permite
    verificar un recorte en vez de suponerlo.
    """

    def anotar(self, libro: dict[NeedId, float], need: NeedId, cuanto: float) -> None:
        libro[need] = libro.get(need, 0.0) + cuanto


# -----------------------------------------------------------------------------
# Estado de un agente
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class AgentState:
    """Dónde está, cómo está y qué está haciendo un agente.

    `slots=True` se acerca a un `struct` de C#: sin `__dict__`, menos memoria y
    acceso a atributos más rápido. A cambio no puedes añadir atributos al vuelo,
    que es justo lo que quieres en el estado caliente.
    """

    spec_id: AgentId
    """Solo el id, no el `AgentSpec` entero.

    Mantiene el estado serializable. En F4 vas a querer partidas guardadas, y un
    estado que arrastra specs se convierte en un problema de identidad al
    recargar: dos copias del mismo spec que ya no son el mismo objeto.
    """

    at: PlaceId
    needs: dict[NeedId, float]

    # --- disposición: quién es este agente AHORA -----------------------------
    #
    # Vive aquí y no en el spec porque tiene que poder cambiar. Un NPC que no
    # es distinto después de un año de vivir no tiene arco, tiene una ficha.
    # El spec pasa a ser las condiciones iniciales.

    traits: dict[TraitId, float] = field(default_factory=dict)
    """Rasgo -> intensidad actual en [-1, 1]. Se mueve con `drift_trait`."""

    tastes: dict[str, float] = field(default_factory=dict)
    """Objetivo -> multiplicador. Ya compuesto: dos gustos hacia lo mismo se
    multiplicaron al construirlo. Se puede mutar directamente, no tiene nada
    derivado que mantener en sincronía."""

    need_weights: dict[NeedId, float] = field(default_factory=dict)
    """DERIVADO de `traits`. Se recompone en `drift_trait`, que es la única
    puerta para moverlos precisamente por eso.

    Está aquí y no se recalcula en cada deliberación porque los rasgos cambian
    muy rara vez y se consultan miles de veces."""

    phase_shift: int = 0
    """DERIVADO de `traits`: cuánto va adelantado el reloj interno, en ticks.

    Vive junto a `need_weights` y se recompone con él, por lo mismo: cambia una
    vez cada muchos días y se consulta en cada deliberación. 0 si el pack no
    declara franjas, y entonces todo lo horario queda inerte."""

    aptitud_base: dict[NeedId, float] = field(default_factory=dict)
    """La aptitud que sale SOLO de los rasgos, antes de los ánimos.

    Existe para no recomponerla cada tick. `gains` cambia con lo que uno lleva
    encima —una fiebre hace que todo cunda menos— y eso va y viene con el
    reloj, pero los rasgos no: guardando la parte estable, el tick solo tiene
    que multiplicar por los ánimos de quien tenga alguno, que son treinta de
    doscientos.

    DERIVADO como todo lo demás: no se guarda, se recompone al cargar.
    """

    gains: dict[NeedId, float] = field(default_factory=dict)
    """DERIVADO de `traits` **y de lo que lleva encima**: la APTITUD hoy.

    Distinto del peso, y conviene no confundirlos: `need_weights` dice cuánto le
    IMPORTA algo, esto dice cuánto le CUNDE. Quien le da mucha importancia al
    descanso y lo recupera despacio es una persona concreta, no una
    contradicción — y quien tiene mano para el arcano sin que le interese,
    también."""

    caps: dict[NeedId, float] = field(default_factory=dict)
    """DERIVADO de `traits` y del `cap` del pack: EL TECHO de esta persona.

    Hasta dónde puede llegar en cada eje. Lo ausente vale 1.0, así que un pack
    que no declare techos se comporta exactamente como antes.

    Es el único límite del motor que es **de la persona y no del mundo**, y por
    eso vive aquí y no en la necesidad. Que dos agentes con la misma ficha salvo
    un rasgo tengan techos distintos en el mismo eje es justo lo que el sistema
    de afinidades pedía y ninguna otra perilla podía decir.
    """

    costs: dict[NeedId, float] = field(default_factory=dict)
    """DERIVADO de `traits`: el TEMPLE de esta persona en cada eje.

    El otro lado del intercambio: `gains` dice cuánto le cunde lo que gana, esto
    cuánto le duele lo que gasta. Con los dos se puede escribir al enano que
    almacena mucho y repone despacio, que con un solo canal era inexpresable.

    Lo ausente vale 1.0, como en `gains`, así que un pack que no declare
    `cost_multipliers` en ningún rasgo se comporta exactamente como antes."""

    goals: dict[GoalId, GoalStatus] = field(default_factory=dict)
    """En qué anda cada meta de esta persona. Se siembra desde el spec.

    Solo el estado, no la meta: qué quiere lo dice el pack y no cambia; lo que
    cambia es si lo ha conseguido, lo ha perdido o sigue en ello. Misma
    separación spec/state que en todo lo demás.
    """

    debt: dict[NeedId, float] = field(default_factory=dict)
    """Lo que el suelo se comió, por necesidad. Siempre >= 0.

    Es la memoria de haber estado peor que vacío. Sin esto, quien pelea tres días
    y quien durmió mal una noche están los dos en 0.0 y son indistinguibles: el
    recorte del suelo tira la información.

    **Reponer paga esto primero.** Por eso una deuda de 1.00 convierte una noche
    de ocho horas en quince, y por eso a quien lo despiertan pronto se levanta con
    la deuda saldada y la necesidad todavía por los suelos.

    Solo existe para las necesidades que declaran `max_debt`; las demás nunca
    entran aquí y el diccionario se queda vacío."""

    condiciones: list[Condicion] = field(default_factory=list)
    """Lo que lleva encima ahora mismo. Ordenada por (situación, marca).

    Una `list` y no un `dict` porque la clave es un par y el orden tiene que ser
    estable sin depender del hash: los efectos se aplican en secuencia y la
    multiplicación de floats no es asociativa. Es la tercera vez que ese par
    —hash y coma flotante— decide una estructura de datos en este motor.
    """

    rango: dict[NeedId, int] = field(default_factory=dict)
    """En qué rango va de cada eje que los tenga. Empieza en 0 y **no tiene
    tope**.

    El valor de la necesidad dice *cuánto lleva de este rango*; esto dice
    **cuántos ha roto**. Separarlos es lo que permite que no haya techo: el eje
    se recorre entero una y otra vez, y cada vuelta cuesta más que la anterior.

    Es el número que se lee para saber quién es alguien. «Dominio 0.4» no dice
    nada por sí solo; «rango 7, y va por el 0.4 del octavo» sí.

    Disperso: solo aparecen los ejes que declaran `rank_slowdown`.
    """

    agonia: dict[NeedId, int] = field(default_factory=dict)
    """Ticks SEGUIDOS a cero, por necesidad. El reloj de lo que está matando.

    Hermano de `debt` sobre el otro eje, y por eso vive al lado: la deuda dice
    **cuán hundido** estás y esto **cuánto llevas**. Son independientes —se puede
    tocar fondo un instante o vivir raspando el suelo un mes— y solo la segunda
    mata.

    Se reinicia en cuanto la necesidad levanta del cero. Comer no salda el hambre
    de tres días como quien paga una deuda: la quita del todo. Es la diferencia
    entre esto y `debt`, que sí se paga a plazos.

    Disperso como la deuda: solo aparecen las que el pack declara `lethal_after`,
    así que un mundo donde no se muere nadie no paga ni un byte por esto."""

    strain: float = 0.0
    """Desgaste cognitivo en [0, 1]. DERIVADO de las necesidades, se recalcula
    cada tick. 0 entero, 1 al límite.

    No es una emoción: es lo que hace que el mismo agente decida peor cuando
    está mal. Se guarda además de usarse porque en F2 va a ser una de las
    primeras cosas que el narrador necesite saber."""

    # Los mismos valores que trae `TuningSpec` por defecto, y no es casualidad:
    # este temperamento provisional dura hasta el primer `recompose`, y si no
    # coincidiera con el mundo neutro habría un tick en que todos deciden como
    # nadie. Nombrados y no posicionales: son diez, y la próxima vez que crezcan
    # la lista tiene que fallar por nombre, no colarse por orden.
    temperament: Temperament = field(
        default_factory=lambda: Temperament(
            temperature=0.15,
            loss_aversion=1.0,
            critical_need_threshold=0.15,
            travel_discount=0.95,
            companionship_weight=0.0,
            novelty_weight=0.6,
            switch_cost=0.0,
            learning_rate=0.0,
            bond_rate=0.0,
            bond_fade=1.0,
        )
    )
    """DERIVADO de `traits`, del `tuning` del pack y del `strain` actual. Cómo
    decide esta persona hoy: su impulsividad, su aversión al precio, su aguante
    y su arraigo.

    Como depende del estado, se recompone **cada tick** y no solo al derivar un
    rasgo. Cuesta una decena de potencias por agente; a cambio hay una sola
    fuente de verdad y nunca queda desfasado.

    El default solo existe para que construir un `AgentState` suelto en un test
    no reviente; cualquier agente de una partida real pasa por `from_spec`."""

    gain_beliefs: dict[ActionId, dict[NeedId, float]] = field(default_factory=dict)
    """Cuánto se fía este agente de lo que cada acción PROMETE dar.

    Multiplicador sobre `satisfies`, por acción y necesidad. Empieza vacío —lo
    ausente vale 1.0, o sea "me creo el pack"— y deriva con la experiencia.

    Es lo que convierte a un NPC en una mente separada en vez de en una consulta
    al estado global: dos agentes con la misma ficha pueden tener expectativas
    distintas sobre lo mismo porque han vivido cosas distintas. Y pueden estar
    equivocados, que es la parte interesante.
    """

    cost_beliefs: dict[ActionId, dict[NeedId, float]] = field(default_factory=dict)
    """Lo mismo, sobre lo que cada acción CUESTA.

    Almacén aparte del anterior porque una necesidad puede aparecer a los dos
    lados de la misma acción, y con un solo diccionario las dos creencias se
    pisarían.

    Aprender el precio importa tanto como aprender el premio: un agente que
    descubre que salir de fiesta le sale más caro de lo que creía deja de
    salir, y nadie tuvo que escribirle esa lección.
    """

    bonds: dict[AgentId, Bond] = field(default_factory=dict)
    """A quién conoce y qué siente por cada cual.

    Lo ausente es un desconocido, y se trata como aprecio 0: neutro, ni atrae ni
    repele. El diccionario solo tiene entrada para quien se ha cruzado de verdad,
    y `forget_bonds` la borra pasado el horizonte. Así el tamaño es "la gente de
    tu vida últimamente" y no "todo el que has visto nunca", que es lo que
    permite que esto escale a un mundo poblado.
    """

    relations: dict[RelationId, set[AgentId]] = field(default_factory=dict)
    """De quién es qué. Al lado de `bonds` y a propósito NO dentro.

    Un vínculo es lo que sientes; una relación es lo que ERES de alguien. El
    primero es emergente, gradual y **se olvida**; la segunda es un hecho y no
    se olvida jamás — `forget_bonds` respeta a los tuyos aunque lleves un año
    sin verlos, que es la mitad de lo que hace que esto sea otra cosa.
    """

    sightings: dict[PlaceId, tuple[int, frozenset[AgentId]]] = field(default_factory=dict)
    """Lo último que este agente vio en cada sitio: `(tick, quiénes)`.

    Solo lo que ha visto con sus ojos, estando allí. Es lo que sustituye a la
    omnisciencia: sin esto, cada agente conoce en tiempo real la ocupación de
    los veintiún lugares del barrio.

    Guarda **nombres y no un recuento**, y ese cambio es lo que hace posible la
    capa relacional. Con un número, un agente solo puede querer ir donde hay
    gente; con nombres puede querer ir donde está Mira. Es la diferencia entre
    un mundo poblado y un mundo habitado.

    Un avistamiento caduca (`sighting_horizon`), y lo caducado se supone **a
    favor**. Así el agente va a mirar y se lleva el chasco; suponer vacío haría
    que nadie fuera nunca a un sitio del que no tuviera noticia fresca.
    """

    saturation: dict[ActionId, float] = field(default_factory=dict)
    """Hastío por acción, en [0, 1]. Sube al COMPLETAR, se disipa cada tick.

    Al completar y no al empezar: uno se cansa de lo que hizo, no de lo que
    intentó. Un agente que empieza y abandona no debería aburrirse de algo que
    nunca llegó a hacer.

    Las acciones sin `saturation_gain` nunca entran en este diccionario, así
    que no ocupan nada.
    """

    busy: Busy | None = None
    """`None` = ocioso. Este agente delibera en el tick actual."""

    ledger: Ledger | None = None
    """Contabilidad de oferta y demanda por eje. `None` = apagada, y esa es la
    normal: una corrida de juego no paga por instrumentarse. La enciende
    `health` para poder responder si un eje decide algo o es decorado."""

    @classmethod
    def from_spec(cls, pack: ContentPack, spec: AgentSpec) -> AgentState:
        """Estado inicial de un agente a partir de sus condiciones de partida.

        Los diccionarios se **copian**. `AgentSpec` es `frozen`, pero eso solo
        impide reasignar sus atributos: el dict de dentro sigue siendo mutable,
        y compartirlo haría que la deriva de un agente contaminara el pack —y
        con él, a cualquier otro mundo cargado desde el mismo fichero.
        """
        # Todas las necesidades del pack, aunque el agente no las mencione. Un
        # dict incompleto obliga a cada consumidor a inventarse un default, y
        # acabarían siendo distintos en dos sitios.
        needs: dict[NeedId, float] = {need.id: need.initial for need in pack.needs}
        needs.update(spec.initial_needs)

        strain = compute_strain(pack, needs)
        return cls(
            spec_id=spec.id,
            at=spec.start_at,
            needs=needs,
            traits=dict(spec.traits),
            tastes=compose_tastes(spec.tastes),
            # Lo que depende de otra nace BLOQUEADO: no empuja ni un peso hasta
            # que la que la abre se logre. Es lo que hace que un arco se recorra
            # en orden en vez de ser cuatro deseos simultáneos.
            goals={
                goal.id: (
                    GoalStatus.LOCKED
                    if goal.requires_goal is not None
                    else GoalStatus.ACTIVE
                )
                for goal in spec.goals
            },
            need_weights=compose_need_weights(pack, spec.traits, spec.goals),
            phase_shift=compose_phase_shift(pack, spec.traits),
            # Las dos, y de la misma fuente. `aptitud_base` es la parte que no
            # cambia con el tick y `gains` la de hoy; una ficha recién nacida no
            # lleva nada encima, así que arrancan iguales. Dejar la base vacía
            # aquí hacía que el primer `refresh_state` borrara la aptitud entera
            # — y eso es la aptitud dejando de existir en el mundo.
            aptitud_base=(aptitud := compose_gains(pack, spec.traits)),
            gains=dict(aptitud),
            costs=compose_costs(pack, spec.traits),
            caps=compose_caps(pack, spec.traits),
            strain=strain,
            temperament=compose_temperament(pack, spec.traits, strain),
            # Lo declarado, tal cual. Las simetrías las cierra `WorldState.new`,
            # que es quien ve a los dos lados; desde aquí solo se ve uno.
            relations={rel: set(quienes) for rel, quienes in spec.relations.items()},
            bonds={
                other: Bond(regard=regard, encounters=1)
                for other, regard in spec.initial_bonds.items()
            },
            busy=None,  # todos deliberan en el tick 0
        )

    def observe(self, tick: int, present: frozenset[AgentId]) -> None:
        """Anota a quién ve donde está. Solo su propio sitio: nadie ve el barrio
        entero desde su cocina."""
        self.sightings[self.at] = (tick, present)

    def perceived_crowd(
        self, place: PlaceId, tick: int, horizon: int
    ) -> frozenset[AgentId] | None:
        """Quién CREE que hay allí. `None` = no lo sabe.

        Sin horizonte, omnisciencia: no hay memoria que valga y quien pregunta
        se queda con la verdad del mundo.

        Donde está, lo sabe de primera mano. De lo demás, tira de lo último que
        vio, si no ha caducado. Y lo que no sabe lo supone a favor — de ahí el
        `None`, que quien decide interpreta como "adelante, ya lo veré".
        """
        if horizon <= 0:
            return None
        seen = self.sightings.get(place)
        if seen is None or tick - seen[0] > horizon:
            return None
        return seen[1]

    # -- relaciones -----------------------------------------------------------

    def related_to(self, other: AgentId) -> tuple[RelationId, ...]:
        """Qué es esta persona de él. Ordenado, que aquí se multiplican floats."""
        return tuple(
            sorted(rel for rel, quienes in self.relations.items() if other in quienes)
        )

    def kin_present(self, others: Collection[AgentId]) -> dict[RelationId, int]:
        """Cuántos de los tuyos hay delante, por relación.

        Es lo que responde `requires_relation`, y la diferencia con contar
        cabezas es toda la gracia: cenar en familia no se arregla con más gente.
        """
        cuenta: dict[RelationId, int] = {}
        presentes = set(others)
        for rel, quienes in self.relations.items():
            n = len(quienes & presentes)
            if n:
                cuenta[rel] = n
        return cuenta

    def relation_floor(self, pack: ContentPack, other: AgentId) -> float | None:
        """El aprecio mínimo que le tiene por ser lo que es suyo. `None` = ninguno.

        Devolver 0.0 en vez de `None` cuando no hay suelo aplastaría el aprecio
        negativo, y entonces sería imposible detestar a nadie.
        """
        by_id = pack.relation_by_id
        suelos = [
            by_id[rel].regard_floor
            for rel in self.related_to(other)
            if by_id[rel].regard_floor is not None
        ]
        return max(s for s in suelos if s is not None) if suelos else None

    def relation_weight(self, pack: ContentPack, other: AgentId) -> float:
        """Cuánto pesa su presencia por ser de los tuyos. 1.0 si no lo es."""
        by_id = pack.relation_by_id
        total = 1.0
        for rel in self.related_to(other):
            total *= by_id[rel].company_multiplier
        return total

    def regard_for(
        self, other: AgentId, tick: int, fade: float, floor: float | None = None
    ) -> float:
        """Aprecio actual hacia alguien. Un desconocido vale 0.

        `floor` es lo que aporta la relación: el aprecio sigue subiendo y
        bajando con lo que se comparte, pero no cae por debajo. La familia se
        aguanta — y se aguanta también contra el desdibujado por no verse, que
        es lo que impide que un hermano ausente acabe valiendo lo que un extraño.
        """
        bond = self.bonds.get(other)
        sentido = 0.0 if bond is None else bond.regard_at(tick, fade)
        return sentido if floor is None else max(sentido, floor)

    def effective_company(
        self,
        others: Collection[AgentId],
        tick: int,
        weight: float,
        fade: float,
        pack: ContentPack | None = None,
    ) -> float:
        """Cuánta compañía es esa gente PARA ESTE AGENTE.

            compañía = Σ (1 + peso * aprecio)

        Sustituye al recuento en todo sitio donde la compañía hacía algo: el
        alivio pasivo de las necesidades, la escala de los efectos y el atractivo
        de un plan acompañado. Con `weight` a 0 devuelve el recuento exacto, así
        que el mundo anónimo de antes es el caso particular.

        Puede salir negativa, y debe poder: tres personas a las que detestas no
        son compañía, son un problema. La saturación está firmada para eso.

        La puerta dura `requires_company` NO pasa por aquí y sigue contando
        cabezas. Una fiesta necesita cuerpos; que te caigan bien es otra cosa, y
        confundirlas dejaría a un misántropo sin poder entrar en un bar lleno.

        Se suma **en orden de id**, y no es cosmética. Quien llama pasa a menudo
        un `frozenset`, cuyo orden de iteración depende del hash de las cadenas
        —aleatorizado por proceso—, y la suma en coma flotante no es asociativa.
        Sin ordenar, dos corridas con el mismo seed en dos procesos distintos
        pueden diferir en el último bit y de ahí en el log entero. Es la misma
        razón por la que los rasgos se recorren ordenados en `disposition.py`.

        Con `pack`, la presencia de los tuyos pesa distinto que la de un
        desconocido de igual aprecio: es la diferencia entre apreciar a alguien y
        que ese alguien sea de los tuyos. Sin `pack` no hay relaciones que mirar
        y se comporta exactamente como antes.
        """
        if weight <= 0.0:
            return float(len(others))
        if pack is None or not self.relations:
            return sum(
                1.0 + weight * self.regard_for(other, tick, fade) for other in sorted(others)
            )
        total = 0.0
        for other in sorted(others):
            aprecio = self.regard_for(other, tick, fade, self.relation_floor(pack, other))
            total += (1.0 + weight * aprecio) * self.relation_weight(pack, other)
        return total

    def remember_company(
        self, others: Collection[AgentId], premium: float, rate: float, tick: int
    ) -> None:
        """Actualiza el aprecio hacia quien acaba de compartir algo con él.

            aprecio <- aprecio + alfa * (premio - aprecio)

        Mismo error de predicción que `learn`, atribuido a personas. El premio va
        acotado a [-1, 1] antes de usarse como objetivo: es una suma pesada sin
        techo natural, y sin acotarla una velada excepcional mandaría el aprecio
        fuera de rango de un golpe.

        Todos los presentes reciben el mismo crédito. No es una simplificación:
        nadie puede saber cuál de los cuatro hizo buena la velada. Lo que
        distingue a unos de otros es la repetición — quien sale en todas las
        veladas buenas acumula, quien salió en una se diluye.
        """
        if rate <= 0.0 or not others:
            return
        target = max(-1.0, min(1.0, premium))
        for other in others:
            bond = self.bonds.get(other)
            if bond is None:
                bond = Bond()
                self.bonds[other] = bond
            bond.regard += rate * (target - bond.regard)
            bond.shared += 1
            bond.last_seen = tick

    def meet(self, other: AgentId, tick: int) -> None:
        """Registra un encuentro. Crea el vínculo si es el primero.

        Separado de `remember_company` porque cruzarse con alguien y compartir
        algo con alguien son cosas distintas: lo primero te hace conocerlo, lo
        segundo te hace apreciarlo o detestarlo.
        """
        bond = self.bonds.get(other)
        if bond is None:
            bond = Bond()
            self.bonds[other] = bond
        bond.encounters += 1
        bond.last_seen = tick

    def lleva(self, situacion: SituationId) -> bool:
        """Si lleva encima esa condición, con la marca que sea."""
        return any(c.situacion == situacion for c in self.condiciones)

    def elegir_destinatario(
        self, presentes: Sequence[AgentState], spec: TargetSpec
    ) -> AgentState | None:
        """A quién de los que están aquí. `None` si a ninguno.

        **Al que más aprecia de entre los que valen**, y el orden importa: el
        filtro es objetivo —lleva la condición o no la lleva— y el desempate es
        subjetivo. Al revés, ordenando por necesidad, el motor tendría que leer
        la ficha interna de todo el mundo para compararlos, que es la omnisciencia
        que `sightings` y el `owner` obligatorio de la memoria existen para
        impedir.

        Una condición **se ve** cuando estás delante: alguien sangrando se nota.
        El valor exacto de sus necesidades, no.

        Desempate por id, como en todas partes: sin él, dos procesos con la misma
        semilla curarían a personas distintas.
        """
        mejor: AgentState | None = None
        mejor_aprecio = 0.0
        for otro in presentes:
            if otro.spec_id == self.spec_id:
                continue
            if spec.requires_condition is not None and not otro.lleva(
                spec.requires_condition
            ):
                continue
            aprecio = self.bonds[otro.spec_id].regard if otro.spec_id in self.bonds else 0.0
            if aprecio < spec.min_regard:
                continue
            if mejor is None or (aprecio, otro.spec_id) > (mejor_aprecio, mejor.spec_id):
                mejor, mejor_aprecio = otro, aprecio
        return mejor

    def disposicion(self, hacia: AgentId, spec: TargetSpec) -> float:
        """Cuánto le compensa hacérselo **a este**. Multiplica la recompensa.

        No veta: encoge. Es la respuesta a *poco probable, no completamente
        improbable* — ayudar a un desconocido sigue valiendo algo, así que ocurre
        cuando no hay nada mejor que hacer.
        """
        if spec.regard_weight <= 0.0:
            return 1.0
        aprecio = max(0.0, self.bonds[hacia].regard if hacia in self.bonds else 0.0)
        return (1.0 - spec.regard_weight) + spec.regard_weight * aprecio

    def afligir(
        self,
        situacion: SituationId,
        marca: str = "",
        hasta: int | None = None,
        donde: PlaceId | None = None,
        gravedad: float = 1.0,
    ) -> Condicion:
        """Le pasa algo. Si ya llevaba una idéntica, se agrava en vez de duplicar.

        *Idéntica* es misma situación **y** misma marca. Otro tajo en el mismo
        brazo empeora el que había; uno en la pierna es otra cosa que drena
        aparte.

        El plazo se queda con el más largo de los dos. Envenenarse otra vez no
        acorta lo que quedaba del primero.
        """
        for cond in self.condiciones:
            if cond.situacion == situacion and cond.marca == marca:
                cond.gravedad += gravedad
                if hasta is None or cond.hasta is None:
                    cond.hasta = None
                else:
                    cond.hasta = max(cond.hasta, hasta)
                # El sitio se queda con el de la PRIMERA. Reescribirlo con el de
                # la última haría que la mazmorra donde casi te matan se borrase
                # por un rasguño reciente en la plaza, y lo que enseña a temer un
                # lugar es lo que empezó, no lo que remató.
                if cond.donde is None:
                    cond.donde = donde
                return cond

        cond = Condicion(situacion=situacion, marca=marca, hasta=hasta,
                         donde=donde, gravedad=gravedad)
        self.condiciones.append(cond)
        # Orden estable y por clave, no de llegada: los efectos se aplican en
        # secuencia y sumar floats en otro orden da otro número.
        self.condiciones.sort(key=lambda c: (c.situacion, c.marca))
        return cond

    def aliviar(
        self, situacion: SituationId, cuanto: float = 0.0, marca: str | None = None
    ) -> int:
        """Le baja la gravedad. Devuelve cuántas condiciones desaparecieron.

        **`cuanto` a 0.0 las quita enteras**, que es lo que hace la API pública y
        lo que hacía la versión anterior de este método. Con un número, resta esa
        gravedad y la condición solo se va cuando llega a cero.

        Esa es la mitad del diseño de las enfermedades: **curar deja de ser todo
        o nada**. Una noche de sueño baja 0.15 de fiebre y no hace nada por una
        pierna rota; un curandero se lleva 3.0 de golpe. Sin escribir en ningún
        sitio que el sueño cura la fiebre y no los huesos — sale del número.

        Que el defecto sea *todas las marcas* es deliberado:
        vendar sabe vendar heridas, no la del brazo derecho, y elegir una por
        `seq` sería inventarse un criterio médico que el motor no tiene.
        """
        antes = len(self.condiciones)
        if cuanto <= 0.0:
            self.condiciones = [
                c
                for c in self.condiciones
                if c.situacion != situacion or (marca is not None and c.marca != marca)
            ]
            return antes - len(self.condiciones)

        for cond in self.condiciones:
            if cond.situacion == situacion and (marca is None or cond.marca == marca):
                cond.gravedad -= cuanto
        self.condiciones = [c for c in self.condiciones if c.gravedad > 1e-9]
        return antes - len(self.condiciones)

    def expirar_condiciones(self, tick: int) -> list[SituationId]:
        """Quita las que se han pasado solas. Devuelve cuáles, para el log."""
        vencidas = [
            c.situacion for c in self.condiciones if c.hasta is not None and tick >= c.hasta
        ]
        if vencidas:
            self.condiciones = [
                c for c in self.condiciones if c.hasta is None or tick < c.hasta
            ]
        return vencidas

    def forget_bonds(self, tick: int, horizon: int) -> None:
        """Borra a quien no ve desde hace demasiado.

        Es el segundo mecanismo de olvido del motor, y el que mantiene acotado
        el estado: sin él, cada agente acumula una entrada por cada persona con
        la que se cruzó alguna vez, y en un mundo poblado eso crece sin techo.

        Que además se lea bien —pierdes el trato y acabas por no acordarte— es
        buena señal, pero no es el motivo.

        **A los tuyos no se les olvida**, y ahí está la mitad de lo que separa
        una relación de un vínculo. Un hermano al que no ves en un año sigue
        siendo tu hermano; si esto lo borrase, la relación se evaporaría por no
        usarla y sería un aprecio con nombre.
        """
        if horizon <= 0:
            return
        de_los_mios = {other for quienes in self.relations.values() for other in quienes}
        for other in [
            other
            for other, bond in self.bonds.items()
            if tick - bond.last_seen > horizon and other not in de_los_mios
        ]:
            del self.bonds[other]

    def animos(self) -> dict[SituationId, float]:
        """Lo que lleva encima, por gravedad acumulada. Puerta única.

        Dos condiciones de la misma situación en marcas distintas —una herida en
        el brazo y otra en la pierna— **suman**: estar herido dos veces afecta
        más a cómo decides que estarlo una. Es la misma regla que ya siguen sus
        `effects`, y separarlas haría que el daño y el ánimo contaran distinto lo
        mismo.
        """
        total: dict[SituationId, float] = {}
        for cond in self.condiciones:
            total[cond.situacion] = total.get(cond.situacion, 0.0) + cond.gravedad
        return total

    def refresh_state(self, pack: ContentPack) -> None:
        """Recalcula el desgaste y con él el temperamento.

        Se llama una vez por tick, después del decaimiento. Todo lo derivado del
        estado se recompone en un solo sitio, así que no puede quedar desfasado
        respecto a las necesidades que lo generan.

        Los ÁNIMOS entran aquí y no en `recompose` a propósito: una condición va
        y viene con el tick, igual que el desgaste, mientras que `recompose` es
        para lo que cambia cuando cambia la persona. Ponerlos allí dejaría a
        alguien decidiendo con el ánimo de ayer hasta que le tocara un rasgo.
        """
        animos = self.animos()
        self.strain = compute_strain(pack, self.needs)
        self.temperament = compose_temperament(pack, self.traits, self.strain, animos)

        # Y LA APTITUD, que un ánimo también toca: una fiebre no solo drena, hace
        # que todo cunda menos mientras dura. Se parte de la base estable —los
        # rasgos, que no cambian con el tick— y solo se multiplica para quien
        # lleve algo encima, que son treinta de doscientos.
        if not animos:
            self.gains = self.aptitud_base
            return
        gains = dict(self.aptitud_base)
        by_situation = pack.situation_by_id
        for situacion in sorted(animos):
            gravedad = animos[situacion]
            for need_id, m in by_situation[situacion].gain_multipliers.items():
                gains[need_id] = gains.get(need_id, 1.0) * m**gravedad
        self.gains = gains

    def drift_trait(self, pack: ContentPack, trait: TraitId, delta: float) -> None:
        """Mueve un rasgo y recompone lo que depende de él.

        Única puerta para cambiar la personalidad, y existe por el invariante:
        `need_weights` es derivado de `traits`, así que tocarlos por separado
        dejaría a un agente decidiendo con los pesos de quien era antes. Ese bug
        no rompe nada visible — solo hace que la deriva no surta efecto.

        El rasgo tiene que existir en el pack, pero NO hace falta que el agente
        lo tuviera declarado: nadie nace con todos los rasgos, y la experiencia
        puede despertar uno que estaba a cero. Lo que no puede es inventarse uno
        —eso sería una errata pasando por capacidad emergente— y por eso falla
        ruidosamente aquí en vez de reventar dentro de la composición.

        Todavía no lo llama nadie. Es la puerta que este paso existe para abrir:
        cicatrices, aprendizaje y rampancia entran por aquí.
        """
        if trait not in pack.trait_by_id:
            raise KeyError(
                f"el rasgo {trait!r} no existe en el pack {pack.id!r}; "
                f"declarados: {sorted(pack.trait_by_id)}"
            )
        self.traits[trait] = max(-1.0, min(1.0, self.traits.get(trait, 0.0) + delta))
        self.recompose(pack)

    def pursuing(self, pack: ContentPack) -> tuple[GoalSpec, ...]:
        """Las metas que este agente persigue ahora mismo.

        Lo logrado y lo perdido dejan de empujar, y eso es la mitad de lo que
        significa "meta": si siguiera pesando después de conseguirla, sería una
        necesidad con otro nombre.

        **Por qué `.get` y no `[...]`.** Es la única cosa que se le sigue
        preguntando al pack en caliente, y quien no tenga ficha allí se queda sin
        metas en vez de reventar. No es tolerancia a una errata: el pack se valida
        al cargar y `WorldState.new` llena censo y reparto de la misma fuente, así
        que faltar aquí solo puede significar una cosa —**haber nacido en marcha**—
        y esa no es un error, es un estado legítimo sin arcos todavía.

        Es también el hilo que hay que cortar cuando los recién nacidos necesiten
        metas propias, y no se corta hoy porque cortarlo obliga a decidir dónde
        viven las metas de quien no está escrito en ningún YAML. Esa decisión es
        de descendencia, no de censo.
        """
        ficha = pack.agent_by_id.get(self.spec_id)
        if ficha is None:
            return ()
        return tuple(
            goal
            for goal in ficha.goals
            if self.goals.get(goal.id) is GoalStatus.ACTIVE
        )

    def recompose(self, pack: ContentPack) -> None:
        """Rehace TODO lo derivado de rasgos y metas. Puerta única.

        Existe porque hay dos cosas que pueden mover los pesos —la personalidad
        y lo que se persigue ahora— y dispersar la recomposición dejaría a un
        agente decidiendo con los pesos de quien era antes. Ese bug no rompe
        nada visible: solo hace que la deriva o el logro no surtan efecto.
        """
        self.need_weights = compose_need_weights(pack, self.traits, self.pursuing(pack))
        self.phase_shift = compose_phase_shift(pack, self.traits)
        self.aptitud_base = compose_gains(pack, self.traits)
        self.gains = dict(self.aptitud_base)
        self.costs = compose_costs(pack, self.traits)
        self.caps = compose_caps(pack, self.traits)
        self.temperament = compose_temperament(pack, self.traits, self.strain)

    # -- necesidades ----------------------------------------------------------

    def decay(
        self,
        need_specs: Mapping[NeedId, NeedSpec],
        company: float = 0.0,
        company_scale: float = 1.0,
    ) -> None:
        """Baja cada necesidad según su propia tasa. Resultado en [0, 1].

        `company` es la compañía **efectiva**: los otros presentes, ya pesados
        por lo que este agente siente por cada uno (ver `effective_company`).
        Las necesidades que declaren `company_relief` decaen más despacio estando
        acompañado, con saturación `n/(n+escala)`. La escala la pone el pack
        (`company_scale`) y dice qué es una multitud aquí: con 1.0 tres personas
        ya dan tres cuartos del alivio, que es una aldea. Ver la nota en
        `company_saturation`.

        Y puede ir al revés. Con compañía efectiva negativa el alivio se vuelve
        castigo y la necesidad decae MÁS DEPRISA que a solas: un cuarto con
        alguien a quien no soportas es más solitario que un cuarto vacío.

        Indexa directo en vez de usar `.get(..., default)`: si una necesidad del
        pack no está en el dict del agente, eso es un bug de construcción y
        quiero que reviente aquí, ruidosamente, y no que se propague un default
        inventado. El invariante lo garantiza `WorldState.new`.
        """
        crowd = company_saturation(company, company_scale)

        libro = self.ledger
        for need_id, spec in need_specs.items():
            relief = spec.company_relief * crowd
            if libro is not None:
                # Bruto y alivio SEPARADOS, no el neto: el neto esconde
                # exactamente lo que se quiere ver, que es cuanta de la oferta
                # llega por estar en la sala sin hacer nada.
                libro.anotar(libro.demanda, need_id, spec.decay_per_tick)
                libro.anotar(libro.pasivo, need_id, relief)
            self._spend(need_id, spec.decay_per_tick - relief, spec.max_debt)

    def apply(
        self,
        effects: Mapping[NeedId, float],
        need_specs: Mapping[NeedId, NeedSpec],
        world_gains: Mapping[NeedId, float] | None = None,
    ) -> list[NeedId]:
        """Suma los deltas de una acción completada. Devuelve los rangos rotos.

        Los deltas pueden ser negativos: trabajar da moneda y quita descanso.
        Una necesidad que la acción no menciona no se toca.

        Lo positivo **paga la deuda antes de subir el valor** y lo negativo la
        acumula al pasarse de rosca. Toda reposición pasa por ahí, no solo la del
        sueño: si te has quedado sin comer días, el primer plato salda y no llena.

        `world_gains` es lo que el sitio y la situación hacen rendir
        (`WorldState.gains_at`). Hasta que existieron las situaciones esto solo
        se aplicaba a lo elástico, así que la calidad de un lugar no tocaba a una
        acción normal — la regla que el pack anunciaba solo era cierta a medias.
        """
        for need_id, delta in effects.items():
            if delta >= 0.0:
                # La aptitud escala lo que se GANA, no lo que cuesta. Que se te
                # dé bien la magia hace que estudiar cunda más; no hace que
                # trabajar canse menos. Lo mismo vale para el sitio y para cómo
                # esté el mundo: una hambruna quita alimento, no ganas de comer.
                contexto = 1.0 if world_gains is None else world_gains.get(need_id, 1.0)
                # Y el rango frena, que es el tercer factor sobre lo que se gana
                # —después de la aptitud y del sitio— y el único que depende de
                # cuánto llevas recorrido. Vale 1.0 en todo eje sin rangos.
                spec = need_specs.get(need_id)
                cuesta = 1.0 if spec is None else self.ritmo_de_rango(spec)
                self.gain(need_id, delta * self.gains.get(need_id, 1.0) * contexto * cuesta)
            else:
                # Y el temple escala lo que se GASTA, que es la mitad que
                # faltaba. El sitio y la situación NO entran aquí: una hambruna
                # quita alimento, no hace que gastarlo duela distinto. Lo que
                # cambia entre dos personas es el cuerpo que paga.
                gasto = -delta * self.costs.get(need_id, 1.0)
                if self.ledger is not None:
                    self.ledger.anotar(self.ledger.demanda, need_id, gasto)
                self._spend(need_id, gasto, need_specs[need_id].max_debt)

        # Y lo último: romper los rangos que se hayan llenado. Va AQUÍ dentro y
        # no en el tick loop para que no existan dos caminos — quien llame a
        # `apply` sube de rango, venga de donde venga la llamada.
        rotos: list[NeedId] = []
        for need_id in sorted(effects):
            spec = need_specs.get(need_id)
            if spec is None or spec.rank_slowdown <= 0.0:
                continue
            if self.needs[need_id] >= self.caps.get(need_id, 1.0) - 1e-9:
                self.subir_de_rango(need_id)
                rotos.append(need_id)
        return rotos

    def endure(
        self, effects: Mapping[NeedId, float], need_specs: Mapping[NeedId, NeedSpec]
    ) -> None:
        """Lo que el mundo te hace por estar donde estás. Deltas, como `apply`.

        Es el cuarto canal de una situación, y el único que **le pasa algo a
        alguien**. Los otros tres multiplican —lo que rinde, lo que apetece— o
        cierran un sitio; ninguno puede hacer daño. Sin este, una oleada de
        monstruos significa exactamente que apetece más trabajar.

        **Existe aparte de `apply` por el libro de calibración, no por capricho.**
        `apply` archiva lo positivo como `activo`, que el libro define como *lo
        que llega por actuar, lo único que una decisión puede mover*. Un regalo de
        una situación no llega por actuar: llega por estar ahí. Filarlo como
        activo inflaría la oferta que se atribuye a las decisiones y vaciaría la
        columna `de gorra`, que es justo la que dice dónde cortar cuando un eje
        está resuelto. Ese error ya costó una campaña entera con el vínculo.

        Lo negativo sí es demanda, igual que en `apply`: perder es perder, lo
        pierdas por gastarlo o porque nieva.
        """
        libro = self.ledger
        for need_id, delta in effects.items():
            if delta >= 0.0:
                if libro is not None:
                    libro.anotar(libro.pasivo, need_id, delta)
                self.restore(need_id, delta)
            else:
                # El temple también aquí, y es lo que expresa la resistencia de
                # una raza al retroceso ambiental: un enano bajo tierra sufre
                # menos cuando alguien fuerza la Tierra cerca. No es que canalice
                # mejor — es que su cuerpo aguanta esas condiciones.
                gasto = -delta * self.costs.get(need_id, 1.0)
                if libro is not None:
                    libro.anotar(libro.demanda, need_id, gasto)
                self._spend(need_id, gasto, need_specs[need_id].max_debt)

    # -- deuda ----------------------------------------------------------------
    #
    # El motor no sabía estar peor que vacío: el suelo recortaba y la información
    # se perdía, así que un guerrero de tres días de batalla y alguien que durmió
    # mal eran indistinguibles. La deuda guarda ese recorte aparte.
    #
    # Lo importante es que `needs` sigue viviendo en [0, 1]. La urgencia, el
    # desgaste, los requisitos y las métricas no se enteran de que esto existe;
    # lo único que cambia es cuánto tarda uno en recuperarse.

    def _spend(self, need_id: NeedId, amount: float, max_debt: float) -> None:
        """Baja una necesidad y anota como deuda lo que el suelo se habría comido."""
        raw = self.needs[need_id] - amount
        if raw < 0.0 and max_debt > 0.0:
            self.debt[need_id] = min(max_debt, self.debt.get(need_id, 0.0) - raw)
        self.needs[need_id] = self._clamp(need_id, raw)

    def ritmo_de_rango(self, spec: NeedSpec) -> float:
        """Cuánto le cunde este eje **en el rango en que va**. 1.0 si no tiene.

            ritmo = 1 / (1 + rango) ** rank_slowdown

        Al novato todo le enseña; al maestro ya casi nada. La cuesta no modela
        que el mundo se ponga difícil, modela que **queda menos por aprender**.
        """
        if spec.rank_slowdown <= 0.0:
            return 1.0
        return float((1 + self.rango.get(spec.id, 0)) ** -spec.rank_slowdown)

    def subir_de_rango(self, need_id: NeedId) -> int:
        """Rompe el rango: sube uno y vuelve a empezar. Devuelve el nuevo.

        **Se vuelve a cero y no se arrastra el sobrante.** Arrastrarlo sería más
        exacto y menos legible: el sobrante viene medido con el ritmo del rango
        viejo, así que al pasarlo al nuevo vale otra cosa. *Rompes un rango y
        empiezas el siguiente desde el principio* se lee de una vez y no engaña.
        """
        nuevo = self.rango.get(need_id, 0) + 1
        self.rango[need_id] = nuevo
        self.needs[need_id] = 0.0
        return nuevo

    def gain(self, need_id: NeedId, amount: float) -> float:
        """`restore` anotando en el libro. Es la puerta por la que entra lo que
        se GANA ACTUANDO, y por eso la usan tambien las acciones elasticas: sin
        ella, dormir —que repone por otra via— no aparecia en la contabilidad y
        el descanso salia con la mitad de oferta de la que tiene."""
        if self.ledger is not None:
            self.ledger.anotar(self.ledger.activo, need_id, amount)
        return self.restore(need_id, amount)

    def restore(self, need_id: NeedId, amount: float) -> float:
        """Repone, saldando primero. Devuelve lo que llegó a la necesidad.

        Ese retorno importa: es la diferencia entre lo que la acción rindió y lo
        que se nota. Quince horas de sueño tras una campaña reponen dos enteros
        de los que la mitad se van en pagar lo debido, y por eso el guerrero se
        levanta descansado justo cuando ya no debe nada.
        """
        owed = self.debt.get(need_id, 0.0)
        if owed > 0.0:
            paid = min(owed, amount)
            amount -= paid
            if owed - paid <= 0.0:
                del self.debt[need_id]
            else:
                self.debt[need_id] = owed - paid
        if amount <= 0.0:
            return 0.0
        before = self.needs[need_id]
        self.needs[need_id] = self._clamp(need_id, before + amount)
        return self.needs[need_id] - before

    def deficit(self, need_id: NeedId) -> float:
        """Cuánto falta para estar entero, contando lo debido.

        Es lo que fija la duración de una acción elástica, y por eso el guerrero
        endeudado duerme el doble que el vecino con el mismo descanso a cero.
        """
        return 1.0 - self.needs[need_id] + self.debt.get(need_id, 0.0)

    # -- hastío ---------------------------------------------------------------

    def saturate(self, action: ActionId, gain: float) -> None:
        """Registra que acaba de hacer esto. `gain` 0 no deja rastro."""
        if gain <= 0.0:
            return
        # A mano y no por `_clamp`: el hastio no es una necesidad y no tiene
        # techo por persona. Que alguien pueda llegar mas lejos con el fuego no
        # significa que se canse distinto de repetirlo.
        self.saturation[action] = max(
            0.0, min(1.0, self.saturation.get(action, 0.0) + gain)
        )

    def recover_novelty(self, rate: float) -> None:
        """Disipa el hastío. Lo que llega a cero se olvida.

        Borrar las entradas agotadas mantiene el diccionario del tamaño de lo
        que el agente hace últimamente, no de todo lo que ha hecho nunca.
        """
        if rate <= 0.0:
            return
        for action in list(self.saturation):
            resto = self.saturation[action] - rate
            if resto <= 0.0:
                del self.saturation[action]
            else:
                self.saturation[action] = resto

    def _clamp(self, need_id: NeedId, value: float) -> float:
        """El ÚNICO sitio donde se fuerza el rango. Una sola puerta.

        Si el clamp se dispersa, un día una necesidad vale 1.4 y pasas dos horas
        buscando quién la dejó así.

        El suelo es 0 para todos; el techo es **de cada cual**. Que reciba el eje
        es lo que hizo falta al aparecer los techos por rasgo: un mago con el
        viento aprendido no puede pasar de su tope aunque practique una década.
        """
        return max(0.0, min(self.caps.get(need_id, 1.0), value))

    # -- ocupación ------------------------------------------------------------

    def advance(self) -> None:
        """Consume un tick de lo que esté haciendo.

        Se detiene en 0 sin limpiar `busy`: quien llama necesita ver QUÉ acabó,
        para aplicar sus efectos o registrar la llegada. Poner `None` aquí
        destruiría esa información.

        `Busy` es inmutable, así que no se decrementa: se reemplaza. Nota sobre
        `model_copy`: **no revalida**. El `ge=0` del campo no se comprueba en la
        copia, y por eso la guarda de arriba (`ticks_remaining == 0`) es
        obligatoria y no defensiva.
        """
        busy = self.busy
        if busy is None or busy.ticks_remaining == 0:
            return
        self.busy = busy.model_copy(update={"ticks_remaining": busy.ticks_remaining - 1})

    @property
    def is_idle(self) -> bool:
        """Dos formas de estar ocioso: nunca empezó, o ya terminó."""
        return self.busy is None or self.busy.ticks_remaining == 0


def _close_relations(pack: ContentPack, agents: dict[AgentId, AgentState]) -> None:
    """Pone la otra mitad de cada relación declarada.

    El pack escribe la hermandad UNA vez y aquí se cierra: la simétrica se
    replica con su mismo nombre, la dirigida crea su inversa del otro lado.
    Obligar al pack a escribirlo dos veces garantizaría que antes o después
    falte una de las dos, y un mundo donde A es hermano de B pero B no lo es de
    A no falla en ninguna parte — simplemente se comporta raro.

    Se recorre en orden de pack y ordenado dentro de cada relación, porque el
    resultado alimenta sumas y productos de floats.
    """
    by_id = pack.relation_by_id
    for spec in pack.agents:
        agente = agents[spec.id]
        for rel in sorted(agente.relations):
            regla = by_id[rel]
            for otro in sorted(agente.relations[rel]):
                if otro not in agents:  # ya lo señaló la validación del pack
                    continue
                if regla.symmetric:
                    agents[otro].relations.setdefault(rel, set()).add(spec.id)
                elif regla.inverse is not None:
                    agents[otro].relations.setdefault(regla.inverse, set()).add(spec.id)


# -----------------------------------------------------------------------------
# Estado del mundo
# -----------------------------------------------------------------------------


@dataclass(slots=True)
class WorldState:
    pack: ContentPack
    travel: TravelMap
    """Construido UNA vez en `new`. No lo recalcules por tick."""

    tick: int = 0

    agents: dict[AgentId, AgentState] = field(default_factory=dict)
    """`dict` y no `list` ni `set`. Hacen falta dos cosas a la vez: búsqueda
    O(1) por id, y orden estable. `dict` da ambas desde 3.7. Un `set` rompe el
    determinismo en silencio y sin aviso."""

    censo: dict[AgentId, AgentSpec] = field(default_factory=dict)
    """**Quién existe, y de qué ficha viene.** La respuesta la da el mundo, no el
    pack.

    Hoy contiene exactamente `pack.agent_by_id` y ni uno más, así que este campo
    no cambia una sola conducta. Existe igualmente, y por una razón concreta: era
    `pack.agents` —congelado al cargar— lo único que contestaba a *quién existe*,
    y por eso **nadie podía nacer ni morir**. Mover la pregunta aquí no hace que
    nazca nadie; hace que haya un sitio donde escribirlo cuando toque.

    El diagnóstico que llevó a esto conviene dejarlo escrito, porque el plan lo
    tenía mal: `WorldState.agents` **ya era mutable**. El bloqueo nunca fue el
    reparto, sino que cada `AgentState` guarda un `spec_id` que apunta a una
    ficha inmutable. Y lo que se le pregunta a esa ficha en caliente resultaron
    ser tres cosas, no diecisiete: la etiqueta, las metas y si existes. Todo lo
    demás —rasgos, gustos, necesidades, relaciones, vínculos— se copia al
    `AgentState` al nacer y nunca se vuelve a consultar.

    **Invariante:** todo el que está en `agents` está en `censo`. Lo comprueba
    `tests/test_censo.py`.

    Al reanudar se reconstruye desde el pack, igual que el resto de lo derivado:
    manda el pack de hoy. Por eso no ocupa sitio en el guardado.
    """

    situations: dict[SituationId, int | None] = field(default_factory=dict)
    """Las situaciones EVENTUALES encendidas -> hasta qué tick, o `None` si es
    hasta que alguien la apague.

    Las periódicas no están aquí a propósito: son una función del reloj, así que
    guardarlas sería guardar algo que ya se sabe calcular, y en un salto temporal
    habría que arrastrarlas. Estar aquí es exactamente lo que distingue una
    guerra —que empieza cuando empieza— de un invierno.
    """

    last_trigger: dict[SituationId, int] = field(default_factory=dict)
    """Tick en que cada situación se encendió por última vez. De aquí sale el
    cooldown de los disparadores.

    Se guarda el ENCENDIDO y no el apagado porque el cooldown se cuenta desde
    ahí: medir desde el final obligaría a recordar cuándo acabó algo que ya no
    está, y `situations` solo guarda lo que sigue pasando.

    Solo lo escriben los disparadores. Encender a mano por la API no lo toca, y
    es deliberado: quien llama sabe lo que hace, y un guion no tiene por qué
    pelearse con la perilla que gobierna el azar.
    """

    rng: RngSource = field(default_factory=lambda: RngSource(0))
    """La fuente de aleatoriedad vive AQUÍ y se pasa explícitamente a quien la
    necesite. Nunca `import random; random.choice(...)` a nivel de módulo: eso
    usa un generador global compartido y ahí muere la reproducibilidad.

    No es un generador, sino una fábrica de generadores por clave. Cada sorteo
    pide el suyo con `rng.stream(...)`, y así el resultado no depende de cuántos
    sorteos hubo antes."""

    memoria: MemoriaEpisodica = field(default_factory=MemoriaEpisodica)
    """Lo que recuerda cada agente. Estado del mundo y no del agente, aunque sea
    por agente, y la razón es la política de olvido: repartida entre los sitios
    que graban recuerdos habría tres copias de la misma regla divergiendo.

    Apagada mientras `memory_capacity` valga 0, que es el defecto."""

    @property
    def seed(self) -> int:
        """Se escribe en la primera línea del log. Un bug se reproduce corriendo
        el mismo seed; sin esto, un fallo raro en el día 5 no se investiga."""
        return self.rng.seed

    @classmethod
    def new(cls, pack: ContentPack, seed: int) -> WorldState:
        """Construye el estado inicial desde un pack ya validado."""
        # El orden del pack fija el orden del mundo.
        agents = {spec.id: AgentState.from_spec(pack, spec) for spec in pack.agents}
        _close_relations(pack, agents)

        return cls(
            pack=pack,
            travel=TravelMap(pack.places),
            tick=0,
            agents=agents,
            # Copia, no `pack.agent_by_id`. El censo es del mundo y se va a
            # escribir; alias al dict del pack haría que una muerte en una
            # partida borrase al agente de cualquier otra cargada del mismo
            # fichero. Es el mismo motivo por el que `from_spec` copia los dicts.
            censo=dict(pack.agent_by_id),
            rng=RngSource(seed),
            # La capacidad y el desdibujado salen del pack de HOY, igual que todo
            # lo demás derivado: al reanudar sobre un pack retocado manda el
            # nuevo, no el que se guardó.
            memoria=MemoriaEpisodica(
                capacidad=pack.tuning.memory_capacity,
                fade=pack.tuning.memory_fade,
                # Disperso: solo quien se desvíe del ritmo del mundo. Un pack sin
                # el séptimo canal deja esto vacío y se comporta como siempre.
                fade_de={
                    spec.id: propio
                    for spec in pack.agents
                    if (propio := compose_memory_fade(
                        pack, spec.traits, pack.tuning.memory_fade
                    )) != pack.tuning.memory_fade
                },
            ),
        )

    # -- situaciones ----------------------------------------------------------

    def active_situations(self) -> tuple[SituationId, ...]:
        """Lo que le pasa al mundo ahora mismo, **ordenado**.

        Tupla ordenada y no `frozenset`, y no es manía: los multiplicadores se
        multiplican entre sí, la multiplicación de floats no es asociativa y el
        orden de iteración de un `frozenset` depende del hash. Sería la tercera
        vez que ese par rompe el determinismo en este motor.
        """
        activas = [
            spec.id
            for spec in self.pack.situations
            if spec.active_at(self.tick) or spec.id in self.situations
        ]
        return tuple(sorted(activas))

    def situations_at(self, place: PlaceId) -> tuple[SituationId, ...]:
        """Las que alcanzan a este sitio. Una sin `places` alcanza a todos."""
        by_id = self.pack.situation_by_id
        return tuple(s for s in self.active_situations() if by_id[s].reaches(place))

    def gains_at(
        self, place: PlaceId, situations: Sequence[SituationId] | None = None
    ) -> dict[NeedId, float]:
        """Cuánto cunde aquí y ahora lo que se haga, sin contar quién lo hace.

        El sitio y lo que le pasa al mundo entran por la MISMA puerta porque son
        lo mismo a dos escalas: dormir a la intemperie, y dormir a la intemperie
        en pleno invierno. Componerlos en dos sitios distintos sería la manera de
        que uno acabara aplicándose donde el otro no.

        Se itera ordenado porque multiplicar floats no es asociativo.

        `situations` se puede pasar ya resuelto. La deliberación recorre los
        veinticinco lugares y volver a filtrar las activas en cada uno sería
        rehacer el mismo trabajo veinticinco veces por agente y por decisión.
        """
        gains = dict(self.pack.place_by_id[place].gain_multipliers)
        by_id = self.pack.situation_by_id
        aqui = self.situations_at(place) if situations is None else situations
        for situation in aqui:
            for need, multiplier in sorted(by_id[situation].gain_multipliers.items()):
                gains[need] = gains.get(need, 1.0) * multiplier
        return gains

    def agents_in_order(self) -> list[AgentState]:
        """Los agentes en orden fijo y reproducible.

        Existe como método propio para que el orden se decida en UN sitio. El
        día que quieras aleatorizarlo por tick (para que el mismo agente no gane
        siempre los empates), se cambia aquí y en ningún otro lado.
        """
        return list(self.agents.values())

    # -- atajos que el tick loop y la deliberación usarán constantemente ------

    def spec_of(self, agent: AgentState) -> AgentSpec:
        """La ficha de este agente, según el censo del mundo.

        Llevaba desde F0 escrito como *«atajo que el tick loop usará
        constantemente»* y no lo llamaba nadie: los dos sitios que necesitaban
        una ficha iban directos a `pack.agent_by_id`. Ahora es la única puerta, y
        por eso el censo puede ser la autoridad — con el atajo muerto, cambiar de
        fuente habría exigido tocar cada consumidor.
        """
        return self.censo[agent.spec_id]

    def existe(self, agent: AgentId) -> bool:
        """Si el mundo reconoce a alguien con ese nombre.

        Se pregunta al censo y no a `agents` a propósito: son dos preguntas
        distintas en cuanto alguien pueda morirse —*tener ficha* y *estar
        presente*— y hoy que coinciden es el momento barato de separarlas.
        """
        return agent in self.censo

    def place_of(self, agent: AgentState) -> PlaceSpec:
        """Dónde está, con sus affordances. Decide qué acciones son válidas."""
        return self.pack.place_by_id[agent.at]

    def occupants(self) -> dict[PlaceId, frozenset[AgentId]]:
        """Quién hay en cada lugar. Una pasada, no una por consulta.

        La deliberación pregunta por los 21 lugares del mundo en cada decisión;
        recorrer los agentes por separado cada vez sería cuadrático.

        Devuelve nombres y no un recuento porque desde la capa relacional la
        pregunta dejó de ser "cuántos" para ser "quiénes". El recuento se saca
        con `len` donde todavía haga falta —la puerta dura de `requires_company`
        sigue contando cabezas—, así que no se pierde nada.
        """
        gathered: dict[PlaceId, set[AgentId]] = {}
        for agent in self.agents.values():
            gathered.setdefault(agent.at, set()).add(agent.spec_id)
        return {place: frozenset(who) for place, who in gathered.items()}

    def others_at(self, agent: AgentState) -> list[AgentState]:
        """Los demás agentes en el mismo lugar.

        Base de los eventos de encuentro del tick loop, y en F2 de quién puede
        hablar con quién.
        """
        return [
            other
            for other in self.agents_in_order()
            if other.spec_id != agent.spec_id and other.at == agent.at
        ]
