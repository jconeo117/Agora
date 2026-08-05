"""Genera el pack de la aldea desde el contrato del barrio."""

import json
import yaml
from pathlib import Path

S = Path(__file__).parent
b = yaml.safe_load(Path("packs/barrio/pack.yaml").read_text(encoding="utf-8"))
prof = json.loads((S / "profesiones.json").read_text())
"""Reparto sorteado con semilla 20260802, respetando las cuotas del diseno:
minimo 5 cazadores repartidos por genero, 1 herrero, 1 minero, 1 granjero y
2 sin profesion, que son los que cazan por su cuenta."""


def N(i, l, d, e, **k):
    return {"id": i, "label": l, "decay_per_tick": d, "urgency_exponent": e, **k}


needs = [
    N("sustento", "sustento", 0.007, 2.5, initial=0.75, base_weight=1.0, strain_weight=0.9),
    N("descanso", "descanso", 0.007, 2.2, initial=0.85, base_weight=1.0,
      strain_weight=1.0, max_debt=1.0),
    N("dinero", "monedas", 0.0016, 1.6, initial=0.55, base_weight=0.9),
    N("vinculo", "vinculo", 0.0040, 1.9, initial=0.60, base_weight=0.75,
      strain_weight=0.3, company_relief=0.0040),
    N("estimulo", "asombro", 0.0040, 1.7, initial=0.55, base_weight=0.65, strain_weight=0.4),
    N("provisiones", "despensa", 0.0012, 1.4, initial=0.70, base_weight=0.50),
    # El mana ambiental satura el nucleo SOLO, a todo el mundo. Cazar lo acelera.
    N("nucleo", "estabilidad del nucleo", 0.0018, 2.0, initial=0.80,
      base_weight=0.85, strain_weight=0.8),
    # Puntos de existencia: solo sube. Exponente por DEBAJO de 1 para que las
    # ganas de crecer se mantengan hasta cerca del tope, al reves que una
    # necesidad. Y `progression` lo saca del triaje: ser novato no es una
    # emergencia, o el aldeano de nivel bajo soltaria todo para ir a entrenar.
    N("ep", "puntos de existencia", 0.0, 0.75, initial=0.05,
      base_weight=0.10, progression=True),
    # Lo que se APARTA, distinto de lo que se tiene. `dinero` es un nivel
    # acotado a 1.0 que sube y baja con el gasto diario, asi que no sabe
    # expresar "juntar durante anos": medido, una meta de dinero al 0.92 se
    # cumplia el dia 0. Esto solo sube, y despacio.
    N("ahorros", "ahorros", 0.0, 1.0, initial=0.0, base_weight=0.08,
      progression=True),
]

traits = []
for t in b["traits"]:
    t = {k: v for k, v in t.items() if v}
    if t["id"] == "impulsividad":
        t["need_weight_multipliers"] = {"nucleo": 0.60}  # el temerario no cuida su nucleo
    traits.append(t)
# A que horas vive cada cual. Un solo eje: el madrugador es el nocturno con el
# signo cambiado, asi que no hace falta declarar `diurnidad`.
traits.append({"id": "nocturnidad", "label": "nocturnidad", "phase_shift": 40})
# Crecer no lo quiere todo el mundo igual. Sin este eje, EP es un motor comun
# que empuja a los diez en la misma direccion y les borra las diferencias:
# medido, la diferenciacion caia de 0.723 a 0.699 aun con el peso por los suelos.
traits.append({"id": "ambicion", "label": "ambicion",
               "need_weight_multipliers": {"ep": 2.2}})
AMBICION = {"arden": 0.8, "leonardo": 0.7, "corin": 0.6, "samantha": 0.5, "alexia": 0.4,
            "kiara": 0.2, "karla": -0.3, "tym": -0.4, "jack": -0.5, "linda": -0.6}
traits.append({"id": "sueno_ligero", "label": "sueno ligero",
               "gain_multipliers": {"descanso": 0.65}})
SUENO = {"samantha": 0.6, "corin": 0.4, "alexia": 0.3, "kiara": 0.0, "jack": -0.4,
         "linda": -0.5, "karla": 0.0, "tym": -0.3, "leonardo": -0.2, "arden": 0.2}
CRONOTIPO = {"samantha": 0.9, "corin": 0.8, "alexia": 0.6, "kiara": 0.0, "jack": 0.0,
             "linda": 0.0, "karla": 0.0, "tym": 0.0, "leonardo": 0.0, "arden": 0.0}


def A(**k):
    return k


actions = [
    # `satisfies` no menciona el nucleo y `effects` si: nadie se acuesta PARA
    # asentarse, pero dormir asienta. Es un beneficio que el agente no anticipa
    # y que `learn` no aprende, porque solo se aprende de lo que se perseguia.
    # Ademas es lo que le devuelve un hueco a la siesta: con el nucleo dentro,
    # dormir ganaba siempre y `descansar` no se usaba nunca.
    A(id="dormir", label="dormir", duration_ticks=64, requires_affordance="cama",
      elastic={"need": "descanso", "per_tick": 0.033, "min_ticks": 4},
      satisfies={"descanso": 0.95},
      effects={"nucleo": 0.10},
      ),
    A(id="meditar", label="asentar el nucleo", duration_ticks=10, requires_affordance="quietud",
      satisfies={"nucleo": 0.55, "estimulo": 0.05, "ep": 0.12},
      effects={"nucleo": 0.38, "estimulo": 0.03, "ep": 0.0015},
      saturation_gain=0.10),
    A(id="cocinar", label="cocinar", duration_ticks=6, requires_affordance="fogon",
      requires={"provisiones": 0.20}, satisfies={"sustento": 0.75},
      costs={"provisiones": 0.35}, effects={"sustento": 0.75, "provisiones": -0.20}),
    A(id="comer_en_la_taberna", label="comer en la taberna", duration_ticks=5,
      requires_affordance="mesa", requires={"dinero": 0.12},
      satisfies={"sustento": 0.70, "vinculo": 0.15}, costs={"dinero": 0.25},
      effects={"sustento": 0.70, "dinero": -0.07, "vinculo": 0.05},
      effects_per_company={"vinculo": 0.25, "dinero": -0.03}, saturation_gain=0.10),
    A(id="comprar_provisiones", label="comprar en la granja", duration_ticks=5,
      requires_affordance="mercaduria", requires={"dinero": 0.18},
      satisfies={"provisiones": 0.80}, costs={"dinero": 0.60},
      effects={"provisiones": 0.80, "dinero": -0.18}),
    # --- el oficio del gremio: paga mas, pero exige un nucleo entero ---------
    A(id="aceptar_una_mision", label="aceptar una mision del gremio", duration_ticks=20,
      requires_affordance="contratos", requires={"nucleo": 0.42},
      satisfies={"dinero": 0.75, "estimulo": 0.25, "ep": 0.30},
      costs={"nucleo": 0.80, "descanso": 0.45},
      effects={"dinero": 0.34, "nucleo": -0.42, "descanso": -0.20, "estimulo": 0.12,
               "ep": 0.006, "ahorros": 0.01},
      saturation_gain=0.08),
    # --- por tu cuenta: paga menos, nadie te pide permiso ni parte -----------
    A(id="cazar_por_tu_cuenta", label="cazar por tu cuenta", duration_ticks=16,
      requires_affordance="caza", requires={"nucleo": 0.36},
      satisfies={"dinero": 0.55, "estimulo": 0.30, "ep": 0.26},
      costs={"nucleo": 0.70, "descanso": 0.35},
      effects={"dinero": 0.24, "nucleo": -0.36, "descanso": -0.16, "estimulo": 0.14,
               "ep": 0.005, "ahorros": 0.007},
      saturation_gain=0.08),
    # Solo para quien ya se ha hecho un nombre. Nadie escribe "sube a 0.45": la
    # urgencia de crecer lo empuja sola, y un dia el gremio le abre esta puerta.
    A(id="mision_de_rango", label="mision de rango", duration_ticks=28,
      requires_affordance="contratos", requires={"nucleo": 0.60, "ep": 0.45},
      satisfies={"dinero": 1.0, "estimulo": 0.45, "ep": 0.5},
      costs={"nucleo": 0.95, "descanso": 0.55},
      effects={"dinero": 0.52, "nucleo": -0.58, "descanso": -0.28, "estimulo": 0.20,
               "ep": 0.012, "ahorros": 0.018},
      saturation_gain=0.06),
    # La via de crecer que NO depende del oficio. Sin ella, EP lo decide la
    # profesion y no el caracter: medido, los cinco cazadores llegaban al tope
    # en tres meses y la granjera se quedaba en 0.42, sin que la ambicion
    # cambiara nada. Entrenar es lo que le da al ambicioso una puerta propia.
    A(id="entrenar", label="entrenar", duration_ticks=10,
      requires_affordance="aire",
      satisfies={"ep": 0.45}, costs={"descanso": 0.20},
      effects={"ep": 0.006, "descanso": -0.09},
      saturation_gain=0.10),
    A(id="trabajar_en_la_herreria", label="trabajar en la herreria", duration_ticks=16,
      requires_affordance="fragua", satisfies={"dinero": 0.50, "estimulo": 0.08},
      costs={"descanso": 0.30}, effects={"dinero": 0.26, "descanso": -0.13, "estimulo": 0.04, "ahorros": 0.006}),
    A(id="trabajar_en_la_mina", label="trabajar en la mina", duration_ticks=18,
      requires_affordance="veta", satisfies={"dinero": 0.50}, costs={"descanso": 0.38},
      effects={"dinero": 0.25, "descanso": -0.17, "ahorros": 0.006}),
    A(id="trabajar_en_la_granja", label="trabajar en la granja", duration_ticks=14,
      requires_affordance="labranza", satisfies={"dinero": 0.35, "provisiones": 0.15},
      costs={"descanso": 0.22},
      effects={"dinero": 0.17, "descanso": -0.10, "provisiones": 0.10, "ahorros": 0.004}),
    A(id="servir_en_la_taberna", label="servir en la taberna", duration_ticks=14,
      requires_affordance="barra", satisfies={"dinero": 0.34, "vinculo": 0.20},
      costs={"descanso": 0.22}, effects={"dinero": 0.16, "descanso": -0.10, "vinculo": 0.06, "ahorros": 0.004}),
    A(id="charlar", label="charlar", duration_ticks=5, requires_affordance="corrillo",
      requires_company=1, satisfies={"vinculo": 0.60}, effects={"vinculo": 0.18},
      effects_per_company={"vinculo": 0.50}, saturation_gain=0.14),
    A(id="beber_en_la_taberna", label="beber en la taberna", duration_ticks=8,
      requires_affordance="barril", requires={"dinero": 0.16},
      satisfies={"estimulo": 0.60, "vinculo": 0.30}, costs={"dinero": 0.55},
      effects={"estimulo": 0.30, "vinculo": 0.10, "dinero": -0.10},
      effects_per_company={"vinculo": 0.35, "estimulo": 0.15, "dinero": -0.05},
      saturation_gain=0.16),
    A(id="tomar_el_aire", label="tomar el aire", duration_ticks=6, requires_affordance="aire",
      satisfies={"estimulo": 0.35}, effects={"estimulo": 0.26}, saturation_gain=0.25),
    A(id="holgazanear", label="no hacer nada", duration_ticks=4,
      satisfies={"estimulo": 0.05}, effects={"estimulo": 0.03}),
]


HORARIOS = {'trabajar_en_la_mina': {'noche': 0.35}, 'trabajar_en_la_herreria': {'noche': 0.35}, 'trabajar_en_la_granja': {'manana': 1.25, 'noche': 0.3}, 'servir_en_la_taberna': {'manana': 0.55, 'noche': 1.45}, 'comprar_provisiones': {'noche': 0.35}, 'aceptar_una_mision': {'manana': 1.15, 'noche': 0.8}, 'mision_de_rango': {'manana': 1.15, 'noche': 0.8}, 'cazar_por_tu_cuenta': {'noche': 1.25}, 'beber_en_la_taberna': {'manana': 0.4, 'noche': 1.7}, 'charlar': {'noche': 1.25}, 'meditar': {'noche': 1.2}, 'tomar_el_aire': {'manana': 1.2, 'noche': 0.8}, 'entrenar': {'manana': 1.2, 'noche': 0.7}, 'dormir': {'noche': 1.5, 'manana': 0.7, 'tarde': 0.5}}
for _a in actions:
    if _a["id"] in HORARIOS:
        _a["phase_multipliers"] = HORARIOS[_a["id"]]


def P(i, l, af, nb):
    return {"id": i, "label": l, "affordances": af, "neighbors": nb}


casas = {f"casa_{n:02d}": d for n, d in zip(range(1, 6), [1, 1, 2, 2, 2])}
places = [
    P("plaza", "la plaza", ["corrillo", "aire", "quietud"],
      {"taberna": 1, "posada": 1, "gremio": 2, "herreria": 2, "granja": 3, "mina": 4, **casas}),
    P("taberna", "la taberna", ["corrillo", "mesa", "barra", "barril"],
      {"plaza": 1, "posada": 1}),
    P("posada", "la posada grande", ["cama", "fogon", "mesa", "quietud"],
      {"plaza": 1, "taberna": 1}) | {"gain_multipliers": {"descanso": 1.15}},
    P("gremio", "el gremio de cazadores", ["contratos"], {"plaza": 2, "bosque": 4}),
    P("herreria", "la herreria", ["fragua"], {"plaza": 2, "mina": 3}) | {"open_during": ["manana", "tarde"]},
    P("mina", "la mina", ["veta"], {"plaza": 4, "herreria": 3}) | {"open_during": ["manana", "tarde"]},
    P("granja", "la granja", ["labranza", "mercaduria", "aire"], {"plaza": 3, "bosque": 3}),
    P("bosque", "el bosque magico", ["caza", "aire"], {"gremio": 4, "granja": 3}),
]
for n, d in zip(range(1, 6), [1, 1, 2, 2, 2]):
    places.append(P(f"casa_{n:02d}", f"la casa {n}", ["cama", "fogon", "quietud"], {"plaza": d}))

# Los arraigados tienen casa; los que no paran en ella comparten la posada.
hogar = {"linda": "casa_01", "tym": "casa_02", "karla": "casa_03",
         "arden": "casa_04", "kiara": "casa_05"}
for i in ("alexia", "samantha", "corin", "jack", "leonardo"):
    hogar[i] = "posada"

oficio = {"cazador": "aceptar_una_mision", "herrero": "trabajar_en_la_herreria",
          "minero": "trabajar_en_la_mina", "granjero": "trabajar_en_la_granja",
          "sin_profesion": "cazar_por_tu_cuenta"}

mapa = {"plaza": "plaza", "club": "taberna", "cafe": "taberna", "restaurante": "taberna",
        "fonda": "taberna", "mercado": "granja", "bazar": "granja", "oficina": "gremio",
        "darse_un_capricho": "beber_en_la_taberna", "descansar": "meditar",
        "cocinar": "cocinar", "charlar": "charlar",
        "trabajar_en_taller": None, "trabajar_en_oficina": None,
        "trabajar_en_almacen": None}

# Lo que quiere cada cual. Solo cinco tienen arco: alguien sin metas es
# legitimo, y un pueblo donde los diez persiguen algo no es un pueblo.
#
# El umbral ES el obstaculo. Puesto al alcance de la rutina normal no habrias
# escrito una meta, habrias escrito una rutina con nombre bonito.
METAS = {
    "arden": [{
        "id": "irse_del_pueblo", "label": "reunir lo suficiente para irse",
        "need": "ahorros", "at_least": 0.55, "weight_multiplier": 2.4,
        # Se fue, asi que ya no es el que no salia. Y deja de matarse a trabajar.
        "on_success": {"arraigo": -0.7, "laboriosidad": -0.3},
        # Ocho anos y no llego: deja de tener sentido madrugar.
        "on_failure": {"laboriosidad": -0.5, "apego_al_hogar": 0.5},
        "deadline": 96 * 240,
    }],
    "leonardo": [{
        "id": "maestria", "label": "que el gremio le tome en serio",
        "need": "ep", "at_least": 0.75, "weight_multiplier": 2.2,
        "on_success": {"sociabilidad": 0.3, "impulsividad": -0.2},
        "on_failure": {"aguante": -0.4},
        "deadline": 96 * 300,
    }],
    "corin": [{
        "id": "hacerse_un_nombre", "label": "dejar de ser el que no es nadie",
        "need": "ep", "at_least": 0.55, "weight_multiplier": 2.6,
        "on_success": {"ambicion": 0.4, "arraigo": 0.3},
        "on_failure": {"sociabilidad": -0.4, "hedonismo": 0.4},
        "deadline": 96 * 180,
    }],
    "samantha": [{
        "id": "salir_de_la_granja", "label": "juntar para no volver a la granja",
        "need": "ahorros", "at_least": 0.30, "weight_multiplier": 2.0,
        "on_success": {"laboriosidad": -0.4, "hedonismo": 0.3},
        "on_failure": {"impulsividad": -0.3, "apego_al_hogar": 0.4},
        "deadline": 96 * 200,
    }],
    "kiara": [{
        "id": "saldar_lo_que_debe", "label": "pagar lo que se gasto de mas",
        "need": "ahorros", "at_least": 0.20, "weight_multiplier": 2.8,
        "on_success": {"frugalidad": 0.4},
        "on_failure": {"frugalidad": -0.3, "hedonismo": 0.4},
        "deadline": 96 * 120,
    }],
}

agents = []
for a in b["agents"]:
    i = a["id"]
    local = dict(mapa)
    for k in range(1, 11):
        local[f"hab_{k:02d}"] = hogar[i]
    gustos = [{"target": oficio[prof[i]], "multiplier": 2.5}]
    vistos = {oficio[prof[i]]}
    for t in a.get("tastes", []):
        d = local.get(t["target"], t["target"])
        if d is None or d in vistos:
            continue
        vistos.add(d)
        gustos.append({"target": d, "multiplier": t["multiplier"]})
    agents.append({"id": i, "label": a["label"], "home": hogar[i], "start_at": hogar[i],
                   "traits": {**a["traits"], "nocturnidad": CRONOTIPO[i], "sueno_ligero": SUENO[i], "ambicion": AMBICION[i]}, "tastes": gustos, "initial_needs": {},
                   "goals": METAS.get(i, [])})

pack = {"id": "aldea", "label": "La aldea del bosque", "clock": {"minutes_per_tick": 15, "ticks_per_day": 96, "phases": [
            {"id": "manana", "label": "manana", "starts_at": 24},   # 06:00
            {"id": "tarde",  "label": "tarde",  "starts_at": 52},   # 13:00
            {"id": "noche",  "label": "noche",  "starts_at": 80},   # 20:00 -> 06:00
        ]},
        "health": {"days": 7, "seeds": [1312, 7, 99],
                   "min_crisis": 0.05, "max_crisis": 0.25,
                   "max_abort_ratio": 0.20, "max_transit": 0.25,
                   "min_differentiation": 0.70,
                   "may_go_unused": ["holgazanear", "mision_de_rango"]},
        "tuning": b["tuning"], "needs": needs, "traits": traits,
        "actions": actions, "places": places, "agents": agents}
(S / "pack.yaml").write_text(yaml.safe_dump(pack, allow_unicode=True, sort_keys=False),
                              encoding="utf-8")

from agora.engine.pack import PackError, load_pack

try:
    p = load_pack(S / "pack.yaml")
    print("CARGA OK:", p.label,
          f"{len(p.places)} lugares, {len(p.actions)} acciones, {len(p.agents)} agentes")
except PackError as e:
    print("RECHAZADO:\n", e)
