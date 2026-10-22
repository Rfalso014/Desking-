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
  const orden = info.linkUrl ? [info.linkUrl, info.srcUrl] : [info.srcUrl, info.linkUrl];
  for (const c of orden) {
    if (c && esUrlWeb(c)) return c;
  }
  // La página solo sirve si no es un inicio o feed (youtube.com/, x.com/home...): ahí no hay UN video.
  for (const c of [info.pageUrl, tab && tab.url]) {
    if (c && esUrlWeb(c) && !esPaginaDeFeed(c)) return c;
  }
  return null;
}

// --- Enlaces a UN video concreto (permalinks) frente a inicios, feeds y búsquedas --------------
const sinPrefijo = (host) => host.replace(/^(www|m|mobile|web|old)\./, "");

const PATRONES_VIDEO = [
  /^(music\.)?youtube\.com\/(watch\?(.*&)?v=[\w-]{6,}|(shorts|live|embed)\/[\w-]{6,})/,
  /^youtu\.be\/[\w-]{6,}/,
  /^(twitter|x)\.com\/[^/]+\/status\/\d+/,
  /^instagram\.com\/([^/]+\/)?(p|reels?|tv)\/[\w-]+/,
  /^facebook\.com\/(.+\/videos\/(.+\/)?\d+|watch\/?\?(.*&)?v=\d|reel\/\d|share\/[vr]\/)/,
  /^fb\.watch\/\w+/,
  /^tiktok\.com\/@[^/]+\/video\/\d+/,
  /^reddit\.com\/r\/[^/]+\/comments\/\w+/,
  /^vimeo\.com\/(\d+|.+\/videos?\/\d+)/,
  /^dailymotion\.com\/video\/\w+/,
  /^(clips\.)?twitch\.tv\/(videos\/\d+|[^/]+\/clip\/[\w-]+|[\w-]+$)/,
  /\/(videos?|watch|clips?|reels?|embed)\/[\w-]{3,}/,          // cualquier otro sitio con rutas típicas de video
];

// Sitios donde todo lo que no es un permalink es un feed, un perfil o una búsqueda.
const SOLO_PERMALINK = /^(twitter\.com|x\.com|instagram\.com|tiktok\.com)$/;
const PATRONES_FEED = [
  /^youtube\.com\/(\?.*)?$/,
  /^youtube\.com\/(feed\/|results\?|@[^/]+|channel\/|c\/|user\/)/,
  /^facebook\.com\/(\?.*)?$/,
  /^facebook\.com\/watch\/?(\?(?!(.*&)?v=).*)?$/,
  /^reddit\.com\/((r\/[^/]+|user\/[^/]+)\/?)?(\?.*)?$/,
];

const resto = (x) => sinPrefijo(x.hostname) + x.pathname + x.search;

/** ¿Apunta a un video concreto? (miniatura de YouTube, tuit con video, reel...) */
export function esEnlaceDeVideo(u) {
  if (!esUrlWeb(u)) return false;
  const r = resto(new URL(u));
  return PATRONES_VIDEO.some((p) => p.test(r));
}

/** ¿Es un inicio, feed, canal o búsqueda? Su dirección NO identifica al video sobre el que está el cursor. */
export function esPaginaDeFeed(u) {
  if (!esUrlWeb(u)) return false;
  const x = new URL(u);
  if (SOLO_PERMALINK.test(sinPrefijo(x.hostname))) return !esEnlaceDeVideo(u);
  return PATRONES_FEED.some((p) => p.test(resto(x))) && !esEnlaceDeVideo(u);
}

/** Identificador para comparar enlaces: el mismo video con otros parámetros (&t=30, #comentarios) cuenta igual. */
export function claveVideo(u) {
  const x = new URL(u);
  const host = sinPrefijo(x.hostname);
  const yt = host === "youtu.be" ? x.pathname.slice(1)
    : /youtube\.com$/.test(host) ? x.searchParams.get("v") || (x.pathname.match(/^\/(shorts|live|embed)\/([\w-]+)/) || [])[2]
    : null;
  if (yt) return `youtube:${yt}`;
  const v = x.searchParams.get("v");
  return host + x.pathname.replace(/\/+$/, "") + (v ? `?v=${v}` : "");
}

/**
 * Busca el permalink del video entre los enlaces de sus contenedores, del más cercano al más lejano.
 * Si en un mismo contenedor aparecen varios videos distintos ya es un feed: no se adivina.
 */
export function enlaceVecino(niveles) {
  for (const nivel of Array.isArray(niveles) ? niveles : []) {
    if (!Array.isArray(nivel)) continue;
    const videos = new Map();
    for (const u of nivel) if (esEnlaceDeVideo(u) && !videos.has(claveVideo(u))) videos.set(claveVideo(u), u);
    if (videos.size === 1) return [...videos.values()][0];
    if (videos.size > 1) return null;
  }
  return null;
}

/**
 * Decide qué URL enviar cuando el botón flotante se pulsa sobre un <video>.
 * Prioridad: enlace que envuelve al video > permalink bajo el cursor (la miniatura bajo una vista previa)
 * > permalink de su tarjeta > fuente directa (no blob:) > página, salvo que la página sea un inicio o feed.
 */
export function elegirUrlParaVideo(c) {
  if (!c) return null;
  if (c.enlace && esUrlWeb(c.enlace)) return c.enlace;
  const bajo = (Array.isArray(c.bajoCursor) ? c.bajoCursor : []).find(esEnlaceDeVideo);
  if (bajo) return bajo;
  const vecino = enlaceVecino(c.cercanos);
  if (vecino) return vecino;
  if (c.fuente && esUrlWeb(c.fuente)) return c.fuente;
  return c.pagina && esUrlWeb(c.pagina) && !esPaginaDeFeed(c.pagina) ? c.pagina : null;
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

/** Nombre legible de un recurso a partir de su URL (último tramo de la ruta, sin parámetros). */
export function nombreDeArchivo(url) {
  try {
    const partes = new URL(url).pathname.split("/").filter(Boolean);
    const ultimo = decodeURIComponent(partes[partes.length - 1] || "");
    return (ultimo || new URL(url).hostname).slice(0, 80);
  } catch {
    return String(url || "").slice(0, 80);
  }
}

const ORDEN_RECURSOS = { video: 0, audio: 1, enlace: 2, imagen: 3 };

/** Videos y audios primero, imágenes al final (conserva el orden dentro de cada tipo). */
export function ordenarRecursos(lista) {
  return lista.map((r, i) => [r, i]).sort((a, b) => (ORDEN_RECURSOS[a[0].tipo] ?? 2) - (ORDEN_RECURSOS[b[0].tipo] ?? 2) || a[1] - b[1]).map(([r]) => r);
}

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
  video: true, audio: false, subtitulos: false, portada: true, idiomas: "es", altura: "", formatoAudio: "mp3", carpeta: "", editable: false,
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
    if (a.editable) d.editable = true;               // MP4 H.264 + AAC para programas de edición
    if (a.altura === "mejor") d.altura_max = null;
    else if (a.altura) d.altura_max = Number(a.altura);
    return d;
  };
  const conAudio = (d) => { if (a.formatoAudio) d.formato_audio = a.formatoAudio; return d; };
  const nombre = String(a.carpeta || "").trim();
  const conCarpeta = (lista) => (nombre ? lista.map((d) => ({ ...d, subcarpeta: nombre })) : lista);
  if (a.video && a.audio) return conCarpeta([conCalidad({ modo: "video", ...extras(true, true) }), conAudio({ modo: "audio", ...extras(false, false) })]);
  if (a.video) return conCarpeta([conCalidad({ modo: "video", ...extras(true, true) })]);
  if (a.audio) return conCarpeta([conAudio({ modo: "audio", ...extras(true, true) })]);
  if (quiereSubs) return conCarpeta([{ modo: "subtitulos", ...extras(true, true) }]);
  return conCarpeta([{ modo: "portada", portada: true, subtitulos: [] }]);
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
    carpeta: op.subcarpeta || defecto.carpeta || "",
    editable: !!op.editable,
  };
}

/** Elementos para el botón «♪» del video: solo audio, con el formato por defecto del usuario. */
export function soloAudio(defecto = ELEMENTOS_POR_DEFECTO) {
  return { ...defecto, video: false, audio: true, subtitulos: false, portada: false };
}

// --- «Esta página»: lo que lee content.js -> lista de recursos ------------------------------------
const lista = (x) => (Array.isArray(x) ? x : []);

/** Clave para no repetir un recurso: el mismo video con otros parámetros (&t=30, #...) cuenta una vez. */
export function claveRecurso(r) {
  try {
    return esEnlaceDeVideo(r.url) ? claveVideo(r.url) : new URL(r.url).href.replace(/#.*$/, "");
  } catch {
    return String(r && r.url);
  }
}

/**
 * Arma la lista de «Esta página»: la propia página si es un video, cada <video>/<audio> con su permalink,
 * los enlaces a videos (las miniaturas de inicios y feeds) y los archivos multimedia o imágenes grandes.
 */
export function armarRecursos(d, maximo = 200) {
  if (!d) return [];
  const salida = new Map();
  const anadir = (tipo, url, nombre) => {
    if (!esUrlWeb(url) || salida.size >= maximo) return;
    const r = { tipo, url, nombre: String(nombre || "").trim().replace(/\s+/g, " ").slice(0, 120) };
    const previo = salida.get(claveRecurso(r));
    if (!previo) salida.set(claveRecurso(r), r);
    else if (r.nombre.length > previo.nombre.length) previo.nombre = r.nombre;   // la miniatura dice «12:34»; el título, el nombre
  };
  if (esEnlaceDeVideo(d.url)) anadir("video", d.url, d.titulo);
  for (const m of lista(d.medios)) anadir(m && m.tipo === "audio" ? "audio" : "video", elegirUrlParaVideo(m && m.candidatas), m && m.nombre);
  for (const e of lista(d.enlaces)) if (e && esEnlaceDeVideo(e.url)) anadir("video", e.url, e.nombre);
  for (const a of lista(d.archivos)) if (a && ["enlace", "imagen", "audio", "video"].includes(a.tipo)) anadir(a.tipo, a.url, a.nombre);
  return [...salida.values()];
}

/**
 * Une lo encontrado antes con lo de ahora sin perder nada al recargar la página: lo que ya no aparece queda
 * marcado como «anterior». El orden se mantiene (lo nuevo va al final) para que la lista no salte.
 */
export function fusionarRecursos(previos, nuevos, maximo = 300) {
  const ahora = new Map(lista(nuevos).map((r) => [claveRecurso(r), r]));
  const vistos = new Set();
  const salida = [];
  for (const r of lista(previos)) {
    const k = claveRecurso(r);
    if (vistos.has(k)) continue;
    vistos.add(k);
    const actual = ahora.get(k);
    salida.push({ ...r, ...(actual && actual.nombre ? { nombre: actual.nombre } : {}), anterior: !actual });
  }
  for (const [k, r] of ahora) if (!vistos.has(k)) { vistos.add(k); salida.push({ ...r, anterior: false }); }
  return salida.slice(-maximo);
}

/** [[altura, bytes]] aproximados de la mejor calidad, 1080p y 720p (copia de extractor.tamanos_por_calidad). */
export function tamanosPorCalidad(formatos, maximo = 3) {
  const lista = Array.isArray(formatos) ? formatos : [];
  const audio = Math.max(0, ...lista.filter((f) => f.tipo === "solo_audio").map((f) => f.tamano || 0));
  const porAltura = new Map();
  for (const f of lista) {
    if (!f.altura || !f.tamano || !["solo_video", "video+audio"].includes(f.tipo)) continue;
    const total = f.tamano + (f.tipo === "solo_video" ? audio : 0);
    porAltura.set(f.altura, Math.max(porAltura.get(f.altura) || 0, total));
  }
  const alturas = [...porAltura.keys()].sort((a, b) => b - a);
  if (!alturas.length) return [];
  const elegidas = [alturas[0], alturas.find((a) => a <= 1080), alturas.find((a) => a <= 720)];
  const salida = [];
  for (const a of elegidas) if (a != null && !salida.some(([x]) => x === a)) salida.push([a, porAltura.get(a)]);
  return salida.slice(0, maximo);
}

/** -1 si a < b, 0 si son iguales, 1 si a > b («1.10.0» > «1.9.2»; lo que falta cuenta como 0). */
export function compararVersiones(a, b) {
  const partes = (v) => String(v || "0").split(/[^0-9]+/).filter(Boolean).map(Number);
  const pa = partes(a), pb = partes(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d > 0 ? 1 : -1;
  }
  return 0;
}

/** Errores típicos de una aplicación anterior a la extensión (no conoce opciones o acciones nuevas). */
export function esErrorDeVersion(error) {
  return /Opción no válida|Acción desconocida|Datos no permitidos/.test(String((error && error.mensaje) || ""));
}

// --- Tema ---------------------------------------------------------------------------------------------
export const TEMAS = ["auto", "dia", "noche"];
export const siguienteTema = (t) => TEMAS[(TEMAS.indexOf(t) + 1) % TEMAS.length];
/** Valor de data-theme del documento (null = seguir a Windows). */
export const atributoTema = (t) => (t === "dia" ? "light" : t === "noche" ? "dark" : null);

// --- Recortar: descargar solo unos minutos -----------------------------------------------------------
export const MAX_TRAMOS = 10;

/** «80», «1:20», «01:02:03» o «1:20.5» -> segundos (null si no se entiende). */
export function parsearTiempo(texto) {
  const t = String(texto ?? "").trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$|^\d{1,3}:\d{1,2}(\.\d+)?$|^\d{1,2}:\d{1,2}:\d{1,2}(\.\d+)?$/.test(t)) return null;
  const partes = t.split(":").map(Number);
  if (partes.slice(1).some((p) => p >= 60)) return null;
  return partes.reduce((acc, p) => acc * 60 + p, 0);
}

/** 80 -> «1:20»; 3723 -> «1:02:03». */
export function formatearTiempo(seg) {
  if (seg == null || !Number.isFinite(seg) || seg < 0) return "";
  const s = Math.floor(seg), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const dos = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${dos(m)}:${dos(r)}` : `${m}:${dos(r)}`;
}

/**
 * Comprueba los trozos escritos ([{desde, hasta}] en texto) contra la duración del video.
 * Devuelve { tramos: [[inicio, fin], ...] } o { error: "texto para la persona" }.
 */
export function validarTramos(filas, duracion = null) {
  const lista = (Array.isArray(filas) ? filas : []).filter((f) => f && (String(f.desde ?? "").trim() || String(f.hasta ?? "").trim()));
  if (!lista.length) return { error: "Marca al menos un trozo: desde qué minuto y hasta cuál." };
  if (lista.length > MAX_TRAMOS) return { error: `Como máximo ${MAX_TRAMOS} trozos por video.` };
  const tramos = [];
  for (const [i, f] of lista.entries()) {
    const n = lista.length > 1 ? ` del trozo ${i + 1}` : "";
    const a = parsearTiempo(f.desde), b = parsearTiempo(f.hasta);
    if (a == null) return { error: `No entiendo el inicio${n}. Escríbelo como 1:20 o 1:02:03.` };
    if (b == null) return { error: `No entiendo el final${n}. Escríbelo como 3:45 o 1:05:00.` };
    if (b <= a) return { error: `El final${n} tiene que ser después del inicio.` };
    if (duracion && Number.isFinite(duracion) && a >= duracion) return { error: `El inicio${n} está después del final del video (${formatearTiempo(duracion)}).` };
    tramos.push([a, duracion && Number.isFinite(duracion) ? Math.min(b, duracion) : b]);
  }
  return { tramos };
}

/** Opciones para descargar esos trozos con lo de «qué descargar por defecto» (sin subtítulos ni portada). */
export function opcionesRecorte(defecto, tramos, { exacto = false, audio = false } = {}) {
  const base = { ...ELEMENTOS_POR_DEFECTO, ...defecto, subtitulos: false, portada: false };
  return construirOpciones(audio ? soloAudio(base) : base)
    .filter((o) => o.modo === "video" || o.modo === "audio")
    .map((o) => ({ ...o, tramos, corte_exacto: !!exacto }));
}

/** «✂ 1:20–3:45 · 5:00–5:30» para mostrar en la cola. */
export function textoTramos(tramos) {
  return Array.isArray(tramos) && tramos.length ? `✂ ${tramos.map(([a, b]) => `${formatearTiempo(a)}–${formatearTiempo(b)}`).join(" · ")}` : "";
}
