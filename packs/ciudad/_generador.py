"""Generador de habitantes a partir de los catalogos.

Cien fichas a mano son mush: lo que hace legible a un personaje no es que sus
numeros sean aleatorios, es que sean COHERENTES ENTRE SI. Asi que aqui no se
tiran veintiun rasgos al azar — se componen cuatro piezas que ya vienen enteras:

    rol         ->  donde vive, su oficio, sus puertas
    arquetipos  ->  dos bloques de personalidad, sorteados y compuestos
    estilo+elem ->  sorteados
    meta        ->  del catalogo, filtrada por rol

Escribe el YAML UNA VEZ y se commitea. No se genera al cargar: asi el mundo es
reproducible y se puede editar a mano a quien haga falta despues.

El sorteo usa `random.Random(SEMILLA)` con semilla fija por el mismo motivo que
el motor no usa `hash()`: la misma semilla tiene que dar la misma ciudad, hoy y
dentro de un ano.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

CATALOGOS = Path("C:/Users/jcone/Downloads")
SEMILLA = 20260807

# -----------------------------------------------------------------------------
# LOS ARQUETIPOS, traducidos a ejes.
#
# Cada uno es un bloque coherente, no un rasgo suelto. Se aplican DOS por ficha
# y se promedian donde chocan: alguien puede ser aplicado y solitario a la vez,
# y "aplicado y vividor" produce un termino medio que tambien es una persona.
# -----------------------------------------------------------------------------
ARQUETIPOS: dict[str, dict[str, float]] = {
    "aplicado": dict(laboriosidad=0.8, impulsividad=-0.5, sociabilidad=-0.3, aguante=0.7),
    "vividor": dict(hedonismo=0.8, frugalidad=-0.5, impulsividad=0.7, aguante=-0.3,
                    sociabilidad=0.5),
    "solitario": dict(sociabilidad=-0.9, apego_al_hogar=0.6, arraigo=0.7, reservado=0.5),
    "ambicioso": dict(ambicion=0.8, laboriosidad=0.6, hedonismo=-0.2, aguante=0.4),
    "temerario": dict(impulsividad=0.8, aguante=-0.4, arraigo=-0.5, hedonismo=0.3),
    "metodico": dict(impulsividad=-0.8, aguante=0.5, frugalidad=0.4),
    "hogareno": dict(apego_al_hogar=0.8, frugalidad=0.6, arraigo=0.7, sociabilidad=-0.2),
    "errante": dict(arraigo=-0.8, apego_al_hogar=-0.5, impulsividad=0.3),
    "noctambulo": dict(nocturnidad=0.8, hedonismo=0.3, sociabilidad=0.2),
    "curtido": dict(curtido=0.9, aguante=0.6, sueno_ligero=-0.4, hedonismo=-0.2),
    "prudente": dict(frugalidad=0.7, impulsividad=-0.7, aguante=0.3),
    "sociable": dict(sociabilidad=0.9, apego_al_hogar=-0.3, hedonismo=0.3),
    "frugal": dict(frugalidad=0.8, hedonismo=-0.5, apego_al_hogar=0.4),
    "hedonista": dict(hedonismo=0.9, frugalidad=-0.6, impulsividad=0.5),
    "estoico": dict(aguante=0.9, impulsividad=-0.4, hedonismo=-0.3, sociabilidad=-0.2),
}

# -----------------------------------------------------------------------------
# LAS METAS, traducidas a umbral.
#
# (eje, umbral, on_success, on_failure, roles a los que pega)
#
# Tres del catalogo NO estan: "no volver a pasar hambre", "que la cosecha alcance
# para todo el invierno" y "cerrar el trato del ano" piden granjeros y
# comerciantes que esta ciudad todavia no tiene. Se quedan fuera en vez de
# forzarlas sobre roles que no son.
# -----------------------------------------------------------------------------
METAS: dict[str, tuple[str, float, dict[str, float], dict[str, float], set[str]]] = {
    "graduarse con honores": (
        "curso", 0.95, {"graduado": 1.0, "ambicion": 0.3},
        {"laboriosidad": 0.5, "hedonismo": -0.3}, {"alumno"}),
    "que su promocion le recuerde": (
        "curso", 0.95, {"graduado": 1.0, "sociabilidad": 0.4},
        {"sociabilidad": -0.4, "apego_al_hogar": 0.4}, {"alumno"}),
    "dominar su elemento antes que nadie": (
        "arcano", 0.85, {"ambicion": 0.3, "sociabilidad": 0.2},
        {"ambicion": -0.4, "hedonismo": 0.3}, {"alumno"}),
    "que le dejen en paz": (
        "discrecion", 0.95, {"sociabilidad": 0.3, "arraigo": -0.3},
        {"sociabilidad": -0.4, "apego_al_hogar": 0.4}, {"alumno", "cazador", "artesano"}),
    "hacerse un nombre en el gremio": (
        "armas", 0.70, {"ambicion": 0.3, "sociabilidad": 0.3},
        {"aguante": -0.4, "apego_al_hogar": 0.4}, {"cazador"}),
    "llegar al fondo de la sima": (
        "temple", 0.70, {"impulsividad": 0.3, "arraigo": -0.3},
        {"aguante": -0.5, "arraigo": 0.4}, {"cazador"}),
    "saldar una deuda con el gremio": (
        "ahorros", 0.45, {"frugalidad": -0.4, "hedonismo": 0.3},
        {"frugalidad": 0.5, "sociabilidad": -0.3}, {"cazador", "artesano"}),
    "volver a entrar donde le echaron": (
        "ahorros", 0.55, {"sociabilidad": 0.4, "arraigo": 0.3},
        {"sociabilidad": -0.5, "impulsividad": 0.4}, {"cazador", "artesano"}),
    "juntar para montar su propio taller": (
        "ahorros", 0.50, {"arraigo": 0.4, "laboriosidad": -0.3},
        {"laboriosidad": 0.5, "hedonismo": -0.3}, {"artesano"}),
    "forjar un arma que nadie mas pueda hacer": (
        "armas", 0.60, {"ambicion": 0.3, "sociabilidad": 0.2},
        {"ambicion": -0.4, "aguante": -0.3}, {"artesano"}),
    "que su taller sobreviva a el": (
        "ahorros", 0.65, {"apego_al_hogar": 0.3, "sociabilidad": 0.3},
        {"laboriosidad": 0.4, "sociabilidad": -0.3}, {"artesano"}),
    "que su nombre quede en la academia": (
        "arcano", 0.90, {"sociabilidad": 0.3, "ambicion": 0.2},
        {"ambicion": -0.5, "apego_al_hogar": 0.4}, {"profesor"}),
}

ESTILOS = ("estilo_guerrero", "estilo_asesino", "estilo_soporte")
ELEMENTOS = ("elem_fuego", "elem_agua", "elem_tierra", "elem_viento")

# 96 x 30 x 12 x 6 = seis anos, uno mas que la carrera.
SEIS_ANOS = 96 * 30 * 12 * 6


def _bloques(fichero: str) -> list[list[str]]:
    texto = (CATALOGOS / fichero).read_text(encoding="utf-8")
    return [
        [x.strip() for x in b.splitlines() if x.strip()]
        for b in re.findall(r"```\n(.*?)```", texto, re.S)
    ]


def _nombres(rng: random.Random, cuantos: int) -> list[str]:
    """Nombre + apellido, sin repetir la combinacion."""
    fem, masc, apellidos = _bloques("nombres-npcs.md")
    pila = [*fem, *masc]
    rng.shuffle(pila)
    usados: set[str] = set()
    salida: list[str] = []
    for pila_nombre in pila:
        for _ in range(40):
            completo = f"{pila_nombre} {rng.choice(apellidos)}"
            if completo not in usados:
                usados.add(completo)
                salida.append(completo)
                break
        if len(salida) == cuantos:
            break
    return salida


def _identificador(label: str, tomados: set[str]) -> str:
    base = re.sub(r"[^a-z]+", "_", label.lower()).strip("_")
    ident, n = base, 2
    while ident in tomados:
        ident, n = f"{base}_{n}", n + 1
    tomados.add(ident)
    return ident


def _personalidad(rng: random.Random) -> tuple[dict[str, float], tuple[str, str]]:
    """Dos arquetipos compuestos. Donde chocan, se promedia.

    Dos y no uno porque uno solo produce cien personas de quince tipos. Dos dan
    ciento cinco combinaciones, y las que chocan —aplicado y vividor— salen
    termino medio, que tambien es una persona.
    """
    a, b = rng.sample(sorted(ARQUETIPOS), 2)
    rasgos: dict[str, float] = {}
    for nombre in (a, b):
        for eje, valor in ARQUETIPOS[nombre].items():
            rasgos[eje] = (rasgos[eje] + valor) / 2 if eje in rasgos else valor
    # Un poco de ruido para que dos fichas del mismo par no sean gemelas.
    return ({k: round(max(-1.0, min(1.0, v + rng.uniform(-0.12, 0.12))), 2)
             for k, v in rasgos.items()}, (a, b))


ROLES = {
    "alumno": dict(home="aca_celdas", oficio="asistir_a_leccion"),
    "profesor": dict(home="barrio_alto", oficio="dar_clase"),
    "cazador": dict(home="barrio_bajo", oficio="expoliar_cripta"),
    "artesano": dict(home="barrio_bajo", oficio="trabajar_en_la_fragua"),
}
OFICIOS_CAZA = ("expoliar_cripta", "caza_menor", "expoliar_cripta")
OFICIOS_CIUDAD = ("trabajar_en_la_fragua", "servir_en_la_taberna", "trabajar_en_la_fragua")


def poblar() -> list[dict]:
    rng = random.Random(SEMILLA)

    # 40 alumnos (ocho por promocion), 10 profesores, 30 cazadores, 20 de ciudad.
    plantilla: list[tuple[str, float | None]] = []
    for curso_inicial in (0.05, 0.25, 0.45, 0.65, 0.85):
        plantilla += [("alumno", curso_inicial)] * 8
    plantilla += [("profesor", None)] * 10
    plantilla += [("cazador", None)] * 30
    plantilla += [("artesano", None)] * 20

    etiquetas = _nombres(rng, len(plantilla))
    tomados: set[str] = set()
    fichas: list[dict] = []

    for (rol, curso_inicial), label in zip(plantilla, etiquetas, strict=True):
        rasgos, _ = _personalidad(rng)
        rasgos[rng.choice(ESTILOS)] = 1.0
        rasgos[rng.choice(ELEMENTOS)] = 1.0

        base = ROLES[rol]
        oficio = str(base["oficio"])
        if rol == "alumno":
            rasgos["alumno"] = 1.0
            # Los de quinto ya salen; los de primero no han pisado la sima.
            if curso_inicial is not None and curso_inicial >= 0.65:
                rasgos["graduado"] = 0.0
        elif rol == "profesor":
            rasgos["profesor"] = 1.0
            rasgos["graduado"] = 1.0
        elif rol == "cazador":
            rasgos["graduado"] = 1.0
            rasgos.setdefault("curtido", 0.7)
            oficio = rng.choice(OFICIOS_CAZA)
        else:
            oficio = rng.choice(OFICIOS_CIUDAD)

        gustos = [{"target": oficio, "multiplier": 2.3}]
        if rol == "cazador":
            gustos.append({"target": "tasar_botin", "multiplier": 1.7})

        ficha: dict = {
            "id": _identificador(label, tomados), "label": label,
            "home": base["home"], "start_at": base["home"],
            "traits": {k: v for k, v in sorted(rasgos.items()) if v},
            "tastes": gustos,
        }
        if curso_inicial:
            ficha["initial_needs"] = {"curso": curso_inicial}

        # No todo el mundo tiene arco: un pueblo donde los cien persiguen algo no
        # es un pueblo. Dos de cada tres, y solo metas que le peguen a su rol.
        posibles = [k for k, v in METAS.items() if rol in v[4]]
        if posibles and rng.random() < 0.66:
            elegida = rng.choice(posibles)
            eje, umbral, ok, ko, _ = METAS[elegida]
            ficha["goals"] = [{
                "id": re.sub(r"[^a-z]+", "_", elegida.lower()).strip("_"),
                "label": elegida, "need": eje, "at_least": umbral,
                "weight_multiplier": 2.2, "deadline": SEIS_ANOS,
                "on_success": ok, "on_failure": ko,
            }]
        fichas.append(ficha)
    return fichas
