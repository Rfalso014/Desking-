// Barra lateral de la extensión. La extensión solo OBTIENE DATOS y manda órdenes («descargar», «cancelar», «eliminar»…):
// quien descarga es siempre la aplicación de escritorio.
// Todo el texto que viene de páginas externas se inserta como texto plano (textContent / nodos de texto).
import {
  ESTADOS_ACTIVOS, ELEMENTOS_POR_DEFECTO, TEMAS, accionesDisponibles, armarRecursos, atributoTema, claveRecurso, compararVersiones, construirOpciones,
  elementosDesdeOpciones, esUrlWeb, filtrarTareas, formatearCodigo, formatearDuracion, formatearEta, formatearTamano, formatearVelocidad,
  fusionarRecursos, miniaturaSegura, tamanosPorCalidad, MAX_TRAMOS, elegirUrlParaVideo, formatearTiempo, opcionesRecorte, textoTramos, validarTramos, nombreDeArchivo, nombreNavegador, nombreSitio, ordenarRecursos, resumenCola, siguienteTema, ETIQUETA_ESTADO,
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
  for (const h of hijos) if (h != null) e.append(h);
  return e;
}

const SECCIONES = ["cola", "pagina", "recortar", "edicion", "ajustes"];
const estado = { tab: "cola", filtro: "todas", busqueda: "", tareas: [], recursos: [], marcados: new Set(), temporizador: null, activa: null,
                 pagina: null, firmaRecursos: "", defecto: { ...ELEMENTOS_POR_DEFECTO }, seleccionDetectado: new Map(), tema: "auto" };

// --- Selector «qué descargar» (casillas combinables) --------------------------------------------------------------
// Devuelve { nodo, leer() }. `alCambiar` recibe los valores cada vez que el usuario toca algo.
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
  const campoCalidad = el("label", { clase: "campo" }, "Calidad máxima", select("altura", [["", "La de mi configuración"], ["mejor", "La mejor"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"]]));
  const campoAudio = el("label", { clase: "campo" }, "Formato de audio", select("formatoAudio", [["mp3", "MP3"], ["m4a", "M4A"], ["flac", "FLAC"], ["ogg", "OGG"], ["opus", "OPUS"], ["wav", "WAV"], ["original", "Pista original"]]));
  const entradaIdiomas = el("input", { type: "text", value: v.idiomas, placeholder: "es,en", maxLength: 40 });
  entradaIdiomas.addEventListener("input", () => { v.idiomas = entradaIdiomas.value; alCambiar({ ...v }); });
  const campoIdiomas = el("label", { clase: "campo" }, "Idiomas de subtítulos", entradaIdiomas);
  const entradaCarpeta = el("input", { type: "text", value: v.carpeta || "", placeholder: "Sin carpeta (la de la app)", maxLength: 80 });
  entradaCarpeta.addEventListener("input", () => { v.carpeta = entradaCarpeta.value; alCambiar({ ...v }); });
  const campoCarpeta = el("label", { clase: "campo", title: "Se crea en la carpeta de descargas de la aplicación, con Videos, Musica, Subtitulos y Portadas dentro" },
    "Guardar en la carpeta", entradaCarpeta);
  const pastillaEdicion = pastilla("editable", "Para edición", "MP4 con H.264 + AAC: lo abre cualquier programa de edición");
  const nodo = el("div", { clase: "selector" },
    el("div", { clase: "fila" }, pastilla("video", "Video", "El video con su audio"), pastillaEdicion, pastilla("audio", "Audio", "Solo el audio"),
      pastilla("subtitulos", "Subtítulos", "Descarga los subtítulos en los idiomas que escribas"), pastilla("portada", "Portada", "La imagen de portada del video")),
    el("div", { clase: "campos" }, campoCalidad, campoAudio, campoIdiomas, campoCarpeta));
  function actualizar() {
    campoCalidad.hidden = pastillaEdicion.hidden = !v.video; campoAudio.hidden = !v.audio; campoIdiomas.hidden = !v.subtitulos;
  }
  actualizar();
  return { nodo, leer: () => ({ ...v }) };
}

let selPagina = null;
/** Opciones (1 o 2 descargas) según lo marcado en `valores`; si algo está mal avisa y devuelve null. */
function opcionesDe(valores) {
  try {
    return construirOpciones(valores);
  } catch (e) {
    mostrarAviso(`${e.mensaje || "Revisa lo que marcaste."} ${e.solucion || ""}`);
    return null;
  }
}

// --- Comunicación con la aplicación (a través del service worker) ---------------------------
async function nativo(accion, datos = {}) {
  const r = await chrome.runtime.sendMessage({ tipo: "nativo", accion, datos });
  if (r && !r.ok && r.error && r.error.codigo === "no_vinculado" && accion !== "emparejar") {
    mostrarVista("vincular");            // el token fue revocado desde la aplicación
  }
  return r || { ok: false, error: { mensaje: "Sin respuesta del navegador." } };
}

const textoError = (e) => [e && e.mensaje, e && e.solucion].filter(Boolean).join(" ");

function mostrarAviso(texto) {
  $("aviso").hidden = !texto;
  $("aviso").textContent = texto || "";
}

const opcionesElegidas = () => opcionesDe(selPagina.leer());

/**
 * Como `nativo`, pero si el video ya está en la lista pregunta «¿descargarlo otra vez?» y, si dices que sí,
 * lo reenvía con `forzar`. Si dices que no, devuelve { ok: false, omitido: true } (no es un error).
 */
async function nativoPreguntando(accion, datos) {
  const r = await nativo(accion, datos);
  if (r.ok || !r.error || r.error.codigo !== "duplicado") return r;
  const texto = [r.error.mensaje, r.error.causa].filter(Boolean).join("\n");
  if (!confirm(`${texto}\n\n¿Quieres descargarlo otra vez?`)) return { ok: false, omitido: true };
  return nativo(accion, { ...datos, forzar: true });
}

/** Envía una orden («encolar» = descargar) por cada conjunto de opciones. Devuelve true si todas salieron bien. */
async function descargarCon(conjuntos, url, origen) {
  if (!conjuntos) return false;
  for (const opciones of conjuntos) {
    const r = await nativoPreguntando("encolar", { url, origen, opciones });
    if (r.omitido) continue;
    if (!r.ok) { mostrarAviso(textoError(r.error)); return false; }
  }
  mostrarAviso("");
  return true;
}

// --- Tema (día / noche / como Windows) -----------------------------------------------------------
const NOMBRE_TEMA = { auto: "automático", dia: "día", noche: "noche" };

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

function ponerCabecera(titulo, sub) {
  $("titulo-seccion").textContent = titulo;
  $("sub-seccion").textContent = sub || "";
}

function mostrarVista(cual) {
  document.body.dataset.vista = cual;
  $("vista-conexion").hidden = cual !== "conexion";
  $("vista-vincular").hidden = cual !== "vincular";
  $("vista-principal").hidden = cual !== "principal";
  clearInterval(estado.temporizador);
  if (cual === "principal") estado.temporizador = setInterval(latido, 1500);
  if (cual === "vincular") { ponerCabecera("Vincular", "Un paso, una sola vez"); ponerEstadoConexion("espera", "Sin vincular"); setTimeout(() => $("codigo").focus(), 50); }
  if (cual === "conexion") ponerCabecera("Gestor de Descargas", "La descarga la hace tu aplicación");
}

async function iniciar() {
  mostrarAviso("");
  ponerEstadoConexion("espera", "Conectando…");
  const r = await nativo("ping");
  if (!r.ok) {
    ponerEstadoConexion("mal", "Sin conexión");
    $("conexion-titulo").textContent = r.error && r.error.mensaje ? r.error.mensaje : "No se pudo conectar con la aplicación";
    $("conexion-texto").textContent = (r.error && [r.error.causa, r.error.solucion].filter(Boolean).join(" ")) || "";
    return mostrarVista("conexion");
  }
  if (!r.datos.vinculado) return mostrarVista("vincular");
  marcarAvisoActualizacion(r.datos.hay_actualizacion);
  avisarVersionApp(r.datos.version_app);
  ponerEstadoConexion("ok", "Conectado");
  mostrarVista("principal");
  const { inicio } = await chrome.storage.local.get("inicio");
  await cargarAjustes();
  cambiarPestana(SECCIONES.includes(inicio) ? inicio : "cola");
  buscarRecursos();
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
  const r = await nativo("emparejar", { codigo: $("codigo").value, nombre: nombreNavegador(navigator.userAgent) });
  if (!r.ok) { mostrarAviso(textoError(r.error)); $("btn-vincular").disabled = false; return; }
  $("codigo").value = "";
  iniciar();
}

// --- Secciones del riel ------------------------------------------------------------------------------
document.querySelectorAll("[data-pestana]").forEach((b) => b.addEventListener("click", () => cambiarPestana(b.dataset.pestana)));
function cambiarPestana(nombre) {
  estado.tab = nombre;
  document.querySelectorAll("[data-pestana]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pestana === nombre)));
  for (const n of SECCIONES) $(`pestana-${n}`).hidden = n !== nombre;
  pintarCabecera();
  if (nombre === "cola") refrescarCola();
  if (nombre === "pagina") buscarRecursos();
  if (nombre === "ajustes") refrescarActualizacion();
  if (nombre === "recortar") refrescarRecorte(true);
}

function pintarCabecera() {
  const n = estado.tareas.length;
  const sub = {
    cola: n ? `${n} ${n === 1 ? "elemento" : "elementos"}` : "Sin descargas",
    pagina: estado.pagina ? nombreSitio(estado.pagina.url) : "Pestaña actual",
    recortar: "Descargar solo unos minutos",
    edicion: "MP4 que abre cualquier editor",
    ajustes: "Extensión y descargas",
  }[estado.tab];
  ponerCabecera({ cola: "Cola", pagina: "Esta página", recortar: "Recortar", edicion: "Edición", ajustes: "Ajustes" }[estado.tab], sub);
}

// Cada 1,5 s: la cola; cada 4,5 s, si estás mirando «Esta página», se vuelve a leer (videos que aparecen al bajar).
let pulsos = 0;
function latido() {
  refrescarCola();
  if (estado.tab === "recortar") refrescarRecorte();
  if (estado.tab === "ajustes" || ["buscando", "actualizando", "listo"].includes(estado.faseAct)) refrescarActualizacion();
  if (estado.tab === "pagina" && ++pulsos % 3 === 0 && document.visibilityState === "visible") buscarRecursos();
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
  if (!estado.activa || !tab || estado.activa.id !== tab.id) $("analisis").hidden = true;
  estado.activa = tab;
  const d = await leerPestana(tab);
  estado.pagina = d && esUrlWeb(d.url) ? d : null;
  const web = !!estado.pagina;
  const titulo = web ? (d.titulo || d.url) : "No se puede leer esta pestaña";
  $("pagina-titulo").textContent = titulo;
  $("pagina-sitio").textContent = web ? nombreSitio(d.url) : "Abre una página web (http o https). Si ya lo es, recárgala.";
  $("ed-pagina").textContent = web ? `${titulo} · ${nombreSitio(d.url)}` : "Abre la página del video que quieres editar.";
  $("btn-analizar").disabled = $("btn-descargar-pagina").disabled = $("btn-editar-pagina").disabled = !web;
  if (estado.tab === "pagina") pintarCabecera();
  return estado.pagina;
}

const GLIFO = { video: "▶", audio: "♪", imagen: "▣", enlace: "↗" };
const claveGuardado = () => `recursos:${estado.activa && estado.activa.id}`;

// Lo encontrado se guarda por pestaña (mientras el navegador esté abierto): al recargar la página no se pierde.
async function buscarRecursos() {
  const d = await cargarPagina();
  const clave = claveGuardado();
  const previos = estado.activa ? ((await chrome.storage.session.get(clave))[clave] || []) : [];
  estado.recursos = ordenarRecursos(fusionarRecursos(previos, armarRecursos(d)));
  if (estado.activa) chrome.storage.session.set({ [clave]: estado.recursos });
  if (estado.verImagenes === undefined) estado.verImagenes = !estado.recursos.some((r) => r.tipo !== "imagen");
  const firma = JSON.stringify(estado.recursos.map((r) => [r.url, r.nombre, r.anterior]));
  const nuevos = estado.recursos.filter((r) => !r.anterior).length;
  $("recursos-nota").textContent = !d && !estado.recursos.length ? ""
    : estado.recursos.length
      ? `Marca lo que quieras. ${estado.recursos.length - nuevos ? "Lo marcado «De antes» se encontró antes de recargar la página. " : ""}La descarga la hace la aplicación.`
      : "No se encontró nada descargable. Prueba «Descargar esta página»: la aplicación intentará extraer el video desde ahí.";
  if (firma !== estado.firmaRecursos) { estado.firmaRecursos = firma; pintarRecursos(); }
}

chrome.tabs.onActivated.addListener(() => { estado.verImagenes = undefined; estado.marcados.clear(); buscarRecursos(); });
chrome.tabs.onUpdated.addListener((tabId, cambio) => {
  if (estado.activa && tabId === estado.activa.id && cambio.status === "complete") buscarRecursos();
});

/** Recursos que se muestran: las imágenes quedan ocultas hasta que se pidan. */
const visiblesRecursos = () => estado.recursos.filter((r) => estado.verImagenes || r.tipo !== "imagen");
const marcadosVisibles = () => visiblesRecursos().filter((r) => estado.marcados.has(claveRecurso(r)));

function pintarRecursos() {
  const visibles = visiblesRecursos();
  $("recursos").replaceChildren(...visibles.map((r) => {
    const k = claveRecurso(r);
    const miniatura = el("div", { clase: "miniatura" }, GLIFO[r.tipo] || "↗");
    if (r.tipo === "imagen" && miniaturaSegura(r.url)) miniatura.replaceChildren(el("img", { src: r.url, alt: "", loading: "lazy", referrerPolicy: "no-referrer" }));
    const nombre = r.nombre || nombreDeArchivo(r.url);
    return el("li", { clase: `item${r.anterior ? " anterior" : ""}` },
      el("label", {}, el("input", { type: "checkbox", checked: estado.marcados.has(k),
        onchange: (e) => { e.target.checked ? estado.marcados.add(k) : estado.marcados.delete(k); actualizarBarraRecursos(); } }),
      miniatura,
      el("div", { clase: "cuerpo" }, el("div", { clase: "titulo" }, nombre),
        el("div", { clase: "meta" }, `${r.tipo} · ${nombreSitio(r.url)}`),
        r.anterior ? el("div", { clase: "chips" }, el("span", { clase: "chip" }, "De antes")) : null)));
  }));
  const imagenes = estado.recursos.filter((r) => r.tipo === "imagen").length;
  const otros = estado.recursos.length - imagenes;
  $("btn-imagenes").hidden = !imagenes || !otros;
  $("btn-imagenes").textContent = estado.verImagenes ? "Ocultar imágenes" : `Mostrar imágenes (${imagenes})`;
  $("contador-recursos").hidden = !visibles.length;
  $("contador-recursos").textContent = visibles.length;
  actualizarBarraRecursos();
}

function actualizarBarraRecursos() {
  const visibles = visiblesRecursos();
  $("barra-recursos").hidden = !visibles.length;
  const n = marcadosVisibles().length;
  $("btn-descargar-sel").disabled = $("btn-enviar").disabled = !n;
  $("btn-descargar-sel").textContent = n ? `Descargar (${n})` : "Descargar";
  $("btn-marcar").textContent = n === visibles.length ? "Quitar marcas" : "Marcar todos";
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

async function enviarMarcados(accion) {
  const origen = estado.pagina ? estado.pagina.url : undefined;
  const conjuntos = opcionesElegidas();
  if (!conjuntos) return;
  let hechos = 0;
  for (const r of marcadosVisibles()) {
    for (const opciones of conjuntos) {                // «detectar» solo agrega a la lista: recuerda lo elegido
      const x = await nativoPreguntando(accion, { url: r.url, origen, opciones });
      if (x.omitido) continue;
      if (!x.ok) { mostrarAviso(textoError(x.error)); return; }
    }
    hechos++;
  }
  if (hechos) {
    mostrarAviso("");
    estado.marcados.clear(); pintarRecursos();
    cambiarPestana("cola");
  }
}
$("btn-descargar-sel").addEventListener("click", () => enviarMarcados("encolar"));
$("btn-enviar").addEventListener("click", () => enviarMarcados("detectar"));

$("btn-descargar-pagina").addEventListener("click", async () => {
  if (estado.pagina && await descargarCon(opcionesElegidas(), estado.pagina.url)) cambiarPestana("cola");
});

// --- Análisis ----------------------------------------------------------------------------------------------
$("btn-analizar").addEventListener("click", () => estado.pagina && analizar(estado.pagina.url));

function chip(texto, clase = "") { return el("span", { clase: `chip ${clase}` }, texto); }

async function analizar(url) {
  const caja = $("analisis");
  caja.hidden = false;
  caja.replaceChildren(el("div", { clase: "tarjeta" }, `Analizando ${nombreSitio(url)}…`));
  const r = await nativo("analizar", { url });
  if (!r.ok) {
    caja.replaceChildren(el("div", { clase: "tarjeta" }, el("div", { clase: "error-caja" }, textoError(r.error))));
    return;
  }
  const d = r.datos, dg = d.diagnostico;
  const alturas = [...new Set(d.formatos.map((f) => f.altura).filter(Boolean))].sort((a, b) => b - a);
  const subs = Object.entries(d.subtitulos || {}).map(([k, auto]) => k + (auto ? " (auto)" : ""));
  const mayor = d.formatos.map((f) => f.tamano).filter(Boolean).sort((a, b) => b - a)[0];
  const h264 = d.formatos.some((f) => /^(avc1|h264)/.test(f.codec_video || ""));
  const compat = { compatible: ["Compatible", "ok"], parcialmente_compatible: ["Compatible en parte", "aviso"], protegido: ["Protegido", "mal"], desconocido: ["Sin datos", ""] }[dg.nivel] || [dg.nivel, ""];
  const mini = miniaturaSegura(d.miniatura);
  caja.replaceChildren(el("div", { clase: "tarjeta" },
    el("div", { clase: "item", style: "border:none;padding:0;background:transparent" },
      el("div", { clase: "miniatura" }, mini ? el("img", { src: mini, referrerPolicy: "no-referrer", alt: "" }) : "▶"),
      el("div", { clase: "cuerpo" }, el("div", { clase: "titulo" }, d.titulo),
        el("div", { clase: "meta" }, [d.sitio, d.autor, formatearDuracion(d.duracion), d.en_vivo ? "en vivo" : ""].filter(Boolean).join(" · ")))),
    el("div", { clase: "chips" }, chip(compat[0], compat[1]),
      ...(alturas.length ? [chip(`hasta ${alturas[0]}p`)] : []), ...(subs.length ? [chip(`Subtítulos: ${subs.join(", ")}`)] : []),
      ...tamanosPorCalidad(d.formatos).map(([a, b]) => chip(`${a}p ≈ ${formatearTamano(b)}`)),
      ...(!tamanosPorCalidad(d.formatos).length && mayor ? [chip(`~${formatearTamano(mayor)}`)] : []),
      ...(h264 ? [chip("H.264: listo para editar", "ok")] : [])),
    el("p", { clase: "ayuda" }, dg.motivo), ...(dg.alternativas || []).map((a) => el("p", { clase: "ayuda" }, `Alternativa: ${a}`)),
    el("div", { clase: "acciones" },
      el("button", { clase: "enlace", textContent: "Cerrar", onclick: () => { caja.hidden = true; } }),
      el("button", { clase: "primario", textContent: "Descargar", disabled: dg.nivel === "protegido" && dg.confianza === "confirmado",
        onclick: async () => { if (await descargarCon(opcionesElegidas(), url)) { caja.hidden = true; cambiarPestana("cola"); } } }))));
}

// --- Cola ----------------------------------------------------------------------------------------------------------
async function accionTarea(accion, id) {
  const r = await nativo(accion, { id });
  if (!r.ok) mostrarAviso(textoError(r.error)); else mostrarAviso("");
  await refrescarCola();
}

const ROTULO = { cancelar: "Cancelar", reintentar: "Reintentar", eliminar: "Eliminar", iniciar: "Descargar", abrir_carpeta: "Abrir carpeta" };

function accionesDeTarea(t) {
  const lista = accionesDisponibles(t.estado);
  if (t.estado === "completado" && t.carpeta_final) lista.unshift("abrir_carpeta");
  return lista;
}

function pintarTarea(t) {
  const mini = miniaturaSegura(t.miniatura);
  const activa = t.estado === "descargando";
  const detalles = [];
  if (activa) detalles.push(t.progreso != null ? `${Math.round(t.progreso)} %` : "Iniciando…", formatearVelocidad(t.velocidad), t.eta != null ? `quedan ${formatearEta(t.eta)}` : "");
  const paraEditar = t.opciones && t.opciones.editable ? "Para edición" : "";
  const cuerpo = [
    el("div", { clase: "titulo" }, t.titulo || t.url),
    el("div", { clase: "meta" }, [t.sitio || nombreSitio(t.url), formatearDuracion(t.duracion), paraEditar, textoTramos(t.opciones && t.opciones.tramos)]
      .filter(Boolean).join(" · ")),
    el("div", { clase: "fila-estado" }, el("span", { clase: `etiqueta-estado ${t.estado}` }, ETIQUETA_ESTADO[t.estado] || t.estado),
      el("span", { clase: "meta" }, detalles.filter(Boolean).join(" · "))),
  ];
  if (["descargando", "procesando"].includes(t.estado) && t.progreso != null) {
    cuerpo.push(el("div", { clase: "barra" }, el("i", { style: `width:${Math.max(0, Math.min(100, t.progreso))}%` })));
  }
  if (t.estado === "procesando") cuerpo.push(el("div", { clase: "meta" }, paraEditar ? "Convirtiendo a H.264 para edición (con la tarjeta gráfica si se puede; en 1440p o 4K tarda más)…" : "La aplicación está uniendo y convirtiendo los archivos…"));
  for (const n of t.notas || []) cuerpo.push(el("div", { clase: "meta" }, n));
  if (t.error) {
    cuerpo.push(el("div", { clase: "error-caja" }, t.error.mensaje,
      el("div", {}, `Causa: ${t.error.causa || "no se pudo determinar"}`), ...(t.error.solucion ? [el("div", {}, `Qué hacer: ${t.error.solucion}`)] : [])));
  }
  if (t.estado === "detectado") {
    // Esperando TU autorización: eliges qué quieres y recién entonces se descarga.
    cuerpo.push(el("div", { clase: "meta" }, "Esperando tu autorización. Elige qué descargar y pulsa «Descargar»."));
    const inicial = estado.seleccionDetectado.get(t.id) || elementosDesdeOpciones(t.opciones, estado.defecto);
    const sel = crearSelector(inicial, (valores) => estado.seleccionDetectado.set(t.id, valores));
    estado.seleccionDetectado.set(t.id, sel.leer());
    cuerpo.push(sel.nodo);
    cuerpo.push(el("div", { clase: "acciones" },
      el("button", { clase: "primario", textContent: "Descargar", onclick: () => autorizarDetectada(t, sel.leer()) }),
      el("button", { clase: "peligro", textContent: "Eliminar", onclick: () => accionTarea("eliminar", t.id) })));
    return itemTarea(t, mini, cuerpo);
  }
  const botones = accionesDeTarea(t).map((a) => el("button", {
    clase: a === "iniciar" ? "primario" : a === "reintentar" || a === "abrir_carpeta" ? "sec" : a === "eliminar" ? "peligro" : "",
    textContent: ROTULO[a], onclick: () => accionTarea(a, t.id),
  }));
  if (botones.length) cuerpo.push(el("div", { clase: "acciones" }, ...botones));
  return itemTarea(t, mini, cuerpo);
}

function itemTarea(t, mini, cuerpo) {
  return el("li", { clase: "item" },
    el("div", { clase: "miniatura" }, mini ? el("img", { src: mini, referrerPolicy: "no-referrer", alt: "", loading: "lazy" }) : "▶"),
    el("div", { clase: "cuerpo" }, ...cuerpo));
}

/** El usuario autoriza una descarga detectada: la primera opción pone en marcha la tarea; las demás (p. ej. el audio aparte) crean otra. */
async function autorizarDetectada(t, valores) {
  const conjuntos = opcionesDe(valores);
  if (!conjuntos) return;
  const r = await nativo("iniciar", { id: t.id, opciones: conjuntos[0] });
  if (!r.ok) { mostrarAviso(textoError(r.error)); return; }
  for (const opciones of conjuntos.slice(1)) {
    const x = await nativoPreguntando("encolar", { url: t.url, origen: t.origen || undefined, opciones });
    if (!x.ok && !x.omitido) { mostrarAviso(textoError(x.error)); break; }
  }
  estado.seleccionDetectado.delete(t.id);
  mostrarAviso("");
  refrescarCola();
}

async function refrescarCola() {
  const r = await nativo("listar", { limite: 100 });
  const ul = $("cola");
  if (!r.ok) { ul.replaceChildren(el("li", { clase: "vacio" }, "No se puede mostrar la cola sin conexión.")); return; }
  estado.tareas = r.datos.tareas;
  const activas = estado.tareas.filter((t) => ESTADOS_ACTIVOS.includes(t.estado));
  const porAutorizar = estado.tareas.filter((t) => t.estado === "detectado");
  const aviso = activas.length + porAutorizar.length;
  $("contador-cola").hidden = !aviso;
  $("contador-cola").textContent = aviso;
  chrome.action.setBadgeBackgroundColor({ color: activas.length ? "#1f9e94" : "#d97706" });
  chrome.action.setBadgeText({ text: activas.length ? String(activas.length) : porAutorizar.length ? String(porAutorizar.length) : "" });
  if (estado.tab !== "cola") return;
  pintarCabecera();

  const s = resumenCola(estado.tareas);
  $("resumen").replaceChildren(
    ...[[s.descargando, "Descargando"], [s.enEspera + s.detectados, "En espera"], [formatearVelocidad(s.velocidad) || "—", "Velocidad", true]]
      .map(([n, txt, resaltado]) => el("div", { clase: `dato${resaltado ? " resaltado" : ""}` }, el("b", {}, String(n)), el("span", {}, txt))));
  $("btn-iniciar-todos").hidden = !s.detectados;
  $("promo-edicion").hidden = !!estado.defecto.editable;
  const visibles = filtrarTareas(estado.tareas, estado.filtro, estado.busqueda);
  ul.replaceChildren(...(visibles.length ? visibles.map(pintarTarea)
    : [el("li", { clase: "vacio" }, estado.tareas.length ? "Nada coincide con el filtro." : "No hay descargas. Usa «＋ Añadir» sobre un video o busca en «Esta página».")]));
}

document.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => {
  estado.filtro = b.dataset.filtro;
  document.querySelectorAll("[data-filtro]").forEach((x) => x.classList.toggle("activo", x === b));
  refrescarCola();
}));
$("busqueda").addEventListener("input", (e) => { estado.busqueda = e.target.value; refrescarCola(); });
$("btn-cancelar-todas").addEventListener("click", async () => {
  if (!estado.tareas.some((t) => t.estado === "detectado" || ESTADOS_ACTIVOS.includes(t.estado))) return;
  if (!confirm("¿Cancelar todas las descargas en curso, en espera y detectadas?")) return;
  await nativo("cancelar_todas");
  refrescarCola();
});
$("btn-limpiar").addEventListener("click", async () => { await nativo("limpiar"); refrescarCola(); });
$("btn-iniciar-todos").addEventListener("click", async () => {
  for (const t of estado.tareas.filter((x) => x.estado === "detectado")) {
    // «Descargar todos»: usa lo que tenga elegido cada uno (o tu valor por defecto).
    const conjuntos = opcionesDe(estado.seleccionDetectado.get(t.id) || elementosDesdeOpciones(t.opciones, estado.defecto));
    if (!conjuntos) return;
    await nativo("iniciar", { id: t.id, opciones: conjuntos[0] });
    for (const opciones of conjuntos.slice(1)) await nativoPreguntando("encolar", { url: t.url, origen: t.origen || undefined, opciones });
  }
  refrescarCola();
});
$("btn-activar-edicion").addEventListener("click", () => {
  guardarDefecto({ ...estado.defecto, editable: true });
  mostrarAviso("Modo edición activado: los videos que añadas se guardarán en MP4 listo para editar.");
  refrescarCola();
});

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
  $("rc-titulo").textContent = v && v.hayVideo ? v.titulo : "No hay ningún video en esta pestaña";
  $("rc-meta").textContent = !v ? "Abre la página del video (si ya está abierta, recárgala)."
    : !v.hayVideo ? "Abre el video que quieres recortar."
    : v.enVivo ? "Es un directo: no se puede recortar mientras se emite."
    : `${nombreSitio(v.url)} · dura ${formatearTiempo(v.duracion)} · ahora en ${formatearTiempo(v.actual)}`;
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
    for (const [a, b] of r.tramos || []) hijos.push(el("div", { clase: "seg", style: `left:${(a / dur) * 100}%;width:${((b - a) / dur) * 100}%` }));
    hijos.push(el("div", { clase: "ahora", style: `left:${(v.actual / dur) * 100}%` }));
  }
  $("rc-linea").replaceChildren(...hijos);
}

async function verTrozo(i) {
  const r = validarTramos([estado.recorte.filas[i]], estado.recorte.video && estado.recorte.video.duracion);
  if (!r.tramos) { $("rc-error").hidden = false; $("rc-error").textContent = r.error; return; }
  const tab = await pestanaActiva();
  try { await chrome.tabs.sendMessage(tab.id, { tipo: "video-ir", segundo: r.tramos[0][0], hasta: r.tramos[0][1] }, { frameId: 0 }); } catch { /* sin video */ }
}

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
    conjuntos = opcionesRecorte(estado.defecto, r.tramos, { exacto: $("rc-exacto").checked, audio: $("rc-audio").checked });
  } catch (e) {
    mostrarAviso(`${e.mensaje || "Revisa «qué descargar» en los Ajustes."} ${e.solucion || ""}`);
    return;
  }
  $("rc-descargar").disabled = true;
  const ok = await descargarCon(conjuntos, url, esUrlWeb(v.url) ? v.url : undefined);
  $("rc-descargar").disabled = false;
  if (ok) { rc.filas = [{ desde: "", hasta: "" }]; pintarFilasRecorte(); cambiarPestana("cola"); }
});

// --- Edición -------------------------------------------------------------------------------------------------------
function pintarEdicion() {
  $("ed-defecto").checked = !!estado.defecto.editable;
  document.querySelectorAll('input[name="ed-calidad"]').forEach((r) => { r.checked = r.value === estado.defecto.altura; });
}
$("ed-defecto").addEventListener("change", (e) => guardarDefecto({ ...estado.defecto, editable: e.target.checked }));
document.querySelectorAll('input[name="ed-calidad"]').forEach((r) => r.addEventListener("change", () => {
  if (r.checked) guardarDefecto({ ...estado.defecto, altura: r.value });
}));
$("btn-editar-pagina").addEventListener("click", async () => {
  if (!estado.pagina) return;
  const conjuntos = opcionesDe({ ...estado.defecto, video: true, audio: false, editable: true });
  if (await descargarCon(conjuntos, estado.pagina.url)) cambiarPestana("cola");
});

// --- Ajustes -------------------------------------------------------------------------------------------------------
function guardarDefecto(valores) {
  estado.defecto = valores;
  chrome.storage.local.set({ elementos: valores });
  pintarEdicion();
  pintarSelectorAjustes();
}

function pintarSelectorAjustes() {
  const sel = crearSelector(estado.defecto, (valores) => { estado.defecto = valores; chrome.storage.local.set({ elementos: valores }); pintarEdicion(); });
  $("selector-ajustes").replaceChildren(sel.nodo);
}

async function cargarAjustes() {
  const a = await chrome.storage.local.get(["botonFlotante", "elementos", "inicio"]);
  $("aj-boton").checked = a.botonFlotante !== false;
  $("aj-inicio").value = a.inicio === "pagina" ? "pagina" : "cola";
  estado.defecto = { ...ELEMENTOS_POR_DEFECTO, ...(a.elementos || {}) };
  selPagina = crearSelector(estado.defecto);
  $("selector-pagina").replaceChildren(selPagina.nodo);
  pintarSelectorAjustes();
  pintarEdicion();
  $("aj-vinculo").textContent = `Vinculada como «${nombreNavegador(navigator.userAgent)}». ` +
    "Puedes revocarla desde la aplicación (pestaña Extensión) o desvincularla aquí.";
}

// --- Versión de la aplicación abierta ------------------------------------------------------------------------------------
// Si la app que está abierta es anterior a esta extensión, no entiende lo nuevo («Para edición», actualizaciones…).
function avisarVersionApp(versionApp) {
  const propia = chrome.runtime.getManifest().version;
  const vieja = compararVersiones(versionApp || "0", propia) < 0;
  $("aviso-version").hidden = !vieja;
  if (vieja) {
    $("aviso-version-texto").textContent = `La aplicación abierta es una versión anterior (${versionApp || "sin versión"}) a esta extensión (${propia}). ` +
      "Reiníciala para que funcione todo (por ejemplo «Para edición»).";
  }
}

$("btn-reiniciar-app").addEventListener("click", async () => {
  $("btn-reiniciar-app").disabled = true;
  const r = await nativo("reiniciar");
  if (!r.ok) {
    $("aviso-version-texto").textContent = r.error && /Acción desconocida/.test(r.error.mensaje || "")
      ? "Esta versión de la aplicación no sabe reiniciarse sola: ciérrala desde el ícono de la bandeja (Salir) y vuelve a abrirla."
      : textoError(r.error);
    $("btn-reiniciar-app").disabled = false;
    return;
  }
  $("aviso-version-texto").textContent = "Reiniciando la aplicación…";
  setTimeout(() => { $("btn-reiniciar-app").disabled = false; iniciar(); }, 4000);
});

// --- Actualizaciones (lo hace la aplicación; la extensión se recarga sola al terminar) ------------------------------------
const NOMBRES_VERSION = [["app", "Aplicación"], ["extension", "Extensión"], ["yt-dlp", "yt-dlp"], ["yt-dlp-ejs", "Solucionador JS"],
                         ["gallery-dl", "gallery-dl"], ["deno", "Deno"], ["ffmpeg", "FFmpeg"]];

function marcarAvisoActualizacion(hay) {
  document.querySelector('[data-pestana="ajustes"]').classList.toggle("con-aviso", !!hay);
}

async function refrescarActualizacion(buscar = false) {
  // Mientras se actualiza, el ping deja que el service worker recargue la extensión cuando la app vuelva.
  if (["actualizando", "listo"].includes(estado.faseAct)) nativo("ping");
  const r = await nativo("actualizacion", buscar ? { buscar: true } : {});
  if (!r.ok) { $("act-estado").textContent = textoError(r.error) || "La aplicación no respondió."; return; }
  pintarActualizacion(r.datos);
}

function pintarActualizacion(e) {
  estado.faseAct = e.fase;
  const propia = chrome.runtime.getManifest().version;
  const v = { ...e.versiones, extension: propia };
  $("act-versiones").replaceChildren(...NOMBRES_VERSION.filter(([k]) => v[k]).map(([k, t]) => el("li", {}, el("span", {}, t), el("b", {}, String(v[k])))));
  $("act-pendientes").replaceChildren(...(e.pendientes || []).map((p) => el("li", {}, `${p.nombre}: ${p.actual} → ${p.nueva}`)));
  const texto = [e.mensaje];
  if (e.fase === "listo") texto.push(...(e.hechos || []).map((h) => `✓ ${h}`));
  texto.push(...(e.avisos || []).map((a) => `⚠ ${a}`));
  if (e.version_extension && e.version_extension !== propia && e.fase !== "actualizando") {
    texto.push(`⚠ Esta extensión (${propia}) no es la de la aplicación (${e.version_extension}). Cárgala desde: ${e.carpeta_extension}`);
  }
  if (e.fase === "inactivo" && e.ultima_busqueda && !e.pendientes.length) texto.push(`Última búsqueda: ${new Date(e.ultima_busqueda * 1000).toLocaleString()}`);
  $("act-estado").textContent = texto.filter(Boolean).join(" ") || "Pulsa «Buscar» para ver si hay algo nuevo.";
  const ocupado = e.fase === "buscando" || e.fase === "actualizando";
  $("btn-actualizar").disabled = $("btn-buscar-act").disabled = ocupado;
  $("btn-actualizar").textContent = e.fase === "actualizando" ? "Actualizando…" : "Actualizar aplicación y extensión";
  marcarAvisoActualizacion((e.pendientes || []).length);
}

$("btn-buscar-act").addEventListener("click", () => refrescarActualizacion(true));
$("btn-actualizar").addEventListener("click", async () => {
  $("btn-actualizar").disabled = true;
  const r = await nativo("actualizar");
  if (!r.ok) { mostrarAviso(textoError(r.error)); $("btn-actualizar").disabled = false; return; }
  mostrarAviso("");
  pintarActualizacion(r.datos);
});

$("aj-boton").addEventListener("change", (e) => chrome.storage.local.set({ botonFlotante: e.target.checked }));
$("aj-inicio").addEventListener("change", (e) => chrome.storage.local.set({ inicio: e.target.value }));
$("btn-abrir-app").addEventListener("click", async () => {
  const r = await nativo("mostrar");
  mostrarAviso(r.ok ? "" : textoError(r.error));
});
$("btn-desvincular").addEventListener("click", async () => {
  const r = await nativo("desvincular");
  if (!r.ok) { mostrarAviso(textoError(r.error)); return; }
  await chrome.runtime.sendMessage({ tipo: "olvidar-token" });
  iniciar();
});

chrome.storage.local.get("tema").then(({ tema }) => aplicarTema(tema));
iniciar();
