// Service worker: menú contextual y puente con la aplicación (Native Messaging).
// La extensión NO descarga nada: delega todo en la aplicación de escritorio.
import { NOMBRE_HOST, elegirUrlParaMenu, elegirUrlParaVideo, esUrlWeb, mensajeErrorNativo, ESTADOS_ACTIVOS } from "./util.js";

const TIEMPO_ESPERA_MS = 20000;
let puerto = null;
const pendientes = new Map(); // id de mensaje -> { resolve, timer }
let contador = 0;

function fallo(e) {
  return { ok: false, error: e };
}

function cerrarPendientes(error) {
  for (const [, p] of pendientes) {
    clearTimeout(p.timer);
    p.resolve(fallo(error));
  }
  pendientes.clear();
}

function conectar() {
  if (puerto) return puerto;
  puerto = chrome.runtime.connectNative(NOMBRE_HOST);
  puerto.onMessage.addListener((resp) => {
    const p = pendientes.get(resp && resp.id);
    if (!p) return;
    clearTimeout(p.timer);
    pendientes.delete(resp.id);
    p.resolve(resp);
  });
  puerto.onDisconnect.addListener(() => {
    const texto = chrome.runtime.lastError ? chrome.runtime.lastError.message : "";
    puerto = null;
    cerrarPendientes(mensajeErrorNativo(texto));
  });
  return puerto;
}

// Token de vinculación: lo entrega la aplicación cuando el usuario escribe su código. Se guarda solo en este navegador.
async function leerToken() {
  const { token } = await chrome.storage.local.get("token");
  return typeof token === "string" ? token : undefined;
}

/** Envía una acción a la app y devuelve la respuesta ({ok, datos} o {ok:false, error}). */
export async function enviar(accion, datos = {}) {
  const token = accion === "emparejar" ? undefined : await leerToken();
  const r = await enviarSinToken(accion, datos, token);
  if (r.ok && accion === "emparejar" && r.datos && r.datos.token) await chrome.storage.local.set({ token: r.datos.token });
  if (r.ok && accion === "desvincular") await chrome.storage.local.remove("token");
  return r;
}

function enviarSinToken(accion, datos, token) {
  return new Promise((resolve) => {
    const id = `m${Date.now().toString(36)}${(contador++).toString(36)}`;
    const timer = setTimeout(() => {
      pendientes.delete(id);
      resolve(fallo({ codigo: "comunicacion", mensaje: "La aplicación no respondió a tiempo.", solucion: "Reintenta en unos segundos." }));
    }, TIEMPO_ESPERA_MS);
    pendientes.set(id, { resolve, timer });
    try {
      conectar().postMessage({ v: 1, id, accion, datos, ...(token ? { token } : {}) });
    } catch (e) {
      clearTimeout(timer);
      pendientes.delete(id);
      puerto = null;
      resolve(fallo(mensajeErrorNativo(e && e.message)));
    }
  });
}

// --- Menú contextual --------------------------------------------------------
// Un solo elemento: así Chrome lo muestra directamente en el menú, sin submenú.
const MENU = [
  { id: "detectar", title: "Añadir a Gestor de Descargas", contexts: ["link", "video", "audio", "image"] },
];

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const m of MENU) chrome.contextMenus.create(m);
  });
});

async function avisar(texto) {
  await chrome.action.setBadgeBackgroundColor({ color: "#b3261e" });
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.storage.session.set({ aviso: texto });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = elegirUrlParaMenu(info, tab);
  if (!url) {
    await avisar("Este elemento no tiene una dirección que se pueda descargar.");
    return;
  }
  // Solo se AÑADE a la lista de detectados; la descarga empieza cuando el usuario pulse «Descargar».
  const r = await enviar("detectar", { url, origen: tab && esUrlWeb(tab.url) ? tab.url : undefined });
  if (!r.ok) await avisar((r.error && r.error.mensaje) || "No se pudo añadir a la lista.");
  else await actualizarInsignia();
});

// --- Insignia con el número de descargas activas ----------------------------
async function actualizarInsignia() {
  const r = await enviar("listar", { estados: [...ESTADOS_ACTIVOS, "detectado"], limite: 100 });
  const tareas = r.ok ? r.datos.tareas : [];
  const activas = tareas.filter((t) => t.estado !== "detectado").length;
  const porAutorizar = tareas.length - activas;
  // Azul = descargando; naranja = hay enlaces esperando tu autorización.
  await chrome.action.setBadgeBackgroundColor({ color: activas ? "#1a73e8" : "#d97706" });
  await chrome.action.setBadgeText({ text: activas ? String(activas) : porAutorizar ? String(porAutorizar) : "" });
}

// --- Mensajes del popup -----------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  if (sender.id !== chrome.runtime.id || !msg) return false;
  if (msg.tipo === "olvidar-token") {
    chrome.storage.local.remove("token").then(() => responder({ ok: true }));
    return true;
  }
  if (msg.tipo === "nativo") {
    enviar(msg.accion, msg.datos).then(responder);
    return true; // respuesta asíncrona
  }
  if (msg.tipo === "detectar-pagina") {      // botón flotante sobre un video (content.js): solo añade a la lista
    const url = elegirUrlParaVideo(msg.candidatas);
    if (!url) {
      responder(fallo({ codigo: "url_invalida", mensaje: "Este video no tiene una dirección descargable." }));
      return false;
    }
    const modo = msg.modo === "audio" ? "audio" : "video";   // lista blanca: lo demás se ignora
    const origen = sender.tab && esUrlWeb(sender.tab.url) ? sender.tab.url : undefined;
    chrome.storage.local.get(["altura"]).then(({ altura }) => {
      const opciones = { modo };
      if (altura === "mejor") opciones.altura_max = null;
      else if (/^\d+$/.test(altura || "")) opciones.altura_max = Number(altura);
      return enviar("detectar", { url, origen, opciones });
    }).then((r) => { responder(r); if (r.ok) actualizarInsignia(); });
    return true;
  }
  return false;
});
