"""Genera el pack de Confluencia: doscientos habitantes de cinco razas.

Se corre a mano cuando cambia el catalogo:

    cd packs/confluencia && uv run python generar.py

Escribir doscientas fichas a mano seria inviable y ademas mentiria: lo que se
quiere probar es si el SISTEMA -razas, clases, afinidades- produce gente
distinta, y para eso la poblacion tiene que salir de sortear el sistema, no de
que alguien la escriba una por una con su gusto.

El sorteo es determinista (`random.Random(SEMILLA)`), asi que el pack es
reproducible: dos generaciones dan el mismo YAML byte a byte.
"""

from __future__ import annotations

import random
import sys
import unicodedata
from pathlib import Path

import yaml

S = Path(__file__).parent
sys.path.insert(0, str(S))

from _acciones import actions  # noqa: E402
from _eventos import condiciones, eventos  # noqa: E402
from _catalogo import (  # noqa: E402
    afinidades, caracter, clases, needs, razas, relations, traits,
)

SEMILLA = 4271
POBLACION = 200

# --- EL MAPA -----------------------------------------------------------------
#
# Viene escrito a mano en `_mapa.yaml`. Aqui solo se le anade una affordance:
# `expolio` a las mazmorras y guaridas, que sin ella no ofrecen NADA y por tanto
# son inalcanzables por proposito -nadie tiene motivo para ir, y aun asi cuestan
# evaluacion en cada deliberacion-. La cripta olvidada se deja vacia a proposito:
# su accion es invocar, y eso pide poder crear agentes en marcha (RAIZ 1).

# Y las de los oficios, que son las que dan sitio propio a cada clase. Sin ellas
# las cinco clases hacen las mismas acciones y la gente sale indistinguible —
# medido en la primera corrida: diferenciacion 0.329 contra el 0.867 de la ciudad.
#
# Todas caen donde el mapa ya decia que caian, en sus propios comentarios: el
# contrabando en el muelle de contrabandistas, la caza en el campo de caza y en
# la linde, y la invocacion en la cripta olvidada — que el autor describe como
# "el sitio donde ocurren invocaciones" y estaba sin una sola affordance.

ANADIR = {
    "mazmorra_menor": ["expolio"], "mazmorra_media": ["expolio"],
    "mazmorra_mayor": ["expolio"], "guarida_goblin": ["expolio"],
    "claro_del_ogro": ["expolio"], "campamento_orco": ["expolio"],
    "muelle_de_contrabandistas": ["contrabando"],
    "campo_de_caza": ["caza"], "linde_salvaje": ["caza"],
    "cripta_olvidada": ["invocacion"],
}

# --- CADA BARRIO SE BASTA A SI MISMO, Y EL CENTRO PAGA MEJOR ------------------
#
# La primera version ponia cada oficio en uno o dos sitios, todos lejos, y medido
# eso no producia migracion sino PARALISIS: la deliberacion decidia -bien- que no
# compensaba cruzar la ciudad, asi que nadie ejercia su oficio y todos hacian las
# mismas cinco cosas genericas (diferenciacion 0.44).
#
# La correccion es que la eleccion sea sobre el PRECIO y no sobre la
# DISPONIBILIDAD. Con el oficio disponible en casa, quien viaja al centro lo hace
# porque paga mas, no porque no le quede otra — y quien se queda esta eligiendo la
# comodidad, no sufriendo una carencia. Solo entonces hay dos conductas que
# observar en vez de una.

BARRIOS_OFICIO = {
    # plaza del barrio            sitio de trabajo   sitio de quietud
    "plaza_elfica": ("arboleda_ancestral", "santuario_del_viento"),
    "plaza_enana": ("forjas", "posada_enana"),
    "plaza_gigante": ("campo_gigante", "salon_comunal_gigante"),
    "plaza_demihumana": ("campo_de_caza", "posada_de_la_manada"),
    "plaza_portuaria": ("muelle", "templo_mareas"),
}
for plaza, (taller, retiro) in BARRIOS_OFICIO.items():
    # Puesto de gremio y mercadillo locales: pagan menos que el centro.
    ANADIR.setdefault(plaza, []).extend(["contratos", "mercaduria"])
    # El taller del barrio sirve para entrenar el cuerpo y para cazar cerca.
    ANADIR.setdefault(taller, []).extend(["palestra", "caza", "trabajo"])
    # Y el retiro, para lo que pide silencio: meditar, estudiar, pactar.
    ANADIR.setdefault(retiro, []).extend(["quietud", "archivo", "invocacion"])
    # El trabajo sucio se hace en la sombra de cada barrio, no solo en el puerto.
    ANADIR.setdefault(plaza, []).append("contrabando")

# El centro es el unico sitio donde se puede trabajar de porteador, y donde el
# gremio y el mercado pagan mejor. Es el iman de la migracion: mismo oficio,
# mejor paga, mas lejos de casa.
CENTRO_MEJOR = {
    "gremio_aventureros": {"dinero": 1.35},
    "mercado_central": {"dinero": 1.30},
}
ANADIR.setdefault("mercado_central", []).append("trabajo")

places = yaml.safe_load((S / "_mapa.yaml").read_text(encoding="utf-8"))["places"]
for p in places:
    if p["id"] in ANADIR:
        nuevas = sorted(set(ANADIR[p["id"]]) - set(p.get("affordances", [])))
        p.setdefault("affordances", []).extend(nuevas)
    if p["id"] in CENTRO_MEJOR:
        p["gain_multipliers"] = {**p.get("gain_multipliers", {}),
                                 **CENTRO_MEJOR[p["id"]]}

# --- QUIEN VIVE DONDE --------------------------------------------------------
#
# La zonificacion del mapa es del autor, y se respeta: cada raza duerme en su
# barrio. Que las plazas de barrio esten a 2 del centro y a 1 de los suyos es lo
# que hace que la geografia signifique algo — sin eso, las razas serian etiquetas.

BARRIOS = {
    "elfo": ("posada_elfica", "plaza_elfica"),
    "enano": ("posada_enana", "plaza_enana"),
    "gigante": ("salon_comunal_gigante", "plaza_gigante"),
    "demihumano": ("posada_de_la_manada", "plaza_demihumana"),
    "humano": ("posada_central", "plaza_mayor"),
}
# Los humanos son mayoria y se reparten entre el centro y el puerto: el puerto es
# identidad economica, no raza, y el mapa lo dice en sus propios comentarios.
BARRIO_PORTUARIO = ("posada_marea", "plaza_portuaria")

# Reparto de la poblacion. Los humanos dominan porque son el grupo de control y
# el que mas varianza tiene; los gigantes son pocos porque una ciudad no sostiene
# a muchos.
MEZCLA = [("humano", 82), ("enano", 38), ("elfo", 32),
          ("demihumano", 34), ("gigante", 14)]

# Sesgo de afinidad por raza. NUNCA un candado: son pesos de una tirada, tal como
# el documento pide ("nunca un candado absoluto, solo una inclinacion fuerte").
SESGO = {
    "humano": {"fuego": 1, "agua": 1, "tierra": 1, "viento": 1},
    "enano": {"tierra": 5, "fuego": 3, "agua": 1, "viento": 1},
    "elfo": {"viento": 6, "agua": 2, "tierra": 1, "fuego": 1},
    "gigante": {"tierra": 4, "fuego": 2, "agua": 2, "viento": 1},
    "demihumano": {"viento": 3, "tierra": 3, "agua": 2, "fuego": 2},
}

# Sesgo de clase. Los demihumanos a lo fisico y los elfos a lo arcano salen de
# aqui, no de un decreto: el propio sistema los empuja.
CLASES = {
    "humano": {"guerrero": 3, "mago": 3, "asesino": 2, "montaraz": 2, "invocador": 1},
    "enano": {"guerrero": 5, "mago": 2, "asesino": 1, "montaraz": 2, "invocador": 1},
    "elfo": {"guerrero": 1, "mago": 5, "asesino": 2, "montaraz": 3, "invocador": 2},
    "gigante": {"guerrero": 7, "mago": 1, "asesino": 1, "montaraz": 2, "invocador": 1},
    "demihumano": {"guerrero": 4, "mago": 1, "asesino": 4, "montaraz": 5,
                   "invocador": 1},
}

NOMBRES = [
    "Aral", "Bern", "Cael", "Dorn", "Eris", "Fenn", "Gith", "Hale", "Ivar",
    "Jora", "Kel", "Lira", "Mor", "Nyx", "Orin", "Pell", "Quen", "Rask",
    "Sela", "Torv", "Ulla", "Varn", "Wyn", "Xan", "Yves", "Zar", "Adze",
    "Brix", "Cyra", "Dain", "Eyla", "Fror", "Gwen", "Hurn", "Isla", "Jarl",
]
APELLIDOS = [
    "Piedraparda", "Vientolargo", "Yunquenegro", "Marfrio", "Cenizal",
    "Rocaviva", "Hojaclara", "Hierrogris", "Solraso", "Nieblalta",
    "Cantorroto", "Fuegolento", "Vadohondo", "Umbrio", "Zarzal",
]


# =============================================================================
# LAS METAS — lo unico que hace que a alguien le cambie el caracter con la vida
#
# Los rasgos son fijos. `on_success` y `on_failure` son la unica forma que hay
# hoy de que una biografia deje marca en quien la vive: lo consigue y se vuelve
# mas ambicioso, lo falla y se resigna. Dos personas del mismo punto de partida
# y dos finales distintos, ninguno escrito como guion.
#
# UN LIMITE QUE HAY QUE CONOCER: `at_least` lee el VALOR del eje, y `dominio`
# vuelve a cero cada vez que se rompe un rango. Asi que **no se puede escribir
# una meta de rango** -"llegar a rango 5"- porque se cumpliria con el primero.
# Las metas de este mundo van sobre `dinero`, `vinculo` y `mana`, que son los
# tres ejes que acumulan de verdad.
#
# Y NO TODO EL MUNDO TIENE ARCO. Un pueblo donde los doscientos persiguen algo
# no es un pueblo: dos de cada tres, y solo lo que le pegue a su clase.
#
# UNA META SOBRE UN EJE SACIABLE ES UN MOMENTO, NO UN ARCO. `at_least` lee el
# VALOR ACTUAL, y una necesidad esta disenyada para llenarse: sobre 2880 ticks,
# todo el que trabaje su eje toca 0.88 alguna vez. Con los umbrales iniciales se
# cumplieron LAS 133 antes del dia 30.
#
# Los umbrales van al filo del maximo medido -p90 de `dinero` a los 30 dias es
# 0.951 y el maximo 0.999- para que llegar signifique algo. Pero el arreglo de
# verdad es de motor: que una meta pueda leer el RANGO. "Llegar a rango 5" es la
# ambicion arquetipica de un mundo con rangos y es la unica que hoy no se puede
# escribir, porque `dominio` vuelve a cero cada vez que se rompe uno.
#
# (eje, umbral_de_valor, rango, on_success, on_failure, clases a las que pega)
#
# Exactamente UNO de `umbral_de_valor` y `rango`, nunca los dos: el motor lo
# valida al cargar. Con los dos habria que decidir si se cumple con uno o con
# ambos, y cualquier respuesta seria una convencion que nadie recuerda.
# =============================================================================

# El plazo va a CIENTO VEINTE DIAS y no a anyos, y la razon es el instrumento:
# con un plazo de tres anyos, `on_failure` no dispara JAMAS en una corrida de
# 180 dias, asi que la mitad del mecanismo -la que amarga a quien no llega- era
# codigo muerto que nadie podia medir. Un plazo que cabe en la medicion es un
# plazo que se puede calibrar.
PLAZO = 96 * 120

METAS: dict[
    str,
    tuple[str, float | None, int | None, dict[str, float], dict[str, float], set[str]],
] = {
    # Lo consigue y le sabe a poco -quiere mas-; lo falla y se resigna, pero se
    # refugia en la gente, que es lo que le queda.
    "juntar una fortuna": (
        "dinero", 0.97, None, {"ambicion": 0.35}, {"ambicion": -0.40, "sociabilidad": 0.30},
        {"asesino", "montaraz", "guerrero"}),
    # El que quiere dejar de deberle nada a nadie. Fallar le vuelve arisco.
    "saldar lo que debe": (
        "dinero", 0.93, None, {"audacia": 0.25, "sociabilidad": 0.25},
        {"sociabilidad": -0.45, "audacia": -0.20},
        {"guerrero", "montaraz", "invocador", "asesino"}),
    # Llenar la reserva hasta el borde. Es la meta del que vive por el arte.
    "dominar su reserva": (
        "mana", 0.96, None, {"ambicion": 0.30, "audacia": 0.25},
        {"ambicion": -0.35, "audacia": -0.30},
        {"mago", "invocador"}),
    # No volver a estar solo. La mas humana, y la que peor sienta fallar.
    "no volver a estar solo": (
        "vinculo", 0.97, None, {"sociabilidad": 0.35},
        {"sociabilidad": -0.55, "ambicion": 0.25},
        {"humano", "guerrero", "mago", "montaraz", "asesino", "invocador"}),
    # --- LAS DE RANGO, que son las unicas que pueden FALLAR -----------------
    #
    # `at_rank` mide cuantos rangos ha roto, y ese numero SOLO SUBE: es el unico
    # de este motor que puede sostener un arco. Y trae su dificultad graduada
    # sin declararla — con la cuesta cuadratica, llegar al rango N pide
    # 1+2+...+N listones, asi que el 2 y el 4 son carreras de longitudes muy
    # distintas sin tocar ni un plazo.
    #
    # Medido: el rango medio a los 180 dias es 3.2, asi que con plazo de 120
    # dias el 2 lo alcanza bastante gente y el 4 casi nadie. Por primera vez hay
    # metas que se pierden, y `on_failure` deja de ser codigo muerto.
    "hacerse un nombre con las armas": (
        "dominio", None, 2, {"ambicion": 0.30, "audacia": 0.25},
        {"ambicion": -0.35, "pereza": 0.30},
        {"guerrero", "asesino", "montaraz"}),
    "que su nombre pese en la torre": (
        "dominio", None, 4, {"ambicion": 0.40, "devocion": 0.30},
        {"devocion": -0.40, "ambicion": -0.30, "aprension": 0.25},
        {"mago", "invocador"}),
    # El que quiere que le conozcan. Distinta de la anterior: esta se conforma
    # con menos y falla menos, pero mueve la misma perilla.
    "que le conozcan en la ciudad": (
        "vinculo", 0.94, None, {"sociabilidad": 0.30, "ambicion": 0.25},
        {"sociabilidad": -0.30, "audacia": -0.25},
        {"mago", "invocador", "guerrero"}),
}


def _id(texto: str) -> str:
    plano = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return plano.lower().replace(" ", "_")


def _elegir(rng: random.Random, pesos: dict[str, int]) -> str:
    llaves = sorted(pesos)
    return rng.choices(llaves, weights=[pesos[k] for k in llaves], k=1)[0]


def poblar() -> list[dict]:
    rng = random.Random(SEMILLA)
    fichas: list[dict] = []
    tomados: set[str] = set()

    reparto = [raza for raza, cuantos in MEZCLA for _ in range(cuantos)]
    rng.shuffle(reparto)

    for n, raza in enumerate(reparto):
        nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
        ident = _id(nombre)
        while ident in tomados:
            ident = f"{_id(nombre)}_{n}"
        tomados.add(ident)

        rasgos: dict[str, float] = {raza: 1.0}

        # AFINIDAD DE NACIMIENTO: una, a intensidad plena. Es el sello del mundo.
        nacimiento = _elegir(rng, SESGO[raza])
        rasgos[f"afin_{nacimiento}"] = 1.0

        # AFINIDAD APRENDIDA: el MISMO tipo de rasgo, a intensidad parcial. De ahi
        # sale que cueste mas sin ningun mecanismo aparte — el temple compone la
        # intensidad como exponente. Los elfos la consiguen mas a menudo (su
        # ventana es mas larga) y los demihumanos casi nunca (la suya se cierra
        # pronto).
        prob = {"elfo": 0.55, "humano": 0.28, "enano": 0.22,
                "gigante": 0.12, "demihumano": 0.10}[raza]
        if rng.random() < prob:
            otros = [e for e in ("fuego", "agua", "tierra", "viento")
                     if e != nacimiento]
            rasgos[f"afin_{_elegir(rng, {e: SESGO[raza][e] for e in otros})}"] = round(
                rng.uniform(0.25, 0.5), 2
            )

        clase = _elegir(rng, CLASES[raza])
        rasgos[clase] = round(rng.uniform(0.7, 1.0), 2)

        # Y el caracter, que es lo que impide que dos enanos guerreros de fuego
        # sean la misma persona.
        #
        # LA INTENSIDAD VA CON SIGNO, y hasta aqui no lo iba: el sorteo era
        # `uniform(0.4, 1.0)`, siempre positivo, asi que en los doscientos
        # agentes del pack anterior habia CERO intensidades negativas.
        #
        # Y la mitad negativa de un rasgo es su opuesto exacto, ya construido:
        # la intensidad se aplica como exponente, asi que `audacia` a -0.7 es
        # prudencia con los reciprocos justos. Media biblioteca estaba sin usar.
        #
        # Se descarta la franja |i| < 0.4 a proposito: por debajo de ahi el
        # rasgo no cambia ninguna decision y solo ensucia la ficha con ruido que
        # se lee como intencion.
        for rasgo in rng.sample(sorted(t["id"] for t in caracter),
                                k=rng.choice([1, 2, 2, 3])):
            signo = 1 if rng.random() < 0.5 else -1
            rasgos[rasgo] = round(signo * rng.uniform(0.4, 1.0), 2)

        cama, plaza = (
            BARRIO_PORTUARIO if raza == "humano" and rng.random() < 0.45
            else BARRIOS[raza]
        )

        # EL APEGO AL BARRIO, y es la mitad de la tension que se quiere observar.
        #
        # `home` no ata a nadie: no tiene ningun efecto mecanico en el motor, solo
        # se valida como referencia. La gente duerme y trabaja donde le compensa,
        # asi que MUDARSE YA ES GRATIS. Lo que faltaba era una razon para no
        # hacerlo, y esa es un gusto: una predileccion por los sitios de los suyos.
        #
        # Se sortea ancho a proposito -de 0.95 a 1.45- para que el barrio no
        # produzca una sola conducta. Por debajo de 1 hay quien esta deseando
        # salir. De la tension entre ese numero, lo que paga el centro y el
        # descuento de viaje sale quien migra y quien se queda, sin que nadie lo
        # programe.
        apego = round(rng.uniform(0.95, 1.45), 2)
        gustos = [{"target": sitio, "multiplier": apego}
                  for sitio in (plaza, cama, *BARRIOS_OFICIO.get(plaza, ()))]

        ficha: dict = {
            "id": ident, "label": nombre, "home": cama, "start_at": plaza,
            "traits": dict(sorted(rasgos.items())),
            "tastes": gustos,
        }

        # EL ARCO. Dos de cada tres, y solo metas que le peguen a su clase o a
        # su raza. El que no tiene ninguna no es un personaje incompleto: es la
        # mayoria silenciosa que hace que los que SI persiguen algo destaquen.
        suyos = {clase, raza}
        posibles = sorted(k for k, v in METAS.items() if suyos & v[5])
        if posibles and rng.random() < 0.66:
            elegida = rng.choice(posibles)
            eje, umbral, rango_pedido, ok, ko, _ = METAS[elegida]
            meta = {
                "id": _id(elegida), "label": elegida, "need": eje,
                "weight_multiplier": 2.2, "deadline": PLAZO,
                "on_success": ok, "on_failure": ko,
            }
            # Exactamente una de las dos, nunca las dos. El motor lo valida.
            if rango_pedido is not None:
                meta["at_rank"] = rango_pedido
            else:
                meta["at_least"] = umbral
            ficha["goals"] = [meta]

        fichas.append(ficha)
    return fichas


agents = poblar()

# =============================================================================
# LOS LAZOS CON NOMBRE, y se tejen DESPUES porque apuntan a ids que ya existen.
#
# La estructura no es decorativa: cada lazo sigue una regla del mundo, y de ahi
# sale una sociedad en vez de un grafo aleatorio.
#
#   parejas       entre gente del MISMO BARRIO. Uno se empareja con quien ve
#   hermandades   de la MISMA RAZA. Una familia no es mestiza en este mundo
#   discipulados  de la MISMA CLASE. Un mago no ensenya a un montaraz
#
# Y los `initial_bonds` van ASIMETRICOS a proposito: cada cual guarda el suyo,
# y que uno quiera un poco mas que el otro es la clase de detalle que hace que
# una pareja no sea un espejo.
# =============================================================================

_rng_lazos = random.Random(SEMILLA + 1)
_por_barrio: dict[str, list[dict]] = {}
_por_raza: dict[str, list[dict]] = {}
_por_clase: dict[str, list[dict]] = {}
for _a in agents:
    _por_barrio.setdefault(_a["home"], []).append(_a)
    # La raza y la clase estan en los rasgos, a intensidad 1.0 y 0.7-1.0.
    for _r in MEZCLA:
        if _r[0] in _a["traits"]:
            _por_raza.setdefault(_r[0], []).append(_a)
    for _c in ("guerrero", "mago", "asesino", "montaraz", "invocador"):
        if _c in _a["traits"]:
            _por_clase.setdefault(_c, []).append(_a)


def _lazo(uno: dict, otro: dict, nombre: str, mio: float, suyo: float) -> None:
    uno.setdefault("relations", {}).setdefault(nombre, []).append(otro["id"])
    if mio:
        uno.setdefault("initial_bonds", {})[otro["id"]] = mio
    if suyo:
        otro.setdefault("initial_bonds", {})[uno["id"]] = suyo


# PAREJAS. Un tercio de la poblacion emparejada, por barrio. Se toman de los
# extremos hacia el centro para que no salgan siempre vecinos de la misma
# cohorte del generador -que estaria ordenada por el sorteo de razas-.
_emparejados: set[str] = set()
for _barrio, _gente in sorted(_por_barrio.items()):
    _libres = [a for a in _gente if a["id"] not in _emparejados]
    for _k in range(len(_libres) // 6):
        _uno, _otro = _libres[_k], _libres[-1 - _k]
        if _uno["id"] == _otro["id"]:
            break
        _lazo(_uno, _otro, "pareja", 0.55, 0.50)
        _emparejados |= {_uno["id"], _otro["id"]}

# HERMANDADES. De la misma raza, y de tres en tres a veces: hay familias con
# mas de dos hijos. SIN aprecio de partida -el suelo de `hermano` es None a
# proposito-, asi que empiezan de cero y se ganan lo que sientan.
_hermanados: set[str] = set()
for _raza, _gente in sorted(_por_raza.items()):
    _libres = [a for a in _gente if a["id"] not in _hermanados]
    _i = 0
    while _i + 1 < len(_libres) // 3:
        _n = 3 if _rng_lazos.random() < 0.25 and _i + 2 < len(_libres) else 2
        _grupo = _libres[_i:_i + _n]
        for _x in _grupo:
            for _y in _grupo:
                if _x is not _y and _y["id"] not in _x.get(
                        "relations", {}).get("hermano", []):
                    _lazo(_x, _y, "hermano", 0.0, 0.0)
        _hermanados |= {a["id"] for a in _grupo}
        _i += _n

# DISCIPULADOS. De la misma clase, y el maestro es quien mas dominio promete:
# se toma al que tiene la clase a mayor intensidad. Uno o dos discipulos cada
# uno, y nadie es discipulo de dos maestros.
_tomados: set[str] = set()
for _clase, _gente in sorted(_por_clase.items()):
    _orden = sorted(_gente, key=lambda a: -a["traits"][_clase])
    _maestros, _resto = _orden[:len(_orden) // 8], _orden[len(_orden) // 8:]
    _pool = [a for a in _resto if a["id"] not in _tomados]
    _j = 0
    for _m in _maestros:
        for _ in range(_rng_lazos.choice([1, 2])):
            if _j >= len(_pool):
                break
            _lazo(_m, _pool[_j], "maestro", 0.30, 0.38)
            _tomados.add(_pool[_j]["id"])
            _j += 1

pack = {
    "id": "confluencia",
    "label": "Confluencia",
    "clock": {"minutes_per_tick": 15, "ticks_per_day": 96, "days_per_year": 360,
              "phases": [{"id": "manana", "label": "manana", "starts_at": 24},
                         {"id": "tarde", "label": "tarde", "starts_at": 52},
                         {"id": "noche", "label": "noche", "starts_at": 80}]},
    # CONTRATO DE UNA VERSION SIN CALIBRAR, y escrito asi a proposito — misma
    # decision que `dark_fantasy`, para que sea una decision y no un olvido.
    #
    # La diferenciacion mide 0.44 y el objetivo es el 0.867 de la ciudad. La
    # banda dice 0.40 para que la bateria pase y siga vigilando que no BAJE, no
    # porque 0.40 este bien.
    #
    # Que falta, medido y no supuesto: las cinco acciones de oficio estan cada
    # una en uno o dos sitios y todos lejos, mientras que `trabajar` esta en seis
    # y a un tick. Con `travel_discount` 0.94, cinco ticks de camino se comen el
    # 27% de la recompensa, asi que la deliberacion decide -bien- que no compensa,
    # y todo el mundo acaba haciendo las mismas cinco cosas genericas.
    #
    # La causa de fondo es que aqui la casa se asigna por RAZA y el oficio por
    # CLASE, y son ortogonales: todo el mundo vive lejos de donde trabaja. La
    # ciudad no tiene el problema porque sus dos poblaciones viven donde trabajan
    # -los alumnos dentro de la academia, los cazadores junto a la sima-.
    "health": {"days": 14, "seeds": [4271],
               "min_crisis": 0.02, "max_crisis": 0.40,
               "max_abort_ratio": 0.30, "max_transit": 0.35,
               "min_differentiation": 0.40,
               # Las de abajo piden viaje largo o rango alto: son meses, no dos
               # semanas. Declaradas para que el panel no mienta.
               #
               # `expoliar` SALE de la lista: llevaba cero usos desde que se
               # escribio el pack porque estaba estrictamente dominada por
               # `trabajar` -mismo `satisfies`, mas coste, mas viaje-. Corregido,
               # 140 usos en catorce dias y cinco mazmorras revividas.
               #
               # `socorrer` ENTRA, y con motivo: exige la conjuncion de herido,
               # sin dinero para el unguento, en un templo, y con alguien
               # delante que le aprecie. Eso pasa, pero no en dos semanas.
               "may_go_unused": ["holgazanear", "socorrer",
                                 "canalizar_linea_ley", "convidar",
                                 "sostener_un_pacto", "trabajo_sucio"]},
    "tuning": {
        "travel_discount": 0.94, "candidate_pool": 3, "temperature": 0.12,
        "loss_aversion": 1.0, "saturation_recovery": 0.004, "novelty_weight": 0.6,
        "switch_cost": 0.8, "duration_discount": 0.995,
        "critical_need_threshold": 0.15, "sighting_horizon": 96,
        "learning_rate": 0.10,
        "bond_scale": 0.04, "bond_rate": 0.15, "bond_weight": 0.5,
        "companionship_weight": 0.4, "company_scale": 10.0,
        "bond_fade": 0.9997, "bond_horizon": 2880,
        "strain_multipliers": {"temperature": 2.2, "travel_discount": 0.85,
                               "critical_need_threshold": 1.5},
        # =====================================================================
        # LA MEMORIA, ENCENDIDA ENTERA. El tercer paso de la disciplina.
        #
        # Todo esto llevaba desde que se escribio a 0.0, y era correcto: nada se
        # estrena movido. Pero lo apagado deja de ser prudencia y pasa a ser
        # deuda en cuanto esta medido, y a estas alturas los cinco mecanismos
        # graban desde hace meses sin que NADIE pague por ellos al decidir.
        #
        # Se enciende TODO a la vez y se mide de una vez, que es lo que pide
        # D-000: cinco perillas encendidas de una en una son cinco mediciones
        # que no dicen nada sobre el conjunto.
        # =====================================================================
        #
        # CAPACIDAD. De 40 a 200, y no es generosidad: con 40 la edad mediana de
        # un recuerdo son TRES DIAS, y nada acumulativo -biografia, duelo,
        # reputacion, rumores- puede significar nada en tres dias. Con 200 son
        # doce, medido.
        "memory_capacity": 200, "memory_scale": 1.0, "memory_fade": 0.9995,
        #
        # LA ESCALA DEL APRECIO. El aprecio de este mundo llega a 0.4564 como
        # mucho, y la saliencia de un recuerdo corriente ronda 0.41 de mediana:
        # por el divisor general, la peor perdida posible entraba por debajo de
        # lo mas barato que hubiera guardado. A 0.5 un duelo dura semanas en vez
        # de un dia, y cuesta ~560 rumores de los 3953 que caben. A 0.1 duraba
        # ochenta dias y costaba el doble; se elige el punto medio.
        "regard_scale": 0.5,
        #
        # EL ESCARMIENTO, por accion. ACOTA, nunca veta: el beneficio crece con
        # la urgencia y esto no, asi que el hambre siempre acaba ganando a la
        # mala experiencia -y quien no reintenta nunca descubre que la cosa
        # mejoro-.
        "regret_weight": 0.35, "regret_scale": 0.5,
        #
        # EL MIEDO, por lugar. Viaja con el peaje, que es donde tiene que estar:
        # los dos son el precio de IR. Un poco por debajo del escarmiento porque
        # encarece un lugar entero y no una accion.
        "fear_weight": 0.30, "fear_scale": 0.5,
        #
        # EL DUELO, por persona. No lleva `_weight` al lado y es deliberado: de
        # una accion y de un lugar uno puede apartarse, de un ausente no. Lo que
        # diferencia dos duelos es de que viene acompanyado el recuerdo -si trae
        # lugar, `miedo` le cambia la rutina- y cuanto le dura, que es suyo.
        "grief_scale": 0.5,
        #
        # LOS RUMORES. 0.10 es una de cada diez veces que alguien termina algo
        # compartido, no una de cada diez conversaciones: con la ocupacion de
        # este mundo eso ya son miles al mes. Y de oidas pesa la mitad, asi que
        # una cadena de tres bocas llega practicamente desdibujada.
        "rumor_rate": 0.10, "rumor_decay": 0.5,
    },
    "needs": needs, "traits": traits, "actions": actions,
    "relations": relations,
    "places": places, "agents": agents,
    # LA PRIMERA SITUACION DE ESTE MUNDO, y es personal: no le pasa a un lugar,
    # le pasa a alguien. Drena 0.0022 por tick, asi que una herida sin tratar se
    # lleva a su duenyo en unos seis dias -y `veces` multiplica, asi que bajar
    # dos veces sin vendarse lo hace en tres-.
    #
    # Sin plazo a proposito: NO se pasa sola. Es lo que obliga a ir a que te la
    # quiten, y lo que convierte la mazmorra en una decision en vez de un grifo.
    # Las condiciones y los eventos viven en , que lleva la
    # plantilla y las reglas al lado.
    "situations": condiciones + eventos,
}

(S / "pack.yaml").write_text(
    yaml.safe_dump(pack, allow_unicode=True, sort_keys=False), encoding="utf-8"
)

from agora.engine.pack import PackError, load_pack  # noqa: E402

try:
    cargado = load_pack(S / "pack.yaml")
except PackError as e:
    print(f"PACK INVALIDO:\n{e}")
    raise SystemExit(1) from e

from collections import Counter  # noqa: E402

print(f"CARGA OK: {cargado.label}  {len(cargado.places)} lugares, "
      f"{len(cargado.actions)} acciones, {len(cargado.agents)} agentes, "
      f"{len(cargado.needs)} necesidades, {len(cargado.traits)} rasgos")
por_raza = Counter(
    r["id"] for a in agents for r in razas if r["id"] in a["traits"]
)
por_clase = Counter(
    c["id"] for a in agents for c in clases if c["id"] in a["traits"]
)
por_afin = Counter(
    f["id"].removeprefix("afin_")
    for a in agents for f in afinidades
    if a["traits"].get(f["id"], 0) == 1.0
)
dobles = sum(
    1 for a in agents
    if sum(1 for f in afinidades if f["id"] in a["traits"]) > 1
)
print(f"  razas   {dict(por_raza.most_common())}")
print(f"  clases  {dict(por_clase.most_common())}")
print(f"  afinidad de nacimiento  {dict(por_afin.most_common())}")
print(f"  con segunda afinidad    {dobles} de {len(agents)}")
