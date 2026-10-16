// Popup de la extensión. La extensión solo OBTIENE DATOS y manda órdenes («descargar», «cancelar», «eliminar»…):
// quien descarga es siempre la aplicación de escritorio.
// Todo el texto que viene de páginas externas se inserta como texto plano (textContent / nodos de texto).
import {
  ESTADOS_ACTIVOS, ELEMENTOS_POR_DEFECTO, accionesDisponibles, construirOpciones, elementosDesdeOpciones, esUrlWeb, filtrarTareas,
  formatearCodigo, formatearDuracion, formatearEta, formatearTamano, formatearVelocidad, miniaturaSegura, nombreNavegador, nombreSitio,
  resumenCola, ETIQUETA_ESTADO,
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

const estado = { tab: "pagina", filtro: "todas", busqueda: "", tareas: [], recursos: [], marcados: new Set(), temporizador: null, activa: null,
                 defecto: { ...ELEMENTOS_POR_DEFECTO }, seleccionDetectado: new Map() };

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
  const nodo = el("div", { clase: "selector" },
    el("div", { clase: "fila" }, pastilla("video", "Video", "El video con su audio"), pastilla("audio", "Audio", "Solo el audio"),
      pastilla("subtitulos", "Subtítulos", "Descarga los subtítulos en los idiomas que escribas"), pastilla("portada", "Portada", "La imagen de portada del video")),
    el("div", { clase: "campos" }, campoCalidad, campoAudio, campoIdiomas));
  function actualizar() {
    campoCalidad.hidden = !v.video; campoAudio.hidden = !v.audio; campoIdiomas.hidden = !v.subtitulos;
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

/** Envía una orden («encolar» = descargar) por cada conjunto de opciones. Devuelve true si todas salieron bien. */
async function descargarConLoElegido(url, origen) {
  const conjuntos = opcionesElegidas();
  if (!conjuntos) return false;
  for (const opciones of conjuntos) {
    const r = await nativo("encolar", { url, origen, opciones });
    if (!r.ok) { mostrarAviso(textoError(r.error)); return false; }
  }
  mostrarAviso("");
  return true;
}

// --- Vistas ----------------------------------------------------------------------------------
function ponerEstadoConexion(clase, texto) {
  $("estado-conexion").className = `punto ${clase}`;
  $("estado-conexion").lastElementChild.textContent = texto;
}

function mostrarVista(cual) {
  $("vista-conexion").hidden = cual !== "conexion";
  $("vista-vincular").hidden = cual !== "vincular";
  $("vista-principal").hidden = cual !== "principal";
  clearInterval(estado.temporizador);
  if (cual === "principal") estado.temporizador = setInterval(refrescarCola, 1500);
  if (cual === "vincular") { ponerEstadoConexion("espera", "Sin vincular"); setTimeout(() => $("codigo").focus(), 50); }
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
  ponerEstadoConexion("ok", "Conectado");
  mostrarVista("principal");
  await cargarAjustes();
  await cargarPagina();
  buscarRecursos();
  refrescarCola();
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

// --- Pestañas --------------------------------------------------------------------------------------
document.querySelectorAll("[data-pestana]").forEach((b) => b.addEventListener("click", () => cambiarPestana(b.dataset.pestana)));
function cambiarPestana(nombre) {
  estado.tab = nombre;
  document.querySelectorAll("[data-pestana]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.pestana === nombre)));
  for (const n of ["pagina", "cola", "ajustes"]) $(`pestana-${n}`).hidden = n !== nombre;
  if (nombre === "cola") refrescarCola();
}

// --- Esta página ---------------------------------------------------------------------------------------
async function pestanaActiva() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function cargarPagina() {
  const tab = await pestanaActiva();
  estado.activa = tab;
  const web = tab && esUrlWeb(tab.url);
  $("pagina-titulo").textContent = web ? (tab.title || tab.url) : "Esta pestaña no es una página web";
  $("pagina-sitio").textContent = web ? nombreSitio(tab.url) : "Abre una página con http o https para usar la extensión aquí.";
  $("btn-analizar").disabled = $("btn-descargar-pagina").disabled = !web;
}

// Esta función se ejecuta DENTRO de la página (por eso no puede usar nada del popup).
function detectarEnPagina() {
  const vistos = new Map();
  const web = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; } };
  const anadir = (tipo, u, nombre) => { const h = web(u); if (h && !vistos.has(h) && vistos.size < 100) vistos.set(h, { tipo, url: h, nombre: (nombre || "").slice(0, 120) }); };
  document.querySelectorAll("video, audio").forEach((m) => {
    const tipo = m.tagName.toLowerCase();
    const enlace = m.closest("a[href]");
    if (enlace) anadir(tipo, enlace.href, document.title);
    if (m.currentSrc) anadir(tipo, m.currentSrc, document.title);
    m.querySelectorAll("source[src]").forEach((s) => anadir(tipo, s.src, document.title));
  });
  document.querySelectorAll("img[src]").forEach((i) => { if ((i.naturalWidth || 0) >= 160) anadir("imagen", i.currentSrc || i.src, i.alt); });
  document.querySelectorAll("a[href]").forEach((a) => {
    if (/\.(mp4|webm|mkv|mov|mp3|m4a|flac|ogg|opus|wav|jpg|jpeg|png|webp|gif)(\?|#|$)/i.test(a.pathname)) anadir("enlace", a.href, a.textContent.trim());
  });
  return [...vistos.values()];
}

const GLIFO = { video: "▶", audio: "♪", imagen: "▣", enlace: "↗" };

async function buscarRecursos() {
  const tab = estado.activa;
  $("recursos-nota").textContent = "Buscando…";
  estado.recursos = []; estado.marcados.clear();
  if (!tab || !esUrlWeb(tab.url)) { $("recursos-nota").textContent = ""; pintarRecursos(); return; }
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: false }, func: detectarEnPagina });
    estado.recursos = res.result || [];
  } catch {
    $("recursos-nota").textContent = "El navegador no permite leer esta página.";
    return pintarRecursos();
  }
  $("recursos-nota").textContent = estado.recursos.length
    ? "Marca lo que quieras. Los datos se leen aquí; la descarga la hace la aplicación."
    : "No se encontró nada descargable directamente. Prueba «Descargar esta página»: la aplicación intentará extraer el video desde ahí.";
  pintarRecursos();
}

function pintarRecursos() {
  const ul = $("recursos");
  ul.replaceChildren(...estado.recursos.map((r, i) => el("li", { clase: "item" },
    el("label", {}, el("input", { type: "checkbox", checked: estado.marcados.has(i),
      onchange: (e) => { e.target.checked ? estado.marcados.add(i) : estado.marcados.delete(i); actualizarBarraRecursos(); } }),
    el("div", { clase: "miniatura" }, GLIFO[r.tipo] || "↗"),
    el("div", { clase: "cuerpo" }, el("div", { clase: "titulo" }, r.nombre || r.url),
      el("div", { clase: "meta" }, `${r.tipo} · ${nombreSitio(r.url)}`), el("div", { clase: "meta" }, r.url))))));
  $("contador-recursos").hidden = !estado.recursos.length;
  $("contador-recursos").textContent = estado.recursos.length;
  actualizarBarraRecursos();
}

function actualizarBarraRecursos() {
  $("barra-recursos").hidden = !estado.recursos.length;
  const n = estado.marcados.size;
  $("btn-descargar-sel").disabled = $("btn-enviar").disabled = !n;
  $("btn-descargar-sel").textContent = n ? `Descargar seleccionados (${n})` : "Descargar seleccionados";
  $("btn-marcar").textContent = n === estado.recursos.length ? "Quitar marcas" : "Marcar todos";
}

$("btn-buscar").addEventListener("click", buscarRecursos);
$("btn-marcar").addEventListener("click", () => {
  if (estado.marcados.size === estado.recursos.length) estado.marcados.clear();
  else estado.recursos.forEach((_, i) => estado.marcados.add(i));
  pintarRecursos();
});

async function enviarMarcados(accion) {
  const origen = estado.activa && esUrlWeb(estado.activa.url) ? estado.activa.url : undefined;
  const conjuntos = opcionesElegidas();
  if (!conjuntos) return;
  let hechos = 0;
  for (const i of [...estado.marcados]) {
    for (const opciones of conjuntos) {                // «detectar» solo agrega a la lista: recuerda lo elegido
      const r = await nativo(accion, { url: estado.recursos[i].url, origen, opciones });
      if (!r.ok) { mostrarAviso(textoError(r.error)); return; }
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
  if (await descargarConLoElegido(estado.activa.url)) cambiarPestana("cola");
});

// --- Análisis ----------------------------------------------------------------------------------------------
$("btn-analizar").addEventListener("click", () => analizar(estado.activa.url));

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
  const compat = { compatible: ["Compatible", "ok"], parcialmente_compatible: ["Compatible en parte", "aviso"], protegido: ["Protegido", "mal"], desconocido: ["Sin datos", ""] }[dg.nivel] || [dg.nivel, ""];
  const mini = miniaturaSegura(d.miniatura);
  caja.replaceChildren(el("div", { clase: "tarjeta" },
    el("div", { clase: "item", style: "border:none;padding:0;box-shadow:none" },
      el("div", { clase: "miniatura" }, mini ? el("img", { src: mini, referrerPolicy: "no-referrer", alt: "" }) : "▶"),
      el("div", { clase: "cuerpo" }, el("div", { clase: "titulo" }, d.titulo),
        el("div", { clase: "meta" }, [d.sitio, d.autor, formatearDuracion(d.duracion), d.en_vivo ? "en vivo" : ""].filter(Boolean).join(" · ")))),
    el("div", { clase: "chips" }, chip(compat[0], compat[1]),
      ...(alturas.length ? [chip(`hasta ${alturas[0]}p`)] : []), ...(subs.length ? [chip(`Subtítulos: ${subs.join(", ")}`)] : []),
      ...(mayor ? [chip(`~${formatearTamano(mayor)}`)] : [])),
    el("p", { clase: "ayuda" }, dg.motivo), ...(dg.alternativas || []).map((a) => el("p", { clase: "ayuda" }, `Alternativa: ${a}`)),
    el("div", { clase: "acciones" },
      el("button", { clase: "enlace", textContent: "Cerrar", onclick: () => { caja.hidden = true; } }),
      el("button", { clase: "primario", textContent: "Descargar", disabled: dg.nivel === "protegido" && dg.confianza === "confirmado",
        onclick: async () => { if (await descargarConLoElegido(url)) { caja.hidden = true; cambiarPestana("cola"); } } }))));
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
  const cuerpo = [
    el("div", { clase: "titulo" }, t.titulo || t.url),
    el("div", { clase: "meta" }, [t.sitio || nombreSitio(t.url), formatearDuracion(t.duracion)].filter(Boolean).join(" · ")),
    el("div", { clase: "fila-estado" }, el("span", { clase: `etiqueta-estado ${t.estado}` }, ETIQUETA_ESTADO[t.estado] || t.estado),
      el("span", { clase: "meta" }, detalles.filter(Boolean).join(" · "))),
  ];
  if (["descargando", "procesando"].includes(t.estado) && t.progreso != null) cuerpo.push(el("progress", { max: 100, value: t.progreso }));
  if (t.estado === "procesando") cuerpo.push(el("div", { clase: "meta" }, "La aplicación está uniendo y convirtiendo los archivos…"));
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
    clase: a === "iniciar" ? "primario" : a === "reintentar" ? "sec" : a === "eliminar" ? "peligro" : "",
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
    const x = await nativo("encolar", { url: t.url, origen: t.origen || undefined, opciones });
    if (!x.ok) { mostrarAviso(textoError(x.error)); break; }
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
  chrome.action.setBadgeBackgroundColor({ color: activas.length ? "#2563eb" : "#d97706" });
  chrome.action.setBadgeText({ text: activas.length ? String(activas.length) : porAutorizar.length ? String(porAutorizar.length) : "" });
  if (estado.tab !== "cola") return;

  const s = resumenCola(estado.tareas);
  $("resumen").replaceChildren(
    ...[[s.descargando, "descargando"], [s.enEspera, "en espera"], [s.detectados, "detectados"], [formatearVelocidad(s.velocidad) || "—", "velocidad"]]
      .map(([n, txt]) => el("div", { clase: "dato" }, el("b", {}, String(n)), el("span", {}, txt))));
  $("btn-iniciar-todos").hidden = !s.detectados;
  const visibles = filtrarTareas(estado.tareas, estado.filtro, estado.busqueda);
  ul.replaceChildren(...(visibles.length ? visibles.map(pintarTarea)
    : [el("li", { clase: "vacio" }, estado.tareas.length ? "Nada coincide con el filtro." : "No hay descargas. Busca recursos en «Esta página» o usa el botón sobre los videos.")]));
}

document.querySelectorAll("[data-filtro]").forEach((b) => b.addEventListener("click", () => {
  estado.filtro = b.dataset.filtro;
  document.querySelectorAll("[data-filtro]").forEach((x) => x.classList.toggle("activo", x === b));
  refrescarCola();
}));
$("busqueda").addEventListener("input", (e) => { estado.busqueda = e.target.value; refrescarCola(); });
$("btn-limpiar").addEventListener("click", async () => { await nativo("limpiar"); refrescarCola(); });
$("btn-iniciar-todos").addEventListener("click", async () => {
  for (const t of estado.tareas.filter((x) => x.estado === "detectado")) {
    // «Descargar todos»: usa lo que tenga elegido cada uno (o tu valor por defecto).
    const conjuntos = opcionesDe(estado.seleccionDetectado.get(t.id) || elementosDesdeOpciones(t.opciones, estado.defecto));
    if (!conjuntos) return;
    await nativo("iniciar", { id: t.id, opciones: conjuntos[0] });
    for (const opciones of conjuntos.slice(1)) await nativo("encolar", { url: t.url, origen: t.origen || undefined, opciones });
  }
  refrescarCola();
});

// --- Ajustes -------------------------------------------------------------------------------------------------------
async function cargarAjustes() {
  const a = await chrome.storage.local.get(["botonFlotante", "elementos"]);
  $("aj-boton").checked = a.botonFlotante !== false;
  estado.defecto = { ...ELEMENTOS_POR_DEFECTO, ...(a.elementos || {}) };
  selPagina = crearSelector(estado.defecto);
  $("selector-pagina").replaceChildren(selPagina.nodo);
  const selAjustes = crearSelector(estado.defecto, (valores) => { estado.defecto = valores; chrome.storage.local.set({ elementos: valores }); });
  $("selector-ajustes").replaceChildren(selAjustes.nodo);
  $("aj-vinculo").textContent = `Esta extensión está vinculada como «${nombreNavegador(navigator.userAgent)}». ` +
    "Puedes revocarla desde la aplicación (pestaña Extensión) o desvincularla aquí.";
}

$("aj-boton").addEventListener("change", (e) => chrome.storage.local.set({ botonFlotante: e.target.checked }));
$("btn-desvincular").addEventListener("click", async () => {
  const r = await nativo("desvincular");
  if (!r.ok) { mostrarAviso(textoError(r.error)); return; }
  await chrome.runtime.sendMessage({ tipo: "olvidar-token" });
  iniciar();
});

iniciar();
