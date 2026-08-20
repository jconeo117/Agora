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
| `--divergence N` | corre N semillas y mide cuánto pesa el azar frente al carácter |

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

- **Ocho puertas duras** antes de puntuar: la affordance del lugar, su horario,
  que ninguna situación lo cierre, que haya gente suficiente, que esté *quien*
  tiene que estar, que alcancen los recursos, que seas quien hay que ser, y —si
  la acción apunta a alguien— que ese alguien esté delante.
- **Compromiso con excepción de urgencia**: se delibera al quedar ocioso y lo
  elegido se termina, salvo que algo cruce su umbral crítico. Reevaluar cada
  tick produce agentes que no acaban nada.
- **Percepción limitada**: se delibera sobre lo que se recuerda haber visto. Lo
  que no se sabe se supone a favor, y el chasco llega al llegar.

### Ser alguien

- **Rasgos** con siete canales. La intensidad es un exponente: 0 neutraliza, −1
  invierte.

  | canal | qué dice |
  |---|---|
  | `need_weight_multipliers` | cuánto le **importa** cada eje |
  | `gain_multipliers` | cuánto le **cunde** lo que gana (aptitud) |
  | `cost_multipliers` | cuánto le **duele** lo que gasta (temple) |
  | `cap_multipliers` | hasta **dónde** puede llegar (el don) |
  | `memory_multipliers` | cuánto le **dura** lo que recuerda |
  | `temperament_multipliers` | cómo **decide** |
  | `phase_shift` | cuánto va adelantado su **reloj interno** |

  El séptimo es el único que **no se compone multiplicando**, y por aritmética:
  un fade es la fracción que sobrevive cada tick, así que `0.99 × 4` da 3.96 —
  que no es *recuerda cuatro veces más*, es un número inválido. Lo que se
  multiplica es la media vida, y eso es un exponente: `fade ** (1/m)`.

  **Temple** y **techo** salieron de un sistema de magia. Una reserva grande no
  es más que *cada conjuro me drena menos*; y un techo resultó ser lo único que
  hace que una progresión signifique algo en una corrida larga — con un ritmo
  bajo se tarda más en llegar al máximo, pero **con tiempo suficiente llega todo
  el mundo**. Medido: doscientos agentes, año y medio, y los doscientos al tope
  del mismo eje.

  El **olvido propio** salió de otra petición que el motor no podía cumplir: que
  un duelo se supere en dos semanas y otro reordene una vida. Con un
  `memory_fade` único del pack eso era imposible por construcción — los 127
  olvidaban al mismo ritmo exacto, así que dos duelos solo podían diferenciarse
  en cuánto pesaban el primer día.
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

### Recordar lo que pasó

- **Memoria episódica**: hechos con fecha, sitio, culpable y valencia. Cada
  recuerdo se guarda **entero** —no un puntero a un log que la persistencia
  poda— y se olvida por lo que aún vale, no por antigüedad: lo importante dura.
- **Arrepentimiento**: lo que salió mal encarece *esa acción* para *quien la
  vivió*. Es memoria, no castigo del mundo: acota, nunca veta. El beneficio
  crece con la urgencia y el escarmiento no, así que el hambre siempre acaba
  ganando a la mala experiencia.
- **Miedo a sitios**: donde te pasó algo malo que no fue culpa tuya. Se cobra en
  el viaje, no en la acción — se rodea el lugar, no se deja de comer.
- **Duelo**: cuánto duele hoy la ausencia de alguien. Tercer índice y el primero
  sobre un eje distinto: `rencor` mira lo que HICISTE, `miedo` DÓNDE estabas y
  este A QUIÉN. Es el único que **no tiene un `_weight` al lado**, y la ausencia
  es la mitad del diseño: de una acción y de un lugar uno puede apartarse, de un
  ausente no. Lo que diferencia dos duelos no es una perilla — es de qué viene
  acompañado el recuerdo (sin lugar duele y se pasa; con lugar, `miedo` le cambia
  la rutina) y cuánto le dura a cada cual.
- **Rumores**: un recuerdo que se copia. Lo que se cuenta es **lo que sorprendió,
  no lo que apretó** — la urgencia es vívida para quien la vive y aburrida para
  quien la oye. Se degrada por boca, el `seq` no cambia (así *¿ya me sé esto?* es
  comparar enteros) y el `tick` tampoco, así que un rumor viejo llega ya
  desdibujado. Y **si va sobre alguien, el peso lo pone quien escucha**: te
  enteras de que murió tu ídolo por boca de alguien a quien le daba igual, y te
  destroza igual.

Los cuatro se apagan por pack, y en `ciudad` van apagados **tras medirlo**: el
arrepentimiento homogeneizaba porque todos se llevaban el mismo chasco, el miedo
tenía la señal contaminada, y los rumores no encuentran sitio —los 127 van a
40/40 de recuerdos propios, y de oídas llega a la mitad de peso, así que el
olvido por valor lo tira al llegar—. El motor sabe hacer más cosas de las que
este mundo le pide, y eso se documenta en vez de esconderse.

### Estar con otros

- **Vínculos** asimétricos: cada uno guarda el suyo y no tienen por qué
  coincidir. Nacen de compartir ratos, se desdibujan sin trato y se olvidan.
- **Cruzarse no es convivir.** Se cuentan aparte los encuentros y los ratos
  compartidos: dos que coinciden cien veces sin dirigirse la palabra se
  distinguen y nada más; dos que coinciden veinte y comparten diez son amigos.
- **Relaciones con nombre** —pareja, hermano, maestro— que son otra cosa: *un
  vínculo es lo que sientes; una relación es lo que eres de alguien*. No crecen
  con el trato, no se disuelven por dejar de verse y **no se olvidan**.
- La compañía **condiciona y alivia**: pesa lo que rinde una acción, frena el
  decaimiento y atrae al deliberar. Cuánta gente es "una multitud" lo declara
  cada pack.
- **Acciones con destinatario**: curar, dar, enseñar, agredir. Hasta que
  existieron, todo `satisfies`/`effects`/`costs` caía sobre quien actúa y el
  motor eran ciento veintisiete personas actuando sobre sí mismas en presencia de
  otras. `requires_company` parece social y no lo es: dice quién tiene que
  **estar**, no a quién le pasa nada.

  El motor **no necesita saber qué es el altruismo**: ayudar paga lo que el pack
  diga que paga, y por eso se hace. Y agredir no necesita primitiva — `gives`
  negativo es dar con el signo cambiado.

  A quién se elige **entre los que tienes delante**, filtrando por condición
  —una herida se ve, el valor exacto de las necesidades de otro no— y
  desempatando por aprecio. El aprecio **encoge la recompensa, no la veta**: a un
  desconocido se le ayuda cuando no hay nada mejor que hacer.

### Tener cuerpo y horario

- **Acciones elásticas**: dormir dura lo que haga falta, entre un suelo y un
  tope, según el déficit de esa persona en ese sitio.
- **Deuda**: se puede estar peor que vacío. Un guerrero tras tres días de
  batalla y alguien que durmió mal dejan de ser indistinguibles.
- **Franjas del día** y **cronotipo**: el horario del mundo es objetivo, el del
  cuerpo es subjetivo. El ave nocturna trabaja de madrugada.
- **Ejes de progresión**: números que solo suben y nunca son una emergencia.
  Cada uno con su **techo por persona**, y el apremio medido contra ese techo:
  quien ya dio todo lo que podía deja de perseguir ese eje y gasta el tiempo en
  otra cosa, en vez de entrenar de por vida algo que no va a mejorar.
- **Condiciones**: lo que uno lleva encima. Herida, infección, veneno,
  borrachera. No es una primitiva nueva — es una situación pegada a una persona
  en vez de a un lugar, y toda la maquinaria del daño ya era por agente.

  Se **acumulan por marca**: brazo, pierna y torso drenan por separado; dos en el
  mismo brazo no duran más, **duelen más**. La marca es opaca — el motor compara
  cadenas y no puede saber qué es un brazo. Se quitan **por plazo y por acción**,
  y las dos hacen falta: sin plazo, una infección que nadie sabe curar mata a
  todo el mundo; sin acción, curarse no se puede decidir.
- **Morir**: `lethal_after` declara cuántos ticks seguidos a cero aguanta un eje.
  **Una sola regla de muerte y tantas causas como el pack quiera** — inanición,
  deshidratación, sobrecarga de maná, desangrarse. No hay muerte-por-herida: hay
  una herida que drena, un eje que llega a cero y un reloj que cobra.

  Dos ejes que ya no se confunden: `debt` dice **cuán hundido** estás y se paga a
  plazos; `agonia`, **cuánto llevas** hundido y se borra de golpe al levantar. Se
  puede tocar fondo un instante sin morirse y vivir raspando el suelo un mes
  tampoco mata.

### Tener mundo

- **Grafo dirigido** con distancias precomputadas y **peajes** por arista: una
  arista con precio es un servicio, no un atajo, y por eso hay quien paga y
  quien camina.
- **Situaciones**: estados del mundo con nombre que van y vienen. Periódicas
  (estaciones, ferias) o eventuales (guerra, derrumbe, oleada). Multiplican lo
  que rinde, lo que apetece, pueden cerrar un lugar y **hacer daño directo** a
  quien esté dentro. Un cuarto canal, y el que las vuelve peligrosas: hasta
  tenerlo, una ventisca solo encarecía cosas.
  El daño se archiva como **pasivo** —te pasó, no lo hiciste— para que la
  memoria no lo confunda con una mala decisión propia.
- **Disparadores**: una situación puede arrancar sola cuando el mundo cumple una
  condición, en vez de por calendario o por guion. Es lo que separa *"en
  invierno hay ventiscas"* de *"la sima se desborda si nadie baja a limpiarla"*.
  El salto temporal los evalúa por tramos, no por tick, para que `--skip 14` no
  los apague sin avisar.

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

**F0 y F1 completos.** El motor determinista está entero: nada de lo que queda
por hacer en F2–F6 puede empezar sin él, y ya no lo bloquea.

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
| ✅ | F1.12 | memoria episódica, arrepentimiento y miedo a lugares |
| ✅ | F1.13 | disparadores, situaciones que dañan, techos, temple y el lazo que se gana |
| ✅ | F1.14 | censo mutable, la pérdida, el duelo, el olvido propio y los rumores |
| ✅ | F1.15 | morir con causa, condiciones, y acciones con destinatario |
| ⬜ | F2 | diálogo y reflexión. Router LLM local/API |
| ⬜ | F3 | el LLM planifica el día, valida, cae a fallback |
| ⬜ | F4 | el jugador entra como un NPC más. Entra `RuleSystem` |
| ⬜ | F5 | narrador/DM + RAG de lore |
| ⬜ | F6 | DM director: ajusta ritmo y cámara, jamás resultados |

## Lo siguiente: un mundo que use lo que el motor sabe

**Cinco mecanismos se envían apagados**, y a estas alturas el patrón es el
hallazgo: arrepentimiento, miedo, duelo, rumores y mortalidad están escritos,
probados y sin usar en ningún pack. El motor va muy por delante de sus mundos.

Ninguno se apagó por capricho. Cada uno tiene una medición detrás:

| mecanismo | por qué está apagado |
|---|---|
| arrepentimiento | homogeneizaba: todos se llevan el mismo chasco |
| miedo a lugares | la señal estaba contaminada por acciones sociales a solas |
| duelo | `about` salía al **0 %** — nada de lo que se recordaba iba sobre nadie |
| rumores | no hay sitio: los 127 van a 40/40 de recuerdos propios |
| mortalidad | ningún pack declara nada letal |

Los dos últimos ya no tienen excusa. Las acciones con destinatario producen
hechos sociales, así que `about` deja de estar vacío; y `lethal_after` existe.

Así que la línea es **encender el motor en un mundo y medirlo**, no añadir un
sexto mecanismo a la pila. La regla del proyecto dice que todo cambio de
comportamiento se mide antes y después, y hay cinco que nunca se han medido en un
mundo poblado. Concretamente:

1. **Una necesidad letal** y una condición que la drene. Es donde se ve si la
   muerte da el precio a equivocarse que el motor lleva tres campañas pidiendo.
2. **Curar y agredir** en `ciudad`, para que `about` deje de ser cero.
3. **Rumores encendidos**, con la capacidad de memoria que haga falta para que
   quepan — el número está medido y documentado.
4. **Volver a medir el panel entero**: diferenciación, geografía, divergencia. La
   población deja de ser fija, así que hay que decidir qué significa una media
   cuando la gente se muere.

Detrás de eso, y ya con datos, quedan tres frentes grandes: **facciones**
(RAÍZ 5, la última pieza social), **edad y descendencia** (que el censo mutable
ya desbloqueó) y **propiedad** (RAÍZ 2).

El resto de frentes —propiedad, facciones, ánimos, aforo— y qué desbloquea cada
uno viven en `PLAN.md`.

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
    memory.py       lo que recuerda: qué pasó, dónde, por culpa de quién
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
`CognitionProvider` (F2) y `RuleSystem` (F4). Se definieron antes de
necesitarlas para que el motor se construya contra ellas.

`MemoryStore` era la tercera y ya está implementada — y la firma reservada
resultó **equivocada en tres cosas**, todas anotadas en el puerto: guardaba un
`event_id` a un log que la ventana poda, una `cue: str` que obligaba a comparar
texto, y devolvía `list[int]` en vez de recuerdos. Reservar una costura ayuda;
adivinar su forma antes de tener el caso de uso, no.

## Garantías

Verificadas por la batería de tests, no por convención:

- Misma semilla → mismo log byte a byte, **también entre procesos distintos**
  (comprobado con `PYTHONHASHSEED` variable).
- El orden de consumo del RNG no afecta al resultado: cada sorteo sale de
  `blake2b(semilla, agente, tick)`. Es lo que hace que reanudar una partida sea
  exacto.
- Todo valor de necesidad queda en `[0, 1]` —o bajo el techo de esa persona, si
  su pack declara uno— y la deuda guarda aparte lo que el suelo recortaría.
- Nadie se queda sin opciones válidas.
- Un techo aguanta el tiempo. Cien mil intentos de crecer no pasan de él: quién
  llega adónde es cuestión de quién eres, no de cuánto se corra el mundo.
- Un agente que llega a su techo deja de sentir apremio por ese eje. La urgencia
  se mide contra el techo propio, no contra el 1.0 de nadie; sin eso, un techo
  sería una trampa que condena a entrenar de por vida lo que ya no mejora.
- El daño que reparte una situación se archiva como **pasivo**, nunca como algo
  que el agente hizo. Lo que te pasa no te enseña a desconfiar de tus decisiones.
- El salto temporal no apaga los disparadores. Se evalúan por tramo y no una vez
  cada N días: el salto aproxima —enciende como mucho una vez por zancada— pero
  el mundo no se queda en calma por correrlo rápido.
- El salto temporal **sí borra el reloj de la agonía**, y es la única marca de
  tiempo que no cobra la zancada. Cuenta ticks *seguidos*, y a través de trece
  días sin simular «seguidos» es falso. Consecuencia declarada: **bajo `--skip`
  no se muere nadie de hambre.** Lo que no se simula, no se inventa.
- Un rumor no se refuerza por oírlo dos veces, ni degrada lo que uno vivió. Sin
  esa guarda, un corrillo de ocho fabricaría certezas en vez de propagarlas.
- Lo que otro te hace se archiva como **pasivo**, igual que una ventisca: no lo
  decidiste tú, así que no puede ensuciar tus creencias sobre lo que rinde cada
  acción.
- Nadie cura ni agrede a distancia: se comprueba que el destinatario **siga
  delante** al terminar, no que siga existiendo.
- Cero vocabulario de ambientación en el motor.
- Un pack no carga si tiene referencias rotas, acciones que nadie puede
  ejecutar, precondiciones más bajas de lo que la acción consume, efectos
  negativos sin coste declarado, un grafo que no es fuertemente conexo, una
  situación que no hace nada, un disparador activo sin cooldown o que se exige a
  sí mismo, una acción elástica que también fija en sus efectos el mismo eje que
  la estira, una condición personal que declara lugar o calendario, una acción
  que cura algo que nadie puede llevar encima, una acción que apunta a alguien y
  no le hace nada o no exige compañía, dos parejas para la misma persona,
  inversas que no se corresponden, o un alivio pasivo que supera al decaimiento.
- Cada pack declara su propio contrato de salud y se comprueba en cada corrida
  de tests.

## Packs

| Pack | Lugares | Acciones | Agentes | Para qué |
|---|---|---|---|---|
| `ciudad` | 25 | 32 | 127 | el mundo de trabajo |
| `confluencia` | 53 | 23 | 200 | el mundo grande, mapa escrito a mano |
| `aldea` | 13 | 17 | 10 | mundo pequeño, contrato sobre tres semillas |
| `barrio` | 21 | 13 | 10 | el mundo contemporáneo original |
| `dark_fantasy` | 5 | 5 | 2 | prueba de agnosticismo, no se juega |

**`ciudad`** — fantasía con academia de magia y una sima debajo. Dos poblaciones
con vidas distintas en el mismo mapa: los alumnos viven dentro de la academia,
los cazadores bajan a la sima, y la ciudad vive del gasto de ambos. Cuatro
situaciones (invierno, feria, ventisca, oleada), cuatro clases de relación, y
una carrera de cinco años que se recorre con el salto temporal.

**`confluencia`** — el banco de pruebas de escala. Cinco razas con afinidad
mágica, cuatro elementos, cinco oficios exclusivos por clase, sobre un mapa de
53 lugares escrito a mano en vez de generado. Cada barrio es autosuficiente y el
centro paga algo mejor, para poder mirar quién migra y quién se queda: la
correlación entre mudarse y estar mejor pagado salió **+0.67**, y los que se
quedan lo hacen por gustos, no por incapacidad.

**`dark_fantasy`** — deliberadamente sin calibrar: se degradó mientras el motor
evolucionaba y solo se le exigen los invariantes universales. Está escrito en el
propio pack para que sea una decisión y no un olvido.

## Calibrar

`--health` mide el mundo y contrasta lo que el pack promete. Cada pack declara
su contrato y se comprueba en cada corrida de tests, así que un cambio de motor
que aplane un mundo se ve el mismo día.

```
  tiempo en crisis         14.9%      diferenciación           0.867
  abandonos/completadas    10.8%      difer. geográfica        0.825
  tiempo en tránsito       18.6%      bloqueos                     0
  lugares desiertos       ['nucleo_sima']
  tiempo con imprevisto     0.0%
  nunca pasan             ['oleada', 'ventisca']
```

- **Diferenciación** — cuánto se distinguen dos biografías cualesquiera. Es la
  medida madre: si baja, el mundo tiene mucha gente viviendo la misma vida.
- **Diferenciación geográfica** — lo mismo sobre *dónde* pasan el tiempo. Separa
  dos fracasos que el número global confunde: gente que hace cosas distintas en
  el mismo sitio, y gente que hace lo mismo repartida por el mapa.
- **Lugares desiertos** y **acciones sin usar** — lo que el pack escribió y
  nadie visita. Contenido muerto, dicho con nombre y apellidos.
- **Tiempo con imprevisto** y **nunca pasan** — qué fracción de la vida
  transcurre bajo alguna situación, y cuáles no llegaron a ocurrir jamás. Arriba
  se ve el instrumento delatando trabajo pendiente en el propio `ciudad`:
  ventisca y oleada están escritas y no disparan en 21 días.
- **`--divergence N`** — el eje vivo/aleatorio. Corre la misma persona con N
  semillas y compara cuánto cambia su vida por azar frente a cuánto la separa de
  sus vecinos. Un mundo demasiado ordenado es aburrido; uno donde el azar pesa
  más que el carácter no permite explicar ninguna conducta.

Además, **oferta y demanda por eje**:

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
uv run pytest          # 781 tests
uv run mypy src tests  # estricto
uv run ruff check
```

Las decisiones de diseño y su porqué viven en los docstrings y en los mensajes
de commit — incluidas las que salieron mal y por qué. Un docstring de este
proyecto explica *por qué* algo es así y qué se rompió al hacerlo de otro modo;
si solo repite lo que hace la función, sobra.
