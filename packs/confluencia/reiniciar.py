"""Soft reset de confluencia (unidad 11, D-160).

A los 200 habitantes les añade los nueve rasgos densos de la mecánica: los
siete potenciales con el nombre de los atributos del borrador y `piedad` y
`arrojo`. Todo lo demás del pack se queda como está. No se usa `generar.py`
porque ya no reproduce este `pack.yaml` (I-003): este script edita el texto en
su sitio, y por eso conserva los comentarios.

Reproducible: cada valor sale de `blake2b(SEMILLA, agente, rasgo)`. Volver a
correrlo sobre un pack que ya los tiene no hace nada.

    uv run python -I packs/confluencia/reiniciar.py packs/confluencia/pack.yaml
"""

import hashlib
import random
import sys
from pathlib import Path

import yaml

SEMILLA = 2026_10_10

POTENCIALES = ("fuerza", "agilidad", "ingenio", "instinto", "voluntad", "presencia", "resonancia")
ESTILO = ("piedad", "arrojo")

ETIQUETAS = {
    "fuerza": "potencial de fuerza", "agilidad": "potencial de agilidad",
    "ingenio": "potencial de ingenio", "instinto": "potencial de instinto",
    "voluntad": "potencial de voluntad", "presencia": "potencial de presencia",
    "resonancia": "potencial de resonancia", "piedad": "piedad", "arrojo": "arrojo",
}

# Cuánto mueve la raza la media del potencial. Un sesgo, no un destino: la
# desviación (DESVIO) es mayor que casi todos estos números.
SESGO = {
    "gigante": {"fuerza": 0.25, "voluntad": 0.05, "agilidad": -0.10, "ingenio": -0.05},
    "enano": {"fuerza": 0.10, "voluntad": 0.15, "resonancia": -0.10},
    "elfo": {"agilidad": 0.15, "resonancia": 0.20, "ingenio": 0.05, "fuerza": -0.10},
    "demihumano": {"instinto": 0.20, "agilidad": 0.10, "ingenio": -0.05},
    "humano": {"presencia": 0.05, "ingenio": 0.05},
}
DESVIO = 0.18
DESVIO_ESTILO = 0.20


def sorteo(agente: str, rasgo: str, media: float, desvio: float) -> float:
    material = f"{SEMILLA}\x1f{agente}\x1f{rasgo}".encode()
    rng = random.Random(int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big"))
    return round(min(1.0, max(0.0, rng.gauss(media, desvio))), 2)


def main(path: Path) -> None:
    texto = path.read_text(encoding="utf-8")
    datos = yaml.safe_load(texto)
    if any(t["id"] == "fuerza" for t in datos["traits"]):
        print("ya tiene los rasgos; no hago nada")
        return
    raza = {}
    for a in datos["agents"]:
        raza[a["id"]] = next((r for r in SESGO if a.get("traits", {}).get(r)), None)

    lineas = texto.splitlines(keepends=True)
    salida: list[str] = []
    en_agentes = False
    agente = None
    puestos = 0
    for linea in lineas:
        if linea.startswith("agents:"):
            en_agentes = True
        elif en_agentes and linea[:1] not in (" ", "-", "\n", "#"):
            en_agentes = False
        if linea.startswith("actions:"):
            for rasgo in (*POTENCIALES, *ESTILO):
                salida.append(f"- id: {rasgo}\n  label: {ETIQUETAS[rasgo]}\n")
        salida.append(linea)
        if en_agentes and linea.startswith("- id: "):
            agente = linea.split(":", 1)[1].strip()
        if en_agentes and linea == "  traits:\n" and agente is not None:
            sesgo = SESGO.get(raza[agente] or "", {})
            for rasgo in POTENCIALES:
                salida.append(f"    {rasgo}: {sorteo(agente, rasgo, 0.5 + sesgo.get(rasgo, 0.0), DESVIO)}\n")
            for rasgo in ESTILO:
                salida.append(f"    {rasgo}: {sorteo(agente, rasgo, 0.5, DESVIO_ESTILO)}\n")
            puestos += 1
        if linea == "    hereda_traits:\n":
            for rasgo in (*POTENCIALES, *ESTILO):
                salida.append(f"    - {rasgo}\n")
    if puestos != len(datos["agents"]):
        raise SystemExit(f"{puestos} agentes con rasgos de {len(datos['agents'])}: el formato cambió")
    path.write_text("".join(salida), encoding="utf-8")
    print(f"{puestos} agentes reiniciados")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
