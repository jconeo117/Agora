# Plantilla de acciones — el repertorio de conducta

Una acción es **todo lo que una persona puede hacer**. Es el único sitio donde
una decisión se convierte en algo que pasa.

**La trampa que más veces ha mordido, antes de nada:**

```
satisfies   lo que el agente CREE que atiende  ->  la deliberación LEE esto
effects     el delta real                      ->  NADIE lo mira al decidir
```

Dos acciones que anuncian lo mismo son **indistinguibles al decidir aunque una
pague el triple**. `expoliar` prometía `dinero: 1.0` igual que `trabajar`,
pagaba 0.40 contra 0.16, y llevaba **cero usos desde que se escribió el pack**.

---

# 1 · La plantilla

```python
def A(**k):
    return k

A(id="mi_accion", label="cómo se lee en pantalla",

  # --- CUÁNTO DURA ----------------------------------------------------------
  duration_ticks=8,        # obligatorio. 96 ticks = 1 día
  interruptible=True,      # False: una vez empezada, no se suelta
  elastic={"need": "descanso", "per_tick": 0.033, "min_ticks": 4},

  # --- LAS PUERTAS DURAS. Se comprueban ANTES de puntuar nada ---------------
  requires_affordance="cama",          # el lugar tiene que ofrecerlo
  requires={"dinero": 0.12},           # hay que TENER esto para empezar
  requires_traits={"elem_fuego": 0.5}, # hay que ser quien hay que ser
  requires_rank={"dominio": 3},        # hay que haber llegado
  requires_company=2,                  # hace falta gente delante
  requires_relation="pareja",          # y que sea de los tuyos

  # --- LO QUE PROMETE, que es lo que se lee al decidir ----------------------
  satisfies={"descanso": 0.95},        # 0..1. LA DELIBERACIÓN LEE ESTO

  # --- LO QUE CUESTA --------------------------------------------------------
  costs={"dinero": 0.25},              # se paga al terminar

  # --- LO QUE PASA DE VERDAD ------------------------------------------------
  effects={"descanso": 0.30, "dinero": -0.07},
  effects_per_company={"vinculo": 0.16},   # por cada persona presente

  # --- CUÁNDO APETECE MÁS ---------------------------------------------------
  phase_multipliers={"noche": 1.5, "manana": 0.7},
  situation_multipliers={"festival": 2.0},
  saturation_gain=0.08,                # cuánto cansa repetirla

  # --- LO QUE LE HACE A OTRO ------------------------------------------------
  target={"gives": {"salud": 0.50}, "cures": {"herida": 1.6},
          "requires_condition": "herida",
          "min_regard": 0.0, "regard_weight": 0.4},

  # --- LO QUE TE DEJA ENCIMA ------------------------------------------------
  inflicts={"situation": "herida", "marca": "torso", "chance": 0.02,
            "gravedad_min": 1.0, "gravedad_max": 3.0, "lasts": 0},
  cures={"herida": 1.2},               # cuánta GRAVEDAD le quita a lo tuyo

  tags=["trabajo"],
)
```

Solo `id`, `label` y `duration_ticks` son obligatorios.

---

# 2 · Cada número, explicado

## `duration_ticks` — y el aviso que ahorra una sesión

```
1 tick = 15 min · 4 = 1 h · 8 = 2 h · 40 = 10 h · 96 = 1 día
```

> ⚠️ **Una acción de duración N termina en el tick N+1.** Empieza en el tick de
> la decisión y ocupa N ticks; el efecto cae al siguiente. Si mides «a los 2
> ticks no ha pasado nada», no es un fallo.

## `elastic` — lo que dura lo que haga falta

El modelo por defecto trata dormir como **una transacción**, y dormir es **una
acumulación**.

```python
elastic={"need": "descanso", "per_tick": 0.033, "min_ticks": 4}
```

```
ticks  = acotado(déficit / ritmo)
efecto = ritmo * ticks
```

> Ya es **por persona sin declarar nada por persona**: quien llega a 0.9 duerme
> una hora y quien llega a 0.1 duerme ocho. Y `gain_multipliers` lo modula, así
> que las quince horas del guerrero salen solas.

`min_ticks` es el suelo: nadie se acuesta para quince minutos.

## `interruptible` — lo que no se suelta

`False` significa que ni siquiera una necesidad crítica la corta. Úsalo poco:
es la diferencia entre *bajar a la mazmorra* (no puedes irte a mitad) y *charlar*.

## Las seis puertas duras

**No son descuentos: son binarias, y se comprueban antes de puntuar.** La
herrería cerrada de noche no es menos atractiva, es que **no está**.

| puerta | qué pide |
|---|---|
| `requires_affordance` | que el lugar ofrezca esa cosa (`cama`, `fogon`, `yunque`) |
| `requires` | tener ese eje **al menos** a ese valor, ahora |
| `requires_traits` | ser quien hay que ser, a esa intensidad mínima |
| `requires_rank` | haber roto ese rango |
| `requires_company` | cuenta **cabezas**, no aprecio — una fiesta necesita cuerpos |
| `requires_relation` | que haya delante alguien que sea eso tuyo |

> ⚠️ **`requires_rank` solo debe gatear lo que el rango ABRE, nunca lo que lo
> DA.** Poner un rango a lo que enseña cierra el mundo entero los primeros días:
> medido, la crisis pasó del 8.0 % al 0.3 % y los 200 se fueron al turno seguro.

## `satisfies` — la promesa, y está acotada a 0..1

**Es lo único que la deliberación lee.** Dice *qué necesidad cree el agente que
esto atiende, y en qué medida*.

```python
satisfies={"sustento": 0.70, "vinculo": 0.20}
```

> Cenar fuera **anuncia** que llena el sustento casi del todo y de paso algo de
> compañía.

**No se arregla una acción muerta subiendo este número** — está acotado a 1.0.
Hay que anunciar algo que la rival **no pueda dar**. A `expoliar` se le puso
`dominio`: fregar platos no te hace mejor mago.

## `costs` vs `effects` negativo

```
costs      lo que se paga por hacerlo, y se PONDERA POR AVERSIÓN
effects    el delta real que queda cuando termina
```

En la práctica se escriben los dos y `effects` lleva el signo:

```python
requires={"dinero": 0.12},   # hay que tener 0.12 para sentarse
costs={"dinero": 0.25},      # pesa 0.25 en el precio al deliberar
effects={"dinero": -0.07},   # y de verdad se va 0.07
```

## `effects_per_company` — lo que cambia por haber gente

```python
effects={"vinculo": 0.015},
effects_per_company={"vinculo": 0.16},
```

> Cenar solo casi no crea vínculo. Cenar con cuatro, sí. **Es la primitiva que
> hace social a una acción** — sin ella, la compañía es decorado.

## `phase_multipliers` — a qué hora apetece

```python
phase_multipliers={"manana": 2.2, "tarde": 1.6, "noche": 0.25}
```

> **Y no es sabor: es lo que hace que un sitio arranque.** Sin horario, todos
> comían en la taberna —82 veces contra 41— porque allí había gente, y donde hay
> gente comer renta más. Un bucle que se realimenta solo y **deja el comedor
> vacío para siempre**. Concentrar la hora hace que coincidan.

Se lee contra la franja **subjetiva** del agente (ver `phase_shift` en
`PERSONALIDAD.md`), así que un nocturno vive esto rotado.

## `saturation_gain` — cuánto cansa repetirla

```
0.00   se puede hacer indefinidamente sin hartarse
0.08   normal
0.20   a la tercera vez ya no apetece
```

Se recupera al ritmo de `saturation_recovery` del mundo. **Es lo que impide que
alguien encuentre la acción óptima y la repita 96 veces al día.**

## `target` — la mitad social

**Lo que le haces a OTRA persona.** El destinatario se elige **donde estás**,
nunca a distancia.

```python
target={
    "gives": {"salud": 0.50},          # lo que recibe. Negativo = agredir
    "cures": {"herida": 1.6},          # cuánta gravedad le quitas
    "inflicts": {...},                 # o lo que le dejas encima
    "requires_condition": "herida",    # solo a quien la lleve
    "min_regard": 0.0,                 # aprecio mínimo para molestarte
    "regard_weight": 0.4,              # cuánto encoge la recompensa el desafecto
}
```

| campo | por qué |
|---|---|
| `requires_condition` | **lo ÚNICO que mira el estado del otro.** Una herida se ve; el valor de las necesidades de otro **no** — sería omnisciencia |
| `min_regard` | puerta dura por aprecio. Úsala poco |
| `regard_weight` | **encoge la recompensa, no la veta**: a un desconocido se le ayuda cuando no hay nada mejor que hacer |
| `gives` negativo | **agredir no necesita primitiva**: es dar de comer con el signo cambiado |

> El motor **no necesita saber qué es el altruismo**. Ayudar paga lo que el pack
> diga que paga, y por eso se hace. Y de aquí sale la profesión de curandero sin
> inventar nada: `target` + `requires_condition` + un `cures` grande + lo que cobra.

## `inflicts` — lo que te deja encima

**Un `costs` se paga una vez y se acabó. Una condición sigue sangrando hagas lo
que hagas, y por eso hay que ir a que te la quiten.**

```python
inflicts={"situation": "herida",     # tiene que ser `personal=True`
          "marca": "torso",          # opaca al motor. Dos iguales AGRAVAN
          "chance": 0.02,            # ojo: en situaciones es POR TICK
          "gravedad_min": 1.0,       # se sortea entre las dos
          "gravedad_max": 3.0,
          "lasts": 0}                # 0 = no se pasa sola
```

> **La banda de gravedad es lo que hace que un brote reparta fiebres distintas.**
> Con un valor fijo, doscientas personas tendrían exactamente la misma fiebre.

**Se aplica al terminar, no al empezar.** Media faena no cuenta.

## `cures` — cuánta gravedad quita

**No es un interruptor: es una cantidad.** La condición solo se va cuando su
gravedad llega a cero.

```python
A(id="dormir",   cures={"fiebre": 0.12})                    # gratis y lento
A(id="vendarse", cures={"herida": 1.2, "fiebre": 0.8})
A(id="socorrer", target={"cures": {"herida": 1.6, "fiebre": 1.2}})
```

> *«Una fiebre con reposo y cuidado se pasa»* **es ese 0.12**. Y no hay ninguna
> regla que diga que el sueño cura fiebres y no huesos: sale del número.

---

# 3 · Ejemplo completo, número a número

```python
A(id="socorrer", label="socorrer a un herido", duration_ticks=10,
  requires_affordance="altar", requires={"dinero": 0.08},
  satisfies={"vinculo": 0.55},
  costs={"dinero": 0.10, "descanso": 0.06},
  effects={"vinculo": 0.28, "dinero": 0.14, "descanso": -0.05},
  target={"gives": {"salud": 0.50}, "cures": {"herida": 1.6, "fiebre": 1.2},
          "requires_condition": "herida", "regard_weight": 0.4},
  saturation_gain=0.05)
```

| número | qué dice |
|---|---|
| `duration_ticks: 10` | dos horas y media. No es un gesto, es una tarde |
| `requires_affordance: "altar"` | **solo se puede en un templo**. Le da geografía a la compasión |
| `requires: dinero 0.08` | el ungüento hay que comprarlo antes |
| `satisfies: vinculo 0.55` | lo que el agente **cree**: que le va a acercar a la gente |
| `effects: dinero +0.14` | **y de verdad cobra más de lo que gastó.** Aquí nace la profesión |
| `target.gives: salud 0.50` | el herido recibe medio punto de salud |
| `target.cures: herida 1.6` | y **1.6 de gravedad menos**: más que vendarse uno solo |
| `requires_condition` | **solo a quien lleve una herida**. No se socorre al sano |
| `regard_weight: 0.4` | a quien no aprecias le ayudas por el 60 % de la recompensa |
| `saturation_gain: 0.05` | bajo: ser curandero **es un oficio**, no un capricho |

---

# 4 · Las trampas

**1 · `satisfies` es lo que se lee; `effects` es lo que pasa.** Si tu acción
nueva no se usa nunca, el 90 % de las veces está **dominada**: otra anuncia lo
mismo y cuesta menos.

**2 · Compara contra sus rivales, no contra el vacío.** `satisfies`, `costs`,
`duration_ticks` y **distancia**. Una acción a 6 ticks de viaje compite con una
que está aquí mismo.

**3 · Una acción sin usar es contenido muerto y el panel te lo dice.** Si es
deliberado (pide rango alto o meses de juego), decláralo en `may_go_unused`.

**4 · `chance` en una acción es por ejecución; en una situación es POR TICK.**
A 1.0, una ventisca heriría 96 veces al día.

**5 · Todo lo que inflijas necesita quien lo cure.** Sin `cures` y sin `lasts`,
es una sentencia de muerte.

**6 · Una acción dirigida necesita las cuatro cosas a la vez** —el otro delante,
con la condición, tú con los requisitos, en el sitio correcto— así que si no se
ejecuta nunca, mira cuál de las cuatro nunca coincide.
