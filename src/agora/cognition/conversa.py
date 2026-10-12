"""Entender qué acto es lo que el jugador le dice a un NPC (unidad 15, D-164).

Es el intérprete de la 14 con otro menú: en vez de acciones del mundo, los
actos del vocabulario cerrado del motor (`SocialAct`) más despedirse. El modelo
elige un acto (y, si habla de un tercero, quién); lo que pesa ese acto lo decide
`engine/social.py`, sin modelo. Con `ACT_HELP` como único léxico, sin modelo se
entiende lo mismo que con el de la 14: por raíces, y peor.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agora.cognition.intencion import Entry, Menu
from agora.engine.ontology import SocialAct

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
    SocialAct.LIE: ("mentir a sabiendas", ("le diré que", "le miento", "invento que")),
    FAREWELL: ("despedirse y dejar la conversación", ("adiós", "hasta luego", "me voy")),
}

ABOUT = frozenset({
    SocialAct.FLATTER, SocialAct.INSULT, SocialAct.ASK, SocialAct.AFFIRM, SocialAct.LIE,
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
    SocialAct.LIE: "te cuenta algo",
}
"""Cómo lo oye quien escucha, para el briefing de la voz. `LIE` se oye como
«te cuenta algo»: el que escucha no sabe que le mienten."""


def heard_as(act: SocialAct, about_label: str | None = None) -> str:
    if about_label is not None and act is SocialAct.FLATTER:
        return f"te habla bien de {about_label}"
    if about_label is not None and act is SocialAct.INSULT:
        return f"te habla mal de {about_label}"
    return HEARD[act]


def talk_menu(people: Sequence[tuple[str, str]], listener: str) -> Menu:
    """Una entrada por acto y por despedirse; los actos que pueden ir sobre un
    tercero, además, una por cada persona que no sea quien escucha."""
    entries: list[Entry] = []
    for key in ACT_HELP:
        entries.append(Entry(str(key)))
        if key in ABOUT:
            entries += [Entry(str(key), target=pid) for pid, _ in people if pid != listener]
    return Menu(
        entries=tuple(entries),
        actions=tuple((str(k), label, examples) for k, (label, examples) in ACT_HELP.items()),
        people=tuple(people),
    )
