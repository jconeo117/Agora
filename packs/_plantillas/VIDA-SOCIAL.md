# Plantilla de vida social — lazos, metas, gustos y la ficha

Cuatro piezas que juntas hacen a alguien **una persona concreta y no un perfil**.

**La distinción de fondo, antes de nada:**

```
UN VÍNCULO es lo que SIENTES        emergente, asimétrico, gradual, se olvida
UNA RELACIÓN es lo que ERES         un HECHO. No crece con el trato
```

> Tu hermano sigue siendo tu hermano el año que no lo visitas, y **lo sigue
> siendo el día que lo detestas**. Meterlo dentro del vínculo habría hecho
> imposible justamente eso: un aprecio con nombre se disolvería con el aprecio.

---

# 1 · Relaciones — lo que eres de alguien

## La plantilla

```python
{"id": "pareja", "label": "pareja",
 "symmetric": True,        # vale igual en los dos sentidos
 "inverse": None,          # o el nombre del otro lado: maestro <-> discipulo
 "exclusive": True,        # solo se puede tener una
 "regard_floor": 0.45,     # aprecio MÍNIMO por ser lo que es. None = ninguno
 "company_multiplier": 2.0}
```

## Cada campo

**`symmetric` vs `inverse`** — alternativas, no complementos. Una relación **o
vale igual en ambos sentidos o se llama distinto en cada uno**.

```python
{"id": "hermano", "symmetric": True}                       # hermano <-> hermano
{"id": "maestro", "inverse": "discipulo"}                  # maestro -> discípulo
{"id": "discipulo", "inverse": "maestro"}
```

Declararla una vez basta: el motor pone la otra mitad. Si no, el pack tendría
que escribir cada hermandad dos veces y **una de las dos acabaría faltando**.

**`exclusive`** — no es una regla moral, es que un árbol genealógico con dos
parejas simultáneas **deja de poder leerse**.

**`regard_floor`** — el campo que más produce, y el más fácil de escribir mal.

```
None   no toca nada. El aprecio es solo lo que hayáis compartido
0.0    un suelo DE VERDAD: el de quien nunca llega a caerte mal del todo
0.45   la familia se aguanta
```

> ⚠️ **`None` y `0.0` no son lo mismo, y confundirlos costó un test.** Un suelo
> en cero **aplasta el aprecio negativo**, así que haría imposible detestar a un
> hermano.

El suelo es **un mínimo, no un valor fijo**: el aprecio sigue subiendo y bajando
con lo que se comparte, pero no cae por debajo. También es el punto de partida —
quien empieza siendo pareja de alguien **no empieza siendo un desconocido**.

Y es lo que decide quién te duele al morir:

```
pareja      con suelo 0.45  ->  duelo 0.3103   se queda en la memoria
discipulo   con suelo 0.30  ->  duelo 0.2308   justo en el filo
hermano     SIN suelo       ->  duelo 0.0000   si no había trato, nada
```

> **Ahí está la propiedad que se buscaba.** Un `padre` declarado sin suelo es
> exactamente el que nunca reconoció a su hijo: tiene la relación y no el
> aprecio, así que apenas se entera. **Lo decide el pack.**

**`company_multiplier`** — cuánto pesa su presencia frente a la de un
desconocido de igual aprecio. Un plan donde estará tu pareja atrae más que el
mismo plan con alguien que te cae igual de bien. **Es la diferencia entre
apreciar a alguien y que ese alguien sea de los tuyos.**

> Una relación puede **no hacer NADA mecánicamente** y seguir siendo legítima.
> Eso la separa de una situación, que si no afecta a nada es contenido muerto:
> aquí el hecho ya vale por sí solo — es lo que el narrador necesita saber.

---

# 2 · Metas — la única forma de que a alguien le cambie el carácter

## La plantilla

```python
{"id": "graduarse", "label": "graduarse con honores",
 "need": "curso",             # sobre qué eje
 "at_least": 0.95,            # el umbral que hay que alcanzar
 "weight_multiplier": 2.2,    # cuánto más le importa ese eje mientras la persiga
 "deadline": 207360,          # en ticks. None = sin plazo
 "on_success": {"graduado": 1.0, "ambicion": 0.3},
 "on_failure": {"laboriosidad": 0.5, "hedonismo": -0.3}}
```

## Por qué importa tanto

**Los rasgos son fijos. Esto es lo único que los mueve.**

```python
"on_success": {"graduado": 1.0, "ambicion": 0.3},
"on_failure": {"laboriosidad": 0.5, "hedonismo": -0.3}
```

> Lo consigue y se vuelve más ambicioso. **Lo falla y se entierra en el trabajo
> renunciando al placer.** Dos biografías distintas del mismo punto de partida,
> y ninguna de las dos está escrita como guion.

`on_success` también **otorga rasgos-llave**: `graduado: 1.0` abre las acciones
que lo piden. Es cómo se gana un título en el mundo.

## Los plazos, en ticks

```
34560     un año
207360    seis años (una carrera y uno más)
None      sin plazo: la persigue toda la vida
```

## Y la regla que hace que un pueblo parezca un pueblo

> **No todo el mundo tiene arco.** Un pueblo donde los cien persiguen algo no es
> un pueblo. **Dos de cada tres**, y solo metas que le peguen a su rol.

```python
posibles = [k for k, v in METAS.items() if rol in v.roles]
if posibles and rng.random() < 0.66:
    ...
```

---

# 3 · Gustos — el sesgo por instancia

```python
{"target": "la_taberna_del_puerto", "multiplier": 1.7}
```

**Los rasgos dicen que le gustan las tabernas; los gustos dicen que le gusta
ESA taberna.** El `target` puede ser una acción, un lugar o una persona.

```python
tastes = [
    {"target": "expoliar_cripta", "multiplier": 2.3},   # su oficio
    {"target": "plaza_elfica", "multiplier": 1.25},     # su barrio
    {"target": "tasar_botin", "multiplier": 1.7},
]
```

## El truco del apego, que produce migración sin programarla

```python
apego = round(rng.uniform(0.95, 1.45), 2)
gustos = [{"target": sitio, "multiplier": apego}
          for sitio in (plaza_de_los_suyos, cama_de_los_suyos)]
```

> **Se sortea ancho a propósito.** `home` no ata a nadie —no tiene ningún efecto
> mecánico— así que **mudarse ya era gratis**. Lo que faltaba era una razón para
> no hacerlo. Por debajo de 1.0 hay gente **deseando salir de su barrio**, y de
> la tensión entre ese número, lo que paga el centro y el descuento de viaje
> sale quién migra y quién se queda, **sin que nadie lo programe**.

---

# 4 · La ficha — dónde se junta todo

```python
{"id": "elena_vadohondo", "label": "Elena Vadohondo",

 "home": "posada_central",      # dónde vive. SIN efecto mecánico
 "start_at": "plaza_mayor",     # dónde está al empezar

 "traits": {"sociabilidad": 0.7, "ambicion": -0.3, "elem_fuego": 1.0},
 "tastes": [{"target": "la_taberna", "multiplier": 1.4}],
 "initial_needs": {"dinero": 0.35},          # override del `initial` del eje
 "goals": [{...}],
 "relations": {"pareja": ["hurn_umbrio"]},
 "initial_bonds": {"hurn_umbrio": 0.55, "isla_hojaclara": 0.20}}
```

## Los dos campos que se confunden

```
relations       lo que ERES de alguien. Un hecho
initial_bonds   lo que SIENTES por alguien al empezar. Cambiará
```

**Y se escriben asimétricos a propósito:**

```python
_uno["initial_bonds"][_otro] = 0.55
_otro["initial_bonds"][_uno] = 0.50
```

> Cada cual guarda el suyo. Que uno quiera un poco más que el otro es la clase
> de detalle que hace que una pareja no sea un espejo.

Y a veces **la relación sin el vínculo es lo interesante**:

```python
# Diez hermandades entre alumnos, SIN aprecio de partida.
# El suelo de `hermano` es None a propósito, así que empiezan de cero y se
# ganan lo que sientan — que es la mitad de la gracia de separar las dos cosas.
```

## `home` no ata a nadie

**No tiene ningún efecto mecánico en el motor**, solo se valida como referencia.
La gente duerme y trabaja donde le compensa. Si quieres que alguien vuelva a
casa, la razón tiene que ser un **gusto**, un peaje o una buena cama.

---

# 5 · Cómo se ensambla una población

Dos maneras probadas, y hacen mundos distintos:

## Arquetipos compuestos

```python
ARQUETIPOS = {
    "aplicado": dict(laboriosidad=0.8, impulsividad=-0.5, sociabilidad=-0.3),
    "vividor":  dict(hedonismo=0.8, frugalidad=-0.5, impulsividad=0.7),
}
# DOS por ficha, promediados donde chocan, más ruido de ±0.12
```

> Uno solo daría cien personas de quince tipos. Dos dan **105 combinaciones**, y
> las que chocan salen término medio — que también es una persona.

## Sesgos por origen

```python
SESGO = {"enano": {"tierra": 5, "fuego": 3, "agua": 1, "viento": 1}}
```

> **Nunca un candado, solo una inclinación fuerte.** El enano de viento existe y
> es raro, que es exactamente lo que quieres: un candado lo haría imposible y
> una tirada plana lo haría corriente.

## Y el orden importa

```
1. la plantilla de roles     ->  cuántos de cada. NO se sortea, se decide
2. el nombre                 ->  del catálogo, sin repetir
3. la personalidad           ->  arquetipos o sesgos + ruido
4. el rol pone lo suyo       ->  casa, oficio, rasgos-llave
5. los gustos                ->  su oficio, su barrio
6. la meta                   ->  2 de cada 3, filtrada por rol
7. las relaciones            ->  DESPUÉS, cuando ya existen todos
```

**El rango no se asigna: no existe en la ficha.** Todos empiezan en rango 0 y se
lo ganan en el mundo.

---

# 6 · Las trampas

**1 · `None` y `0.0` en `regard_floor` no son lo mismo.** Cero aplasta el
aprecio negativo y hace imposible detestar a alguien.

**2 · Una relación exclusiva declarada dos veces no carga.** Es el invariante que
va a sostener la descendencia.

**3 · `home` no hace nada.** Si quieres arraigo, ponlo en `tastes`.

**4 · Un gusto por debajo de 1.0 es una aversión**, y es legítimo y útil.

**5 · Las relaciones van después de crear a todo el mundo**, porque apuntan a
ids que tienen que existir.

**6 · Una meta sin `deadline` no falla nunca**, así que su `on_failure` es
código muerto.

**7 · Un vínculo solo crece compartiendo acciones** (`effects_per_company`).
Cruzarse crea el vínculo con aprecio 0; **lo que lo mueve es hacer cosas
juntos**. Si tu mundo no tiene acciones compartidas, no habrá aprecio y ninguna
muerte le dolerá a nadie.
