---
name: doc-convenciones
description: Actualiza docs/CONVENCIONES.md. Úsala cuando aparezca un patrón nuevo del motor, cambie la configuración de mypy/ruff/pytest, se fije una regla de nombrado, o —lo más importante— cuando una convención se rompa y haya que decidir si se corrige el código o la convención.
---

# Mantener CONVENCIONES.md

`docs/CONVENCIONES.md` — cómo se escribe aquí y **por qué**.

> Todo lo de ahí está sacado del código que ya existe, no inventado. Si algo
> choca con lo que hay, **gana lo que hay o se cambia en los dos sitios**.

## Estructura

```
§1  herramientas y su configuración
§2  idioma (mixto, con regla)
§3  pydantic en las fronteras, dataclass dentro
§4  DETERMINISMO — las cuatro reglas mecánicas
§5  los docstrings son el argumento
§6  patrones del motor
§7  tests, y qué NO cuenta como evidencia
§8  contenido: cómo se escribe un pack
```

## §4 es lo más importante

Las cuatro reglas de determinismo. Romper cualquiera produce un bug que **no
rompe nada visible** — solo hace que dos corridas con la misma semilla difieran,
y eso se descubre semanas después.

```
1  nunca iterar un set/dict sin ordenar
2  desempatar por un entero único, nunca por el float
3  el RNG se deriva por clave: a quién, cuándo, de qué viene
4  una sola puerta por mecanismo
```

Si se añade una quinta, tiene que venir con **el bug real que la motivó**.

## §6 — un patrón nuevo se documenta con su excepción

El motor tiene tres formas de componer y confundirlas rompe cosas:

```
multiplicativa   M ** intensidad          la mayoría
aditiva          Σ(shift · intensidad)    phase_shift: es una traslación
exponente inv.   fade ** (1/m)            memory_multipliers
```

Cuando un patrón tenga excepción, **nómbrala ahí mismo**. Una regla sin su
excepción escrita se rompe sola.

## Reglas

- Los números salen de medir: `grep -c`, `wc -l`. La proporción español/inglés
  de los tests, la densidad de docstrings, cuántas clases pydantic hay.
- **Cuando una convención se rompa**, decide explícitamente: ¿se corrige el
  código o se corrige la convención? Las dos son respuestas válidas; no decidir
  no lo es.
- §7.2 no se toca a la ligera: fija que **una prueba unitaria verde no es
  evidencia de que algo funcione**. Lleva fecha y motivo.
- No repitas el flujo de trabajo. Aquí va el **estilo**; el procedimiento es
  `FLUJO.md`.
