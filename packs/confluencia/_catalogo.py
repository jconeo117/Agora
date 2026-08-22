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
caracter = [
    # +1 se lanza sin pensarlo y aguanta hasta el final; -1 calcula y se retira
    # pronto. Toca las dos perillas que deciden cuando cunde el panico y cuanto
    # pesa lo que se arriesga.
    T("audacia", "audacia", temperament_multipliers={"critical_need_threshold": 0.6,
                                                     "loss_aversion": 0.65}),
    # +1 necesita gente y ademas le atrae el bullicio; -1 ni lo uno ni lo otro.
    # Son DOS canales porque son dos cosas: un ermitanyo puede echar de menos a
    # alguien concreto y aun asi no querer entrar en una taberna llena.
    T("sociabilidad", "sociabilidad", need_weight_multipliers={"vinculo": 2.1},
      temperament_multipliers={"companionship_weight": 2.4}),
    # +1 quiere llegar mas alto y cobrar por ello; -1 esta a gusto donde esta.
    T("ambicion", "ambicion", need_weight_multipliers={"dominio": 1.7,
                                                       "dinero": 1.3}),
    # El cronotipo, que es un DESFASE y no una preferencia: para un ave nocturna
    # la noche no vale mas, la noche ES su manyana. A -0.82 salen los -18 ticks
    # que llevaba `madrugador`.
    T("nocturnidad", "nocturnidad", phase_shift=22),
]

traits = razas + afinidades + clases + caracter
