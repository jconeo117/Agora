# Plantillas de contenido — cómo se escribe un mundo

Seis plantillas. Entre las seis está **todo lo que el motor sabe expresar hoy**
sobre una persona y sobre el mundo donde vive.

Cada una lleva la plantilla en blanco, un ejemplo real con datos, **la
explicación de cada número**, y las trampas que ya han mordido.

---

# El mapa

| plantilla | qué parte del ser humano cubre |
|---|---|
| **[NECESIDADES](NECESIDADES.md)** | **qué le mueve** — hambre, sueño, dinero, compañía, ambición |
| **[PERSONALIDAD](PERSONALIDAD.md)** | **quién es** — los siete canales de un rasgo |
| **[ACCIONES](ACCIONES.md)** | **qué puede hacer** — el repertorio, y lo que le hace a otros |
| **[LUGARES](LUGARES.md)** | **dónde vive** — el mapa, las distancias, los horarios |
| **[EVENTOS](EVENTOS.md)** | **qué le pasa sin decidirlo** — clima, tragedias, heridas, enfermedades |
| **[VIDA-SOCIAL](VIDA-SOCIAL.md)** | **de quién es** — lazos, metas, gustos, la ficha |
| **[MUNDO](MUNDO.md)** | **cómo es este mundo** — las 33 perillas, el reloj, el contrato |

---

# El orden en que se llenan

**No es un capricho: cada paso apunta al anterior.** Un rasgo multiplica un eje;
si el eje no existe, el rasgo no carga.

```
1. NECESIDADES    los ejes. Todo lo demás apunta aquí
2. LUGARES        el mapa y sus affordances
3. ACCIONES       lo que se hace, y dónde. Cierra el bucle con 1 y 2
4. PERSONALIDAD   los rasgos, que reescalan lo de 1 y 3
5. VIDA-SOCIAL    lazos y metas
6. EVENTOS        lo que le pasa a uno encima de todo eso
7. MUNDO          las perillas, al final, con todo delante para medirlo
```

**Un pack no carga si algo apunta a lo que no existe**, así que cargar ya es
media comprobación.

---

# Las cinco reglas que valen para las seis plantillas

## 1 · Escribe siempre las dos mitades

Un eje que se llena y nunca se gasta es decorado. Un eje que se gasta y no se
puede llenar es una condena. Una condición que se inflige y nadie cura es una
sentencia de muerte.

## 2 · Todo se estrena apagado

Un mecanismo nuevo con la perilla a 0 **no puede mover un contrato ya medido**.
Se enciende después, con la línea base delante.

## 3 · La intensidad negativa ya existe

No escribas el rasgo opuesto: es el mismo a `-1.0`, exacto. Un catálogo de 20
rasgos describe muchas más de 20 clases de persona.

## 4 · Contenido muerto se lee como contenido vivo

Un lugar desierto, una acción sin usar, una situación que no dispara. **El panel
lo delata**, y lo que es deliberadamente raro se declara (`may_go_unused`).

## 5 · Se mide en conjunto, nunca pieza a pieza

Que tu rasgo funcione en su prueba no significa nada si el mundo entero, con
todo encendido y a seis meses, se apaga. **Un engranaje sin tope atascó cuatro
mecanismos** y ninguna prueba unitaria podía verlo.

---

# Lo que el motor NO sabe expresar todavía

Por si lo intentas y no sale — no es que lo estés escribiendo mal:

| No hay | Consecuencia |
|---|---|
| **Edad** | nadie envejece: sin veteranía, sin herencia, sin ventanas por edad |
| **Estados de ánimo** | el desgaste es UN número: enfadado y abatido son el mismo valor bajo |
| **Rencor hacia una PERSONA** | el culpable es una situación, nunca alguien. **Sin venganza ni perdón** |
| **Rasgos que interactúan** | cada uno actúa por su cuenta. No hay «audaz, pero solo si está solo» |
| **Grupos y facciones** | los lazos son de dos en dos. «El gremio» no se puede expresar |
| **Propiedad** | nadie posee nada. El dinero aparece al trabajar y desaparece al gastar |
| **Inventario** | ningún lugar tiene almacén; nada se agota ni se repone |
| **Aforo** | un lugar no tiene capacidad. «Lleno» no se puede escribir |
| **Nacimientos** | el censo puede menguar (se muere gente) pero no crecer |
| **Lugares en marcha** | el mapa se fija al cargar. Nadie construye nada |
| **Diálogo** | la costura está reservada y vacía |

---

# Cómo se prueba lo que escribes

```bash
# Regenerar el pack. Si no valida, no escribe nada
cd packs/<mundo> && uv run python generar.py

# El panel: contra el contrato que el propio pack promete
uv run agora --pack packs/<mundo>/pack.yaml --health

# El eje vivo/aleatorio: cuánto cambia la vida de la MISMA persona
# entre semillas. Si el azar pesa tanto como el carácter, nada se explica
uv run agora --pack packs/<mundo>/pack.yaml --divergence 3
```

**El `pack.yaml` generado NO se edita a mano.** Se edita el generador.

Y para cualquier cosa acumulativa —memoria, miedo, duelo, rumores, progresión—
**la corrida corta no vale**: 60–90 días como mínimo, y **180 si hay rangos**,
porque la cuesta es cuadrática y a 60 días no se distingue *«sube despacio»* de
*«está atascado»*.
