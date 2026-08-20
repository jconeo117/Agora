"""Condiciones: lo que alguien lleva encima. Herida, infección, veneno.

**No es una primitiva nueva, es un alcance nuevo para la que ya había.** Una
`SituationSpec` ya era exactamente lo que hace falta —un estado con nombre, que
va y viene, que multiplica lo que rinde y puede hacer daño— y lo único que le
faltaba era poder pegarse a una persona en vez de a un lugar. Toda la maquinaria
del daño ya era por agente: el tick loop llama a `endure` uno por uno, y lo único
que se consultaba por lugar era *cuáles te alcanzan*.

**Y de aquí sale, sin mecanismo de muerte nuevo, todo lo que no era agotamiento.**
Una hemorragia no es *morir de pérdida de sangre*: es un estado que llevas y que
te drena, y morirse es lo que pasa si nadie lo para. Eso ya lo cobra
`lethal_after`. Una regla de muerte, tantas causas como el pack quiera.

Las tres decisiones de diseño vinieron del encargo y las tres se prueban aquí:

1. **Se quitan por tiempo Y por acción.** Sin plazo, una infección que nadie sabe
   curar mata a todo el mundo; sin acción, curarse no se puede decidir.
2. **Se acumulan por marca.** Brazo, pierna y torso drenan por separado; dos en el
   mismo brazo no duran más, duelen más.
3. La marca es **opaca**: el motor compara cadenas y no sabe qué es un brazo.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from agora.engine.ontology import ActionId, AgentId, NeedId, PlaceId, SituationId
from agora.engine.pack import ContentPack
from agora.engine.persistence import load, save
from agora.engine.world import Simulation

AG1 = AgentId("ag1")
AG2 = AgentId("ag2")
P1 = PlaceId("p1")
SANGRE = NeedId("sangre")
HERIDA = SituationId("herida")
VENENO = SituationId("veneno")
VENDAR = ActionId("vendar")


def cond_pack(**overrides: Any) -> ContentPack:
    """Un mundo con heridas que drenan sangre y vendas que las quitan."""
    data: dict[str, Any] = {
        "id": "test",
        "label": "test",
        "needs": [
            {"id": "sangre", "label": "sangre", "decay_per_tick": 0.0,
             "initial": 1.0, "lethal_after": 5},
        ],
        "situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.05}},
            {"id": "veneno", "label": "veneno", "personal": True,
             "effects": {"sangre": -0.02}},
        ],
        "actions": [
            {"id": "vendar", "label": "vendar", "duration_ticks": 1,
             "requires_affordance": "botica", "satisfies": {"sangre": 1.0},
             "effects": {"sangre": 0.10}, "cures": ["herida"]},
            {"id": "nada", "label": "nada", "duration_ticks": 1},
        ],
        "places": [
            {"id": "p1", "label": "p1", "affordances": ["botica"],
             "neighbors": {}},
        ],
        "agents": [
            {"id": "ag1", "label": "Uno", "home": "p1", "start_at": "p1"},
            {"id": "ag2", "label": "Dos", "home": "p1", "start_at": "p1"},
        ],
        "tuning": {"memory_capacity": 20, "memory_scale": 1.0},
    }
    data.update(copy.deepcopy(overrides))
    return ContentPack.model_validate(data)


def sin_cura(**overrides: Any) -> ContentPack:
    """Igual, pero nadie sabe vendar: la herida no se puede quitar por acción."""
    return cond_pack(
        **{
            "actions": [{"id": "nada", "label": "nada", "duration_ticks": 1}],
            "places": [{"id": "p1", "label": "p1", "affordances": [],
                        "neighbors": {}}],
            **overrides,
        }
    )


# --- lo que el pack puede declarar -------------------------------------------


def test_a_personal_situation_cannot_live_in_a_place() -> None:
    """Lo que le pasa a alguien viaja con quien lo lleva. Declararle un sitio es
    un malentendido sobre qué clase de cosa se está escribiendo."""
    with pytest.raises(ValueError, match="personal y declara `places`"):
        cond_pack(
            **{"situations": [{"id": "herida", "label": "herida",
                               "personal": True, "places": ["p1"],
                               "effects": {"sangre": -0.05}}]}
        )


def test_a_wound_does_not_come_back_every_spring() -> None:
    with pytest.raises(ValueError, match="personal y es periódica"):
        cond_pack(
            **{"situations": [{"id": "herida", "label": "herida",
                               "personal": True, "every": 100, "lasts": 10,
                               "effects": {"sangre": -0.05}}]}
        )


def test_you_cannot_cure_the_weather() -> None:
    """`cures` solo apunta a lo personal: nadie lleva encima un invierno."""
    with pytest.raises(ValueError, match="no es una situación personal"):
        cond_pack(
            **{"situations": [{"id": "herida", "label": "herida",
                               "personal": True,
                               "effects": {"sangre": -0.05}},
                              {"id": "invierno", "label": "invierno",
                               "effects": {"sangre": -0.01}}],
               "actions": [
                   {"id": "vendar", "label": "vendar", "duration_ticks": 1,
                    "requires_affordance": "botica",
                    "satisfies": {"sangre": 1.0},
                    "effects": {"sangre": 0.10}, "cures": ["invierno"]},
                   {"id": "nada", "label": "nada", "duration_ticks": 1}]}
        )


def test_the_weather_is_not_something_you_carry() -> None:
    sim = Simulation(
        cond_pack(**{"situations": [
            {"id": "herida", "label": "herida", "personal": True,
             "effects": {"sangre": -0.05}},
            {"id": "veneno", "label": "veneno", "personal": True,
             "effects": {"sangre": -0.02}},
            {"id": "invierno", "label": "invierno",
             "effects": {"sangre": -0.001}}]}),
        seed=1,
    )
    with pytest.raises(ValueError, match="no es personal"):
        sim.afligir(AG1, SituationId("invierno"))


# --- se acumulan por marca ---------------------------------------------------


def test_three_wounds_in_three_places_drain_separately() -> None:
    """Brazo, pierna y torso. No forman una herida mayor: son tres."""
    sim = Simulation(sin_cura(), seed=1)
    for donde in ("brazo", "pierna", "torso"):
        sim.afligir(AG1, HERIDA, marca=donde)

    condiciones = sim.state.agents[AG1].condiciones
    assert len(condiciones) == 3
    assert all(c.veces == 1 for c in condiciones)


def test_two_wounds_in_the_same_arm_hurt_more_and_do_not_last_longer() -> None:
    """La regla del encargo: casi idéntica agrava, distinta se apila. Alargar el
    plazo modelaría una herida mal curada; multiplicar el daño modela dos."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, HERIDA, marca="brazo", ticks=100)
    sim.afligir(AG1, HERIDA, marca="brazo", ticks=100)

    condiciones = sim.state.agents[AG1].condiciones
    assert len(condiciones) == 1
    assert condiciones[0].veces == 2
    assert condiciones[0].hasta == sim.state.tick + 100, "no dura más"


def test_stacking_multiplies_the_bleeding() -> None:
    uno = Simulation(sin_cura(), seed=1)
    uno.afligir(AG1, HERIDA, marca="brazo")
    uno.run(3)

    dos = Simulation(sin_cura(), seed=1)
    dos.afligir(AG1, HERIDA, marca="brazo")
    dos.afligir(AG1, HERIDA, marca="brazo")
    dos.run(3)

    perdida_uno = 1.0 - uno.state.agents[AG1].needs[SANGRE]
    perdida_dos = 1.0 - dos.state.agents[AG1].needs[SANGRE]
    assert perdida_dos == pytest.approx(perdida_uno * 2, rel=0.01)


def test_the_mark_is_opaque_to_the_engine() -> None:
    """El motor compara cadenas y no sabe qué es un brazo. Un pack de naves diría
    `casco`; uno de política, `reputación`."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, HERIDA, marca="tobera de estribor")
    sim.afligir(AG1, HERIDA, marca="reputación")
    assert len(sim.state.agents[AG1].condiciones) == 2


def test_something_without_parts_needs_no_mark() -> None:
    """Una borrachera es una borrachera. La cadena vacía es marca válida."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, VENENO)
    sim.afligir(AG1, VENENO)
    assert len(sim.state.agents[AG1].condiciones) == 1
    assert sim.state.agents[AG1].condiciones[0].veces == 2


# --- se quitan por tiempo Y por acción ---------------------------------------


def test_a_poison_wears_off() -> None:
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, VENENO, ticks=10)
    sim.run(9)
    assert sim.state.agents[AG1].condiciones
    sim.run(2)
    assert not sim.state.agents[AG1].condiciones


def test_an_infection_does_not_wear_off_and_that_is_why_it_is_scary() -> None:
    """Sin plazo no se pasa sola. En este mundo tampoco hay quien la cure, así
    que acaba matando — que es exactamente por lo que da miedo."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, HERIDA, ticks=None)
    sim.run(10)
    assert sim.state.agents[AG1].condiciones, "no se pasó sola"
    sim.run(290)
    assert AG1 not in sim.state.agents, "y nadie la paró"


def test_bandaging_takes_it_away() -> None:
    sim = Simulation(cond_pack(), seed=1)
    sim.afligir(AG1, HERIDA, marca="brazo")
    assert sim.state.agents[AG1].condiciones

    while sim.state.agents[AG1].condiciones and sim.state.tick < 200:
        sim.run(1)
    assert not sim.state.agents[AG1].condiciones, "nunca se vendó"


def test_bandaging_knows_how_to_bandage_wounds_not_the_right_arm() -> None:
    """Quita todas las marcas de golpe. El motor no puede saber cuál elegir, y
    elegir por `seq` sería inventarse un criterio médico."""
    sim = Simulation(cond_pack(), seed=1)
    for donde in ("brazo", "pierna", "torso"):
        sim.afligir(AG1, HERIDA, marca=donde)
    sim.afligir(AG1, VENENO)

    assert sim.state.agents[AG1].aliviar(HERIDA) == 3
    quedan = sim.state.agents[AG1].condiciones
    assert [c.situacion for c in quedan] == [VENENO], "el veneno no lo cura una venda"


def test_curing_what_you_do_not_have_is_silent() -> None:
    sim = Simulation(cond_pack(), seed=1)
    assert sim.aliviar(AG1, HERIDA) == 0


# --- y de aquí sale la muerte, sin mecanismo nuevo ---------------------------


def test_bleeding_out_is_just_a_need_reaching_zero() -> None:
    """**Lo que este paso demuestra.** No hay muerte-por-herida: hay una herida
    que drena, un eje que llega a cero y `lethal_after` que cobra. Una regla de
    muerte, tantas causas como el pack quiera."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, HERIDA, marca="torso")
    sim.run(40)
    assert AG1 not in sim.state.agents


def test_someone_who_can_heal_survives_what_kills_someone_who_cannot() -> None:
    """El primer trozo de la regla del encargo: *si el herido tiene la capacidad
    de curarse solo*. Aquí es literal — el mundo con botica salva, el mundo sin
    ella no— y con acciones que apunten a otro pasará a ser también *si los de
    alrededor están dispuestos a ayudarlo*."""
    puede = Simulation(cond_pack(), seed=1)
    puede.afligir(AG1, HERIDA, marca="torso")
    puede.run(60)

    no_puede = Simulation(sin_cura(), seed=1)
    no_puede.afligir(AG1, HERIDA, marca="torso")
    no_puede.run(60)

    assert AG1 in puede.state.agents, "tenía con qué curarse"
    assert AG1 not in no_puede.state.agents, "no tenía con qué"


def test_the_damage_is_filed_as_something_that_happened_to_you() -> None:
    """Mismo `endure` que una ventisca: una herida no es una decisión suya, así
    que se archiva como pasivo y no ensucia el rencor contra sus propios actos."""
    sim = Simulation(sin_cura(), seed=1)
    sim.afligir(AG1, HERIDA, marca="torso")
    sim.run(3)
    agente = sim.state.agents[AG1]
    assert agente.needs[SANGRE] < 1.0
    assert sim.state.memoria.rencor(AG1, sim.state.tick, escala=1.0) == {}


# --- durar -------------------------------------------------------------------


def test_a_wound_survives_a_save(tmp_path: Any) -> None:
    pack = sin_cura()
    sim = Simulation(pack, seed=1)
    sim.afligir(AG1, HERIDA, marca="brazo", ticks=500)
    sim.afligir(AG1, HERIDA, marca="brazo")
    sim.afligir(AG1, VENENO)

    fichero = tmp_path / "partida.json"
    save(sim.state, set(), fichero)
    vuelto, _ = load(fichero, pack)

    condiciones = vuelto.agents[AG1].condiciones
    assert len(condiciones) == 2
    porsit = {c.situacion: c for c in condiciones}
    assert porsit[HERIDA].veces == 2
    assert porsit[HERIDA].marca == "brazo"
    assert porsit[VENENO].veces == 1


def test_nothing_changes_for_a_pack_without_conditions() -> None:
    """Estrenar esto no puede mover ningún contrato ya medido.

    La primera versión de este test quitaba las situaciones y dejaba `vendar`
    curando `herida`; el pack se negó a cargar, con razón. Es la validación
    haciendo su trabajo: una acción que cura algo que no existe es contenido
    muerto que se lee como vivo.
    """
    sim = Simulation(
        cond_pack(**{"situations": [], "actions": [
            {"id": "vendar", "label": "vendar", "duration_ticks": 1,
             "requires_affordance": "botica", "satisfies": {"sangre": 1.0},
             "effects": {"sangre": 0.10}},
            {"id": "nada", "label": "nada", "duration_ticks": 1}]}),
        seed=1,
    )
    sim.run(50)
    assert sim.state.agents[AG1].condiciones == []
    assert len(sim.state.agents) == 2
