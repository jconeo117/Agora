# Plantilla de necesidades — los ejes que mueven a una persona

Una necesidad es **un eje de presión interna**. El motor no sabe si esto es
«hambre» o «nivel de oxígeno»: solo sabe que baja sola y que ciertas acciones la
suben.

**Todo lo demás del pack apunta aquí.** Un rasgo multiplica un eje, una acción
llena un eje, un lugar encarece un eje, una herida drena un eje. Si los ejes
están mal, no hay rasgo que lo arregle.

---

# 1 · La plantilla

```python
def N(id, label, decay, **k):
    return {"id": id, "label": label, "decay_per_tick": decay, **k}

N("mi_eje", "cómo se lee en pantalla", 0.006,

  # --- QUÉ CLASE DE EJE ES --------------------------------------------------
  progression=False,       # True: solo sube. Nivel, experiencia, reputación
  urgent_when_low=True,    # False: quedarse sin esto NO es una emergencia

  # --- DE DÓNDE PARTE Y HASTA DÓNDE LLEGA -----------------------------------
  initial=1.0,             # valor al empezar la partida
  cap=1.0,                 # techo del mundo. Los rasgos lo suben, no lo bajan

  # --- CUÁNTO PESA ----------------------------------------------------------
  base_weight=1.0,         # importancia antes de que la personalidad la toque
  urgency_exponent=2.0,    # la curva: urgencia = (1 - valor) ** exponente

  # --- LO QUE LO HACE DURO --------------------------------------------------
  strain_weight=0.0,       # cuánto DESGASTA que escasee. OJO: renormaliza
  max_debt=0.0,            # cuánto puede estar POR DEBAJO de cero
  lethal_after=0,          # ticks seguidos a cero antes de morir. 0 = nunca

  # --- LO QUE LO HACE SOCIAL ------------------------------------------------
  company_relief=0.0,      # cuánto frena la gente su decaimiento, por tick

  # --- PROGRESIÓN SIN TECHO -------------------------------------------------
  rank_slowdown=0.0,       # convierte el eje en rangos numerados
)
```

---

# 2 · Cada número, explicado

## `decay_per_tick` — cuánto baja sola

**Calibrar esto es el trabajo entero.** Con 96 ticks al día:

```
0.010  ->  se vacía en 100 ticks     ~1 día        hambre apremiante
0.007  ->  se vacía en 143 ticks     ~1.5 días     descanso
0.003  ->  se vacía en 333 ticks     ~3.5 días     dinero
0.001  ->  se vacía en 1000 ticks    ~10 días      algo de fondo
0.000  ->  no se pierde solo                       solo cambia por lo que haces
```

Un `0` describe un eje que **solo cambia por lo que se hace**. La salud de
confluencia es así: nadie enferma por el paso del tiempo, solo por lo que le
pasa.

## `progression` — no es una carencia, es lo lejos que has llegado

```python
N("dominio", "dominio", 0.0, progression=True, rank_slowdown=1.0, cap=0.50)
```

> **La diferencia no es de grado sino de naturaleza:** estar a 0.1 de sustento
> es una emergencia; estar a 0.1 de experiencia es **ser novato**.

**Un eje de progresión no puede entrar en crisis.** Sin este campo, alguien que
empieza abajo estaría bajo el umbral crítico durante toda su escalada: soltaría
lo que estuviera haciendo para ir a entrenar. Medido: el tiempo en crisis pasa
del 0 % al 27.7 %, de sobra para reventar el contrato de un mundo sano.

**Lo que sí conserva es la urgencia**, y ahí está lo bueno: `(1 - valor) ** exp`
hace que subir apremie mientras eres novato y deje de importar cerca del tope.
**Querer crecer no necesita un sistema de metas** — la fórmula ya sabe querer.

## `urgent_when_low` — la bolsa vacía es un martes

La distinción es entre **lo que se AGOTA y lo que se ACUMULA**.

```python
N("botin", "botín", 0.02, urgent_when_low=False)
```

> El hambre a cero es una urgencia. La bolsa vacía es un martes.

Sin esto, un inventario vacío produce un agente que interrumpe lo que sea para
ir a por material — medido, **una alumna de magia se fue a vivir al bosque el
primer día**. Apagarlo no toca la urgencia: sigue apeteciendo llenarlo, con la
misma curva. Solo pierde el **poder de interrumpir**.

## `urgency_exponent` — la curva, y decide el carácter del mundo

```
urgencia = (1 - valor) ** exponente
```

| exponente | a valor 0.5 | qué produce |
|---|---|---|
| `1.0` | 0.50 | **oscila**: atiende todo a medias, nunca termina nada |
| `2.0` | 0.25 | el defecto sano |
| `2.6` | 0.15 | **aguanta y luego corre**: ignora hasta que aprieta de verdad |
| `4.0` | 0.06 | solo existe en la emergencia |

Un exponente alto produce gente que **no se preocupa hasta que el problema es
grave**. Es lo que hace que la salud de confluencia (2.6) se ignore mientras se
esté por encima de la mitad.

## `base_weight` — la importancia antes de la personalidad

**Absoluto, no relativo.** Añadir una necesidad nueva **no recompone los pesos
del mundo** — se midió dos veces y el panel no se mueve ni una milésima.

```
base_weight 1.0   lo normal
base_weight 2.0   este eje vale por dos: el mundo entero gira alrededor
base_weight 0.4   está ahí, pero rara vez gana una deliberación
```

## `strain_weight` — lo único que SÍ renormaliza

**El desgaste no es una emoción: es un modificador de CÓMO se decide.** Estar
agotado y con hambre no cambia lo que quieres —de eso se encarga la urgencia—
sino que **decides peor**: más errático, y las distancias pesan más.

```python
N("descanso", "descanso", 0.007, strain_weight=1.0)
N("dinero",   "dinero",   0.003, strain_weight=0.0)   # aprieta, no te atonta
```

> ⚠️ **Este es el único campo que renormaliza.** Añadir una necesidad que lo
> declare **cambia el desgaste de todo el mundo**. Añadir una sin él es gratis.
> Ha mordido una vez ya.

## `company_relief` — estar acompañado, aunque no hables

```python
N("vinculo", "vínculo", 0.006, company_relief=0.003)
```

> Estar rodeado de gente alivia la soledad aunque no hables con nadie, **y da
> igual quién sea**. Es la diferencia entre estar acompañado y estar acompañado
> **por alguien**.

Satura: `relief * n/(n + company_scale)`. **Nunca por encima del
`decay_per_tick`** —lo comprueba el validador— porque por encima la necesidad
**subiría sola** por estar en una multitud y el bucle social entero moriría sin
que nada fallase.

> **El fallo que ya ocurrió:** con ocupación media de 14.4 y `company_scale: 1`,
> el alivio pasivo cubría el 94 % del decaimiento y **la soledad no llegó a
> apretar ni una vez en 256 000 muestras**. En un mundo poblado hay que subir la
> escala.

## `max_debt` — estar peor que vacío

Sin esto, quien peleó tres días y quien durmió mal una noche están los dos en
0.0 y **son indistinguibles**.

```python
N("descanso", "descanso", 0.007, max_debt=1.0)
```

Con deuda, lo que el suelo recortaría se anota aparte, y **reponer paga la deuda
antes de subir la necesidad**. El drama sale sin escribirlo:

> Con `decay 0.007`, tres días sin dormir dejan deuda de 1.00. Pagarla y llenar
> el descanso son 2.00 a razón de 0.033 por tick: **quince horas de sueño**. Y a
> quien despierten a las ocho se levanta con la deuda saldada y el descanso a
> 0.19 — todavía hecho polvo.

Es la perilla que dice **cómo de brutal es la ambientación**:

```
1.0   una noche mala se paga en una noche larga
3.0   una campaña te deja roto una semana
```

## `lethal_after` — cuántos ticks a cero antes de morirte

```
0     nunca mata (el defecto)
288   tres días
96    un día
8     dos horas — el aire de una estación espacial
```

**El motor no puede saber que el hambre mata.** Que un eje sea mortal es
ambientación pura. Se cuenta a **valor cero**, no por deuda: *«tres días sin
comer y te mueres»* es una regla que quien juega aprende.

> ⚠️ **`lethal_after` por sí solo es decoración.** Ningún mundo calibrado para
> ser habitable deja un eje vacío tanto tiempo — medido en tres mundos. Para que
> alguien se muera hace falta algo que drene **desde fuera de sus decisiones**:
> una condición (`inflicts`). Ver `EVENTOS.md`.

## `cap` — el techo del mundo

Los rasgos lo **suben** (`cap_multipliers`), nunca lo bajan. La necesidad
declara *lo que alcanza cualquiera con empeño*; el rasgo dice *quién lo pasa*.

Y el apremio se mide **contra el techo propio**, no contra 1.0 — sin eso un
techo sería una trampa que condena a entrenar de por vida lo que ya no mejora.

## `rank_slowdown` — progresión sin techo

```python
N("dominio", "dominio", 0.0, progression=True, cap=0.50, rank_slowdown=1.0)
```

El valor sigue en `[0,1]` y significa **cuánto llevas de este rango**; al
llenarlo, el rango sube uno y el valor vuelve a cero.

```
ritmo(rango) = ritmo_base / (1 + rango) ** rank_slowdown

1.0   inversamente proporcional: el rango 3 sube a un cuarto que el 0
0.5   la cuesta es suave
2.0   brutal
```

Con `1.0` y un ritmo que llene el primer rango en medio día:

```
rango  5   ~8 días      rango 20   ~110 días      rango 50   ~2 años
```

**Nadie termina.** Los rangos altos son raros porque cuestan, no porque un tope
los prohíba.

> **Y aquí `cap` cambia de significado:** deja de ser *hasta dónde llegas* y pasa
> a ser *cuánto te cuesta romper el listón*. **Un `cap` bajo pasa a ser un don,
> no una limitación.**

---

# 3 · Ejemplo completo: siete ejes que describen a un humano

```python
needs = [
    # LO QUE SE AGOTA — el cuerpo
    N("sustento",  "sustento",  0.010, strain_weight=1.0, max_debt=0.6,
      lethal_after=288, urgency_exponent=2.2),
    N("descanso",  "descanso",  0.007, strain_weight=1.0, max_debt=1.0,
      urgency_exponent=2.0),
    N("salud",     "salud",     0.000, lethal_after=288, urgency_exponent=2.6),

    # LO QUE SE ACUMULA — la bolsa
    N("dinero",    "dinero",    0.003, urgency_exponent=1.8),

    # LO QUE PIDE A OTROS — el alma
    N("vinculo",   "vínculo",   0.006, company_relief=0.003, strain_weight=0.5,
      urgency_exponent=2.0),
    N("estimulo",  "estímulo",  0.005, urgency_exponent=1.6),

    # LO QUE NO SE PIERDE — la vida
    N("dominio",   "dominio",   0.000, progression=True, cap=0.50,
      rank_slowdown=1.0),
]
```

| eje | por qué esos números |
|---|---|
| `sustento` | el más rápido (1 día) y **mortal a los tres días**. Desgasta. Con deuda: pasar hambre se paga |
| `descanso` | día y medio, **la deuda más alta** (1.0): tres días en vela cuestan quince horas de sueño |
| `salud` | **no decae sola** — solo la mueven las heridas. Exponente 2.6: se ignora hasta que aprieta |
| `dinero` | tres días y medio, exponente bajo: **preocupa pronto y de forma sostenida**, no en pánico |
| `vinculo` | con `company_relief` a la mitad del decaimiento: la gente **frena** la soledad, no la cura |
| `estimulo` | exponente 1.6, el más bajo: el aburrimiento **molesta antes** que casi nada |
| `dominio` | ni decae ni mata ni entra en crisis. Solo sube, y cada rango cuesta más |

---

# 4 · Las trampas

**1 · Un eje sin acción que lo llene es una condena.** Y sin acción que lo gaste,
decorado. Escribe siempre las dos mitades.

**2 · `strain_weight` renormaliza.** Es el único. Añadir un eje que lo declare
mueve el desgaste de todo el mundo, y el panel entero con él.

**3 · `company_relief` por encima del decaimiento mata el bucle social.** El
validador lo impide, pero incluso rozándolo, en un mundo poblado la necesidad
deja de apretar.

**4 · `lethal_after` sin `inflicts` no mata a nadie.** Está medido en tres mundos.

**5 · Un eje de progresión sin `progression=True` mete al mundo en crisis
permanente.** 27.7 % del tiempo, medido.

**6 · Oferta/demanda por encima de 1.3 = el eje está resuelto y no decide nada.**
Todo lo que escribas alrededor es decorado. El panel lo mide.

**7 · «De gorra».** Si un eje se llena sin cumplir la condición que dice
importar, encarecerlo solo hace que la gente se quede quieta. Mide qué fracción
se satisface gratis.
