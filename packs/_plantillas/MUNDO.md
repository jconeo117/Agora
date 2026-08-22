# Plantilla del mundo — las perillas que valen para todos

`TuningSpec` son **33 números que describen la psicología del mundo**, no de una
persona. Cada uno lo puede modular un rasgo (los cinco de temperamento) o
ninguno.

**La regla que lo ordena todo:**

> Un mundo donde viajar es peligroso y una persona que odia salir de casa son
> **dos cosas distintas que se componen**, no que se sustituyen.

---

# 1 · La plantilla, agrupada por lo que hace

```python
"tuning": {

    # === CÓMO SE DECIDE ====================================================
    "candidate_pool": 3,            # cuántas finalistas entran en el sorteo
    "temperature": 0.12,            # cuánto azar dentro de las finalistas
    "loss_aversion": 1.0,           # cuánto pesa perder frente a ganar
    "critical_need_threshold": 0.15,  # cuándo algo interrumpe lo que haces
    "travel_discount": 0.94,        # cuánto resta atractivo cada tick de viaje
    "duration_discount": 0.995,     # cuánto resta comprometer tiempo
    "switch_cost": 0.8,             # cuánto protege lo ya invertido

    # === EL HASTÍO =========================================================
    "saturation_recovery": 0.004,   # cuánto se pasa por tick
    "novelty_weight": 0.6,          # cuánto castiga estar harto

    # === LO QUE SE APRENDE =================================================
    "learning_rate": 0.10,          # cuánto corrige sus expectativas

    # === LO QUE SE VE ======================================================
    "sighting_horizon": 96,         # cuánto vale lo que vio en un sitio

    # === EL APRECIO ========================================================
    "bond_rate": 0.15,              # cuánto mueve un rato compartido
    "bond_scale": 0.04,             # cuánto premio equivale a medio aprecio
    "bond_weight": 0.5,             # cuánto vale un apreciado como compañía
    "bond_fade": 0.9997,            # cuánto se desdibuja por no verse
    "bond_horizon": 2880,           # tras cuánto sin verse se borra entero
    "company_scale": 10.0,          # qué es "mucha gente" en ESTE mundo
    "companionship_weight": 0.4,    # cuánto atrae la compañía esperada

    # === EL DESGASTE =======================================================
    "strain_multipliers": {"temperature": 2.0, "travel_discount": 0.85},

    # === LA MEMORIA ========================================================
    "memory_capacity": 200,         # 0 DESACTIVA la memoria episódica
    "memory_fade": 0.9995,          # cuánto se desdibuja por tick
    "memory_urgency_weight": 1.0,   # cuánto pesa lo que apretaba entonces
    "memory_surprise_weight": 1.0,  # cuánto pesa que se saliera de lo esperado
    "memory_witness_weight": 0.5,   # cuánto pesa que hubiera alguien delante
    "memory_scale": 1.0,            # cuánto bruto equivale a media importancia
    "regard_scale": None,           # cuánto APRECIO equivale a media importancia

    # === LOS TRES ÍNDICES. Todos estrenan a 0.0 ============================
    "regret_weight": 0.0,           # el escarmiento, por ACCIÓN
    "regret_scale": 0.5,
    "fear_weight": 0.0,             # el miedo, por LUGAR
    "fear_scale": 0.5,
    "grief_scale": 0.0,             # el duelo, por PERSONA. No tiene _weight

    # === LOS RUMORES =======================================================
    "rumor_rate": 0.0,              # probabilidad de contar algo al terminar
    "rumor_decay": 0.5,             # cuánto sobrevive a cada boca
}
```

---

# 2 · Los que más carácter dan al mundo

## `temperature` + `candidate_pool` — cuánto azar hay

```
candidate_pool: 1    determinismo puro. Siempre la mejor opción
candidate_pool: 3    las tres mejores entran en el sorteo
temperature: 0.05    casi siempre gana la mejor
temperature: 0.12    lo normal
temperature: 0.40    el mundo es caótico
```

> Con `temperature: 0` el mundo es un reloj y **todos los del mismo perfil hacen
> exactamente lo mismo**. La diferenciación se hunde. Con demasiado, ninguna
> conducta se puede explicar — y eso lo mide `--divergence`.

## `critical_need_threshold` — cuándo cunde el pánico

**Por debajo de este valor, una necesidad puede interrumpir lo que se está
haciendo.** Solo interrumpe si la acción en curso **no la atiende**: nadie
abandona la cena por hambre.

```
0.10   aguanta mucho. La gente termina lo que empieza
0.15   lo normal
0.30   el mundo entero va apagando fuegos
```

## `travel_discount` — cuánto encoge el mundo

```
descuento ** ticks_de_viaje

0.94 ** 1 = 0.94     al lado, casi gratis
0.94 ** 5 = 0.73     al otro lado del pueblo, un 27 % menos atractivo
0.94 ** 10 = 0.54    otra comarca: tiene que compensar el doble
```

> Es **la perilla que decide si tu mapa existe**. A 0.99 todo el mundo va a
> todas partes y la geografía no significa nada; a 0.85 nadie sale de su barrio
> y los lugares lejanos son contenido muerto.

## `switch_cost` — cuánto protege lo ya invertido

Sin esto, cualquier cosa mejor interrumpe lo que se está haciendo y **salen
agentes que no terminan nada**. Es la mitad del *compromiso con excepción de
urgencia*.

## `company_scale` — qué es «mucha gente» aquí

**El fallo que ya ocurrió, y conviene no repetirlo:**

> Con ocupación media de 14.4 personas y `company_scale: 1`, el alivio pasivo de
> la compañía cubría el **94 % del decaimiento** del vínculo, y **la soledad no
> llegó a apretar ni una vez en 256 000 muestras.**

```
1.0    un pueblo de diez: una persona ya es compañía
10.0   una ciudad de doscientos
```

## `bond_rate` y `bond_scale` — cómo de fácil es encariñarse

```
aprecio <- aprecio + bond_rate * (premio - aprecio)
```

```
bond_rate: 0.05   cuesta años tomar cariño
bond_rate: 0.15   lo normal
bond_rate: 0.40   se encariña en una tarde
```

> ⚠️ **Y esto decide si las muertes le duelen a alguien.** Medido: con
> `bond_rate 0.15` el aprecio máximo que confluencia llega a producir es 0.4564,
> y el aprecio mediano 0.1046. **Si tu mundo no da aprecio, no da duelo.**

## `bond_fade` y `bond_horizon` — cómo se pierde a la gente

```
bond_fade: 0.9997     a los 30 días queda el 42 %
bond_horizon: 2880    a los 30 días sin verse, el vínculo se borra entero
```

## `memory_capacity` — el techo real de todo lo acumulativo

```
0     DESACTIVA la memoria episódica entera
40    la biografía dura TRES días
200   doce días
```

> **Es el techo de todo lo que se acumula**: biografía, duelo, reputación,
> rumores. Y el olvido **descarta el de menor valor retenido, no el más viejo**
> — con FIFO, lo memorable queda enterrado por la rutina de los días siguientes,
> al revés de como funciona una biografía.

⚠️ **Con la memoria llena, lo que entre por debajo del listón se tira de
inmediato.** Medido en confluencia: la importancia mínima retenida es 0.2394 y
la mediana 0.4422. Si un mecanismo tuyo graba por debajo de eso, **no existe**.

## `regard_scale` — la escala del aprecio, y por qué es otra

**El aprecio y la saliencia no viven en la misma escala.** Un recuerdo corriente
saca su importancia de un bruto que compone urgencia, sorpresa y testigos. Un
duelo —y una noticia sobre alguien— la saca del **aprecio**, que es un número
pequeño por construcción: sale de `bond_rate` moviendo poco a poco un valor
acotado.

Metidos los dos por el mismo divisor:

```
importancia MEDIANA de lo guardado                 0.4422
importancia MÍNIMA retenida, con la memoria llena  0.2394
duelo típico   (aprecio 0.0746, escala 1.0)        0.0690
duelo MÁXIMO   (aprecio 0.4564, escala 1.0)        0.3134
```

> Es como apuntar lo que marca cada cosa en una escala del 0 al 10 y apuntar lo
> que marca una muerte en una del 0 al 3: **la peor pérdida posible saca un 3 y
> una buena cena saca un 5.** El olvido por valor tira lo más barato, así que el
> duelo se iba el mismo día. Medido: cinco muertes, y al día 75 **cero dolientes
> de 195 supervivientes**.

```
escala   duelo típico   duelo máximo   contra el listón 0.2394
1.0          0.069          0.313       casi todo se tira
0.5          0.130          0.477       lo típico se sigue tirando
0.1          0.427          0.820       el conocido dura semanas, el querido se queda
```

**Lo gobierna el rango que el aprecio alcanza en TU mundo**, que depende de
`bond_rate` y `bond_scale`. Por eso es una perilla del pack y no una constante:
**mídelo antes de ponerlo**.

`None` = usa `memory_scale`, o sea exactamente lo de siempre.

## Los tres índices, y el que no tiene `_weight`

```
regret_weight   el escarmiento, por ACCIÓN   ->  encarece la acción
fear_weight     el miedo, por LUGAR          ->  encarece el viaje
grief_scale     el duelo, por PERSONA        ->  NO ENCARECE NADA
```

> **El duelo no tiene un `_weight` al lado, y es deliberado.** De una acción y
> de un lugar uno puede apartarse; **de un ausente no**. Un peso obligaría a
> contestar *«el duelo encarece qué»*, y cualquier respuesta sería inventarse
> una forma única de vivirlo.

Lo que diferencia dos duelos es **de qué viene acompañado el recuerdo**:

```
sin lugar ni acción   duele y se pasa
con lugar             `miedo` le cambia la rutina
con acción            `rencor` se lo hace cuesta arriba
y cuánto le dura      es suyo, por `memory_multipliers`
```

**Cuatro vidas distintas sin una sola rama escrita para el duelo.**

## `strain_multipliers` — cómo decide alguien al límite

```python
"strain_multipliers": {"temperature": 2.0, "travel_discount": 0.85}
```

> Agotado y con hambre **no quieres cosas distintas** —de eso se encarga la
> urgencia— sino que **decides peor**: más errático, y las distancias pesan más.

⚠️ El desgaste **se renormaliza** con los `strain_weight` de las necesidades.

---

# 3 · El reloj

```python
"clock": {
    "minutes_per_tick": 15,
    "ticks_per_day": 96,
    "days_per_year": 360,
    "phases": [{"id": "manana", "label": "mañana", "starts_at": 24},
               {"id": "tarde",  "label": "tarde",  "starts_at": 52},
               {"id": "noche",  "label": "noche",  "starts_at": 80}],
}
```

**Todo lo que el pack declara en tiempo va en ticks, nunca en días** — el reloj
lo define el pack, y hablar en días obligaría al motor a saber cuántos ticks
tiene uno.

```
96      un día        2016    tres semanas
288     tres días     34560   un año
2880    un mes
```

Las franjas son **desde `starts_at` hasta la siguiente**, circulares: con las de
arriba, de 80 a 24 es «noche», y cubre la madrugada.

---

# 4 · El contrato de salud

**Cada pack promete algo de sí mismo y se comprueba en cada corrida de tests.**

```python
"health": {
    "days": 14,
    "seeds": [4271],
    "min_crisis": 0.02,           # menos que esto: el mundo es un balneario
    "max_crisis": 0.40,           # más: es inhabitable
    "max_abort_ratio": 0.30,      # cuánto se abandona a medias
    "max_transit": 0.35,          # cuánto tiempo se pasa andando
    "min_differentiation": 0.40,  # cuánto se distinguen dos biografías
    "max_muertes": None,
    "may_go_unused": ["socorrer", "expoliar_corazon"],
}
```

**Un mundo pequeño y uno grande no tienen los mismos números sanos**, por eso
cada pack declara el suyo en vez de haber umbrales globales.

`may_go_unused` es donde se declara **lo que es deliberadamente raro**: pedir
`armas 0.60` y `temple 0.50` son meses, no dos semanas. Declararlo es la
diferencia entre contenido lento y contenido muerto.

> ⚠️ **`muertes` sale la primera del panel y rompe el orden**, porque si las hay,
> todo lo de abajo describe a los supervivientes. Y un perfil vacío no entra en
> la diferenciación: como vector es máximamente distinto de todos, así que
> **matar gente mejoraba la diferenciación**.

---

# 5 · La regla de oro para llenar esto

**Todo mecanismo se estrena apagado.** Los cinco de memoria vienen a 0.0 por
defecto, y no es pereza:

> Estrenar algo **no puede mover ningún contrato ya medido**. Se enciende
> después, con la línea base delante, y se mide antes y después.

Los que estrenan apagados:

```
memory_capacity: 0    regret_weight: 0.0    fear_weight: 0.0
grief_scale: 0.0      rumor_rate: 0.0       bond_rate: 0.0
bond_weight: 0.0      companionship_weight: 0.0   learning_rate: 0.0
sighting_horizon: 0   bond_horizon: 0
```

**Un pack que no los toca se comporta exactamente como antes de que existieran.**
