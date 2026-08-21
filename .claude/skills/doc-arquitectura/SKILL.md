---
name: doc-arquitectura
description: Actualiza docs/ARQUITECTURA.md. Úsala al añadir o quitar un módulo, cambiar el orden del tick loop, alterar el flujo de datos, o —lo más frecuente— cuando el motor gane una capacidad nueva o se descubra un límite que muerde. Es el único sitio donde vive la lista de QUÉ NO EXISTE.
---

# Mantener ARQUITECTURA.md

`docs/ARQUITECTURA.md` — qué hay, cómo circula el dato, y **qué no existe**.
Es el primer archivo que se consulta antes de escribir nada.

## Cuándo tocarlo

| Pasó esto | Actualiza |
|---|---|
| Módulo nuevo, o uno que crece mucho | §2 Carpetas (con el `wc -l` real) |
| Cambia el orden del tick loop | §3.2 |
| Nuevo paso en el ciclo decisión → efecto | §3.3 |
| Dependencia nueva | §1 Stack |
| **El motor gana una capacidad** | quítala de §5.1 |
| **Se descubre un límite** | añádelo a §5.2 |
| **Un pack estrena algo, o deja de usarlo** | §5.3 |
| Un puerto se implementa | §6 |

## §5 es el corazón — tres secciones y no una

```
§5.1  No existe en absoluto        lo que el motor no puede expresar
§5.2  Existe pero con un límite    lo que muerde al usarlo
§5.3  Existe y ningún mundo lo usa la deuda que ordena el trabajo
```

Confundirlas rompe el archivo. Una entrada de §5.2 lleva **el límite concreto y
su medición**, no una advertencia vaga:

```markdown
| `memory_capacity` | con 40 la biografía dura **tres días**; con 200, doce.
                      Es el techo real de todo lo acumulativo |
```

§5.3 se regenera midiendo, no de memoria:

```bash
uv run python -c "
from pathlib import Path
from agora.engine.pack import load_pack
for n in ('ciudad','confluencia','aldea','barrio'):
    t = load_pack(Path(f'packs/{n}/pack.yaml')).tuning
    print(n, t.memory_capacity, t.regret_weight, t.fear_weight, t.grief_scale, t.rumor_rate)
"
```

## Reglas

- **Los números salen de medir**, nunca de recordar. Tamaños con `wc -l`,
  perillas cargando el pack.
- Enlaza a los hermanos en vez de repetirlos: el *por qué* va en
  `DECISIONES.md`, el *cómo arreglarlo* en `ERRORES.md`.
- Si una capacidad se añade y ningún pack la usa, **pasa de §5.1 a §5.3**. No
  desaparece.
- Fecha las tablas volátiles (§5.3 lleva «Al DD/MM/AAAA»).
