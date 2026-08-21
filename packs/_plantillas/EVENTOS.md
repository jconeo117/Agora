# Plantilla de eventos y condiciones — lo que le pasa a uno sin decidirlo

Dos primitivas, y son **la misma clase con un `bool` de diferencia**:

```
SITUACIÓN    un estado del mundo con nombre, pegado a LUGARES
CONDICIÓN    la misma clase con `personal: True`, pegada a una PERSONA
```

Una tormenta alcanza a quien esté en la plaza. Una herida **te sigue a casa**.

---

# 1 · La plantilla

```python
def E(**k):
    return k

E(id="mi_evento", label="cómo se lee en pantalla",

  # DÓNDE. Vacío o ausente = en todo el mundo
  places=["plaza_mayor", "mercado"],

  # O A QUIÉN: personal la convierte en condición. Sin `places`
  personal=False,

  # --- CUÁNDO. Elige UNA forma, no se mezclan -------------------------------
  #
  # (a) PERIÓDICA — por calendario, no hace falta encenderla
  every=34560, lasts=192, starts_at=9600,
  #
  # (b) EVENTUAL — cuando al mundo le da por ahí
  trigger={"expected_per_year": 3.0,
           "lasts_min": 200, "lasts_max": 800,
           "cooldown": 2880,
           "requires_situations": ["invierno"]},

  # --- QUÉ HACE. Al menos uno, o el pack NO CARGA ---------------------------
  gain_multipliers={"dinero": 1.4, "sustento": 0.5},   # lo que RINDE
  effects={"salud": -0.003},                            # daño directo por tick
  inflicts={"situation": "herida", "marca": "quemadura",
            "chance": 0.02, "gravedad_min": 1.0, "gravedad_max": 3.0},
)
```

Y el cuarto y quinto canal **no van aquí**:

```
situation_multipliers   va en la ACCIÓN   cuánto APETECE hacer algo durante
closed_during           va en el LUGAR    lo cierra del todo
```

---

# 2 · Cada campo, explicado

## `places` — a quién alcanza

**Vacío o ausente = a todo el mundo, esté donde esté.** Un invierno es así; un
incendio no.

## `personal` — la condición

```python
E(id="herida", label="herida", personal=True, effects={"salud": -0.0022})
E(id="fiebre", label="fiebre", personal=True,
  effects={"salud": -0.0009, "descanso": -0.0012})
```

Una condición **no puede declarar `places`** —vive pegada a quien la lleva— y
tampoco aparece nunca en las situaciones del mundo.

> **Y es la única forma que hay de que exista la muerte.** `lethal_after` por sí
> solo es decoración: ningún mundo calibrado para ser habitable deja un eje
> vacío el tiempo suficiente. Un `costs` se paga una vez y ahí acaba; **una
> condición sigue drenando hagas lo que hagas**, y por eso hay que ir a que te
> la quiten.

## Las periódicas: `every` / `lasts` / `starts_at`

```
every       cada cuánto vuelve, en ticks
lasts       cuánto dura
starts_at   el desfase, para que no caigan todas encima
```

```
1/año  = every 34560      6/año  = every 5760      52/año = every 665
2/año  = every 17280     12/año  = every 2880
4/año  = every  8640     24/año  = every 1440
```

> ⚠️ **Una periódica no puede durar tanto como su ciclo**, o el lugar sería
> inalcanzable para siempre.

**No guardan estado**: se calculan del reloj, igual que una franja del día.

## Las eventuales: `trigger`

```python
trigger={"expected_per_year": 1.5,     # la tasa, como si estuviera siempre
         "lasts_min": 192,             # cuánto dura, sorteado entre las dos
         "lasts_max": 768,
         "cooldown": 4320,             # OBLIGATORIO si es activa
         "requires_situations": ["invierno"]}
```

| campo | ojo con |
|---|---|
| `expected_per_year` | es la tasa **como si estuviera siempre habilitada**. Con `requires_situations` sale bastante más raro que el número escrito |
| `cooldown` | **sin él, lo que acaba de terminar se reenciende al tick siguiente** |
| `lasts_min/max` | la banda es lo que hace que dos incendios no sean el mismo |

Escalas útiles:

```
6.0/año    tormentas: pasa y no es noticia
1.5/año    incursiones: se recuerdan
0.5/año    tragedias: marcan un año
0.05/año   cataclismos: una vez por generación
0.02/año   míticos: quien lo viva lo contará el resto de su vida
```

> **El sorteo va por clave** `(situación, tick)`, no por un generador
> consumido en secuencia: dos procesos con la misma semilla encienden
> exactamente lo mismo.

## `gain_multipliers` — lo que rinde mientras dure

```python
gain_multipliers={"dinero": 0.3, "vinculo": 1.5}
```

> Una huelga: se gana mucho menos, y **la gente se junta más**.

**Es el canal más barato y el que más conducta produce**, porque no prohíbe
nada: cambia lo que compensa, y cada cual decide.

## `effects` — daño directo, CADA TICK

```python
effects={"salud": -0.006}   # -0.576 al día si te quedas dentro
```

⚠️ **Por tick.** Un número que parece pequeño es enorme si alguien se queda ocho
horas.

**Se recupera cuando la situación acaba.** La diferencia entre un mal rato y una
consecuencia está en `inflicts`.

## `inflicts` — lo que sobrevive a que el evento termine

```python
inflicts={"situation": "fiebre", "chance": 0.004,
          "gravedad_min": 0.4, "gravedad_max": 2.6}
```

> ⚠️ **`chance` es POR TICK, no por evento.** Los efectos se aplican cada tick,
> así que 1.0 en una ventisca heriría **96 veces al día**. El número bajo no es
> azar decorativo: es **cuánto aguantas dentro**, y sale gratis que el riesgo
> crezca con la exposición.

```
0.02   -> algo cada ~50 ticks    (media hora larga)
0.005  -> cada ~200 ticks        (dos horas)
0.004  -> un brote lento
```

**La banda de gravedad es lo que hace que un brote reparta enfermedades
distintas.** Con un valor fijo, doscientas personas tendrían exactamente la misma
fiebre, y la única variación posible sería cuántas veces les tocó.

⚠️ **Y por eso la gravedad que acabas llevando encima puede pasar del máximo
declarado**: dos ticks son dos tiradas, y dos tiradas en la misma marca **suman**.
El rango acota *una infligida*, no *lo que acabas llevando*.

## `marca` — el discriminador opaco

```
Dos condiciones con la MISMA marca  ->  AGRAVAN (suman gravedad)
Con marcas distintas                ->  SE APILAN (drenan por separado)
```

> Brazo, pierna y torso drenan por separado. **Dos tajos en el mismo torso no
> duran más, duelen más.** El motor compara cadenas y nunca las interpreta.

Y al agravarse, **el sitio se queda con el de la primera**: lo que enseña a
temer un lugar es lo que empezó, no lo que remató.

---

# 3 · Ejemplo: un brote, y por qué esos números

```python
E(id="brote_enfermedad", label="Brote de enfermedad",
  places=["enfermeria", "plaza_mayor", "mercado_central", "posada_central"],
  trigger={"expected_per_year": 0.1, "lasts_min": 960, "lasts_max": 2880,
           "cooldown": 17280},
  gain_multipliers={"sustento": 0.7},
  inflicts={"situation": "fiebre", "chance": 0.004,
            "gravedad_min": 0.4, "gravedad_max": 2.6})
```

| número | qué dice |
|---|---|
| `places` | los **sitios concurridos**, no los apartados. Una epidemia vive donde se junta la gente |
| `0.1/año` | una vez cada diez años. Cuando pasa, se recuerda |
| `lasts 960-2880` | de diez días a un mes. **La banda es la diferencia entre un susto y una plaga** |
| `cooldown 17280` | medio año de gracia después |
| `sustento: 0.7` | comer rinde peor: la comida escasea. No hace falta simular el mercado |
| `chance: 0.004` | ~un contagio cada dos horas dentro. Quien pasa por el mercado y se va, casi nunca |
| `0.4 - 2.6` | **a uno le toca pasarla en cama dos días y a otro casi lo mata** |

Y la condición que reparte:

```python
E(id="fiebre", label="fiebre", personal=True,
  effects={"salud": -0.0009, "descanso": -0.0012})
```

> Más lenta que una herida y **no se para sola**: no declara `lasts`. Da miedo
> por eso, no por el número — **hay que ir a que te la quiten.**

---

# 4 · El cataclismo: cuando quieres que muera gente

**Un cataclismo no es una tragedia grande.** Es la única clase de evento escrita
para matar.

```python
E(id="ruptura_del_sello", label="Ruptura del Sello Profundo",
  places=[...todas las mazmorras...],
  trigger={"expected_per_year": 0.05, "lasts_min": 480, "lasts_max": 1440,
           "cooldown": 34560},
  gain_multipliers={"dinero": 3.0, "dominio": 3.0},
  effects={"salud": -0.010},
  inflicts={"situation": "herida", "marca": "desgarro", "chance": 0.09,
            "gravedad_min": 3.0, "gravedad_max": 9.0})
```

**La regla que lo hace funcionar: la recompensa sube CON el peligro.**

> Un cataclismo que solo hace daño **vacía el sitio**, y un sitio vacío no mata a
> nadie: sería un evento letal con cero muertes. Subiendo las dos cosas sigue
> siendo una decisión — el temerario baja, el prudente espera, y el motor no
> tiene que saber cuál es cuál.

Y el umbral que hay que cruzar es **el de lo curable**:

```
                       chance   gravedad   daño esperado/tick
la bestia despierta      0.015    1.0            0.015
la ruptura del sello     0.09     3.0-9.0        0.540      36x
```

> Una herida de gravedad 9 drena 0.0198 de salud por tick —de lleno a vacío en
> medio día— y `vendarse` quita 1.2, así que hacen falta **ocho vendajes
> seguidos mientras sigue sangrando**. Ahí es donde `lethal_after` por fin cobra.

Medido: 4 muertes contra 1 del control en seis meses.

---

# 5 · Las seis reglas que el pack vigila

**1 · Tiene que hacer algo.** Al menos un canal, o no carga. Una situación que no
hace nada **se lee como contenido vivo** y no lo es.

**2 · Solo se puede infligir algo declarado `personal`.** Nadie lleva encima un
invierno. Y **todo lo que se inflija necesita quien lo cure**, o es una sentencia
de muerte: una acción con `cures`, o un `lasts` en el `inflicts`.

**3 · Una situación no puede pegarse a sí misma.**

**4 · Una eventual activa necesita `cooldown`.**

**5 · `expected_per_year` con `requires_situations` sale más raro que el número
escrito.**

**6 · Una periódica no puede durar tanto como su ciclo.**

---

# 6 · Las trampas

**1 · `chance` por tick, no por evento.** Es el error que más veces se comete.

**2 · La gravedad acumulada puede pasar del máximo declarado.** No es un fallo:
son varias tiradas sumadas.

**3 · Una condición no aparece en las situaciones del mundo.** Vive pegada a
quien la lleva, así que no cuenta como «situación que nunca ocurrió».

**4 · Estrena todo apagado.** Un disparador nuevo con `expected_per_year: 0` no
puede mover un contrato ya medido.

**5 · El salto temporal (`--skip`) le da zancada a los disparadores** pero **no a
la agonía**: bajo `--skip` no se muere nadie de hambre.

**6 · Lo que un evento hace se aplica a quien esté DENTRO en ese tick.** Alguien
que entra y sale se lleva una fracción del daño — y eso es correcto, es
exposición.
