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
   nunca la coherencia del mundo.

Y una quinta, de método: **todo cambio de comportamiento se mide antes y
después**. Cuando una métrica no se mueve, sospecha de la métrica.

## Tres ejes independientes

| Eje | Dónde vive | Cambia con |
|-----|------------|------------|
| Ambientación | `packs/*/pack.yaml` | la campaña |
| Sistema de rol | `rules/` (desde F4) | la mesa |
| Motor de simulación | `src/agora/engine/` | nunca |

## Cómo se ejecuta

```bash
uv sync

uv run agora --pack packs/ciudad/pack.yaml            # una semana, log legible
uv run agora --pack packs/ciudad/pack.yaml --health   # panel de calibración
uv run agora --days 3 --quiet                         # solo el resumen

# corridas largas
uv run agora --days 1800 --skip 14 --window 7 --save graduados.json
uv run agora --load graduados.json --days 360 --jsonl siguiente.jsonl
```

Reloj: **1 tick = 15 minutos**, 96 ticks por día.

| Opción | Qué hace |
|---|---|
| `--skip N` | simula un día de cada N y da la zancada a los ejes de progresión |
| `--window D` | el log conserva solo los últimos D días |
| `--jsonl F` | vierte el log según ocurre, en streaming |
| `--save` / `--load` | guarda y reanuda la partida |
| `--health` | mide el mundo y contrasta el contrato que el pack declara |

---

## Qué sabe hacer el motor

### Decidir

La utilidad de cada par (acción, lugar) del mundo entero, descontada por el
viaje. El agente elige un objetivo; el viaje es la consecuencia.

```
beneficio = Σ( peso · urgencia · satisface · lo_aprendido )
utilidad  = beneficio · descuento_viaje · gustos · novedad · compañía · hora
                      · situación
          - aversión · (coste + peaje)
```

- **Siete puertas duras** antes de puntuar: la affordance del lugar, su horario,
  que ninguna situación lo cierre, que haya gente suficiente, que esté *quien*
  tiene que estar, que alcancen los recursos y que seas quien hay que ser.
- **Compromiso con excepción de urgencia**: se delibera al quedar ocioso y lo
  elegido se termina, salvo que algo cruce su umbral crítico. Reevaluar cada
  tick produce agentes que no acaban nada.
- **Percepción limitada**: se delibera sobre lo que se recuerda haber visto. Lo
  que no se sabe se supone a favor, y el chasco llega al llegar.

### Ser alguien

- **Rasgos** con cuatro canales: cuánto le importa cada necesidad, cómo decide
  (temperamento), cuánto le cunde lo que hace (aptitud) y cuánto va adelantado
  su reloj interno (cronotipo). La intensidad es un exponente: 0 neutraliza, −1
  invierte.
- **Temperamento** en cinco perillas —azar, aversión al precio, umbral de
  pánico, peso de la distancia y cuánto le atrae la gente— compuestas del mundo,
  de los rasgos y del desgaste actual.
- **Desgaste**: los días malos sin tocar la personalidad. El mismo NPC decide
  distinto según cómo esté, y sigue siendo él.
- **Gustos** por instancia. Los rasgos sesgan categorías; los gustos sesgan
  cosas concretas. Sin esta capa todos los sociables se comportan igual.
- **Creencias aprendidas**, sobre lo que rinde algo y sobre lo que cuesta.
  Descubrir que algo sale más caro cambia una rutina tanto como descubrir que
  rinde menos.
- **Metas** con plazo, que al cumplirse o al vencer mueven rasgos. Diez rutinas
  pasan a ser diez historias.

### Estar con otros

- **Vínculos** asimétricos: cada uno guarda el suyo y no tienen por qué
  coincidir. Nacen de compartir ratos, se desdibujan sin trato y se olvidan.
- **Relaciones con nombre** —pareja, hermano, maestro— que son otra cosa: *un
  vínculo es lo que sientes; una relación es lo que eres de alguien*. No crecen
  con el trato, no se disuelven por dejar de verse y **no se olvidan**.
- La compañía **condiciona y alivia**: pesa lo que rinde una acción, frena el
  decaimiento y atrae al deliberar. Cuánta gente es "una multitud" lo declara
  cada pack.

### Tener cuerpo y horario

- **Acciones elásticas**: dormir dura lo que haga falta, entre un suelo y un
  tope, según el déficit de esa persona en ese sitio.
- **Deuda**: se puede estar peor que vacío. Un guerrero tras tres días de
  batalla y alguien que durmió mal dejan de ser indistinguibles.
- **Franjas del día** y **cronotipo**: el horario del mundo es objetivo, el del
  cuerpo es subjetivo. El ave nocturna trabaja de madrugada.
- **Ejes de progresión**: números que solo suben y nunca son una emergencia.

### Tener mundo

- **Grafo dirigido** con distancias precomputadas y **peajes** por arista: una
  arista con precio es un servicio, no un atajo, y por eso hay quien paga y
  quien camina.
- **Situaciones**: estados del mundo con nombre que van y vienen. Periódicas
  (estaciones, ferias) o eventuales (guerra, derrumbe, oleada). Multiplican lo
  que rinde, lo que apetece, y pueden cerrar un lugar.

### Durar

- **Persistencia**: se guarda el estado, no la historia, y se reconcilia con el
  pack de hoy. Reanudar en el tick N da exactamente lo mismo que no haber
  parado.
- **Salto temporal**: se simulan días de verdad, solo que menos. Lo que oscila
  queda exacto porque no se estima; solo se aproxima lo monótono. Cinco años de
  la ciudad en dos minutos.
- **Log acotado**: ventana en memoria y vertido a disco según ocurre, con los
  totales contabilizados aparte para que un resumen no pueda mentir.

---

## Estado

**F0 completo. F1 completo salvo memoria episódica y arrepentimiento.**

| | Fase | Contenido |
|---|------|-----------|
| ✅ | F0 | motor, pack loader, necesidades, rasgos, gustos, utility AI, tick loop |
| ✅ | F1.0 | presencia: la compañía condiciona y alivia |
| ✅ | F1.1 | hastío por repetición y novedad |
| ✅ | F1.2 | coste de cambio: lo invertido protege de la interrupción |
| ✅ | F1.3 | precondiciones de recurso: el "no puedo permitírmelo" |
| ✅ | F1.4 | desgaste cognitivo: los días malos sin tocar la personalidad |
| ✅ | F1.5 | memoria como expectativas, sobre ganancias y sobre precios |
| ✅ | F1.6 | percepción limitada: solo se delibera sobre lo que se conoce |
| ✅ | F1.7 | capa relacional: se dejan de contar cabezas |
| ✅ | F1.8 | reloj con franjas, cronotipo, elasticidad y deuda |
| ✅ | F1.9 | metas y arcos, ejes de progresión, aptitud y puertas por rasgo |
| ✅ | F1.10 | persistencia, salto temporal, log acotado |
| ✅ | F1.11 | situaciones y relaciones con nombre |
| ⬜ | F1.12 | memoria episódica (`MemoryStore`) y arrepentimiento |
| ⬜ | F2 | diálogo y reflexión. Router LLM local/API |
| ⬜ | F3 | el LLM planifica el día, valida, cae a fallback |
| ⬜ | F4 | el jugador entra como un NPC más. Entra `RuleSystem` |
| ⬜ | F5 | narrador/DM + RAG de lore |
| ⬜ | F6 | DM director: ajusta ritmo y cámara, jamás resultados |

Los frentes de mundo pendientes —descendencia, propiedad, facciones,
disparadores, psicología ampliada— viven en `PLAN.md`, con lo que cada uno
desbloquea y qué lo bloquea.

## Arquitectura

```
src/agora/
  engine/
    ontology.py     primitivas invariantes: Need, Trait, Action, Place, Goal,
                    Phase, Relation, Situation, Taste, Agent, Tuning
    pack.py         carga y validación del mundo — un pack malformado no arranca
    state.py        estado mutable de una partida, y el libro de calibración
    disposition.py  quién es este agente en números
    outcome.py      qué le pasó y qué concluye
    topology.py     grafo, distancias precomputadas, conexidad fuerte
    events.py       registro append-only, con ventana, vertido y recuento
    world.py        el tick loop
    persistence.py  guardar y reanudar, reconciliando con el pack de hoy
    timeskip.py     avanzar meses sin simular cada cuarto de hora
    render.py       vista legible del log (depuración, NO el narrador)
    rng.py          aleatoriedad derivable por clave
    ports.py        costuras reservadas, vacías a propósito
  agents/
    decide.py       deliberación por utilidad
  health.py         mide un mundo y comprueba lo que promete
  run.py            CLI
```

**Costuras reservadas** en `engine/ports.py`, vacías a propósito:
`MemoryStore` (F1.12), `CognitionProvider` (F2), `RuleSystem` (F4). Se
definieron antes de necesitarlas para que el motor se construya contra ellas.

## Garantías

Verificadas por la batería de tests, no por convención:

- Misma semilla → mismo log byte a byte, **también entre procesos distintos**
  (comprobado con `PYTHONHASHSEED` variable).
- El orden de consumo del RNG no afecta al resultado: cada sorteo sale de
  `blake2b(semilla, agente, tick)`. Es lo que hace que reanudar una partida sea
  exacto.
- Todo valor de necesidad queda en `[0, 1]`, y la deuda guarda aparte lo que el
  suelo recortaría.
- Nadie se queda sin opciones válidas.
- Cero vocabulario de ambientación en el motor.
- Un pack no carga si tiene referencias rotas, acciones que nadie puede
  ejecutar, precondiciones más bajas de lo que la acción consume, efectos
  negativos sin coste declarado, un grafo que no es fuertemente conexo, una
  situación que no hace nada, dos parejas para la misma persona, inversas que no
  se corresponden, o un alivio pasivo que supera al decaimiento.
- Cada pack declara su propio contrato de salud y se comprueba en cada corrida
  de tests.

## Packs

| Pack | Lugares | Acciones | Agentes | Para qué |
|---|---|---|---|---|
| `ciudad` | 25 | 32 | 127 | el mundo de trabajo |
| `aldea` | 13 | 17 | 10 | mundo pequeño, contrato sobre tres semillas |
| `barrio` | 21 | 13 | 10 | el mundo contemporáneo original |
| `dark_fantasy` | 5 | 5 | 2 | prueba de agnosticismo, no se juega |

**`ciudad`** — fantasía con academia de magia y una sima debajo. Dos poblaciones
con vidas distintas en el mismo mapa: los alumnos viven dentro de la academia,
los cazadores bajan a la sima, y la ciudad vive del gasto de ambos. Cuatro
situaciones (invierno, feria, ventisca, oleada), cuatro clases de relación, y
una carrera de cinco años que se recorre con el salto temporal.

**`dark_fantasy`** — deliberadamente sin calibrar: se degradó mientras el motor
evolucionaba y solo se le exigen los invariantes universales. Está escrito en el
propio pack para que sea una decisión y no un olvido.

## Calibrar

`--health` mide el mundo y contrasta lo que el pack promete. Además del panel
clásico, informa de **oferta y demanda por eje**:

```
oferta/demanda por eje   (>1.3 = el eje no decide nada)
  vinculo          1.12   de gorra 25%
  nucleo           1.09
  descanso         0.98
```

Un eje muy por encima de 1.0 está resuelto y no decide nada: todo lo que el pack
escribió alrededor de él es decorado. La columna `de gorra` dice qué fracción
llega **sin cumplir la condición que el pack dice que importa**, y es la que
indica dónde cortar — mientras la oferta sea incondicional, encarecer el eje
solo hace que la gente se quede quieta.

Este instrumento se construyó tarde y lo primero que hizo fue destapar que el
vínculo de la ciudad llevaba 256 000 muestras sin apretar ni una vez mientras el
panel se veía sano.

## Desarrollo

```bash
uv run pytest          # 529 tests
uv run mypy src tests  # estricto
uv run ruff check
```

Las decisiones de diseño y su porqué viven en los docstrings y en los mensajes
de commit — incluidas las que salieron mal y por qué. Un docstring de este
proyecto explica *por qué* algo es así y qué se rompió al hacerlo de otro modo;
si solo repite lo que hace la función, sobra.
