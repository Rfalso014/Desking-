// Service worker: menú contextual y puente con la aplicación (Native Messaging).
// La extensión NO descarga nada: delega todo en la aplicación de escritorio.
import { NOMBRE_HOST, ELEMENTOS_POR_DEFECTO, construirOpciones, elegirUrlParaMenu, elegirUrlParaVideo, esErrorDeVersion, opcionesRecorte, soloAudio, esUrlWeb, mensajeErrorNativo, validarTramos, ESTADOS_ACTIVOS } from "./util.js";

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
  if (r.ok && accion === "ping") comprobarRecarga(r.datos);
  if (r.ok && accion === "emparejar" && r.datos && r.datos.token) await chrome.storage.local.set({ token: r.datos.token });
  if (r.ok && accion === "desvincular") await chrome.storage.local.remove("token");
  return r;
}

/**
 * Tras «Actualizar aplicación y extensión» la app deja una marca nueva (o trae otra versión de la extensión):
 * la extensión se recarga para leer sus archivos nuevos. Cada marca/versión se atiende una sola vez (sin bucles).
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

// Al abrir el navegador se comprueba si la aplicación se actualizó mientras tanto.
chrome.runtime.onStartup.addListener(() => { enviar("ping"); });

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

// La interfaz es una barra lateral: el ícono de la extensión la abre y la cierra.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

// Lo encontrado en «Esta página» se guarda por pestaña; al cerrarla ya no sirve.
chrome.tabs.onRemoved.addListener((tabId) => { chrome.storage.session.remove(`recursos:${tabId}`); });

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    for (const m of MENU) chrome.contextMenus.create(m);
  });
});

/** Añade a la lista (sin descargar) con lo que el usuario dejó como «qué descargar por defecto». */
/**
 * Añade a la lista con lo que el usuario dejó como «qué descargar por defecto».
 * Si ese video ya estaba en la lista, la app responde «duplicado»: se devuelve qué opciones faltaron (`repetidas`)
 * para que el usuario confirme y se vuelvan a enviar SOLO esas, con `forzar`.
 */
async function detectarConLoElegido(url, origen, audio, repetidasConfirmadas = null) {
  return enviarConLoElegido("detectar", url, origen, repetidasConfirmadas, (base) => construirOpciones(audio ? soloAudio(base) : base));
}

/** ✂ Descarga ya (encolar) solo esos trozos del video, con lo de «qué descargar por defecto». */
async function recortarConLoElegido(url, origen, msg) {
  const { tramos, error } = validarTramos((Array.isArray(msg.tramos) ? msg.tramos : []).map(([a, b]) => ({ desde: String(a), hasta: String(b) })));
  if (error) return { ok: false, error: { codigo: "configuracion", mensaje: error } };
  return enviarConLoElegido("encolar", url, origen, Array.isArray(msg.repetidas) ? msg.repetidas : null,
    (base) => opcionesRecorte(base, tramos, { exacto: msg.exacto === true, audio: msg.audio === true }));
}

async function enviarConLoElegido(accion, url, origen, repetidasConfirmadas, armar) {
  let conjuntos;
  if (Array.isArray(repetidasConfirmadas)) {
    conjuntos = repetidasConfirmadas.filter((o) => o && typeof o === "object").slice(0, 2);
  } else {
    const { elementos } = await chrome.storage.local.get("elementos");
    const base = { ...ELEMENTOS_POR_DEFECTO, ...(elementos || {}) };
    try {
      conjuntos = armar(base);
    } catch (e) {
      return { ok: false, error: { codigo: "configuracion", mensaje: e.mensaje || "Revisa «qué descargar» en los Ajustes.", solucion: e.solucion } };
    }
  }
  const forzar = Array.isArray(repetidasConfirmadas);
  let ultima = { ok: false, error: { mensaje: "Nada que añadir." } };
  const repetidas = [];
  let errorRepetido = null;
  for (const opciones of conjuntos) {
    ultima = await enviar(accion, { url, origen, opciones, ...(forzar ? { forzar: true } : {}) });
    if (!ultima.ok && esErrorDeVersion(ultima.error)) {
      return { ok: false, error: { codigo: "version", mensaje: "Reinicia la aplicación: es una versión anterior",
        solucion: "Abre la extensión y pulsa «Reiniciar aplicación» (o ciérrala desde la bandeja y vuelve a abrirla)." } };
    }
    if (!ultima.ok && ultima.error && ultima.error.codigo === "duplicado") { repetidas.push(opciones); errorRepetido = ultima.error; continue; }
    if (!ultima.ok) return ultima;
  }
  if (repetidas.length) return { ok: false, error: errorRepetido, repetidas };
  return ultima;
}

// Clic derecho sobre un video que ya está en la lista: una notificación pregunta si añadirlo otra vez.
async function preguntarRepetido(url, origen, r) {
  const id = `repetido-${Date.now()}`;
  await chrome.storage.session.set({ [id]: { url, origen, repetidas: r.repetidas } });
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
  const r = await detectarConLoElegido(datos.url, datos.origen, false, datos.repetidas);
  if (!r.ok) await avisar((r.error && r.error.mensaje) || "No se pudo añadir a la lista.");
  else await actualizarInsignia();
});
chrome.notifications.onClosed.addListener((id) => { if (id.startsWith("repetido-")) chrome.storage.session.remove(id); });

async function avisar(texto) {
  await chrome.action.setBadgeBackgroundColor({ color: "#b3261e" });
  await chrome.action.setBadgeText({ text: "!" });
  await chrome.storage.session.set({ aviso: texto });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const url = elegirUrlParaMenu(info, tab);
  if (!url) {
    await avisar("No se encontró el enlace de este video: ábrelo en su propia página o haz clic derecho sobre su miniatura.");
    return;
  }
  // Solo se AÑADE a la lista de detectados; la descarga empieza cuando el usuario pulse «Descargar».
  const origen = tab && esUrlWeb(tab.url) ? tab.url : undefined;
  const r = await detectarConLoElegido(url, origen, false);
  if (!r.ok && r.repetidas) return preguntarRepetido(url, origen, r);
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
  await chrome.action.setBadgeBackgroundColor({ color: activas ? "#1f9e94" : "#d97706" });
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
  if (msg.tipo === "detectar-pagina" || msg.tipo === "recortar") {      // botón flotante sobre un video (content.js): solo añade a la lista
    const url = elegirUrlParaVideo(msg.candidatas);
    if (!url) {
      responder(fallo({ codigo: "url_invalida", mensaje: "No se encontró el enlace de este video.",
        solucion: "Abre el video en su propia página, o haz clic derecho sobre su miniatura → «Añadir a Gestor de Descargas»." }));
      return false;
    }
    const audio = msg.modo === "audio";                      // lista blanca: cualquier otra cosa = «lo de por defecto»
    const origen = sender.tab && esUrlWeb(sender.tab.url) ? sender.tab.url : undefined;
    // `repetidas`: el usuario ya confirmó (segundo clic) que quiere ese video otra vez.
    if (msg.tipo === "recortar") {                            // ✂ panel sobre el video: descarga ya esos trozos
      recortarConLoElegido(url, origen, msg).then((r) => { responder(r); if (r.ok) actualizarInsignia(); });
      return true;
    }
    detectarConLoElegido(url, origen, audio, Array.isArray(msg.repetidas) ? msg.repetidas : null)
      .then((r) => { responder(r); if (r.ok) actualizarInsignia(); });
    return true;
  }
  return false;
});
