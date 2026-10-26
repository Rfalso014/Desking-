// Barra lateral de la extensión. La extensión solo OBTIENE DATOS y manda órdenes («descargar», «cancelar», «eliminar»…):
// quien descarga es siempre el gestor web de este equipo.
// Todo el texto que viene de páginas externas se inserta como texto plano (textContent / nodos de texto).
import {
  ELEMENTOS_POR_DEFECTO, ESTADOS_ACTIVOS, MAX_TRAMOS, PUERTO_POR_DEFECTO, TEMAS, armarRecursos, atributoTema, claveRecurso, construirOpciones,
  elegirUrlParaVideo, esUrlWeb, formatearCodigo, formatearDuracion, formatearEta, formatearTamano, formatearTiempo, formatearVelocidad,
  fusionarRecursos, miniaturaSegura, nombreDeArchivo, nombreNavegador, nombreSitio, opcionesRecorte, ordenarRecursos, siguienteTema,
  textoTramos, validarTramos,
} from "./util.js";

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "clase") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "datos") Object.assign(e.dataset, v);
    else e[k] = v;
  }
  for (const h of hijos.flat()) if (h != null && h !== false) e.append(h);
  return e;
}

const SECCIONES = ["pagina", "cola", "ajustes"];
const estado = { tab: "pagina", busqueda: "", tareas: [], recursos: [], marcados: new Set(), temporizador: null, activa: null,
                 pagina: null, firmaRecursos: "", defecto: { ...ELEMENTOS_POR_DEFECTO }, tema: "auto", prefs: {}, grupos: [], medios: [] };

// --- Selector «qué descargar» (casillas combinables) --------------------------------------------------------------
function crearSelector(inicial, alCambiar = () => {}) {
  const v = { ...ELEMENTOS_POR_DEFECTO, ...inicial };
  const pastilla = (clave, texto, ayuda) => {
    const cb = el("input", { type: "checkbox", checked: !!v[clave] });
    cb.addEventListener("change", () => { v[clave] = cb.checked; actualizar(); alCambiar({ ...v }); });
    return el("label", { clase: "pastilla", title: ayuda }, cb, el("span", {}, texto));
  };
  const select = (clave, opciones) => {
    const s = el("select", {}, ...opciones.map(([val, txt]) => el("option", { value: val, textContent: txt })));
    s.value = v[clave];
    s.addEventListener("change", () => { v[clave] = s.value; alCambiar({ ...v }); });
    return s;
  };
  const campoCalidad = el("label", { clase: "campo" }, "Calidad máxima", select("altura", [["", "La de los ajustes"], ["mejor", "La mejor"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"]]));
  const campoAudio = el("label", { clase: "campo" }, "Formato de audio", select("formatoAudio", [["mp3", "MP3"], ["m4a", "M4A"], ["flac", "FLAC"], ["ogg", "OGG"], ["opus", "OPUS"], ["wav", "WAV"], ["original", "Pista original"]]));
  const entradaIdiomas = el("input", { type: "text", value: v.idiomas, placeholder: "es,en", maxLength: 40 });
  entradaIdiomas.addEventListener("input", () => { v.idiomas = entradaIdiomas.value; alCambiar({ ...v }); });
  const campoIdiomas = el("label", { clase: "campo" }, "Idiomas de subtítulos", entradaIdiomas);
  const pastillaEdicion = pastilla("editable", "Para edición", "MP4 con H.264 + AAC: lo abre Premiere, DaVinci, CapCut…");
  const nodo = el("div", { clase: "selector" },
    el("div", { clase: "fila" }, pastilla("video", "Video", "El video con su audio"), pastillaEdicion, pastilla("audio", "Audio", "Solo el audio"),
      pastilla("subtitulos", "Subtítulos", "Los subtítulos en los idiomas que escribas"), pastilla("portada", "Portada", "La imagen de portada")),
    el("div", { clase: "campos" }, campoCalidad, campoAudio, campoIdiomas));
  function actualizar() {
    campoCalidad.hidden = pastillaEdicion.hidden = !v.video; campoAudio.hidden = !v.audio; campoIdiomas.hidden = !v.subtitulos;
  }
  actualizar();
  return { nodo, leer: () => ({ ...v, carpeta: "" }) };
}

let selPagina = null;
/** Opciones (1 o 2 descargas) según lo marcado; si algo está mal avisa y devuelve null. */
function opcionesDe(valores) {
  try {
    return construirOpciones(valores);
  } catch (e) {
    mostrarAviso(`${e.mensaje || "Revisa lo que marcaste."} ${e.solucion || ""}`, true);
    return null;
  }
}

// --- Comunicación con el gestor (a través del service worker) -----------------------------------
async function gestor(accion, datos = {}) {
  const r = await chrome.runtime.sendMessage({ tipo: "gestor", accion, datos });
  if (r && !r.ok && r.error && r.error.codigo === "no_vinculado" && accion !== "emparejar") mostrarVista("vincular");
  if (r && !r.ok && r.error && r.error.codigo === "comunicacion") iniciar();
  return r || { ok: false, error: { mensaje: "Sin respuesta del navegador." } };
}

const textoError = (e) => [e && e.mensaje, e && e.solucion].filter(Boolean).join(" ");

function mostrarAviso(texto, error = false) {
  $("aviso").hidden = !texto;
  $("aviso").textContent = texto || "";
  $("aviso").classList.toggle("error", !!error);
  if (texto && !error) setTimeout(() => { if ($("aviso").textContent === texto) mostrarAviso(""); }, 4000);
}

/** Añade con las opciones elegidas en el panel. Si ya estaba en la lista, pregunta si repetirlo. */
async function anadir(url, conjuntos, pagina) {
  if (!conjuntos) return false;
  let r = await chrome.runtime.sendMessage({ tipo: "anadir-panel", url, conjuntos, pagina });
  if (r && !r.ok && r.repetidas) {
    const texto = [r.error && r.error.mensaje, r.error && r.error.causa].filter(Boolean).join("\n");
    if (!confirm(`${texto}\n\n¿Quieres descargarlo otra vez?`)) return false;
    r = await chrome.runtime.sendMessage({ tipo: "anadir-panel", url, conjuntos, pagina, repetidas: r.repetidas });
  }
  if (!r || !r.ok) { mostrarAviso(textoError(r && r.error) || "No se pudo añadir.", true); return false; }
  mostrarAviso(r.datos && r.datos.modo === "grupo" ? `Añadido al grupo «${r.datos.grupo}».` : "Descarga iniciada.");
  return true;
}

const paginaActual = () => (estado.activa ? { id: estado.activa.id, url: estado.activa.url, title: estado.activa.title } : null);

// --- Tema (día / noche / como Windows) -----------------------------------------------------------
const NOMBRE_TEMA = { auto: "automático", dia: "claro", noche: "oscuro" };
function aplicarTema(t) {
  estado.tema = TEMAS.includes(t) ? t : "auto";
  const a = atributoTema(estado.tema);
  if (a) document.documentElement.dataset.theme = a; else delete document.documentElement.dataset.theme;
  $("btn-tema").title = `Tema: ${NOMBRE_TEMA[estado.tema]}`;
  $("btn-tema").querySelector("use").setAttribute("href", `#i-${estado.tema}`);
  $("aj-tema").value = estado.tema;
}
function guardarTema(t) { aplicarTema(t); chrome.storage.local.set({ tema: estado.tema }); }
$("btn-tema").addEventListener("click", () => guardarTema(siguienteTema(estado.tema)));
$("aj-tema").addEventListener("change", (e) => guardarTema(e.target.value));

// --- Vistas ----------------------------------------------------------------------------------
function ponerEstadoConexion(clase, texto) {
  $("estado-conexion").className = `punto ${clase}`;
  $("estado-conexion").lastElementChild.textContent = texto;
}

function mostrarVista(cual) {
  document.body.dataset.vista = cual;
  $("vista-conexion").hidden = cual !== "conexion";
  $("vista-vincular").hidden = cual !== "vincular";
  $("vista-principal").hidden = cual !== "principal";
  $("barra-modo").hidden = $("pestanas").hidden = cual !== "principal";
  clearInterval(estado.temporizador);
  if (cual === "principal") estado.temporizador = setInterval(latido, 1500);
  if (cual === "vincular") { ponerEstadoConexion("espera", "Sin vincular"); setTimeout(() => $("codigo").focus(), 50); }
}

let iniciando = false;
async function iniciar() {
  if (iniciando) return;
  iniciando = true;
  try {
    ponerEstadoConexion("espera", "Conectando…");
    const r = await chrome.runtime.sendMessage({ tipo: "gestor", accion: "ping", datos: {} });
    if (!r || !r.ok) {
      ponerEstadoConexion("mal", "Apagado");
      $("conexion-titulo").textContent = (r && r.error && r.error.mensaje) || "No se pudo conectar con el gestor";
      $("conexion-texto").textContent = (r && r.error && r.error.solucion) || "";
      return mostrarVista("conexion");
    }
    if (!r.datos.vinculado) return mostrarVista("vincular");
    ponerEstadoConexion("ok", "Conectado");
    mostrarVista("principal");
    await cargarAjustes();
    await cargarModo();
    cambiarPestana(estado.tab);
  } finally {
    iniciando = false;
  }
}

// --- Vinculación -------------------------------------------------------------------------------
$("codigo").addEventListener("input", (e) => {
  e.target.value = formatearCodigo(e.target.value);
  $("btn-vincular").disabled = e.target.value.length !== 9;
});
$("codigo").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("btn-vincular").disabled) vincular(); });
$("btn-vincular").addEventListener("click", vincular);
$("btn-reintentar-conexion").addEventListener("click", iniciar);

async function vincular() {
  $("btn-vincular").disabled = true;
  const r = await gestor("emparejar", { codigo: $("codigo").value, nombre: nombreNavegador(navigator.userAgent) });
  if (!r.ok) { mostrarAviso(textoError(r.error), true); $("btn-vincular").disabled = false; return; }
  $("codigo").value = "";
  iniciar();
}

async function abrirWeb(seccion = "") {
  const { puerto } = await chrome.storage.local.get("puerto");
  chrome.tabs.create({ url: `http://127.0.0.1:${puerto || PUERTO_POR_DEFECTO}/${seccion ? `#${seccion}` : ""}` });
}
$("btn-web").addEventListener("click", () => abrirWeb());
$("btn-abrir-web").addEventListener("click", () => abrirWeb());
$("btn-abrir-codigo").addEventListener("click", () => abrirWeb("ajustes"));

// --- Modo de añadir (lo guarda el gestor: es el mismo en la página y en la extensión) --------------------------
function fijarSegmentos(valor) {
  for (const b of $("seg-cuando").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.valor === valor));
}

function pintarModo() {
  const p = estado.prefs;
  fijarSegmentos(p.modo_anadir);
  $("sel-grupo").hidden = p.modo_anadir !== "grupo";
  $("chk-carpeta").checked = p.carpeta_propia !== false;
  $("sel-grupo").replaceChildren(...estado.grupos.map((g) => el("option", { value: g.nombre, textContent: g.esperando ? `${g.nombre} (${g.esperando})` : g.nombre })),
    el("option", { value: "__nuevo", textContent: "+ Grupo nuevo…" }));
  $("sel-grupo").value = p.grupo_activo;
  $("btn-descargar-pagina").textContent = p.modo_anadir === "grupo" ? `Añadir al grupo «${p.grupo_activo}»` : "Descargar esta página";
}

async function cargarModo() {
  const [p, g] = await Promise.all([gestor("preferencias"), gestor("grupos")]);
  if (p.ok) estado.prefs = p.datos;
  if (g.ok) estado.grupos = g.datos.grupos;
  pintarModo();
}

async function cambiarPreferencia(cambios) {
  const r = await gestor("preferencias", { cambios });
  if (!r.ok) { mostrarAviso(textoError(r.error), true); return; }
  estado.prefs = r.datos;
  pintarModo();
}

$("seg-cuando").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b) cambiarPreferencia({ modo_anadir: b.dataset.valor });
});
$("chk-carpeta").addEventListener("change", (e) => cambiarPreferencia({ carpeta_propia: e.target.checked }));
$("sel-grupo").addEventListener("change", async (e) => {
  if (e.target.value !== "__nuevo") return cambiarPreferencia({ grupo_activo: e.target.value });
  const nombre = (prompt("Nombre del grupo nuevo:") || "").trim().slice(0, 60);
  if (!nombre) return pintarModo();
  const r = await gestor("grupo_crear", { nombre });
  if (!r.ok) { mostrarAviso(textoError(r.error), true); return pintarModo(); }
  await cargarModo();
});

// --- Pestañas ---------------------------------------------------------------------------------------
document.querySelectorAll("[data-pestana]").forEach((b) => b.addEventListener("click", () => cambiarPestana(b.dataset.pestana)));
function cambiarPestana(nombre) {
  estado.tab = SECCIONES.includes(nombre) ? nombre : "pagina";
  document.querySelectorAll("[data-pestana]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pestana === estado.tab)));
  for (const n of SECCIONES) $(`pestana-${n}`).hidden = n !== estado.tab;
  if (estado.tab === "cola") refrescarCola();
  if (estado.tab === "pagina") { buscarRecursos(); refrescarRecorte(true); }
  if (estado.tab === "ajustes") refrescarActualizacion();
}

// Cada 1,5 s: la cola (y la insignia); en «Esta página», el video (recortar) y los enlaces directos.
let pulsos = 0;
function latido() {
  refrescarCola();
  if (estado.tab === "pagina") {
    if ($("plegable-recortar").open) refrescarRecorte();
    if (++pulsos % 2 === 0) refrescarMedios();
    if (pulsos % 4 === 0 && document.visibilityState === "visible") buscarRecursos();
  }
  if (pulsos % 20 === 0) cargarModo();          // por si se cambió desde la página web
}

// --- Esta página ---------------------------------------------------------------------------------------
async function pestanaActiva() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

/** Pide al content script lo que hay en la pestaña. Si la pestaña se abrió antes de instalar la extensión, lo inyecta. */
async function leerPestana(tab) {
  if (!tab || tab.id == null) return null;
  const pedir = () => chrome.tabs.sendMessage(tab.id, { tipo: "recursos" }, { frameId: 0 });
  try {
    const r = await pedir();
    if (r) return r;
  } catch { /* sin content script */ }
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    return (await pedir()) || null;
  } catch {
    return null;
  }
}

async function cargarPagina() {
  const tab = await pestanaActiva();
  estado.activa = tab;
  const d = await leerPestana(tab);
  estado.pagina = d && esUrlWeb(d.url) ? d : (tab && esUrlWeb(tab.url) ? { url: tab.url, titulo: tab.title } : null);
  const web = !!estado.pagina;
  $("pagina-titulo").textContent = web ? (estado.pagina.titulo || estado.pagina.url) : "No se puede leer esta pestaña";
  $("pagina-sitio").textContent = web ? nombreSitio(estado.pagina.url) : "Abre una página web (http o https).";
  $("btn-descargar-pagina").disabled = !web;
  return d && esUrlWeb(d.url) ? d : null;
}

const GLIFO = { video: "▶", audio: "♪", imagen: "▣", enlace: "↗", hls: "▶", dash: "▶" };
const claveGuardado = () => `recursos:${estado.activa && estado.activa.id}`;

// Lo encontrado se guarda por pestaña (mientras el navegador esté abierto): al recargar la página no se pierde.
async function buscarRecursos() {
  const d = await cargarPagina();
  const clave = claveGuardado();
  const previos = estado.activa ? ((await chrome.storage.session.get(clave))[clave] || []) : [];
  estado.recursos = ordenarRecursos(fusionarRecursos(previos, armarRecursos(d)))
    .filter((r) => !estado.pagina || r.url !== estado.pagina.url);          // la página ya tiene su botón
  if (estado.activa) chrome.storage.session.set({ [clave]: estado.recursos });
  if (estado.verImagenes === undefined) estado.verImagenes = false;
  const firma = JSON.stringify(estado.recursos.map((r) => [r.url, r.nombre, r.anterior]));
  $("recursos-nota").textContent = estado.recursos.length
    ? "Otros videos, audios y enlaces de esta página. Marca los que quieras."
    : "No se encontró nada más en esta página.";
  if (firma !== estado.firmaRecursos) { estado.firmaRecursos = firma; pintarRecursos(); }
  refrescarMedios();
}

chrome.tabs.onActivated.addListener(() => {
  estado.verImagenes = undefined; estado.marcados.clear();
  if (estado.tab === "pagina") { buscarRecursos(); refrescarRecorte(true); }
});
chrome.tabs.onUpdated.addListener((tabId, cambio) => {
  if (estado.activa && tabId === estado.activa.id && cambio.status === "complete" && estado.tab === "pagina") buscarRecursos();
});

const visiblesRecursos = () => estado.recursos.filter((r) => estado.verImagenes || r.tipo !== "imagen");
const marcadosVisibles = () => visiblesRecursos().filter((r) => estado.marcados.has(claveRecurso(r)));

function pintarRecursos() {
  const visibles = visiblesRecursos();
  $("recursos").replaceChildren(...visibles.map((r) => {
    const k = claveRecurso(r);
    const miniatura = el("div", { clase: "miniatura" }, GLIFO[r.tipo] || "↗");
    if (r.tipo === "imagen" && miniaturaSegura(r.url)) miniatura.replaceChildren(el("img", { src: r.url, alt: "", loading: "lazy", referrerPolicy: "no-referrer" }));
    return el("li", { clase: `item${r.anterior ? " anterior" : ""}` },
      el("label", {}, el("input", { type: "checkbox", checked: estado.marcados.has(k),
        onchange: (e) => { e.target.checked ? estado.marcados.add(k) : estado.marcados.delete(k); actualizarBarraRecursos(); } }),
      miniatura,
      el("div", { clase: "cuerpo" }, el("div", { clase: "titulo" }, r.nombre || nombreDeArchivo(r.url)),
        el("div", { clase: "meta" }, `${r.tipo} · ${nombreSitio(r.url)}${r.anterior ? " · de antes" : ""}`))));
  }));
  const imagenes = estado.recursos.filter((r) => r.tipo === "imagen").length;
  $("btn-imagenes").hidden = !imagenes;
  $("btn-imagenes").textContent = estado.verImagenes ? "Ocultar imágenes" : `Mostrar imágenes (${imagenes})`;
  $("contador-recursos").hidden = !visibles.length;
  $("contador-recursos").textContent = visibles.length;
  actualizarBarraRecursos();
}

function actualizarBarraRecursos() {
  const visibles = visiblesRecursos();
  $("barra-recursos").hidden = !visibles.length;
  const n = marcadosVisibles().length;
  $("btn-descargar-sel").disabled = !n;
  $("btn-descargar-sel").textContent = n ? `Descargar (${n})` : "Descargar";
  $("btn-marcar").textContent = n && n === visibles.length ? "Quitar marcas" : "Marcar todos";
  $("btn-olvidar").hidden = !estado.recursos.some((r) => r.anterior);
}

$("btn-buscar").addEventListener("click", buscarRecursos);
$("btn-imagenes").addEventListener("click", () => {
  estado.verImagenes = !estado.verImagenes;
  if (!estado.verImagenes) estado.recursos.forEach((r) => { if (r.tipo === "imagen") estado.marcados.delete(claveRecurso(r)); });
  pintarRecursos();
});
$("btn-marcar").addEventListener("click", () => {
  const visibles = visiblesRecursos();
  const todos = visibles.every((r) => estado.marcados.has(claveRecurso(r)));
  visibles.forEach((r) => (todos ? estado.marcados.delete(claveRecurso(r)) : estado.marcados.add(claveRecurso(r))));
  pintarRecursos();
});
$("btn-olvidar").addEventListener("click", async () => {
  estado.recursos = estado.recursos.filter((r) => !r.anterior);
  await chrome.storage.session.set({ [claveGuardado()]: estado.recursos });
  estado.firmaRecursos = "";
  buscarRecursos();
});

$("btn-descargar-sel").addEventListener("click", async () => {
  const conjuntos = opcionesDe(selPagina.leer());
  if (!conjuntos) return;
  let hechos = 0;
  for (const r of marcadosVisibles()) if (await anadir(r.url, conjuntos, paginaActual())) hechos++;
  if (hechos) { estado.marcados.clear(); pintarRecursos(); }
});

$("btn-descargar-pagina").addEventListener("click", async () => {
  if (!estado.pagina) return;
  $("btn-descargar-pagina").disabled = true;
  await anadir(estado.pagina.url, opcionesDe(selPagina.leer()), paginaActual());
  $("btn-descargar-pagina").disabled = false;
});

// --- Enlaces directos vistos en la red (los apunta el service worker) ---------------------------------------------
async function refrescarMedios() {
  const tab = estado.activa;
  estado.medios = tab ? (await chrome.runtime.sendMessage({ tipo: "medios", tabId: tab.id })) || [] : [];
  $("contador-medios").hidden = !estado.medios.length;
  $("contador-medios").textContent = estado.medios.length;
  $("nota-medios").hidden = !estado.medios.length;
  $("nota-medios").textContent = `El reproductor cargó ${estado.medios.length} ${estado.medios.length === 1 ? "enlace directo" : "enlaces directos"}: si la página no se puede analizar, el gestor los usa.`;
  const firma = estado.medios.map((m) => m.url).join("|");
  if (firma === estado.firmaMedios) return;
  estado.firmaMedios = firma;
  $("medios").replaceChildren(...(estado.medios.length ? estado.medios.map((m) => el("li", { clase: "item" },
    el("div", { clase: "miniatura" }, GLIFO[m.tipo] || "▶"),
    el("div", { clase: "cuerpo" },
      el("div", { clase: "titulo" }, nombreDeArchivo(m.url)),
      el("div", { clase: "meta" }, [{ hls: "Lista HLS (m3u8)", dash: "Lista DASH (mpd)", video: "Archivo de video", audio: "Archivo de audio" }[m.tipo],
        m.tamano ? formatearTamano(m.tamano) : "", nombreSitio(m.url)].filter(Boolean).join(" · ")),
      el("div", { clase: "acciones" }, el("button", { clase: "sec", textContent: "Descargar este",
        onclick: () => {
          const conjuntos = opcionesDe(selPagina.leer());
          if (conjuntos) anadir(m.url, conjuntos.map((o) => ({ ...o, titulo_pagina: (estado.activa && estado.activa.title || "").slice(0, 300) || undefined })), paginaActual());
        } })))))
    : [el("li", { clase: "vacio" }, "Todavía nada. Reproduce el video unos segundos.")]));
}

// --- Recortar: descargar solo unos minutos ------------------------------------------------------------------------------
// El video de la pestaña lo lee content.js (tiempo actual y duración); aquí se escriben los trozos.
estado.recorte = { filas: [{ desde: "", hasta: "" }], video: null, pestana: null };

async function leerVideo() {
  const tab = await pestanaActiva();
  if (!tab || tab.id == null) return null;
  try {
    return (await chrome.tabs.sendMessage(tab.id, { tipo: "video-estado" }, { frameId: 0 })) || null;
  } catch {
    return null;
  }
}

async function refrescarRecorte(rehacer = false) {
  const tab = await pestanaActiva();
  const v = await leerVideo();
  const rc = estado.recorte;
  if (tab && rc.pestana !== tab.id) { rc.pestana = tab.id; rehacer = true; rc.filas = [{ desde: "", hasta: "" }]; }
  rc.video = v;
  $("rc-meta").textContent = !v ? "Abre la página del video (si ya está abierta, recárgala)."
    : !v.hayVideo ? "No hay ningún video en esta pestaña."
    : v.enVivo ? "Es un directo: no se puede recortar mientras se emite."
    : `Dura ${formatearTiempo(v.duracion)} · ahora en ${formatearTiempo(v.actual)}`;
  if (rehacer) pintarFilasRecorte();
  pintarLineaRecorte();
}

function pintarFilasRecorte() {
  const rc = estado.recorte;
  $("rc-tramos").replaceChildren(...rc.filas.map((f, i) => {
    const campo = (clave, rotulo) => {
      const entrada = el("input", { type: "text", value: f[clave], placeholder: clave === "desde" ? "1:20" : "3:45", spellcheck: false,
        oninput: (e) => { f[clave] = e.target.value; pintarLineaRecorte(); } });
      const marcar = el("button", { textContent: "Ahora", title: "Usa el segundo en el que va el video",
        onclick: () => { if (rc.video && rc.video.hayVideo) { f[clave] = formatearTiempo(rc.video.actual); entrada.value = f[clave]; pintarLineaRecorte(); } } });
      return el("label", {}, rotulo, el("div", { clase: "con-boton" }, entrada, marcar));
    };
    const ver = el("button", { clase: "enlace", textContent: "▶ Ver", title: "Reproduce este trozo en la pestaña", onclick: () => verTrozo(i) });
    const quitar = el("button", { clase: "enlace", textContent: "Quitar", hidden: rc.filas.length === 1,
      onclick: () => { rc.filas.splice(i, 1); pintarFilasRecorte(); pintarLineaRecorte(); } });
    return el("li", { clase: "tramo-fila" }, el("div", { clase: "cab-tramo" }, `Trozo ${i + 1}`, el("span", {}, ver, quitar)),
      el("div", { clase: "tiempos" }, campo("desde", "Desde"), campo("hasta", "Hasta")));
  }));
  $("rc-anadir").hidden = rc.filas.length >= MAX_TRAMOS;
}

function pintarLineaRecorte() {
  const rc = estado.recorte, v = rc.video, dur = v && v.hayVideo && !v.enVivo ? v.duracion : null;
  const r = validarTramos(rc.filas, dur);
  const escritas = rc.filas.some((f) => f.desde.trim() || f.hasta.trim());
  $("rc-error").hidden = !escritas || !r.error;
  $("rc-error").textContent = r.error || "";
  const total = r.tramos ? r.tramos.reduce((s, [a, b]) => s + b - a, 0) : 0;
  $("rc-resumen").textContent = r.tramos ? `${r.tramos.length} ${r.tramos.length === 1 ? "trozo" : "trozos"} · ${formatearTiempo(total)} en total` : "";
  $("rc-descargar").disabled = !r.tramos || !dur;
  const hijos = [];
  if (dur) {
    for (const [a, b] of r.tramos || []) {
      const seg = el("div", { clase: "seg" });
      seg.style.left = `${(a / dur) * 100}%`; seg.style.width = `${((b - a) / dur) * 100}%`;
      hijos.push(seg);
    }
    const ahora = el("div", { clase: "ahora" });
    ahora.style.left = `${(v.actual / dur) * 100}%`;
    hijos.push(ahora);
  }
  $("rc-linea").replaceChildren(...hijos);
}

async function verTrozo(i) {
  const r = validarTramos([estado.recorte.filas[i]], estado.recorte.video && estado.recorte.video.duracion);
  if (!r.tramos) { $("rc-error").hidden = false; $("rc-error").textContent = r.error; return; }
  const tab = await pestanaActiva();
  try { await chrome.tabs.sendMessage(tab.id, { tipo: "video-ir", segundo: r.tramos[0][0], hasta: r.tramos[0][1] }, { frameId: 0 }); } catch { /* sin video */ }
}

$("plegable-recortar").addEventListener("toggle", () => { if ($("plegable-recortar").open) refrescarRecorte(true); });
$("rc-anadir").addEventListener("click", () => {
  const rc = estado.recorte;
  if (rc.filas.length < MAX_TRAMOS) rc.filas.push({ desde: "", hasta: "" });
  pintarFilasRecorte(); pintarLineaRecorte();
});
$("rc-descargar").addEventListener("click", async () => {
  const rc = estado.recorte, v = rc.video;
  const r = validarTramos(rc.filas, v && v.duracion);
  if (!r.tramos || !v || !v.hayVideo) return;
  const url = elegirUrlParaVideo(v.candidatas) || v.url;
  let conjuntos;
  try {
    conjuntos = opcionesRecorte(selPagina.leer(), r.tramos, { exacto: $("rc-exacto").checked, audio: $("rc-audio").checked });
  } catch (e) {
    mostrarAviso(`${e.mensaje || "Revisa «qué descargar»."} ${e.solucion || ""}`, true);
    return;
  }
  $("rc-descargar").disabled = true;
  const ok = await anadir(url, conjuntos, paginaActual());
  $("rc-descargar").disabled = false;
  if (ok) { rc.filas = [{ desde: "", hasta: "" }]; pintarFilasRecorte(); pintarLineaRecorte(); }
});

// --- Descargas ----------------------------------------------------------------------------------------------------
const ETIQUETA = { detectado: "En el grupo", pendiente: "En espera", analizando: "Analizando", descargando: "Descargando",
  procesando: "Procesando", completado: "Terminada", cancelado: "Cancelada", error: "Error" };

async function accionTarea(accion, id) {
  const r = await gestor(accion, { id });
  if (!r.ok) mostrarAviso(textoError(r.error), true);
  await refrescarCola();
}

function pintarTarea(t) {
  const mini = miniaturaSegura(t.miniatura);
  const activa = ESTADOS_ACTIVOS.includes(t.estado);
  const detalles = [];
  if (t.estado === "descargando") detalles.push(t.progreso != null ? `${Math.round(t.progreso)} %` : "", formatearVelocidad(t.velocidad), t.eta != null ? `quedan ${formatearEta(t.eta)}` : "");
  const cuerpo = [
    el("div", { clase: "titulo" }, t.titulo || t.url),
    el("div", { clase: "fila-estado" }, el("span", { clase: `estado e-${t.estado}` }, ETIQUETA[t.estado] || t.estado),
      ...[t.sitio || nombreSitio(t.url), formatearDuracion(t.duracion), textoTramos(t.opciones && t.opciones.tramos), ...detalles].filter(Boolean)
        .map((x) => el("span", {}, x)),
      t.grupo ? el("span", { clase: "chip acento" }, t.grupo) : null),
  ];
  if (activa) {
    const barra = el("div", { clase: "barra" }, el("i"));
    barra.firstChild.style.width = `${Math.max(2, Math.min(100, t.progreso || 0))}%`;
    cuerpo.push(barra);
  }
  if (t.error) cuerpo.push(el("div", { clase: "error-caja" }, el("b", {}, t.error.mensaje), t.error.solucion ? ` ${t.error.solucion}` : ""));
  else if (!activa && t.notas && t.notas.length) cuerpo.push(el("div", { clase: "meta" }, t.notas[t.notas.length - 1]));
  const botones = [];
  const boton = (accion, texto, clase = "") => el("button", { clase, textContent: texto, onclick: () => accionTarea(accion, t.id) });
  if (t.estado === "detectado") botones.push(boton("iniciar", "Descargar", "primario"));
  if (t.estado === "completado" && t.carpeta_final) botones.push(boton("abrir_carpeta", "Abrir carpeta", "sec"));
  if (["error", "cancelado"].includes(t.estado)) botones.push(boton("reintentar", "Reintentar", "sec"));
  if (activa) botones.push(boton("cancelar", "Cancelar"));
  botones.push(boton("eliminar", activa ? "Quitar" : "Quitar de la lista", "enlace"));
  cuerpo.push(el("div", { clase: "acciones" }, botones));
  return el("li", { clase: "item" },
    el("div", { clase: "miniatura" }, mini ? el("img", { src: mini, referrerPolicy: "no-referrer", alt: "", loading: "lazy" }) : "▶"),
    el("div", { clase: "cuerpo" }, ...cuerpo));
}

const GRUPOS_COLA = [
  { titulo: "En curso", estados: ["descargando", "procesando", "analizando", "pendiente"] },
  { titulo: "Esperando en grupos", estados: ["detectado"], grupos: true },
  { titulo: "Con error o canceladas", estados: ["error", "cancelado"] },
  { titulo: "Terminadas", estados: ["completado"] },
];

async function refrescarCola() {
  const r = await gestor("listar", { limite: 100 });
  if (!r.ok) { $("cola").replaceChildren(el("p", { clase: "vacio" }, "No se puede mostrar sin conexión con el gestor.")); return; }
  estado.tareas = r.datos.tareas;
  const activas = estado.tareas.filter((t) => ESTADOS_ACTIVOS.includes(t.estado));
  const enGrupo = estado.tareas.filter((t) => t.estado === "detectado");
  $("contador-cola").hidden = !(activas.length + enGrupo.length);
  $("contador-cola").textContent = activas.length + enGrupo.length;
  chrome.action.setBadgeBackgroundColor({ color: activas.length ? "#2f5f8a" : "#8a5a00" });
  chrome.action.setBadgeText({ text: activas.length ? String(activas.length) : enGrupo.length ? String(enGrupo.length) : "" });
  if (estado.tab !== "cola") return;
  const texto = estado.busqueda.trim().toLowerCase();
  const visibles = estado.tareas.filter((t) => !texto || `${t.titulo || ""} ${t.url} ${t.sitio || ""} ${t.grupo || ""}`.toLowerCase().includes(texto));
  const bloques = [];
  for (const g of GRUPOS_COLA) {
    const ts = visibles.filter((t) => g.estados.includes(t.estado));
    if (!ts.length) continue;
    if (g.grupos) {                                  // uno por grupo, con su botón «Descargar grupo»
      for (const nombre of [...new Set(ts.map((t) => t.grupo || "Sin grupo"))]) {
        const delGrupo = ts.filter((t) => (t.grupo || "Sin grupo") === nombre);
        bloques.push(el("div", { clase: "seccion-titulo" }, `Grupo «${nombre}»`, el("span", { clase: "insignia" }, String(delGrupo.length)), el("span", { clase: "espacio" }),
          el("button", { clase: "primario", textContent: "Descargar grupo", onclick: async () => {
            const x = await gestor("grupo_iniciar", { nombre });
            if (!x.ok) mostrarAviso(textoError(x.error), true); else mostrarAviso(`Empezaron ${x.datos.iniciadas} descargas.`);
            refrescarCola();
          } })), el("ul", { clase: "lista" }, delGrupo.map(pintarTarea)));
      }
      continue;
    }
    bloques.push(el("div", { clase: "seccion-titulo" }, g.titulo, el("span", { clase: "insignia" }, String(ts.length))), el("ul", { clase: "lista" }, ts.map(pintarTarea)));
  }
  $("cola").replaceChildren(...(bloques.length ? bloques
    : [el("p", { clase: "vacio" }, estado.tareas.length ? "Nada coincide con la búsqueda." : "No hay descargas. Usa «＋» sobre un video o «Descargar esta página».")]));
}

$("busqueda").addEventListener("input", (e) => { estado.busqueda = e.target.value; refrescarCola(); });
$("btn-cancelar-todas").addEventListener("click", async () => {
  if (!estado.tareas.some((t) => ESTADOS_ACTIVOS.includes(t.estado))) return;
  if (!confirm("¿Cancelar todas las descargas en curso y en espera?")) return;
  await gestor("cancelar_todas");
  refrescarCola();
});
$("btn-limpiar").addEventListener("click", async () => { await gestor("limpiar"); refrescarCola(); });

// --- Ajustes -------------------------------------------------------------------------------------------------------
function pintarSelectorAjustes() {
  const sel = crearSelector(estado.defecto, (valores) => {
    estado.defecto = valores; chrome.storage.local.set({ elementos: valores });
    selPagina = crearSelector(estado.defecto); $("selector-pagina").replaceChildren(selPagina.nodo);
  });
  $("selector-ajustes").replaceChildren(sel.nodo);
}

async function cargarAjustes() {
  const a = await chrome.storage.local.get(["botonFlotante", "elementos", "usarSesion", "puerto"]);
  $("aj-boton").checked = a.botonFlotante !== false;
  $("aj-sesion").checked = a.usarSesion !== false;
  $("aj-puerto").value = a.puerto || PUERTO_POR_DEFECTO;
  estado.defecto = { ...ELEMENTOS_POR_DEFECTO, ...(a.elementos || {}) };
  selPagina = crearSelector(estado.defecto);
  $("selector-pagina").replaceChildren(selPagina.nodo);
  pintarSelectorAjustes();
  $("aj-vinculo").textContent = `Vinculada como «${nombreNavegador(navigator.userAgent)}». Puedes revocarla desde la página del gestor o aquí.`;
}

$("aj-boton").addEventListener("change", (e) => chrome.storage.local.set({ botonFlotante: e.target.checked }));
$("aj-sesion").addEventListener("change", (e) => chrome.storage.local.set({ usarSesion: e.target.checked }));
$("aj-puerto").addEventListener("change", async (e) => {
  const p = Number(e.target.value);
  if (Number.isInteger(p) && p > 0 && p < 65536) { await chrome.storage.local.set({ puerto: p }); iniciar(); }
});
$("btn-desvincular").addEventListener("click", async () => {
  if (!confirm("¿Desvincular esta extensión del gestor?")) return;
  const r = await gestor("desvincular");
  if (!r.ok) { mostrarAviso(textoError(r.error), true); return; }
  await chrome.runtime.sendMessage({ tipo: "olvidar-token" });
  iniciar();
});

// --- Actualizaciones (las hace el gestor; la extensión se recarga sola al terminar) ------------------------------------
const NOMBRES_VERSION = [["app", "Gestor"], ["extension", "Extensión"], ["yt-dlp", "yt-dlp"], ["yt-dlp-ejs", "Solucionador JS"],
                         ["gallery-dl", "gallery-dl"], ["deno", "Deno"], ["ffmpeg", "FFmpeg"]];

async function refrescarActualizacion(buscar = false) {
  if (["actualizando", "listo"].includes(estado.faseAct)) gestor("ping");
  const r = await gestor("actualizacion", buscar ? { buscar: true } : {});
  if (!r.ok) { $("act-estado").textContent = textoError(r.error) || "El gestor no respondió."; return; }
  pintarActualizacion(r.datos);
}

function pintarActualizacion(e) {
  estado.faseAct = e.fase;
  const v = { ...e.versiones, extension: chrome.runtime.getManifest().version };
  $("act-versiones").replaceChildren(...NOMBRES_VERSION.filter(([k]) => v[k]).map(([k, t]) => el("li", {}, el("span", {}, t), el("b", {}, String(v[k])))));
  const texto = [e.mensaje, ...(e.pendientes || []).map((p) => `${p.nombre}: ${p.actual} → ${p.nueva}`)];
  if (e.fase === "listo") texto.push(...(e.hechos || []).map((h) => `✓ ${h}`));
  texto.push(...(e.avisos || []).map((a) => `⚠ ${a}`));
  $("act-estado").textContent = texto.filter(Boolean).join(" · ") || "Pulsa «Buscar» para ver si hay algo nuevo.";
  const ocupado = e.fase === "buscando" || e.fase === "actualizando";
  $("btn-actualizar").disabled = $("btn-buscar-act").disabled = ocupado;
  $("btn-actualizar").hidden = !(e.pendientes || []).length && e.fase !== "actualizando";
  if (typeof e.automatico === "boolean") $("act-auto").checked = e.automatico;
}

$("act-auto").addEventListener("change", async (e) => {
  const r = await gestor("actualizacion", { automatico: e.target.checked });
  if (r.ok) pintarActualizacion(r.datos); else mostrarAviso(textoError(r.error), true);
});
$("btn-buscar-act").addEventListener("click", () => { refrescarActualizacion(true); setTimeout(() => refrescarActualizacion(), 4000); });
$("btn-actualizar").addEventListener("click", async () => {
  $("btn-actualizar").disabled = true;
  const r = await gestor("actualizar");
  if (!r.ok) { mostrarAviso(textoError(r.error), true); $("btn-actualizar").disabled = false; return; }
  pintarActualizacion(r.datos);
});

chrome.storage.local.get("tema").then(({ tema }) => aplicarTema(tema));
iniciar();
