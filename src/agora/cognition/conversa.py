"""Entender qué acto es lo que el jugador le dice a un NPC (unidad 15, D-164).

Es el intérprete de la 14 con otro menú: en vez de acciones del mundo, los
actos del vocabulario cerrado del motor (`SocialAct`) más despedirse. El modelo
elige un acto (y, si habla de un tercero, quién); lo que pesa ese acto lo decide
`engine/social.py`, sin modelo. Con `ACT_HELP` como único léxico, sin modelo se
entiende lo mismo que con el de la 14: por raíces, y peor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, create_model

from agora.cognition.intencion import Entry, Menu
from agora.engine.ontology import AgentId, ClaimKind, PlaceId, QuestionKind, SocialAct
from agora.engine.ports import CognitionProvider
from agora.engine.social import Claim

CONVERSA = (Path(__file__).parent / "prompts" / "conversa.txt").read_text(encoding="utf-8")

FAREWELL = "despedirse"
"""Cierra la conversación. No es un `SocialAct`: no le hace nada a nadie."""

ACT_HELP: dict[str, tuple[str, tuple[str, ...]]] = {
    SocialAct.GREET: ("saludar", ("hola", "buenas", "saludo a")),
    SocialAct.CHAT: ("charlar de cualquier cosa", ("qué tal el día", "hablamos un rato",
                                                   "cuéntame algo")),
    SocialAct.FLATTER: ("halagar o hablar bien de alguien", ("qué bien lo haces", "eres muy hábil",
                                                             "es buena gente")),
    SocialAct.JOKE: ("bromear", ("te cuento un chiste", "es broma", "ja, qué gracia")),
    SocialAct.COURT: ("cortejar, coquetear", ("me gustas", "estás muy guapa",
                                              "quieres cenar conmigo")),
    SocialAct.APOLOGIZE: ("disculparse", ("lo siento", "perdona", "me equivoqué contigo")),
    SocialAct.CONFESS: ("confesar algo propio", ("tengo que contarte algo", "te confieso que",
                                                 "no se lo he dicho a nadie")),
    SocialAct.INSULT: ("insultar o hablar mal de alguien", ("eres un inútil", "idiota",
                                                            "es una rata")),
    SocialAct.THREATEN: ("amenazar", ("te voy a matar", "como vuelvas te arrepientes",
                                      "cuidado conmigo")),
    SocialAct.ASK: ("preguntar algo", ("has visto a", "dónde está", "sabes algo de")),
    SocialAct.AFFIRM: ("afirmar un hecho", ("yo estuve allí", "te digo que", "es verdad que")),
    SocialAct.GIVE: ("dar algo de lo tuyo", ("toma", "te doy", "quédate con esto")),
    SocialAct.ASK_FOR: ("pedir algo", ("dame", "me prestas", "¿me das")),
    FAREWELL: ("despedirse y dejar la conversación", ("adiós", "hasta luego", "me voy")),
}

ABOUT = frozenset({
    SocialAct.FLATTER, SocialAct.INSULT, SocialAct.ASK, SocialAct.AFFIRM,
})
"""Los actos que pueden ir sobre un tercero."""

HEARD: dict[SocialAct, str] = {
    SocialAct.GREET: "te saluda",
    SocialAct.CHAT: "charla contigo",
    SocialAct.FLATTER: "te halaga",
    SocialAct.JOKE: "te hace una broma",
    SocialAct.COURT: "te corteja",
    SocialAct.APOLOGIZE: "te pide disculpas",
    SocialAct.CONFESS: "te confiesa algo",
    SocialAct.INSULT: "te insulta",
    SocialAct.THREATEN: "te amenaza",
    SocialAct.ASK: "te pregunta algo",
    SocialAct.AFFIRM: "te afirma algo",
    SocialAct.GIVE: "te da algo",
    SocialAct.ASK_FOR: "te pide algo",
}
"""Cómo lo oye quien escucha, para el briefing de la voz."""


def heard_as(act: SocialAct, about_label: str | None = None) -> str:
    if about_label is not None and act is SocialAct.FLATTER:
        return f"te habla bien de {about_label}"
    if about_label is not None and act is SocialAct.INSULT:
        return f"te habla mal de {about_label}"
    return HEARD[act]


def talk_menu(
    people: Sequence[tuple[str, str]], listener: str,
    dados: Sequence[tuple[str, str]] = (), pedibles: Sequence[tuple[str, str]] = (),
) -> Menu:
    """Una entrada por acto y por despedirse; los actos que pueden ir sobre un
    tercero, además, una por cada persona que no sea quien escucha.

    `dados` son los objetos del jugador (para dar) y `pedibles`, los del oyente
    que no lleva puestos (para pedir). Cada uno es una entrada del acto con su
    `item`: dar y pedir sin objeto no dicen nada, así que no hay entrada vacía.
    """
    entries: list[Entry] = []
    for key in ACT_HELP:
        if key is SocialAct.GIVE:
            entries += [Entry(str(key), item=pid) for pid, _ in dados]
            continue
        if key is SocialAct.ASK_FOR:
            entries += [Entry(str(key), item=pid) for pid, _ in pedibles]
            continue
        entries.append(Entry(str(key)))
        if key in ABOUT:
            entries += [Entry(str(key), target=pid) for pid, _ in people if pid != listener]
    presentes = {e.action for e in entries}
    return Menu(
        entries=tuple(entries),
        actions=tuple((str(k), label, examples) for k, (label, examples) in ACT_HELP.items()
                      if str(k) in presentes),
        people=tuple(people),
    )


# --- afirmar y preguntar (unidad 15b) -------------------------------------------

AFIRMAR = (Path(__file__).parent / "prompts" / "afirmar.txt").read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class Said:
    """Lo que se afirma o se pregunta, ya como lo entiende el motor. Con las dos
    cosas a `None`, la frase no era ni una ni otra."""

    claim: Claim | None = None
    question: tuple[QuestionKind, AgentId] | None = None


def said_schema(
    people: Sequence[tuple[str, str]], places: Sequence[tuple[str, str]]
) -> type[BaseModel]:
    """El esquema anidado (unidad 15b): la afirmación y la pregunta cada una con
    sus campos, y los enumerados hechos con las personas y los lugares de este
    momento. Con un esquema plano con todo opcional, el modelo dejaba la persona
    vacía y un «Renna es buena gente» acababa en «Renna está en…»: medido,
    21/30 contra 29/30 con este."""
    persona: Any = Literal[tuple(pid for pid, _ in people)] if people else str
    lugar: Any = Literal[tuple(pid for pid, _ in places)] if places else str
    afirmacion = create_model(
        "Afirmacion",
        que=(Literal[tuple(k.value for k in ClaimKind)], ...),
        persona=(persona, ...),
        lugar=(lugar | None, None),
        victima=(persona | None, None),
    )
    pregunta = create_model(
        "Pregunta",
        que=(Literal[tuple(k.value for k in QuestionKind)], ...),
        persona=(persona, ...),
    )
    model: type[BaseModel] = create_model(
        "Dicho",
        __config__=ConfigDict(extra="ignore"),
        tipo=(Literal["afirmar", "preguntar", "otro"], ...),
        afirmacion=(afirmacion | None, None),
        pregunta=(pregunta | None, None),
    )
    return model


def said_briefing(
    people: Sequence[tuple[str, str]], places: Sequence[tuple[str, str]], prose: str,
    listener: str | None = None,
) -> str:
    return AFIRMAR.format(
        personas="\n".join(
            f"  {pid}: {label}" + (" (con quien hablas)" if pid == listener else "")
            for pid, label in people),
        lugares="\n".join(f"  {pid}: {label}" for pid, label in places),
        prosa=prose,
    )


def interpret_said(
    people: Sequence[tuple[str, str]], places: Sequence[tuple[str, str]], prose: str,
    provider: CognitionProvider | None, seed: int, listener: str | None = None,
) -> Said | None:
    """Qué afirma o pregunta el jugador (unidad 15b). **Solo con modelo**: no hay
    léxico para esto, porque un falso sí aquí acusa a alguien de algo que no
    hizo. `None`: no se entendió (sin modelo, o falló); `Said()` vacío: el modelo
    dice que no es ni una afirmación ni una pregunta."""
    if provider is None:
        return None
    out = provider.think(
        said_briefing(people, places, prose, listener), said_schema(people, places), seed)
    if not isinstance(out, BaseModel):
        return None
    d = out.model_dump()
    try:
        if d["tipo"] == "afirmar":
            a = d["afirmacion"]
            if a is None:
                return None
            kind = ClaimKind(a["que"])
            if (kind is ClaimKind.AT and a["lugar"] is None) or (
                    kind is ClaimKind.HARMED and a["victima"] is None):
                return None
            return Said(claim=Claim(
                kind, AgentId(a["persona"]),
                None if kind is not ClaimKind.AT else PlaceId(a["lugar"]),
                None if kind is not ClaimKind.HARMED else AgentId(a["victima"]),
            ))
        if d["tipo"] == "preguntar":
            p = d["pregunta"]
            if p is None:
                return None
            return Said(question=(QuestionKind(p["que"]), AgentId(p["persona"])))
    except (KeyError, ValueError, TypeError):
        return None
    return Said()
