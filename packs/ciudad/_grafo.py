from agora.engine.ontology import PlaceSpec, PlaceId
from agora.engine.topology import TravelMap, is_strongly_connected

def P(i, l, af, nb, **k): return {"id": i, "label": l, "affordances": af, "neighbors": nb, **k}

# --- LA ACADEMIA: un mundo cerrado. Todo lo que un alumno necesita, dentro ---
ACADEMIA = [
    P("aca_patio",     "el patio de la academia", ["aire","corrillo","quietud"],
      {"aca_celdas":1,"aca_aulas":1,"aca_biblioteca":1,"aca_palestra":1,
       "aca_refectorio":1,"plaza":2}),
    P("aca_celdas",    "las celdas",              ["cama","quietud"], {"aca_patio":1}),
    P("aca_aulas",     "las aulas",               ["leccion"],        {"aca_patio":1}),
    P("aca_biblioteca","la biblioteca",           ["archivo","quietud"], {"aca_patio":1}),
    P("aca_palestra",  "la palestra",             ["palestra"],       {"aca_patio":1}),
    P("aca_refectorio","el refectorio",           ["mesa","fogon","corrillo"], {"aca_patio":1}),
]

CIUDAD = [
    P("plaza",       "la plaza mayor",  ["corrillo","aire","quietud"],
      {"gremio":1,"aca_patio":2,"mercado":1,"taberna":1,"posada":1,"templo":2,
       "barrio_alto":2,"barrio_bajo":1,"herreria":2,"puerta_norte":2,"puerta_sur":2}),
    P("gremio",      "el gremio",       ["contratos","tasacion","corrillo"],
      {"plaza":1,"mercado":1,"puerta_sur":2}),
    P("mercado",     "el mercado",      ["mercaduria","corrillo"], {"plaza":1,"gremio":1}),
    P("taberna",     "la taberna",      ["mesa","barra","barril","corrillo"],
      {"plaza":1,"posada":1,"barrio_bajo":1}),
    P("posada",      "la posada",       ["cama","fogon","mesa"], {"plaza":1,"taberna":1}),
    P("templo",      "el templo",       ["altar","quietud"], {"plaza":2}),
    P("barrio_alto", "el barrio alto",  ["cama","fogon","quietud"], {"plaza":2},
      gain_multipliers={"descanso":1.2}),
    P("barrio_bajo", "el barrio bajo",  ["cama","fogon","corrillo"], {"plaza":1,"taberna":1}),
    P("herreria",    "la herreria",     ["fragua"], {"plaza":2}),
    P("puerta_norte","la puerta norte", ["aire"], {"plaza":2,"camino_bosque":3}),
    P("puerta_sur",  "la puerta sur",   ["aire"], {"plaza":2,"gremio":2,"sendero":3}),
]

# --- SALVAJE: se puede acampar. Mal, salvo que estes curtido. ---------------
ACAMPADA = {"descanso": 0.45}
SALVAJE = [
    P("camino_bosque","el camino del bosque",["aire","hoguera","cama"],
      {"puerta_norte":1,"bosque":2}, gain_multipliers=ACAMPADA),
    P("bosque",       "el bosque",           ["aire","caza_menor","cama"],
      {"camino_bosque":2,"espesura":3}, gain_multipliers=ACAMPADA),
    P("espesura",     "la espesura",         ["caza_mayor"], {"bosque":3}),
    P("sendero",      "el sendero de piedra",["aire","hoguera","cama"],
      {"puerta_sur":1,"boca":1}, gain_multipliers=ACAMPADA),
    P("boca",         "la boca de la sima",  ["aire","hoguera","cama"],
      {"sendero":1,"cripta":1}, gain_multipliers=ACAMPADA),
    P("cripta",       "la cripta",           ["expolio_1"], {"boca":1,"galerias":2}),
    P("galerias",     "las galerias",        ["expolio_2"], {"cripta":2,"nucleo_sima":2}),
    P("nucleo_sima",  "el corazon de la sima",["expolio_3"], {"galerias":2}),
]

LUGARES = ACADEMIA + CIUDAD + SALVAJE
idx = {p["id"]: p for p in LUGARES}
for p in LUGARES:
    for v, c in list(p["neighbors"].items()):
        idx[v]["neighbors"].setdefault(p["id"], c)

if __name__ == "__main__":
    specs = tuple(PlaceSpec.model_validate(p) for p in LUGARES)
    print(f"conexo: {is_strongly_connected(specs)}   {len(specs)} lugares")
    tm = TravelMap(specs)
    print("\nel mundo de un ALUMNO (desde su celda):")
    for p in specs:
        d = tm.distance(PlaceId("aca_celdas"), p.id)
        if d and d <= 3: print(f"  {p.label:<28} {d}t")
    print("  ...y la plaza a 3t, el gremio a 4t")
    print("\nel mundo de un CAZADOR (desde el barrio bajo):")
    for z in ("gremio","puerta_sur","boca","cripta","galerias","nucleo_sima","bosque","espesura"):
        d = tm.distance(PlaceId("barrio_bajo"), PlaceId(z))
        print(f"  {idx[z]['label']:<28} {d:>3}t  ida y vuelta {d*2:>3}t = {d*2/4:.1f}h")
