"""Cómo se toma un NPC lo que le dicen (unidad 15, D-164).

El modelo interpreta la frase como un acto de un vocabulario cerrado; aquí se
decide, sin azar y sin modelo, cuánto le mueve el aprecio, si se le queda
grabado y con qué tono contesta. Lo lee `World.apply_social`, que es la única
puerta que lo aplica; la voz solo pone las palabras a un tono ya decidido.

Lo que pesa, todo del motor y nada del mundo:

- **cuánto aprecia ya a quien le habla**: lo bueno satura (al amigo de siempre
  un halago no le cambia nada) y una broma de quien te cae mal sienta mal;
- **si le debe algo** (`agravio`): con rencor, lo amable pesa la mitad;
- **cómo está** (las carencias de la ficha): con una necesidad desesperada,
  lo amable pesa la mitad y contesta triste o seco;
- **su temperamento**: lo malo pesa por `loss_aversion` (mediana 1.0, de 0.55
  a 1.85), lo bueno por `bond_rate` relativo a la mediana (0.15);
- **de quién se habla**: halagar o insultar a un tercero mueve el aprecio
  hacia quien habla según lo que el oyente piense de ese tercero —el enemigo
  de mi amigo—;
- **la repetición** dentro de la misma conversación (`repeat_decay`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agora.engine.consulta import Lack, ficha
from agora.engine.ontology import AgentId, SocialAct, Tone
from agora.engine.state import WorldState

BOND_RATE = 0.15
"""La mediana de `bond_rate` en los packs medidos: el halago vale lo que dice
el pack para alguien que se encariña a ese ritmo."""

ABOUT_GAIN = 5.0
"""Cuánto aprecio por el tercero hace falta para que hablar de él pese entero:
0.2, el doble del p90 de `confluencia`."""

GRUDGE = 0.2
"""Agravio a partir del cual lo amable de esa persona pesa la mitad."""

HOSTILE_AT = -0.2
"""El mismo umbral que usa el respaldo de la voz para sonar hostil."""

POSITIVE = frozenset({
    SocialAct.GREET, SocialAct.CHAT, SocialAct.FLATTER, SocialAct.JOKE, SocialAct.COURT,
    SocialAct.APOLOGIZE, SocialAct.CONFESS,
})
NEGATIVE = frozenset({SocialAct.INSULT, SocialAct.THREATEN})


@dataclass(frozen=True, slots=True)
class Reaction:
    act: SocialAct
    regard: float
    """Cuánto se movió el aprecio hacia quien habla."""
    regard_after: float
    valence: float
    importance: float
    tone: Tone
    leaves: bool
    """Si se va y la conversación acaba."""


@dataclass
class Conversation:
    """Una conversación en curso: cuántas veces se ha dicho cada acto. La
    lleva quien conversa (la terminal y el guion, igual), y por eso reproducir
    da lo mismo."""

    listener: AgentId
    said: dict[SocialAct, int] = field(default_factory=dict)
    count: int = 0
    over: bool = False


def react(
    world: WorldState, listener: AgentId, speaker: AgentId, act: SocialAct,
    about: AgentId | None, talk: Conversation,
) -> Reaction:
    pack = world.pack
    spec = pack.social.acts[act]
    oyente = world.agents[listener]
    temp = oyente.temperament
    tick = world.tick

    def aprecio(otro: AgentId) -> float:
        return oyente.regard_for(otro, tick, temp.bond_fade, oyente.relation_floor(pack, otro))

    ahora = aprecio(speaker)
    base = spec.regard
    if about is not None and about not in (listener, speaker) and act in (
        SocialAct.FLATTER, SocialAct.INSULT
    ):
        # Hablar de un tercero: cuenta lo que el oyente piensa de él, no el acto.
        signo = 1.0 if act is SocialAct.FLATTER else -1.0
        peso = max(-1.0, min(1.0, aprecio(about) * ABOUT_GAIN))
        base = signo * abs(spec.regard) * peso
    elif act is SocialAct.JOKE and ahora < 0.0:
        base = -abs(base)

    peor = ficha(world, listener).carencias
    apurado = bool(peor) and peor[0][1] in (Lack.DESPERATE, Lack.SEVERE)
    rencor = world.memoria.agravio(listener, tick, pack.tuning.grief_scale).get(speaker, 0.0)

    if base > 0.0:
        delta = base * (temp.bond_rate / BOND_RATE) * (1.0 - max(0.0, ahora))
        if apurado:
            delta *= 0.5
        if rencor > GRUDGE:
            delta *= 0.5
    else:
        delta = base * temp.loss_aversion
    delta *= pack.social.repeat_decay ** talk.said.get(act, 0)
    despues = max(-1.0, min(1.0, ahora + delta))

    if act in NEGATIVE or delta < 0.0:
        tono = (Tone.AFRAID if act is SocialAct.THREATEN and despues > HOSTILE_AT
                else Tone.HOSTILE if despues <= HOSTILE_AT / 2 else Tone.CURT)
    elif apurado:
        tono = Tone.SAD if peor[0][1] is Lack.DESPERATE else Tone.CURT
    elif rencor > GRUDGE:
        tono = Tone.CURT
    else:
        tono = Tone.FRIENDLY
    se_va = (
        despues < pack.social.leave_below
        or talk.count + 1 >= pack.social.max_acts
        or (act is SocialAct.THREATEN and tono is Tone.AFRAID)
    )
    # Si salió al revés de lo que el acto pretendía (la broma de quien te cae
    # mal), se recuerda al revés.
    valencia = spec.valence if (delta >= 0.0) == (spec.valence >= 0.0) else -spec.valence
    return Reaction(act, delta, despues, valencia, spec.importance, tono, se_va)
