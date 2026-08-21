# Plantilla de lugares — el escenario, y lo que cuesta estar en él

Un lugar es **un nodo con cosas que se pueden hacer allí**. El motor no sabe qué
es una taberna: sabe que ofrece `mesa` y `bebida`, que está a 3 de la plaza, y
que cierra de madrugada.

**Y el mapa no es decorado: es la mitad de la personalidad de un mundo.** Que
las plazas de barrio estén a 2 del centro y a 1 de los suyos es lo que hace que
la geografía signifique algo — sin eso, las razas serían etiquetas.

---

# 1 · La plantilla

```yaml
- id: taberna_central
  label: La Taberna del Puerto

  # QUÉ SE PUEDE HACER AQUÍ. Sin affordances, un lugar es un pasillo
  affordances: [mesa, bebida, cama]

  # A QUÉ DISTANCIA ESTÁ DE SUS VECINOS, en ticks de viaje
  neighbors:
    plaza_mayor: 1
    puerto: 2
    barrio_alto: 4

  # LO QUE CUESTA IR desde cada sitio. NO lo que cuesta hacer algo aquí
  tolls:
    barrio_alto: {descanso: 0.04}

  # LO QUE RINDE MÁS AQUÍ que en otro sitio
  gain_multipliers: {vinculo: 1.3, descanso: 0.8}

  # CUÁNDO ESTÁ ABIERTO. Vacío = siempre
  open_during: [tarde, noche]

  # QUÉ LO CIERRA DEL TODO
  closed_during: [inundacion, cuarentena]

  tags: [social, interior]
```

---

# 2 · Cada campo, explicado

## `affordances` — el vocabulario que une lugares y acciones

**Es la única costura entre el mapa y el repertorio.** Una acción pide
`requires_affordance: "cama"`; un lugar la ofrece o no.

```
cama · mesa · fogon · yunque · mercaduria · altar · palestra · sima
```

> El motor **compara cadenas y nunca las interpreta**. Un pack de naves diría
> `esclusa`; uno de política, `tribuna`.

⚠️ **Un lugar sin affordances es un pasillo:** solo sirve para pasar por él. Es
legítimo (un camino, un puente) pero si no es lo que querías, nadie irá nunca.

## `neighbors` — la distancia, en ticks

```
1   al lado. Se cruza sin pensarlo
2-3 la misma zona
5-7 al otro lado del pueblo: ir allí es una decisión
10+ otra comarca
```

**El grafo se precomputa entero al cargar** (`TravelMap`), así que no hace falta
declarar todas las parejas: basta con los vecinos directos y el motor calcula el
resto por el camino más corto.

> **La distancia es lo que hace que un lugar exista o no.** Si tu sitio nuevo
> está a 7 ticks y ofrece lo mismo que uno a 1 tick, no lo va a pisar nadie —
> y saldrá en el panel como lugar desierto.

## `tolls` — lo que cuesta IR, no lo que cuesta HACER

```yaml
tolls:
  barrio_alto: {descanso: 0.04}   # subir la cuesta desde el barrio alto cansa
```

**Se resuelve por lugar de origen y se suma al precio de todo lo que se haga
allí.** Es lo que modela una cuesta, un peaje de puente, un tramo peligroso.

> **El miedo viaja con el peaje**: los dos son el precio de ir. Cuando alguien
> aprende a temer un sitio, entra exactamente por aquí.

Los peajes **no los reduce el temple** (`cost_multipliers`): un porte vale lo
que vale, no menos por ser tú.

## `gain_multipliers` — lo que rinde más aquí

```yaml
gain_multipliers: {vinculo: 1.3, descanso: 0.8}
```

> En la taberna la compañía cunde un 30 % más, y se descansa peor.

**Es lo que diferencia dos sitios que ofrecen lo mismo.** Dos posadas con `cama`
son idénticas hasta que una declara `descanso: 1.2` y la otra `0.85` — y
entonces una es la buena y la otra la barata.

## `open_during` — el horario, y es OBJETIVO

```yaml
open_during: [tarde, noche]   # cerrado por la mañana
```

**Vacío = siempre abierto.**

> ⚠️ **Los horarios NO se desplazan con el cronotipo.** La herrería cierra a la
> misma hora para todo el mundo: el horario del mundo es objetivo y el reloj del
> cuerpo es subjetivo. Un nocturno vive su mañana a tu medianoche, y aun así se
> encuentra la herrería cerrada.

Es una **puerta dura**: el lugar cerrado no es menos atractivo, es que no está.

## `closed_during` — lo que lo cierra del todo

```yaml
closed_during: [inundacion]
```

Distinto de bajar su rendimiento con `gain_multipliers` desde la situación. Una
redada **deja el sitio sin nada que ofrecer**; una inundación **lo borra del
mapa** mientras dura.

> Elige según lo que quieras que pase: cerrarlo del todo **fuerza** a la gente a
> buscar alternativa, y ahí se ve quién tenía plan B.

---

# 3 · Ejemplo: cuatro lugares que se explican entre sí

```yaml
- id: plaza_mayor
  label: La Plaza Mayor
  affordances: [mercaduria, fuente]
  neighbors: {taberna: 1, forjas: 2, posada: 1, puerta_norte: 3}
  gain_multipliers: {vinculo: 1.2}
  open_during: [manana, tarde]

- id: taberna
  label: La Taberna
  affordances: [mesa, bebida]
  neighbors: {plaza_mayor: 1, posada: 1}
  gain_multipliers: {vinculo: 1.5, estimulo: 1.4, descanso: 0.7}
  open_during: [tarde, noche]

- id: posada
  label: La Posada
  affordances: [cama, mesa]
  neighbors: {plaza_mayor: 1, taberna: 1}
  gain_multipliers: {descanso: 1.25}

- id: sima
  label: La Sima
  affordances: [sima]
  neighbors: {puerta_norte: 4}
  tolls: {puerta_norte: {descanso: 0.08}}
  gain_multipliers: {dinero: 1.4, dominio: 1.6}
```

| decisión | qué produce |
|---|---|
| plaza abierta **solo de día** | por la noche la vida se muda a la taberna, sola |
| taberna con `descanso: 0.7` | se puede dormir la mona, pero se descansa mal |
| posada con `descanso: 1.25` | la buena cama de la zona, y por eso todos vuelven |
| sima **a 4+3 de la plaza** | bajar es medio día. **Nadie baja por capricho** |
| peaje de `descanso: 0.08` | y encima llegas cansado antes de empezar |
| `dinero 1.4` + `dominio 1.6` | pero paga, y **enseña**. El trato entero de la aventura |

> La sima es el ejemplo de todo junto: **lejos, cara de llegar, y la única que
> da lo que nadie más da.** Si le quitas cualquiera de las tres, deja de ser una
> decisión y pasa a ser una obviedad — hacia un lado o hacia el otro.

---

# 4 · Las trampas

**1 · Un lugar desierto sale en el panel.** Si nadie va, casi siempre es una de
tres: está demasiado lejos, ofrece lo mismo que uno más cerca, o su horario no
coincide con cuándo apetece lo que ofrece.

**2 · Dos lugares con las mismas affordances y sin `gain_multipliers` son el
mismo lugar.** El más cercano gana siempre y el otro es contenido muerto.

**3 · `neighbors` es dirigido en la escritura pero el grafo se cierra.** Declara
la ida; el motor resuelve el resto por camino más corto.

**4 · No existe el aforo.** Un lugar no tiene capacidad. «Lleno» no se puede
expresar hoy, así que una taberna puede tener dentro a los 200.

**5 · No se pueden crear lugares en marcha.** El mapa se fija al cargar. Nadie
construye nada.

**6 · El chasco de llegada es real y es correcto.** Se delibera sobre lo que se
**recuerda**, y la verdad se comprueba al llegar: viajas a la taberna porque
había gente, y al llegar se han ido. Eso no es un fallo, es la percepción
funcionando.
