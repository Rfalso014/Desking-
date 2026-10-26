// Service worker: menú contextual, detección de enlaces directos de video y puente con el gestor web
// (http://127.0.0.1:7878, en este mismo equipo). La extensión NO descarga nada: lo hace el gestor.
import {
  ELEMENTOS_POR_DEFECTO, ESTADOS_ACTIVOS, PUERTO_POR_DEFECTO, claveVideo, construirOpciones, elegirUrlParaMenu, elegirUrlParaVideo,
  esMedioDirecto, esUrlWeb, mensajeSinServidor, opcionesRecorte, ordenarMedios, soloAudio, validarTramos,
} from "./util.js";

const TIEMPO_ESPERA_MS = 20000;
let contador = 0;

const fallo = (e) => ({ ok: false, error: e });

async function puerto() {
  const { puerto: p } = await chrome.storage.local.get("puerto");
  return Number.isInteger(p) && p > 0 && p < 65536 ? p : PUERTO_POR_DEFECTO;
}
async function urlGestor() {
  return `http://127.0.0.1:${await puerto()}/`;
}

// Token de vinculación: lo entrega el gestor cuando el usuario escribe su código. Se guarda solo en este navegador.
async function leerToken() {
  const { token } = await chrome.storage.local.get("token");
  return typeof token === "string" ? token : undefined;
}

/** Envía una acción al gestor y devuelve su respuesta ({ok, datos} o {ok:false, error}). */
async function enviar(accion, datos = {}) {
  const token = accion === "emparejar" ? undefined : await leerToken();
  const id = `e${Date.now().toString(36)}${(contador++).toString(36)}`;
  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), TIEMPO_ESPERA_MS);
  let r;
  try {
    const resp = await fetch(`${await urlGestor()}api`, {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: control.signal,
      body: JSON.stringify({ v: 1, id, accion, datos, ...(token ? { token } : {}) }),
    });
    r = await resp.json();
  } catch (e) {
    return fallo(mensajeSinServidor(e && e.name === "AbortError"));
  } finally {
    clearTimeout(reloj);
  }
  if (r.ok && accion === "ping") comprobarRecarga(r.datos);
  if (r.ok && accion === "emparejar" && r.datos && r.datos.token) await chrome.storage.local.set({ token: r.datos.token });
  if (r.ok && accion === "desvincular") await chrome.storage.local.remove("token");
  return r;
}

/**
 * Tras «Actualizar» el gestor deja una marca nueva (o trae otra versión de la extensión): la extensión se recarga
 * para leer sus archivos nuevos. Cada marca/versión se atiende una sola vez (sin bucles).
 */
async function comprobarRecarga(d) {
  if (!d || !d.vinculado) return;
  const { recargaVista, recargadaPara } = await chrome.storage.local.get(["recargaVista", "recargadaPara"]);
  const propia = chrome.runtime.getManifest().version;
  if (recargaVista === undefined) {
    await chrome.storage.local.set({ recargaVista: d.actualizacion_id || 0 });   // primera vez: solo se apunta
  } else if (d.actualizacion_id && d.actualizacion_id !== recargaVista) {
    await chrome.storage.local.set({ recargaVista: d.actualizacion_id });
    return chrome.runtime.reload();
  }
  if (d.version_extension && d.version_extension !== propia && d.version_extension !== recargadaPara) {
    await chrome.storage.local.set({ recargadaPara: d.version_extension });
    chrome.runtime.reload();
  }
}

chrome.runtime.onStartup.addListener(() => { enviar("ping"); });

// --- Enlaces directos de video vistos en la red ----------------------------------------------------
// Muchos sitios cargan el video con su propio reproductor (m3u8, mpd, mp4): el video no aparece en el HTML y
// yt-dlp no lo encuentra. Aquí se apuntan esos enlaces por pestaña (solo en la memoria de la sesión del navegador)
// para mandárselos al gestor como respaldo. No se envía nada hasta que el usuario añade un video.
const MAX_MEDIOS = 15;
const claveMedios = (tabId) => `medios:${tabId}`;

chrome.webRequest.onResponseStarted.addListener(async (d) => {
  if (d.tabId < 0 || d.statusCode >= 400) return;
  const cabecera = (n) => (d.responseHeaders || []).find((h) => h.name.toLowerCase() === n);
  const tipo = cabecera("content-type"), largo = cabecera("content-length");
  const medio = esMedioDirecto(d.url, tipo && tipo.value, largo && Number(largo.value));
  if (!medio) return;
  const clave = claveMedios(d.tabId);
  const previos = (await chrome.storage.session.get(clave))[clave] || [];
  if (previos.some((m) => m.url === d.url)) return;
  await chrome.storage.session.set({ [clave]: ordenarMedios([{ ...medio, url: d.url, visto: Date.now() }, ...previos]).slice(0, MAX_MEDIOS) });
}, { urls: ["http://*/*", "https://*/*"], types: ["media", "xmlhttprequest", "other"] }, ["responseHeaders"]);

// Al navegar a otra página (o cerrar la pestaña) lo visto ya no sirve.
chrome.tabs.onUpdated.addListener((tabId, cambio) => {
  if (cambio.url) chrome.storage.session.remove([claveMedios(tabId), `recursos:${tabId}`]);
});
chrome.tabs.onRemoved.addListener((tabId) => { chrome.storage.session.remove([claveMedios(tabId), `recursos:${tabId}`]); });

async function mediosDe(tabId) {
  if (tabId == null || tabId < 0) return [];
  return (await chrome.storage.session.get(claveMedios(tabId)))[claveMedios(tabId)] || [];
}

// --- Sesión del sitio (cookies): solo al añadir y solo de ese sitio -----------------------------------------
async function cookiesPara(urls) {
  const { usarSesion } = await chrome.storage.local.get("usarSesion");
  if (usarSesion === false) return [];
  const vistas = new Map();
  for (const u of urls.filter(esUrlWeb).slice(0, 4)) {
    try {
      for (const c of await chrome.cookies.getAll({ url: u })) {
        vistas.set(`${c.domain}|${c.path}|${c.name}`, { name: c.name, value: c.value, domain: c.domain, path: c.path,
          secure: c.secure, expirationDate: c.expirationDate });
      }
    } catch { /* sin permiso para ese sitio */ }
  }
  return [...vistas.values()].slice(0, 400);
}

// --- Añadir ---------------------------------------------------------------------------------------------
/**
 * Añade `url` con las opciones que arma `armar` (a partir de «qué descargar por defecto») y el modo elegido
 * (descargar ya / al grupo: lo guarda el gestor). `pagina` = la pestaña de donde viene. Si el video ES esa página
 * (y no una miniatura que lleva a otro video), se adjuntan los enlaces directos vistos en la red, por si la página
 * sola no basta. La sesión del sitio va siempre (salvo que se desactive), solo para esa descarga.
 * Si el video ya estaba en la lista, el gestor responde «duplicado»: se devuelve qué opciones faltaron (`repetidas`)
 * para que el usuario confirme y se vuelvan a enviar SOLO esas, con `forzar`.
 */
async function anadirConLoElegido(url, pagina, armar, repetidasConfirmadas = null) {
  let conjuntos;
  if (Array.isArray(repetidasConfirmadas)) {
    conjuntos = repetidasConfirmadas.filter((o) => o && typeof o === "object").slice(0, 2);
  } else {
    const { elementos } = await chrome.storage.local.get("elementos");
    try {
      conjuntos = armar({ ...ELEMENTOS_POR_DEFECTO, ...(elementos || {}) });
    } catch (e) {
      return fallo({ codigo: "configuracion", mensaje: e.mensaje || "Revisa «qué descargar» en los Ajustes.", solucion: e.solucion });
    }
  }
  const origen = pagina && esUrlWeb(pagina.url) ? pagina.url : undefined;
  const mismaPagina = !!origen && claveVideo(origen) === claveVideo(url);
  const medios = mismaPagina ? (await mediosDe(pagina.id)).map((m) => m.url).slice(0, 4) : [];
  const cookies = await cookiesPara([url, ...(origen ? [origen] : []), ...medios]);
  const forzar = Array.isArray(repetidasConfirmadas);
  let ultima = fallo({ mensaje: "Nada que añadir." });
  const repetidas = [];
  let errorRepetido = null;
  for (const base of conjuntos) {
    const opciones = { ...base };
    if (medios.length) opciones.medios = medios;
    if (mismaPagina && pagina.title) opciones.titulo_pagina = String(pagina.title).slice(0, 300);
    ultima = await enviar("anadir", { url, origen, opciones, ...(cookies.length ? { cookies } : {}), ...(forzar ? { forzar: true } : {}) });
    if (!ultima.ok && ultima.error && ultima.error.codigo === "duplicado") { repetidas.push(base); errorRepetido = ultima.error; continue; }
    if (!ultima.ok) return ultima;
  }
  if (repetidas.length) return { ok: false, error: errorRepetido, repetidas };
  actualizarInsignia();
  return ultima;
}

const conDefecto = (audio) => (base) => construirOpciones(audio ? soloAudio(base) : base);

// Clic derecho sobre un video que ya está en la lista: una notificación pregunta si añadirlo otra vez.
async function preguntarRepetido(url, pagina, r) {
  const id = `repetido-${Date.now()}`;
  await chrome.storage.session.set({ [id]: { url, pagina, repetidas: r.repetidas } });
  chrome.notifications.create(id, {
    type: "basic", iconUrl: "icons/128.png", title: "Este video ya está en tu lista",
    message: [r.error && r.error.causa, "¿Quieres añadirlo otra vez?"].filter(Boolean).join(" "),
    buttons: [{ title: "Añadir otra vez" }, { title: "No, déjalo" }], priority: 1,
  });
}

chrome.notifications.onButtonClicked.addListener(async (id, boton) => {
  if (!id.startsWith("repetido-")) return;
  const datos = (await chrome.storage.session.get(id))[id];
  chrome.notifications.clear(id);
  await chrome.storage.session.remove(id);
  if (!datos || boton !== 0) return;
  const r = await anadirConLoElegido(datos.url, datos.pagina, conDefecto(false), datos.repetidas);
  if (!r.ok) await avisar((r.error && r.error.mensaje) || "No se pudo añadir.");
});
chrome.notifications.onClosed.addListener((id) => { if (id.startsWith("repetido-")) chrome.storage.session.remove(id); });

async function avisar(texto) {
  await chrome.action.setBadgeBackgroundColor({ color: "#a63a32" });
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.storage.session.set({ aviso: texto });
}

// --- Menú contextual (un solo elemento: Chrome lo muestra directamente, sin submenú) ------------------------
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "anadir", title: "Descargar con Gestor de Descargas", contexts: ["link", "video", "audio", "image", "page"] });
  });
});

// La interfaz es una barra lateral: el ícono de la extensión la abre y la cierra.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = elegirUrlParaMenu(info, tab);
  if (!url) {
    await avisar("No se encontró el enlace de este video: ábrelo en su propia página o haz clic derecho sobre su miniatura.");
    return;
  }
  const pagina = tab ? { id: tab.id, url: tab.url, title: tab.title } : null;
  const r = await anadirConLoElegido(url, pagina, conDefecto(false));
  if (!r.ok && r.repetidas) return preguntarRepetido(url, pagina, r);
  if (!r.ok) await avisar((r.error && r.error.mensaje) || "No se pudo añadir.");
});

// --- Insignia: azul = descargando; ámbar = esperando en grupos ----------------------------------------------
async function actualizarInsignia() {
  const r = await enviar("listar", { estados: [...ESTADOS_ACTIVOS, "detectado"], limite: 200 });
  const tareas = r.ok ? r.datos.tareas : [];
  const activas = tareas.filter((t) => t.estado !== "detectado").length;
  const enGrupo = tareas.length - activas;
  await chrome.action.setBadgeBackgroundColor({ color: activas ? "#2f5f8a" : "#8a5a00" });
  await chrome.action.setBadgeText({ text: activas ? String(activas) : enGrupo ? String(enGrupo) : "" });
}

// --- Mensajes del panel lateral y de las páginas --------------------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  if (sender.id !== chrome.runtime.id || !msg) return false;
  if (msg.tipo === "olvidar-token") {
    chrome.storage.local.remove("token").then(() => responder({ ok: true }));
    return true;
  }
  if (msg.tipo === "gestor") {                               // el panel lateral pide algo al gestor
    enviar(msg.accion, msg.datos).then((r) => { responder(r); if (r.ok && /^(cancelar|eliminar|iniciar|grupo_iniciar|limpiar)/.test(msg.accion)) actualizarInsignia(); });
    return true;
  }
  if (msg.tipo === "medios") {                               // el panel lateral muestra lo visto en la pestaña
    mediosDe(msg.tabId).then(responder);
    return true;
  }
  if (msg.tipo === "anadir-panel") {                         // el panel lateral añade con lo que eligió ahí
    anadirConLoElegido(msg.url, msg.pagina || null, () => msg.conjuntos, Array.isArray(msg.repetidas) ? msg.repetidas : null).then(responder);
    return true;
  }
  if (msg.tipo === "detectar-pagina" || msg.tipo === "recortar") {      // botones sobre un video (content.js)
    const url = elegirUrlParaVideo(msg.candidatas);
    if (!url) {
      responder(fallo({ codigo: "url_invalida", mensaje: "No se encontró el enlace de este video.",
        solucion: "Abre el video en su propia página, o haz clic derecho sobre su miniatura → «Descargar con Gestor de Descargas»." }));
      return false;
    }
    const pagina = sender.tab ? { id: sender.tab.id, url: sender.tab.url, title: sender.tab.title } : null;
    const repetidas = Array.isArray(msg.repetidas) ? msg.repetidas : null;
    if (msg.tipo === "recortar") {                            // ✂ sobre el video: esos trozos
      const { tramos, error } = validarTramos((Array.isArray(msg.tramos) ? msg.tramos : []).map(([a, b]) => ({ desde: String(a), hasta: String(b) })));
      if (error) { responder(fallo({ codigo: "configuracion", mensaje: error })); return false; }
      anadirConLoElegido(url, pagina, (base) => opcionesRecorte(base, tramos, { exacto: msg.exacto === true, audio: msg.audio === true }), repetidas)
        .then(responder);
      return true;
    }
    anadirConLoElegido(url, pagina, conDefecto(msg.modo === "audio"), repetidas).then(responder);
    return true;
  }
  return false;
});
