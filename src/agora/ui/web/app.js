"use strict";

// La página no sabe nada del mundo: pinta eventos que le manda el servidor, en orden.
// Cada evento es un `tipo` con sus campos (ver src/agora/ui/session.py, WebPresenter).

const $ = (id) => document.getElementById(id);
const relato = $("relato");

let fuente = null;           // EventSource de la partida que se ve
let cola = Promise.resolve(); // los eventos se pintan uno detrás de otro
let activa = false;          // si la partida espera una respuesta del jugador
let completar = null;        // completa el tecleo en curso, si lo hay
let instantaneo = false;     // al retomar una partida, la historia se pinta sin tecleo
let enPartida = false;
let enTurno = false;         // si estamos dentro de un turno (entre `turno` y la pregunta)

const DESENLACE = {
  failure: "falla",
  success_at_cost: "éxito con coste",
  success: "éxito",
  critical: "crítico",
};

const RAZON = {
  victoria: "has ganado: eres el último en pie",
  muerte: "has muerto",
  fin: "se acabaron los días",
  salir: "has salido",
};

// -- utilidades ----------------------------------------------------------------

function el(tag, clase, texto) {
  const e = document.createElement(tag);
  if (clase) e.className = clase;
  if (texto !== undefined) e.textContent = texto;
  return e;
}

function alFinal() {
  relato.scrollTop = relato.scrollHeight;
}

function añadir(nodo) {
  relato.appendChild(nodo);
  alFinal();
  return nodo;
}

function aviso(texto, clase = "aviso") {
  return añadir(el("div", clase, texto));
}

async function api(ruta, metodo = "GET", cuerpo) {
  const r = await fetch(ruta, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
  });
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(datos.error || `error ${r.status}`);
  return datos;
}

// Un botón que se puede pulsar solo mientras la partida espera una respuesta.
function boton(texto, clase, alPulsar) {
  const b = el("button", `accion ${clase || ""}`.trim(), texto);
  b.disabled = !activa;
  b.addEventListener("click", alPulsar);
  return b;
}

function setActiva(valor) {
  activa = valor;
  $("texto").disabled = !valor;
  $("enviar").disabled = !valor;
  document.querySelectorAll(".accion").forEach((b) => { b.disabled = !valor; });
  if (valor) {
    enTurno = false;
    mostrarVivir(false);
    $("texto").focus();
  }
}

// Mientras el personaje vive sin decidir (21b) no llega ninguna pregunta: solo
// `estado`, cada hora de juego. Un turno, en cambio, empieza con `turno`.
function mostrarVivir(visible) {
  $("viviendo").hidden = !visible;
  $("parar").hidden = !visible;
}

async function responder(texto, eco = true) {
  if (!activa) return;
  setActiva(false);
  $("respuestas").replaceChildren();
  if (eco) añadir(el("div", "tu", `› ${texto}`));
  try {
    await api("/api/entrada", "POST", { texto });
  } catch (err) {
    aviso(err.message, "aviso error");
  }
}

// -- el tecleo -----------------------------------------------------------------

// Escribe `texto` en `nodo` letra a letra. Clic o tecla lo completa. Devuelve una
// promesa que se cumple cuando acaba, para que el evento siguiente espere.
function escribir(nodo, texto) {
  if (instantaneo) {
    nodo.textContent = texto;
    alFinal();
    return Promise.resolve();
  }
  return new Promise((ok) => {
    let i = 0;
    let reloj = null;
    const fin = () => {
      clearInterval(reloj);
      nodo.textContent = texto;
      completar = null;
      alFinal();
      ok();
    };
    completar = fin;
    reloj = setInterval(() => {
      i += 2;
      nodo.textContent = texto.slice(0, i);
      alFinal();
      if (i >= texto.length) fin();
    }, 16);
  });
}

// -- la hoja y el tapete -------------------------------------------------------

function pintarHoja(v) {
  const h = $("hoja");
  h.replaceChildren(el("h2", "", v.nombre));
  for (const [etiqueta, valor, critica] of v.necesidades) {
    const fila = el("div", critica ? "necesidad critica" : "necesidad");
    const barra = el("div", "barra-valor");
    const relleno = el("i");
    relleno.style.width = `${Math.round(valor * 100)}%`;
    barra.appendChild(relleno);
    fila.append(el("span", "", etiqueta), barra);
    h.appendChild(fila);
  }
  for (const [etiqueta, gravedad] of v.condiciones) {
    h.appendChild(el("div", "condicion", `${etiqueta}, ${gravedad.toFixed(1)}`));
  }
  if (v.propia) {
    h.appendChild(el("h2", "", "equipo"));
    if (v.objetos.length === 0) h.appendChild(el("div", "vacio", "no llevas nada"));
    for (const [n, nombre, puesto] of v.objetos) {
      const fila = el("div", "equipo");
      fila.appendChild(el("span", "", `${n}. ${nombre}`));
      if (puesto) {
        fila.appendChild(el("span", "puesto", "(puesto)"));
      } else {
        fila.appendChild(boton("poner", "", () => responder(`equipar ${n}`)));
      }
      h.appendChild(fila);
    }
  }
}

function pintarDados(tirada) {
  const dados = $("dados");
  dados.replaceChildren();
  const caras = [];
  for (const v of tirada.dice) caras.push(el("div", "d6", String(v)));
  for (const v of tirada.opposing_dice || []) caras.push(el("div", "d6 rival", String(v)));
  caras.forEach((c) => dados.appendChild(c));
  return caras;
}

// Los dados ruedan un momento y se paran en su valor; el desenlace queda a la vista.
function rodar(tirada) {
  const caras = pintarDados(tirada);
  const finales = [...tirada.dice, ...(tirada.opposing_dice || [])];
  caras.forEach((c) => c.classList.add("rodando"));
  if (instantaneo) {
    caras.forEach((c, i) => { c.textContent = String(finales[i]); c.classList.remove("rodando"); });
    desenlace(tirada);
    return Promise.resolve();
  }
  return new Promise((ok) => {
    let t = 0;
    const reloj = setInterval(() => {
      t += 1;
      caras.forEach((c) => { c.textContent = String(1 + Math.floor(Math.random() * 6)); });
      if (t >= 8) {
        clearInterval(reloj);
        caras.forEach((c, i) => { c.textContent = String(finales[i]); c.classList.remove("rodando"); });
        desenlace(tirada);
        ok();
      }
    }, 70);
  });
}

function desenlace(tirada) {
  const d = $("desenlace");
  d.replaceChildren(
    el("span", `veredicto ${tirada.outcome}`, DESENLACE[tirada.outcome] || tirada.outcome),
    el("span", "linea", tirada.linea),
  );
}

function pintarCombate(filas) {
  const c = $("combate");
  c.replaceChildren();
  for (const f of filas) {
    const bloque = el("div", "luchador");
    const nombre = el("div", "nombre");
    nombre.append(el("span", "", f.label), el("span", "", f.status));
    const pv = el("div", "pv");
    const relleno = el("i");
    relleno.style.width = `${f.vitality_max ? Math.round((100 * f.vitality) / f.vitality_max) : 0}%`;
    pv.appendChild(relleno);
    bloque.append(nombre, pv,
      el("div", "fat", `${f.vitality}/${f.vitality_max} PV · fatiga ${f.fatigue}/${f.fatigue_max} · estrés ${f.stress}/${f.stress_max}`));
    c.appendChild(bloque);
  }
}

// -- los eventos ---------------------------------------------------------------

const MANEJADORES = {
  apertura(e) {
    // La apertura (unidad 22): el mundo, la llegada y quién eres, párrafo a párrafo, con
    // su máquina de escribir. Clic o tecla completan el párrafo que se escribe.
    const caja = añadir(el("div", "apertura"));
    let cadena = Promise.resolve();
    for (const parrafo of e.texto.split(/\n\n+/)) {
      const p = el("p");
      caja.appendChild(p);
      cadena = cadena.then(() => escribir(p, parrafo));
    }
    if (e.sin_narrador) {
      cadena = cadena.then(() => aviso("el narrador no contestó: lo cuenta la plantilla"));
    }
    return cadena;
  },

  turno(e) {
    enTurno = true;
    mostrarVivir(false);
    $("cabecera").textContent = `${e.nombre} · tick ${e.tick}`;
    añadir(el("div", "turno", `${e.nombre}, tick ${e.tick}`));
  },

  estado(e) {
    pintarHoja(e);
    if (!enTurno) mostrarVivir(true);
  },

  relato(e) {
    const p = añadir(el("p", e.de_modelo ? "narracion" : "narracion plantilla"));
    const hecho = escribir(p, e.texto);
    if (e.sin_narrador) aviso("el narrador no contestó: lo cuenta la plantilla");
    return hecho;
  },

  suceso(e) {
    aviso(e.texto, "suceso");
  },

  aviso(e) {
    aviso(e.texto);
  },

  error(e) {
    aviso(e.texto, "aviso error");
  },

  atajos(e) {
    const caja = $("atajos");
    caja.replaceChildren();
    const locales = ["mirar", "ficha", "equipo", "esperar", "opciones", "más"];
    const verbos = [...e.atajos, ...locales.filter((v) => !e.atajos.includes(v))];
    for (const v of verbos) caja.appendChild(boton(v, "", () => responder(v)));
  },

  opciones(e) {
    const caja = añadir(el("details"));
    caja.open = true;
    caja.appendChild(el("summary", "", `opciones (${e.items.length})`));
    const lista = el("ol");
    for (const it of e.items) {
      const b = boton("", "opcion", () => responder(String(it.n)));
      b.append(el("span", "n", String(it.n)), el("span", "", it.texto));
      const li = el("li");
      li.appendChild(b);
      lista.appendChild(li);
    }
    caja.appendChild(lista);
  },

  gente(e) {
    const caja = añadir(el("details"));
    caja.open = true;
    caja.appendChild(el("summary", "", "con quién"));
    const lista = el("ol");
    for (const it of e.items) {
      const b = boton("", "persona", () => responder(String(it.n)));
      b.append(el("span", "n", String(it.n)), el("span", "", it.nombre), el("code", "", it.id));
      const li = el("li");
      li.appendChild(b);
      lista.appendChild(li);
    }
    caja.appendChild(lista);
  },

  mirar(e) {
    añadir(el("p", "", e.cabecera));
    for (const f of e.filas) {
      const fila = el("div", "mirar-fila");
      fila.append(el("code", "", f.id), el("span", "", `${f.nombre}: ${f.que}`));
      relato.appendChild(fila);
    }
    alFinal();
  },

  ficha(e) {
    const lineas = [...e.lineas];
    if (e.propia) {
      lineas.push("");
      if (e.objetos.length === 0) lineas.push("  no llevas nada");
      for (const [n, nombre, puesto] of e.objetos) {
        lineas.push(`  ${n}. ${nombre}${puesto ? " (puesto)" : ""}`);
      }
    }
    añadir(el("div", "ficha-card", lineas.join("\n")));
  },

  dicho(e) {
    const p = añadir(el("p", "dicho"));
    const quien = el("b", "", e.quien);
    const texto = el("span");
    p.append(quien, ": «", texto, "»");
    if (e.tono) p.append(" ", el("i", "", `[${e.tono}]`));
    if (e.respaldo) p.append(" ", el("i", "", "(respaldo)"));
    return escribir(texto, e.dice);
  },

  tirada(e) {
    añadir(el("div", "tirada-log", e.linea));
    return rodar(e);
  },

  combate(e) {
    pintarCombate(e.filas);
  },

  ronda(e) {
    aviso(e.texto, "ronda");
  },

  pensando(e) {
    $("pensando").hidden = !e.activo;
  },

  pide(e) {
    $("respuestas").replaceChildren();
    // El aviso de la caja sigue a la pregunta: «tú>» en una conversación, «>» fuera.
    const pregunta = e.texto.trim();
    $("texto").placeholder = pregunta && pregunta !== ">" ? pregunta : "escribe lo que haces";
    setActiva(true);
  },

  elige(e) {
    aviso(e.pregunta.trim());
    const caja = $("respuestas");
    caja.replaceChildren();
    e.textos.forEach((texto, i) => {
      const letra = "abc"[i];
      caja.appendChild(boton(`${letra}) ${texto}`, "", () => responder(letra)));
    });
    setActiva(true);
  },

  confirma(e) {
    aviso(e.texto.trim());
    const caja = $("respuestas");
    caja.replaceChildren(
      boton("sí", "", () => responder("s")),
      boton("no", "", () => responder("n")),
    );
    setActiva(true);
  },

  final(e) {
    setActiva(false);
    mostrarVivir(false);
    $("respuestas").replaceChildren();
    $("atajos").replaceChildren();
    const f = añadir(el("div", "final"));
    f.appendChild(el("h2", "", "fin de la partida"));
    f.appendChild(el("p", "", `${RAZON[e.razon] || e.razon}, ${e.ticks} ticks jugados`));
    for (const linea of e.lineas) f.appendChild(el("p", "", linea.replace(/^# /, "")));
    $("nueva").hidden = false;
    alFinal();
  },
};

function pintar(e) {
  const manejador = MANEJADORES[e.tipo];
  return manejador ? manejador(e) : undefined;
}

// -- la conexión ----------------------------------------------------------------

function mostrarPartida() {
  if (enPartida) return;
  enPartida = true;
  $("inicio").hidden = true;
  $("partida").hidden = false;
}

function mostrarInicio() {
  enPartida = false;
  if (fuente) fuente.close();
  fuente = null;
  $("partida").hidden = true;
  $("inicio").hidden = false;
  $("nueva").hidden = true;
}

// Se conecta a la partida en curso (o a la última): la historia desde 0, y después
// lo nuevo. Recargar la página no pierde nada.
function conectar(alRetomar) {
  if (fuente) fuente.close();
  cola = Promise.resolve();
  instantaneo = alRetomar;
  let recibidos = 0;
  let reposo = null;
  fuente = new EventSource("/api/eventos?desde=0");
  fuente.onmessage = (m) => {
    recibidos += 1;
    const evento = JSON.parse(m.data);
    if (!enPartida) mostrarPartida();
    if (alRetomar) {
      // Lo que llega a rachas, al retomar, es la historia: se pinta sin tecleo. Cuando
      // el flujo se queda quieto, la partida está en vivo y vuelve el tecleo.
      clearTimeout(reposo);
      reposo = setTimeout(() => { instantaneo = false; }, 400);
    }
    cola = cola.then(() => pintar(evento)).catch((err) => aviso(String(err), "aviso error"));
  };
  fuente.onerror = () => {
    if (!fuente) return;
    fuente.close();
    fuente = null;
    // Sin ningún evento, no hay partida: se queda la pantalla de inicio.
    if (recibidos > 0) aviso("se ha cortado la conexión con la mesa", "aviso error");
  };
}

function empezarVista() {
  relato.replaceChildren();
  $("hoja").replaceChildren();
  $("dados").replaceChildren();
  $("desenlace").replaceChildren();
  $("combate").replaceChildren();
  $("atajos").replaceChildren();
  $("respuestas").replaceChildren();
  $("cabecera").textContent = "";
  $("nueva").hidden = true;
  $("pensando").hidden = true;
  setActiva(false);
  mostrarPartida();
}

// -- la pantalla de inicio -------------------------------------------------------

function rellenar(id, items, prefijo) {
  const caja = $(id);
  caja.replaceChildren();
  items.forEach((it) => {
    const l = el("label");
    const r = el("input");
    r.type = "radio";
    r.name = "quien";
    r.value = `${prefijo}:${it.id}`;
    const nombre = el("span", "", it.label);
    l.append(r, nombre);
    if (it.resumen) l.append(el("small", "", ` ${it.resumen}`));
    caja.appendChild(l);
  });
  return items.length;
}

async function cargarPersonajes() {
  const mundo = $("mundo").value;
  const enc = encodeURIComponent(mundo);
  // Desde dónde se empieza: el mundo tal como lo escribió el pack, o un estado guardado.
  const guardados = await api(`/api/mundos/${enc}/guardados`);
  const sel = $("guardado");
  const previo = sel.value;
  sel.replaceChildren(...guardados.map((g) => new Option(g.label, g.id)));
  if (guardados.some((g) => g.id === previo)) sel.value = previo;
  const datos = await api(
    `/api/mundos/${enc}/personajes?guardado=${encodeURIComponent(sel.value || "nuevo")}`,
  );
  rellenar("personajes", datos.personajes, "p");
  $("bloque-forasteros").hidden = rellenar("forasteros", datos.forasteros, "f") === 0;
  const primero = document.querySelector('input[name="quien"][value^="p:"]');
  if (primero) primero.checked = true;
  creacionMundo = await api(`/api/mundos/${enc}/creacion`);
  $("opcion-crear").hidden = !creacionMundo.disponible;
  prepararCreacion();
  alCambiarQuien();
}

async function cargarMundos() {
  const mundos = await api("/api/mundos");
  const sel = $("mundo");
  sel.replaceChildren();
  for (const m of mundos) sel.appendChild(new Option(m.label, m.id));
  await cargarPersonajes();
}

function errorInicio(err) {
  const p = $("error-inicio");
  p.textContent = err.message;
  p.hidden = false;
}

// -- crear el personaje (lo que el mundo deja elegir) -------------------------------

let creacionMundo = null;   // lo que el mundo deja crear, o null hasta cargarlo
let tirada = null;          // los potenciales de la tirada: una por preparación

function modoElegido() {
  return document.querySelector('input[name="modo"]:checked').value;
}

function alCambiarQuien() {
  const quien = document.querySelector('input[name="quien"]:checked');
  const crea = quien !== null && quien.value === "c";
  $("bloque-creacion").hidden = !crea;
  // Con la tirada hecha, nombre y semilla se quedan: cambiarlos sería volver a tirar.
  $("crear-nombre").disabled = tirada !== null && crea;
  $("semilla").disabled = tirada !== null && crea;
}

function deslizador(id, etiqueta, min, max, paso, inicial, grupo) {
  const fila = el("label", "deslizador");
  const rango = el("input");
  rango.type = "range";
  rango.min = String(min);
  rango.max = String(max);
  rango.step = String(paso);
  rango.value = String(inicial);
  rango.dataset.id = id;
  rango.dataset.grupo = grupo;
  const valor = el("span", "valor", Number(inicial).toFixed(2));
  rango.addEventListener("input", () => {
    valor.textContent = Number(rango.value).toFixed(2);
    actualizarResto();
  });
  fila.append(el("span", "", etiqueta), rango, valor);
  return fila;
}

function prepararCreacion() {
  const c = creacionMundo;
  tirada = null;
  $("crear-nombre").disabled = false;
  $("semilla").disabled = false;
  $("crear-tirar").disabled = false;
  $("crear-dados").hidden = true;
  $("crear-dados").replaceChildren();
  $("crear-grupos").replaceChildren();
  $("crear-potenciales").replaceChildren();
  $("crear-caracter").replaceChildren();
  if (!c || !c.disponible) return;
  for (const g of c.grupos) {
    const sel = el("select");
    sel.dataset.grupo = g.id;
    sel.appendChild(new Option(g.obligatorio ? "elige…" : "ninguno", ""));
    for (const r of g.rasgos) sel.appendChild(new Option(r.label, r.id));
    const etiqueta = el("label", "grupo");
    etiqueta.append(`${g.label} `, sel);
    $("crear-grupos").appendChild(etiqueta);
  }
  $("crear-dificultad").replaceChildren(
    ...c.dificultades.map((d) => new Option(`${d.id} (${d.presupuesto.toFixed(2)})`, d.id)),
  );
  if (c.potenciales) {
    const p = c.potenciales;
    for (const r of p.rasgos) {
      $("crear-potenciales").appendChild(deslizador(r.id, r.label, p.min, p.max, p.step, p.min, "pot"));
    }
  }
  for (const r of c.caracter) {
    const inicial = Math.min(Math.max(0, r.min), r.max);
    $("crear-caracter").appendChild(deslizador(r.id, r.label, r.min, r.max, 0.01, inicial, "car"));
  }
  alCambiarModo();
}

function alCambiarModo() {
  const modo = modoElegido();
  const enTirada = modo === "roll";
  for (const r of document.querySelectorAll('#crear-potenciales input[type="range"]')) {
    r.disabled = enTirada;
  }
  $("bloque-dificultad").hidden = modo !== "points";
  $("crear-tirar").hidden = !enTirada;
  $("crear-dados").hidden = !enTirada || tirada === null;
  actualizarResto();
}

function sumaDePotenciales() {
  let suma = 0;
  for (const r of document.querySelectorAll('input[type="range"][data-grupo="pot"]')) {
    suma += Number(r.value);
  }
  return suma;
}

function actualizarResto() {
  const p = $("crear-resto");
  const dificultad = creacionMundo && creacionMundo.disponible
    ? creacionMundo.dificultades.find((d) => d.id === $("crear-dificultad").value)
    : undefined;
  if (modoElegido() !== "points" || dificultad === undefined) {
    p.hidden = true;
    return;
  }
  const resto = dificultad.presupuesto - sumaDePotenciales();
  p.hidden = false;
  p.textContent = `te quedan ${resto.toFixed(2)} de ${dificultad.presupuesto.toFixed(2)}`;
  p.classList.toggle("error", resto < -1e-9);
}

async function tirarDados() {
  const pedido = {
    mundo: $("mundo").value,
    nombre: $("crear-nombre").value.trim(),
    semilla: Number($("semilla").value),
  };
  const r = await api("/api/tirada", "POST", pedido);
  tirada = r.potenciales;
  const etiquetas = new Map(creacionMundo.potenciales.rasgos.map((x) => [x.id, x.label]));
  const dados = $("crear-dados");
  dados.replaceChildren();
  for (const [id, valor] of Object.entries(tirada)) {
    const d = el("div", "d6 pot", Number(valor).toFixed(2));
    d.title = etiquetas.get(id) || id;
    dados.appendChild(d);
  }
  dados.hidden = false;
  for (const rango of document.querySelectorAll('#crear-potenciales input[type="range"]')) {
    const v = tirada[rango.dataset.id];
    if (v !== undefined) {
      rango.value = String(v);
      rango.nextElementSibling.textContent = Number(v).toFixed(2);
    }
  }
  $("crear-tirar").disabled = true;
  alCambiarQuien();
  actualizarResto();
}

function valoresDe(grupo, sinCeros) {
  const salida = {};
  for (const r of document.querySelectorAll(`input[type="range"][data-grupo="${grupo}"]`)) {
    const v = Number(r.value);
    if (!(sinCeros && v === 0)) salida[r.dataset.id] = v;
  }
  return salida;
}

function elegirCreacion() {
  const modo = modoElegido();
  const crear = {
    name: $("crear-nombre").value.trim(),
    mode: modo,
    groups: [...document.querySelectorAll("#crear-grupos select")]
      .map((s) => s.value)
      .filter((v) => v !== ""),
    character: valoresDe("car", true),
  };
  if (modo === "points") crear.difficulty = $("crear-dificultad").value;
  if (modo !== "roll") crear.potentials = valoresDe("pot", false);
  return crear;
}

$("mundo").addEventListener("change", () => cargarPersonajes().catch(errorInicio));
$("guardado").addEventListener("change", () => cargarPersonajes().catch(errorInicio));

$("form-inicio").addEventListener("change", (ev) => {
  const t = ev.target;
  if (t.name === "quien") alCambiarQuien();
  if (t.name === "modo") alCambiarModo();
  if (t.id === "crear-dificultad") actualizarResto();
});

$("crear-tirar").addEventListener("click", () => tirarDados().catch(errorInicio));

$("form-inicio").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const datos = new FormData(ev.target);
  const quien = String(datos.get("quien") || "");
  const pedido = {
    mundo: $("mundo").value,
    guardado: $("guardado").value || "nuevo",
    semilla: Number($("semilla").value),
    modelo: datos.get("modelo") === "1",
  };
  if (quien === "c") pedido.crear = elegirCreacion();
  else if (quien.startsWith("f:")) pedido.ficha = quien.slice(2);
  else pedido.personaje = quien.slice(2);
  $("error-inicio").hidden = true;
  try {
    await api("/api/partida", "POST", pedido);
  } catch (err) {
    errorInicio(err);
    return;
  }
  empezarVista();
  conectar(false);
});

// -- la entrada -----------------------------------------------------------------

$("form-entrada").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const texto = $("texto").value.trim();
  if (!texto || !activa) return;
  $("texto").value = "";
  responder(texto);
});

relato.addEventListener("click", () => { if (completar) completar(); });

document.addEventListener("keydown", () => {
  if (completar && document.activeElement?.tagName !== "INPUT") completar();
});

$("vivir-boton").addEventListener("click", () => responder($("vivir-hasta").value));

$("parar").addEventListener("click", () => {
  api("/api/parar", "POST").catch((err) => aviso(err.message, "aviso error"));
});

$("nueva").addEventListener("click", () => {
  mostrarInicio();
  cargarMundos().catch(errorInicio);
});

// -- arranque -------------------------------------------------------------------

cargarMundos().catch(errorInicio);
conectar(true);
