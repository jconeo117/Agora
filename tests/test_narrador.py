"""Pruebas del narrador: selector, anclaje, plantillas y mesa (unidad 17, §B.1 y §B.3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agora.banco import load_moments, run_tell_bank
from agora.cognition.narrador import (
    ALIKE,
    CAN,
    DEATH,
    TOP,
    BeatView,
    Fact,
    Kind,
    Moment,
    Narration,
    Sighting,
    Table,
    briefing,
    fallback,
    load_table,
    moment_from_json,
    moment_to_json,
    narrate,
    question_moment,
    round_facts,
    round_moment,
    select,
    strangers,
    tell,
    world_moment,
)
from agora.engine.events import Event, EventKind
from agora.engine.ontology import ActionId, AgentId, ContentTag, NarrationSpec, PlaceId
from agora.engine.pack import load_pack
from agora.engine.ports import CognitionProvider
from agora.engine.world import Simulation
from agora.rules.system import load_ruleset

ISLA_PACK = Path("packs/isla/pack.yaml")
BASE_RULES = Path("rules/base/rules.yaml")
MESA_ISLA = Path("packs/isla/mesa.yaml")
BANCO_NARRACION = Path("packs/isla/banco-narracion.jsonl")


class DummyProvider(CognitionProvider):
    def __init__(self, answer: object) -> None:
        self.answer = answer

    def think(self, briefing: str, schema: type, semilla: int) -> object:
        return self.answer


# --- B.1 Tests de narrador ----------------------------------------------------


def test_tell_formas_y_fallback() -> None:
    # 1. tell: con NarrationSpec, las tres formas (you si actúa el jugador,
    # at_you si el objetivo es el jugador, them si no); sin at_you, them;
    # sin spec, la etiqueta con «tú» y «a ti».
    spec = NarrationSpec(
        you="atacas a {o}{d}",
        them="{a} ataca a {o}{d}",
        at_you="{a} te ataca{d}",
    )
    name = lambda a: a or "nadie"  # noqa: E731

    # Actor es el jugador
    assert tell(spec, "atacar", "yo", "rival", "yo", name, ", fuerte") == "atacas a rival, fuerte"
    # Objetivo es el jugador (con at_you)
    assert tell(spec, "atacar", "rival", "yo", "yo", name, ", fuerte") == "rival te ataca, fuerte"
    # Tercero contra tercero
    esperado_tercero = "rival ataca a otro, fuerte"
    assert tell(spec, "atacar", "rival", "otro", "yo", name, ", fuerte") == esperado_tercero

    # Sin at_you definido en el spec
    spec_sin_at_you = NarrationSpec(you="te cubres", them="{a} se cubre")
    assert tell(spec_sin_at_you, "cubrirse", "rival", "yo", "yo", name) == "rival se cubre"

    # Sin spec (spec is None): formato de respaldo con etiqueta
    assert tell(None, "huir", "yo", None, "yo", name) == "tú: huir"
    assert tell(None, "atacar", "rival", "yo", "yo", name) == "rival: atacar (a ti)"
    assert tell(None, "atacar", "rival", "otro", "yo", name) == "rival: atacar (otro)"


def test_select_accion_contra_jugador_prioridad_5_y_mine() -> None:
    # 2. select: un ACTION_STARTED de otro con data["target"] = jugador da un
    # hecho de prioridad 5 y mine; un ENCOUNTER no da ninguno.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    here = str(world.agents[AgentId("elor_d1")].at)

    e_ataca = Event(
        kind=EventKind.ACTION_STARTED,
        tick=1,
        seq=1,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={"target": "elor_d1"},
    )
    e_encuentro = Event(
        kind=EventKind.ENCOUNTER,
        tick=1,
        seq=2,
        place=PlaceId(here),
        data={"participantes": 2},
    )

    facts = select(world, [e_ataca, e_encuentro], "elor_d1", Sighting(here), Table())
    assert len(facts) == 1
    (f0,) = facts
    assert f0.priority == 5
    assert f0.mine is True
    assert "te ataca" in f0.text


def test_select_agrupa_acciones_ajenas_similares() -> None:
    # 3. select: tres o más acciones violentas ajenas en el sitio del jugador dejan
    # dos y un «y N más así a tu alrededor», ordenado inmediatamente detrás del
    # segundo.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    here = str(world.agents[AgentId("elor_d1")].at)

    targets = ["vidan_d1", "gara_d1", "naia_d2", "lobel_d2"]
    eventos = [
        Event(
            kind=EventKind.ACTION_STARTED,
            tick=1,
            seq=n,
            actor=AgentId("renna_d1"),
            place=PlaceId(here),
            action=ActionId("atacar"),
            data={"target": targets[n - 1]},
        )
        for n in range(1, 5)
    ]

    facts = select(world, eventos, "elor_d1", Sighting(here), Table())
    # Deben quedar ALIKE (2) hechos individuales más el resumen
    resumen = [f for f in facts if "y 2 más así a tu alrededor" in f.text]
    assert len(resumen) == 1
    f_res = resumen[0]
    assert f_res.mine is False

    # El resumen debe tener exactamente el orden grupo[ALIKE - 1].order + 1
    # y quedar ordenado inmediatamente tras el segundo hecho
    assert len(facts) == ALIKE + 1
    assert facts[ALIKE] == f_res
    assert f_res.order == facts[ALIKE - 1].order + 1


def test_select_respeta_lineas_y_muerte() -> None:
    # 4. select: un hecho con contenido que la mesa declara línea no aparece; con
    # DEATH en líneas, tampoco «el cuerpo de…» ni «caes…».
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    here = str(world.agents[AgentId("elor_d1")].at)

    # Hecho con contenido violencia
    e_violencia = Event(
        kind=EventKind.ACTION_STARTED,
        tick=1,
        seq=1,
        actor=AgentId("renna_d1"),
        place=PlaceId(here),
        action=ActionId("atacar"),
        data={"target": "elor_d1"},
    )
    t_violencia = Table(lines=(ContentTag("violencia"),))
    facts_v = select(world, [e_violencia], "elor_d1", Sighting(here), t_violencia)
    assert not any("violencia" in f.content for f in facts_v)
    assert len(facts_v) == 0

    # Línea DEATH
    t_muerte = Table(lines=(ContentTag(DEATH),))
    seen = Sighting(here, frozenset(["renna_d1"]))
    world.agents.pop(AgentId("renna_d1"))  # renna ya no vive
    world.agents.pop(AgentId("elor_d1"))   # elor tampoco vive (jugador muerto)
    facts_m = select(world, [], "elor_d1", seen, t_muerte)
    assert not any("caes" in f.text for f in facts_m)
    assert not any("el cuerpo de" in f.text for f in facts_m)


def test_select_cuerpo_presente_anterior_muerto() -> None:
    # 5. select: alguien presente en el Sighting anterior que ya no vive, sin
    # AGENT_DIED del jugador, da «el cuerpo de X yace aquí».
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    here = str(world.agents[AgentId("elor_d1")].at)

    # Renna estaba presente pero ya no está entre los agentes vivos
    world.agents.pop(AgentId("renna_d1"))
    seen = Sighting(place=here, present=frozenset(["renna_d1"]))

    facts = select(world, [], "elor_d1", seen, Table())
    cuerpos = [f for f in facts if "el cuerpo de Renna yace aquí" in f.text]
    assert len(cuerpos) == 1
    assert cuerpos[0].priority == 4
    assert DEATH in cuerpos[0].content


def test_select_jugador_muerto_caes() -> None:
    # 6. select con el jugador muerto: aparece «caes, y ya no te levantas» con mine.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    world.agents.pop(AgentId("elor_d1"))

    facts = select(world, [], "elor_d1", Sighting(), Table())
    caes = [f for f in facts if f.text == "caes, y ya no te levantas"]
    assert len(caes) == 1
    assert caes[0].mine is True
    assert caes[0].priority == 6


def test_select_maximo_top_y_orden() -> None:
    # 7. select nunca devuelve más de TOP hechos y los devuelve en orden de suceso.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    here = str(world.agents[AgentId("elor_d1")].at)

    eventos = [
        Event(
            kind=EventKind.TRAVEL_ARRIVED,
            tick=1,
            seq=n,
            actor=AgentId("renna_d1"),
            place=PlaceId(here),
        )
        for n in range(1, 20)
    ]

    facts = select(world, eventos, "elor_d1", Sighting(here), Table())
    assert len(facts) <= TOP
    assert facts == tuple(sorted(facts, key=lambda f: f.order))


def test_briefing_tuyo_velos_ronda_y_pregunta() -> None:
    # 8. briefing: los hechos mine llevan (TUYO); con velos, el texto del velo;
    # una ronda no lleva CÓMO ES; una pregunta lleva LO QUE SABES y la pregunta.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state

    f_mio = Fact(3, 1, "haces algo importante", mine=True)
    f_otro = Fact(3, 2, "otro hace algo", mine=False)
    mesa_velos = Table(veils=(ContentTag("violencia"),))
    m_mundo = world_moment(world, "elor_d1", (f_mio, f_otro), mesa_velos)
    b_mundo = briefing(m_mundo)
    assert "(TUYO) haces algo importante" in b_mundo
    assert "(TUYO) otro hace algo" not in b_mundo
    assert "otro hace algo" in b_mundo

    # Ronda no lleva CÓMO ES y conserva description=None
    m_ronda = round_moment(world, "elor_d1", (f_mio,), (), (), Table())
    assert m_ronda.description is None
    assert "CÓMO ES:" not in briefing(m_ronda)

    # Pregunta lleva LO QUE SABES y la pregunta
    m_preg = question_moment(world, "elor_d1", "¿dónde hay agua?", {}, Table())
    b_preg = briefing(m_preg)
    assert "LO QUE SABES:" in b_preg
    assert "¿dónde hay agua?" in b_preg


def test_strangers_detecta_censo_ausente_del_briefing() -> None:
    # 9. strangers: la prosa que nombra a alguien del censo ausente del briefing lo
    # devuelve; un nombre del briefing, no.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state

    m = world_moment(world, "elor_d1", (), Table())
    b = briefing(m)
    extrano = next(n for n in m.everyone if n not in b)

    prosa_con_extrano = f"De pronto aparece {extrano} corriendo."
    assert extrano in strangers(m, prosa_con_extrano)

    prosa_conocido = "Elor respira hondo."
    assert strangers(m, prosa_conocido) == ()


def test_narrate_cadena_anclaje_y_plantilla() -> None:
    # 10. narrate: proveedor que inventa un nombre → el siguiente de la cadena;
    # todos fallan → plantilla con by is None; el primero válido gana con su índice.
    pack = load_pack(ISLA_PACK)
    sim = Simulation(pack, seed=1)
    world = sim.state
    f_hecho = Fact(3, 1, "llegas a la playa", mine=True)
    m = world_moment(world, "elor_d1", (f_hecho,), Table())
    b = briefing(m)
    extrano = next(n for n in m.everyone if n not in b)

    # Proveedor 0 inventa al extraño (no está en briefing)
    p0 = DummyProvider(Narration(prosa=f"{extrano} te saluda desde las rocas."))
    # Proveedor 1 responde algo válido sin extraños
    p1 = DummyProvider(Narration(prosa="Llegas a la orilla del mar."))
    # Proveedor 2 también válido
    p2 = DummyProvider(Narration(prosa="Miras las olas."))

    # El primero válido es p1 (índice 1)
    told = narrate(m, [p0, p1, p2], 42)
    assert told.by == 1
    assert told.text == "Llegas a la orilla del mar."

    # Si todos fallan o inventan extraños, recurre a plantilla (by is None)
    told_fb = narrate(m, [p0], 42)
    assert told_fb.by is None
    assert told_fb.text == fallback(m)


def test_fallback_pregunta() -> None:
    # 11. fallback de una pregunta: «¿dónde puedo beber?» con una línea
    # «puedes beber: en…» la devuelve; sin coincidencia, remite a «ficha».
    m_acierto = Moment(
        kind=Kind.QUESTION,
        player="Elor",
        place="playa",
        description=None,
        phase=None,
        present=(),
        state=(),
        facts=(),
        question="¿dónde puedo beber agua?",
        knowledge=(f"{CAN}beber: en el arroyo, a 2 cuartos de hora",),
    )
    fb = fallback(m_acierto)
    assert "Puedes beber: en el arroyo" in fb

    # Sin prefijo CAN: aunque comparta palabra ('beber'), se ignora y remite a ficha
    m_fallo = Moment(
        kind=Kind.QUESTION,
        player="Elor",
        place="playa",
        description=None,
        phase=None,
        present=(),
        state=(),
        facts=(),
        question="¿dónde puedo beber agua?",
        knowledge=("beber: no te conviene",),
    )
    fb_fallo = fallback(m_fallo)
    assert "Sin el narrador no sé contestarte eso; prueba «ficha» o «mirar»." in fb_fallo


def test_moment_to_json_from_json_ida_y_vuelta() -> None:
    # 12. moment_to_json / moment_from_json: ida y vuelta da el mismo Moment.
    f = Fact(3, 10, "un hecho", ("Ana",), ("violencia",), "violenta", True)
    m = Moment(
        kind=Kind.WORLD,
        player="Elor",
        place="selva",
        description="Árboles densos",
        phase="mañana",
        present=("Ana", "Bea"),
        state=("te falta comida: hambriento",),
        facts=(f,),
        veils=("violencia",),
        question=None,
        knowledge=(),
        everyone=("Ana", "Bea", "Elor"),
    )
    d = moment_to_json(m)
    m2 = moment_from_json(d)
    assert m == m2


def test_round_facts() -> None:
    # 13. round_facts: atacar.success con banda usa {d}; una clave sin resultado
    # (huir) se usa cuando no hay huir.<resultado>; la escena con línea
    # violencia no deja hechos de atacar.
    name = lambda a: a.capitalize() if a else "Alguien"  # noqa: E731
    narration = {
        "atacar.success": NarrationSpec(you="alcanzas a {o}{d}", them="{a} alcanza a {o}{d}"),
        "huir": NarrationSpec(you="escapas; nadie te sigue", them="{a} escapa"),
    }
    content = {"atacar": ("violencia",)}

    # atacar.success con banda
    b1 = BeatView(1, "atacar", "yo", "rival", "success", ", un buen golpe", "atacar")
    facts1 = round_facts([b1], "yo", name, narration, content, Table())
    assert len(facts1) == 1
    assert facts1[0].text == "alcanzas a Rival, un buen golpe"

    # huir sin subresultado en narration
    b2 = BeatView(2, "huir", "yo", None, "critical", "", "huir")
    facts2 = round_facts([b2], "yo", name, narration, content, Table())
    assert len(facts2) == 1
    assert facts2[0].text == "escapas; nadie te sigue"

    # Mesa con línea violencia suprime atacar
    t_linea = Table(lines=(ContentTag("violencia"),))
    facts3 = round_facts([b1], "yo", name, narration, content, t_linea)
    assert len(facts3) == 0


# --- B.3 Esquema y datos ------------------------------------------------------


def test_narration_spec_campos_permitidos() -> None:
    # 1. NarrationSpec con {objetivo} falla al cargar nombrando el campo; con
    # {a}, {o}, {d}, carga.
    with pytest.raises(ValidationError, match="objetivo"):
        NarrationSpec(you="atacas a {objetivo}", them="{a} ataca a {objetivo}")

    # Campos válidos {a}, {o}, {d}
    s = NarrationSpec(you="atacas a {o}{d}", them="{a} ataca a {o}{d}", at_you="{a} te ataca{d}")
    assert s.you == "atacas a {o}{d}"


def test_combat_spec_validacion_claves(tmp_path: Path) -> None:
    # 2. load_ruleset con combat.narration: {volar: ...}, con
    # atacar.ganar: ... o con combat.content: {volar: [...]} falla.
    raw = yaml.safe_load(BASE_RULES.read_text(encoding="utf-8"))

    # Clave de acción desconocida en narration
    raw1 = dict(raw)
    raw1["combat"] = dict(raw["combat"])
    raw1["combat"]["narration"] = {"volar": {"you": "vuelas", "them": "{a} vuela"}}
    tmp1 = tmp_path / "bad1.yaml"
    tmp1.write_text(yaml.safe_dump(raw1), encoding="utf-8")
    with pytest.raises(ValueError, match="volar"):
        load_ruleset(tmp1)

    # Clave con subresultado inválido en narration
    raw2 = dict(raw)
    raw2["combat"] = dict(raw["combat"])
    raw2["combat"]["narration"] = {"atacar.ganar": {"you": "ganas", "them": "{a} gana"}}
    tmp2 = tmp_path / "bad2.yaml"
    tmp2.write_text(yaml.safe_dump(raw2), encoding="utf-8")
    with pytest.raises(ValueError, match=r"atacar\.ganar"):
        load_ruleset(tmp2)

    # Clave de acción desconocida en content
    raw3 = dict(raw)
    raw3["combat"] = dict(raw["combat"])
    raw3["combat"]["content"] = {"volar": ["violencia"]}
    tmp3 = tmp_path / "bad3.yaml"
    tmp3.write_text(yaml.safe_dump(raw3), encoding="utf-8")
    with pytest.raises(ValueError, match="volar"):
        load_ruleset(tmp3)


def test_isla_descripciones_narracion_y_mesa() -> None:
    # 3. La isla carga con description en todos sus lugares y narration en sus 16
    # acciones (17 con registrar de 16a); mesa.yaml carga con load_table.
    pack = load_pack(ISLA_PACK)
    assert len(pack.places) > 0
    for p in pack.places:
        assert p.description is not None and len(p.description) > 0

    assert len(pack.actions) == 17
    for a in pack.actions:
        assert a.narration is not None

    table = load_table(MESA_ISLA)
    assert isinstance(table, Table)
    assert "violencia" in table.veils
    assert "muerte" in table.veils


def test_banco_narracion_plantilla_contrato() -> None:
    # 4. run_tell_bank(load_moments(banco), ()): 95 momentos, del_modelo == 0,
    # cobertura 314/314, tuyos 158/158. Es el contrato de las plantillas.
    momentos = load_moments(BANCO_NARRACION)
    assert len(momentos) == 95
    informe = run_tell_bank(momentos, ())
    assert informe.momentos == 95
    assert informe.del_modelo == 0
    assert informe.hechos == 308
    assert informe.hechos_contados == 308
    assert informe.tuyos == 146
    assert informe.tuyos_contados == 146
