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

from dataclasses import dataclass, field, replace
from enum import StrEnum

from agora.engine.consulta import Lack, ficha
from agora.engine.events import EventKind
from agora.engine.ontology import AgentId, ClaimKind, PlaceId, SocialAct, Tone
from agora.engine.ports import Contest, Outcome, SocialResolver
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


class Belief(StrEnum):
    BELIEVED = "creida"
    DOUBTFUL = "dudosa"
    CAUGHT = "pillada"


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
    belief: Belief | None = None
    """Qué hizo con una afirmación (unidad 15b); `None` si no era una."""
    info: tuple[str, ...] = ()
    """Lo que contó al preguntarle, en frases para la voz (unidad 15b)."""
    contest: Contest | None = None
    """La tirada de la mentira, con sus dados, si la hubo (unidad 18)."""


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
    rencor = world.memoria.agravio(
        listener, tick, pack.tuning.grief_scale, pack.tuning.agravio_de_oidas
    ).get(speaker, 0.0)

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


# --- afirmar y preguntar (unidad 15b) -------------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    kind: ClaimKind
    who: AgentId
    place: PlaceId | None = None
    """Solo `AT`."""
    victim: AgentId | None = None
    """Solo `HARMED`; el jugador puede ser la víctima."""


def _regard(world: WorldState, listener: AgentId, other: AgentId) -> float:
    oyente = world.agents[listener]
    return oyente.regard_for(
        other, world.tick, oyente.temperament.bond_fade, oyente.relation_floor(world.pack, other)
    )


def _remembers_death(world: WorldState, listener: AgentId, who: AgentId) -> bool:
    return any(r.kind is EventKind.AGENT_DIED and r.about == who
               for r in world.memoria.de(listener))


def _lived_harm(world: WorldState, victim: AgentId) -> set[AgentId]:
    """Quién le hizo daño a `victim`, según lo que él mismo vivió: lo oído no
    cuenta, porque es la versión de otro."""
    return {r.por_quien for r in world.memoria.de(victim)
            if r.de_oidas == 0 and r.valencia < 0.0 and r.por_quien is not None}


def truth(world: WorldState, claim: Claim) -> bool | None:
    """Lo que el mundo sostiene. `None`: no se puede saber."""
    quien = claim.who
    if quien not in world.censo:
        return None
    vivo = world.agents.get(quien)
    match claim.kind:
        case ClaimKind.AT:
            return vivo is not None and vivo.at == claim.place
        case ClaimKind.ALIVE:
            return vivo is not None
        case ClaimKind.DEAD:
            return vivo is None
        case ClaimKind.HARMED:
            if claim.victim is None or claim.victim not in world.agents:
                return None
            return quien in _lived_harm(world, claim.victim)


def contradicts(world: WorldState, listener: AgentId, claim: Claim) -> bool:
    """Si choca con lo que el oyente vio o recuerda, no con la verdad."""
    oyente = world.agents[listener]
    quien = claim.who
    vivo = world.agents.get(quien)
    match claim.kind:
        case ClaimKind.AT:
            if oyente.at == claim.place and (vivo is None or vivo.at != claim.place):
                return True
            horizonte = world.pack.tuning.sighting_horizon
            if horizonte > 0:
                aqui = [t for sitio, (t, quienes) in oyente.sightings.items()
                        if sitio == claim.place and quien in quienes]
                fuera = [t for sitio, (t, quienes) in oyente.sightings.items()
                         if sitio != claim.place and quien in quienes
                         and world.tick - t <= horizonte]
                if fuera and (not aqui or max(fuera) > max(aqui)):
                    return True
            return _remembers_death(world, listener, quien)
        case ClaimKind.ALIVE:
            return _remembers_death(world, listener, quien)
        case ClaimKind.DEAD:
            return vivo is not None and vivo.at == oyente.at
        case ClaimKind.HARMED:
            if claim.victim != listener:
                return False
            quienes = _lived_harm(world, listener)
            return quien not in quienes and bool(quienes)


def trusts(world: WorldState, listener: AgentId, speaker: AgentId) -> bool:
    """Aprecio (con el suelo de la relación) ≥ `trust_above`, o cualquier relación."""
    return (_regard(world, listener, speaker) >= world.pack.social.trust_above
            or bool(world.agents[listener].related_to(speaker)))


def judge(
    world: WorldState, listener: AgentId, speaker: AgentId, claim: Claim,
    resolver: SocialResolver | None, key: str,
) -> tuple[Belief, Contest | None]:
    """Qué hace el oyente con una afirmación: en este orden, lo que sabe, lo que
    es verdad, y solo si no hay nada de eso, una tirada (o el aprecio, sin
    sistema de rol). Devuelve también la tirada, para enseñar sus dados."""
    if contradicts(world, listener, claim):
        return Belief.CAUGHT, None
    if truth(world, claim) is True:
        return Belief.BELIEVED, None
    contest = None if resolver is None else resolver.deceive(world, speaker, listener, key)
    if contest is None:
        creida = _regard(world, listener, speaker) >= 0.0
        return (Belief.BELIEVED if creida else Belief.CAUGHT), None
    resultado = contest.resolution.outcome
    if resultado is Outcome.FAILURE:
        return Belief.CAUGHT, contest
    creencia = Belief.DOUBTFUL if resultado is Outcome.SUCCESS_AT_COST else Belief.BELIEVED
    return creencia, contest


def _leaves(world: WorldState, despues: float, talk: Conversation) -> bool:
    return (despues < world.pack.social.leave_below
            or talk.count + 1 >= world.pack.social.max_acts)


def react_claim(
    world: WorldState, listener: AgentId, speaker: AgentId, belief: Belief,
    talk: Conversation, contest: Contest | None = None,
) -> Reaction:
    """La recepción de una afirmación ya juzgada. Creída: no mueve el aprecio
    (lo que cambia son sus efectos en lo que el oyente cree). A medias: lo baja
    un poco. Pillada: cuesta como un agravio, con quien habla de culpable."""
    base = replace(react(world, listener, speaker, SocialAct.AFFIRM, None, talk),
                   contest=contest)
    social = world.pack.social
    if belief is Belief.BELIEVED:
        return replace(base, belief=belief)
    ahora = base.regard_after
    if belief is Belief.DOUBTFUL:
        delta = social.doubt
        despues = max(-1.0, min(1.0, ahora + delta))
        return replace(base, regard=delta, regard_after=despues, tone=Tone.CURT,
                       leaves=_leaves(world, despues, talk), belief=belief)
    delta = social.caught.regard * world.agents[listener].temperament.loss_aversion
    despues = max(-1.0, min(1.0, ahora + delta))
    return replace(
        base, regard=delta, regard_after=despues, valence=social.caught.valence,
        importance=social.caught.importance,
        tone=Tone.HOSTILE if despues <= -0.1 else Tone.CURT,
        leaves=_leaves(world, despues, talk), belief=belief,
    )


def react_ask(
    world: WorldState, listener: AgentId, speaker: AgentId, talk: Conversation,
) -> Reaction:
    """La recepción de una pregunta: si no se fía, se niega seco."""
    base = react(world, listener, speaker, SocialAct.ASK, None, talk)
    if trusts(world, listener, speaker):
        return base
    return replace(base, tone=Tone.CURT)


def freshest_sighting(
    world: WorldState, listener: AgentId, who: AgentId
) -> tuple[PlaceId, int, frozenset[AgentId]] | None:
    """El avistamiento más reciente del oyente que contenga a `who`; a igual
    tick, el primer sitio por id."""
    mejores = [(t, sitio, quienes)
               for sitio, (t, quienes) in world.agents[listener].sightings.items()
               if who in quienes]
    if not mejores:
        return None
    t, sitio, quienes = max(mejores, key=lambda x: (x[0], [-ord(c) for c in x[1]]))
    return sitio, t, quienes
