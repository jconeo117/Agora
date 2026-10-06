"""El test ácido: el motor no puede saber en qué mundo está corriendo.

La disciplina personal no aguanta seis meses de desarrollo. Esto sí.
Si falla, alguien filtró ambientación dentro del motor y hay que sacarla al
content pack antes de seguir.

Qué escanea y qué no
--------------------
Escanea lo que puede alterar el comportamiento: **identificadores** y
**literales de cadena reales**. Ignora comentarios y docstrings, porque un
comentario que dice "esto NO sabe qué es una espada" documenta el
agnosticismo en vez de romperlo. Por eso el análisis va por `ast` y no por
expresión regular sobre el fichero crudo.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1] / "src" / "agora"

# Vocabulario prohibido. Crecerá según lo que definan los packs.
# Ir añadiendo aquí es sano: cada término nuevo es una trampa que ya no caerá.
FORBIDDEN = [
    # fantasía
    "espada", "magia", "hechizo", "mana", "maná", "elfo", "orco", "dragon",
    "dragón", "taberna", "castillo", "caballero", "poción", "runa",
    # ciencia ficción
    "nave", "laser", "láser", "plasma", "androide", "hiperespacio", "blaster",
    "oxigeno", "oxígeno", "cyborg", "warp",
    # necesidades y recursos concretos: van en el pack, no en el motor
    "hambre", "sueno", "sueño", "cordura", "oro", "credito", "crédito",
]

PROHIBIDAS = frozenset(w.lower() for w in FORBIDDEN)


def _trozos(texto: str) -> Iterator[str]:
    """Las palabras de un identificador o de una cadena.

    Antes se buscaba con `\\b`, y `\\b` trata `_` como letra: `need_hambre`,
    `gold_oro` o `manaPool` pasaban limpios en un motor escrito en snake_case.
    Se parte por todo lo que no es letra o cifra y por cada cambio a mayúscula.
    """
    for parte in re.split(r"[^0-9A-Za-zÀ-ÿ]+", texto):
        for trozo in re.sub(r"([a-zà-ÿ0-9])([A-ZÀ-Þ])", r"\1 \2", parte).split():
            yield trozo.lower()


def _prohibida(trozo: str) -> str | None:
    """La palabra prohibida que es este trozo, en singular o en plural."""
    for raiz in (trozo, trozo.removesuffix("s"), trozo.removesuffix("es")):
        if raiz in PROHIBIDAS:
            return raiz
    return None


def _engine_sources() -> list[Path]:
    return sorted(
        path
        for path in ENGINE_ROOT.rglob("*.py")
        # `packs` y `cognition/prompts` sí pueden nombrar cosas del mundo.
        if "packs" not in path.parts and "prompts" not in path.parts
    )


def _prose_nodes(tree: ast.AST) -> set[int]:
    """Cadenas que son documentación, no datos.

    Cubre las tres formas: docstring de módulo, de clase/función, y el idiom de
    pydantic de poner una cadena suelta bajo un campo. Las tres son un
    `Expr` cuyo valor es una constante de texto.
    """
    return {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def _scannable(tree: ast.AST) -> list[tuple[int, str]]:
    """Devuelve (línea, texto) de todo lo que sí puede alterar comportamiento."""
    prose = _prose_nodes(tree)
    found: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        match node:
            case ast.Constant(value=str() as text) if id(node) not in prose:
                found.append((node.lineno, text))
            case ast.Name(id=name):
                found.append((node.lineno, name))
            case ast.Attribute(attr=name):
                found.append((node.lineno, name))
            case ast.arg(arg=name):
                found.append((node.lineno, name))
            case ast.keyword(arg=str() as name):
                found.append((node.lineno, name))
            case ast.FunctionDef(name=name) | ast.ClassDef(name=name):
                found.append((node.lineno, name))

    return found


def test_engine_sources_exist() -> None:
    """Evita el falso verde: un test que no escanea nada siempre pasa."""
    assert _engine_sources(), f"no se encontró código de motor en {ENGINE_ROOT}"


@pytest.mark.parametrize("source", _engine_sources(), ids=lambda p: p.name)
def test_engine_has_no_setting_vocabulary(source: Path) -> None:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    offenders = [
        f"  {source.name}:{lineno} -> {palabra!r} en {text!r}"
        for lineno, text in _scannable(tree)
        for trozo in _trozos(text)
        if (palabra := _prohibida(trozo))
    ]

    assert not offenders, (
        "Ambientación filtrada dentro del motor:\n"
        + "\n".join(offenders)
        + "\n\nEso pertenece a un content pack. El motor solo conoce primitivas "
        "abstractas (Need, Action, Place, Tag)."
    )


@pytest.mark.parametrize(
    "palabra",
    ["need_hambre", "gold_oro", "manaPool", "espadas", "naves", "Espada"],
)
def test_lo_que_se_escapaba_ya_no_se_escapa(palabra: str) -> None:
    assert any(_prohibida(trozo) for trozo in _trozos(palabra))


@pytest.mark.parametrize(
    "palabra",
    ["manager", "coronas", "mananas", "oroboros", "nacido_en", "need_weights"],
)
def test_lo_que_se_parece_no_es_prohibido(palabra: str) -> None:
    assert not any(_prohibida(trozo) for trozo in _trozos(palabra))
