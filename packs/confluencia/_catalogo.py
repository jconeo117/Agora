"""Catalogos de Confluencia: necesidades, rasgos y acciones.

Separado de `generar.py` por lo mismo que en la ciudad: el catalogo se lee de un
vistazo y el generador se ocupa de poblarlo. Aqui vive el SISTEMA; alli, la gente.

El mundo sale de dos documentos de diseno -el sistema de mana y el de razas- y la
traduccion a primitivas del motor es casi entera:

    mana                 -> una `need` con `max_debt`  (quemar reservas ES la deuda)
    afinidad             -> un `trait` + `requires_traits` en el conjuro
    de nacimiento vs aprendida -> el MISMO trait a distinta intensidad
    reserva por raza     -> `cost_multipliers` sobre mana   (el temple)
    regeneracion por raza-> `gain_multipliers` sobre mana   (la aptitud)
    rangos               -> un eje de progresion + `requires` en los hechizos
    clases               -> paquetes de rasgos + puertas por rasgo

Lo que NO entra en esta version, y por que: elementos compuestos, avanzados y
conceptuales (multiplicarian el catalogo sin cambiar la pregunta que se le hace a
esta corrida, que es si la gente sale distinta); ventanas del Nucleo por edad,
herencia y no-muertos (piden RAIZ 1: nacer, morir, envejecer).
"""

# --- NECESIDADES -------------------------------------------------------------
#
# Seis ejes. La ciudad tiene quince y es demasiado para estrenar un sistema: con
# seis se puede leer el panel de oferta/demanda de un vistazo y saber cual esta
# muerto.


def N(i, l, d, e, **k):
    return {"id": i, "label": l, "decay_per_tick": d, "initial": e, **k}


needs = [
    # EL EJE DEL SISTEMA. Decae despacio -no se pierde mana por existir, casi-
    # pero los conjuros lo muerden. `max_debt` es literalmente "quemar reservas":
    # se puede gastar por debajo de cero, y eso deja resaca durante dias.
    N("mana", "mana", 0.0006, 0.85, urgency_exponent=2.6, max_debt=0.40,
      company_relief=0.0),
    N("sustento", "sustento", 0.0045, 0.70, urgency_exponent=2.0, max_debt=0.15),
    N("descanso", "descanso", 0.0050, 0.70, urgency_exponent=2.2, max_debt=0.30),
    N("dinero", "dinero", 0.0012, 0.50, urgency_exponent=1.6),
    N("vinculo", "vinculo", 0.0030, 0.45, urgency_exponent=1.8, company_relief=0.0016),
    # El rango. Solo sube y nunca es una emergencia: ser novato no es una crisis.
    # De el cuelgan las puertas de los conjuros, que es como el sistema convierte
    # "Novato -> Trascendente" en algo que decide conducta.
    # RANGOS NUMERADOS, sin techo. El valor dice cuanto lleva del rango en curso;
    # `rango` dice cuantos ha roto. Siempre se puede ser mas fuerte, y siempre
    # cuesta mas: `rank_slowdown` 1.0 es inversamente proporcional, asi que el
    # rango 3 sube a un cuarto de velocidad que el 0.
    #
    # Sustituye a un `cap` plano que se probo antes y empeoraba las cosas: hacia
    # que la gente llegara a su tope ANTES, y el contenido que dependia del eje
    # -las mazmorras- se moria aun mas deprisa. Ver ERRORES E-002.
    #
    # Empieza en 0.0 y no en 0.05: con rangos, el 0.05 era "ya llevas un 5 % del
    # primero", que no queria decir nada.
    # `cap` 0.06 es EL LISTON DE UN RANGO, no un techo de poder: lo que hay que
    # acumular para romper el que llevas. Pequenyo a proposito.
    #
    # Salio de medir y de un error mio: al pasar de "toda tu carrera va de 0 a 1"
    # a "un RANGO va de 0 a 1" no se reescalo nada, y con el liston en 1.0 un
    # solo rango costaba mas que la progresion entera de antes. Resultado: CERO
    # rangos rotos en sesenta dias, los 200 en rango 0.
    #
    # El eje ganaba ~0.87 en sesenta dias. Con la cuesta inversa, llegar al rango
    # 5 pide 1+2+3+4+5 = 15 listones, asi que 0.87/15 = 0.058. Redondeado a 0.06.
    N("dominio", "dominio", 0.0, 0.0, progression=True,
      rank_slowdown=1.0, cap=0.50),
    # EL EJE MORTAL. No decae -nadie se desangra en su cama- y solo lo gasta
    # una herida. Sin `strain_weight` a proposito: se midio que anyadir una
    # necesidad es gratis, pero que una que declare desgaste recompone el de
    # TODO el mundo, porque `compute_strain` divide por la suma de los pesos.
    #
    # Tres dias a cero. Da tiempo de sobra a llegar a un sanador: lo que mata
    # no es la herida, es no ir -o no tener con que, o que nadie te lleve-.
    N("salud", "salud", 0.0, 1.0, urgency_exponent=2.6, lethal_after=288),
]

# --- RELACIONES --------------------------------------------------------------
#
# UN VINCULO ES LO QUE SIENTES; UNA RELACION ES LO QUE ERES DE ALGUIEN.
#
#   `Bond`     emergente, asimetrico, gradual, y se desdibuja si dejas de verte
#   relacion   un HECHO. No crece con el trato ni se disuelve por dejar de verse
#
# Tu hermano sigue siendo tu hermano el anyo que no lo visitas, y lo sigue siendo
# el dia que lo detestas. Meterlo dentro del vinculo habria hecho imposible
# justamente eso: un aprecio con nombre se disolveria con el aprecio.
#
# Y `regard_floor` es lo que decide a quien le duele tu muerte. Se leia en crudo
# durante meses -perder a tu pareja dolia lo que hubierais cenado juntos
# ultimamente- hasta que se arreglo. Ver DECISIONES D-041.
relations = [
    # Exclusiva y con suelo alto: la que sostendra la descendencia el dia que
    # exista. El suelo no es carinyo garantizado, es un MINIMO: el aprecio sigue
    # subiendo y bajando con lo que se comparta, pero no cae por debajo.
    {"id": "pareja", "label": "pareja", "symmetric": True, "exclusive": True,
     "regard_floor": 0.45, "company_multiplier": 2.0},

    # SIN SUELO A PROPOSITO, y es la mitad de la gracia de separar las dos cosas.
    # Un hermano puede caerte fatal y el pack tiene que poder escribirlo; lo que
    # no puede es dejar de ser tu hermano. Empiezan de cero y se ganan lo que
    # sientan.
    {"id": "hermano", "label": "hermano", "symmetric": True,
     "company_multiplier": 1.5},

    # Dirigida, y con suelos DISTINTOS en cada lado a proposito: el discipulo
    # admira mas de lo que el maestro se encarinya. Un maestro tiene varios; un
    # discipulo, uno.
    {"id": "maestro", "label": "maestro de", "inverse": "discipulo",
     "regard_floor": 0.20, "company_multiplier": 1.4},
    {"id": "discipulo", "label": "discipulo de", "inverse": "maestro",
     "regard_floor": 0.30, "company_multiplier": 1.6},
]


# --- RASGOS ------------------------------------------------------------------


def T(i, l, **k):
    return {"id": i, "label": l, **k}


# RAZAS. Cinco palancas del documento, expresadas con los canales que hay.
# La sexta -duracion de la ventana del Nucleo- pide edad y no esta.
razas = [
    # El grupo de control. Sin sesgo, y por eso la mayor varianza: el generador
    # le da tiradas mas anchas de afinidad y de clase que a nadie.
    T("humano", "humano"),

    # Reserva alta, regeneracion lenta: "el mana se almacena como mineral".
    # Y resistencia al retroceso de Tierra, que es temple sobre el eje que muerde.
    T("enano", "enano",
      cost_multipliers={"mana": 0.62, "descanso": 0.85},
      gain_multipliers={"mana": 0.75}),

    # Reserva enorme, control pesimo. Lo primero es temple; lo segundo son las
    # puertas: `dominio` le rinde poco, asi que tarda una eternidad en abrir los
    # conjuros de rango alto. No hace falta prohibirle nada.
    T("gigante", "gigante",
      cost_multipliers={"mana": 0.45},
      gain_multipliers={"mana": 0.85, "dominio": 0.45, "descanso": 1.15}),

    # La ventana extendida, aproximada por lo unico que hoy se puede decir: que
    # aprende mas deprisa. No es lo mismo -la ventana da mas INTENTOS, no mas
    # velocidad- y queda anotado como la deuda que RAIZ 1 salda.
    T("elfo", "elfo",
      gain_multipliers={"mana": 1.25, "dominio": 1.5},
      cost_multipliers={"mana": 1.1}),

    # Ventanas cortas: una afinidad bien dominada, no varias. Cuerpo por delante
    # de nucleo, asi que se inclina a las clases fisicas sin que nadie lo decrete.
    T("demihumano", "demihumano",
      gain_multipliers={"descanso": 1.3, "sustento": 1.2, "dominio": 0.8},
      cost_multipliers={"descanso": 0.75, "mana": 1.15}),
]

# AFINIDADES. Cuatro basicos, y nada mas en esta version.
#
# El truco esta en la INTENSIDAD: el mismo rasgo a 1.0 es afinidad de nacimiento
# y a 0.35 es aprendida. Como `cost_multipliers` compone con la intensidad como
# exponente, 0.55**1.0 = 0.55 y 0.55**0.35 = 0.81. La regla "de nacimiento
# siempre es mas barato" sale de la aritmetica, no de un caso especial.
afinidades = [
    T(f"afin_{e}", f"afinidad de {e}", cost_multipliers={"mana": 0.55})
    for e in ("fuego", "agua", "tierra", "viento")
]

# CLASES. Cada una gasta el mana de forma distinta, que es lo que el documento
# pedia para que no fueran "todas magas con distinto disfraz".
clases = [
    # Refuerza el cuerpo. Barato en mana, caro en descanso, y aguanta.
    T("guerrero", "guerrero",
      cost_multipliers={"mana": 0.7, "descanso": 0.8},
      gain_multipliers={"dominio": 0.7},
      need_weight_multipliers={"descanso": 1.3, "mana": 0.6}),
    # El conjurador puro: mas mana, mas dominio, cuerpo fragil.
    T("mago", "mago",
      gain_multipliers={"mana": 1.3, "dominio": 1.35},
      cost_multipliers={"descanso": 1.25},
      need_weight_multipliers={"mana": 1.6, "dominio": 1.4}),
    # Rafagas cortas: gasta poco por acto pero no sostiene. Se modela como coste
    # bajo y aptitud de mana baja — se vacia y tarda en volver.
    T("asesino", "asesino",
      cost_multipliers={"mana": 0.75},
      gain_multipliers={"mana": 0.8},
      need_weight_multipliers={"dinero": 1.4, "vinculo": 0.6}),
    T("montaraz", "montaraz",
      gain_multipliers={"sustento": 1.25, "descanso": 1.15},
      need_weight_multipliers={"sustento": 1.2, "vinculo": 0.8}),
    # Drenaje continuo: el pacto cuesta mana todo el rato. Hoy se aproxima con
    # un coste alto y sostenido; el drenaje de verdad pide que una situacion
    # alcance a un AGENTE y no a un lugar, que es un hueco anotado.
    T("invocador", "invocador",
      cost_multipliers={"mana": 1.2},
      gain_multipliers={"mana": 1.15, "dominio": 1.1},
      need_weight_multipliers={"mana": 1.5}),
]

# CARACTER. Para que dos personas de la misma raza y clase sigan sin ser la
# misma persona.
#
# =============================================================================
# CUATRO EJES, NO OCHO RASGOS. Y la razon es aritmetica, no de estilo.
#
# La intensidad se aplica como EXPONENTE, asi que -1.0 invierte el rasgo EXACTO:
# `audacia` a -1.0 ES la prudencia, con los reciprocos justos. Escribir el
# opuesto al lado es escribir el mismo rasgo dos veces.
#
# Y no era solo redundante: el generador sorteaba sin mirar, asi que podia dar
# los dos a la vez. Medido sobre el pack anterior:
#
#     ambicioso + acomodado a la vez     6 agentes
#     madrugador + nocturno              2
#     audaz + prudente                   1
#
# Nueve personas cuyo `dominio` se multiplicaba por 1.7 y por 0.5 a la vez. No
# reventaba nada -los factores se componen y algo sale- pero lo que salia no lo
# habia decidido nadie.
#
# Al fusionar, la mitad negativa deja de ser un rasgo aparte y pasa a ser
# inalcanzable por accidente: nadie puede ser lo uno y lo otro porque son EL
# MISMO NUMERO con el signo cambiado.
#
# NOTA sobre los valores: los pares no estaban centrados -`sociable` daba
# vinculo 1.9 y `solitario` 0.35, que no es 1/1.9- porque cada uno se escribio
# por su lado. Al fusionar hay que elegir UNO, y se toma un punto entre los dos
# reciprocos. El `travel_discount` que llevaba `acomodado` sale de aqui: es un
# eje distinto -el arraigo- y le toca su propio rasgo, no ir de polizon.
# =============================================================================
# -----------------------------------------------------------------------------
# COMO DECIDE — y aqui va una regla que se paga sola: UNA PERILLA, UN EJE DUENYO.
#
# Dos rasgos que toquen `loss_aversion` se multiplican sobre ella y ya no se
# puede leer que hizo cual. Es el enredo de los pares contradictorios, mas
# disimulado y mas dificil de ver. Asi que cada una de las cinco perillas del
# motor tiene exactamente un rasgo responsable:
#
#     temperature              -> impulsividad
#     loss_aversion            -> calculo
#     critical_need_threshold  -> audacia
#     travel_discount          -> arraigo
#     companionship_weight     -> sociabilidad
#
# Cuando alguien decida raro, se sabe donde mirar.
# -----------------------------------------------------------------------------
decidir = [
    # +1 aguanta hasta el final; -1 se retira pronto. Es CUANDO cunde el panico,
    # no cuanto se arriesga: eso es `calculo`.
    T("audacia", "audacia",
      temperament_multipliers={"critical_need_threshold": 0.6}),
    # +1 decide a bulto, -1 siempre la mejor opcion. El eje de lo erratico, y el
    # unico que produce a alguien que hoy hace algo que ayer no habria hecho sin
    # que le haya cambiado nada por dentro.
    T("impulsividad", "impulsividad",
      temperament_multipliers={"temperature": 2.8}),
    # +1 mide cada moneda antes de gastarla; -1 vive el momento.
    T("calculo", "calculo", temperament_multipliers={"loss_aversion": 1.9}),
    # +1 no sale de su barrio; -1 andariego. OJO: `travel_discount` se recorta a
    # 1.0 al componerse, asi que el arraigo se escribe entero pero el nomadismo
    # SATURA — llega hasta "la distancia no cuesta nada" y ahi se para. No es un
    # fallo: ese es el techo real.
    T("arraigo", "arraigo", temperament_multipliers={"travel_discount": 0.85}),
    # +1 necesita gente y ademas le atrae el bullicio; -1 ni lo uno ni lo otro.
    # Son DOS canales porque son dos cosas: un ermitanyo puede echar de menos a
    # alguien concreto y aun asi no querer entrar en una taberna llena.
    T("sociabilidad", "sociabilidad", need_weight_multipliers={"vinculo": 2.1},
      temperament_multipliers={"companionship_weight": 2.4}),
]

# -----------------------------------------------------------------------------
# QUE LE IMPORTA — un eje por necesidad del mundo, y todos con contrapeso.
#
# Un rasgo que solo SUBE cosas no es una personalidad: es un multiplicador
# global. Lo que hace a alguien es a que renuncia.
# -----------------------------------------------------------------------------
querer = [
    T("ambicion", "ambicion", need_weight_multipliers={"dominio": 1.7,
                                                       "dinero": 1.3}),
    T("codicia", "codicia", need_weight_multipliers={"dinero": 2.0,
                                                     "vinculo": 0.75}),
    T("gula", "gula", need_weight_multipliers={"sustento": 1.8,
                                               "dinero": 0.85}),
    T("pereza", "pereza", need_weight_multipliers={"descanso": 1.8,
                                                   "dominio": 0.7}),
    # El que vive por el arte y no por lo que da de comer.
    T("devocion", "devocion", need_weight_multipliers={"mana": 1.9,
                                                       "dinero": 0.75}),
    # A -1.0 es el temerario que ignora una herida hasta que se cae. Hasta ahora
    # `salud` no la ponderaba NI UN rasgo: nadie cuidaba su pellejo mas que la
    # media, y nadie menos.
    T("aprension", "aprension", need_weight_multipliers={"salud": 2.2}),
]

# -----------------------------------------------------------------------------
# QUE SE LE DA BIEN Y QUE AGUANTA
# -----------------------------------------------------------------------------
poder = [
    # Aprende deprisa. NO ES LO MISMO QUE `prodigio`, y la distincion es la
    # buena: `talento` sube mas rapido DENTRO del rango, `prodigio` necesita
    # menos PARA ROMPERLO.
    T("talento", "talento", gain_multipliers={"dominio": 1.5, "mana": 1.2}),
    # Encaja los golpes: todo lo que le quite salud le quita un 28 % menos. Es
    # el canal por el que entrara D-111 el dia que el rango endurezca.
    T("dureza", "dureza", cost_multipliers={"salud": 0.72, "descanso": 0.85}),
    # Aguanta privaciones. El hambre y el sueno le muerden menos.
    T("templanza", "templanza", cost_multipliers={"sustento": 0.72,
                                                  "descanso": 0.75}),
]

# -----------------------------------------------------------------------------
# LOS DOS CANALES QUE NINGUN MUNDO HABIA ESTRENADO
# -----------------------------------------------------------------------------
raro = [
    # `memory_multipliers`: CERO rasgos en los tres mundos hasta hoy, y con el
    # duelo encendido es el que mas separa a dos personas. Es literalmente quien
    # supera una perdida en dos semanas y quien reordena su vida entera.
    #
    # Ojo con la direccion, que es la contraria a la intuicion: MAS GRANDE =
    # RECUERDA MAS TIEMPO. No escala el desdibujado, escala la MEDIA VIDA.
    T("tenacidad", "tenacidad", memory_multipliers=3.2),
    # `cap_multipliers`: tambien cero. Y con rangos, `cap` no es el techo sino
    # EL LISTON -cuanto hay que acumular para romper el rango en curso-, asi que
    # un cap BAJO es un don. A 0.55 rompe cada rango con poco mas de la mitad; a
    # -1.0 es el tardio, que necesita casi el doble que nadie.
    #
    # Solo tiene efecto sobre `dominio`: los demas ejes de este mundo tienen cap
    # 1.0 y el motor recorta a 1.0 al componer.
    T("prodigio", "prodigio", cap_multipliers={"dominio": 0.55}),
    # El cronotipo, que es un DESFASE y no una preferencia: para un ave nocturna
    # la noche no vale mas, la noche ES su manyana. A -0.82 salen los -18 ticks
    # que llevaba `madrugador`.
    T("nocturnidad", "nocturnidad", phase_shift=22),
]

# -----------------------------------------------------------------------------
# TITULOS — rasgos que NO se sortean: se ganan.
#
# No entran en el sorteo del generador. Los concede el `on_success` de una meta,
# que es el unico camino que hay hoy para que un rasgo cambie con la vida, y
# sirven de vara para el eslabon siguiente de un arco (`at_traits`).
#
# Llevan un efecto pequenyo a proposito. Podrian no llevar ninguno -un titulo es
# legitimo aunque no haga nada, como una relacion- pero si algo se GANA conviene
# que se note, aunque sea poco.
# -----------------------------------------------------------------------------
titulos = [
    # A quien ya se le conoce, la gente se le acerca antes.
    T("nombrado", "de nombre conocido", gain_multipliers={"vinculo": 1.15}),
]

# `caracter` es lo que el generador sortea. Los titulos van aparte a proposito:
# meterlos en la bolsa haria que alguien naciera con un nombre que no se ha
# ganado, y entonces el arco que lo concede no significaria nada.
caracter = decidir + querer + poder + raro

traits = razas + afinidades + clases + caracter + titulos
