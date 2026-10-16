// Funciones puras compartidas por el service worker y el popup (se prueban con Node).

export const NOMBRE_HOST = "com.gestor.descargas";

/** ¿Es una URL http/https? Las blob:, data:, javascript: etc. NO sirven para la app. */
export function esUrlWeb(u) {
  try {
    const x = new URL(u);
    return x.protocol === "http:" || x.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * Elige qué URL enviar a la app según donde se hizo clic derecho.
 * Muchos reproductores usan blob: (no descargable): en ese caso se envía la
 * URL de la página para que la app intente extraer el video desde ahí.
 */
export function elegirUrlParaMenu(info, tab) {
  // Si se hizo clic en un enlace, manda el enlace; si fue en un medio, manda su fuente.
  const orden = info.linkUrl
    ? [info.linkUrl, info.srcUrl, info.pageUrl, tab && tab.url]
    : [info.srcUrl, info.linkUrl, info.pageUrl, tab && tab.url];
  for (const c of orden) {
    if (c && esUrlWeb(c)) return c;
  }
  return null;
}

/**
 * Decide qué URL enviar cuando el botón flotante se pulsa sobre un <video>.
 * Prioridad: enlace que envuelve al video (miniaturas de YouTube, etc.) > fuente directa (no blob:) > página.
 */
export function elegirUrlParaVideo(c) {
  for (const u of [c && c.enlace, c && c.fuente, c && c.pagina]) {
    if (u && esUrlWeb(u)) return u;
  }
  return null;
}

/** Traduce los errores crudos de Chrome (connectNative) a mensajes comprensibles. */
export function mensajeErrorNativo(texto) {
  const t = String(texto || "");
  if (/not found/i.test(t)) {
    return {
      codigo: "comunicacion",
      mensaje: "No está instalado el componente de comunicación con la aplicación.",
      solucion: "Ejecuta el instalador del Gestor de Descargas (o scripts/instalar_host.py) y reinicia el navegador.",
    };
  }
  if (/forbidden/i.test(t)) {
    return {
      codigo: "comunicacion",
      mensaje: "El navegador no permite que esta extensión hable con la aplicación.",
      solucion: "Reinstala el componente de comunicación: el ID de la extensión no coincide con el autorizado.",
    };
  }
  return {
    codigo: "comunicacion",
    mensaje: "No se pudo comunicar con la aplicación de escritorio.",
    solucion: "Abre «Gestor de Descargas» e inténtalo de nuevo.",
    detalle: t || undefined,
  };
}

export const ETIQUETA_ESTADO = {
  detectado: "Detectado", analizando: "Analizando", pendiente: "Pendiente", descargando: "Descargando",
  procesando: "Procesando", completado: "Completado", cancelado: "Cancelado", error: "Error",
};

export const ESTADOS_ACTIVOS = ["analizando", "pendiente", "descargando", "procesando"];

/** Acciones disponibles para una tarea según su estado. */
export function accionesDisponibles(estado) {
  if (ESTADOS_ACTIVOS.includes(estado)) return ["cancelar"];
  if (estado === "detectado") return ["iniciar", "eliminar"];
  if (estado === "error" || estado === "cancelado") return ["reintentar", "eliminar"];
  return ["eliminar"];
}

export function nombreSitio(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

export function formatearTamano(bytes) {
  if (!bytes) return "?";
  const mb = bytes / 1048576;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(1)} MB`;
}

/** Nombre que se le muestra a la app para identificar este navegador en la lista de vinculados. */
export function nombreNavegador(ua) {
  const u = String(ua || "");
  const navegador = /Edg\//.test(u) ? "Edge" : /OPR\//.test(u) ? "Opera" : /Firefox\//.test(u) ? "Firefox" : /Chrome\//.test(u) ? "Chrome" : "Navegador";
  return `${navegador} en este equipo`;
}

/** Deja el código como XXXX-XXXX mientras se escribe (solo letras y números, en mayúsculas, máximo 8). */
export function formatearCodigo(texto) {
  const limpio = String(texto || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 8);
  return limpio.length > 4 ? `${limpio.slice(0, 4)}-${limpio.slice(4)}` : limpio;
}

export function formatearVelocidad(bps) {
  if (!bps || bps <= 0) return "";
  if (bps >= 1048576) return `${(bps / 1048576).toFixed(1)} MB/s`;
  if (bps >= 1024) return `${(bps / 1024).toFixed(0)} KB/s`;
  return `${Math.round(bps)} B/s`;
}

export function formatearEta(seg) {
  if (seg == null || seg < 0) return "";
  seg = Math.round(seg);
  if (seg >= 3600) return `${Math.floor(seg / 3600)} h ${Math.floor((seg % 3600) / 60)} min`;
  if (seg >= 60) return `${Math.floor(seg / 60)} min ${seg % 60} s`;
  return `${seg} s`;
}

export function formatearDuracion(seg) {
  if (!seg) return "";
  seg = Math.round(seg);
  const h = Math.floor(seg / 3600), m = Math.floor((seg % 3600) / 60), s = seg % 60;
  const dos = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${dos(m)}:${dos(s)}` : `${m}:${dos(s)}`;
}

const PENDIENTES = ["pendiente", "detectado"];

/** Filtra la cola por categoría y por texto (título, sitio o URL). */
export function filtrarTareas(tareas, filtro, texto = "") {
  const q = String(texto).trim().toLowerCase();
  return tareas.filter((t) => {
    const ok = filtro === "activas" ? ESTADOS_ACTIVOS.includes(t.estado) || PENDIENTES.includes(t.estado)
      : filtro === "completadas" ? t.estado === "completado"
      : filtro === "errores" ? t.estado === "error"
      : true;
    return ok && (!q || [t.titulo, t.sitio, t.url].some((x) => (x || "").toLowerCase().includes(q)));
  });
}

/** Resumen para la franja superior de la cola. */
export function resumenCola(tareas) {
  const descargando = tareas.filter((t) => t.estado === "descargando");
  return {
    descargando: descargando.length,
    enEspera: tareas.filter((t) => t.estado === "pendiente" || t.estado === "analizando").length,
    detectados: tareas.filter((t) => t.estado === "detectado").length,
    velocidad: descargando.reduce((a, t) => a + (t.velocidad || 0), 0),
  };
}

/** Solo se cargan miniaturas http/https (nunca data:, javascript: ni blob:). */
export function miniaturaSegura(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

// --- Qué descargar: casillas -> opciones (copia de src/gestor/elementos.py; si cambias una, cambia la otra) ---
const IDIOMA = /^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$/;

export const ELEMENTOS_POR_DEFECTO = {
  video: true, audio: false, subtitulos: false, portada: true, idiomas: "es", altura: "", formatoAudio: "mp3",
};

/** «es, en» -> { idiomas: ["es","en"], invalidos: [] }. */
export function parsearIdiomas(texto) {
  const idiomas = [], invalidos = [];
  for (const t of String(texto || "").split(",").map((x) => x.trim())) {
    if (!t) continue;
    if (!IDIOMA.test(t)) invalidos.push(t);
    else if (!idiomas.includes(t)) idiomas.push(t);
  }
  return { idiomas, invalidos };
}

/**
 * Devuelve 1 o 2 diccionarios de opciones (uno por descarga). Lanza Error con .mensaje y .solucion si algo está mal.
 * Video + audio a la vez = dos descargas; los subtítulos y la portada acompañan solo a la primera.
 */
export function construirOpciones(e) {
  const a = { ...ELEMENTOS_POR_DEFECTO, ...e };
  const { idiomas, invalidos } = parsearIdiomas(a.idiomas);
  if (invalidos.length) throw Object.assign(new Error("idioma"), { mensaje: `Idioma de subtítulos no válido: ${invalidos[0]}.`, solucion: "Usa códigos de 2 o 3 letras separados por comas, por ejemplo: es,en" });
  const quiereSubs = !!a.subtitulos;
  const langs = quiereSubs && !idiomas.length ? ["es"] : idiomas;
  if (!(a.video || a.audio || quiereSubs || a.portada)) {
    throw Object.assign(new Error("nada"), { mensaje: "No hay nada marcado para descargar.", solucion: "Marca al menos una casilla: video, audio, subtítulos o portada." });
  }
  const extras = (conSubs, conPortada) => ({ subtitulos: quiereSubs && conSubs ? langs : [], portada: !!(a.portada && conPortada) });
  const conCalidad = (d) => {
    if (a.altura === "mejor") d.altura_max = null;
    else if (a.altura) d.altura_max = Number(a.altura);
    return d;
  };
  const conAudio = (d) => { if (a.formatoAudio) d.formato_audio = a.formatoAudio; return d; };
  if (a.video && a.audio) return [conCalidad({ modo: "video", ...extras(true, true) }), conAudio({ modo: "audio", ...extras(false, false) })];
  if (a.video) return [conCalidad({ modo: "video", ...extras(true, true) })];
  if (a.audio) return [conAudio({ modo: "audio", ...extras(true, true) })];
  if (quiereSubs) return [{ modo: "subtitulos", ...extras(true, true) }];
  return [{ modo: "portada", portada: true, subtitulos: [] }];
}

/** Reconstruye las casillas a partir de las opciones guardadas en una tarea (o usa los valores por defecto). */
export function elementosDesdeOpciones(op, defecto = ELEMENTOS_POR_DEFECTO) {
  if (!op || !op.modo) return { ...defecto };
  const subs = Array.isArray(op.subtitulos) ? op.subtitulos : [];
  return {
    video: op.modo === "video", audio: op.modo === "audio", subtitulos: subs.length > 0 || op.modo === "subtitulos",
    portada: !!op.portada || op.modo === "portada", idiomas: subs.length ? subs.join(",") : defecto.idiomas,
    altura: !("altura_max" in op) ? "" : op.altura_max === null ? "mejor" : String(op.altura_max),
    formatoAudio: op.formato_audio || defecto.formatoAudio,
  };
}

/** Elementos para el botón «♪» del video: solo audio, con el formato por defecto del usuario. */
export function soloAudio(defecto = ELEMENTOS_POR_DEFECTO) {
  return { ...defecto, video: false, audio: true, subtitulos: false, portada: false };
}
