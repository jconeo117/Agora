"""Genera `packs/isla/pack.yaml`: la isla, un battle royale de 300 tributos.

Primera campaña de prueba (2026-10-10). Una isla enorme con la cornucopia en el
centro, cinco regiones en anillos y una zona que se cierra de fuera hacia
dentro. 300 tributos en 12 distritos de 25. No hay partos ni vejez: la partida
dura días. Todo es contenido: el motor no sabe qué es una isla ni un tributo.

Reproducible: todo sorteo sale de `blake2b(SEMILLA, ...)`.

    uv run python -I packs/isla/generar.py packs/isla/pack.yaml
"""

import hashlib
import random
import sys
from pathlib import Path

import yaml

SEMILLA = 2026_10_10
DIA = 96
DISTRITOS = 12
POR_DISTRITO = 25


def rng(*clave: object) -> random.Random:
    material = "\x1f".join(str(c) for c in (SEMILLA, *clave)).encode()
    return random.Random(int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big"))


# --- El mapa -------------------------------------------------------------------

REGIONES = {
    "selva":   {"label": "la selva",   "lugares": ["espesura", "claro", "arroyo", "matorral", "ceiba", "helechal", "barranco", "lianas"],
                "afford": [["forraje", "escondite"], ["forraje", "aire"], ["agua", "forraje"], ["escondite", "refugio"]]},
    "montana": {"label": "la montaña", "lugares": ["cueva", "manantial", "risco", "paso", "canchal", "cornisa", "grieta", "cumbre"],
                "afford": [["refugio", "escondite"], ["refugio"], ["vigia"], ["vigia", "escondite"]]},
    "playa":   {"label": "la playa",   "lugares": ["cala", "dunas", "rompiente", "manglar", "arrecife", "faro", "muelle roto", "naufragio"],
                "afford": [["refugio"], ["forraje"], ["forraje", "aire"], ["agua", "escondite"]]},
    "cienaga": {"label": "la ciénaga", "lugares": ["juncal", "charca", "isleta", "niebla", "pantano", "turbera", "carrizal", "cieno"],
                "afford": [["escondite"], ["agua"], ["refugio", "escondite"], ["forraje"]]},
    "ruinas":  {"label": "las ruinas", "lugares": ["plaza rota", "torre", "sótano", "pozo", "templo caído", "muralla", "almacén", "cripta"],
                "afford": [["botin_menor"], ["vigia"], ["refugio", "escondite"], ["botin_menor", "escondite"]]},
}
ORDEN = list(REGIONES)

# Cómo es cada tipo de lugar (unidad 17): lo único con lo que el narrador puede
# ambientar. Solo atmósfera, nunca recursos: lo que ofrece un sitio sale de
# `afford`, que no depende del nombre, y un «manantial» sin agua descrito con
# agua prometería al jugador algo que el menú no le da.
DESCRIPCION = {
    "espesura": "Árboles muy juntos y un aire húmedo que huele a hoja podrida.",
    "claro": "Un hueco abierto al cielo en la selva; la hierba llega a la rodilla.",
    "arroyo": "Un cauce de piedras con musgo; se oye agua cerca.",
    "matorral": "Arbustos espinosos y densos que arañan al pasar.",
    "ceiba": "Un árbol enorme con raíces como paredes; bajo sus ramas no crece nada.",
    "helechal": "Helechos más altos que una persona, empapados.",
    "barranco": "Una grieta de tierra roja con las paredes cubiertas de raíces.",
    "lianas": "Cortinas de lianas que cuelgan de las copas y se mueven sin viento.",
    "cueva": "Una boca estrecha en la ladera; dentro, el aire es frío y quieto.",
    "manantial": "Rocas lisas y verdes, y el rumor de agua bajo la piedra.",
    "risco": "Una cornisa de piedra desde la que se ve media isla.",
    "paso": "Un sendero estrecho entre dos paredes de roca.",
    "canchal": "Piedra suelta que resbala a cada paso.",
    "cornisa": "Un saliente de roca sobre el vacío, barrido por el viento.",
    "grieta": "Una hendidura en la montaña donde apenas cabe un cuerpo.",
    "cumbre": "La cima pelada; el viento no para y todo queda abajo.",
    "cala": "Una ensenada pequeña entre rocas, con arena gris.",
    "dunas": "Montes de arena blanda que cambian de forma con el viento.",
    "rompiente": "Las olas revientan contra rocas negras; el ruido lo tapa todo.",
    "manglar": "Raíces retorcidas sobre agua salobre, y mosquitos.",
    "arrecife": "Roca y coral a ras de agua, cortantes bajo los pies.",
    "faro": "Una torre blanca apagada, con la puerta arrancada.",
    "muelle roto": "Tablones podridos que se adentran en el mar y se acaban de golpe.",
    "naufragio": "El casco de un barco varado, medio enterrado en la arena.",
    "juncal": "Juncos más altos que una persona, que se cierran detrás de ti.",
    "charca": "Agua quieta entre el barro; el suelo cede bajo los pies.",
    "isleta": "Un montículo de tierra firme rodeado de fango.",
    "niebla": "Una bruma espesa que no deja ver a cinco pasos.",
    "pantano": "Agua negra y árboles muertos; burbujea de vez en cuando.",
    "turbera": "Tierra esponjosa y negra que huele a humo viejo.",
    "carrizal": "Cañas secas que crujen con cualquier movimiento.",
    "cieno": "Lodo hasta los tobillos, y un olor dulzón a podrido.",
    "plaza rota": "Losas levantadas por raíces y una fuente seca en el centro.",
    "torre": "Una torre de piedra sin tejado, con escaleras que suben a medias.",
    "sótano": "Un hueco bajo las ruinas, cerrado y con eco.",
    "pozo": "Un brocal de piedra entre muros caídos.",
    "templo caído": "Columnas derribadas y un tejado a medias sobre la piedra rota.",
    "muralla": "Un lienzo de muralla en pie, con huecos donde faltan piedras.",
    "almacén": "Estanterías vencidas y cajas reventadas por el tiempo.",
    "cripta": "Nichos vacíos en la pared y un frío que no se va.",
}
ANILLOS = {1: 4, 2: 6, 3: 8}            # lugares por región y anillo; el 3 es la costa


def lugar_id(region: str, anillo: int, i: int) -> str:
    return f"{region}_{anillo}_{i}"


def mapa() -> tuple[list[dict], dict[int, list[str]]]:
    lugares: dict[str, dict] = {}
    por_anillo: dict[int, list[str]] = {0: [], 1: [], 2: [], 3: []}
    vecinos: dict[str, dict[str, int]] = {}

    def unir(a: str, b: str, t: int) -> None:
        vecinos.setdefault(a, {})[b] = t
        vecinos.setdefault(b, {})[a] = t

    # El lago de la cornucopia: la arena final necesita agua, o los últimos
    # mueren todos de sed el mismo día y nadie gana (sonda 2 de la v1).
    lugares["cornucopia"] = {"id": "cornucopia", "label": "la cornucopia",
                             "description": "Un cuerno de metal enorme junto a un lago, rodeado de cajas y mochilas.",
                             "affordances": ["botin", "aire", "agua"], "tags": ["centro"],
                             # Cuarenta armas y veinte armaduras (16a): pocas,
                             # porque si todos saquean armados, el arma no
                             # distingue a nadie (medido: 107-128 saqueos). Y la
                             # comida y las vendas (16b), que no se reponen aquí.
                             "items": {"cuchillo": 16, "lanza_corta": 14, "hacha": 10,
                                       "cuero": 12, "cota": 8, "racion": 150, "venda": 60}}
    por_anillo[0].append("cornucopia")
    for d in range(1, DISTRITOS + 1):
        pid = f"pedestal_{d}"
        lugares[pid] = {"id": pid, "label": f"el pedestal {d}", "affordances": ["aire"], "tags": ["pedestal"],
                        "description": "Una plataforma de metal a unos pasos de la cornucopia, sobre hierba pisoteada."}
        por_anillo[0].append(pid)
        unir(pid, "cornucopia", 1)
    for r, region in enumerate(ORDEN):
        datos = REGIONES[region]
        for anillo, n in ANILLOS.items():
            for i in range(n):
                lid = lugar_id(region, anillo, i)
                nombre = datos["lugares"][(i + anillo) % len(datos["lugares"])]
                aff = datos["afford"][(i + 2 * anillo) % len(datos["afford"])]
                lugares[lid] = {"id": lid, "label": f"{nombre} ({datos['label']}, {['', 'interior', 'media', 'costa'][anillo]})",
                                "description": DESCRIPCION[nombre],
                                "affordances": list(aff), "tags": [region, f"anillo_{anillo}"]}
                # Lo que hay en el suelo de cada sitio (16b): el forraje se repone
                # solo (6 raciones al día por sitio); lo rebuscado no vuelve.
                if "forraje" in aff:
                    lugares[lid]["items"] = {"racion": 20}
                    lugares[lid]["regrow"] = {"racion": {"max": 20, "every": 16}}
                if "botin_menor" in aff:
                    lugares[lid]["items"] = {"racion": 4, "venda": 2}
                por_anillo[anillo].append(lid)
                if i > 0:                                    # el camino dentro del anillo
                    unir(lid, lugar_id(region, anillo, i - 1), 2)
                if anillo > 1:                               # hacia dentro
                    prev = ANILLOS[anillo - 1]
                    unir(lid, lugar_id(region, anillo - 1, min(prev - 1, i * prev // n)), 3)
        # los pedestales que miran a esta región
        for d in range(1, DISTRITOS + 1):
            if (d - 1) * len(ORDEN) // DISTRITOS == r:
                unir(f"pedestal_{d}", lugar_id(region, 1, (d - 1) % ANILLOS[1]), 2)
        # una región toca a la siguiente en cada anillo
        siguiente = ORDEN[(r + 1) % len(ORDEN)]
        for anillo, n in ANILLOS.items():
            unir(lugar_id(region, anillo, n - 1), lugar_id(siguiente, anillo, 0), 3)
    for lid, v in vecinos.items():
        lugares[lid]["neighbors"] = dict(sorted(v.items()))
    return list(lugares.values()), por_anillo


# --- La zona que se cierra --------------------------------------------------------

ZONA = {3: 2, 2: 4, 1: 5}                 # anillo -> día en que se cierra
FINAL = 6
AGOTADA = 5
"""Día en que la cornucopia deja de dar botín (sigue el agua del lago): sin
esto era un refugio con curas ilimitadas y en el final hacía falta una docena
de ataques por muerte (calibración del 2026-10-13)."""
"""Día en que se cierran también los pedestales y solo queda la cornucopia: el
final que obliga a encontrarse. Sin él, con la zona sola, el día 7 quedaban
15-32 vivos repartidos entre cornucopia y pedestales (calibración del
2026-10-13)."""


# --- Los tributos ------------------------------------------------------------------

POTENCIALES = ("fuerza", "agilidad", "ingenio", "instinto", "voluntad", "presencia", "resonancia")
CARACTER = ("audacia", "impulsividad", "calculo", "sociabilidad", "aprension", "codicia", "crueldad", "pereza")

# El sesgo del distrito: unos crían luchadores, otros supervivientes.
SESGO = {
    1: {"fuerza": 0.15, "agilidad": 0.10, "arrojo": 0.15, "piedad": -0.15},
    2: {"fuerza": 0.20, "voluntad": 0.05, "arrojo": 0.15, "piedad": -0.10},
    3: {"ingenio": 0.20, "fuerza": -0.05},
    4: {"agilidad": 0.15, "instinto": 0.05, "arrojo": 0.10},
    5: {"ingenio": 0.15, "voluntad": 0.05},
    6: {"voluntad": 0.10, "piedad": 0.05},
    7: {"fuerza": 0.10, "instinto": 0.05},
    8: {"presencia": 0.10, "agilidad": 0.05},
    9: {"instinto": 0.10, "voluntad": 0.05},
    10: {"fuerza": 0.10, "voluntad": 0.10},
    11: {"instinto": 0.15, "agilidad": 0.05, "piedad": 0.10},
    12: {"instinto": 0.10, "voluntad": 0.10, "fuerza": -0.05, "piedad": 0.10},
}
RANGO_DE_COMBATE = {1: (2, 4), 2: (2, 4), 4: (1, 3)}   # los demás, de 0 a 1

SILABAS = ["ka", "ren", "to", "mi", "sa", "lo", "vi", "dan", "el", "ia", "mor", "tu", "ze", "ra", "fin", "ga",
           "ly", "or", "ves", "na", "bel", "co", "dri", "hal"]


def nombre(r: random.Random) -> str:
    return "".join(r.choice(SILABAS) for _ in range(r.choice((2, 2, 3)))).capitalize()


def tributos(por_anillo: dict[int, list[str]]) -> list[dict]:
    refugios_interiores = por_anillo[1]
    agentes = []
    usados: set[str] = set()
    for d in range(1, DISTRITOS + 1):
        ids_distrito = []
        fichas = []
        for k in range(POR_DISTRITO):
            r = rng("tributo", d, k)
            nom = nombre(r)
            while nom in usados:
                nom = nombre(r)
            usados.add(nom)
            aid = f"{nom.lower()}_d{d}"
            sesgo = SESGO[d]
            rasgos = {p: round(min(1.0, max(0.0, r.gauss(0.5 + sesgo.get(p, 0.0), 0.18))), 2) for p in POTENCIALES}
            for p in ("piedad", "arrojo"):
                rasgos[p] = round(min(1.0, max(0.0, r.gauss(0.5 + sesgo.get(p, 0.0), 0.2))), 2)
            for c in r.sample(CARACTER, r.choice((1, 2, 2, 3))):
                rasgos[c] = round(r.uniform(-0.9, 0.95), 2)
            lo, hi = RANGO_DE_COMBATE.get(d, (0, 1))
            fichas.append({
                "id": aid,
                "label": f"{nom}, del distrito {d}",
                "home": refugios_interiores[(d * 7 + k) % len(refugios_interiores)],
                "start_at": f"pedestal_{d}",
                "edad_inicial": DIA * 360 * r.randint(14, 19),
                "initial_rank": {"combate": r.randint(lo, hi)},
                "traits": rasgos,
            })
            ids_distrito.append(aid)
        for f in fichas:
            otros = [o for o in ids_distrito if o != f["id"]]
            f["relations"] = {"del_distrito": otros}
            r = rng("vinculos", f["id"])
            f["initial_bonds"] = {o: round(r.uniform(0.15, 0.45), 2) for o in sorted(r.sample(otros, 6))}
        agentes += fichas
    return agentes


def pack() -> dict:
    lugares, por_anillo = mapa()
    for anillo, dia in ZONA.items():
        for lid in por_anillo[anillo]:
            next(p for p in lugares if p["id"] == lid)["closed_during"] = [f"zona_{anillo}"]
    pedestales = [lid for lid in por_anillo[0] if lid != "cornucopia"]
    for lid in pedestales:
        next(p for p in lugares if p["id"] == lid)["closed_during"] = ["zona_final"]
    rasgo = lambda i, label, **canales: {"id": i, "label": label, **canales}  # noqa: E731
    return {
        "id": "isla",
        "label": "La isla",
        "clock": {"minutes_per_tick": 15, "ticks_per_day": DIA, "phases": [
            {"id": "manana", "label": "mañana", "starts_at": 24},
            {"id": "tarde", "label": "tarde", "starts_at": 52},
            {"id": "noche", "label": "noche", "starts_at": 80}]},
        "health": {"days": 6, "seeds": [1312], "max_crisis": 0.95, "max_transit": 0.6,
                   "min_differentiation": 0.2, "may_go_unused": ["dormir_al_raso", "golpe_mortal", "atacar_con_sana", "luchar_a_muerte", "vigilar"]},
        "tuning": {"travel_discount": 0.94, "candidate_pool": 3, "temperature": 0.12, "loss_aversion": 1.0,
                   "saturation_recovery": 0.004, "novelty_weight": 0.3, "switch_cost": 0.8,
                   "duration_discount": 0.995, "critical_need_threshold": 0.15, "sighting_horizon": 192,
                   "lod_focus_radius": 4, "lod_menu_radius": 4, "learning_rate": 0.1, "bond_scale": 0.04,
                   "bond_rate": 0.15, "bond_weight": 0.5, "companionship_weight": 0.3, "company_scale": 8.0,
                   "bond_fade": 0.9997, "bond_horizon": 2880,
                   "strain_multipliers": {"temperature": 2.2, "travel_discount": 0.85, "critical_need_threshold": 1.5},
                   "memory_capacity": 120, "memory_scale": 1.0, "memory_fade": 0.9995, "regard_scale": 0.5,
                   "regret_weight": 0.35, "regret_scale": 0.5, "fear_weight": 0.5, "fear_scale": 0.5,
                   "grief_scale": 0.5, "rumor_rate": 0.1, "rumor_decay": 0.5},
        "needs": [
            {"id": "sustento", "label": "comida", "decay_per_tick": 0.006, "urgency_exponent": 2.4, "initial": 0.7, "base_weight": 1.0, "strain_weight": 0.8},
            {"id": "agua", "label": "agua", "decay_per_tick": 0.007, "urgency_exponent": 2.6, "initial": 0.8, "base_weight": 1.1, "strain_weight": 0.9, "lethal_after": 192},
            {"id": "descanso", "label": "descanso", "decay_per_tick": 0.006, "urgency_exponent": 2.2, "initial": 0.8, "base_weight": 1.0, "strain_weight": 1.0, "max_debt": 1.0},
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0, "urgency_exponent": 2.6, "initial": 1.0, "base_weight": 1.0, "lethal_after": 8},
            {"id": "seguridad", "label": "seguridad", "decay_per_tick": 0.004, "urgency_exponent": 1.8, "initial": 0.5, "base_weight": 0.9, "strain_weight": 0.6},
            {"id": "vinculo", "label": "compañía", "decay_per_tick": 0.003, "urgency_exponent": 1.6, "initial": 0.45, "base_weight": 0.6, "strain_weight": 0.3, "company_relief": 0.002},
            # Sale de lo que se lleva (16b): una ración vale 0.1 y una venda 0.15.
            # No decae: se gasta o se pierde, y por eso no puede bajar sola.
            {"id": "suministros", "label": "suministros", "decay_per_tick": 0.0, "urgency_exponent": 1.5, "initial": 0.2, "base_weight": 0.6,
             "from_items": {"comida": 0.1, "venda": 0.15}},
            {"id": "combate", "label": "combate", "decay_per_tick": 0.0, "initial": 0.0, "progression": True, "rank_slowdown": 1.0, "base_weight": 0.3, "urgency_exponent": 1.0},
        ],
        "traits": [
            *(rasgo(p, f"potencial de {p}") for p in ("resonancia",)),
            # La fuerza pesa sin el jugador delante (I-008): escala el daño que hace,
            # vía `quita_por_pericia: combate`, y el que recibe, vía el temple.
            rasgo("fuerza", "potencial de fuerza", gain_multipliers={"combate": 4.0}, cost_multipliers={"salud": 0.55}),
            rasgo("agilidad", "potencial de agilidad", gain_multipliers={"combate": 1.6}, cost_multipliers={"descanso": 0.85, "seguridad": 0.85}),
            rasgo("ingenio", "potencial de ingenio", gain_multipliers={"suministros": 1.35}),
            rasgo("instinto", "potencial de instinto", gain_multipliers={"seguridad": 1.3}),
            rasgo("voluntad", "potencial de voluntad", cost_multipliers={"descanso": 0.85, "salud": 0.9}),
            rasgo("presencia", "potencial de presencia", gain_multipliers={"vinculo": 1.3}),
            rasgo("piedad", "piedad", need_weight_multipliers={"combate": 0.35}),
            rasgo("arrojo", "arrojo", need_weight_multipliers={"combate": 1.8, "seguridad": 0.75}),
            rasgo("audacia", "audacia", temperament_multipliers={"critical_need_threshold": 0.6}),
            rasgo("impulsividad", "impulsividad", temperament_multipliers={"temperature": 2.8}),
            rasgo("calculo", "cálculo", temperament_multipliers={"loss_aversion": 1.9}),
            rasgo("sociabilidad", "sociabilidad", need_weight_multipliers={"vinculo": 2.1}, temperament_multipliers={"companionship_weight": 2.4}),
            rasgo("aprension", "aprensión", need_weight_multipliers={"salud": 2.2, "seguridad": 1.5}),
            rasgo("codicia", "codicia", need_weight_multipliers={"suministros": 2.0}),
            rasgo("crueldad", "crueldad", need_weight_multipliers={"combate": 2.2}),
            rasgo("pereza", "pereza", need_weight_multipliers={"descanso": 1.8}),
        ],
        "actions": acciones(),
        "items": ITEMS,
        "relations": [{"id": "del_distrito", "label": "del mismo distrito", "symmetric": True, "regard_floor": 0.15, "company_multiplier": 1.3}],
        "places": lugares,
        "agents": tributos(por_anillo),
        "situations": [
            {"id": "herida", "label": "herida", "personal": True, "visible": True, "effects": {"salud": -0.0025},
             "content": ["violencia"]},
            # Periódicas con un ciclo de un año: empiezan el día de su anillo y
            # duran más que cualquier partida. Es la forma de decir «a partir
            # del día N, para siempre» con lo que el motor ya sabe.
            *({"id": f"zona_{anillo}", "label": f"la zona se cierra (anillo {anillo})", "starts_at": dia * DIA,
               "every": 360 * DIA, "lasts": 300 * DIA, "places": por_anillo[anillo], "effects": {"salud": -0.012, "seguridad": -0.01}}
              for anillo, dia in ZONA.items()),
            {"id": "zona_final", "label": "la zona se cierra (solo queda la cornucopia)", "starts_at": FINAL * DIA,
             "every": 360 * DIA, "lasts": 300 * DIA, "places": pedestales, "effects": {"salud": -0.012, "seguridad": -0.01}},
            # El final: un battle royale tiene que acabar con un solo ganador, y
            # los dos últimos se aprecian 1.0 y atacar exige aprecio <= 0.05: sin
            # esto dormían juntos para siempre (calibración I-011). La condición
            # es la puerta de `luchar_a_muerte`: antes de esto, no está en el menú.
            {"id": "sin_tregua", "label": "sin tregua", "personal": True, "effects": {"seguridad": -0.005}},
            {"id": "arena_final", "label": "ya no hay treguas", "starts_at": FINAL * DIA,
             "every": 360 * DIA, "lasts": 300 * DIA, "places": ["cornucopia"],
             "inflicts": {"situation": "sin_tregua", "lasts": 300 * DIA}},
            {"id": "cornucopia_agotada", "label": "la cornucopia está vacía", "starts_at": AGOTADA * DIA,
             "every": 360 * DIA, "lasts": 300 * DIA, "places": ["cornucopia"], "gain_multipliers": {"suministros": 0.05}},
        ],
        "newcomer": {"home": por_anillo[1][0], "start_at": "pedestal_12", "edad_inicial": DIA * 360 * 17},
        # Lo que se lleva al empezar: dos raciones, los 0.2 de antes (16b).
        "starting_items": {"racion": 2},
        "voice": {
            "identity_traits": [],
            "character_traits": list(CARACTER) + ["piedad", "arrojo"],
            "fallback": {"amable": ["Aún sigo aquí.", "Mientras respire, hay partida."],
                         "seco": ["Sigue andando.", "No tengo nada para ti."],
                         "hostil": ["Un paso más y te arrepientes.", "Lárgate."],
                         "triste": ["Ya no queda casi nadie.", "No sé cuánto aguanto."],
                         "asustado": ["No me hagas daño.", "Aquí no, por favor."]}},
    }


# Lo que se lleva (16a). Cuatro tipos de arma y dos de armadura: el enlace
# `reglas/base.yaml` dice qué pieza de la ficha es cada uno. Sin arco: el
# enlace no tiene arma de proyectil ni competencia para ella, y eso se decide
# aparte (ver el contrato, §A.9).
ITEMS = [
    {"id": "cuchillo", "label": "cuchillo", "slot": "arma", "gains": {"combate": 1.3},
     "narration": "un cuchillo"},
    {"id": "lanza_corta", "label": "lanza corta", "slot": "arma", "gains": {"combate": 1.5},
     "narration": "una lanza corta"},
    {"id": "hacha", "label": "hacha", "slot": "arma", "gains": {"combate": 1.8},
     "narration": "un hacha de batalla"},
    {"id": "cuero", "label": "armadura de cuero", "slot": "armadura", "costs": {"salud": 0.85},
     "narration": "una armadura de cuero"},
    {"id": "cota", "label": "cota de malla", "slot": "armadura", "costs": {"salud": 0.7},
     "narration": "una cota de malla"},
    # Lo que se come y se cura (16b). Sin `slot`: no se llevan puestos, se gastan.
    {"id": "racion", "label": "ración", "slot": "ninguno", "tags": ["comida"],
     "narration": "una ración de comida"},
    {"id": "venda", "label": "venda", "slot": "ninguno", "tags": ["venda"],
     "narration": "una venda"},
]

# Cómo pediría cada acción un jugador (unidad 14). Las lee el intérprete de la
# prosa, no el motor. Escritas antes que el banco de intenciones y sin copiar
# sus frases: si coincidieran, el banco mediría la lista y no al intérprete.
EJEMPLOS = {
    "dormir": ["duermo a cubierto", "busco refugio para pasar la noche", "me acuesto bajo techo"],
    "dormir_al_raso": ["me echo a dormir aquí", "duermo al aire libre", "echo una cabezada"],
    "beber": ["bebo", "tengo sed", "relleno la cantimplora"],
    "recolectar": ["busco comida", "recojo frutos y raíces", "cazo algo", "pesco"],
    "comer": ["como algo", "saco comida de la mochila", "tengo hambre"],
    "saquear_cornucopia": ["cojo lo que pueda de la cornucopia", "voy a por las armas",
                           "saqueo las provisiones del cuerno"],
    "registrar": ["registro lo que hay en el suelo", "cojo lo que hay tirado", "miro qué hay aquí"],
    "saquear_armadura": ["me pongo una armadura", "busco protección", "cojo algo para el pecho"],
    "coger_provisiones": ["cojo comida", "busco provisiones", "cojo lo que pueda de comer"],
    "coger_vendas": ["cojo vendas", "busco vendas", "necesito algo para las heridas"],
    "rebuscar": ["rebusco entre los escombros", "registro las ruinas", "busco algo útil"],
    "esconderse": ["me escondo", "me oculto", "me pongo a cubierto sin que me vean"],
    "vigilar": ["vigilo", "subo a un sitio alto a otear", "monto guardia"],
    "luchar_a_muerte": ["lucho a muerte con", "solo puede quedar uno", "acabo con esto de una vez"],
    "aliarse": ["me alío con", "le propongo ir juntos", "hago un pacto con"],
    "atacar": ["ataco a", "le pego", "me lanzo contra", "peleo con"],
    "atacar_con_sana": ["le ataco sin piedad", "voy a por todas contra", "le doy con toda mi rabia"],
    "golpe_mortal": ["remato a", "acabo con", "le doy el golpe de gracia", "mato al herido"],
    "saquear": ["le registro", "le quito sus cosas", "le robo al herido"],
    "curarse": ["me curo", "me vendo las heridas", "me limpio la herida"],
    "socorrer": ["ayudo a", "curo las heridas de", "socorro a"],
}


# Cómo cuenta el narrador cada acción (unidad 17): tú / otro / otro sobre ti.
# Con la etiqueta, «rematar a un herido contra Zetu», los dos 70B del banco
# entendieron «un herido que luchaba contra Zetu».
NARRACION = {
    "dormir": ("duermes a cubierto", "{a} duerme a cubierto", None),
    "dormir_al_raso": ("duermes al raso", "{a} duerme al raso", None),
    "beber": ("bebes", "{a} bebe", None),
    "recolectar": ("buscas algo que comer", "{a} busca algo que comer", None),
    "comer": ("comes de lo que llevas", "{a} come de lo que lleva", None),
    "saquear_cornucopia": ("rebuscas en las cajas de la cornucopia", "{a} rebusca en las cajas de la cornucopia", None),
    "registrar": ("registras lo que hay en el suelo", "{a} registra lo que hay en el suelo", None),
    "saquear_armadura": ("te pones una armadura de la cornucopia", "{a} se pone una armadura de la cornucopia", None),
    "coger_provisiones": ("coges comida de lo que queda aquí", "{a} coge comida de lo que queda aquí", None),
    "coger_vendas": ("coges vendas de lo que queda aquí", "{a} coge vendas de lo que queda aquí", None),
    "rebuscar": ("rebuscas entre los escombros", "{a} rebusca entre los escombros", None),
    "esconderse": ("te escondes", "{a} se esconde", None),
    "vigilar": ("vigilas desde lo alto", "{a} vigila desde lo alto", None),
    "luchar_a_muerte": ("te lanzas a matar a {o}", "{a} se lanza a matar a {o}", "{a} se lanza a matarte"),
    "aliarse": ("haces un pacto con {o}", "{a} pacta con {o}", "{a} te propone un pacto"),
    "atacar": ("atacas a {o}", "{a} ataca a {o}", "{a} te ataca"),
    "atacar_con_sana": ("te lanzas sin piedad contra {o}", "{a} se lanza sin piedad contra {o}",
                        "{a} se lanza sin piedad contra ti"),
    "golpe_mortal": ("rematas a {o}, que estaba herido", "{a} remata a {o}, que estaba herido",
                     "{a} va a rematarte"),
    "saquear": ("le quitas lo que lleva a {o}, herido", "{a} le quita lo que lleva a {o}, herido",
                "{a} te quita lo que llevas"),
    "curarse": ("te curas las heridas", "{a} se cura las heridas", None),
    "socorrer": ("curas las heridas de {o}", "{a} cura las heridas de {o}", "{a} te cura las heridas"),
}
CONTENIDO = {"luchar_a_muerte": ["violencia", "muerte"], "atacar": ["violencia"], "atacar_con_sana": ["violencia"],
             "golpe_mortal": ["violencia", "muerte"], "saquear": ["violencia"]}


def acciones() -> list[dict]:
    def narracion(i: str) -> dict:
        tu, otro, a_ti = NARRACION[i]
        return {"you": tu, "them": otro, **({"at_you": a_ti} if a_ti else {})}
    return [{**a, "examples": EJEMPLOS[a["id"]], "narration": narracion(a["id"]),
             **({"content": CONTENIDO[a["id"]]} if a["id"] in CONTENIDO else {})}
            for a in _acciones()]


def _acciones() -> list[dict]:
    herida = {"situation": "herida", "marca": "cuerpo", "gravedad_min": 0.4, "gravedad_max": 1.0, "lasts": 2 * DIA}
    return [
        # Dormir deja desprevenido: quien te ataca dormido te pilla por sorpresa
        # (D-165, unidad 13).
        {"id": "dormir", "label": "dormir a cubierto", "duration_ticks": 32, "interruptible": True, "vulnerable": True,
         "requires_affordance": "refugio", "elastic": {"min_ticks": 12, "need": "descanso", "per_tick": 0.03},
         "phase_multipliers": {"noche": 1.9, "manana": 0.5, "tarde": 0.4}, "satisfies": {"descanso": 1.0},
         "effects": {"seguridad": 0.05}},
        {"id": "dormir_al_raso", "label": "dormir al raso", "duration_ticks": 16, "interruptible": True, "vulnerable": True,
         "satisfies": {"descanso": 0.5}, "effects": {"descanso": 0.2, "seguridad": -0.08}, "costs": {"seguridad": 0.3}},
        {"id": "beber", "label": "beber", "duration_ticks": 2, "requires_affordance": "agua",
         "satisfies": {"agua": 1.0}, "effects": {"agua": 0.35}},
        # Los suministros salen de lo que se lleva (16b): recoger comida es coger
        # una ración del suelo, y comerla es gastarla. Ya no hay efecto sobre el eje.
        {"id": "recolectar", "label": "buscar comida", "duration_ticks": 8, "requires_affordance": "forraje",
         "requires_item": {"where": "suelo", "tags": ["comida"]}, "takes_item": {"where": "suelo", "tags": ["comida"]},
         "satisfies": {"suministros": 1.0, "sustento": 0.3}, "effects": {"sustento": 0.05, "descanso": -0.05},
         "costs": {"descanso": 0.2}},
        {"id": "comer", "label": "comer de lo que lleva", "duration_ticks": 2,
         "requires_item": {"where": "encima", "tags": ["comida"]}, "consumes": {"where": "encima", "tags": ["comida"]},
         "satisfies": {"sustento": 1.0}, "effects": {"sustento": 0.4}},
        # La cornucopia se parte en dos (16b): «el mejor» de la 16a es el de mayor
        # `gains`, y quien va por comida no debe llevarse un hacha.
        {"id": "saquear_cornucopia", "label": "saquear la cornucopia", "duration_ticks": 4, "requires_affordance": "botin",
         # Solo mientras haya un arma tirada: sin la puerta, `combate` (que empieza
         # en 0 y es la necesidad más urgente) la elegiría con las cajas vacías.
         "requires_item": {"where": "suelo", "slot": "arma"},
         "satisfies": {"combate": 1.0}, "effects": {"seguridad": -0.2}, "costs": {"seguridad": 0.4}, "situation_multipliers": {"cornucopia_agotada": 0.1},
         "takes_item": {"where": "suelo", "slot": "arma"}},
        {"id": "saquear_armadura", "label": "ponerse una armadura de la cornucopia", "duration_ticks": 4, "requires_affordance": "botin",
         "requires_item": {"where": "suelo", "slot": "armadura"},
         "satisfies": {"combate": 1.0}, "effects": {"seguridad": -0.2}, "costs": {"seguridad": 0.4}, "situation_multipliers": {"cornucopia_agotada": 0.1},
         "takes_item": {"where": "suelo", "slot": "armadura"}},
        {"id": "coger_provisiones", "label": "coger comida de la cornucopia", "duration_ticks": 4, "requires_affordance": "botin",
         "requires_item": {"where": "suelo", "tags": ["comida"]}, "takes_item": {"where": "suelo", "tags": ["comida"]},
         "satisfies": {"suministros": 1.0}, "effects": {"seguridad": -0.2}, "costs": {"seguridad": 0.4}, "situation_multipliers": {"cornucopia_agotada": 0.1}},
        {"id": "coger_vendas", "label": "coger vendas de la cornucopia", "duration_ticks": 4, "requires_affordance": "botin",
         "requires_item": {"where": "suelo", "tags": ["venda"]}, "takes_item": {"where": "suelo", "tags": ["venda"]},
         "satisfies": {"suministros": 1.0}, "effects": {"seguridad": -0.2}, "costs": {"seguridad": 0.4}, "situation_multipliers": {"cornucopia_agotada": 0.1}},
        # Coger lo que está en el suelo del sitio donde se está (16a). Sin
        # afordancia: cualquier sitio con algo tirado vale. Lo que se gana es
        # estar armado, no comida.
        {"id": "registrar", "label": "registrar el suelo", "duration_ticks": 2,
         "requires_item": {}, "takes_item": {},
         "satisfies": {"seguridad": 0.2}, "costs": {"descanso": 0.05}},
        {"id": "rebuscar", "label": "rebuscar entre los escombros", "duration_ticks": 6, "requires_affordance": "botin_menor",
         "requires_item": {}, "takes_item": {},
         "satisfies": {"suministros": 1.0}, "effects": {"descanso": -0.03}, "costs": {"descanso": 0.15}},
        {"id": "esconderse", "label": "esconderse", "duration_ticks": 12, "requires_affordance": "escondite",
         "satisfies": {"seguridad": 1.0}, "effects": {"seguridad": 0.35, "descanso": 0.05}},
        {"id": "vigilar", "label": "vigilar desde lo alto", "duration_ticks": 6, "requires_affordance": "vigia",
         "satisfies": {"seguridad": 0.8}, "effects": {"seguridad": 0.2, "combate": 0.01, "descanso": -0.03},
         "costs": {"descanso": 0.1}},
        {"id": "luchar_a_muerte", "label": "luchar a muerte", "duration_ticks": 3, "requires_company": 1,
         "satisfies": {"seguridad": 1.0, "combate": 1.0}, "effects": {"combate": 0.06, "descanso": -0.05},
         "costs": {"descanso": 0.1}, "situation_multipliers": {"arena_final": 4.0},
         "target": {"combate": True, "por_desconocido": True, "max_regard": 1.0, "requires_condition": "sin_tregua",
                    "quita_por_pericia": "combate", "gives": {"salud": -0.3}, "inflicts": herida}},
        {"id": "aliarse", "label": "aliarse", "duration_ticks": 4, "requires_company": 1,
         "satisfies": {"vinculo": 1.0, "seguridad": 0.4}, "effects": {"vinculo": 0.25, "seguridad": 0.1},
         "target": {"acerca": 0.25, "regard_weight": 0.5, "gives": {"vinculo": 0.1}}},
        {"id": "atacar", "label": "atacar", "duration_ticks": 3, "requires_company": 1,
         "satisfies": {"seguridad": 0.2, "combate": 1.0}, "effects": {"combate": 0.06, "seguridad": 0.15, "descanso": -0.05},
         "costs": {"descanso": 0.2},
         "target": {"combate": True, "por_desconocido": True, "max_regard": 0.05, "quita_por_pericia": "combate", "gives": {"salud": -0.2}, "inflicts": herida}},
        {"id": "atacar_con_sana", "label": "atacar con saña", "duration_ticks": 3, "requires_company": 1,
         "requires_rank": {"combate": 3},
         "satisfies": {"seguridad": 0.25, "combate": 1.0}, "effects": {"combate": 0.06, "seguridad": 0.2, "descanso": -0.06},
         "costs": {"descanso": 0.25},
         "target": {"combate": True, "por_desconocido": True, "max_regard": 0.05, "quita_por_pericia": "combate", "gives": {"salud": -0.32},
                    "inflicts": {**herida, "gravedad_max": 1.4}}},
        {"id": "golpe_mortal", "label": "rematar a un herido", "duration_ticks": 2, "requires_company": 1,
         "requires_rank": {"combate": 1},
         "satisfies": {"combate": 1.0, "seguridad": 0.5}, "effects": {"combate": 0.08, "seguridad": 0.1},
         "target": {"combate": True, "por_desconocido": True, "max_regard": 0.0, "requires_condition": "herida", "quita_por_pericia": "combate", "gives": {"salud": -0.4}}},
        {"id": "saquear", "label": "saquear a un herido", "duration_ticks": 3, "requires_company": 1,
         "satisfies": {"suministros": 1.0}, "takes_item": {"where": "objetivo"},
         "target": {"por_desconocido": True, "max_regard": 0.05, "requires_condition": "herida"}},
        {"id": "curarse", "label": "curarse las heridas", "duration_ticks": 8,
         "requires_item": {"where": "encima", "tags": ["venda"]}, "consumes": {"where": "encima", "tags": ["venda"]},
         "satisfies": {"salud": 1.0}, "effects": {"salud": 0.25},
         "cures": {"herida": 1.0}},
        {"id": "socorrer", "label": "socorrer a un aliado", "duration_ticks": 6, "requires_company": 1,
         "satisfies": {"vinculo": 0.6}, "effects": {"vinculo": 0.2},
         "target": {"requires_condition": "herida", "min_regard": 0.2, "regard_weight": 0.7,
                    "cures": {"herida": 1.2}, "gives": {"salud": 0.3}}},
    ]


if __name__ == "__main__":
    salida = Path(sys.argv[1])
    texto = ("# Generado por packs/isla/generar.py. No se edita a mano: se cambia el\n"
             "# generador y se vuelve a correr. Ver el docstring del generador.\n")
    salida.write_text(texto + yaml.safe_dump(pack(), allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    print(f"isla -> {salida}")
