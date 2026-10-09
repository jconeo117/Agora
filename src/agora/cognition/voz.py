"""Que un NPC hable en personaje, con un LLM o sin él (unidad 07).

El modelo recibe un briefing cerrado, hecho de la ficha y de nada más, y
devuelve una estructura validable. Si falla, no valida o no hay modelo, habla
el respaldo: frases del pack, con el tono que da una regla. Lo dicho no se
escribe en ningún sitio, y por eso encender el modelo no cambia el mundo
(regla 4).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agora.engine.consulta import Ficha, Lack, ficha
from agora.engine.ontology import AgentId, Tone
from agora.engine.ports import CognitionProvider
from agora.engine.state import WorldState

PLANTILLA = (Path(__file__).parent / "prompts" / "voz.txt").read_text(encoding="utf-8")
SIN_VOZ = "…"
"""Lo que dice un NPC de un mundo sin `voice` cuando no hay modelo. No es prosa
del mundo: es no decir nada."""


class Habla(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    dice: str = Field(min_length=1, max_length=400)
    tono: Tone


def briefing(f: Ficha) -> str:
    def lista(xs: tuple[str, ...]) -> str:
        return ", ".join(xs)

    recuerdos = "; ".join(
        " ".join(
            p
            for p in (
                r.tipo,
                r.accion,
                f"en {r.lugar}" if r.lugar else None,
                f"con {r.persona}" if r.persona else None,
                "bueno" if r.valencia > 0 else "malo" if r.valencia < 0 else None,
            )
            if p
        )
        for r in f.recuerdos
    )
    aprecio = f.aprecio_al_interlocutor or 0
    trato = "aprecio" if aprecio > 0 else "inquina" if aprecio < 0 else "indiferencia"
    interlocutor = (
        f"Te habla {f.interlocutor}"
        + (f" ({lista(f.relaciones_con_interlocutor)})" if f.relaciones_con_interlocutor else "")
        + (f"; le tienes {trato}." if f.aprecio_al_interlocutor is not None else ".")
        + " Te pregunta qué tal te va."
        if f.interlocutor is not None
        else "Un desconocido se te acerca y te pregunta qué tal te va."
    )
    return PLANTILLA.format(
        nombre=f.nombre,
        identidad=f" ({lista(f.identidad)})" if f.identidad else "",
        caracter=f"Eres {lista(f.caracter)}." if f.caracter else "",
        lugar=f.lugar,
        fase=f", {f.fase}" if f.fase else "",
        actividad=(
            f"Ahora mismo: {f.actividad}." if f.actividad
            else f"Vas de camino a {f.de_camino_a}." if f.de_camino_a else ""
        ),
        carencias=", ".join(f"{b.value} {n}" for n, b in f.carencias) or "nada",
        recuerdos=f"Recuerdas: {recuerdos}." if recuerdos else "",
        vinculos=" ".join(
            p for p in (
                f"Aprecias a {lista(f.aprecia)}." if f.aprecia else "",
                f"Te cae mal {lista(f.detesta)}." if f.detesta else "",
            ) if p
        ),
        interlocutor=interlocutor,
    )


def tono_de_respaldo(f: Ficha) -> Tone:
    """La regla, en orden: quien te cae mal te encuentra hostil; quien está
    desesperado, triste; quien pasa mucha necesidad, seco; el resto, amable.
    `AFRAID` no lo da esta regla: lo puede elegir el modelo."""
    if f.aprecio_al_interlocutor is not None and f.aprecio_al_interlocutor <= -0.2:
        return Tone.HOSTILE
    peor = f.carencias[0][1] if f.carencias else Lack.MILD
    if peor is Lack.DESPERATE:
        return Tone.SAD
    if peor is Lack.SEVERE:
        return Tone.CURT
    return Tone.FRIENDLY


def respaldo(world: WorldState, f: Ficha) -> Habla:
    tono = tono_de_respaldo(f)
    voz = world.pack.voice
    frases = (voz.fallback.get(tono) or voz.fallback.get(Tone.FRIENDLY) or ()) if voz else ()
    if not frases:
        return Habla(dice=SIN_VOZ, tono=tono)
    elegida = world.rng.stream("voz-respaldo", f.agente, world.tick).choice(frases)
    return Habla(dice=elegida, tono=tono)


def hablar(
    world: WorldState,
    agente: AgentId,
    interlocutor: AgentId | None = None,
    proveedor: CognitionProvider | None = None,
) -> tuple[Habla, bool, str]:
    """(lo que dice, si lo dijo el modelo, el briefing). No escribe nada."""
    f = ficha(world, agente, interlocutor)
    texto = briefing(f)
    if proveedor is not None:
        semilla = world.rng.stream("voz-semilla", agente, world.tick).randrange(2**31)
        salida = proveedor.think(texto, Habla, semilla)
        if isinstance(salida, Habla):
            return salida, True, texto
    return respaldo(world, f), False, texto
