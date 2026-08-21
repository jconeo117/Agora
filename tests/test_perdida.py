"""La pérdida: el duelo pesa lo que pesaba el afecto, y dura lo que dura en cada
cual.

**El encargo, y por qué obligó a cambiar de plan.** Se pidió que el duelo no
estuviera encasillado — *uno lo supera en dos semanas, otro reordena su vida
entera*— y el motor no podía cumplirlo: `memory_fade` es UN número del pack, así
que los 127 habitantes olvidaban al mismo ritmo exacto y dos duelos solo podían
diferenciarse en cuánto pesaban el primer día. De ahí el séptimo canal.

**Y por qué la muerte, si lo general es la pérdida.** Se midió antes de escribir
nada: 120 días de ciudad, 127 agentes, **cero vínculos rotos**. El grafo de
conocidos se completa —16 002 de 16 002— y `forget_bonds` no dispara ni una vez
en cuatro meses. La ruptura no ocurre, la ausencia tampoco (necesita situaciones
que no disparan), y la noticia necesita rumores. La muerte es la única causa de
pérdida con combustible, así que es con la que se estrena la primitiva general.

Es la misma disciplina que dejó parado el miedo a lugares una fase entera: *el
motor sabe hacer más cosas de las que este mundo le pide*.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.disposition import compose_memory_fade
from agora.engine.events import Event, EventKind
from agora.engine.memory import MemoriaEpisodica
from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, TraitId
from agora.engine.pack import ContentPack
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
AG3 = AgentId("ag3")
IDOLO = AgentId("idolo")
P1 = PlaceId("p1")
P2 = PlaceId("p2")
TENAZ = TraitId("tenaz")


def perdida_pack(**overrides: Any) -> ContentPack:
    """Dos lugares para poder estar delante o no estarlo."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "n1", "label": "n1", "decay_per_tick": 0.01, "initial": 0.6},
        ],
        "traits": [
            {"id": "tenaz", "label": "tenaz", "memory_multipliers": 4.0},
        ],
        "actions": [
            {"id": "estar", "label": "estar", "duration_ticks": 1,
             "requires_affordance": "sitio", "satisfies": {"n1": 1.0},
             "effects": {"n1": 0.05}},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["sitio"],
             "neighbors": {"p2": 1}},
            {"id": "p2", "label": "p2", "affordances": ["sitio"],
             "neighbors": {"p1": 1}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 40, "memory_fade": 0.99,
                   "memory_scale": 1.0, "grief_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def evento(seq: int, tick: int, quien: AgentId, muerto: AgentId,
           place: PlaceId | None = None) -> Event:
    return Event(seq=seq, tick=tick, kind=EventKind.AGENT_DIED,
                 actor=quien, place=place, subject=muerto)


# --- séptimo canal: cuánto le dura ------------------------------------------


def test_without_traits_you_forget_at_the_worlds_pace() -> None:
    assert compose_memory_fade(perdida_pack(), {}, 0.99) == pytest.approx(0.99)


def test_a_world_that_does_not_blur_does_not_start_now() -> None:
    """`1.0 ** x` es 1.0 para cualquier x, pero se dice explícito: estrenar el
    canal no puede encender el desdibujado en un pack que no lo pedía."""
    assert compose_memory_fade(perdida_pack(), {TENAZ: 1.0}, 1.0) == 1.0


def test_the_channel_scales_the_half_life_and_does_not_multiply() -> None:
    """**La trampa aritmética del canal.** Un fade es la fracción que sobrevive
    cada tick: multiplicarlo por 4 daría 3.96, que no es "recuerda cuatro veces
    más" sino un número inválido. Lo que se multiplica es la media vida, y eso es
    un exponente."""
    pack = perdida_pack()
    propio = compose_memory_fade(pack, {TENAZ: 1.0}, 0.99)

    assert propio == pytest.approx(0.99 ** (1 / 4))
    assert 0.99 < propio < 1.0, "olvida más despacio, sin salirse de rango"


def test_the_channel_can_also_make_you_forget_sooner() -> None:
    pack = perdida_pack(
        **{"traits": [{"id": "tenaz", "label": "tenaz",
                       "memory_multipliers": 0.25}]}
    )
    assert compose_memory_fade(pack, {TENAZ: 1.0}, 0.99) == pytest.approx(0.99**4)


def test_intensity_grades_it_like_every_other_channel() -> None:
    pack = perdida_pack()
    entero = compose_memory_fade(pack, {TENAZ: 1.0}, 0.99)
    medio = compose_memory_fade(pack, {TENAZ: 0.5}, 0.99)
    assert 0.99 < medio < entero


def test_nobody_remembers_better_than_perfectly() -> None:
    pack = perdida_pack(
        **{"traits": [{"id": "tenaz", "label": "tenaz",
                       "memory_multipliers": 5000.0}]}
    )
    assert compose_memory_fade(pack, {TENAZ: 1.0}, 0.99) <= 1.0


def test_two_people_grieve_the_same_loss_for_different_lengths() -> None:
    """**Lo que el encargo pedía y el motor no podía dar.** Mismo muerto, mismo
    aprecio, mismo día: a los tres meses uno lo tiene casi olvidado y el otro
    sigue con ello encima."""
    memoria = MemoriaEpisodica(capacidad=40, fade=0.99,
                               fade_de={AG2: 0.99 ** (1 / 4)})
    for quien in (AG1, AG2):
        memoria.remember(quien, evento(1, 0, quien, IDOLO),
                         importancia=0.8, valencia=-1.0)

    tarde = 96 * 90
    corriente = memoria.duelo(AG1, tarde, escala=1.0)[IDOLO]
    tenaz = memoria.duelo(AG2, tarde, escala=1.0)[IDOLO]

    assert tenaz > corriente * 5, "al tenaz le sigue doliendo"
    assert corriente < 0.02, "al otro se le pasó"


# --- el índice del duelo -----------------------------------------------------


def test_grief_is_indexed_by_person() -> None:
    memoria = MemoriaEpisodica(capacidad=40, fade=1.0)
    memoria.remember(AG1, evento(1, 0, AG1, IDOLO), importancia=0.5,
                     valencia=-1.0)
    assert memoria.duelo(AG1, 0, escala=1.0) == {IDOLO: pytest.approx(1 / 3)}


def test_a_scale_of_zero_turns_the_lens_off() -> None:
    """Como `regret_scale` y `fear_scale`: el recuerdo se guarda igual —es
    biografía— pero el índice no informa de nada."""
    memoria = MemoriaEpisodica(capacidad=40, fade=1.0)
    memoria.remember(AG1, evento(1, 0, AG1, IDOLO), importancia=0.5,
                     valencia=-1.0)
    assert memoria.duelo(AG1, 0, escala=0.0) == {}
    assert len(memoria.de(AG1)) == 1


def test_what_you_did_is_not_grief() -> None:
    """La partición que comparte con `miedo`: una pérdida no es una decisión de
    quien la sufre, así que lo que lleva `action` no entra."""
    memoria = MemoriaEpisodica(capacidad=40, fade=1.0)
    ev = Event(seq=1, tick=0, kind=EventKind.ACTION_COMPLETED, actor=AG1,
               subject=IDOLO, action=ActionId("estar"))
    memoria.remember(AG1, ev, importancia=0.9, valencia=-1.0)
    assert memoria.duelo(AG1, 0, escala=1.0) == {}


def test_a_good_memory_of_someone_is_not_grief() -> None:
    memoria = MemoriaEpisodica(capacidad=40, fade=1.0)
    memoria.remember(AG1, evento(1, 0, AG1, IDOLO), importancia=0.9,
                     valencia=1.0)
    assert memoria.duelo(AG1, 0, escala=1.0) == {}


def test_grief_and_fear_are_orthogonal_and_that_is_not_double_counting() -> None:
    """**El único índice que se solapa con otro, y a propósito.** `rencor` y
    `miedo` se parten por `action` y no coinciden jamás. Este mira A QUIÉN, que
    es un eje distinto: una pérdida ocurrida en un sitio pesa aquí por la persona
    y allí por el lugar.

    No son dos penalizaciones sobre la misma decisión — son dos decisiones
    distintas. Es lo que hace que a un testigo se le cambie la rutina y al que se
    enteró de lejos no, sin una sola línea escrita para el duelo.
    """
    memoria = MemoriaEpisodica(capacidad=40, fade=1.0)
    from agora.engine.ontology import SituationId
    memoria.remember(AG1, evento(1, 0, AG1, IDOLO, place=P1), importancia=0.6,
                     valencia=-1.0, culpable=SituationId("lo_que_sea"))

    assert IDOLO in memoria.duelo(AG1, 0, escala=1.0)
    assert P1 in memoria.miedo(AG1, 0, escala=1.0)


# --- la muerte ---------------------------------------------------------------


def con_aprecio(sim: Simulation, de: AgentId, hacia: AgentId,
                veces: int) -> None:
    """Construye afecto real: encuentros MÁS trato, que es lo que mueve `regard`."""
    agente = sim.state.agents[de]
    for t in range(veces):
        agente.meet(hacia, tick=t)
        agente.remember_company([hacia], premium=0.5, rate=0.4, tick=t)


def test_the_dead_leave_the_roster_but_stay_in_the_census() -> None:
    """El mundo sigue sabiendo quién fue. Es lo que permite nombrarlo al
    recordarlo."""
    sim = Simulation(perdida_pack(), seed=1)
    sim.morir(AG2, porque="test")

    assert AG2 not in sim.state.agents
    assert sim.state.existe(AG2), "no se borra de la historia"


def test_what_they_knew_and_did_not_tell_dies_with_them() -> None:
    sim = Simulation(perdida_pack(), seed=1)
    sim.state.memoria.remember(AG2, evento(1, 0, AG2, AG1), importancia=0.9,
                               valencia=-1.0)
    assert len(sim.state.memoria.de(AG2)) == 1

    sim.morir(AG2)
    assert sim.state.memoria.de(AG2) == ()


def test_grief_lands_on_whoever_cared() -> None:
    sim = Simulation(perdida_pack(), seed=1)
    con_aprecio(sim, AG1, AG2, veces=40)
    sim.morir(AG2)

    duelo = sim.state.memoria.duelo(AG1, sim.state.tick, escala=1.0)
    assert duelo.get(AG2, 0.0) > 0.0


def test_a_death_nobody_mourned_did_not_socially_happen() -> None:
    """Quien no tenía vínculo no recibe nada: ni evento, ni recuerdo. Es correcto
    y conviene verlo escrito."""
    sim = Simulation(perdida_pack(), seed=1)
    sim.morir(AG2)

    assert sim.state.memoria.de(AG1) == ()
    assert sim.log.of_kind(EventKind.AGENT_DIED) == []


def test_the_pain_is_the_affection_and_not_the_relation() -> None:
    """**La propiedad que se buscaba, y sale sin un solo caso especial.**

    El hijo al que nunca reconoció: existe la relación, no el aprecio. El ídolo
    de un desconocido: existe el aprecio, no la relación. El motor pesa el duelo
    por `Bond.regard`, que es otro campo distinto de `relations` y siempre lo
    fue — *un vínculo es lo que sientes; una relación es lo que eres de alguien*.
    """
    pack = perdida_pack(
        **{
            "relations": [{"id": "padre", "label": "padre", "inverse": "hijo"},
                          {"id": "hijo", "label": "hijo", "inverse": "padre"}],
            "agents": [
                {"id": "ag1", "label": "Padre", "home": "p1", "start_at": "p1",
                 "relations": {"padre": ["ag2"]}},
                {"id": "ag2", "label": "Hijo", "home": "p1", "start_at": "p1"},
                {"id": "ag3", "label": "Admirador", "home": "p1",
                 "start_at": "p1"},
            ],
        }
    )
    sim = Simulation(pack, seed=1)
    # El padre tiene la relación y ningún trato. El admirador, al revés.
    con_aprecio(sim, AG3, AG2, veces=60)

    assert "padre" in {str(r) for r in sim.state.agents[AG1].relations}
    sim.morir(AG2)

    duelo_padre = sim.state.memoria.duelo(AG1, sim.state.tick, escala=1.0)
    duelo_admirador = sim.state.memoria.duelo(AG3, sim.state.tick, escala=1.0)

    assert duelo_padre.get(AG2, 0.0) == 0.0, "la relación sola no duele"
    assert duelo_admirador.get(AG2, 0.0) > 0.0, "el aprecio solo, sí"


# --- el suelo de la relación: lo que `morir` se estaba saltando --------------
#
# **Salió de medir, no de leer el código.** Cinco muertes en confluencia, 505
# líneas de duelo grabadas, y al día 75 CERO dolientes de 195. Buscando por qué,
# apareció que `morir` era el único sitio del motor que leía el afecto sin pasar
# por `regard_for` — así que perdía el suelo de la relación y el desdibujado.


def pareja_pack(**overrides: Any) -> ContentPack:
    """Un mundo con dos lazos: uno con suelo y otro sin él, a propósito."""
    return perdida_pack(**{
        "relations": [
            {"id": "pareja", "label": "pareja", "symmetric": True,
             "regard_floor": 0.45},
            # Sin suelo, como en ciudad: un hermano puede caerte fatal, y el
            # pack tiene que poder escribirlo.
            {"id": "hermano", "label": "hermano", "symmetric": True},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1",
             "relations": {"pareja": ["ag2"]}},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1",
             "relations": {"hermano": ["ag2"]}},
        ],
        **overrides,
    })


def test_losing_your_partner_hurts_without_any_shared_time() -> None:
    """**Lo que este arreglo compra.** Nadie ha compartido nada con nadie: el
    aprecio emergente de los tres es exactamente cero.

    Antes, perder a tu pareja dolía lo que hubierais cenado juntos últimamente
    —o sea, nada— porque `Bond.regard` en crudo no sabe que es tu pareja. El
    suelo es justo lo que el pack escribió para decirlo.
    """
    sim = Simulation(pareja_pack(), seed=1)
    sim.morir(AG2)

    duelo = sim.state.memoria.duelo(AG1, sim.state.tick, escala=1.0)
    assert duelo.get(AG2, 0.0) > 0.0


def test_and_the_brother_without_a_floor_still_feels_nothing() -> None:
    """**La mitad que no se puede perder al arreglarlo.** En el mismo mundo, la
    misma muerte y el mismo trato (ninguno): el hermano no recibe nada.

    Quién tiene suelo y quién no lo decide el pack, que es donde estaba la
    decisión. El motor no sabe qué es una pareja ni qué es un hermano.
    """
    sim = Simulation(pareja_pack(), seed=1)
    sim.morir(AG2)

    duelo = sim.state.memoria.duelo(AG3, sim.state.tick, escala=1.0)
    assert duelo.get(AG2, 0.0) == 0.0


def test_affection_above_the_floor_still_wins() -> None:
    """El suelo es un mínimo, no un valor fijo. Quien de verdad la quería llora
    más que quien solo estaba casado con ella en el papel."""
    sim = Simulation(pareja_pack(), seed=1)
    con_aprecio(sim, AG3, AG2, veces=60)
    sim.morir(AG2)

    de_la_pareja = sim.state.memoria.duelo(AG1, sim.state.tick, escala=1.0)
    del_hermano = sim.state.memoria.duelo(AG3, sim.state.tick, escala=1.0)
    assert del_hermano[AG2] > de_la_pareja[AG2]


def test_you_grieve_less_for_someone_you_stopped_seeing() -> None:
    """La otra mitad de `regard_for`: el desdibujado por no verse. Ya lo decía
    `bond_fade` en todas partes menos aquí.

    Dos personas con el MISMO aprecio construido; a una se lo dejaron de ver
    hace mucho. `bond_fade` se declara explícito porque el pack de este fichero
    no lo traía, y estrenar el canal aquí no puede depender de un default.
    """
    pack = perdida_pack(**{
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
            {"id": "ag3", "label": "Tres", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 40, "memory_fade": 0.99,
                   "memory_scale": 1.0, "grief_scale": 1.0,
                   "bond_fade": 0.999},
    })
    sim = Simulation(pack, seed=1)
    con_aprecio(sim, AG1, AG2, veces=40)
    con_aprecio(sim, AG3, AG2, veces=40)
    # Al de AG1 lo vio ayer; al de AG3, hace mil ticks.
    sim.state.agents[AG1].bonds[AG2].last_seen = sim.state.tick
    sim.state.agents[AG3].bonds[AG2].last_seen = sim.state.tick - 1000
    sim.morir(AG2)

    reciente = sim.state.memoria.duelo(AG1, sim.state.tick, escala=1.0)
    lejano = sim.state.memoria.duelo(AG3, sim.state.tick, escala=1.0)
    assert reciente[AG2] > lejano[AG2]


def test_only_the_witness_carries_the_place() -> None:
    """Al que estaba delante le entra además por `miedo` y puede acabar rodeando
    el sitio. Al que se enteró de lejos no: colgarle un lugar en el que no le
    pasó nada sería inventarle una aversión."""
    sim = Simulation(perdida_pack(), seed=1)
    con_aprecio(sim, AG1, AG2, veces=40)
    sim.state.agents[AG1].at = P2  # no estaba delante
    sim.morir(AG2)

    recuerdos = sim.state.memoria.de(AG1)
    assert len(recuerdos) == 1
    assert recuerdos[0].place is None
    assert recuerdos[0].about == AG2


def test_the_witness_does_carry_it() -> None:
    sim = Simulation(perdida_pack(), seed=1)
    con_aprecio(sim, AG1, AG2, veces=40)
    assert sim.state.agents[AG1].at == sim.state.agents[AG2].at
    sim.morir(AG2)

    assert sim.state.memoria.de(AG1)[0].place == P1


def test_dying_twice_is_loud() -> None:
    """`KeyError` ruidoso y no un no-op silencioso: quien lo llama cree que
    alguien está vivo, y esa creencia equivocada no se ve en el log."""
    sim = Simulation(perdida_pack(), seed=1)
    sim.morir(AG2)
    with pytest.raises(KeyError, match="Ya murió"):
        sim.morir(AG2)


def test_killing_a_stranger_says_so() -> None:
    sim = Simulation(perdida_pack(), seed=1)
    with pytest.raises(KeyError, match="Nunca existió"):
        sim.morir(AgentId("nadie"))


def test_the_world_goes_on_without_them() -> None:
    """Que el reparto encoja no puede romper el tick loop."""
    sim = Simulation(perdida_pack(), seed=1)
    sim.run(50)
    sim.morir(AG2)
    sim.run(50)

    assert AG2 not in sim.state.agents
    assert sim.state.agents[AG1].needs[NeedId("n1")] >= 0.0
