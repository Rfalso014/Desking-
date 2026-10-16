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
