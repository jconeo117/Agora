---
name: doc-errores
description: Registra en docs/ERRORES.md algo que mordió, con síntoma, causa y solución. Úsala cuando un fallo cueste más de diez minutos de depuración, cuando un test propio falle por una premisa equivocada, o cuando alguien confunda una decisión deliberada con un bug — para eso está la sección "a propósito".
---

# Mantener ERRORES.md

`docs/ERRORES.md` — lo que muerde. **Síntoma → causa → solución.** Y una sección
aparte para lo que parece un fallo y es una decisión.

Casi todo lo de ahí costó al menos una sesión. Se consulta **antes** de depurar.

## El formato

```markdown
### E-0XX · Síntoma, escrito como lo vería alguien que no sabe la causa

**Síntoma** — Qué se ve. Mensaje exacto si lo hay.

**Causa** — Por qué pasa. Con el número o el caso real que lo demuestra.

**Solución** — Qué hacer. Concreto.
```

Numeración por bloque:

```
E-001..009   escribiendo contenido (packs)
E-010..019   escribiendo motor
E-020..029   midiendo
§4           a propósito — sin numerar
```

## Cuándo añadir una entrada

- Un fallo costó **más de diez minutos** de depuración
- **Un test propio falló por una premisa equivocada.** Estos son los mejores:
  *«afirmaba que al mendigo lo dejan morir; el motor hacía lo correcto y el
  escenario era mío»*
- Un mensaje de validación se repite y no es evidente qué lo causa
- Algo se comportó al revés de lo esperado **y estaba bien**

## §4 «A propósito» — la que evita arreglar lo que no está roto

Va sin numerar, con título en frase y el porqué debajo. Aquí entra todo lo que
alguien podría intentar «corregir»:

```markdown
### Bajo `--skip` no se muere nadie de hambre

`agonia` cuenta ticks **seguidos**, y a través de trece días sin simular
«seguidos» es falso. [...] **Borrarla dice lo único cierto: no sabemos qué pasó
esos días.**
```

Si al escribir la entrada dudas entre §1-3 y §4, pregúntate: **¿alguien debería
arreglarlo?** Si no, va en §4.

## Reglas

- El síntoma se escribe **desde la ignorancia**, como lo vería quien no sabe la
  causa. Es lo que hace el archivo buscable.
- La causa lleva **la medición**: `expoliar` cae un 68 % entre el día 30 y el 60.
- Si el error nace de una decisión, enlaza a `DECISIONES.md`. **No repitas el
  porqué**: aquí va el síntoma y el arreglo.
- Un error corregido en el motor **no se borra**: se deja con la solución, para
  que no se reintroduzca.
