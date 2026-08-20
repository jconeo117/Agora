"""Que se puede hacer en Confluencia.

La regla que ordena el catalogo: **cada accion es un intercambio**. Da algo,
cuesta algo, y pide estar en un sitio que lo permita. El sistema de mana entra
por `costs`, los rangos por `requires`, y las afinidades por `requires_traits`.

Y una nota de escala que costo entenderla en la ciudad: `satisfies` es una
INTENCION en 0-1 -cuanto persigue el agente ese eje al elegir- mientras que
`effects` es el delta real. Son dos numeros distintos y confundirlos hace que
todo el mundo persiga lo que menos rinde.
"""


def A(**k):
    return k


# --- LO QUE SOSTIENE UN CUERPO -----------------------------------------------

vivir = [
    # Elastica: dura lo que haga falta segun el deficit, entre un suelo y un tope.
    # Sin `effects` sobre descanso: lo repone el ritmo elastico, y declararlo en
    # los dos sitios lo aplicaria dos veces. El validador lo caza.
    A(id="dormir", label="dormir", duration_ticks=40, requires_affordance="cama",
      satisfies={"descanso": 1.0},
      elastic={"need": "descanso", "per_tick": 0.028, "min_ticks": 12},
      interruptible=True, phase_multipliers={"noche": 1.9, "manana": 0.5,
                                             "tarde": 0.35}),
    A(id="comer", label="comer", duration_ticks=3, requires_affordance="mesa",
      satisfies={"sustento": 1.0}, requires={"dinero": 0.06},
      costs={"dinero": 0.6},
      effects={"sustento": 0.34, "dinero": -0.05, "vinculo": 0.02},
      effects_per_company={"vinculo": 0.06}, saturation_gain=0.08),
    # Medido: se uso UNA vez en catorce dias, porque `comer` daba MAS sustento y
    # costaba menos. Aprovisionarse tiene que rendir mas que una comida suelta —
    # se paga de golpe lo que dura varios dias— o no es una decision, es un error.
    A(id="comprar_provisiones", label="comprar provisiones", duration_ticks=6,
      requires_affordance="mercaduria", satisfies={"sustento": 1.0},
      requires={"dinero": 0.16}, costs={"dinero": 1.0},
      effects={"sustento": 0.62, "dinero": -0.15}, saturation_gain=0.05),
    A(id="tomar_el_aire", label="tomar el aire", duration_ticks=4,
      requires_affordance="aire", satisfies={"descanso": 0.35},
      effects={"descanso": 0.06, "vinculo": 0.01}, saturation_gain=0.16),
]

# --- LO QUE SOSTIENE UN VINCULO ----------------------------------------------

convivir = [
    A(id="charlar", label="charlar", duration_ticks=5,
      requires_affordance="corrillo", requires_company=1,
      satisfies={"vinculo": 1.0}, effects={"vinculo": 0.10},
      effects_per_company={"vinculo": 0.30}, saturation_gain=0.12),
    # Nunca se uso: `charlar` daba casi lo mismo y era gratis. Convidar tiene que
    # comprar algo que charlar no puede dar — aqui, mucho mas vinculo por cabeza.
    # Pagar por afecto es una decision; pagar por lo mismo, un despiste.
    A(id="convidar", label="convidar una ronda", duration_ticks=8,
      requires_affordance="mesa", requires_company=1, requires={"dinero": 0.10},
      satisfies={"vinculo": 1.0}, costs={"dinero": 0.7, "descanso": 0.2},
      effects={"vinculo": 0.14, "dinero": -0.09, "descanso": -0.03},
      effects_per_company={"vinculo": 0.70}, saturation_gain=0.22),
]

# --- EL MANA -----------------------------------------------------------------
#
# Tres vias de reponerlo, con precios muy distintos. Es donde el sistema deja de
# ser una ficha y se vuelve una decision.

canalizar = [
    # La via segura y lenta. Elastica: se medita lo que haga falta.
    A(id="meditar", label="meditar", duration_ticks=24,
      requires_affordance="quietud", satisfies={"mana": 1.0},
      elastic={"need": "mana", "per_tick": 0.011, "min_ticks": 6},
      interruptible=True, saturation_gain=0.05),
    # La via rapida y cara: mana ambiental. Repone el triple que meditar y muerde
    # el descanso, porque es mana "sin filtrar". Ademas esta al fondo de las
    # catacumbas y tras un peaje, asi que ir ya es una decision.
    # Tampoco se uso, y ahi la culpa es de la geografia: esta al fondo de las
    # catacumbas, tras un peaje, a catorce ticks del centro, mientras `meditar`
    # se puede hacer en ocho sitios distintos. Para que el viaje pague, tiene que
    # llenar la reserva de golpe — que es lo que el documento dice del mana
    # ambiental: poder extra, sin filtrar, y caro.
    A(id="canalizar_linea_ley", label="canalizar la linea ley", duration_ticks=10,
      requires_affordance="linea_ley", satisfies={"mana": 1.0},
      requires={"descanso": 0.30},
      costs={"descanso": 1.0},
      effects={"mana": 0.85, "descanso": -0.28}, saturation_gain=0.12),
]

# --- APRENDER ----------------------------------------------------------------

aprender = [
    A(id="practicar", label="practicar", duration_ticks=12,
      requires_affordance="palestra", satisfies={"dominio": 1.0},
      requires={"mana": 0.20}, costs={"mana": 0.9, "descanso": 0.5},
      effects={"dominio": 0.016, "mana": -0.13, "descanso": -0.09},
      saturation_gain=0.10),
    A(id="estudiar", label="estudiar", duration_ticks=14,
      requires_affordance="archivo", satisfies={"dominio": 0.75},
      costs={"descanso": 0.7},
      effects={"dominio": 0.011, "descanso": -0.12}, saturation_gain=0.14),
]

# --- CONJURAR ----------------------------------------------------------------
#
# Cuatro acciones identicas salvo por la puerta de afinidad. Ahi esta el motor de
# la diferenciacion: dos agentes con la misma ficha y distinta afinidad no pueden
# hacer lo mismo, y el temple hace que al de nacimiento le cueste la mitad.
#
# `requires: dominio` es el rango. Un novato no puede: el sistema no se lo
# prohibe por decreto, es que la puerta no se le abre.

conjuros = [
    A(id=f"conjurar_{e}", label=f"conjurar {e}", duration_ticks=8,
      requires_affordance="palestra",
      requires_traits={f"afin_{e}": 0.20},
      requires={"mana": 0.28, "dominio": 0.18},
      satisfies={"dominio": 0.9},
      costs={"mana": 1.0},
      effects={"dominio": 0.020, "mana": -0.22}, saturation_gain=0.07)
    for e in ("fuego", "agua", "tierra", "viento")
]

# --- GANARSE LA VIDA ---------------------------------------------------------

trabajar = [
    A(id="trabajar", label="trabajar", duration_ticks=18,
      requires_affordance="trabajo", satisfies={"dinero": 1.0},
      costs={"descanso": 0.8},
      effects={"dinero": 0.16, "descanso": -0.15, "vinculo": 0.02},
      saturation_gain=0.06),
    # El gremio paga mejor pero pide rango y cobra mana: es trabajo de aventurero.
    A(id="contrato_del_gremio", label="tomar un contrato", duration_ticks=22,
      requires_affordance="contratos", requires={"dominio": 0.12, "mana": 0.25},
      satisfies={"dinero": 1.0}, costs={"mana": 0.9, "descanso": 0.9},
      effects={"dinero": 0.28, "mana": -0.20, "descanso": -0.20, "dominio": 0.004},
      saturation_gain=0.10),
    # Bajar a saquear. Paga mucho, cuesta mucho, y pide rango de verdad.
    # Es lo que da proposito a las mazmorras: sin esto son habitaciones vacias.
    # ESTABA ESTRICTAMENTE DOMINADA, y por eso las seis mazmorras del mapa
    # llevaban desiertas desde que se escribio el pack. Media: CERO usos en
    # catorce dias, con 186 de 200 agentes ya pasando la puerta de rango.
    #
    #   expoliar   dur 26   dinero 1.0   mana 1.0 + descanso 1.0   a 5-7 ticks
    #   trabajar   dur 18   dinero 1.0   descanso 0.8              al lado
    #
    # El comentario decia "paga mucho" y `effects` lo cumplia -0.40 contra 0.16-
    # pero LA DELIBERACION NO LEE `effects`, lee `satisfies`. Los dos anunciaban
    # `dinero: 1.0`, asi que ganaba el barato, nunca se probaba el otro y nunca
    # se aprendia que pagaba mejor. Una trampa de aprendizaje.
    #
    # `satisfies` esta acotado a 0..1, asi que no se arregla subiendo el dinero.
    # Se arregla anunciando lo que la mazmorra da y un turno de trabajo no puede
    # dar: RANGO. Fregar platos no te hace mejor mago.
    A(id="expoliar", label="expoliar la mazmorra", duration_ticks=26,
      requires_affordance="expolio", requires={"dominio": 0.30, "mana": 0.35},
      satisfies={"dinero": 1.0, "dominio": 0.55},
      costs={"mana": 0.85, "descanso": 0.90},
      effects={"dinero": 0.40, "mana": -0.30, "descanso": -0.26, "dominio": 0.010},
      # Y se vuelve de ahi abajo con algo encima. Es lo que separa una mazmorra
      # de un turno peor pagado.
      inflicts={"situation": "herida", "marca": "cuerpo"},
      saturation_gain=0.12),
]

# --- EL OFICIO ---------------------------------------------------------------
#
# **Lo que la primera version no tenia, y por eso fracaso.** Con cinco clases que
# solo se distinguian en multiplicadores, un mago y un guerrero hacian
# exactamente las mismas acciones en las mismas proporciones: comer, trabajar,
# dormir, practicar y charlar eran el 75% del dia de todo el mundo, y la
# diferenciacion salio en 0.329 contra el 0.867 de la ciudad.
#
# Un multiplicador cambia CUANTO, no QUE. Para que dos vidas se separen de verdad
# hace falta que haya cosas que uno pueda hacer y el otro no — y para eso ya
# existe `requires_traits`, que hasta ahora solo gateaba afinidades.
#
# Cada una tiene ademas su sitio, y de paso eso da proposito a media docena de
# lugares que el mapa declaraba y nadie pisaba.

oficios = [
    # GUERRERO: refuerza el cuerpo. Barato en mana, caro en cuerpo — su economia
    # es la del documento: "eficiente y sostenido, sin techo de dano a distancia".
    A(id="templar_el_cuerpo", label="templar el cuerpo", duration_ticks=14,
      requires_affordance="palestra", requires_traits={"guerrero": 0.30},
      satisfies={"dominio": 0.85}, costs={"descanso": 1.0},
      effects={"dominio": 0.017, "descanso": -0.20}, saturation_gain=0.09),

    # MAGO: teoria profunda. Pide rango y cobra en mana Y en descanso.
    A(id="investigar", label="investigar", duration_ticks=20,
      requires_affordance="archivo", requires_traits={"mago": 0.30},
      requires={"dominio": 0.15, "mana": 0.22},
      satisfies={"dominio": 1.0}, costs={"mana": 0.9, "descanso": 0.6},
      effects={"dominio": 0.030, "mana": -0.15, "descanso": -0.10},
      saturation_gain=0.08),

    # ASESINO: rafagas cortas y dinero rapido, en el muelle de contrabandistas.
    # Paga mejor que trabajar y muerde el vinculo: nadie presume de esto.
    A(id="trabajo_sucio", label="hacer un trabajo sucio", duration_ticks=12,
      requires_affordance="contrabando", requires_traits={"asesino": 0.30},
      requires={"mana": 0.20}, satisfies={"dinero": 1.0},
      costs={"mana": 0.8, "vinculo": 0.5},
      effects={"dinero": 0.26, "mana": -0.16, "vinculo": -0.05},
      saturation_gain=0.10),

    # MONTARAZ: caza. Da sustento y algo de dinero, y se hace lejos, en el campo
    # y en la linde del bosque salvaje.
    A(id="cazar", label="cazar", duration_ticks=16,
      requires_affordance="caza", requires_traits={"montaraz": 0.30},
      satisfies={"sustento": 1.0}, costs={"descanso": 0.8},
      effects={"sustento": 0.38, "dinero": 0.09, "descanso": -0.16},
      saturation_gain=0.08),

    # INVOCADOR: el pacto. Drenaje continuo, que es su economia entera segun el
    # documento — se sostiene, no se golpea. Aqui se aproxima con una accion muy
    # larga y muy cara; el drenaje de verdad pide que una situacion alcance a un
    # AGENTE, y eso es un hueco anotado.
    #
    # Y es lo que le da sentido a la cripta olvidada, que el mapa declaraba como
    # el sitio de las invocaciones y estaba vacio.
    A(id="sostener_un_pacto", label="sostener un pacto", duration_ticks=30,
      requires_affordance="invocacion", requires_traits={"invocador": 0.30},
      requires={"mana": 0.40, "dominio": 0.10},
      satisfies={"dominio": 1.0}, costs={"mana": 1.0},
      effects={"dominio": 0.038, "mana": -0.34}, saturation_gain=0.06),
]

# --- LA RED DE SEGURIDAD -----------------------------------------------------
#
# Sin affordance: se puede hacer en cualquier sitio. El pack no carga sin una de
# estas, y con razon: sin ella un agente puede quedarse sin ninguna opcion valida
# y la simulacion se bloquea.

red = [
    A(id="holgazanear", label="holgazanear", duration_ticks=4,
      satisfies={"descanso": 0.15}, effects={"descanso": 0.02}),
]

actions = vivir + convivir + canalizar + aprender + conjuros + trabajar + oficios + red


# --- LA HERIDA ---------------------------------------------------------------
#
# Lo que cierra el bucle de la sima. Sin una forma de quitarsela, expoliar seria
# una sentencia; con ella, la mazmorra es una decision con precio.
#
# `socorrer` es la que importa: es la primera accion de este mundo que sabe A
# QUIEN le hace falta, porque `requires_condition` mira lo que el otro lleva
# encima. Una herida se VE cuando estas delante; el valor exacto de las
# necesidades de otro, no.
herida = [
    # CUESTA DINERO, y ahi esta el escenario entero. Curarse solo es lo primero
    # que hace cualquiera -medido: con `vendarse` gratis, `socorrer` no se usaba
    # NI UNA VEZ, porque nadie necesita ayuda si puede apanyarse-. El unguento
    # se compra, asi que quien no tiene con que depende de que alguien le
    # aprecie lo suficiente. Es el mendigo herido, escrito sin nombrarlo.
    A(id="vendarse", label="vendarse", duration_ticks=12,
      requires_affordance="quietud", requires={"dinero": 0.22},
      satisfies={"salud": 0.90}, costs={"dinero": 0.45},
      effects={"salud": 0.55, "dinero": -0.16}, cures=["herida"]),
    # Cuesta tiempo y no da salud a quien la hace: lo que gana es vinculo, y por
    # eso `regard_weight` alto. La sangre de otro es cosa suya salvo que le
    # tengas aprecio -y ahi esta el mendigo: poco probable, no imposible-.
    A(id="socorrer", label="socorrer a un herido", duration_ticks=10,
      requires_affordance="quietud", requires_company=1,
      satisfies={"vinculo": 0.80}, effects={"vinculo": 0.30},
      target={"gives": {"salud": 0.50}, "cures": ["herida"],
              "requires_condition": "herida", "regard_weight": 0.70}),
]
actions = actions + herida
