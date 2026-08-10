"""Genera el pack de la ciudad.

Dos poblaciones con vidas distintas en el mismo mapa, que es lo que separa esto
de la aldea: los alumnos viven dentro de la academia y los cazadores bajan a la
sima. El grafo hace casi todo el trabajo — la academia es autosuficiente y salir
cuesta, asi que el 80 % sale de la geografia y no de una regla.
"""

from pathlib import Path

import yaml

from _elenco import fichas  # type: ignore[import-not-found]
from _generador import poblar  # type: ignore[import-not-found]
from _grafo import LUGARES  # type: ignore[import-not-found]

S = Path(__file__).parent


def N(i, l, d, e, **k):
    return {"id": i, "label": l, "decay_per_tick": d, "urgency_exponent": e, **k}


# -----------------------------------------------------------------------------
# NECESIDADES
#
# Ocho que decaen y seis que solo suben. `ep` de la aldea NO viene: con cuatro
# habilidades seria el mismo numero contado dos veces.
# -----------------------------------------------------------------------------
needs = [
    N("sustento", "sustento", 0.007, 2.5, initial=0.75, base_weight=1.0, strain_weight=0.9),
    N("descanso", "descanso", 0.007, 2.2, initial=0.85, base_weight=1.0,
      strain_weight=1.0, max_debt=1.0),
    N("dinero", "monedas", 0.0016, 1.6, initial=0.50, base_weight=0.9),
    N("vinculo", "vinculo", 0.0040, 1.9, initial=0.60, base_weight=0.75,
      strain_weight=0.3, company_relief=0.0040),
    N("estimulo", "asombro", 0.0040, 1.7, initial=0.55, base_weight=0.65, strain_weight=0.4),
    N("provisiones", "despensa", 0.0012, 1.4, initial=0.70, base_weight=0.50),
    # El mana ambiental satura el nucleo solo. Conjurar y expoliar lo aceleran.
    N("nucleo", "estabilidad del nucleo", 0.0018, 2.0, initial=0.80,
      base_weight=0.85, strain_weight=0.8),
    # Lo que se trae de la sima. No es progresion: se gasta al tasarlo, y ese es
    # el bucle economico entero. Decae poquisimo porque el material se estropea.
    N("botin", "botin", 0.0004, 1.2, initial=0.0, base_weight=0.45,
      urgent_when_low=False),
    # Cuanto pasa desapercibido. No decae sola —la gente no te olvida por si
    # sola— pero dormir la repone un poco: un dia mas y ya nadie hablaba de ti.
    # Lo que la gasta es hacerse ver, y ahi esta toda la tension: lo que rinde
    # es publico. Que ser notado NO sea urgente es deliberado: es una
    # preferencia, no una emergencia, y tratarla como tal llenaria el mundo de
    # falsas alarmas para gente a la que le da igual.
    N("discrecion", "discrecion", 0.0, 1.5, initial=0.90, base_weight=0.35,
      urgent_when_low=False),

    # --- ejes que solo suben --------------------------------------------------
    N("ahorros", "ahorros", 0.0, 1.0, initial=0.0, base_weight=0.08, progression=True),
    # Antiguedad, no competencia. Sube yendo a clase y nada mas, y por eso NO
    # sirve para gatear la sima: un cazador que nunca piso la academia lo tiene
    # a cero y quedaria encerrado fuera de su propio oficio.
    N("curso", "curso", 0.0, 0.7, initial=0.0, base_weight=0.18, progression=True),
    N("arcano", "saber arcano", 0.0, 0.8, initial=0.05, base_weight=0.18, progression=True),
    N("armas", "armas", 0.0, 0.8, initial=0.05, base_weight=0.18, progression=True),
    N("agilidad", "agilidad", 0.0, 0.8, initial=0.05, base_weight=0.18, progression=True),
    N("temple", "temple", 0.0, 0.8, initial=0.05, base_weight=0.18, progression=True),
]


def T(i, l, **k):
    return {"id": i, "label": l, **k}


# -----------------------------------------------------------------------------
# RASGOS
#
# Tres familias. Los de siempre dicen que le importa a cada cual; el estilo dice
# que se le da bien aprender; el elemento dice que puede canalizar.
# -----------------------------------------------------------------------------
traits = [
    T("sociabilidad", "sociabilidad", need_weight_multipliers={"vinculo": 2.2, "descanso": 0.9}),
    T("laboriosidad", "laboriosidad", need_weight_multipliers={"dinero": 1.6, "descanso": 0.75}),
    T("hedonismo", "hedonismo", need_weight_multipliers={"estimulo": 2.4, "dinero": 0.7}),
    T("frugalidad", "frugalidad",
      need_weight_multipliers={"dinero": 1.5, "provisiones": 1.6, "estimulo": 0.6}),
    T("apego_al_hogar", "apego al hogar",
      need_weight_multipliers={"descanso": 1.35, "vinculo": 0.7}),
    T("impulsividad", "impulsividad",
      need_weight_multipliers={"nucleo": 0.60},
      temperament_multipliers={"temperature": 3.0, "loss_aversion": 0.55}),
    T("aguante", "aguante", temperament_multipliers={"critical_need_threshold": 0.60}),
    T("arraigo", "arraigo", temperament_multipliers={"travel_discount": 0.80}),
    T("nocturnidad", "nocturnidad", phase_shift=40),
    T("sueno_ligero", "sueno ligero", gain_multipliers={"descanso": 0.65}),
    # Quien esta hecho a dormir fuera. Compensa el 0.45 de la acampada: un
    # cazador curtido acampando repone casi como en una cama, y un alumno no.
    T("curtido", "curtido", gain_multipliers={"descanso": 1.9}),
    # A quien le importa no destacar. Sin este rasgo la discrecion no pesa nada
    # y el mundo se comporta igual que antes: es un eje que solo existe para
    # quien tiene algo que esconder.
    T("reservado", "reservado", need_weight_multipliers={"discrecion": 3.2}),
    # A quien todo se le da bien, en lo que sea que se le de. Se compone con el
    # estilo: el prodigio dice CUANTO y el estilo dice EN QUE.
    #
    # Fijate en el `curso`: el talento apenas lo acelera. Aprender magia deprisa
    # no te salta las clases, y ahi esta el arco del prodigio — brillante y sin
    # graduar, porque el titulo se gana asistiendo y no siendo listo.
    T("prodigio", "prodigio",
      gain_multipliers={"arcano": 1.8, "armas": 1.8, "agilidad": 1.8,
                        "temple": 1.8, "curso": 1.15}),
    T("ambicion", "ambicion",
      need_weight_multipliers={"curso": 2.2, "arcano": 1.8, "armas": 1.8}),

    # --- estilo: que se le da bien APRENDER ----------------------------------
    T("estilo_guerrero", "guerrero", gain_multipliers={"armas": 2.4, "temple": 1.8}),
    T("estilo_asesino", "asesino", gain_multipliers={"agilidad": 2.4, "armas": 1.6}),
    T("estilo_soporte", "soporte", gain_multipliers={"arcano": 2.4, "temple": 1.6}),

    # --- elemento: que puede canalizar. Solo abre puertas. --------------------
    T("elem_fuego", "afinidad de fuego"),
    T("elem_agua", "afinidad de agua"),
    T("elem_tierra", "afinidad de tierra"),
    T("elem_viento", "afinidad de viento"),

    # Quien esta matriculado. Abre las aulas Y el estipendio: el gremio paga a
    # los alumnos que patrocina, y por eso pueden vivir sin bajar a la sima.
    T("alumno", "alumno de la academia"),
    # Quien da las clases. Abre `dar_clase` y nada mas: un profesor es un
    # ciudadano con una llave distinta.
    T("profesor", "profesor de la academia"),
    # Se gana cumpliendo la meta de graduarse, y abre los contratos serios.
    T("graduado", "graduado"),
]


def A(**k):
    return k


HORARIO_DIA = {"manana": 1.2, "noche": 0.35}
HORARIO_NOCHE = {"manana": 0.35, "noche": 1.6}

# -----------------------------------------------------------------------------
# ACCIONES
# -----------------------------------------------------------------------------
actions = [
    # --- lo basico ------------------------------------------------------------
    A(id="dormir", label="dormir", duration_ticks=64, requires_affordance="cama",
      elastic={"need": "descanso", "per_tick": 0.033, "min_ticks": 4},
      satisfies={"descanso": 0.95}, effects={"nucleo": 0.10, "discrecion": 0.05},
      phase_multipliers={"noche": 1.5, "manana": 0.7, "tarde": 0.5}),
    # Se sirve a sus horas, y eso no es sabor: es lo que hace que el refectorio
    # arranque. Sin horario todos comian en la taberna —82 veces contra 41—
    # porque alli habia gente, y donde hay gente comer renta mas. Un bucle que
    # se realimenta solo y deja el comedor de la academia vacio para siempre.
    # Concentrar la hora hace que coincidan, y entonces el sitio se sostiene.
    A(id="rancho", label="comer el rancho", duration_ticks=4, requires_affordance="rancho",
      satisfies={"sustento": 0.70, "vinculo": 0.20},
      effects={"sustento": 0.70, "vinculo": 0.06},
      effects_per_company={"vinculo": 0.30}, saturation_gain=0.08,
      phase_multipliers={"manana": 2.2, "tarde": 1.6, "noche": 0.25}),
    A(id="comer_fuera", label="comer fuera", duration_ticks=5, requires_affordance="mesa",
      requires={"dinero": 0.12}, satisfies={"sustento": 0.70, "vinculo": 0.15},
      costs={"dinero": 0.25}, effects={"sustento": 0.70, "dinero": -0.07, "vinculo": 0.05},
      effects_per_company={"vinculo": 0.25, "dinero": -0.03}, saturation_gain=0.10),
    A(id="cocinar", label="cocinar", duration_ticks=6, requires_affordance="fogon",
      requires={"provisiones": 0.20}, satisfies={"sustento": 0.75},
      costs={"provisiones": 0.35}, effects={"sustento": 0.75, "provisiones": -0.20}),
    A(id="comprar_provisiones", label="comprar en el mercado", duration_ticks=5,
      requires_affordance="mercaduria", requires={"dinero": 0.18},
      satisfies={"provisiones": 0.80}, costs={"dinero": 0.60},
      effects={"provisiones": 0.80, "dinero": -0.18}, phase_multipliers=HORARIO_DIA),
    A(id="charlar", label="charlar", duration_ticks=5, requires_affordance="corrillo",
      requires_company=1, satisfies={"vinculo": 0.60}, costs={"discrecion": 0.06}, effects={"vinculo": 0.18, "discrecion": -0.015},
      effects_per_company={"vinculo": 0.50}, saturation_gain=0.14),
    A(id="beber", label="beber en la taberna", duration_ticks=8, requires_affordance="barril",
      requires={"dinero": 0.16}, satisfies={"estimulo": 0.60, "vinculo": 0.30},
      costs={"dinero": 0.55, "discrecion": 0.16}, effects={"estimulo": 0.30, "vinculo": 0.10, "dinero": -0.10, "discrecion": -0.015},
      effects_per_company={"vinculo": 0.35, "estimulo": 0.15, "dinero": -0.05},
      saturation_gain=0.16, phase_multipliers=HORARIO_NOCHE),
    A(id="tomar_el_aire", label="tomar el aire", duration_ticks=6, requires_affordance="aire",
      satisfies={"estimulo": 0.35}, effects={"estimulo": 0.26}, saturation_gain=0.25),
    A(id="meditar", label="asentar el nucleo", duration_ticks=10, requires_affordance="quietud",
      satisfies={"nucleo": 0.55, "estimulo": 0.05},
      effects={"nucleo": 0.38, "estimulo": 0.03}, saturation_gain=0.10),
    A(id="oficiar", label="oficiar en el templo", duration_ticks=12, requires_affordance="altar",
      satisfies={"nucleo": 0.75, "temple": 0.30, "vinculo": 0.10},
      effects={"nucleo": 0.60, "temple": 0.004, "vinculo": 0.06},
      effects_per_company={"vinculo": 0.20}, saturation_gain=0.10),
    A(id="velar_el_fuego", label="velar junto al fuego", duration_ticks=6,
      requires_affordance="hoguera", satisfies={"vinculo": 0.45, "temple": 0.20},
      effects={"vinculo": 0.15, "temple": 0.003},
      effects_per_company={"vinculo": 0.40}, saturation_gain=0.12,
      phase_multipliers=HORARIO_NOCHE),
    A(id="holgazanear", label="no hacer nada", duration_ticks=4,
      satisfies={"estimulo": 0.05}, effects={"estimulo": 0.03}),

    # --- la academia ----------------------------------------------------------
    # Paga. Sin estipendio el alumno se muere de hambre y acaba de cazador:
    # medido, Sira se fue a vivir al bosque el primer dia y no piso un aula.
    A(id="asistir_a_leccion", label="asistir a leccion", duration_ticks=12,
      requires_affordance="leccion", requires_traits={"alumno": 0.5},
      requires_company=1,
      satisfies={"curso": 0.55, "arcano": 0.25, "dinero": 0.45},
      costs={"descanso": 0.15},
      effects={"curso": 0.00038, "arcano": 0.004, "descanso": -0.06, "vinculo": 0.04,
               "dinero": 0.13},
      phase_multipliers={"manana": 1.6, "tarde": 1.1, "noche": 0.05}),
    A(id="dar_clase", label="dar clase", duration_ticks=14,
      requires_affordance="leccion", requires_traits={"profesor": 0.5},
      satisfies={"dinero": 0.60, "arcano": 0.25, "vinculo": 0.20},
      costs={"descanso": 0.20, "discrecion": 0.10},
      effects={"dinero": 0.22, "arcano": 0.002, "descanso": -0.09, "vinculo": 0.05,
               "discrecion": -0.025, "ahorros": 0.006},
      effects_per_company={"vinculo": 0.20},
      phase_multipliers={"manana": 1.7, "tarde": 1.1, "noche": 0.05}),
    A(id="estudiar", label="estudiar", duration_ticks=6, requires_affordance="archivo",
      satisfies={"arcano": 0.75}, costs={"descanso": 0.10},
      effects={"arcano": 0.011, "descanso": -0.04}, saturation_gain=0.08),
    A(id="entrenar", label="entrenar en la palestra", duration_ticks=10,
      requires_affordance="palestra", satisfies={"armas": 0.45, "agilidad": 0.35},
      costs={"descanso": 0.22, "discrecion": 0.80},
      effects={"armas": 0.006, "agilidad": 0.005, "descanso": -0.10, "discrecion": -0.20},
      saturation_gain=0.10),
    # La otra mitad del trato: rinde bastante menos y no te ve nadie. Sin esto,
    # querer pasar desapercibido solo se podria expresar como no entrenar.
    A(id="entrenar_a_solas", label="entrenar a solas", duration_ticks=12,
      requires_affordance="retiro", satisfies={"armas": 0.30, "agilidad": 0.25},
      costs={"descanso": 0.26},
      effects={"armas": 0.0035, "agilidad": 0.003, "descanso": -0.12,
               "discrecion": 0.01},
      saturation_gain=0.10),

    # --- los cuatro elementos. Mismo sitio, cuatro perfiles distintos. --------
    A(id="pyromancia", label="practicar pyromancia", duration_ticks=8,
      requires_affordance="palestra", requires_traits={"elem_fuego": 0.5},
      requires={"nucleo": 0.30},
      satisfies={"arcano": 0.60, "armas": 0.30}, costs={"nucleo": 0.60, "discrecion": 0.640},
      effects={"arcano": 0.009, "armas": 0.004, "nucleo": -0.26, "discrecion": -0.16}, saturation_gain=0.08),
    A(id="hidromancia", label="practicar hidromancia", duration_ticks=8,
      requires_affordance="palestra", requires_traits={"elem_agua": 0.5},
      satisfies={"arcano": 0.45, "nucleo": 0.20},
      costs={"discrecion": 0.016}, effects={"arcano": 0.006, "nucleo": 0.05, "discrecion": -0.004}, saturation_gain=0.08),
    A(id="geomancia", label="practicar geomancia", duration_ticks=10,
      requires_affordance="palestra", requires_traits={"elem_tierra": 0.5},
      satisfies={"arcano": 0.35, "temple": 0.45},
      costs={"discrecion": 0.080}, effects={"arcano": 0.004, "temple": 0.007, "nucleo": 0.03, "discrecion": -0.02}, saturation_gain=0.08),
    A(id="aeromancia", label="practicar aeromancia", duration_ticks=5,
      requires_affordance="palestra", requires_traits={"elem_viento": 0.5},
      satisfies={"arcano": 0.40, "agilidad": 0.35}, costs={"nucleo": 0.25, "discrecion": 0.016},
      effects={"arcano": 0.005, "agilidad": 0.006, "nucleo": -0.10, "discrecion": -0.004}, saturation_gain=0.08),

    # --- el gremio ------------------------------------------------------------
    A(id="tasar_botin", label="tasar el botin", duration_ticks=4,
      requires_affordance="tasacion", requires={"botin": 0.25},
      satisfies={"dinero": 0.85}, costs={"botin": 0.60, "discrecion": 0.12},
      effects={"dinero": 0.30, "botin": -0.25, "ahorros": 0.012, "discrecion": -0.012},
      phase_multipliers=HORARIO_DIA),
    A(id="contrato_del_gremio", label="contrato del gremio", duration_ticks=18,
      requires_affordance="contratos", requires_traits={"graduado": 0.9},
      requires={"nucleo": 0.35},
      satisfies={"dinero": 0.80, "estimulo": 0.25, "temple": 0.30},
      costs={"nucleo": 0.70, "descanso": 0.40, "discrecion": 0.28},
      effects={"dinero": 0.34, "nucleo": -0.30, "descanso": -0.18, "temple": 0.006,
               "ahorros": 0.010, "discrecion": -0.07},
      saturation_gain=0.08, phase_multipliers=HORARIO_DIA),

    # --- el bosque ------------------------------------------------------------
    A(id="caza_menor", label="cazar en el bosque", duration_ticks=12,
      requires_affordance="caza_menor",
      satisfies={"botin": 0.45, "estimulo": 0.20}, costs={"descanso": 0.25},
      effects={"botin": 0.22, "descanso": -0.11, "estimulo": 0.10, "armas": 0.003},
      saturation_gain=0.06),
    A(id="caza_mayor", label="batir la espesura", duration_ticks=16,
      requires_affordance="caza_mayor", requires={"armas": 0.25, "descanso": 0.30},
      satisfies={"botin": 0.70, "estimulo": 0.35},
      costs={"descanso": 0.45, "nucleo": 0.30, "discrecion": 0.12},
      effects={"botin": 0.38, "descanso": -0.20, "nucleo": -0.14, "estimulo": 0.16,
               "armas": 0.006, "temple": 0.004, "discrecion": -0.012},
      saturation_gain=0.06),

    # --- la sima, por profundidad ---------------------------------------------
    A(id="expoliar_cripta", label="expoliar la cripta", duration_ticks=12,
      requires_affordance="expolio_1", requires={"nucleo": 0.28, "descanso": 0.25},
      satisfies={"botin": 0.55, "estimulo": 0.30},
      costs={"nucleo": 0.55, "descanso": 0.40},
      effects={"botin": 0.26, "nucleo": -0.24, "descanso": -0.18, "estimulo": 0.14,
               "armas": 0.005, "temple": 0.004},
      saturation_gain=0.06),
    A(id="expoliar_galerias", label="expoliar las galerias", duration_ticks=16,
      requires_affordance="expolio_2", requires={"armas": 0.35, "nucleo": 0.40,
                                                 "descanso": 0.35},
      satisfies={"botin": 0.80, "estimulo": 0.45, "arcano": 0.25},
      costs={"nucleo": 0.85, "descanso": 0.60, "discrecion": 0.20},
      effects={"botin": 0.42, "nucleo": -0.38, "descanso": -0.30, "estimulo": 0.20,
               "armas": 0.008, "arcano": 0.005, "temple": 0.006, "discrecion": -0.02},
      saturation_gain=0.06),
    # Inabandonable: de ahi abajo no se sale a media faena. Es lo que produce la
    # deuda de sueno, y por eso hay que volver arriba a dormir dias.
    A(id="expoliar_corazon", label="bajar al corazon de la sima", duration_ticks=24,
      requires_affordance="expolio_3",
      requires={"armas": 0.60, "temple": 0.50, "nucleo": 0.60, "descanso": 0.50},
      interruptible=False,
      satisfies={"botin": 1.0, "estimulo": 0.70, "arcano": 0.40},
      costs={"nucleo": 1.0, "descanso": 0.95, "discrecion": 0.40},
      effects={"botin": 0.60, "nucleo": -0.58, "descanso": -0.48, "estimulo": 0.30,
               "armas": 0.012, "arcano": 0.008, "temple": 0.012, "ahorros": 0.015, "discrecion": -0.1},
      saturation_gain=0.05),
    # La salida de practica de los mayores. Misma cripta, pero la manda la
    # academia: la puerta es la ANTIGUEDAD, no la competencia.
    A(id="salida_de_practica", label="salida de practica", duration_ticks=12,
      requires_affordance="expolio_1", requires={"curso": 0.60, "descanso": 0.25},
      satisfies={"botin": 0.40, "curso": 0.30, "armas": 0.30},
      costs={"descanso": 0.35},
      effects={"botin": 0.18, "curso": 0.00032, "armas": 0.006, "descanso": -0.15,
               "temple": 0.003},
      saturation_gain=0.06),

    # --- oficios de ciudad ----------------------------------------------------
    A(id="trabajar_en_la_fragua", label="trabajar en la fragua", duration_ticks=16,
      requires_affordance="fragua", satisfies={"dinero": 0.50, "estimulo": 0.08},
      costs={"descanso": 0.30, "discrecion": 0.12},
      effects={"dinero": 0.26, "descanso": -0.13, "estimulo": 0.04, "ahorros": 0.006, "discrecion": -0.012},
      phase_multipliers=HORARIO_DIA),
    A(id="servir_en_la_taberna", label="servir en la taberna", duration_ticks=14,
      requires_affordance="barra", satisfies={"dinero": 0.34, "vinculo": 0.20},
      costs={"descanso": 0.22, "discrecion": 0.80},
      effects={"dinero": 0.16, "descanso": -0.10, "vinculo": 0.06, "ahorros": 0.004, "discrecion": -0.02},
      phase_multipliers=HORARIO_NOCHE),
]

# -----------------------------------------------------------------------------
# EL PORTE DEL GREMIO
#
# Una arista con precio no es un atajo, es un servicio. Deja en la boca de la
# sima en un tick; la vuelta se hace andando y gratis. Al que va justo de dinero
# el peaje le duele mucho mas, asi que el pobre camina y el holgado paga.
# -----------------------------------------------------------------------------
places = [dict(p) for p in LUGARES]
por_id = {p["id"]: p for p in places}
# Sitios donde uno se puede encerrar. La plaza tiene `quietud` pero esta llena
# de gente: meditar en publico vale, entrenar en secreto no.
for _sitio in ("aca_celdas", "barrio_alto", "templo"):
    por_id[_sitio]["affordances"] = [*por_id[_sitio]["affordances"], "retiro"]
por_id["gremio"]["neighbors"]["boca"] = 1
por_id["gremio"]["tolls"] = {"boca": {"dinero": 0.14}}

# -----------------------------------------------------------------------------
# ELENCO DE PRUEBA
#
# Ocho y no dos. Con dos agentes en veinticinco lugares no coinciden nunca, el
# vinculo no se puede llenar y las metricas miden la soledad del banco de
# pruebas en vez del mundo: medido, 62 % de abandonos que no eran del diseno.
# -----------------------------------------------------------------------------
def alumno(i, label, estilo, elemento, **rasgos):
    return {
        "id": i, "label": label, "home": "aca_celdas", "start_at": "aca_celdas",
        "traits": {"alumno": 1.0, estilo: 1.0, elemento: 1.0, **rasgos},
        "tastes": [{"target": "asistir_a_leccion", "multiplier": 2.2}],
        "goals": [{
            "id": "graduarse", "label": "graduarse", "need": "curso", "at_least": 0.95,
            "weight_multiplier": 2.0, "deadline": 96 * 900,
            "on_success": {"graduado": 1.0, "arraigo": -0.4, "ambicion": 0.3},
            "on_failure": {"ambicion": -0.5, "apego_al_hogar": 0.4},
        }],
    }


def cazador(i, label, estilo, elemento, casa, oficio, **rasgos):
    return {
        "id": i, "label": label, "home": casa, "start_at": casa,
        "traits": {"graduado": 1.0, "curtido": 0.8, estilo: 1.0, elemento: 1.0, **rasgos},
        "tastes": [{"target": oficio, "multiplier": 2.2},
                   {"target": "tasar_botin", "multiplier": 1.8}],
    }


agents = [
    # Kiara: el talento no se traduce en titulo. Su arcano corre cuatro veces mas
    # que el de nadie y su curso apenas, porque graduarse se gana yendo a clase.
    {
        "id": "kiara", "label": "Kiara Reynolds",
        "home": "aca_celdas", "start_at": "aca_celdas",
        "traits": {
            "alumno": 1.0, "estilo_soporte": 1.0, "elem_agua": 1.0,
            "prodigio": 0.9,
            "sociabilidad": 0.5, "laboriosidad": -0.4, "hedonismo": 0.2,
            "impulsividad": 0.1, "aguante": -0.2,
        },
        "tastes": [{"target": "estudiar", "multiplier": 2.5},
                   {"target": "entrenar", "multiplier": 0.3},
                   {"target": "asistir_a_leccion", "multiplier": 1.2}],
        "goals": [{
            "id": "graduarse", "label": "graduarse", "need": "curso",
            "at_least": 0.95, "weight_multiplier": 2.0, "deadline": 96 * 900,
            "on_success": {"graduado": 1.0, "arraigo": -0.4},
            # El prodigio que descubre que el talento no bastaba, y aprende a
            # trabajar. Es el final malo y es mejor que el bueno.
            "on_failure": {"laboriosidad": 0.6, "ambicion": 0.4, "hedonismo": -0.3},
        }],
    },
    # Aster: asesino de fuego, y esa combinacion es una contradiccion andante.
    # Su elemento es lo mas llamativo que hay y el quiere no destacar, asi que
    # la piromancia le cuesta el triple de discrecion que a nadie le importa.
    {
        "id": "aster", "label": "Aster Collins",
        "home": "aca_celdas", "start_at": "aca_celdas",
        "traits": {
            "alumno": 1.0, "estilo_asesino": 1.0, "elem_fuego": 1.0,
            "reservado": 0.9, "ambicion": 0.8,
            "sociabilidad": -0.4, "laboriosidad": 0.8, "hedonismo": -0.3,
            "frugalidad": 0.2, "apego_al_hogar": 0.3, "impulsividad": -0.6,
            "aguante": 0.9, "arraigo": 0.0,
        },
        "tastes": [{"target": "estudiar", "multiplier": 2.5},
                   {"target": "asistir_a_leccion", "multiplier": 1.4},
                   {"target": "beber", "multiplier": 0.1}],
        "goals": [{
            "id": "fuerza_suficiente", "label": "la fuerza que considera suficiente",
            "need": "agilidad", "at_least": 0.65, "weight_multiplier": 2.4,
            "deadline": 96 * 1800,
            # Deja de esconderse: lo unico que el motor entiende de "podra dejar
            # de ocultar parte de su capacidad".
            "on_success": {"reservado": -0.7, "sociabilidad": 0.4},
            "on_failure": {"aguante": -0.4, "ambicion": -0.3},
        }],
    },
    alumno("sira", "Sira", "estilo_soporte", "elem_agua",
           sociabilidad=0.4, ambicion=0.7, impulsividad=-0.4, arraigo=0.5),
    alumno("teo", "Teo", "estilo_guerrero", "elem_fuego",
           sociabilidad=0.2, ambicion=0.5, impulsividad=0.6, aguante=0.5),
    alumno("nima", "Nima", "estilo_asesino", "elem_viento",
           sociabilidad=-0.4, ambicion=0.8, impulsividad=0.3, nocturnidad=0.7),
    alumno("orso", "Orso", "estilo_soporte", "elem_tierra",
           sociabilidad=0.7, ambicion=0.2, hedonismo=0.5, aguante=-0.3),

    cazador("brac", "Brac", "estilo_guerrero", "elem_tierra", "barrio_bajo",
            "expoliar_cripta", laboriosidad=0.6, impulsividad=0.5, arraigo=-0.7,
            aguante=0.6, hedonismo=0.3),
    cazador("vela", "Vela", "estilo_asesino", "elem_viento", "barrio_bajo",
            "expoliar_cripta", sociabilidad=0.5, impulsividad=0.7, arraigo=-0.6,
            hedonismo=0.6, nocturnidad=0.5),
    cazador("hult", "Hult", "estilo_guerrero", "elem_fuego", "posada",
            "caza_menor", laboriosidad=0.4, frugalidad=0.6, arraigo=0.3, aguante=0.4),

    # No todo el mundo baja a la sima. La ciudad la sostienen tambien los que
    # nunca pisan el salvaje, y sin ellos no es una ciudad.
    {"id": "mira", "label": "Mira", "home": "barrio_alto", "start_at": "barrio_alto",
     "traits": {"sociabilidad": 0.8, "laboriosidad": 0.5, "arraigo": 0.8,
                "frugalidad": 0.4, "elem_agua": 1.0},
     "tastes": [{"target": "trabajar_en_la_fragua", "multiplier": 2.4},
                {"target": "aca_patio", "multiplier": 0.2}]},
]

agents += fichas()
agents += poblar()

# --- la ciudad que sostiene a la academia ------------------------------------
#
# Andamio, no elenco: con dieciocho alumnos y cuatro personas mas, el 82 % del
# mundo hace lo mismo y la diferenciacion se hunde a 0.66. No es colapso, es
# MONOCULTIVO — medido, entre alumnos da 0.547 y entre los demas 0.680.
#
# Y es lo que el propio diseno pedia: la ciudad vive del gasto de los cazadores
# y de gente de fondo. Sin ellos esto es un campus con una cueva al lado.
for _i, (_id, _lab, _casa, _oficio, _estilo, _elem, _extra) in enumerate([
    ("kell", "Kell", "barrio_bajo", "expoliar_cripta", "estilo_guerrero", "elem_fuego",
     dict(laboriosidad=0.5, impulsividad=0.4, arraigo=-0.6, aguante=0.5)),
    ("rhun", "Rhun", "barrio_bajo", "caza_menor", "estilo_asesino", "elem_viento",
     dict(sociabilidad=-0.5, frugalidad=0.7, arraigo=0.2, aguante=0.6)),
    ("dalia", "Dalia", "posada", "expoliar_cripta", "estilo_asesino", "elem_agua",
     dict(sociabilidad=0.6, hedonismo=0.7, impulsividad=0.6, nocturnidad=0.6)),
    ("bram", "Bram", "barrio_alto", "trabajar_en_la_fragua", "estilo_guerrero", "elem_tierra",
     dict(sociabilidad=0.3, laboriosidad=0.7, arraigo=0.8, frugalidad=0.5)),
    ("noe", "Noe", "barrio_bajo", "servir_en_la_taberna", "estilo_soporte", "elem_agua",
     dict(sociabilidad=0.9, hedonismo=0.4, arraigo=0.6, nocturnidad=0.5)),
]):
    _t = {_estilo: 1.0, _elem: 1.0, **_extra}
    if _oficio in ("expoliar_cripta", "caza_menor"):
        _t.update({"graduado": 1.0, "curtido": 0.8})
    agents.append({
        "id": _id, "label": _lab, "home": _casa, "start_at": _casa, "traits": _t,
        "tastes": [{"target": _oficio, "multiplier": 2.3},
                   {"target": "tasar_botin", "multiplier": 1.6}]
        if _oficio in ("expoliar_cripta", "caza_menor")
        else [{"target": _oficio, "multiplier": 2.3},
              {"target": "aca_patio", "multiplier": 0.3}],
    })

# ---------------------------------------------------------------------------
# Relaciones: quien es que de quien.
#
# La ciudad llevaba ciento veintisiete desconocidos que se iban conociendo desde
# cero cada corrida. Las primeras dos semanas de cualquier partida eran el mundo
# presentandose.
#
# El vocabulario es del pack, no del motor: aqui hay pareja, hermano y maestro
# porque esta ambientacion los tiene. Otra tendria vasallo, cofrade o deudor.
# ---------------------------------------------------------------------------
relations = [
    # Exclusiva y con suelo alto: es la que va a sostener la descendencia.
    {"id": "pareja", "label": "pareja", "symmetric": True, "exclusive": True,
     "regard_floor": 0.45, "company_multiplier": 2.0},
    # Sin suelo A PROPOSITO. Un hermano puede caerte fatal, y el pack tiene que
    # poder escribirlo; lo que no puede es dejar de ser tu hermano.
    {"id": "hermano", "label": "hermano", "symmetric": True,
     "company_multiplier": 1.5},
    {"id": "maestro", "label": "maestro de", "inverse": "discipulo",
     "regard_floor": 0.2, "company_multiplier": 1.4},
    {"id": "discipulo", "label": "discipulo de", "inverse": "maestro",
     "regard_floor": 0.3, "company_multiplier": 1.6},
]

# Y cenar en familia: la puerta dura. Sin una accion que EXIJA a los tuyos, la
# capa relacional solo tinta numeros y no se ve nada.
actions.append(A(
    id="cenar_con_los_tuyos", label="cenar con los tuyos", duration_ticks=5,
    requires_affordance="mesa", requires_relation="pareja",
    requires={"dinero": 0.10},
    satisfies={"vinculo": 0.9, "sustento": 0.7}, costs={"dinero": 0.22},
    effects={"vinculo": 0.30, "sustento": 0.45, "dinero": -0.06},
    effects_per_company={"vinculo": 0.10},
    phase_multipliers={"noche": 1.8, "tarde": 1.2},
))

# Quien es que de quien. Se declara UNA vez: el motor pone la otra mitad.
_lazos = {
    "brac": {"hermano": ["vela"]},          # los dos del barrio bajo, a la cripta
    "mira": {"pareja": ["bram"]},           # la fragua, en casa y en el trabajo
    "hult": {"pareja": ["dalia"]},          # posada
    "kell": {"hermano": ["rhun"]},
    "aster": {"discipulo": ["kiara"]},      # ella va por delante y el lo sabe
    "noe": {"hermano": ["dalia"]},
}
# Y el aprecio de partida, que es OTRA cosa: la relacion dice que son el uno del
# otro, esto dice como se llevan. Brac y Vela son hermanos y se detestan.
_aprecios = {
    "brac": {"vela": -0.55},
    "vela": {"brac": -0.45, "dalia": 0.5},
    "mira": {"bram": 0.75},
    "bram": {"mira": 0.7},
    "aster": {"kiara": 0.35},
    "kiara": {"aster": 0.1},
    "noe": {"dalia": 0.6, "hult": 0.3},
}
for _a in agents:
    if _a["id"] in _lazos:
        _a["relations"] = _lazos[_a["id"]]
    if _a["id"] in _aprecios:
        _a["initial_bonds"] = _aprecios[_a["id"]]

# Y la poblacion generada. Con seis parejas escritas a mano sobre ciento
# veintisiete habitantes la muestra no dice nada —medido: cuatro con pareja
# frente a ciento veintitres sin ella—, asi que la ciudad se empareja tambien.
#
# El emparejado es DETERMINISTA por posicion, sin sorteo: dos corridas con la
# misma semilla tienen que dar el mismo arbol. Y respeta el grupo: los adultos
# de fuera se emparejan entre ellos y los alumnos son hermanos entre ellos,
# porque un alumno interno casado con una tabernera no es esta ambientacion.
_ya_atados = {_id for _id in _lazos} | {
    _o for _v in _lazos.values() for _q in _v.values() for _o in _q
}


def _grupo(ficha):
    _t = ficha.get("traits", {})
    if _t.get("alumno"):
        return "alumno"
    return "profesor" if _t.get("profesor") else "fuera"


_libres = {"alumno": [], "profesor": [], "fuera": []}
for _a in agents:
    if _a["id"] not in _ya_atados:
        _libres[_grupo(_a)].append(_a)

_por_id = {_a["id"]: _a for _a in agents}

# Catorce parejas entre los de fuera. Se toman de los extremos hacia el centro
# para que no salgan siempre vecinos de la misma cohorte del generador.
_fuera = _libres["fuera"]
for _k in range(min(14, len(_fuera) // 2)):
    _uno, _otro = _fuera[_k], _fuera[-1 - _k]
    _uno.setdefault("relations", {}).setdefault("pareja", []).append(_otro["id"])
    _uno.setdefault("initial_bonds", {})[_otro["id"]] = 0.55
    _otro.setdefault("initial_bonds", {})[_uno["id"]] = 0.50

# Diez hermandades entre alumnos: familias que mandan a mas de un hijo.
_alu = _libres["alumno"]
for _k in range(0, min(20, len(_alu) - 1), 2):
    _uno, _otro = _alu[_k], _alu[_k + 1]
    _uno.setdefault("relations", {}).setdefault("hermano", []).append(_otro["id"])
    # Sin aprecio de partida: son hermanos, ya se veran. El suelo de `hermano`
    # es None a proposito, asi que estos empiezan de cero y se ganan lo que
    # sientan — que es la mitad de la gracia de separar las dos cosas.

# Y el claustro: cada profesor toma dos discipulos de los cursos altos.
_prof = _libres["profesor"]
_altos = [_a for _a in _alu if _a.get("initial_needs", {}).get("curso", 0.0) >= 0.4]
for _k, _p in enumerate(_prof):
    for _d in _altos[_k * 2: _k * 2 + 2]:
        _p.setdefault("relations", {}).setdefault("maestro", []).append(_d["id"])
        _p.setdefault("initial_bonds", {})[_d["id"]] = 0.3
        _d.setdefault("initial_bonds", {})[_p["id"]] = 0.35

# ---------------------------------------------------------------------------
# Situaciones: como esta el mundo.
#
# Un ano son doce meses de treinta dias: 360 * 96 = 34560 ticks. Las periodicas
# se cuelgan de ese ciclo y no guardan estado, igual que una franja del dia.
#
# Ninguna de las dos periodicas cae dentro de los primeros veintiun dias, que es
# lo que mide --health. Es a proposito: el contrato de salud describe una semana
# cualquiera de la ciudad, y una semana cualquiera no es la feria.
# ---------------------------------------------------------------------------
ANO = 360 * 96

situations = [
    # ESTACION. El cuarto ultimo del ano. Global: el invierno no es de un sitio.
    {"id": "invierno", "label": "invierno",
     "every": ANO, "lasts": 90 * 96, "starts_at": 270 * 96,
     # Lo que de verdad se recoge, no las ganas de recogerlo.
     "gain_multipliers": {"provisiones": 0.6}},

    # FIESTA. Una semana en primavera, y solo donde se celebra.
    {"id": "feria", "label": "feria de primavera",
     "every": ANO, "lasts": 7 * 96, "starts_at": 90 * 96,
     "places": ["plaza", "mercado", "taberna"]},

    # CLIMA. Eventual y local: se enciende cuando el narrador quiera.
    {"id": "ventisca", "label": "ventisca",
     "places": ["camino_bosque", "bosque", "espesura", "sendero", "boca"],
     "gain_multipliers": {"descanso": 0.5}},

    # PELIGRO. Eventual, en la sima. Cierra el fondo y el gremio paga mejor.
    {"id": "oleada", "label": "oleada de la sima",
     "places": ["boca", "cripta", "galerias", "nucleo_sima"]},
]

# Y como se nota cada una. Se declara aparte del catalogo de acciones para que
# se lea de un vistazo que hace cada situacion, en vez de repartido en treinta.
_efectos = {
    "caza_menor": {"invierno": 0.55},
    "caza_mayor": {"invierno": 0.5, "ventisca": 0.4},
    "tomar_el_aire": {"invierno": 0.45, "ventisca": 0.2, "feria": 1.6},
    "velar_el_fuego": {"invierno": 1.7, "ventisca": 2.0},
    "charlar": {"feria": 1.8},
    "beber": {"feria": 1.9},
    "comprar_provisiones": {"feria": 1.4, "invierno": 1.3},
    "expoliar_cripta": {"oleada": 0.5},
    "expoliar_galerias": {"oleada": 0.4},
    "salida_de_practica": {"oleada": 0.2},
    "contrato_del_gremio": {"oleada": 2.2},
}
for _a in actions:
    if _a["id"] in _efectos:
        _a["situation_multipliers"] = _efectos[_a["id"]]

# Puertas duras. La espesura con ventisca y el fondo de la sima con oleada no
# son menos atractivos: es que no se puede.
for _p in places:
    if _p["id"] == "espesura":
        _p["closed_during"] = ["ventisca"]
    if _p["id"] == "nucleo_sima":
        _p["closed_during"] = ["oleada"]

pack = {
    "id": "ciudad", "label": "La ciudad y la sima",
    "relations": relations,
    "situations": situations,
    "clock": {"minutes_per_tick": 15, "ticks_per_day": 96, "phases": [
        {"id": "manana", "label": "manana", "starts_at": 24},
        {"id": "tarde", "label": "tarde", "starts_at": 52},
        {"id": "noche", "label": "noche", "starts_at": 80},
    ]},
    # Treinta dias y no siete. Este mundo tiene ritmos mas lentos que la aldea
    # porque los ejes de progresion gatean contenido: en una semana no da tiempo
    # a que nadie llegue a las galerias ni a cuarto curso, y la mitad del pack
    # parece muerto sin estarlo.
    # UNA semilla, y no tres. Con ciento veintisiete habitantes una corrida son
    # doscientos cincuenta mil agente-ticks: la muestra ya es grande dentro de la
    # propia corrida, y tres semillas costarian dos minutos por cada `--health`.
    # El aviso de "una corrida es una muestra, no un resultado" se escribio para
    # mundos de diez.
    "health": {"days": 21, "seeds": [1312],
               "min_crisis": 0.05, "max_crisis": 0.30,
               "max_abort_ratio": 0.25, "max_transit": 0.25,
               "min_differentiation": 0.70,
               # El corazon pide armas 0.60 y la salida de practica cuarto curso:
               # meses, no semanas. Y holgazanear es la red de seguridad.
               "may_go_unused": ["holgazanear", "expoliar_corazon", "salida_de_practica"]},
    "tuning": {
        "travel_discount": 0.94, "candidate_pool": 3, "temperature": 0.12,
        "loss_aversion": 1.0, "saturation_recovery": 0.004, "novelty_weight": 0.6,
        "switch_cost": 0.8, "duration_discount": 0.995, "critical_need_threshold": 0.15,
        "sighting_horizon": 96, "learning_rate": 0.10,
        "bond_scale": 0.04, "bond_rate": 0.15, "bond_weight": 0.5,
        "companionship_weight": 0.4, "bond_fade": 0.9997, "bond_horizon": 2880,
        "strain_multipliers": {"temperature": 2.2, "travel_discount": 0.85,
                               "critical_need_threshold": 1.5},
    },
    "needs": needs, "traits": traits, "actions": actions,
    "places": places, "agents": agents,
}

(S / "pack.yaml").write_text(
    yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
)

from agora.engine.pack import PackError, load_pack  # noqa: E402

try:
    p = load_pack(S / "pack.yaml")
    print(f"CARGA OK: {p.label}  {len(p.places)} lugares, {len(p.actions)} acciones, "
          f"{len(p.agents)} agentes, {len(p.needs)} necesidades")
except PackError as e:
    print("RECHAZADO:\n", e)
