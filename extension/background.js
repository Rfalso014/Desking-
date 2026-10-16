// Service worker: menú contextual y puente con la aplicación (Native Messaging).
// La extensión NO descarga nada: delega todo en la aplicación de escritorio.
import { NOMBRE_HOST, elegirUrlParaMenu, esUrlWeb, mensajeErrorNativo, ESTADOS_ACTIVOS } from "./util.js";

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

/** Envía una acción a la app y devuelve la respuesta ({ok, datos} o {ok:false, error}). */
export function enviar(accion, datos = {}) {
  return new Promise((resolve) => {
    const id = `m${Date.now().toString(36)}${(contador++).toString(36)}`;
    const timer = setTimeout(() => {
      pendientes.delete(id);
      resolve(fallo({ codigo: "comunicacion", mensaje: "La aplicación no respondió a tiempo.", solucion: "Reintenta en unos segundos." }));
    }, TIEMPO_ESPERA_MS);
    pendientes.set(id, { resolve, timer });
    try {
      conectar().postMessage({ v: 1, id, accion, datos });
    } catch (e) {
      clearTimeout(timer);
      pendientes.delete(id);
      puerto = null;
      resolve(fallo(mensajeErrorNativo(e && e.message)));
    }
  });
}

// --- Menú contextual --------------------------------------------------------
const MENU = [
  { id: "encolar", title: "Añadir a la cola de descargas", contexts: ["link", "video", "audio", "image", "page"] },
  { id: "analizar", title: "Analizar enlace…", contexts: ["link", "video", "audio", "image", "page"] },
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
  if (info.menuItemId === "encolar") {
    const r = await enviar("encolar", { url, origen: tab && esUrlWeb(tab.url) ? tab.url : undefined });
    if (!r.ok) await avisar((r.error && r.error.mensaje) || "No se pudo añadir a la cola.");
    else await actualizarInsignia();
  } else if (info.menuItemId === "analizar") {
    await chrome.storage.session.set({ analizarUrl: url });
    try {
      await chrome.action.openPopup();
    } catch {
      await chrome.action.setBadgeBackgroundColor({ color: "#1a73e8" });
      await chrome.action.setBadgeText({ text: "1" }); // el usuario abre el popup con un clic
    }
  }
});

// --- Insignia con el número de descargas activas ----------------------------
async function actualizarInsignia() {
  const r = await enviar("listar", { estados: ESTADOS_ACTIVOS, limite: 50 });
  const n = r.ok ? r.datos.tareas.length : 0;
  await chrome.action.setBadgeBackgroundColor({ color: "#1a73e8" });
  await chrome.action.setBadgeText({ text: n ? String(n) : "" });
}

// --- Mensajes del popup -----------------------------------------------------
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  if (sender.id !== chrome.runtime.id || !msg || msg.tipo !== "nativo") return false;
  enviar(msg.accion, msg.datos).then(responder);
  return true; // respuesta asíncrona
});
