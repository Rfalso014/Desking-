// Popup: recursos detectados + cola de descargas. Todo el texto de páginas externas se
// inserta como texto plano (textContent / nodos de texto) para que una página no pueda inyectar código.
import { ETIQUETA_ESTADO, ESTADOS_ACTIVOS, accionesDisponibles, esUrlWeb, formatearTamano, nombreSitio } from "./util.js";

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "clase") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e[k] = v;
  }
  for (const h of hijos) e.append(h);
  return e;
}

const nativo = (accion, datos = {}) => chrome.runtime.sendMessage({ tipo: "nativo", accion, datos });

function mostrarAviso(texto) {
  $("aviso").hidden = !texto;
  $("aviso").textContent = texto || "";
}

function opcionesElegidas() {
  const o = { modo: $("modo").value };
  if ($("altura").value) o.altura_max = Number($("altura").value);
  return o;
}

// --- Conexión -----------------------------------------------------------------
async function comprobarConexion() {
  const r = await nativo("ping");
  const chip = $("conexion");
  chip.className = "chip " + (r.ok ? "ok" : "mal");
  chip.textContent = r.ok ? "Conectado" : "Sin conexión";
  if (!r.ok && r.error) mostrarAviso(`${r.error.mensaje} ${r.error.solucion || ""}`);
  return r.ok;
}

// --- Detección en la página --------------------------------------------------
// Esta función se ejecuta DENTRO de la página (por eso no puede usar nada del popup).
function detectarEnPagina() {
  const vistos = new Map();
  const web = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; } };
  const anadir = (tipo, u, nombre) => { const h = web(u); if (h && !vistos.has(h) && vistos.size < 100) vistos.set(h, { tipo, url: h, nombre: (nombre || "").slice(0, 120) }); };
  document.querySelectorAll("video, audio").forEach((m) => {
    const tipo = m.tagName.toLowerCase();
    if (m.currentSrc) anadir(tipo, m.currentSrc, document.title);
    m.querySelectorAll("source[src]").forEach((s) => anadir(tipo, s.src, document.title));
  });
  document.querySelectorAll("img[src]").forEach((i) => { if ((i.naturalWidth || 0) >= 120) anadir("imagen", i.currentSrc || i.src, i.alt); });
  document.querySelectorAll("a[href]").forEach((a) => {
    if (/\.(mp4|webm|mkv|mov|mp3|m4a|flac|ogg|opus|wav|jpg|jpeg|png|webp|gif)(\?|#|$)/i.test(a.pathname)) anadir("enlace", a.href, a.textContent.trim());
  });
  return [...vistos.values()];
}

const detectados = [];

async function buscarEnPagina() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !esUrlWeb(tab.url)) { mostrarAviso("Abre una página web (http/https) para buscar recursos."); return; }
  try {
    const [res] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: detectarEnPagina });
    detectados.splice(0, detectados.length, ...(res.result || []));
    pintarDetectados();
    $("detectados-nota").textContent = detectados.length
      ? `${detectados.length} recurso(s) encontrados. Elige cuáles añadir.`
      : "No se encontró nada descargable. Prueba «Añadir esta página»: la aplicación intentará extraer el video desde ahí.";
  } catch {
    mostrarAviso("No se pudo leer esta página (el navegador no lo permite aquí).");
  }
}

function pintarDetectados() {
  const ul = $("detectados");
  ul.replaceChildren();
  detectados.forEach((d, i) => {
    const cb = el("input", { type: "checkbox", id: `d${i}`, checked: false });
    ul.append(el("li", { clase: "item" }, el("label", {},
      cb, el("div", {}, el("div", { clase: "titulo" }, d.nombre || d.url),
        el("div", { clase: "meta" }, `${d.tipo} · ${nombreSitio(d.url)}`), el("div", { clase: "meta" }, d.url)))));
  });
  $("btn-anadir").disabled = !detectados.length;
}

async function anadirSeleccionados() {
  const marcados = detectados.filter((_, i) => $(`d${i}`).checked);
  if (!marcados.length) { mostrarAviso("Marca al menos un recurso."); return; }
  mostrarAviso("");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  for (const m of marcados) {
    const r = await nativo("encolar", { url: m.url, origen: tab && esUrlWeb(tab.url) ? tab.url : undefined, opciones: opcionesElegidas() });
    if (!r.ok) { mostrarAviso(`${r.error.mensaje} ${r.error.solucion || ""}`); break; }
  }
  await refrescarCola();
}

async function anadirPagina() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !esUrlWeb(tab.url)) { mostrarAviso("Esta pestaña no es una página web."); return; }
  const r = await nativo("encolar", { url: tab.url, opciones: opcionesElegidas() });
  mostrarAviso(r.ok ? "" : `${r.error.mensaje} ${r.error.solucion || ""}`);
  await refrescarCola();
}

// --- Análisis de un enlace ---------------------------------------------------
async function analizar(url) {
  const caja = $("analisis-cuerpo");
  $("analisis").hidden = false;
  caja.replaceChildren(el("p", { clase: "nota" }, `Analizando ${nombreSitio(url)}…`));
  const r = await nativo("analizar", { url });
  if (!r.ok) { caja.replaceChildren(el("p", { clase: "error-caja" }, `${r.error.mensaje} ${r.error.causa || ""} ${r.error.solucion || ""}`)); return; }
  const d = r.datos, dg = d.diagnostico;
  const alturas = [...new Set(d.formatos.map((f) => f.altura).filter(Boolean))].sort((a, b) => b - a);
  const subs = Object.entries(d.subtitulos || {}).map(([k, auto]) => k + (auto ? " (auto)" : ""));
  const lineas = [
    el("div", { clase: "titulo" }, d.titulo),
    el("div", { clase: "meta" }, `${d.sitio}${d.autor ? " · " + d.autor : ""}${d.en_vivo ? " · en vivo" : ""}`),
    el("div", { clase: "meta" }, `Calidades: ${alturas.length ? alturas.map((a) => a + "p").join(", ") : "no informadas"} · Subtítulos: ${subs.join(", ") || "ninguno"}`),
    el("div", { clase: "meta" }, `Compatibilidad: ${dg.nivel.replaceAll("_", " ")} (${dg.motivo})`),
  ];
  for (const a of dg.alternativas || []) lineas.push(el("div", { clase: "meta" }, `Alternativa: ${a}`));
  lineas.push(el("div", { clase: "acciones" },
    el("button", { clase: "sec", textContent: "Cerrar", onclick: () => { $("analisis").hidden = true; } }),
    el("button", { textContent: "Añadir a la cola", onclick: async () => {
      const x = await nativo("encolar", { url, opciones: opcionesElegidas() });
      mostrarAviso(x.ok ? "" : `${x.error.mensaje} ${x.error.solucion || ""}`);
      $("analisis").hidden = x.ok; await refrescarCola();
    } })));
  caja.replaceChildren(el("div", { clase: "item" }, ...lineas));
}

// --- Cola -----------------------------------------------------------------------
async function accionTarea(accion, id) {
  const r = await nativo(accion, { id });
  if (!r.ok) mostrarAviso(`${r.error.mensaje} ${r.error.solucion || ""}`);
  await refrescarCola();
}

const ROTULO = { cancelar: "Cancelar", reintentar: "Reintentar", eliminar: "Eliminar", iniciar: "Descargar" };

function pintarTarea(t) {
  const hijos = [
    el("div", { clase: "titulo" }, t.titulo || t.url),
    el("div", { clase: "meta" }, `${t.sitio || nombreSitio(t.url)} · ${t.url}`),
    el("div", {}, el("span", { clase: `estado ${t.estado}` }, ETIQUETA_ESTADO[t.estado] || t.estado),
      document.createTextNode(t.progreso != null && ESTADOS_ACTIVOS.includes(t.estado) ? ` ${Math.round(t.progreso)} %` : "")),
  ];
  if (t.progreso != null && ["descargando", "procesando"].includes(t.estado)) hijos.push(el("progress", { max: 100, value: t.progreso }));
  for (const n of t.notas || []) hijos.push(el("div", { clase: "meta" }, n));
  if (t.error) {
    hijos.push(el("div", { clase: "error-caja" }, t.error.mensaje,
      ...(t.error.causa ? [el("div", {}, `Causa: ${t.error.causa}`)] : []),
      ...(t.error.solucion ? [el("div", {}, `Qué hacer: ${t.error.solucion}`)] : [])));
  }
  const botones = accionesDisponibles(t.estado).map((a) =>
    el("button", { clase: a === "eliminar" || a === "cancelar" ? "sec" : "", textContent: ROTULO[a], onclick: () => accionTarea(a, t.id) }));
  if (botones.length) hijos.push(el("div", { clase: "acciones" }, ...botones));
  return el("li", { clase: "item" }, ...hijos);
}

async function refrescarCola() {
  const f = $("filtro").value;
  const datos = { limite: 50 };
  if (f === "activas") datos.estados = ESTADOS_ACTIVOS;
  else if (f) datos.estados = [f];
  const r = await nativo("listar", datos);
  const ul = $("cola");
  if (!r.ok) { ul.replaceChildren(el("li", { clase: "vacio" }, "No se puede mostrar la cola sin conexión.")); return; }
  ul.replaceChildren(...(r.datos.tareas.length ? r.datos.tareas.map(pintarTarea) : [el("li", { clase: "vacio" }, "No hay descargas.")]));
  const n = r.datos.tareas.filter((t) => ESTADOS_ACTIVOS.includes(t.estado)).length;
  chrome.action.setBadgeText({ text: n && !f ? String(n) : "" });
}

// --- Arranque --------------------------------------------------------------------
$("btn-detectar").addEventListener("click", buscarEnPagina);
$("btn-anadir").addEventListener("click", anadirSeleccionados);
$("btn-pagina").addEventListener("click", anadirPagina);
$("btn-analizar-pagina").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && esUrlWeb(tab.url)) analizar(tab.url); else mostrarAviso("Esta pestaña no es una página web.");
});
$("filtro").addEventListener("change", refrescarCola);
$("btn-anadir").disabled = true;

(async function iniciar() {
  const { aviso, analizarUrl } = await chrome.storage.session.get(["aviso", "analizarUrl"]);
  if (aviso) { mostrarAviso(aviso); await chrome.storage.session.remove("aviso"); }
  await chrome.action.setBadgeText({ text: "" });
  if (await comprobarConexion()) {
    if (analizarUrl) { await chrome.storage.session.remove("analizarUrl"); analizar(analizarUrl); }
    await refrescarCola();
    setInterval(refrescarCola, 1500);
  }
})();
