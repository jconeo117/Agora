"""Los doce alumnos, traducidos de sus fichas.

Sus hojas no traian estilo ni elemento —son obligatorios en este mundo— asi que
se infieren de su descripcion y viven AQUI, en una tabla, para que corregir uno
sea una linea.

Sus gustos apuntaban a cosas que en esta ciudad no se llaman asi:

    ocio        -> beber y tomar_el_aire      socializar -> charlar
    investigar  -> estudiar (se queda el mayor)
    explorar    -> tomar_el_aire
    conflicto   -> NO EXISTE. El motor no tiene disputas, asi que la aversion de
                   Maya a los conflictos no tiene todavia donde morder.

Y casi todos escribieron `plazo: indefinido`. Sin plazo una meta nunca falla y su
`si_lo_pierde` no puede ocurrir jamas, asi que se les pone uno generoso —seis
anos, uno mas que la carrera— para que el final malo exista aunque sea raro.
"""

# 96 ticks/dia x 30 dias x 12 meses x 6 anos
SEIS_ANOS = 96 * 30 * 12 * 6

PERFIL = {
    #                    estilo             elemento       prodigio
    "arthur_leywin":    ("estilo_guerrero", "elem_viento", 0.5),
    "mikasa_lionheart": ("estilo_guerrero", "elem_tierra", 0.3),
    "norman_stark":     ("estilo_soporte",  "elem_agua",   0.4),
    "albedo_elric":     ("estilo_soporte",  "elem_fuego",  0.5),
    "max_andersonn":    ("estilo_asesino",  "elem_viento", 0.2),
    "alexia_tompson":   ("estilo_soporte",  "elem_tierra", 0.3),
    "ethan_moore":      ("estilo_asesino",  "elem_agua",   0.0),
    "lena_hartwell":    ("estilo_asesino",  "elem_viento", 0.2),
    "darius_cole":      ("estilo_guerrero", "elem_fuego",  0.3),
    "nora_bellamy":     ("estilo_asesino",  "elem_tierra", 0.2),
    "silas_reed":       ("estilo_soporte",  "elem_agua",   0.4),
    "maya_sterling":    ("estilo_soporte",  "elem_fuego",  0.1),
}

ETIQUETA = {
    "arthur_leywin": "Arthur Leywin", "mikasa_lionheart": "Mikasa Lionheart",
    "norman_stark": "Norman Stark", "albedo_elric": "Albedo Elric",
    "max_andersonn": "Max Andersonn", "alexia_tompson": "Alexia Tompson",
    "ethan_moore": "Ethan Moore", "lena_hartwell": "Lena Hartwell",
    "darius_cole": "Darius Cole", "nora_bellamy": "Nora Bellamy",
    "silas_reed": "Silas Reed", "maya_sterling": "Maya Sterling",
}

RASGOS = {
    "arthur_leywin": dict(sociabilidad=0.1, laboriosidad=0.9, hedonismo=-0.3,
                          frugalidad=0.2, impulsividad=-0.4, aguante=0.9, arraigo=0.1),
    "mikasa_lionheart": dict(sociabilidad=-0.7, laboriosidad=0.7, hedonismo=-0.2,
                             frugalidad=0.3, apego_al_hogar=0.6, impulsividad=-0.7,
                             aguante=0.8, arraigo=0.8),
    "norman_stark": dict(sociabilidad=-0.2, laboriosidad=0.7, frugalidad=0.3,
                         apego_al_hogar=0.1, impulsividad=-0.8, aguante=0.5, arraigo=0.2),
    "albedo_elric": dict(sociabilidad=0.1, laboriosidad=0.9, hedonismo=-0.2,
                         frugalidad=0.1, apego_al_hogar=0.2, impulsividad=-0.3,
                         aguante=0.7, arraigo=0.2),
    "max_andersonn": dict(sociabilidad=0.9, laboriosidad=0.2, hedonismo=0.8,
                          frugalidad=-0.4, apego_al_hogar=-0.2, impulsividad=0.7,
                          aguante=0.3, arraigo=-0.2),
    "alexia_tompson": dict(sociabilidad=0.2, laboriosidad=0.8, hedonismo=-0.1,
                           frugalidad=0.1, apego_al_hogar=0.1, impulsividad=-0.2,
                           aguante=0.6, arraigo=0.2),
    "ethan_moore": dict(sociabilidad=0.1, laboriosidad=-0.4, hedonismo=0.3,
                        frugalidad=0.5, apego_al_hogar=0.4, impulsividad=-0.2,
                        aguante=0.2, arraigo=0.4),
    "lena_hartwell": dict(sociabilidad=0.5, laboriosidad=0.3, hedonismo=0.5,
                          frugalidad=-0.2, apego_al_hogar=-0.2, impulsividad=0.8,
                          aguante=0.2, arraigo=-0.3),
    "darius_cole": dict(sociabilidad=0.2, laboriosidad=0.7, hedonismo=-0.2,
                        frugalidad=0.3, apego_al_hogar=0.3, impulsividad=-0.5,
                        aguante=0.9, arraigo=0.3),
    "nora_bellamy": dict(sociabilidad=0.3, laboriosidad=0.4, hedonismo=0.2,
                         frugalidad=0.4, impulsividad=0.2, aguante=0.4, arraigo=-0.1),
    # Su meta ES la discrecion, asi que el rasgo que la hace pesar no es adorno.
    "silas_reed": dict(sociabilidad=-0.9, laboriosidad=0.6, hedonismo=-0.2,
                       frugalidad=0.5, apego_al_hogar=0.8, impulsividad=-0.5,
                       aguante=0.6, arraigo=0.9, reservado=0.8),
    "maya_sterling": dict(sociabilidad=0.8, laboriosidad=0.5, hedonismo=0.5,
                          frugalidad=-0.1, apego_al_hogar=0.4, impulsividad=0.1,
                          aguante=0.3, arraigo=0.4),
}

GUSTOS = {
    "arthur_leywin": {"estudiar": 2.0, "entrenar": 2.5, "beber": 0.4, "tomar_el_aire": 0.4},
    "mikasa_lionheart": {"estudiar": 1.8, "entrenar": 2.0, "beber": 0.3, "charlar": 0.2},
    "norman_stark": {"estudiar": 2.5, "entrenar": 1.2, "beber": 0.6, "meditar": 1.6},
    "albedo_elric": {"estudiar": 2.5, "entrenar": 1.8, "beber": 0.4},
    "max_andersonn": {"charlar": 2.5, "beber": 2.0, "estudiar": 1.0, "entrenar": 0.7},
    "alexia_tompson": {"estudiar": 2.5, "entrenar": 1.6, "beber": 0.5},
    "ethan_moore": {"estudiar": 1.4, "beber": 1.3, "entrenar": 0.4},
    "lena_hartwell": {"estudiar": 1.4, "tomar_el_aire": 2.0, "beber": 1.5, "entrenar": 1.0},
    "darius_cole": {"entrenar": 2.5, "estudiar": 1.7, "beber": 0.5},
    "nora_bellamy": {"estudiar": 1.6, "beber": 1.2, "entrenar": 1.1, "tomar_el_aire": 1.7},
    "silas_reed": {"estudiar": 2.0, "beber": 0.8, "charlar": 0.1, "tomar_el_aire": 0.4},
    "maya_sterling": {"charlar": 2.5, "beber": 1.7, "estudiar": 1.4},
}

# (id de meta, eje, umbral, on_success, on_failure)
#
# Solo los que tenian una meta expresable como un umbral. Los que querian "una
# vida estable" o "un ambiente agradable" no llevan meta: el motor no sabe medir
# la calma ni la armonia, y ponerles cualquier otra cosa seria mentir sobre lo
# que su ficha decia.
METAS = {
    "arthur_leywin": ("mejorar_sin_techo", "armas", 0.80,
                      {"ambicion": 0.3, "aguante": 0.2},
                      {"impulsividad": 0.4, "aguante": -0.3}),
    "norman_stark": ("comprenderlo_todo", "arcano", 0.85,
                     {"sociabilidad": 0.3},
                     {"impulsividad": 0.5, "laboriosidad": -0.2}),
    "albedo_elric": ("la_excelencia", "arcano", 0.90,
                     {"hedonismo": 0.3, "laboriosidad": -0.2},
                     {"laboriosidad": 0.5, "aguante": 0.3}),
    "alexia_tompson": ("destacar", "curso", 0.95,
                       {"graduado": 1.0, "sociabilidad": 0.3},
                       {"laboriosidad": 0.5, "hedonismo": -0.3}),
    "ethan_moore": ("salir_del_paso", "curso", 0.95,
                    {"graduado": 1.0, "apego_al_hogar": 0.3},
                    {"laboriosidad": 0.6, "aguante": 0.3}),
    "darius_cole": ("estar_preparado", "temple", 0.75,
                    {"sociabilidad": 0.3, "aguante": 0.2},
                    {"aguante": -0.4, "apego_al_hogar": 0.4}),
    # La unica meta del mundo que apunta a la discrecion, y por eso existe el eje.
    "silas_reed": ("que_le_dejen_en_paz", "discrecion", 0.95,
                   {"sociabilidad": 0.3, "arraigo": -0.3},
                   {"sociabilidad": -0.4, "apego_al_hogar": 0.4}),
    "mikasa_lionheart": ("terminar_sin_sobresaltos", "curso", 0.95,
                         {"graduado": 1.0, "arraigo": -0.2},
                         {"apego_al_hogar": 0.5, "aguante": -0.3}),
    "max_andersonn": ("disfrutarlo", "curso", 0.95,
                      {"graduado": 1.0, "hedonismo": 0.3},
                      {"laboriosidad": 0.7, "hedonismo": -0.5}),
}


def fichas() -> list[dict]:
    salida = []
    for ident, (estilo, elemento, prodigio) in PERFIL.items():
        traits = {"alumno": 1.0, estilo: 1.0, elemento: 1.0, **RASGOS[ident]}
        if prodigio:
            traits["prodigio"] = prodigio
        ficha: dict = {
            "id": ident, "label": ETIQUETA[ident],
            "home": "aca_celdas", "start_at": "aca_celdas",
            "traits": traits,
            "tastes": [{"target": k, "multiplier": v}
                       for k, v in sorted(GUSTOS[ident].items())],
        }
        if ident in METAS:
            gid, need, umbral, ok, ko = METAS[ident]
            ficha["goals"] = [{
                "id": gid, "label": gid.replace("_", " "), "need": need,
                "at_least": umbral, "weight_multiplier": 2.2, "deadline": SEIS_ANOS,
                "on_success": ok, "on_failure": ko,
            }]
        salida.append(ficha)
    return salida
