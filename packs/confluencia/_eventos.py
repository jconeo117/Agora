"""EVENTOS DE CONFLUENCIA — plantilla, reglas y catalogo.

Un evento es una `situacion`: un estado del mundo CON NOMBRE que va y viene, y
que mientras dura cambia lo que la gente hace. No es un guion ni una escena: es
una condicion del mundo, y los habitantes reaccionan a ella deliberando como
siempre.

Se importa desde `generar.py`: `from _eventos import condiciones, eventos`.

===============================================================================
LOS CINCO CANALES
===============================================================================

Ninguno es obligatorio, pero el pack NO CARGA si una situacion no hace al menos
uno: una situacion que no hace nada se lee como contenido vivo y no lo es.

  1  gain_multipliers      lo que RINDE cada eje mientras dure
                           1.5 = todo lo que reponga eso cunde un 50 % mas
                           0.4 = cunde menos de la mitad

  2  situation_multipliers va en la ACCION (`_acciones.py`): cuanto APETECE
                           hacer algo durante la situacion

  3  closed_during         va en el LUGAR (`_mapa.yaml`): lo cierra del todo

  4  effects               DAÑO DIRECTO cada tick a quien este dentro

  5  inflicts              le PEGA UNA CONDICION a quien este dentro. Lo unico
                           que sobrevive a que la situacion termine

===============================================================================
LA PLANTILLA
===============================================================================

    E(id="...", label="...",

      places=["mazmorra_mayor"],   # VACIO O AUSENTE = TODO EL MUNDO

      # --- CUANDO. Elige UNA forma, no se mezclan --------------------------
      #
      # (a) PERIODICA — por calendario, no hace falta encenderla
      every=34560, lasts=192, starts_at=9600,
      #
      # (b) EVENTUAL — cuando el mundo lo decide
      trigger={"expected_per_year": 3.0, "lasts_min": 200, "lasts_max": 800,
               "cooldown": 2880, "requires_situations": ["invierno"]},

      # --- QUE HACE --------------------------------------------------------
      gain_multipliers={"sustento": 0.5, "dinero": 1.4},
      effects={"salud": -0.003},
      inflicts={"situation": "herida", "marca": "quemadura", "chance": 0.02},
    )

===============================================================================
LAS SEIS REGLAS QUE EL PACK VIGILA
===============================================================================

1  TIENE QUE HACER ALGO. Al menos un canal, o no carga.

2  SOLO SE PUEDE INFLIGIR ALGO DECLARADO `personal`. Nadie lleva encima un
   invierno. Y ojo: TODO LO QUE SE INFLIJA NECESITA QUIEN LO CURE, o es una
   sentencia de muerte. Ver el bloque `condiciones`.

3  `chance` ES POR TICK, no por evento. Los efectos se aplican cada tick, asi
   que 1.0 en una ventisca heriria 96 veces al dia. Un numero bajo no es azar
   decorativo: es CUANTO AGUANTAS dentro.
      0.02  -> algo cada ~50 ticks   (media hora larga)
      0.005 -> cada ~200 ticks       (dos horas)

4  UNA EVENTUAL ACTIVA NECESITA `cooldown`. Sin el, lo que acaba de terminar se
   reenciende al tick siguiente.

5  `expected_per_year` ES LA TASA COMO SI ESTUVIERA SIEMPRE HABILITADA. Con
   `requires_situations` sale bastante mas raro que el numero escrito.

6  UNA PERIODICA NO PUEDE DURAR TANTO COMO SU CICLO, o el lugar seria
   inalcanzable para siempre.

===============================================================================
VOCABULARIO
===============================================================================

NECESIDADES   mana · sustento · descanso · dinero · vinculo · dominio · salud
FRANJAS       manana · tarde · noche
RELOJ         96 ticks = 1 dia · 34 560 ticks = 1 anyo

              1/anyo = every 34560       6/anyo = every 5760
              2/anyo = every 17280      12/anyo = every 2880
              4/anyo = every  8640      24/anyo = every 1440
                                        52/anyo = every  665

LUGARES (53), por familia:

  academia      academia_arcana · dormitorios_academia · gran_biblioteca
                archivo_prohibido · refectorio_academico · casa_de_pruebas
                campo_de_practica_elemental · torre_observacion
  ciudad        plaza_mayor · mercado_central · taberna_central · posada_central
                templo_central · salon_del_consejo · gremio_aventureros
                forjas · enfermeria · prision · puerta_norte · patio_de_duelos
  barrios       plaza_elfica/posada_elfica · plaza_enana/posada_enana
                plaza_gigante/salon_comunal_gigante/campo_gigante
                plaza_demihumana · plaza_portuaria/posada_marea
                posada_de_la_manada · templo_mareas · santuario_del_viento
  produccion    granja · mina · cantera · muelle · mercado_de_artefactos
                muelle_de_contrabandistas · arboleda_ancestral
  PELIGRO       mazmorra_menor/media/mayor · guarida_goblin · claro_del_ogro
                campamento_orco · entrada_catacumbas · catacumbas_profundas
                cripta_olvidada · nido_dragonewt · risco_de_los_majin
                linde_salvaje · campo_de_caza
"""


def E(**k):
    return k


# =============================================================================
# CONDICIONES — lo que la gente se lleva encima
#
# CADA UNA NECESITA QUIEN LA CURE. `vendarse` y `socorrer` (en `_acciones.py`)
# declaran cuales quitan; anyadir una condicion sin anyadirla ahi es condenar a
# quien la pille.
# =============================================================================

condiciones = [
    E(id="herida", label="herida", personal=True,
      effects={"salud": -0.0022}),
    # Mas lenta que una herida y NO se para sola. Da miedo por eso, no por el
    # numero: hay que ir a que te la quiten.
    E(id="fiebre", label="fiebre", personal=True,
      effects={"salud": -0.0009, "descanso": -0.0012}),
]


# =============================================================================
# FESTIVIDADES — periodicas, calendario fijo
#
# Todas suben `vinculo`: una fiesta es, mecanicamente, un sitio donde estar con
# gente rinde mas. `starts_at` escalonado para que no caigan todas encima.
# =============================================================================

festividades = [
    E(id="festival_cosecha", label="Festival de la Cosecha",
      places=["granja", "plaza_demihumana"],
      every=34560, lasts=288, starts_at=2400,
      gain_multipliers={"vinculo": 2.0, "sustento": 1.8}),

    E(id="noche_mareas", label="Noche de las Mareas",
      places=["templo_mareas", "plaza_portuaria"],
      every=8640, lasts=96, starts_at=1200,
      gain_multipliers={"vinculo": 1.7, "mana": 1.3}),

    E(id="vigilia_viento", label="Vigilia del Viento Eterno",
      places=["santuario_del_viento"],
      every=34560, lasts=192, starts_at=6000,
      gain_multipliers={"vinculo": 1.6, "mana": 1.5}),

    E(id="festival_yunque", label="Festival del Yunque",
      places=["plaza_enana", "forjas"],
      every=34560, lasts=192, starts_at=14000,
      gain_multipliers={"vinculo": 1.8, "dinero": 1.4}),

    E(id="ronda_gigantes", label="Ronda de los Gigantes",
      places=["plaza_gigante", "campo_gigante"],
      every=34560, lasts=192, starts_at=20000,
      gain_multipliers={"vinculo": 1.7, "dominio": 1.4}),

    E(id="solsticio_arcano", label="Solsticio Arcano",
      places=["campo_de_practica_elemental"],
      every=34560, lasts=288, starts_at=26000,
      gain_multipliers={"dominio": 2.2, "vinculo": 1.3}),

    E(id="feria_mercaderes", label="Feria de Mercaderes",
      places=["mercado_central"],
      every=8640, lasts=384, starts_at=4000,
      gain_multipliers={"dinero": 1.9, "vinculo": 1.4}),
]


# =============================================================================
# SOCIALES Y ACADEMICOS — frecuentes, escala pequenya
# =============================================================================

sociales = [
    # Semanal, y corta: una noche. Es el punto algido del chisme, asi que sube
    # `vinculo` fuerte — y cuando los rumores esten encendidos, este es el
    # evento que los va a mover.
    E(id="noche_corrillo", label="Noche de corrillo",
      places=["taberna_central", "posada_central", "posada_elfica",
              "posada_enana", "posada_marea", "posada_de_la_manada"],
      every=665, lasts=40, starts_at=300,
      gain_multipliers={"vinculo": 1.8}),

    E(id="refresco_contratos", label="Refresco de contratos",
      places=["gremio_aventureros"],
      every=1440, lasts=96, starts_at=200,
      gain_multipliers={"dinero": 1.6}),

    E(id="torneo_duelos", label="Torneo de duelos estudiantil",
      places=["patio_de_duelos"],
      every=2880, lasts=144, starts_at=800,
      gain_multipliers={"dominio": 1.7, "vinculo": 1.4}),

    E(id="concurso_caza", label="Concurso de caza",
      places=["campo_de_caza"],
      every=17280, lasts=192, starts_at=5000,
      gain_multipliers={"dinero": 1.5, "vinculo": 1.5, "dominio": 1.3}),

    E(id="examen_rango", label="Examen de rango",
      places=["torre_observacion", "campo_de_practica_elemental"],
      every=8640, lasts=192, starts_at=3000,
      gain_multipliers={"dominio": 1.9}),

    E(id="simposio_elemental", label="Simposio de teoria elemental",
      places=["gran_biblioteca"],
      every=17280, lasts=192, starts_at=9000,
      gain_multipliers={"dominio": 1.6, "vinculo": 1.2}),

    E(id="sesion_consejo", label="Sesion del consejo",
      places=["salon_del_consejo"],
      every=1440, lasts=96, starts_at=600,
      gain_multipliers={"vinculo": 1.4, "dinero": 1.2}),
]


# =============================================================================
# TRABAJO Y ECONOMIA
# =============================================================================

economia = [
    E(id="pesca_alta", label="Temporada de pesca alta",
      places=["muelle", "plaza_portuaria"],
      every=17280, lasts=1440, starts_at=7000,
      gain_multipliers={"dinero": 1.7, "sustento": 1.5}),

    E(id="vetas_ricas", label="Hallazgo de vetas ricas",
      places=["mina"],
      trigger={"expected_per_year": 1.0, "lasts_min": 960, "lasts_max": 2880,
               "cooldown": 5760},
      gain_multipliers={"dinero": 2.0}),

    # Una redada no cierra el sitio del todo —eso seria `closed_during` en el
    # mapa— pero lo deja sin nada que ofrecer mientras dura.
    E(id="redada_contrabando", label="Redada de contrabando",
      places=["muelle_de_contrabandistas"],
      trigger={"expected_per_year": 3.0, "lasts_min": 192, "lasts_max": 768,
               "cooldown": 2880},
      gain_multipliers={"dinero": 0.15}),

    E(id="huelga_canteros", label="Huelga de canteros",
      places=["cantera"],
      trigger={"expected_per_year": 0.2, "lasts_min": 960, "lasts_max": 2880,
               "cooldown": 8640},
      gain_multipliers={"dinero": 0.2, "vinculo": 1.5}),

    E(id="colapso_tunel", label="Colapso de tunel",
      places=["mina"],
      trigger={"expected_per_year": 0.5, "lasts_min": 96, "lasts_max": 480,
               "cooldown": 5760},
      gain_multipliers={"dinero": 0.3},
      effects={"salud": -0.004},
      inflicts={"situation": "herida", "marca": "aplastamiento",
                "chance": 0.02}),
]


# =============================================================================
# TRAGEDIAS Y ACCIDENTES
# =============================================================================

tragedias = [
    E(id="incendio_forjal", label="Incendio en El Forjal",
      places=["forjas", "plaza_enana"],
      trigger={"expected_per_year": 0.5, "lasts_min": 96, "lasts_max": 384,
               "cooldown": 5760},
      gain_multipliers={"dinero": 0.3},
      effects={"salud": -0.005},
      inflicts={"situation": "herida", "marca": "quemadura", "chance": 0.025}),

    E(id="naufragio", label="Naufragio",
      places=["muelle", "plaza_portuaria"],
      trigger={"expected_per_year": 1.0, "lasts_min": 192, "lasts_max": 576,
               "cooldown": 4320},
      gain_multipliers={"dinero": 0.4, "vinculo": 1.4}),

    # Sin plazo en la fiebre: no se pasa sola. El brote acaba, la enfermedad no.
    E(id="brote_enfermedad", label="Brote de enfermedad",
      places=["enfermeria", "plaza_mayor", "mercado_central", "posada_central"],
      trigger={"expected_per_year": 0.1, "lasts_min": 960, "lasts_max": 2880,
               "cooldown": 17280},
      gain_multipliers={"sustento": 0.7},
      # Un brote no reparte la misma fiebre a todos: a uno le toca pasarla en
      # cama dos dias y a otro casi lo mata.
      inflicts={"situation": "fiebre", "chance": 0.004,
                "gravedad_min": 0.4, "gravedad_max": 2.6}),

    E(id="incursion_orcos", label="Incursion de orcos",
      places=["linde_salvaje", "puerta_norte", "granja"],
      trigger={"expected_per_year": 1.5, "lasts_min": 192, "lasts_max": 768,
               "cooldown": 4320},
      gain_multipliers={"sustento": 0.5, "dominio": 1.5},
      effects={"salud": -0.003},
      inflicts={"situation": "herida", "marca": "flecha", "chance": 0.018}),
]


# =============================================================================
# SOBRENATURALES
# =============================================================================

sobrenatural = [
    E(id="pulso_linea_ley", label="Pulso de la linea ley",
      places=["catacumbas_profundas"],
      trigger={"expected_per_year": 2.0, "lasts_min": 96, "lasts_max": 480,
               "cooldown": 2880},
      # El mana rinde muchisimo y ademas te esta matando. Es la clase de trato
      # que separa al temerario del prudente sin escribir la regla.
      gain_multipliers={"mana": 2.5, "dominio": 1.8},
      effects={"salud": -0.006}),

    E(id="plaga_no_muertos", label="Plaga de no muertos menor",
      places=["mazmorra_menor", "mazmorra_media", "entrada_catacumbas"],
      trigger={"expected_per_year": 2.0, "lasts_min": 288, "lasts_max": 1152,
               "cooldown": 2880},
      gain_multipliers={"dinero": 0.6, "dominio": 1.5},
      inflicts={"situation": "herida", "marca": "mordisco", "chance": 0.012}),

    # LA BESTIA. Baja la recompensa, no la seguridad: el evento no prohibe nada,
    # deja la decision en cada cual. El temerario baja igual porque el rango
    # compensa; el prudente espera a que pase.
    E(id="la_bestia_despierta", label="La bestia ha despertado",
      places=["mazmorra_mayor", "catacumbas_profundas", "nido_dragonewt"],
      trigger={"expected_per_year": 2.0, "lasts_min": 480, "lasts_max": 1920,
               "cooldown": 2880},
      gain_multipliers={"dinero": 0.45, "dominio": 1.6},
      inflicts={"situation": "herida", "marca": "zarpazo", "chance": 0.015}),

    # Casi mitologico: una vez cada cincuenta anyos. Si alguna vez pasa, quien
    # lo viva lo va a recordar y contar durante el resto de su vida.
    E(id="aparicion_lich", label="Aparicion de un Lich",
      places=["mazmorra_mayor", "catacumbas_profundas"],
      trigger={"expected_per_year": 0.02, "lasts_min": 960, "lasts_max": 2880,
               "cooldown": 34560},
      gain_multipliers={"dinero": 0.2, "dominio": 2.5},
      effects={"salud": -0.012, "mana": -0.004},
      inflicts={"situation": "herida", "marca": "toque_del_lich",
                "chance": 0.05}),
]


# =============================================================================
# CATACLISMOS — el orden de magnitud de arriba
#
# Un cataclismo NO es una tragedia grande: es la unica clase de evento escrita
# para MATAR gente. Todo lo demas de este fichero hiere y se cura; esto abre un
# agujero en el censo.
#
# Por eso son casi miticos (una vez por generacion) y por eso la recompensa
# sube con el peligro: el evento no prohibe bajar, deja la decision en cada
# cual. Un cataclismo que solo hace danyo vaciaria las mazmorras, y entonces no
# mataria a nadie — que es exactamente lo contrario de para lo que existe.
# =============================================================================

cataclismos = [
    # LA RUPTURA. El evento que existe para probar que se puede morir.
    #
    # Comparado con `la_bestia_despierta`, que es el mas peligroso de arriba:
    #
    #                          chance   gravedad   danyo esperado por tick
    #   la_bestia_despierta      0.015    1.0             0.015
    #   ruptura_del_sello        0.09     3.0-9.0         0.540      36x
    #
    # Y ese 36x no es una escala mas: cruza el umbral de lo curable. Una herida
    # de gravedad 9 drena 0.0198 de salud por tick —de lleno a vacio en medio
    # dia— y `vendarse` quita 1.2, asi que hacen falta OCHO vendajes seguidos
    # mientras sigue sangrando. Ahi es donde `lethal_after` por fin cobra.
    #
    # La banda 3.0-9.0 es ancha a proposito: al mismo sitio y el mismo dia, uno
    # sale cojeando y a otro lo sacan muerto. Un valor fijo haria que la
    # supervivencia dependiera solo de quien estaba dentro.
    E(id="ruptura_del_sello", label="Ruptura del Sello Profundo",
      places=["mazmorra_menor", "mazmorra_media", "mazmorra_mayor",
              "guarida_goblin", "claro_del_ogro", "campamento_orco",
              "entrada_catacumbas", "catacumbas_profundas", "cripta_olvidada",
              "nido_dragonewt", "risco_de_los_majin"],
      trigger={"expected_per_year": 0.05, "lasts_min": 480, "lasts_max": 1440,
               "cooldown": 34560},
      # Lo que se saca tambien se multiplica. Es lo que hace que siga siendo una
      # decision y no un muro: el temerario baja, el prudente espera, y el motor
      # no tiene que saber cual es cual.
      gain_multipliers={"dinero": 3.0, "dominio": 3.0},
      effects={"salud": -0.010},
      inflicts={"situation": "herida", "marca": "desgarro", "chance": 0.09,
                "gravedad_min": 3.0, "gravedad_max": 9.0}),
]


# =============================================================================
# CLIMATICAS
# =============================================================================

clima = [
    E(id="tormenta_electrica", label="Tormenta electrica",
      places=["plaza_mayor", "puerta_norte", "plaza_elfica", "plaza_gigante",
              "campo_de_practica_elemental", "patio_de_duelos", "granja",
              "campo_de_caza", "linde_salvaje", "cantera"],
      trigger={"expected_per_year": 6.0, "lasts_min": 96, "lasts_max": 384,
               "cooldown": 1440},
      # No hace danyo: estropea lo que se hace al aire libre. Un mal rato, no
      # una tragedia — y el mundo necesita las dos cosas.
      gain_multipliers={"dominio": 0.6, "vinculo": 0.7, "descanso": 0.8}),

    E(id="marea_inusual", label="Fenomeno de marea inusual",
      places=["plaza_portuaria", "muelle", "templo_mareas"],
      every=17280, lasts=384, starts_at=11000,
      gain_multipliers={"dinero": 0.6, "mana": 1.6}),
]


eventos = (festividades + sociales + economia + tragedias + sobrenatural
           + cataclismos + clima)


# =============================================================================
# LO QUE FALTA — y por que
#
# Estos de tu lista NO se pueden escribir todavia. Cada uno con lo que necesita:
#
#   LE PASAN A UNA PERSONA, no a un lugar. Hoy una situacion alcanza un sitio, o
#   se pega a alguien POR API; no existe "el mundo elige a alguien":
#     · Colapso de mana (individual)       8/año
#     · Retroceso ambiental mayor          1/año
#     · Incidente en el archivo prohibido  0.3/año
#     · Invocacion demoniaca no autorizada 0.5/año
#
#   NECESITAN EDAD, que no existe. Nadie envejece:
#     · Dia de las Pruebas · Apertura de la ventana
#     · Expulsion por sobreentrenamiento infantil
#
#   NECESITAN NACIMIENTOS o CENSO QUE CREZCA:
#     · Nacimiento con multiafinidad · Visita de emisario externo
#
#   NECESITAN FACCIONES (RAIZ 5):
#     · Disputa entre casas nobles
#
#   NECESITAN OTRAS COSAS:
#     · Boda intercultural       `begin_relation` existe, pero nada la llama sola
#     · Avistamiento de vampiro  un RUMOR SIN HECHO: hoy un rumor es la copia de
#                                un recuerdo real, nadie puede propagar algo que
#                                no ocurrio
#     · Evolucion a majin        cambiar de raza al cruzar un rango
#     · Migracion de dragonewts  criaturas como poblacion
#     · Usuario de Realidad      trama, no frecuencia
# =============================================================================
