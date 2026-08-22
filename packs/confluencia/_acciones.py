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
    #  en dormir es la regla "con reposo y cuidado se pasa": baja la
    # fiebre poco a poco y no toca las heridas. Un cuerpo sabe pelear una
    # infeccion; no sabe cerrarse un tajo.
    A(id="dormir", label="dormir", duration_ticks=40, requires_affordance="cama",
      cures={"fiebre": 0.12},
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

    # LA PUERTA QUE HACE QUE UNA RELACION SE NOTE.
    #
    # Sin una accion que EXIJA a los tuyos, la capa relacional solo tinye
    # numeros: el suelo de aprecio y el multiplicador de compania cambian cuentas
    # que nadie ve. Con esto, tener pareja o hermanos ABRE algo que a los demas
    # les esta cerrado, y de golpe la gente tiene una razon para coincidir con
    # quien es suyo en vez de con quien tenga delante.
    #
    # TIENE QUE COSTAR, Y LA RAZON ES DEL MOTOR, NO DE LA AMBIENTACION.
    #
    # `requires_relation` se comprueba AL EJECUTAR, no al deliberar: uno decide
    # ir viendo que su pareja estaba alli y al llegar ya no esta. Eso es el
    # chasco de llegada y es correcto — pero ABORTAR NO ENSENYA NADA
    # (`learning_rate` solo corrige al completar), asi que una accion gateada
    # por una persona concreta se reintenta ETERNAMENTE.
    #
    # Medido con la primera version, que era gratis y prometia mucho:
    #
    #     cenar_con_los_tuyos   3060 abortadas /  124 completadas
    #     dar_leccion           2354 abortadas /   24 completadas
    #     abandonos del mundo entero: 2.3 % -> 98.6 %
    #
    # Lo unico que corta el bucle es el PRECIO: si fallar cuesta, deja de ser
    # la primera opcion de todos a todas horas. Por eso la cena se paga y la
    # leccion cansa, y por eso ninguna de las dos promete mas que sus rivales
    # sueltas -`comer` y `charlar` juntas dan mas-. Lo que compran no es
    # cantidad, es que ademas te acerca a quien es tuyo.
    A(id="cenar_con_los_tuyos", label="cenar con los tuyos", duration_ticks=6,
      requires_affordance="mesa", requires_relation="pareja",
      requires={"dinero": 0.08},
      satisfies={"vinculo": 0.55, "sustento": 0.45},
      costs={"dinero": 0.35, "descanso": 0.08},
      effects={"vinculo": 0.20, "sustento": 0.38, "dinero": -0.08},
      effects_per_company={"vinculo": 0.16},
      phase_multipliers={"noche": 1.8, "tarde": 1.1}, saturation_gain=0.10),

    # NO HAY `dar_leccion`, Y LA RAZON MERECE QUEDARSE ESCRITA.
    #
    # Se escribio -maestro y discipulo, `requires_relation: discipulo`- y se
    # retiro midiendo. Barrido de `satisfies` sobre cinco dias:
    #
    #     0.45     0 abortadas /  0 completadas   contenido muerto
    #     0.55   109          /  3                36 fracasos por uso
    #     0.65   492          /  4
    #     0.80  1581          / 19                abandonos del mundo al 37 %
    #
    # No hay ventana. Y la causa no es el numero sino la ARITMETICA DE LA
    # COINCIDENCIA: un maestro tiene uno o dos discipulos entre doscientos, asi
    # que la probabilidad de tenerlo delante en un sitio con `quietud` es
    # minuscula — mientras que la de QUERER hacerlo es alta en cuanto la accion
    # compite. Cada intento es un viaje y un fracaso, y abortar no ensenya nada.
    #
    # `cenar_con_los_tuyos` SI funciona con la misma primitiva, y la diferencia
    # es exactamente esa: una pareja comparte barrio y cama, asi que coincide.
    #
    # LA REGLA, para la proxima: una accion gateada por una persona concreta
    # solo es viable si esa persona esta donde tu estas la mayor parte del
    # tiempo. Es el mismo pelo de banda que hizo revertir `convidar` en la
    # ciudad, ver DECISIONES D-093.
    #
    # La relacion maestro/discipulo se queda igualmente, y no es decorado: el
    # suelo de aprecio hace que la muerte de un maestro le duela a los suyos, y
    # `company_multiplier` hace que su presencia valga mas. Una relacion puede
    # no hacer NADA mecanicamente y seguir siendo legitima.
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
      effects={"dominio": 0.012, "mana": -0.13, "descanso": -0.09},
      saturation_gain=0.10),
    A(id="estudiar", label="estudiar", duration_ticks=14,
      requires_affordance="archivo", satisfies={"dominio": 0.75},
      costs={"descanso": 0.7},
      effects={"dominio": 0.006, "descanso": -0.12}, saturation_gain=0.14),
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
      requires={"mana": 0.28},
      satisfies={"dominio": 0.9},
      costs={"mana": 1.0},
      effects={"dominio": 0.020, "mana": -0.22}, saturation_gain=0.07)
    for e in ("fuego", "agua", "tierra", "viento")
]

# --- GANARSE LA VIDA ---------------------------------------------------------

# EL ORDEN DE LAS FUENTES DE RANGO, y estaba al reves.
#
# `expoliar` daba 0.010: MENOS que estudiar en una biblioteca (0.011) y muy por
# debajo de practicar (0.016). El combate real era la PEOR fuente de rango del
# mundo.
#
# Ahora va por cuan REAL es la experiencia. Practicar y estudiar siguen contando
# -hay que repetir lo aprendido para perfeccionarlo- pero la practica pesa mas
# que la teoria, y bajar a una mazmorra pesa mas que las dos:
#
#   expoliar 0.075 · pacto 0.050 · contrato 0.030 · conjurar 0.020
#   templar 0.014 · practicar 0.012 · investigar 0.010 · estudiar 0.006
#
# Y de aqui sale el DESACOPLAMIENTO: si el rango viene del combate, `practicar`
# deja de ser la fuente principal y el liston puede bajar -rangos que avanzan-
# sin aplanar el mundo, porque el agotamiento ya no cuelga de el.
#
# OJO al tocar estos numeros: van en `effects`, NO en `satisfies`. `satisfies` es
# la PROMESA que la deliberacion lee y vive en 0..1; `effects` es lo que de
# verdad pasa. Confundirlos deja el mundo sin motivo para perseguir rango.
trabajar = [
    A(id="trabajar", label="trabajar", duration_ticks=18,
      requires_affordance="trabajo", satisfies={"dinero": 1.0},
      costs={"descanso": 0.8},
      effects={"dinero": 0.16, "descanso": -0.15, "vinculo": 0.02},
      saturation_gain=0.06),
    # El gremio paga mejor pero pide rango y cobra mana: es trabajo de aventurero.
    A(id="contrato_del_gremio", label="tomar un contrato", duration_ticks=22,
      requires_affordance="contratos", requires={"mana": 0.25},
      satisfies={"dinero": 1.0}, costs={"mana": 0.9, "descanso": 0.9},
      effects={"dinero": 0.28, "mana": -0.20, "descanso": -0.20, "dominio": 0.030},
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
      requires_affordance="expolio", requires={"mana": 0.35},
      satisfies={"dinero": 1.0, "dominio": 0.55},
      costs={"mana": 0.85, "descanso": 0.90},
      effects={"dinero": 0.40, "mana": -0.30, "descanso": -0.26, "dominio": 0.075},
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
      effects={"dominio": 0.014, "descanso": -0.20}, saturation_gain=0.09),

    # MAGO: teoria profunda. Pide rango y cobra en mana Y en descanso.
    A(id="investigar", label="investigar", duration_ticks=20,
      requires_affordance="archivo", requires_traits={"mago": 0.30},
      requires={"mana": 0.22},
      satisfies={"dominio": 1.0}, costs={"mana": 0.9, "descanso": 0.6},
      effects={"dominio": 0.010, "mana": -0.15, "descanso": -0.10},
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
      requires={"mana": 0.40}, requires_rank={"dominio": 1},
      satisfies={"dominio": 1.0}, costs={"mana": 1.0},
      effects={"dominio": 0.050, "mana": -0.34}, saturation_gain=0.06),
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
      effects={"salud": 0.55, "dinero": -0.16}, cures={"herida": 1.2, "fiebre": 0.8}),
    # Cuesta tiempo y no da salud a quien la hace: lo que gana es vinculo, y por
    # eso `regard_weight` alto. La sangre de otro es cosa suya salvo que le
    # tengas aprecio -y ahi esta el mendigo: poco probable, no imposible-.
    A(id="socorrer", label="socorrer a un herido", duration_ticks=10,
      requires_affordance="quietud", requires_company=1,
      satisfies={"vinculo": 0.80}, effects={"vinculo": 0.30},
      target={"gives": {"salud": 0.50}, "cures": {"herida": 1.6, "fiebre": 1.2},
              "requires_condition": "herida", "regard_weight": 0.70}),
]
actions = actions + herida
