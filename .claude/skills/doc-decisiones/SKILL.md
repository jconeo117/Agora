---
name: doc-decisiones
description: Registra una decisión de diseño en docs/DECISIONES.md. Úsala cuando se elija entre dos formas de hacer algo, cuando se descarte una alternativa, y sobre todo cuando una decisión anterior resulte FALSA al medirla — la sección de revertidas es la más valiosa del archivo.
---

# Mantener DECISIONES.md

`docs/DECISIONES.md` — qué se decidió, **por qué**, qué se descartó, y si sigue
en pie.

> Una decisión sin su alternativa descartada no es una decisión: es una
> costumbre. **La tercera columna es obligatoria.**

## El formato

```markdown
| **D-0XX** | Qué se decidió | Por qué | Qué se descartó | `estado` |
```

Estados: `vigente` · `revertida` · `superada` · `pendiente`

Numeración por bloques, sin reutilizar ids:

```
D-000        la regla que ordena todo (todo se prueba en conjunto)
D-001..009   fundacionales
D-010..019   determinismo
D-020..029   estructura de datos
D-030..049   psicología y memoria
D-050..069   mundo y consecuencia
D-070..079   instrumento
D-090..099   revertidas / corregidas / superadas
D-100..      pendientes con decisión ya tomada
```

## §7 es la sección que más sirve

Cuando algo que creímos resulta falso, **no se borra la entrada: se mueve a §7**
con lo que resultó ser, y la original queda `superada`.

```markdown
| **D-09X** | Qué creímos | Qué resultó, CON LA MEDICIÓN | `superada` |
```

Ejemplo real:

```markdown
| **D-092** | «Añadir una necesidad recompone los pesos del mundo» |
**Falso.** `compose_need_weights` asigna `base_weight` absoluto. Medido dos
veces: el panel no se mueve ni una milésima. Pero **`strain_weight` sí
renormaliza** — ese era el culpable | `superada` |
```

Seis decisiones del proyecto resultaron falsas al medirlas, y las seis parecían
obvias cuando se tomaron. **Ese es el valor del archivo.**

## Reglas

- El *por qué* lleva **el número que lo justifica** cuando existe: *«medido: 200
  agentes, año y medio, los 200 al máximo»*.
- Si la decisión sale de un fallo, dilo. Un fallo propio explicado vale más que
  un acierto sin explicar.
- **No dupliques**: el síntoma y cómo arreglarlo van en `ERRORES.md`; aquí va la
  elección y su alternativa.
- Una decisión `pendiente` que bloquea trabajo real se marca como tal — hoy
  D-094 (el techo en `dominio`) es la única.
