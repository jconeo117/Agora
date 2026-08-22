# Plantilla de psicología y personalidad

Cómo se escribe una persona en Agora. Todo lo de aquí está verificado contra
`src/agora/engine/ontology.py` — si algo no cuadra, manda el código.

**La idea de fondo:** un rasgo **no hace nada**. Reescala números que ya
existían. Dos personas con reglas idénticas y pesos distintos viven vidas
distintas sin una sola línea de código específica para ellas.

---

# 1 · Las dos piezas

Se escriben en sitios distintos y significan cosas distintas:

```
EL CATÁLOGO   qué es "sociable" en este mundo     una vez, en el pack
LA FICHA      cuán sociable es Elena              por persona, intensidad -1..1
```

```python
# CATÁLOGO — qué significa el rasgo
T("sociabilidad", "sociabilidad",
  need_weight_multipliers={"vinculo": 2.2, "descanso": 0.9},
  temperament_multipliers={"companionship_weight": 3.2})

# FICHA — cuánto lo es esta persona
{"id": "elena", "label": "Elena", "traits": {"sociabilidad": 0.7}}
```

## La regla que lo gobierna todo: la intensidad es un EXPONENTE

```
factor = multiplicador ** intensidad
```

| intensidad | con `vinculo: 2.2` | qué es |
|---|---|---|
| `1.0` | ×2.20 | sociable de libro |
| `0.7` | ×1.72 | bastante sociable |
| `0.4` | ×1.37 | tirando a sociable |
| `0.0` | ×1.00 | **el rasgo no existe** |
| `-0.5` | ×0.67 | tirando a huraño |
| `-1.0` | ×0.45 | **el opuesto exacto** |

**Por eso no hace falta escribir `insociabilidad`.** Una intensidad negativa es
el rasgo invertido, exacto. Y por eso el multiplicador tiene que ser
estrictamente mayor que 0: con 0 o negativo, `0 ** -1` revienta.

> ⚠️ **Escribir el opuesto al lado no es solo redundante: produce gente que es
> las dos cosas.** El generador sortea de la lista entera, así que puede darte
> `ambicioso` y `acomodado` a la vez — 9 de 200 en el pack anterior. Un eje, no
> un par. Ver [ERRORES](../../docs/ERRORES.md) E-006.

**Y el sorteo tiene que ir con signo**, o la mitad del catálogo no existe:

```python
signo = 1 if rng.random() < 0.5 else -1
rasgos[eje] = round(signo * rng.uniform(0.4, 1.0), 2)
```

Descarta la franja `|i| < 0.4`: por debajo de ahí el rasgo no cambia ninguna
decisión y solo ensucia la ficha con ruido que se lee como intención.

> Con interpolación lineal, un multiplicador de 2.2 e intensidad -1 daría un
> factor negativo, que no significa nada.

---

# 2 · Los siete canales

Un rasgo puede usar los siete, uno, o ninguno. La mayoría usa uno o dos.

| canal | apodo | la pregunta | forma |
|---|---|---|---|
| `need_weight_multipliers` | — | ¿cuánto le **importa**? | `{eje: factor}` |
| `gain_multipliers` | la **aptitud** | ¿cuánto le **cunde**? | `{eje: factor}` |
| `cost_multipliers` | el **temple** | ¿cuánto le **duele** gastar? | `{eje: factor}` |
| `cap_multipliers` | el **don** | ¿hasta **dónde** llega? | `{eje: factor}` |
| `memory_multipliers` | — | ¿cuánto le **dura**? | un solo número |
| `phase_shift` | el **cronotipo** | ¿cuánto va **adelantado**? | entero, en ticks |
| `temperament_multipliers` | — | ¿**cómo** decide? | `{perilla: factor}` |

## 2.1 `need_weight_multipliers` — cuánto le importa

El más usado. Reescala el peso de un eje en la deliberación.

```python
T("hedonismo", "hedonismo",
  need_weight_multipliers={"estimulo": 2.4, "dinero": 0.7})
```

> El estímulo le importa 2.4 veces más que a la media, y el dinero un 30 %
> menos. **Los dos números juntos son el rasgo**: no es solo que le guste
> divertirse, es que además le importa poco lo que cuesta.

**Escribe siempre el contrapeso.** Un rasgo que solo sube cosas produce gente
que quiere todo más que los demás, y eso no es una personalidad, es un
multiplicador global.

## 2.2 `gain_multipliers` — la aptitud

Cuánto **rinde** lo que hace. Distinto de que le importe.

```python
T("estilo_guerrero", "guerrero",
  gain_multipliers={"armas": 2.4, "temple": 1.8})
```

> Entrenando armas avanza 2.4 veces más deprisa. **No dice que le gusten las
> armas** — puede odiarlas y seguir teniendo mano.

```
need_weight_multipliers  ->  cuánto le IMPORTA
gain_multipliers         ->  cuánto le CUNDE
```

Quien le da mucha importancia al descanso y lo recupera despacio existe. Quien
tiene mano para el arcano y le trae sin cuidado, también. **Sin los dos canales,
«se le da bien la magia» solo puede significar «le gusta más», que es la mitad
de la idea.**

Multiplica cualquier efecto **positivo**: lo que gana una acción terminada y el
ritmo de las elásticas (dormir). Sigue siendo un **ritmo, no un tope** — *«duermo
poco y me basta»* es recuperarse deprisa, no tener un límite bajo.

## 2.3 `cost_multipliers` — el temple

Espejo exacto de la aptitud, sobre el otro lado del intercambio.

```python
T("afin_fuego", "afinidad de fuego", cost_multipliers={"mana": 0.55})
```

> Cada conjuro de fuego le drena un 45 % menos. **Eso es una reserva de maná**,
> escrita sin inventar una primitiva de reserva.

Multiplica cualquier efecto **negativo**: lo que cuesta una acción y lo que te
hace una situación. **No toca los peajes** —un porte vale lo que vale, no menos
por ser tú— ni el decaimiento, que es el reloj del cuerpo.

Con `0.5` a intensidad plena el coste es la mitad; a intensidad 0.4 es 0.76.
**Una afinidad de nacimiento y una aprendida son el mismo rasgo a distinta
intensidad**, sin mecanismo nuevo.

## 2.4 `cap_multipliers` — el don

Hasta dónde puede llegar. Multiplica el `cap` de la necesidad, recortado a 1.0.

```python
# con la necesidad declarando cap: 0.35 y el rasgo 2.8
de nacimiento (intensidad 1.00)  ->  0.35 * 2.8       = 0.98
aprendida     (intensidad 0.35)  ->  0.35 * 2.8**0.35 = 0.50
```

**Sube un techo bajo; no baja uno alto.** La necesidad declara lo que alcanza
cualquiera con empeño, y el rasgo dice quién lo pasa. Al revés —techo alto que
los rasgos bajan— habría que enumerar en cada persona todo lo que NO se le da
bien, que es infinito.

> **Ojo con los ejes de rango.** En un eje con `rank_slowdown`, el `cap` deja de
> ser *hasta dónde llegas* y pasa a ser *cuánto te cuesta romper el listón*.
> **Un `cap` bajo pasa a ser un don, no una limitación.**

## 2.5 `memory_multipliers` — cuánto le dura

**Un solo número, no un diccionario.** Olvidar despacio no es una propiedad de
*qué* recuerdas: es tuya.

```python
T("tenaz", "tenaz", memory_multipliers=4.0)   # recuerda 4x más tiempo
T("volatil", "volátil", memory_multipliers=0.4)
```

**Dirección contraintuitiva: más grande = recuerda MÁS tiempo.** No escala el
desdibujado, escala la **media vida** — la aritmética es `fade ** (1/m)`, un
exponente, porque un fade multiplicado se sale de rango (`0.99 × 4 = 3.96`, que
no es «recuerda cuatro veces más» sino un número imposible).

Este canal existe por una carencia medida: `memory_fade` es un solo número del
pack, así que sin él **los 127 habitantes olvidaban al mismo ritmo exacto**, y
dos duelos solo podían diferenciarse en cuánto pesaban el primer día — jamás en
cuánto duraban.

## 2.6 `phase_shift` — el cronotipo

**Aditivo, no multiplicativo.** Un entero en ticks.

```
franja_subjetiva = franja_de(tick + phase_shift * intensidad)
```

```python
T("nocturnidad", "nocturnidad", phase_shift=40)    # +10 h  (96 ticks = 1 día)
T("madrugador", "madrugador", phase_shift=-18)     # -4.5 h
```

**Un cronotipo no es una preferencia, es un desfase.** Para un ave nocturna la
noche no «vale más»: la noche **es** su mañana. Rotando la franja percibida,
todo lo demás cae solo — trabaja, come y socializa en su mañana subjetiva, y
duerme en su noche subjetiva, que es tu tarde.

> **Por qué no es un multiplicador, y costó una medición:** con `dormir`
> favorecido de noche y un rasgo nocturno que multiplica lo nocturno, el búho
> dormiría MÁS de noche — justo al revés.

**Lo que NO se desplaza son los horarios de los lugares.** La herrería cierra a
la misma hora para todo el mundo: el horario del mundo es objetivo y el reloj
del cuerpo es subjetivo.

## 2.7 `temperament_multipliers` — cómo decide

En vez de QUÉ le importa, cambia CÓMO decide. **Conjunto cerrado de cinco
perillas** — esto no lo define la ambientación, lo define el motor.

| perilla | alto | bajo |
|---|---|---|
| `temperature` | errático | metódico |
| `loss_aversion` | calculador | vive el momento |
| `critical_need_threshold` | se alarma pronto | aguanta |
| `travel_discount` | se mueve | arraigado |
| `companionship_weight` | busca el bullicio | le da igual |

```python
T("impulsividad", "impulsividad",
  need_weight_multipliers={"nucleo": 0.60},
  temperament_multipliers={"temperature": 3.0, "loss_aversion": 0.55})
```

> Decide con el triple de azar y le pesa el precio casi la mitad. **No es que
> quiera cosas distintas: es que las persigue de otra manera.**

El pack fija el valor del mundo y el agente lo modula. **Un mundo donde viajar
es peligroso y una persona que odia salir de casa son dos cosas distintas que se
componen, no que se sustituyen.**

> **Una perilla, un eje dueño.** Dos rasgos que toquen `loss_aversion` se
> multiplican sobre ella y ya no se puede leer qué hizo cuál. Reparte:
>
> ```
> temperature              -> impulsividad
> loss_aversion            -> cálculo
> critical_need_threshold  -> audacia
> travel_discount          -> arraigo
> companionship_weight     -> sociabilidad
> ```
>
> Cuando alguien decida raro, sabes exactamente qué rasgo mirar.

**Y son solo cinco.** Pasado el catálogo por la lista OCEAN, faltan las que
harían falta para **Apertura** (`novelty_weight`) y **Responsabilidad**
(`switch_cost`) — son perillas del mundo, no de la persona — y las dos del
apego (`bond_rate`, `bond_fade`). Extraversión sí se escribe entera.

---

# 3 · La plantilla, entera

```python
def T(id, label, **k):
    return {"id": id, "label": label, **k}

T("mi_rasgo", "cómo se lee en pantalla",

  # ¿QUÉ le importa?      factor > 0, siempre
  need_weight_multipliers={"eje_que_sube": 2.0, "eje_que_baja": 0.7},

  # ¿Qué se le DA BIEN?   escala lo que gana
  gain_multipliers={"eje": 1.8},

  # ¿Qué le CUESTA POCO?  escala lo que gasta
  cost_multipliers={"eje": 0.55},

  # ¿Hasta DÓNDE llega?   escala el techo del eje
  cap_multipliers={"eje": 2.8},

  # ¿Cuánto le DURA?      un número suelto. >1 recuerda más
  memory_multipliers=1.0,

  # ¿Va ADELANTADO?       entero en ticks. 96 = un día
  phase_shift=0,

  # ¿CÓMO decide?         solo las cinco perillas del motor
  temperament_multipliers={"temperature": 1.0, "loss_aversion": 1.0,
                           "critical_need_threshold": 1.0,
                           "travel_discount": 1.0,
                           "companionship_weight": 1.0},
)
```

Ninguno es obligatorio. **Un rasgo sin ningún canal es legal y no hace nada** —
sirve como llave.

## 3.1 · El rasgo como llave: `requires_traits`

Va en la ACCIÓN, no en el rasgo. Es una **puerta dura**: se comprueba antes de
puntuar nada, y pide una intensidad mínima.

```python
T("elem_fuego", "afinidad de fuego")          # cero canales, cero efectos

A(id="canalizar_llama", label="canalizar la llama",
  requires_affordance="palestra",
  requires_traits={"elem_fuego": 0.5})        # solo si la tiene a 0.5 o más
```

> `elem_fuego` no tiene un solo multiplicador. **Su único trabajo es abrir
> puertas** — y por eso una afinidad aprendida a 0.35 te deja fuera de lo que
> una de nacimiento a 1.0 te abre, sin escribir la regla en ningún sitio.

Es lo que separa *«esta persona es distinta»* de *«esta persona puede hacer
cosas que otras no»*, y las dos hacen falta.

---

# 4 · Ejemplo completo, número a número

```python
T("el_veterano", "veterano de la sima",
  need_weight_multipliers={"vinculo": 0.6, "dominio": 1.4},
  gain_multipliers={"descanso": 1.9, "armas": 1.6},
  cost_multipliers={"salud": 0.7},
  memory_multipliers=2.2,
  temperament_multipliers={"critical_need_threshold": 0.55,
                           "companionship_weight": 0.7})
```

| número | qué dice de él |
|---|---|
| `vinculo: 0.6` | la compañía le importa un 40 % menos. No es un misántropo: es alguien que ya no necesita que le acompañen |
| `dominio: 1.4` | pero mejorar sí le importa, un 40 % más que a la media |
| `descanso: 1.9` | **duerme fuera igual de bien**. Compensa el mal ritmo de una acampada: él repone casi como en una cama, un novato no |
| `armas: 1.6` | entrenando armas avanza un 60 % más deprisa |
| `salud: 0.7` | **encaja los golpes.** Todo lo que le quite salud le quita un 30 % menos. Esto es lo que D-111 pide para los rangos |
| `memory_multipliers: 2.2` | lo que le pasa se le queda **más del doble** de tiempo. Sus rencores y sus miedos duran |
| `critical_need_threshold: 0.55` | **cunde el pánico casi la mitad de tarde.** Sigue bajando con la salud a la mitad, donde otro ya habría salido corriendo |
| `companionship_weight: 0.7` | una taberna llena le atrae un 30 % menos |

Y en la ficha, la misma persona a tres intensidades:

```python
{"traits": {"el_veterano": 1.00}}   # el que lleva veinte años bajando
{"traits": {"el_veterano": 0.45}}   # el que empieza a curtirse
{"traits": {"el_veterano": -0.6}}   # el bisoño: duerme mal fuera, se asusta
                                    # pronto, busca compañía, olvida rápido
```

**Ese `-0.6` no está escrito en ningún sitio.** Sale de invertir el rasgo, y por
eso un catálogo de 20 rasgos describe muchas más de 20 clases de persona.

---

# 5 · Cómo se combinan en una ficha

Dos maneras probadas, y hacen mundos distintos:

## Arquetipos compuestos (ciudad)

Se sortean **DOS arquetipos de quince** y se promedian donde chocan, más un
ruido de ±0.12.

```python
ARQUETIPOS = {
    "aplicado":  dict(laboriosidad=0.8, impulsividad=-0.5,
                      sociabilidad=-0.3, aguante=0.7),
    "vividor":   dict(hedonismo=0.8, frugalidad=-0.5, impulsividad=0.7,
                      aguante=-0.3, sociabilidad=0.5),
    ...
}
```

> Uno solo daría cien personas de quince tipos. Dos dan **105 combinaciones**, y
> *«aplicado + vividor»* sale un término medio que **también es una persona**:
> impulsividad `(-0.5 + 0.7) / 2 = 0.1`, alguien que quiere aplicarse y no
> siempre puede.

## Sesgos por origen (confluencia)

Se sortea con pesos por raza — **nunca un candado, solo una inclinación**.

```python
SESGO = {
    "enano": {"tierra": 5, "fuego": 3, "agua": 1, "viento": 1},
    "elfo":  {"viento": 6, "agua": 2, "tierra": 1, "fuego": 1},
}
```

> Un enano *tiende* a tierra, pero puede salir de viento. **El enano de viento
> existe y es raro**, que es exactamente lo que quieres — un candado lo haría
> imposible y una tirada plana lo haría corriente.

Y encima, uno o dos rasgos de carácter a intensidad sorteada:

```python
for rasgo in rng.sample(sorted(caracter), k=rng.choice([1, 1, 2])):
    rasgos[rasgo] = round(rng.uniform(0.4, 1.0), 2)
```

> **Lo que impide que dos enanos guerreros de fuego sean la misma persona.**

---

# 6 · Las trampas

**1 · Un rasgo que solo sube cosas no es una personalidad.** Escribe el
contrapeso. `hedonismo` sube `estimulo` 2.4 **y baja** `dinero` a 0.7.

**2 · Confundir «le importa» con «se le da bien».** Son `need_weight` y `gain`,
dos canales distintos, y la mitad de las personas interesantes viven en el
desacuerdo entre los dos.

**3 · El multiplicador nunca puede ser 0 ni negativo.** Se eleva a una potencia.
Para «no le importa nada» usa `0.05`, no `0`.

**4 · Un rasgo sin ficha que lo lleve es contenido muerto.** El pack lo carga y
el panel lo delata. Si escribes `reservado`, alguien tiene que serlo.

**5 · La intensidad negativa ya existe.** No escribas el rasgo opuesto: es el
mismo a `-1.0`, exacto.

**6 · Los rasgos NO interactúan entre sí.** Cada uno actúa por su cuenta y se
componen multiplicando. No hay forma de escribir *«audaz, pero solo si está
solo»*.

**7 · Estrena todo a 0.** Un rasgo nuevo con perilla a 0 no puede mover un
contrato ya medido. Súbelo después de tener la línea base.

---

# 7 · Lo que hoy NO se puede escribir

Por si lo intentas y no sale:

| No hay | Consecuencia |
|---|---|
| **Estados de ánimo** | `strain` es UN número. Enfadado y abatido son el mismo valor bajo |
| **Rasgos que interactúan** | cada uno por su cuenta, se componen multiplicando |
| **Edad** | nadie envejece: no hay rasgos por edad ni veteranía que llegue sola |
| **Rencor hacia una PERSONA** | `culpable` apunta a una situación, nunca a alguien. Sin esto no hay venganza ni perdón |
| **Rasgos que cambian solos** | los rasgos son fijos. Lo que cambia con la vida son las metas (`on_success`/`on_failure`) y el desgaste |

Ese último tiene una salida parcial y conviene conocerla: **una meta cumplida o
fallada sí retoca rasgos.**

```python
"goals": [{
    "id": "graduarse", "label": "graduarse con honores",
    "need": "curso", "at_least": 0.95, "deadline": 207360,
    "on_success": {"graduado": 1.0, "ambicion": 0.3},
    "on_failure": {"laboriosidad": 0.5, "hedonismo": -0.3},
}]
```

> Lo consigue y se vuelve más ambicioso. Lo falla y se entierra en el trabajo
> renunciando al placer. **Es la única forma que hay hoy de que a alguien le
> cambie el carácter**, y es de las cosas más baratas de escribir.
