"""El borrador del mundo (unidad 22, A.2): un LLM autor redacta `mundo.yaml` a partir de
lo que el pack ya declara. Va fuera de la partida: no toca el estado, y lo que escribe
no se usa hasta que quien juega lo revisa y lo guarda como `mundo.yaml`.

El briefing lleva solo lo que el pack dice: nombres de rasgos, de grupos, de
necesidades, de lugares y sus conexiones. Ningún nombre de persona: el censo no entra
al briefing, y lo que devuelve el modelo se comprueba contra el censo y contra los
lugares del pack antes de escribir nada.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agora.engine.ontology import WorldLore
from agora.engine.pack import ContentPack
from agora.engine.ports import CognitionProvider

PROMPTS = Path(__file__).parent / "prompts"
BORRADOR = (PROMPTS / "borrador.txt").read_text(encoding="utf-8")
DESCRIBIR = (PROMPTS / "describir.txt").read_text(encoding="utf-8")

LOTE = 15
"""Lugares por petición: con más, la respuesta se corta (unidad 22)."""

DESCRIPCION_MAX = 300
"""Lo mismo que el pack acepta por lugar (`PlaceSpec.description`)."""


class LoreDraft(BaseModel):
    """Lo que el modelo devuelve para el texto del mundo: el esquema de la petición."""

    model_config = ConfigDict(extra="ignore")
    premise: str = Field(min_length=1, max_length=4000)
    tone: str = Field(min_length=1, max_length=300)
    known: list[str] = Field(default_factory=list)


class PlacesDraft(BaseModel):
    """Las descripciones de un lote de lugares: `{id de lugar: descripción}`."""

    model_config = ConfigDict(extra="ignore")
    places: dict[str, str] = Field(default_factory=dict)


class BorradorError(ValueError):
    """El borrador no se puede aceptar: se dice por qué, y no se escribe nada."""


def briefing_del_mundo(pack: ContentPack) -> str:
    """Lo que el pack declara, y nada más: ni personas ni sus relaciones."""
    lines = [f"MUNDO: {pack.label}"]
    if pack.creation is not None:
        for grupo in pack.creation.groups:
            rasgos = ", ".join(pack.trait_by_id[t].label for t in grupo.traits)
            lines.append(f"GRUPO DE RASGOS «{grupo.label}»: {rasgos}")
    for tipo in pack.faction_kinds:
        lines.append(f"TIPO DE GRUPO: {tipo.label}")
    lines.append("NECESIDADES: " + ", ".join(n.label for n in pack.needs))
    globales = [s.label for s in pack.situations if not s.personal]
    if globales:
        lines.append("SITUACIONES DEL MUNDO: " + ", ".join(globales))
    lines.append("LUGARES:")
    for lugar in pack.places:
        conexiones = ", ".join(
            f"{pack.place_by_id[n].label} ({t} tick{'s' if t != 1 else ''})"
            for n, t in sorted(lugar.neighbors.items(), key=lambda par: str(par[0]))
        )
        linea = f"  - {lugar.id}: {lugar.label}"
        if lugar.description:
            linea += f". Ya descrito: {lugar.description}"
        if conexiones:
            linea += f". Conexiones: {conexiones}"
        lines.append(linea)
    return "\n".join(lines)


def _nombres_de_personas(pack: ContentPack) -> tuple[str, ...]:
    return tuple(sorted({a.label.split(",")[0].strip() for a in pack.agents}))


def _mencionados(texto: str, nombres: Iterable[str]) -> tuple[str, ...]:
    return tuple(n for n in nombres
                 if re.search(rf"\b{re.escape(n)}\b", texto, re.IGNORECASE) is not None)


def pedir_borrador(
    pack: ContentPack, proveedor: CognitionProvider, seed: int
) -> tuple[WorldLore, dict[str, str]]:
    """El texto del mundo y las descripciones que faltan. `BorradorError` si el modelo
    no contesta, si nombra a una persona, o si inventa un lugar."""
    briefing = briefing_del_mundo(pack)
    lore = proveedor.think(BORRADOR.format(contexto=briefing), LoreDraft, seed)
    if not isinstance(lore, LoreDraft):
        raise BorradorError("el modelo no devolvió el texto del mundo (sin respuesta válida)")
    nombres = _nombres_de_personas(pack)
    texto_lore = "\n".join([lore.premise, lore.tone, *lore.known])
    if _mencionados(texto_lore, nombres):
        raise BorradorError("el texto del mundo nombra a personas: "
                            + ", ".join(_mencionados(texto_lore, nombres)))

    ids = {str(lugar.id) for lugar in pack.places}
    faltan = [lugar for lugar in pack.places if not lugar.description]
    descripciones: dict[str, str] = {}
    for inicio in range(0, len(faltan), LOTE):
        lote = faltan[inicio:inicio + LOTE]
        bloque = "\n".join(f"  - {p.id}: {p.label}" for p in lote)
        out = proveedor.think(DESCRIBIR.format(contexto=briefing_del_mundo(pack),
                                               lugares=bloque), PlacesDraft, seed + inicio)
        if not isinstance(out, PlacesDraft):
            raise BorradorError("el modelo no devolvió las descripciones de un lote de lugares")
        sin_describir = [str(p.id) for p in lote if str(p.id) not in out.places]
        if sin_describir:
            raise BorradorError("el modelo no describió: " + ", ".join(sin_describir))
        for lugar, texto in sorted(out.places.items()):
            if lugar not in ids:
                raise BorradorError(f"el modelo inventó el lugar «{lugar}»")
            # Lo mismo que el pack exige: una descripción vacía o larga no carga después.
            if not texto.strip() or len(texto) > DESCRIPCION_MAX:
                raise BorradorError(f"la descripción de «{lugar}» está vacía o pasa de "
                                    f"{DESCRIPCION_MAX} caracteres")
            if _mencionados(texto, nombres):
                raise BorradorError(f"la descripción de «{lugar}» nombra a personas: "
                                    + ", ".join(_mencionados(texto, nombres)))
            descripciones[lugar] = texto
    lore_final = WorldLore(premise=lore.premise, tone=lore.tone, known=tuple(lore.known))
    return lore_final, descripciones


CABECERA = ("# borrador de mundo, escrito por un modelo: revísalo y guárdalo como "
            "`mundo.yaml` junto al pack.\n# No se usa hasta que lo guardes.\n")


def escribir_borrador(
    salida: Path, lore: WorldLore, descripciones: dict[str, str]
) -> None:
    """Escribe el borrador, nunca `mundo.yaml`: quien juega lo copia a mano."""
    if salida.name == "mundo.yaml":
        raise BorradorError("el borrador no escribe mundo.yaml: escribe otro nombre y revísalo")
    datos = {
        "premise": lore.premise,
        "tone": lore.tone,
        "known": list(lore.known),
        "places": dict(sorted(descripciones.items())),
    }
    salida.write_text(CABECERA + yaml.safe_dump(datos, allow_unicode=True, sort_keys=False),
                      encoding="utf-8")

