---
name: doc-flujo
description: Actualiza docs/FLUJO.md, el procedimiento de trabajo. Úsala cuando cambie cómo se mide, cuando aparezca un paso nuevo del checklist, cuando el instrumental gane o pierda una capacidad, o cuando una regla de "cuándo NO hacer el cambio" se gane su sitio a base de costar tiempo.
---

# Mantener FLUJO.md

`docs/FLUJO.md` — cómo se hace un cambio, de principio a fin. Es el archivo
operativo, y existe para hacer cumplible **D-000: todo se prueba en conjunto**.

## Estructura

```
§1  antes de escribir nada    orden de consulta + ¿puede el mundo alimentarlo?
§2  la línea base             se mide ANTES, siempre
§3  el cambio                 motor / contenido, y las trampas
§4  medición de conjunto      EL PASO QUE NO SE SALTA
§5  checklist                 mecánico · de conjunto · de honestidad
§6  el commit                 formato y qué lleva el cuerpo
§7  cuándo NO hacer el cambio
```

## Cuándo tocarlo

| Pasó esto | Actualiza |
|---|---|
| Cambia cómo se mide algo | §4 |
| El instrumento gana o pierde capacidad | §4.4 |
| Un paso nuevo resulta obligatorio | §5 |
| Un comando cambia | §2, §3 |
| **Una regla se gana su sitio costando tiempo** | §7 |

## §4 es el corazón

Las cuatro condiciones **no se negocian**, y si alguna cambia hay que decir por
qué:

```
todo encendido · mundo real · plazo largo (60-90 días) · varios cortes (14/30/60)
```

Y la regla de lectura: **un mecanismo que decae por tramos está apagándose**,
aunque el número final parezca sano. Si algo se apaga, la causa casi nunca está
en ese mecanismo.

## §7 se gana a base de costar tiempo

No se añaden reglas por prudencia. Se añaden cuando algo **ya salió mal**, y con
el caso real:

```markdown
**No se cambian dos cosas a la vez.** Se hizo una vez y la conclusión salió
invertida: se culpó a `convidar` de matar las galerías cuando el `strain_weight`
de otra necesidad estaba rescatándolas en paralelo. Costó dos sesiones.
```

## Reglas

- Los comandos van **copiables y verificados**, no de memoria.
- Lo que le falta al instrumental se declara en §4.4 como **deuda declarada, no
  descuido**.
- El checklist es de tres tandas —mecánico, de conjunto, de honestidad— y la
  tercera es la que más se olvida.
- Si un procedimiento nace de un fallo, el fallo se nombra.
