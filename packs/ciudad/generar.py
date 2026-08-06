"""Genera el pack de la ciudad.

Dos poblaciones con vidas distintas en el mismo mapa, que es lo que separa esto
de la aldea: los alumnos viven dentro de la academia y los cazadores bajan a la
sima. El grafo hace casi todo el trabajo — la academia es autosuficiente y salir
cuesta, asi que el 80 % sale de la geografia y no de una regla.
"""

from pathlib import Path

import yaml

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
      satisfies={"descanso": 0.95}, effects={"nucleo": 0.10},
      phase_multipliers={"noche": 1.5, "manana": 0.7, "tarde": 0.5}),
    A(id="rancho", label="comer el rancho", duration_ticks=4, requires_affordance="rancho",
      satisfies={"sustento": 0.70, "vinculo": 0.15},
      effects={"sustento": 0.70, "vinculo": 0.05},
      effects_per_company={"vinculo": 0.25}, saturation_gain=0.10),
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
      requires_company=1, satisfies={"vinculo": 0.60}, effects={"vinculo": 0.18},
      effects_per_company={"vinculo": 0.50}, saturation_gain=0.14),
    A(id="beber", label="beber en la taberna", duration_ticks=8, requires_affordance="barril",
      requires={"dinero": 0.16}, satisfies={"estimulo": 0.60, "vinculo": 0.30},
      costs={"dinero": 0.55}, effects={"estimulo": 0.30, "vinculo": 0.10, "dinero": -0.10},
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
      satisfies={"curso": 0.55, "arcano": 0.25, "dinero": 0.45},
      costs={"descanso": 0.15},
      effects={"curso": 0.006, "arcano": 0.004, "descanso": -0.06, "vinculo": 0.04,
               "dinero": 0.13},
      phase_multipliers={"manana": 1.6, "tarde": 1.1, "noche": 0.05}),
    A(id="estudiar", label="estudiar", duration_ticks=6, requires_affordance="archivo",
      satisfies={"arcano": 0.75}, costs={"descanso": 0.10},
      effects={"arcano": 0.011, "descanso": -0.04}, saturation_gain=0.08),
    A(id="entrenar", label="entrenar en la palestra", duration_ticks=10,
      requires_affordance="palestra", satisfies={"armas": 0.45, "agilidad": 0.35},
      costs={"descanso": 0.22}, effects={"armas": 0.006, "agilidad": 0.005, "descanso": -0.10},
      saturation_gain=0.10),

    # --- los cuatro elementos. Mismo sitio, cuatro perfiles distintos. --------
    A(id="pyromancia", label="practicar pyromancia", duration_ticks=8,
      requires_affordance="palestra", requires_traits={"elem_fuego": 0.5},
      requires={"nucleo": 0.30},
      satisfies={"arcano": 0.60, "armas": 0.30}, costs={"nucleo": 0.60},
      effects={"arcano": 0.009, "armas": 0.004, "nucleo": -0.26}, saturation_gain=0.08),
    A(id="hidromancia", label="practicar hidromancia", duration_ticks=8,
      requires_affordance="palestra", requires_traits={"elem_agua": 0.5},
      satisfies={"arcano": 0.45, "nucleo": 0.20},
      effects={"arcano": 0.006, "nucleo": 0.05}, saturation_gain=0.08),
    A(id="geomancia", label="practicar geomancia", duration_ticks=10,
      requires_affordance="palestra", requires_traits={"elem_tierra": 0.5},
      satisfies={"arcano": 0.35, "temple": 0.45},
      effects={"arcano": 0.004, "temple": 0.007, "nucleo": 0.03}, saturation_gain=0.08),
    A(id="aeromancia", label="practicar aeromancia", duration_ticks=5,
      requires_affordance="palestra", requires_traits={"elem_viento": 0.5},
      satisfies={"arcano": 0.40, "agilidad": 0.35}, costs={"nucleo": 0.25},
      effects={"arcano": 0.005, "agilidad": 0.006, "nucleo": -0.10}, saturation_gain=0.08),

    # --- el gremio ------------------------------------------------------------
    A(id="tasar_botin", label="tasar el botin", duration_ticks=4,
      requires_affordance="tasacion", requires={"botin": 0.25},
      satisfies={"dinero": 0.85}, costs={"botin": 0.60},
      effects={"dinero": 0.30, "botin": -0.25, "ahorros": 0.012},
      phase_multipliers=HORARIO_DIA),
    A(id="contrato_del_gremio", label="contrato del gremio", duration_ticks=18,
      requires_affordance="contratos", requires_traits={"graduado": 0.9},
      requires={"nucleo": 0.35},
      satisfies={"dinero": 0.80, "estimulo": 0.25, "temple": 0.30},
      costs={"nucleo": 0.70, "descanso": 0.40},
      effects={"dinero": 0.34, "nucleo": -0.30, "descanso": -0.18, "temple": 0.006,
               "ahorros": 0.010},
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
      costs={"descanso": 0.45, "nucleo": 0.30},
      effects={"botin": 0.38, "descanso": -0.20, "nucleo": -0.14, "estimulo": 0.16,
               "armas": 0.006, "temple": 0.004},
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
      costs={"nucleo": 0.85, "descanso": 0.60},
      effects={"botin": 0.42, "nucleo": -0.38, "descanso": -0.30, "estimulo": 0.20,
               "armas": 0.008, "arcano": 0.005, "temple": 0.006},
      saturation_gain=0.06),
    # Inabandonable: de ahi abajo no se sale a media faena. Es lo que produce la
    # deuda de sueno, y por eso hay que volver arriba a dormir dias.
    A(id="expoliar_corazon", label="bajar al corazon de la sima", duration_ticks=24,
      requires_affordance="expolio_3",
      requires={"armas": 0.60, "temple": 0.50, "nucleo": 0.60, "descanso": 0.50},
      interruptible=False,
      satisfies={"botin": 1.0, "estimulo": 0.70, "arcano": 0.40},
      costs={"nucleo": 1.0, "descanso": 0.95},
      effects={"botin": 0.60, "nucleo": -0.58, "descanso": -0.48, "estimulo": 0.30,
               "armas": 0.012, "arcano": 0.008, "temple": 0.012, "ahorros": 0.015},
      saturation_gain=0.05),
    # La salida de practica de los mayores. Misma cripta, pero la manda la
    # academia: la puerta es la ANTIGUEDAD, no la competencia.
    A(id="salida_de_practica", label="salida de practica", duration_ticks=12,
      requires_affordance="expolio_1", requires={"curso": 0.60, "descanso": 0.25},
      satisfies={"botin": 0.40, "curso": 0.30, "armas": 0.30},
      costs={"descanso": 0.35},
      effects={"botin": 0.18, "curso": 0.005, "armas": 0.006, "descanso": -0.15,
               "temple": 0.003},
      saturation_gain=0.06),

    # --- oficios de ciudad ----------------------------------------------------
    A(id="trabajar_en_la_fragua", label="trabajar en la fragua", duration_ticks=16,
      requires_affordance="fragua", satisfies={"dinero": 0.50, "estimulo": 0.08},
      costs={"descanso": 0.30},
      effects={"dinero": 0.26, "descanso": -0.13, "estimulo": 0.04, "ahorros": 0.006},
      phase_multipliers=HORARIO_DIA),
    A(id="servir_en_la_taberna", label="servir en la taberna", duration_ticks=14,
      requires_affordance="barra", satisfies={"dinero": 0.34, "vinculo": 0.20},
      costs={"descanso": 0.22},
      effects={"dinero": 0.16, "descanso": -0.10, "vinculo": 0.06, "ahorros": 0.004},
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

pack = {
    "id": "ciudad", "label": "La ciudad y la sima",
    "clock": {"minutes_per_tick": 15, "ticks_per_day": 96, "phases": [
        {"id": "manana", "label": "manana", "starts_at": 24},
        {"id": "tarde", "label": "tarde", "starts_at": 52},
        {"id": "noche", "label": "noche", "starts_at": 80},
    ]},
    # Veintiun dias y no siete. Este mundo tiene ritmos mas lentos que la aldea
    # porque los ejes de progresion gatean contenido: en una semana no da tiempo
    # a que nadie llegue a las galerias ni a cuarto curso, y la mitad del pack
    # parece muerto sin estarlo.
    "health": {"days": 21, "seeds": [1312, 7, 99],
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
