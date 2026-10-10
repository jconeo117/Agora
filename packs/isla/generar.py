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
                "afford": [["refugio", "escondite"], ["agua"], ["vigia"], ["vigia", "escondite"]]},
    "playa":   {"label": "la playa",   "lugares": ["cala", "dunas", "rompiente", "manglar", "arrecife", "faro", "muelle roto", "naufragio"],
                "afford": [["refugio"], ["forraje"], ["forraje", "aire"], ["agua", "escondite"]]},
    "cienaga": {"label": "la ciénaga", "lugares": ["juncal", "charca", "isleta", "niebla", "pantano", "turbera", "carrizal", "cieno"],
                "afford": [["escondite"], ["agua"], ["refugio", "escondite"], ["forraje"]]},
    "ruinas":  {"label": "las ruinas", "lugares": ["plaza rota", "torre", "sotano", "pozo", "templo caido", "muralla", "almacen", "cripta"],
                "afford": [["botin_menor"], ["vigia"], ["refugio", "escondite"], ["agua"]]},
}
ORDEN = list(REGIONES)
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
                             "affordances": ["botin", "aire", "agua"], "tags": ["centro"]}
    por_anillo[0].append("cornucopia")
    for d in range(1, DISTRITOS + 1):
        pid = f"pedestal_{d}"
        lugares[pid] = {"id": pid, "label": f"el pedestal {d}", "affordances": ["aire"], "tags": ["pedestal"]}
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
                                "affordances": list(aff), "tags": [region, f"anillo_{anillo}"]}
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

ZONA = {3: 3, 2: 6, 1: 9}                 # anillo -> día en que se cierra


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
    rasgo = lambda i, label, **canales: {"id": i, "label": label, **canales}  # noqa: E731
    return {
        "id": "isla",
        "label": "La isla",
        "clock": {"minutes_per_tick": 15, "ticks_per_day": DIA, "phases": [
            {"id": "manana", "label": "mañana", "starts_at": 24},
            {"id": "tarde", "label": "tarde", "starts_at": 52},
            {"id": "noche", "label": "noche", "starts_at": 80}]},
        "health": {"days": 12, "seeds": [1312], "max_crisis": 0.95, "max_transit": 0.6,
                   "min_differentiation": 0.2, "may_go_unused": ["dormir_al_raso", "golpe_mortal", "atacar_con_sana"]},
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
            {"id": "sustento", "label": "comida", "decay_per_tick": 0.0045, "urgency_exponent": 2.4, "initial": 0.7, "base_weight": 1.0, "strain_weight": 0.8},
            {"id": "agua", "label": "agua", "decay_per_tick": 0.007, "urgency_exponent": 2.6, "initial": 0.8, "base_weight": 1.1, "strain_weight": 0.9, "lethal_after": 192},
            {"id": "descanso", "label": "descanso", "decay_per_tick": 0.006, "urgency_exponent": 2.2, "initial": 0.8, "base_weight": 1.0, "strain_weight": 1.0, "max_debt": 1.0},
            {"id": "salud", "label": "salud", "decay_per_tick": 0.0, "urgency_exponent": 2.6, "initial": 1.0, "base_weight": 1.0, "lethal_after": 8},
            {"id": "seguridad", "label": "seguridad", "decay_per_tick": 0.004, "urgency_exponent": 1.8, "initial": 0.5, "base_weight": 0.9, "strain_weight": 0.6},
            {"id": "vinculo", "label": "compañía", "decay_per_tick": 0.003, "urgency_exponent": 1.6, "initial": 0.45, "base_weight": 0.6, "strain_weight": 0.3, "company_relief": 0.002},
            {"id": "suministros", "label": "suministros", "decay_per_tick": 0.0005, "urgency_exponent": 1.5, "initial": 0.2, "base_weight": 0.6},
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
        "relations": [{"id": "del_distrito", "label": "del mismo distrito", "symmetric": True, "regard_floor": 0.15, "company_multiplier": 1.3}],
        "places": lugares,
        "agents": tributos(por_anillo),
        "situations": [
            {"id": "herida", "label": "herida", "personal": True, "effects": {"salud": -0.0025}},
            # Periódicas con un ciclo de un año: empiezan el día de su anillo y
            # duran más que cualquier partida. Es la forma de decir «a partir
            # del día N, para siempre» con lo que el motor ya sabe.
            *({"id": f"zona_{anillo}", "label": f"la zona se cierra (anillo {anillo})", "starts_at": dia * DIA,
               "every": 360 * DIA, "lasts": 300 * DIA, "places": por_anillo[anillo], "effects": {"salud": -0.012, "seguridad": -0.01}}
              for anillo, dia in ZONA.items()),
        ],
        "newcomer": {"home": por_anillo[1][0], "start_at": "pedestal_12", "edad_inicial": DIA * 360 * 17,
                     "initial_needs": {"suministros": 0.2}},
        "voice": {
            "identity_traits": [],
            "character_traits": list(CARACTER) + ["piedad", "arrojo"],
            "fallback": {"amable": ["Aún sigo aquí.", "Mientras respire, hay partida."],
                         "seco": ["Sigue andando.", "No tengo nada para ti."],
                         "hostil": ["Un paso más y te arrepientes.", "Lárgate."],
                         "triste": ["Ya no queda casi nadie.", "No sé cuánto aguanto."],
                         "asustado": ["No me hagas daño.", "Aquí no, por favor."]}},
    }


def acciones() -> list[dict]:
    herida = {"situation": "herida", "marca": "cuerpo", "gravedad_min": 0.4, "gravedad_max": 1.0, "lasts": 2 * DIA}
    return [
        {"id": "dormir", "label": "dormir a cubierto", "duration_ticks": 32, "interruptible": True,
         "requires_affordance": "refugio", "elastic": {"min_ticks": 12, "need": "descanso", "per_tick": 0.03},
         "phase_multipliers": {"noche": 1.9, "manana": 0.5, "tarde": 0.4}, "satisfies": {"descanso": 1.0},
         "effects": {"seguridad": 0.05}},
        {"id": "dormir_al_raso", "label": "dormir al raso", "duration_ticks": 16, "interruptible": True,
         "satisfies": {"descanso": 0.5}, "effects": {"descanso": 0.2, "seguridad": -0.08}, "costs": {"seguridad": 0.3}},
        {"id": "beber", "label": "beber", "duration_ticks": 2, "requires_affordance": "agua",
         "satisfies": {"agua": 1.0}, "effects": {"agua": 0.6}},
        {"id": "recolectar", "label": "buscar comida", "duration_ticks": 8, "requires_affordance": "forraje",
         "satisfies": {"suministros": 1.0, "sustento": 0.3}, "effects": {"suministros": 0.25, "sustento": 0.05, "descanso": -0.05},
         "costs": {"descanso": 0.2}},
        {"id": "comer", "label": "comer de lo que lleva", "duration_ticks": 2, "requires": {"suministros": 0.1},
         "satisfies": {"sustento": 1.0}, "effects": {"suministros": -0.1, "sustento": 0.4}, "costs": {"suministros": 0.5}},
        {"id": "saquear_cornucopia", "label": "saquear la cornucopia", "duration_ticks": 4, "requires_affordance": "botin",
         "satisfies": {"suministros": 1.0}, "effects": {"suministros": 0.6, "seguridad": -0.2}, "costs": {"seguridad": 0.4}},
        {"id": "rebuscar", "label": "rebuscar entre los escombros", "duration_ticks": 6, "requires_affordance": "botin_menor",
         "satisfies": {"suministros": 1.0}, "effects": {"suministros": 0.3, "descanso": -0.03}, "costs": {"descanso": 0.15}},
        {"id": "esconderse", "label": "esconderse", "duration_ticks": 12, "requires_affordance": "escondite",
         "satisfies": {"seguridad": 1.0}, "effects": {"seguridad": 0.35, "descanso": 0.05}},
        {"id": "vigilar", "label": "vigilar desde lo alto", "duration_ticks": 6, "requires_affordance": "vigia",
         "satisfies": {"seguridad": 0.8}, "effects": {"seguridad": 0.2, "combate": 0.01, "descanso": -0.03},
         "costs": {"descanso": 0.1}},
        {"id": "aliarse", "label": "aliarse", "duration_ticks": 4, "requires_company": 1,
         "satisfies": {"vinculo": 1.0, "seguridad": 0.4}, "effects": {"vinculo": 0.25, "seguridad": 0.1},
         "target": {"acerca": 0.25, "regard_weight": 0.5, "gives": {"vinculo": 0.1}}},
        {"id": "atacar", "label": "atacar", "duration_ticks": 3, "requires_company": 1,
         "satisfies": {"seguridad": 0.2, "combate": 1.0}, "effects": {"combate": 0.06, "seguridad": 0.15, "descanso": -0.05},
         "costs": {"descanso": 0.2},
         "target": {"por_desconocido": True, "max_regard": 0.05, "quita_por_pericia": "combate", "gives": {"salud": -0.2}, "inflicts": herida}},
        {"id": "atacar_con_sana", "label": "atacar con saña", "duration_ticks": 3, "requires_company": 1,
         "requires_rank": {"combate": 3},
         "satisfies": {"seguridad": 0.25, "combate": 1.0}, "effects": {"combate": 0.06, "seguridad": 0.2, "descanso": -0.06},
         "costs": {"descanso": 0.25},
         "target": {"por_desconocido": True, "max_regard": 0.05, "quita_por_pericia": "combate", "gives": {"salud": -0.32},
                    "inflicts": {**herida, "gravedad_max": 1.4}}},
        {"id": "golpe_mortal", "label": "rematar a un herido", "duration_ticks": 2, "requires_company": 1,
         "requires_rank": {"combate": 1},
         "satisfies": {"combate": 1.0, "seguridad": 0.5}, "effects": {"combate": 0.08, "seguridad": 0.1},
         "target": {"por_desconocido": True, "max_regard": 0.0, "requires_condition": "herida", "quita_por_pericia": "combate", "gives": {"salud": -0.4}}},
        {"id": "saquear", "label": "saquear a un herido", "duration_ticks": 3, "requires_company": 1,
         "satisfies": {"suministros": 1.0}, "effects": {"suministros": 0.3},
         "target": {"por_desconocido": True, "max_regard": 0.05, "requires_condition": "herida", "gives": {"suministros": -0.3}}},
        {"id": "curarse", "label": "curarse las heridas", "duration_ticks": 8, "requires": {"suministros": 0.2},
         "satisfies": {"salud": 1.0}, "effects": {"salud": 0.25, "suministros": -0.15}, "costs": {"suministros": 0.4},
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
