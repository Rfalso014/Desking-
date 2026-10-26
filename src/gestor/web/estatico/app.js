// Página del gestor: habla con el servidor de este mismo equipo (POST /api) y recibe los cambios en vivo
// (GET /api/eventos). Las descargas las hace el servidor; aquí solo se piden y se muestran.

const TOKEN = document.querySelector('meta[name="gestor-token"]').content;
const VERSION = document.querySelector('meta[name="gestor-version"]').content;
const $ = (id) => document.getElementById(id);

function el(tag, props = {}, ...hijos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "clase") e.className = v;
    else if (k === "texto") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat()) if (h !== null && h !== undefined && h !== false) e.append(h);
  return e;
}
const icono = (nombre) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("class", "ic");
  const u = document.createElementNS("http://www.w3.org/2000/svg", "use");
  u.setAttribute("href", `#i-${nombre}`);
  s.append(u);
  return s;
};

// --- API ------------------------------------------------------------------------------------
let contador = 0;
async function api(accion, datos = {}) {
  let r;
  try {
    r = await fetch("/api", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ v: 1, id: `w${Date.now().toString(36)}${(contador++).toString(36)}`, accion, datos, token: TOKEN }),
    });
  } catch {
    throw { codigo: "comunicacion", mensaje: "No hay conexión con el servidor del gestor." };
  }
  const j = await r.json().catch(() => null);
  if (!j) throw { codigo: "comunicacion", mensaje: "Respuesta no válida del servidor." };
  if (!j.ok) {
    if (j.error && j.error.codigo === "no_vinculado") location.reload();   // el servidor se reinició: token nuevo
    throw j.error;
  }
  return j.datos;
}
const textoError = (e) => [e && e.mensaje, e && e.solucion].filter(Boolean).join(" ") || "Algo salió mal.";

// --- Avisos y diálogo -------------------------------------------------------------------------
function avisar(texto, error = false) {
  const t = el("div", { clase: `toast${error ? " error" : ""}`, role: error ? "alert" : "status", texto });
  $("avisos").append(t);
  setTimeout(() => t.remove(), error ? 7000 : 3500);
}

function dialogo(titulo, texto, { si = "Aceptar", entrada = null, peligro = false } = {}) {
  const d = $("dialogo");
  $("dialogo-titulo").textContent = titulo;
  $("dialogo-texto").replaceChildren(texto || "");
  let input = null;
  if (entrada !== null) {
    input = el("input", { clase: "entrada", value: entrada, maxlength: "60" });
    input.style.width = "100%";
    $("dialogo-texto").append(el("br"), input);
  }
  $("dialogo-si").textContent = si;
  $("dialogo-si").className = `boton ${peligro ? "peligro" : "primario"}`;
  return new Promise((resolver) => {
    const fin = (ok) => { d.close(); resolver(ok ? (input ? input.value.trim() : true) : null); };
    $("dialogo-si").onclick = () => fin(true);
    $("dialogo-no").onclick = () => fin(false);
    d.oncancel = (e) => { e.preventDefault(); fin(false); };
    if (input) input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); fin(true); } };
    d.showModal();
    (input || $("dialogo-si")).focus();
  });
}

// --- Estado ----------------------------------------------------------------------------------
const estado = {
  vista: "descargas", filtro: "todas", busqueda: "", tareas: new Map(), grupos: [], prefs: {},
  modo: "video", cuando: "instantanea",
};
const ACTIVAS = new Set(["pendiente", "analizando", "descargando", "procesando"]);
const ETIQUETA = { detectado: "En el grupo", pendiente: "En espera", analizando: "Analizando", descargando: "Descargando",
  procesando: "Procesando", completado: "Terminada", cancelado: "Cancelada", error: "Error" };

// --- Formatos ---------------------------------------------------------------------------------
function tamano(b) {
  if (!b) return "";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i >= 2 ? 1 : 0)} ${u[i]}`;
}
const velocidad = (bps) => (bps ? `${tamano(bps)}/s` : "");
function duracion(seg) {
  if (!seg && seg !== 0) return "";
  seg = Math.round(seg);
  const h = Math.floor(seg / 3600), m = Math.floor((seg % 3600) / 60), s = seg % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
const eta = (seg) => (seg ? `quedan ${duracion(seg)}` : "");
function sitio(t) {
  if (t.sitio && t.sitio !== "generic") return t.sitio;
  try { return new URL(t.url).hostname.replace(/^www\./, ""); } catch { return ""; }
}
function parsearTiempo(texto) {
  const p = String(texto).trim().split(":").map((x) => x.trim());
  if (!p.length || p.length > 3 || p.some((x) => !/^\d+(\.\d+)?$/.test(x))) return null;
  return p.reduce((acc, x) => acc * 60 + Number(x), 0);
}

// --- Tema --------------------------------------------------------------------------------------
const TEMAS = ["auto", "claro", "oscuro"];
function aplicarTema(t) {
  if (t === "claro") document.documentElement.dataset.theme = "light";
  else if (t === "oscuro") document.documentElement.dataset.theme = "dark";
  else delete document.documentElement.dataset.theme;
  $("btn-tema").querySelector("span").textContent = `Tema: ${t === "auto" ? "automático" : t}`;
}
let tema = "auto";
try { tema = localStorage.getItem("tema") || "auto"; } catch { /* sin almacenamiento */ }
aplicarTema(tema);
$("btn-tema").addEventListener("click", () => {
  tema = TEMAS[(TEMAS.indexOf(tema) + 1) % TEMAS.length];
  aplicarTema(tema);
  try { localStorage.setItem("tema", tema); } catch { /* sin almacenamiento */ }
});

// --- Navegación ---------------------------------------------------------------------------------
function irA(vista) {
  estado.vista = vista;
  for (const b of document.querySelectorAll(".nav")) {
    if (b.dataset.vista === vista) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  for (const v of ["descargas", "grupos", "ajustes"]) $(`vista-${v}`).hidden = v !== vista;
  if (vista === "ajustes") cargarAjustes();
  if (vista === "grupos") pintarGrupos();
}
for (const b of document.querySelectorAll(".nav")) b.addEventListener("click", () => irA(b.dataset.vista));

function segmentos(id, alCambiar) {
  const cont = $(id);
  const fijar = (valor) => {
    for (const b of cont.querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.valor === valor));
  };
  cont.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    fijar(b.dataset.valor);
    alCambiar(b.dataset.valor);
  });
  return fijar;
}

// --- Añadir ------------------------------------------------------------------------------------
segmentos("seg-modo", (v) => { estado.modo = v; $("campo-calidad").hidden = v !== "video"; });
const fijarCuando = segmentos("seg-cuando", (v) => { estado.cuando = v; pintarAnadir(); });

function pintarAnadir() {
  const enGrupo = estado.cuando === "grupo";
  $("sel-grupo").hidden = !enGrupo;
  $("btn-anadir").querySelector("span").textContent = enGrupo ? "Añadir al grupo" : "Descargar";
}

function pintarSelectorGrupos() {
  const sel = $("sel-grupo");
  const actual = sel.value || estado.prefs.grupo_activo;
  sel.replaceChildren(...estado.grupos.map((g) => el("option", { value: g.nombre, texto: g.nombre })),
    el("option", { value: "__nuevo", texto: "+ Grupo nuevo…" }));
  sel.value = estado.grupos.some((g) => g.nombre === actual) ? actual : (estado.grupos[0] || {}).nombre || "";
}
$("sel-grupo").addEventListener("change", async (e) => {
  if (e.target.value !== "__nuevo") return;
  const nombre = await dialogo("Grupo nuevo", "¿Cómo se llama?", { si: "Crear", entrada: "" });
  if (nombre) await crearGrupo(nombre);
  pintarSelectorGrupos();
  if (nombre) $("sel-grupo").value = nombre;
});

function filaTramo() {
  const fila = el("div", { clase: "recorte-fila" },
    el("input", { clase: "entrada", placeholder: "Desde", "aria-label": "Desde", inputmode: "numeric" }),
    el("span", { clase: "tenue", texto: "a" }),
    el("input", { clase: "entrada", placeholder: "Hasta", "aria-label": "Hasta", inputmode: "numeric" }),
    el("button", { type: "button", clase: "icono-boton", title: "Quitar este trozo", onclick: () => { fila.remove(); } }, icono("x")));
  $("tramos").append(fila);
}
$("btn-recortar").addEventListener("click", () => {
  const abrir = $("recorte").hidden;
  $("recorte").hidden = !abrir;
  $("btn-recortar").setAttribute("aria-expanded", String(abrir));
  if (abrir && !$("tramos").children.length) filaTramo();
});
$("btn-tramo").addEventListener("click", () => {
  if ($("tramos").children.length < 10) filaTramo();
});

function leerTramos() {
  if ($("recorte").hidden) return [];
  const tramos = [];
  for (const fila of $("tramos").children) {
    const [a, b] = [...fila.querySelectorAll("input")].map((i) => i.value);
    if (!a.trim() && !b.trim()) continue;
    const desde = parsearTiempo(a), hasta = parsearTiempo(b);
    if (desde === null || hasta === null) throw new Error("Escribe los tiempos como 1:30 o 01:02:15.");
    if (desde >= hasta) throw new Error("Cada trozo debe terminar después de empezar.");
    tramos.push([desde, hasta]);
  }
  return tramos;
}

function opcionesAnadir() {
  const op = { modo: estado.modo, carpeta_propia: $("chk-carpeta").checked };
  if (estado.modo === "video" && $("sel-calidad").value) op.altura_max = Number($("sel-calidad").value);
  const tramos = leerTramos();
  if (tramos.length) {
    if (!["video", "audio"].includes(estado.modo)) throw new Error("Recortar solo sirve para video o audio.");
    op.tramos = tramos;
    op.corte_exacto = $("chk-exacto").checked;
  }
  return op;
}

$("form-anadir").addEventListener("submit", async (e) => {
  e.preventDefault();
  const error = $("error-anadir");
  error.hidden = true;
  let datos;
  try {
    datos = { url: $("url").value.trim(), opciones: opcionesAnadir(), modo: estado.cuando };
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
    return;
  }
  if (estado.cuando === "grupo" && $("sel-grupo").value && $("sel-grupo").value !== "__nuevo") datos.grupo = $("sel-grupo").value;
  $("btn-anadir").disabled = true;
  try {
    let r;
    try {
      r = await api("anadir", datos);
    } catch (err) {
      if (!err || err.codigo !== "duplicado") throw err;
      const otra = await dialogo("Ya está en tu lista", `${err.causa || ""} ¿Quieres añadirlo otra vez?`, { si: "Añadir otra vez" });
      if (!otra) return;
      r = await api("anadir", { ...datos, forzar: true });
    }
    recibirTarea(r);
    $("url").value = "";
    avisar(r.modo === "grupo" ? `Añadido al grupo «${r.grupo}».` : "Descarga iniciada.");
  } catch (err) {
    error.textContent = textoError(err);
    error.hidden = false;
  } finally {
    $("btn-anadir").disabled = false;
  }
});

// --- Lista de descargas ---------------------------------------------------------------------------
segmentos("seg-filtro", (v) => { estado.filtro = v; pintarLista(); });
$("buscar").addEventListener("input", (e) => { estado.busqueda = e.target.value.trim().toLowerCase(); pintarLista(); });
$("btn-limpiar").addEventListener("click", async () => {
  try {
    const r = await api("limpiar");
    for (const [id, t] of estado.tareas) if (["completado", "cancelado", "error"].includes(t.estado)) estado.tareas.delete(id);
    avisar(`Se quitaron ${r.eliminadas} de la lista. Los archivos siguen en su carpeta.`);
    pintarLista();
  } catch (err) { avisar(textoError(err), true); }
});

async function accion(nombre, t) {
  try {
    if (nombre === "eliminar" && ACTIVAS.has(t.estado)) {
      if (!await dialogo("¿Quitar esta descarga?", "Se detendrá y se borrará lo que llevaba descargado.", { si: "Quitar", peligro: true })) return;
    }
    const r = await api(nombre, { id: t.id });
    if (nombre === "eliminar") { estado.tareas.delete(t.id); pintarLista(); }
    else if (r && r.id) recibirTarea(r);
  } catch (err) { avisar(textoError(err), true); }
}

function itemTarea(t) {
  const activa = ACTIVAS.has(t.estado);
  const mini = el("div", { clase: "mini" });
  if (t.miniatura && /^https?:/.test(t.miniatura)) {
    const img = el("img", { src: t.miniatura, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
    img.addEventListener("error", () => img.remove());
    mini.append(img);
  } else mini.append(icono(t.opciones && t.opciones.modo === "audio" ? "musica" : "video"));

  const meta = el("div", { clase: "item-meta" },
    el("span", { clase: `estado e-${t.estado}` }, el("i"), ETIQUETA[t.estado] || t.estado),
    sitio(t) && el("span", { texto: sitio(t) }),
    t.duracion && el("span", { texto: duracion(t.duracion) }),
    t.opciones && t.opciones.modo === "audio" && el("span", { clase: "chip", texto: "Solo audio" }),
    t.opciones && t.opciones.tramos && t.opciones.tramos.length && el("span", { clase: "chip", texto: `✂ ${t.opciones.tramos.length} trozo${t.opciones.tramos.length > 1 ? "s" : ""}` }),
    t.grupo && el("span", { clase: "chip acento", texto: t.grupo }),
    activa && t.progreso != null && el("span", { texto: `${Math.round(t.progreso)} %` }),
    activa && velocidad(t.velocidad) && el("span", { texto: velocidad(t.velocidad) }),
    activa && eta(t.eta) && el("span", { texto: eta(t.eta) }));

  const cuerpo = el("div", { clase: "item-cuerpo" },
    el("div", { clase: "item-titulo", title: t.titulo || t.url, texto: t.titulo || t.url }), meta);
  if (activa) {
    const barra = el("div", { clase: `progreso${t.progreso == null || t.estado !== "descargando" ? " indeterminado" : ""}` }, el("i"));
    barra.firstChild.style.width = `${Math.max(2, t.progreso || 0)}%`;
    cuerpo.append(barra);
  }
  if (t.estado === "error" && t.error) {
    cuerpo.append(el("div", { clase: "item-error" }, el("b", { texto: t.error.mensaje }),
      t.error.solucion ? ` ${t.error.solucion}` : ""));
  } else if (t.notas && t.notas.length && !activa) {
    cuerpo.append(el("div", { clase: "item-nota", texto: t.notas[t.notas.length - 1] }));
  }

  const botones = [];
  const boton = (nombre, titulo, ic, clase = "") =>
    el("button", { clase: `icono-boton ${clase}`, title: titulo, "aria-label": titulo, onclick: () => accion(nombre, t) }, icono(ic));
  if (t.estado === "detectado") botones.push(el("button", { clase: "boton primario", onclick: () => accion("iniciar", t) }, icono("descarga"), "Descargar"));
  if (t.estado === "completado" && t.carpeta_final) botones.push(boton("abrir_carpeta", "Abrir carpeta", "carpeta"));
  if (["error", "cancelado"].includes(t.estado)) botones.push(boton("reintentar", "Reintentar", "reintentar"));
  if (activa) botones.push(boton("cancelar", "Cancelar", "x"));
  botones.push(boton("eliminar", activa ? "Detener y quitar" : "Quitar de la lista", "papelera", "peligro"));
  return el("li", { clase: "item", "data-id": t.id }, mini, cuerpo, el("div", { clase: "item-acciones" }, botones));
}

const SECCIONES = [
  { id: "curso", titulo: "En curso", estados: ["descargando", "procesando", "analizando", "pendiente"] },
  { id: "grupo", titulo: "Esperando en grupos", estados: ["detectado"] },
  { id: "listas", titulo: "Terminadas", estados: ["completado"] },
  { id: "errores", titulo: "Con error o canceladas", estados: ["error", "cancelado"] },
];
const FILTRO = { todas: ["curso", "grupo", "listas", "errores"], curso: ["curso", "grupo"], listas: ["listas"], errores: ["errores"] };

let pintando = false;
function pintarLista() {
  if (pintando) return;
  pintando = true;
  requestAnimationFrame(() => { pintando = false; pintarListaYa(); });
}
function pintarListaYa() {
  const texto = estado.busqueda;
  const todas = [...estado.tareas.values()].filter((t) => !texto
    || `${t.titulo || ""} ${t.url} ${t.sitio || ""} ${t.grupo || ""}`.toLowerCase().includes(texto));
  const cont = $("secciones");
  cont.replaceChildren();
  let hay = false;
  for (const s of SECCIONES.filter((x) => FILTRO[estado.filtro].includes(x.id))) {
    const ts = todas.filter((t) => s.estados.includes(t.estado));
    if (!ts.length) continue;
    hay = true;
    const extra = [];
    if (s.id === "grupo") extra.push(el("button", { clase: "boton texto", onclick: () => irA("grupos") }, "Ver grupos"));
    if (s.id === "curso") extra.push(el("button", { clase: "boton texto", onclick: cancelarTodas }, "Cancelar todas"));
    cont.append(el("section", { clase: "seccion-lista" },
      el("header", {}, el("h2", { texto: s.titulo }), el("span", { clase: "chip", texto: String(ts.length) }), el("span", { clase: "espacio" }), extra),
      el("ul", { clase: "tarjeta lista" }, ts.map(itemTarea))));
  }
  if (!hay) {
    cont.append(el("div", { clase: "tarjeta vacio" },
      el("b", { texto: texto ? "Nada coincide con la búsqueda" : "Todavía no hay descargas aquí" }),
      texto ? "Prueba con otra palabra." : "Pega un enlace arriba, o usa «＋ Añadir» sobre un video con la extensión."));
  }
  const curso = [...estado.tareas.values()].filter((t) => ACTIVAS.has(t.estado)).length;
  $("cuenta-activas").hidden = !curso;
  $("cuenta-activas").textContent = curso;
  document.title = curso ? `(${curso}) Gestor de Descargas` : "Gestor de Descargas";
}

async function cancelarTodas() {
  if (!await dialogo("¿Cancelar todas?", "Se detiene todo lo que está descargando o en espera.", { si: "Cancelar todas", peligro: true })) return;
  try { const r = await api("cancelar_todas"); avisar(`Canceladas: ${r.canceladas}.`); } catch (err) { avisar(textoError(err), true); }
}

function recibirTarea(t) {
  estado.tareas.set(t.id, t);
  pintarLista();
}

// --- Grupos -----------------------------------------------------------------------------------------
async function cargarGrupos() {
  const r = await api("grupos");
  estado.grupos = r.grupos;
  const esperando = estado.grupos.reduce((n, g) => n + g.esperando, 0);
  $("cuenta-grupos").hidden = !esperando;
  $("cuenta-grupos").textContent = esperando;
  pintarSelectorGrupos();
  if (estado.vista === "grupos") pintarGrupos();
}

async function crearGrupo(nombre) {
  try {
    const r = await api("grupo_crear", { nombre });
    estado.grupos = r.grupos;
    estado.prefs.grupo_activo = nombre;
    avisar(`Grupo «${nombre}» creado y activo.`);
    pintarGrupos();
  } catch (err) { avisar(textoError(err), true); }
}

$("form-grupo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const nombre = $("nombre-grupo").value.trim();
  if (!nombre) return;
  await crearGrupo(nombre);
  $("nombre-grupo").value = "";
  cargarGrupos();
});

async function accionGrupo(nombre, g) {
  try {
    if (nombre === "grupo_eliminar") {
      const texto = g.esperando ? `Se quitan también los ${g.esperando} enlaces que esperan en él. Lo ya descargado no se toca.` : "Lo ya descargado no se toca.";
      if (!await dialogo(`¿Eliminar «${g.nombre}»?`, texto, { si: "Eliminar", peligro: true })) return;
    }
    let datos = { nombre: g.nombre };
    if (nombre === "grupo_renombrar") {
      const nuevo = await dialogo("Renombrar grupo", "Nombre nuevo:", { si: "Renombrar", entrada: g.nombre });
      if (!nuevo || nuevo === g.nombre) return;
      datos = { nombre: g.nombre, nuevo };
    }
    const r = await api(nombre, datos);
    if (nombre === "grupo_iniciar") avisar(`Empezaron ${r.iniciadas} descargas del grupo «${g.nombre}».`);
    if (nombre === "grupo_activar") estado.prefs.grupo_activo = g.nombre;
    await cargarGrupos();
    await cargarTareas();
  } catch (err) { avisar(textoError(err), true); }
}

function pintarGrupos() {
  $("txt-carpeta-grupo").textContent = estado.prefs.carpeta_grupo === false
    ? "Las descargas de un grupo se guardan como las demás (puedes cambiarlo en Ajustes)."
    : "Cada grupo se guarda en una carpeta con su nombre (puedes cambiarlo en Ajustes).";
  const lista = $("lista-grupos");
  lista.replaceChildren(...estado.grupos.map((g) => {
    const numeros = el("div", { clase: "grupo-numeros" },
      el("span", {}, el("b", { texto: String(g.esperando) }), "esperando"),
      el("span", {}, el("b", { texto: String(g.activas) }), "en curso"),
      el("span", {}, el("b", { texto: String(g.listas) }), "terminadas"),
      g.errores ? el("span", {}, el("b", { texto: String(g.errores) }), "con error") : null);
    const enEspera = [...estado.tareas.values()].filter((t) => t.grupo === g.nombre && t.estado === "detectado").slice(0, 4);
    return el("article", { clase: `tarjeta grupo${g.activo ? " activo" : ""}` },
      el("div", { clase: "grupo-cab" }, el("h3", { texto: g.nombre, title: g.nombre }), g.activo ? el("span", { clase: "chip acento", texto: "Activo" }) : null),
      numeros,
      enEspera.length ? el("ul", { clase: "tenue chico" }, enEspera.map((t) => el("li", { texto: t.titulo || t.url }))) : null,
      el("div", { clase: "grupo-acciones" },
        el("button", { clase: "boton primario", disabled: !g.esperando, onclick: () => accionGrupo("grupo_iniciar", g) }, icono("descarga"),
          g.esperando ? `Descargar grupo (${g.esperando})` : "Nada que descargar"),
        !g.activo && el("button", { clase: "boton borde", title: "Lo que añadas «Al grupo» irá aquí", onclick: () => accionGrupo("grupo_activar", g) }, "Usar este"),
        el("button", { clase: "boton texto", onclick: () => accionGrupo("grupo_renombrar", g) }, "Renombrar"),
        el("button", { clase: "boton texto", onclick: () => accionGrupo("grupo_eliminar", g) }, "Eliminar")));
  }));
}

// --- Ajustes ------------------------------------------------------------------------------------------
function pintarPreferencias() {
  const p = estado.prefs;
  for (const c of document.querySelectorAll("[data-pref]")) {
    const v = p[c.dataset.pref];
    if (c.type === "checkbox") c.checked = !!v;
    else c.value = v === null || v === undefined ? "" : String(v);
  }
  $("aj-carpeta").textContent = p.carpeta_raiz || "—";
  $("aj-idiomas").textContent = (p.idiomas_subtitulos || []).join(", ");
  $("chk-carpeta").checked = p.carpeta_propia !== false;
  if (!pintarPreferencias.hecho) {           // la primera vez: lo de «al añadir» toma los valores por defecto
    pintarPreferencias.hecho = true;
    estado.cuando = p.modo_anadir || "instantanea";
    fijarCuando(estado.cuando);
    if (p.altura_max) $("sel-calidad").value = String(p.altura_max);
    pintarAnadir();
  }
}

for (const c of document.querySelectorAll("[data-pref]")) {
  c.addEventListener("change", async () => {
    let v = c.type === "checkbox" ? c.checked : c.value;
    if (c.dataset.tipo === "numero") v = v === "" ? null : Number(v);
    try {
      estado.prefs = await api("preferencias", { cambios: { [c.dataset.pref]: v } });
      pintarPreferencias();
      avisar("Guardado.");
    } catch (err) {
      avisar(textoError(err), true);
      pintarPreferencias();
    }
  });
}

let relojCodigo = null;
async function cargarAjustes() {
  try {
    estado.prefs = await api("preferencias");
    pintarPreferencias();
    await pintarVinculos();
  } catch (err) { avisar(textoError(err), true); }
  clearInterval(relojCodigo);
  relojCodigo = setInterval(() => { if (estado.vista === "ajustes") pintarVinculos(); else clearInterval(relojCodigo); }, 30000);
  refrescarActualizacion(false);
}

async function pintarVinculos(revocar) {
  const r = await api("vinculos", revocar ? { revocar } : {});
  $("aj-codigo").textContent = r.codigo;
  $("aj-vinculos").replaceChildren(...r.vinculos.map((v) => el("li", {},
    el("span", {}, el("b", { texto: v.nombre }), el("span", { clase: "tenue chico", texto: `  vinculada ${new Date(v.creado).toLocaleDateString()}` })),
    el("button", { clase: "boton texto", onclick: async () => {
      if (await dialogo("¿Desvincular?", `«${v.nombre}» dejará de poder enviar descargas.`, { si: "Desvincular", peligro: true })) pintarVinculos(v.id);
    } }, "Desvincular"))));
  if (!r.vinculos.length) $("aj-vinculos").append(el("li", { clase: "tenue" }, "Ninguna extensión vinculada todavía."));
}

$("btn-cambiar-carpeta").addEventListener("click", async () => {
  avisar("Elige la carpeta en la ventana que se abrió en tu escritorio.");
  try { estado.prefs = await api("elegir_carpeta"); pintarPreferencias(); } catch (err) { avisar(textoError(err), true); }
});
$("btn-abrir-raiz").addEventListener("click", () => api("abrir_raiz").catch((err) => avisar(textoError(err), true)));
$("btn-apagar").addEventListener("click", async () => {
  if (!await dialogo("¿Apagar el gestor?", "La página y la extensión dejarán de funcionar hasta que lo enciendas con GestorDescargas.exe.", { si: "Apagar", peligro: true })) return;
  await api("apagar").catch(() => {});
  conexion(false, "Apagado");
});
$("btn-reiniciar").addEventListener("click", async () => {
  if (!await dialogo("¿Reiniciar el gestor?", "Las descargas en curso se retoman solas al volver.", { si: "Reiniciar" })) return;
  await api("reiniciar").catch(() => {});
  conexion(false, "Reiniciando…");
});

async function refrescarActualizacion(buscar) {
  try {
    const e = await api("actualizacion", buscar ? { buscar: true } : {});
    const p = e.pendientes || [];
    $("act-estado").textContent = e.mensaje || (p.length ? `Hay novedades: ${p.map((x) => `${x.nombre} ${x.nueva || ""}`).join(", ")}.`
      : "Los sitios cambian a menudo: mantener yt-dlp al día evita muchos fallos.");
    $("btn-actualizar").hidden = !p.length;
  } catch { /* sin actualizador: se deja el texto */ }
}
$("btn-buscar-act").addEventListener("click", () => { refrescarActualizacion(true); setTimeout(() => refrescarActualizacion(false), 5000); });
$("btn-actualizar").addEventListener("click", async () => {
  try { const e = await api("actualizar"); $("act-estado").textContent = e.mensaje || "Actualizando…"; } catch (err) { avisar(textoError(err), true); }
});

// --- Conexión y eventos en vivo -------------------------------------------------------------------------
function conexion(ok, texto) {
  $("conexion").className = `conexion ${ok ? "ok" : "mal"}`;
  $("conexion").querySelector("span").textContent = texto || (ok ? "Conectado" : "Sin conexión");
  $("banda-conexion").hidden = ok;
}

let fuente = null;
function escuchar() {
  if (fuente) fuente.close();
  fuente = new EventSource(`/api/eventos?token=${encodeURIComponent(TOKEN)}`);
  fuente.onopen = () => { conexion(true); };
  fuente.onmessage = (m) => {
    let d;
    try { d = JSON.parse(m.data); } catch { return; }
    if (d.tipo === "tarea") {
      const antes = estado.tareas.get(d.tarea.id);
      recibirTarea(d.tarea);
      if (antes && antes.estado !== d.tarea.estado && ["completado", "error"].includes(d.tarea.estado)) {
        avisar(d.tarea.estado === "completado" ? `Terminada: ${d.tarea.titulo || "descarga"}` : `Falló: ${d.tarea.titulo || d.tarea.url}`, d.tarea.estado === "error");
        cargarGrupos().catch(() => {});
      }
      if (!antes || antes.estado !== d.tarea.estado) cargarGrupos().catch(() => {});
    } else if (d.tipo === "eliminado") {
      if (d.id === "*") cargarTareas(); else { estado.tareas.delete(d.id); pintarLista(); }
      cargarGrupos().catch(() => {});
    } else if (d.tipo === "grupos") {
      cargarGrupos().catch(() => {});
    }
  };
  fuente.onerror = () => {
    conexion(false);
    if (fuente.readyState === EventSource.CLOSED) volverAConectar();
  };
}

// Si el servidor se apagó o se reinició, se espera a que vuelva; con un reinicio cambia el token y se recarga la página.
let esperando = false;
async function volverAConectar() {
  if (esperando) return;
  esperando = true;
  for (;;) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const r = await fetch("/api/salud", { cache: "no-store" });
      if (r.ok) break;
    } catch { /* sigue apagado */ }
  }
  esperando = false;
  try {
    const p = await api("ping");
    if (!p.vinculado) return location.reload();
  } catch { return; }
  await cargarTodo();
  escuchar();
}

async function cargarTareas() {
  const r = await api("listar", { limite: 200 });
  estado.tareas = new Map(r.tareas.map((t) => [t.id, t]));
  pintarLista();
}

async function cargarTodo() {
  estado.prefs = await api("preferencias");
  pintarPreferencias();
  await Promise.all([cargarTareas(), cargarGrupos()]);
}

$("aj-version").textContent = VERSION;
$("aj-direccion").textContent = location.origin;
cargarTodo().then(() => conexion(true)).catch((err) => { conexion(false); avisar(textoError(err), true); });
escuchar();
if (["#ajustes", "#grupos"].includes(location.hash)) irA(location.hash.slice(1));   // p. ej. «Ver el código» desde la extensión
