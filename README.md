# Agora

Simulador social multiagente para experiencias TTRPG. NPCs con agenda propia en
un mundo con vida independiente del jugador, y un agente narrador encima.

**Premisa:** el jugador no es el epicentro del mundo. Es un grano de arena más.

## Las cuatro reglas que no se negocian

1. **El motor es la única fuente de verdad.** El narrador lee y cuenta; nunca
   muta estado. Si el narrador puede inventar hechos, el mundo deja de existir.

2. **El motor no sabe en qué mundo corre.** Cero vocabulario de ambientación en
   `src/agora/`. La ambientación entra como content pack. Lo vigila
   `tests/test_agnosticism.py`, que se ejecuta en cada test run.

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

## Estado

**F0 — motor determinista.** En curso.

| Fase | Contenido |
|------|-----------|
| F0   | motor + pack loader + necesidades, rasgos, gustos, utility AI |
| F0.5 | segundo pack (sci-fi) como test ácido de agnosticismo |
| F1   | memoria, relaciones, miedos emergentes, memoria de lugar |
| F1.5 | metas, sueños, valores y tabúes |
| F2   | LangGraph: diálogo y reflexión. Router LLM local/API |
| F3   | el LLM planifica el día, valida, cae a fallback |
| F4   | el jugador entra como un NPC más. Entra `RuleSystem` |
| F5   | narrador/DM + RAG de lore |
| F6   | DM director: ajusta ritmo y cámara, jamás resultados |

## Desarrollo

```bash
uv sync
uv run pytest
uv run mypy src tests
uv run ruff check src tests
```

Reloj de simulación: **1 tick = 15 minutos**, 96 ticks por día.
