"""Pruebas del intérprete de intenciones sobre el menú (unidad 14, D-163)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agora.cognition.intencion import (
    Entry,
    Kind,
    Menu,
    Order,
    briefing,
    interpret,
    lexical,
    resolve,
    schema,
)
from agora.engine.ports import CognitionProvider


class DummyProvider(CognitionProvider):
    def __init__(self, response: object | None) -> None:
        self.response = response

    def think(self, briefing: str, schema: type, semilla: int) -> object | None:
        return self.response


def menu_prueba() -> Menu:
    entries = (
        Entry(action="atacar", place="aqui", target="ana"),
        Entry(action="saquear", place="aqui", target="bea"),
        Entry(action="esconderse", place="arroyo_sur"),
        Entry(action="esconderse", place="arroyo_norte"),
        Entry(action="beber", place="arroyo_sur"),
    )
    actions = (
        ("atacar", "atacar", ("ataco a", "peleo con")),
        ("saquear", "saquear", ("saqueo a", "le quito las cosas")),
        ("esconderse", "esconderse", ("me escondo", "me oculto")),
        ("beber", "beber", ("bebo agua", "tengo sed")),
    )
    places = (
        ("aqui", "aquí", 0),
        ("arroyo_sur", "arroyo (sur)", 2),
        ("arroyo_norte", "arroyo (norte)", 4),
    )
    people = (
        ("ana", "Ana"),
        ("bea", "Bea"),
        ("cai", "Cai"),
    )
    orders = (Order.LOOK, Order.SHEET, Order.WAIT, Order.TALK)
    return Menu(entries=entries, actions=actions, places=places, people=people, orders=orders)


def test_resolve_con_accion_y_destinatario() -> None:
    # 1. resolve con acción y destinatario del menú devuelve esa entrada.
    m = menu_prueba()
    r = resolve(m, Kind.ACTION, action="atacar", target="ana")
    assert r.kind is Kind.ACTION
    assert r.entry == 0


def test_resolve_combinacion_que_no_esta() -> None:
    # 2. resolve(atacar, target=bea) (combinación que no está) es NO_FIT,
    # con atacar→ana y saquear→bea entre las candidatas.
    m = menu_prueba()
    r = resolve(m, Kind.ACTION, action="atacar", target="bea")
    assert r.kind is Kind.NO_FIT
    assert 0 in r.candidates  # atacar ana
    assert 1 in r.candidates  # saquear bea


def test_resolve_acepta_cualquier_lugar_repetido() -> None:
    # 3. resolve(esconderse, place=arroyo_norte) acepta cualquier «arroyo» y
    # devuelve el primero del menú con ese nombre (no exige el id).
    m = menu_prueba()
    r = resolve(m, Kind.ACTION, action="esconderse", place="arroyo_norte")
    assert r.kind is Kind.ACTION
    assert r.entry == 2  # el primero del menú con short_name "arroyo" (arroyo_sur)


def test_resolve_ambigua_con_candidatas() -> None:
    # 4. resolve(AMBIGUOUS, candidates=((atacar, ana),)) con una sola válida es
    # ACTION; con dos, AMBIGUOUS con las dos; con ninguna, NO_FIT.
    m = menu_prueba()
    # Una sola válida
    r1 = resolve(m, Kind.AMBIGUOUS, candidates=(("atacar", "ana"),))
    assert r1.kind is Kind.ACTION
    assert r1.entry == 0

    # Dos válidas
    r2 = resolve(m, Kind.AMBIGUOUS, candidates=(("atacar", "ana"), ("saquear", "bea")))
    assert r2.kind is Kind.AMBIGUOUS
    assert r2.candidates == (0, 1)

    # Ninguna válida
    r3 = resolve(m, Kind.AMBIGUOUS, candidates=(("volar", "nadie"),))
    assert r3.kind is Kind.NO_FIT


def test_schema_representantes_y_validacion() -> None:
    # 5. schema(menu): model_json_schema() enumera exactamente las acciones,
    # personas y lugares representantes del menú (arroyo_sur, no arroyo_norte),
    # y validar {"tipo":"accion","accion":"volar"} falla.
    m = menu_prueba()
    s = schema(m)
    js = s.model_json_schema()
    lugar_prop = js["properties"]["lugar"]
    # Los lugares permitidos solo incluyen los representantes: 'aqui' y 'arroyo_sur'
    lugares_enum = lugar_prop.get("enum")
    if lugares_enum is None:
        # Pydantic v2 anyOf con null
        any_of = lugar_prop.get("anyOf", [])
        for item in any_of:
            if "enum" in item:
                lugares_enum = item["enum"]
                break
    assert lugares_enum is not None
    assert set(lugares_enum) == {"aqui", "arroyo_sur"}
    assert "arroyo_norte" not in lugares_enum

    with pytest.raises(ValidationError):
        s.model_validate({"tipo": "accion", "accion": "volar"})


def test_order_no_tiene_salir() -> None:
    # 6. Order no tiene salir: set(Order) == {mirar, ficha, esperar, hablar, vivir}.
    assert set(Order) == {Order.LOOK, Order.SHEET, Order.WAIT, Order.TALK, Order.LIVE}
    assert {o.value for o in Order} == {"mirar", "ficha", "esperar", "hablar", "vivir"}


def test_interpret_con_proveedor_none() -> None:
    # 7. interpret con proveedor None es igual a lexical.
    m = menu_prueba()
    prosa = "me escondo en el arroyo"
    r_interp = interpret(m, prosa, None, 1312)
    r_lex = lexical(m, prosa)
    assert r_interp == r_lex
    assert r_interp.by_model is False


def test_interpret_proveedor_falla_o_invalido() -> None:
    # 8. interpret con un proveedor que devuelve None, un dict, o un modelo con
    # tipo="orden" y orden=None: el resultado es el de lexical y by_model is False.
    m = menu_prueba()
    prosa = "me escondo en el arroyo"
    lex = lexical(m, prosa)

    # Proveedor devuelve None
    r1 = interpret(m, prosa, DummyProvider(None), 1312)
    assert r1 == lex
    assert r1.by_model is False

    # Proveedor devuelve un dict (no BaseModel)
    r2 = interpret(m, prosa, DummyProvider({"tipo": "accion"}), 1312)
    assert r2 == lex
    assert r2.by_model is False

    # Proveedor devuelve modelo con tipo="orden" y orden=None
    s = schema(m)
    obj = s.model_validate({"tipo": "orden", "orden": None})
    r3 = interpret(m, prosa, DummyProvider(obj), 1312)
    assert r3 == lex
    assert r3.by_model is False


def test_interpret_con_proveedor_valido() -> None:
    # 9. interpret con un proveedor que devuelve una intención válida: by_model
    # y la entrada que corresponde.
    m = menu_prueba()
    s = schema(m)
    obj = s.model_validate({"tipo": "accion", "accion": "atacar", "destinatario": "ana"})
    r = interpret(m, "ataco a Ana", DummyProvider(obj), 1312)
    assert r.kind is Kind.ACTION
    assert r.entry == 0
    assert r.by_model is True


def test_lexico_resolucion_y_determinismo() -> None:
    # 10. Léxico: «me escondo en el arroyo» → esconderse@arroyo_sur (el más
    # cercano); «¿qué pasa?» sin nada parecido → QUESTION; la misma frase dos
    # veces da el mismo Reading.
    m = menu_prueba()
    r1 = lexical(m, "me escondo en el arroyo")
    assert r1.kind is Kind.ACTION
    assert r1.entry == 2  # esconderse @ arroyo_sur

    # «¿qué pasa?» sin nada parecido (por ejemplo en una escena sin órdenes) → QUESTION
    m_sin_ordenes = Menu(
        entries=m.entries, actions=m.actions, places=m.places, people=m.people, orders=()
    )
    r2 = lexical(m_sin_ordenes, "¿qué pasa?")
    assert r2.kind is Kind.QUESTION

    assert lexical(m, "bebo agua") == lexical(m, "bebo agua")


def test_briefing_no_contiene_no_representantes() -> None:
    # 11. briefing no contiene el id de ningún lugar que no sea representante.
    m = menu_prueba()
    b = briefing(m, "me escondo")
    assert "arroyo_sur" in b
    assert "arroyo_norte" not in b
