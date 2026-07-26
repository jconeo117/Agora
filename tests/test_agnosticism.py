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

PATTERN = re.compile(r"\b(" + "|".join(FORBIDDEN) + r")\b", re.IGNORECASE)


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
        f"  {source.name}:{lineno} -> {match.group(0)!r} en {text!r}"
        for lineno, text in _scannable(tree)
        if (match := PATTERN.search(text))
    ]

    assert not offenders, (
        "Ambientación filtrada dentro del motor:\n"
        + "\n".join(offenders)
        + "\n\nEso pertenece a un content pack. El motor solo conoce primitivas "
        "abstractas (Need, Action, Place, Tag)."
    )
