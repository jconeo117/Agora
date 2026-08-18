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
    N("dominio", "dominio", 0.0, 0.05, progression=True),
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

# TEMPERAMENTO. Los de siempre, para que dos personas de la misma raza y clase
# sigan sin ser la misma persona.
caracter = [
    T("audaz", "audaz", temperament_multipliers={"critical_need_threshold": 0.6,
                                     "loss_aversion": 0.65}),
    T("prudente", "prudente", temperament_multipliers={"critical_need_threshold": 1.5,
                                           "loss_aversion": 1.6}),
    T("sociable", "sociable", need_weight_multipliers={"vinculo": 1.9},
      temperament_multipliers={"companionship_weight": 1.8}),
    T("solitario", "solitario", need_weight_multipliers={"vinculo": 0.35},
      temperament_multipliers={"companionship_weight": 0.25}),
    T("ambicioso", "ambicioso", need_weight_multipliers={"dominio": 1.7,
                                                         "dinero": 1.3}),
    T("acomodado", "acomodado", need_weight_multipliers={"dominio": 0.5},
      temperament_multipliers={"travel_discount": 0.88}),
    T("madrugador", "madrugador", phase_shift=-18),
    T("nocturno", "nocturno", phase_shift=22),
]

traits = razas + afinidades + clases + caracter
