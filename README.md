# Agora

Simulador social multiagente para experiencias TTRPG. NPCs con agenda propia en
un mundo con vida independiente del jugador, y un agente narrador encima.

**Premisa:** el jugador no es el epicentro del mundo. Es un grano de arena más.

El objetivo declarado no es replicar una mente: es que los NPCs **se sientan**
vivos con el LLM limitado a la prosa. El principio rector es **legibilidad, no
inteligencia** — el jugador debe poder reconstruir por qué alguien hizo algo, y
ser sorprendido de forma que tenga sentido a posteriori. Un NPC listo es caro y
aburrido; uno con historia, sesgos y un punto ciego cuesta microsegundos.

## Las cuatro reglas que no se negocian

1. **El motor es la única fuente de verdad.** El narrador lee y cuenta; nunca
   muta estado. Si el narrador puede inventar hechos, el mundo deja de existir.

2. **El motor no sabe en qué mundo corre.** Cero vocabulario de ambientación en
   `src/agora/`. La ambientación entra como content pack. Lo vigila
   `tests/test_agnosticism.py`, que analiza el AST en cada ejecución.

3. **La simulación corre entera sin LLM.** La cognición es una capa opcional
   sobre un motor determinista completo. Si el motor es plano, el LLM solo
   escribe prosa bonita sobre un mundo muerto.

4. **Portabilidad de modelo.** La experiencia debe aguantar con Claude, con
   Gemini o con un 7B local. Cambiar de modelo cambia la calidad de la prosa,
   nunca la coherencia del mundo. El motor entrega briefings precomputados y
   cerrados; el LLM devuelve estructuras pequeñas y validadas; todo fallo cae a
   un fallback determinista.

## Tres ejes independientes

| Eje | Dónde vive | Cambia con |
|-----|------------|------------|
| Ambientación | `packs/*/pack.yaml` | la campaña |
| Sistema de rol | `rules/` (desde F4) | la mesa |
| Motor de simulación | `src/agora/engine/` | nunca |

## Cómo se ejecuta

```bash
uv sync

uv run agora                      # siete días del barrio, log legible
uv run agora --days 3 --quiet     # solo el resumen
uv run agora --health             # panel de calibración y contrato del pack
uv run agora --jsonl corrida.jsonl   # log crudo, para diffear dos corridas
```

Reloj: **1 tick = 15 minutos**, 96 ticks por día.

## Estado

**F0 completo. F1 al 70 %.** El motor determinista funciona de punta a punta.

| | Fase | Contenido |
|---|------|-----------|
| ✅ | F0 | motor, pack loader, necesidades, rasgos, gustos, utility AI, tick loop |
| ✅ | F0.9 | calibración del barrio: 21 lugares, 10 residentes con nombre |
| ✅ | F1.0 | presencia: la compañía condiciona y alivia |
| ✅ | F1.1 | hastío por repetición y novedad |
| ✅ | F1.2 | coste de cambio: lo invertido protege de la interrupción |
| ✅ | F1.3 | precondiciones de recurso: el "no puedo permitírmelo" |
| ✅ | F1.4 | desgaste cognitivo: los días malos sin tocar la personalidad |
| ✅ | F1.5 | memoria como expectativas, sobre ganancias y sobre precios |
| ⬜ | F1.6 | percepción limitada: solo se delibera sobre lo que se conoce |
| ⬜ | F1.7 | arrepentimiento |
| ⬜ | F2 | LangGraph: diálogo y reflexión. Router LLM local/API |
| ⬜ | F3 | el LLM planifica el día, valida, cae a fallback |
| ⬜ | F4 | el jugador entra como un NPC más. Entra `RuleSystem` |
| ⬜ | F5 | narrador/DM + RAG de lore |
| ⬜ | F6 | DM director: ajusta ritmo y cámara, jamás resultados |

Las fórmulas y los valores vigentes, con su justificación, están en
`agora-formulas.md`.

## Arquitectura

```
src/agora/
  engine/
    ontology.py     primitivas invariantes: Need, Trait, Action, Place, Taste, Agent
    pack.py         carga y validación del mundo — un pack malformado no arranca
    state.py        estado mutable de una partida
    disposition.py  quién es este agente en números
    outcome.py      qué le pasó y qué concluye
    topology.py     grafo, distancias precomputadas, conexidad fuerte
    events.py       registro append-only indexado por actor y lugar
    world.py        el tick loop
    render.py       vista legible del log (depuración, NO el narrador)
    rng.py          aleatoriedad derivable por clave
  agents/
    decide.py       deliberación por utilidad
  health.py         mide un mundo y comprueba lo que promete
  run.py            CLI
```

**Costuras reservadas** en `engine/ports.py`, vacías a propósito:
`CognitionProvider` (F2), `MemoryStore` (F1), `RuleSystem` (F4). Se definieron
antes de necesitarlas para que el motor se construya contra ellas.

## Garantías

Verificadas por la batería de tests, no por convención:

- Misma semilla → mismo log byte a byte.
- El orden de consumo del RNG no afecta al resultado. Cada sorteo sale de un
  flujo derivado de `(semilla, clave)`, con la clave indexada por tiempo
  absoluto — requisito de la carga diferida que vendrá.
- Todo valor de necesidad queda en `[0, 1]`.
- Nadie se queda sin opciones válidas.
- Cero vocabulario de ambientación en el motor.
- Un pack no carga si tiene referencias rotas, acciones que nadie puede
  ejecutar, precondiciones más bajas de lo que la acción consume, efectos
  negativos sin coste declarado, o un grafo que no es fuertemente conexo.
- Cada pack declara su propio contrato de salud y se comprueba en cada corrida
  de tests.

## Packs

**`barrio`** — el mundo de trabajo. Barrio urbano contemporáneo: 21 lugares,
6 necesidades, 8 ejes de carácter, 13 acciones, 10 residentes con nombre.

**`dark_fantasy`** — existe para probar el agnosticismo, no para jugarse.
Deliberadamente sin calibrar: se degradó mientras el motor evolucionaba y solo
se le exigen los invariantes universales. Está escrito en el propio pack para
que sea una decisión y no un olvido.

## Desarrollo

```bash
uv run pytest
uv run mypy src tests
uv run ruff check src tests
```

Todo cambio de comportamiento se mide antes y después. Las decisiones de diseño
y su porqué viven en los docstrings y en los mensajes de commit — incluidas las
que salieron mal y por qué.
