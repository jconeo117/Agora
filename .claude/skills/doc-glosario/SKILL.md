---
name: doc-glosario
description: Actualiza docs/GLOSARIO.md. Úsala cuando nazca un término nuevo en un docstring o en una conversación, cuando se cree o renombre una entidad del motor, o cuando una sigla o una unidad necesite quedar fijada. Si una palabra se usa en dos sitios sin explicarse, va aquí.
---

# Mantener GLOSARIO.md

`docs/GLOSARIO.md` — el vocabulario que los otros cinco archivos usan sin
explicar.

## Tres secciones, y no se mezclan

```
§1  Términos     lo que NO es nombre de clase: puerta dura, el temple,
                 de gorra, chasco de llegada, contenido muerto...
§2  Entidades    las clases reales, agrupadas por pack / estado / memoria /
                 suceso / puertos
§3  Siglas       F0-F6, RAÍZ 1-5, TTRPG, LOD, AST... y las UNIDADES
```

## §1 — cómo se escribe un término

Negrita, guion largo, y **el origen si lo tiene**. Casi todos nacieron en un
docstring o midiendo algo:

```markdown
**Chasco de llegada** — Viajaste a un sitio y al llegar la acción ya no era
posible: la gente se fue, el dinero se gastó. Se delibera sobre lo que se
**recuerda**, y la verdad se comprueba al llegar.
```

Cuando dos términos se confunden entre sí, **defínelos juntos y por contraste**:

```markdown
**Deuda** — Es *cuán hundido* estás. Se paga a plazos.
**Agonía** — Es *cuánto llevas* hundido. Se borra de golpe. Solo esto mata.
```

## §2 — las entidades salen del código

Nunca de memoria:

```bash
grep -rhoE "^class [A-Za-z]+" src/agora/engine/*.py src/agora/agents/*.py src/agora/health.py | sed 's/class //' | sort
```

Una línea por entidad, diciendo **qué es**, no repitiendo sus campos.

## §3.4 — las unidades

Es lo que más se consulta. Mantén las conversiones y algún ejemplo real:

```
1 tick = 15 min · 96 ticks = 1 día · 360 días = 1 año
bond_horizon: 2880 = 30 días · lethal_after: 288 = 3 días
```

Con la regla: **todo lo que el pack declara en tiempo va en ticks**, nunca en
días.

## Reglas

- Si una palabra aparece en dos archivos sin explicarse, **va aquí**.
- Los apodos importan: `cost_multipliers` **es** «el temple», `cap_multipliers`
  **es** «el don». Se usan en conversación y hay que poder buscarlos.
- No expliques el *por qué* de una decisión: eso es `DECISIONES.md`. Aquí se
  define, no se argumenta.
- Al renombrar una entidad, **cámbiala aquí y en `ARQUITECTURA.md` §2**.
