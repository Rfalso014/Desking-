// Botón flotante sobre los videos y sobre las miniaturas que enlazan a un video (columna de sugeridos, inicio,
// búsquedas…): aparece al pasar el cursor y envía el video a la aplicación.
// Este script SOLO lee la página localmente; no envía nada hasta que el usuario hace clic.
// (Script clásico, no módulo: los content scripts no pueden usar "import".)
(() => {
  if (window.__gestorDescargasActivo) return; // evita duplicarlo si Chrome lo inyecta dos veces
  window.__gestorDescargasActivo = true;

  const MIN_ANCHO = 200, MIN_ALTO = 110;            // reproductor (<video>)
  const MIN_MINI_ANCHO = 120, MIN_MINI_ALTO = 60;   // miniatura enlazada (las de la columna de sugeridos miden ~168×94)

  // ¿El enlace lleva a UN video? Copia resumida de PATRONES_VIDEO (util.js; los content scripts no pueden importar).
  // extension/test/util.test.mjs comprueba que las dos dicen lo mismo.
  const PARECE_VIDEO = /^https?:\/\/([^/]+\.)?(youtube\.com\/(watch\?(.*&)?v=[\w-]{6,}|(shorts|live|embed)\/[\w-]{6,})|youtu\.be\/[\w-]{6,}|(twitter|x)\.com\/[^/]+\/status\/\d+|instagram\.com\/([^/]+\/)?(p|reels?|tv)\/[\w-]+|facebook\.com\/(.+\/videos\/(.+\/)?\d+|watch\/?\?(.*&)?v=\d|reel\/\d|share\/[vr]\/)|fb\.watch\/\w+|tiktok\.com\/@[^/]+\/video\/\d+|reddit\.com\/r\/[^/]+\/comments\/\w+|vimeo\.com\/(\d+|.+\/videos?\/\d+)|dailymotion\.com\/video\/\w+|(clips\.)?twitch\.tv\/(videos\/\d+|[^/]+\/clip\/[\w-]+))|^https?:\/\/[^?#]*\/(videos?|watch|clips?|reels?|embed)\/[\w-]{3,}/i;

  // El usuario puede desactivar el botón en los Ajustes de la extensión.
  let activo = true;
  try {
    chrome.storage.local.get(["botonFlotante"], (r) => { activo = !r || r.botonFlotante !== false; });
    chrome.storage.onChanged.addListener((cambios, area) => {
      if (area === "local" && cambios.botonFlotante) { activo = cambios.botonFlotante.newValue !== false; if (!activo) ocultar(); }
    });
  } catch { /* la extensión se recargó: este script queda inactivo */ }

  // --- Interfaz en un Shadow DOM cerrado: los estilos de la página no la rompen ---------
  const anfitrion = document.createElement("div");
  anfitrion.style.cssText = "all:initial;position:fixed;z-index:2147483647;top:0;left:0;width:0;height:0;";
  const sombra = anfitrion.attachShadow({ mode: "closed" });
  const estilo = document.createElement("style");
  estilo.textContent = `
      .pildora { position: fixed; display: none; align-items: stretch; font: 600 13px/1 system-ui, "Segoe UI", sans-serif;
                 background: #2f7d6d; color: #fff; border-radius: 999px; box-shadow: 0 2px 10px rgba(0,0,0,.45);
                 overflow: hidden; user-select: none; }
      .pildora.visible { display: flex; }
      .pildora button { all: unset; cursor: pointer; padding: 8px 12px; display: flex; align-items: center; gap: 6px; }
      .pildora button:hover { background: rgba(255,255,255,.2); }
      .pildora button:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }
      .sep { width: 1px; background: rgba(255,255,255,.4); }
      .pildora [hidden] { display: none; }
      .recorte { position: fixed; display: none; width: 292px; box-sizing: border-box; padding: 12px 14px 14px; border-radius: 16px;
                 background: #262a2e; color: #dcdad5; font: 13px/1.4 system-ui, "Segoe UI", sans-serif; box-shadow: 0 8px 28px rgba(0,0,0,.55); }
      .recorte.visible { display: block; }
      .recorte * { box-sizing: border-box; }
      .recorte .cab { display: flex; justify-content: space-between; align-items: center; font-weight: 700; font-size: 14px; }
      .recorte .tenue { color: #9a9d9f; font-size: 12px; }
      .recorte .fila { display: flex; gap: 6px; align-items: center; margin-top: 8px; }
      .recorte .fila span { width: 44px; color: #9a9d9f; font-size: 12px; }
      .recorte input[type=text] { all: unset; flex: 1; min-width: 0; background: #202326; border: 1px solid #42484e; border-radius: 9px;
                                  padding: 6px 9px; font: 600 13px system-ui; color: #dcdad5; }
      .recorte input[type=text]:focus { border-color: #7fb8a8; }
      .recorte button { all: unset; cursor: pointer; border-radius: 999px; padding: 6px 11px; font-weight: 600; font-size: 12px;
                        background: #30353a; color: #dcdad5; white-space: nowrap; }
      .recorte button:hover { filter: brightness(1.2); }
      .recorte button:focus-visible { outline: 2px solid #7fb8a8; outline-offset: 1px; }
      .recorte button.primario { background: #7fb8a8; color: #17201d; }
      .recorte button.cerrar { padding: 2px 8px; font-size: 16px; background: transparent; }
      .recorte button:disabled { opacity: .5; cursor: default; }
      .pista { position: fixed; display: none; height: 40px; touch-action: none; user-select: none; }
      .pista.visible { display: block; }
      .pista .fondo { position: absolute; left: 0; right: 0; top: 16px; height: 8px; border-radius: 4px; background: rgba(30,33,36,.85);
                      box-shadow: 0 1px 6px rgba(0,0,0,.5); cursor: pointer; }
      .pista .zona { position: absolute; top: 11px; height: 18px; border: 2px solid #7fb8a8; border-radius: 7px; background: rgba(127,184,168,.4);
                     cursor: grab; box-sizing: border-box; }
      .pista .zona:active { cursor: grabbing; }
      .pista .manija { position: absolute; top: 4px; width: 14px; height: 32px; margin-left: -7px; border-radius: 7px; background: #7fb8a8;
                       border: 2px solid #fff; box-sizing: border-box; cursor: ew-resize; box-shadow: 0 1px 6px rgba(0,0,0,.6); }
      .pista .manija::after { content: ""; position: absolute; left: 4px; top: 9px; width: 2px; height: 10px; border-left: 1px solid #17201d;
                              border-right: 1px solid #17201d; box-sizing: border-box; }
      .pista .etq { position: absolute; top: -18px; transform: translateX(-50%); background: #262a2e; color: #fff; border-radius: 6px;
                    font: 700 11px/1 system-ui, "Segoe UI", sans-serif; padding: 4px 6px; white-space: nowrap; pointer-events: none; }
      .pista .cabezal { position: absolute; top: 8px; width: 2px; height: 24px; margin-left: -1px; background: #fff; pointer-events: none;
                        box-shadow: 0 0 3px rgba(0,0,0,.8); }
      .recorte label { display: flex; gap: 7px; align-items: center; margin-top: 8px; font-size: 12px; cursor: pointer; }
      .recorte label input { accent-color: #7fb8a8; margin: 0; }
      .recorte .error { color: #e0938a; font-size: 12px; margin-top: 6px; }
      .recorte .acciones { display: flex; justify-content: flex-end; gap: 6px; margin-top: 10px; }
    `;
  const crear = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const btnVideo = crear("button", { id: "video", textContent: "＋ Descargar", title: "Mandar este video al Gestor de Descargas (se descarga ya o espera en el grupo, según lo elegido en la extensión)" });
  const btnAudio = crear("button", { id: "audio", textContent: "♪", title: "Mandar solo el audio al Gestor de Descargas" });
  const btnRecortar = crear("button", { id: "recortar", textContent: "✂", title: "Descargar solo un trozo (marca el inicio y el fin)" });
  const sepRecortar = crear("span", { className: "sep" });
  const pildora = crear("div", { className: "pildora", role: "group" });
  pildora.setAttribute("aria-label", "Gestor de Descargas");
  pildora.append(btnVideo, crear("span", { className: "sep" }), btnAudio, sepRecortar, btnRecortar);
  sombra.append(estilo, pildora);

  let videoActual = null;  // el <video> o la miniatura (enlace) sobre la que está el botón
  let enlaceActual = null; // si es una miniatura: el enlace al video
  let pilaActual = [];   // elementos bajo el cursor cuando se detectó el video (incluye la miniatura bajo una vista previa)
  let ocultarTimer = null;
  let ocupado = false; // mientras se muestra el resultado de un clic

  const esWeb = (u) => { try { return /^https?:$/.test(new URL(u, location.href).protocol); } catch { return false; } };

  function colocar() {
    if (!videoActual || !videoActual.isConnected) return ocultar();
    const r = videoActual.getBoundingClientRect();
    const [minAncho, minAlto] = enlaceActual ? [MIN_MINI_ANCHO, MIN_MINI_ALTO] : [MIN_ANCHO, MIN_ALTO];
    const visible = r.width >= minAncho && r.height >= minAlto && r.bottom > 0 && r.top < innerHeight &&
                    r.right > 0 && r.left < innerWidth;
    if (!visible) return ocultar();
    if (!ocupado) btnVideo.textContent = r.width < 240 ? "＋" : "＋ Añadir";   // en miniaturas pequeñas, solo el ícono
    btnRecortar.hidden = sepRecortar.hidden = !!enlaceActual;               // recortar necesita el reproductor (marcar tiempos)
    const ancho = pildora.offsetWidth || 140;
    const x = Math.min(Math.max(r.right - ancho - 10, 4), innerWidth - ancho - 4);
    const y = Math.min(Math.max(r.top + 10, 4), innerHeight - 40);
    pildora.style.left = `${x}px`;
    pildora.style.top = `${y}px`;
    pildora.classList.add("visible");
  }

  function ocultar() {
    if (ocupado) return;
    pildora.classList.remove("visible");
    videoActual = enlaceActual = null;
  }

  function programarOcultar() {
    clearTimeout(ocultarTimer);
    ocultarTimer = setTimeout(ocultar, 700);
  }

  // Miniatura bajo el cursor: un enlace a un video que contiene una imagen de tamaño razonable.
  function miniaturaBajoCursor(pila) {
    for (const el of pila) {
      const a = el.closest && el.closest("a[href]");
      if (!a || !PARECE_VIDEO.test(a.href) || !a.querySelector("img, video, picture")) continue;
      const r = a.getBoundingClientRect();
      if (r.width >= MIN_MINI_ANCHO && r.height >= MIN_MINI_ALTO) return a;   // el enlace del título (texto) no cuenta
    }
    return null;
  }

  // Los reproductores ponen capas encima del <video>, así que se busca por posición del cursor.
  let pendiente = false, ultimoX = 0, ultimoY = 0;
  function alMover(e) {
    if (!activo) return;
    ultimoX = e.clientX; ultimoY = e.clientY;
    if (pendiente) return;
    pendiente = true;
    requestAnimationFrame(() => {
      pendiente = false;
      if (document.fullscreenElement) return;
      const pila = document.elementsFromPoint(ultimoX, ultimoY);
      if (pila.includes(anfitrion)) { clearTimeout(ocultarTimer); return; }   // el cursor está sobre el botón
      const v = pila.find((el) => el.tagName === "VIDEO");
      if (v) {
        const r = v.getBoundingClientRect();
        if (r.width >= MIN_ANCHO && r.height >= MIN_ALTO) {
          clearTimeout(ocultarTimer);
          videoActual = v;
          enlaceActual = null;
          pilaActual = pila;
          colocar();
          return;
        }
      }
      const mini = miniaturaBajoCursor(pila);
      if (mini) {
        clearTimeout(ocultarTimer);
        videoActual = mini;
        enlaceActual = mini.href;
        pilaActual = pila;
        colocar();
        return;
      }
      if (pildora.classList.contains("visible")) programarOcultar();
    });
  }

  document.addEventListener("mousemove", alMover, { passive: true, capture: true });
  addEventListener("scroll", () => videoActual && colocar(), { passive: true, capture: true });
  addEventListener("resize", () => videoActual && colocar(), { passive: true });
  document.addEventListener("fullscreenchange", ocultar);
  pildora.addEventListener("mouseenter", () => clearTimeout(ocultarTimer));
  pildora.addEventListener("mouseleave", programarOcultar);

  // --- Clic: se recogen las direcciones candidatas y el service worker decide cuál usar -----
  const hrefs = (enlaces) => [...new Set(enlaces.filter(Boolean).map((a) => a.href).filter(esWeb))];

  // En inicios y feeds la página no identifica al video: se mandan los enlaces de alrededor
  // (de la tarjeta más cercana hacia fuera) y el service worker elige el permalink.
  function enlacesCercanos(v) {
    const niveles = [];
    let previo = -1;
    for (let el = v.parentElement, i = 0; el && el !== document.body && i < 10; el = el.parentElement, i++) {
      const enlaces = el.querySelectorAll("a[href]");
      if (enlaces.length > 80) break;              // ya es media página: no aporta
      if (enlaces.length === previo) continue;
      previo = enlaces.length;
      niveles.push(hrefs([...enlaces]).slice(0, 40));
    }
    return niveles;
  }

  function candidatas(v, deMiniatura = enlaceActual, pila = pilaActual) {
    if (deMiniatura) return { enlace: deMiniatura, pagina: location.href };   // miniatura: su enlace es el video
    const enlace = v.closest("a[href]");
    return {
      enlace: enlace && esWeb(enlace.href) ? enlace.href : null,       // p. ej. la miniatura de YouTube
      bajoCursor: hrefs(pila.map((el) => el.closest && el.closest("a[href]"))).slice(0, 20),
      cercanos: enlacesCercanos(v),
      fuente: v.currentSrc && esWeb(v.currentSrc) ? v.currentSrc : null, // vacía si es blob:
      pagina: location.href,
    };
  }

  // --- «Esta página» en la barra lateral: qué hay en esta pestaña --------------------------------
  // Solo responde el marco principal. Los enlaces se mandan tal cual; la extensión decide cuáles son videos.
  function recursosDePagina() {
    const abs = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; } };
    const texto = (n) => (n.getAttribute("title") || n.getAttribute("aria-label") || n.textContent || "").trim().slice(0, 160);
    const medios = [...document.querySelectorAll("video, audio")].slice(0, 30).map((m) => {
      const enlace = m.closest("a[href]");
      const fuente = m.currentSrc || (m.querySelector("source[src]") || {}).src || "";
      return { tipo: m.tagName.toLowerCase(), nombre: document.title,
        candidatas: { enlace: enlace && esWeb(enlace.href) ? enlace.href : null, cercanos: enlacesCercanos(m), fuente: abs(fuente), pagina: location.href } };
    });
    const enlaces = [];
    for (const n of document.querySelectorAll("a[href], iframe[src]")) {
      if (enlaces.length >= 500) break;
      const u = abs(n.href || n.src);
      if (u) enlaces.push({ url: u, nombre: n.tagName === "IFRAME" ? n.title || "" : texto(n) });
    }
    const archivos = [];
    const MEDIO = /\.(mp4|webm|mkv|mov|m4v|mp3|m4a|flac|ogg|opus|wav)(\?|#|$)/i;
    for (const a of document.querySelectorAll("a[href]")) {
      if (archivos.length >= 100) break;
      const u = MEDIO.test(a.pathname) && abs(a.href);
      if (u) archivos.push({ tipo: "enlace", url: u, nombre: texto(a) });
    }
    for (const i of document.images) {
      if (archivos.length >= 160) break;
      const u = (i.naturalWidth || 0) >= 160 && abs(i.currentSrc || i.src);
      if (u) archivos.push({ tipo: "imagen", url: u, nombre: i.alt || i.title || "" });
    }
    return { url: location.href, titulo: document.title, medios, enlaces, archivos };
  }

  try {
    chrome.runtime.onMessage.addListener((msg, sender, responder) => {
      if (window.top !== window || sender.id !== chrome.runtime.id || !msg) return false;
      if (msg.tipo === "recursos") responder(recursosDePagina());
      else if (msg.tipo === "video-estado") responder(estadoVideo());           // página «Recortar» de la barra lateral
      else if (msg.tipo === "video-ir") responder(irA(Number(msg.segundo), msg.hasta == null ? null : Number(msg.hasta)));
      return false;
    });
  } catch { /* la extensión se recargó */ }

  function mostrar(boton, texto, ms = 2200) {
    const original = boton.dataset.original || boton.textContent;
    boton.dataset.original = original;
    boton.textContent = texto;
    ocupado = true;
    setTimeout(() => { boton.textContent = original; ocupado = false; programarOcultar(); }, ms);
  }

  // Si el video ya está en la lista, el botón pregunta: un segundo clic (en 6 s) lo añade otra vez.
  let confirmar = null;   // { boton, datos, repetidas, hasta }

  function enviar(boton, modo) {
    return (e) => {
      if (!e.isTrusted || !videoActual) return;   // ignora clics fabricados por scripts de la página
      const repetir = confirmar && confirmar.boton === boton && Date.now() < confirmar.hasta ? confirmar : null;
      confirmar = null;
      const datos = repetir ? repetir.datos : candidatas(videoActual);
      mostrar(boton, "Enviando…", 10000);
      try {
        chrome.runtime.sendMessage({ tipo: "detectar-pagina", candidatas: datos, modo, ...(repetir ? { repetidas: repetir.repetidas } : {}) }, (r) => {
          ocupado = false;
          if (chrome.runtime.lastError || !r) return mostrar(boton, "✗ Sin respuesta");
          if (!r.ok && r.repetidas) {
            confirmar = { boton, datos, repetidas: r.repetidas, hasta: Date.now() + 6000 };
            return mostrar(boton, "Ya está en tu lista · pulsa otra vez para repetirlo", 6000);
          }
          mostrar(boton, r.ok ? (r.datos && r.datos.modo === "grupo" ? `✓ Al grupo «${String(r.datos.grupo).slice(0, 20)}»` : "✓ Descargando") : `✗ ${(r.error && r.error.mensaje) || "Error"}`.slice(0, 60), r.ok ? 2200 : 4500);
        });
      } catch {
        ocupado = false;
        mostrar(boton, "✗ Recarga la página");     // la extensión se actualizó mientras la página estaba abierta
      }
    };
  }
  btnVideo.addEventListener("click", enviar(btnVideo, "defecto"));
  btnAudio.addEventListener("click", enviar(btnAudio, "audio"));

  // --- ✂ Recortar en la propia página: marcar inicio y fin con el video reproduciéndose --------------
  // Copias de formatearTiempo / parsearTiempo (util.js): los content scripts no pueden importar.
  const fmt = (seg) => {
    if (seg == null || !Number.isFinite(seg) || seg < 0) return "";
    const s = Math.floor(seg), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    const dos = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${dos(m)}:${dos(r)}` : `${m}:${dos(r)}`;
  };
  const parsear = (texto) => {
    const t = String(texto ?? "").trim().replace(",", ".");
    if (!/^\d+(\.\d+)?$|^\d{1,3}:\d{1,2}(\.\d+)?$|^\d{1,2}:\d{1,2}:\d{1,2}(\.\d+)?$/.test(t)) return null;
    const partes = t.split(":").map(Number);
    return partes.slice(1).some((p) => p >= 60) ? null : partes.reduce((acc, p) => acc * 60 + p, 0);
  };

  const rc = {};
  rc.caja = crear("div", { className: "recorte", role: "dialog" });
  rc.caja.setAttribute("aria-label", "Descargar un trozo del video");
  rc.cerrar = crear("button", { className: "cerrar", textContent: "×", title: "Cerrar" });
  rc.ahora = crear("div", { className: "tenue" });
  const filaTiempo = (rotulo) => {
    const entrada = crear("input", { type: "text", spellcheck: false, placeholder: "0:00" });
    const marcar = crear("button", { textContent: "Marcar ahora", title: "Usa el segundo en el que va el video" });
    const fila = crear("div", { className: "fila" });
    fila.append(crear("span", { textContent: rotulo }), entrada, marcar);
    return { fila, entrada, marcar };
  };
  rc.desde = filaTiempo("Desde");
  rc.hasta = filaTiempo("Hasta");
  // Franja sobre el propio video (encima de la barra de YouTube): se arrastran las asas de inicio y fin
  // —el video muestra ese fotograma mientras arrastras— o la zona entera para moverla.
  rc.pista = crear("div", { className: "pista" });
  rc.fondo = crear("div", { className: "fondo", title: "Haz clic para ir a ese punto del video" });
  rc.zona = crear("div", { className: "zona", title: "Arrastra para mover el trozo" });
  rc.manijaA = crear("div", { className: "manija", title: "Inicio del trozo: arrástralo" });
  rc.manijaB = crear("div", { className: "manija", title: "Fin del trozo: arrástralo" });
  rc.etqA = crear("div", { className: "etq" });
  rc.etqB = crear("div", { className: "etq" });
  rc.cabezal = crear("div", { className: "cabezal" });
  rc.pista.append(rc.fondo, rc.zona, rc.cabezal, rc.manijaA, rc.manijaB, rc.etqA, rc.etqB);
  rc.exacto = crear("input", { type: "checkbox" });
  rc.audio = crear("input", { type: "checkbox" });
  const casilla = (input, texto) => { const l = crear("label"); l.append(input, crear("span", { textContent: texto })); return l; };
  rc.resumen = crear("div", { className: "tenue" });
  rc.error = crear("div", { className: "error" });
  rc.ver = crear("button", { textContent: "▶ Ver trozo", title: "Reproduce solo el trozo marcado" });
  rc.descargar = crear("button", { className: "primario", textContent: "Descargar trozo" });
  const cab = crear("div", { className: "cab" });
  cab.append(crear("span", { textContent: "✂ Descargar un trozo" }), rc.cerrar);
  const acciones = crear("div", { className: "acciones" });
  acciones.append(rc.ver, rc.descargar);
  rc.caja.append(cab, rc.ahora, crear("div", { className: "tenue", textContent: "Arrastra las asas sobre el video, o marca y escribe los tiempos:" }),
    rc.desde.fila, rc.hasta.fila,
    casilla(rc.exacto, "Corte exacto (empieza en el segundo justo; tarda un poco más)"), casilla(rc.audio, "Solo el audio"),
    rc.resumen, rc.error, acciones);
  sombra.append(rc.pista, rc.caja);
  // Que escribir en el panel no active los atajos de teclado de YouTube (espacio, k, j, l, números…).
  for (const tipo of ["keydown", "keyup", "keypress"]) rc.caja.addEventListener(tipo, (e) => e.stopPropagation());

  let videoRecorte = null, pilaRecorte = [], vistaHasta = null, temporizadorRecorte = null, repetirRecorte = null;
  let arrastre = null;   // { tipo: "a" | "b" | "zona", t0, a0, b0 } mientras se arrastra en la franja

  function leerTramo() {
    const a = parsear(rc.desde.entrada.value), b = parsear(rc.hasta.entrada.value);
    const dur = videoRecorte && Number.isFinite(videoRecorte.duration) ? videoRecorte.duration : null;
    if (a == null) return { error: "No entiendo el inicio. Escríbelo como 1:20 o 1:02:03." };
    if (b == null) return { error: "No entiendo el final. Escríbelo como 3:45 o 1:05:00." };
    if (b <= a) return { error: "El final tiene que ser después del inicio." };
    if (dur && a >= dur) return { error: `El inicio está después del final del video (${fmt(dur)}).` };
    return { tramo: [a, dur ? Math.min(b, dur) : b] };
  }

  function pintarRecorte() {
    if (!videoRecorte || !videoRecorte.isConnected) return cerrarRecorte();
    const v = videoRecorte, dur = Number.isFinite(v.duration) ? v.duration : null;
    rc.ahora.textContent = dur ? `Ahora: ${fmt(v.currentTime)} de ${fmt(dur)}` : "Es un directo: no se puede recortar mientras se emite.";
    if (vistaHasta != null && v.currentTime >= vistaHasta) { v.pause(); vistaHasta = null; }
    const { tramo, error } = leerTramo();
    rc.error.textContent = rc.desde.entrada.value || rc.hasta.entrada.value ? error || "" : "";
    rc.descargar.disabled = rc.ver.disabled = !tramo || !dur;
    rc.resumen.textContent = tramo ? `Trozo de ${fmt(tramo[1] - tramo[0])}` : "";
    const r = v.getBoundingClientRect();
    // Franja: a lo ancho del video, justo encima de la barra de progreso de YouTube.
    rc.pista.classList.toggle("visible", !!dur);
    rc.pista.style.left = `${r.left + 14}px`;
    rc.pista.style.width = `${Math.max(r.width - 28, 120)}px`;
    rc.pista.style.top = `${Math.min(Math.max(r.bottom - 112, r.top + 40), innerHeight - 48)}px`;
    if (dur) {
      const pct = (s) => `${(Math.min(Math.max(s, 0), dur) / dur) * 100}%`;
      rc.cabezal.style.left = pct(v.currentTime);
      for (const x of [rc.zona, rc.manijaA, rc.manijaB, rc.etqA, rc.etqB]) x.style.display = tramo ? "block" : "none";
      if (tramo) {
        rc.zona.style.left = pct(tramo[0]); rc.zona.style.width = `${((tramo[1] - tramo[0]) / dur) * 100}%`;
        rc.manijaA.style.left = rc.etqA.style.left = pct(tramo[0]);
        rc.manijaB.style.left = rc.etqB.style.left = pct(tramo[1]);
        rc.etqA.textContent = fmt(tramo[0]); rc.etqB.textContent = fmt(tramo[1]);
      }
    }
    // Panel: arriba a la derecha del video (debajo del botón). Si así tapa la franja (reproductor pequeño),
    // va al lado del video —sobre la columna de sugeridos— o encima de él.
    const alto = rc.caja.offsetHeight || 300, franja = parseFloat(rc.pista.style.top);
    let x = Math.min(Math.max(r.right - 304, 8), innerWidth - 300), y = Math.min(Math.max(r.top + 52, 8), innerHeight - alto - 8);
    if (y + alto > franja - 26) {
      if (innerWidth - r.right >= 304) { x = r.right + 8; y = Math.min(Math.max(r.top, 8), innerHeight - alto - 8); }
      else if (r.top - alto - 8 >= 8) y = r.top - alto - 8;
    }
    rc.caja.style.left = `${x}px`;
    rc.caja.style.top = `${y}px`;
  }

  function abrirRecorte(v, pila = []) {
    videoRecorte = v; pilaRecorte = pila; repetirRecorte = null;
    const dur = Number.isFinite(v.duration) ? v.duration : null;
    rc.desde.entrada.value = fmt(v.currentTime);
    rc.hasta.entrada.value = dur ? fmt(Math.min(v.currentTime + 60, dur)) : "";
    rc.descargar.textContent = "Descargar trozo";
    rc.caja.classList.add("visible");
    ocupado = false; ocultar();
    clearInterval(temporizadorRecorte);
    temporizadorRecorte = setInterval(pintarRecorte, 250);
    pintarRecorte();
    rc.desde.entrada.focus();
  }

  function cerrarRecorte() {
    clearInterval(temporizadorRecorte);
    rc.caja.classList.remove("visible");
    rc.pista.classList.remove("visible");
    videoRecorte = null; vistaHasta = null; arrastre = null;
  }

  function irA(segundo, hasta = null) {
    const v = videoRecorte && videoRecorte.isConnected ? videoRecorte : videoPrincipal();
    if (!v || !Number.isFinite(segundo)) return { ok: false };
    v.currentTime = segundo;
    vistaHasta = Number.isFinite(hasta) ? hasta : null;
    v.play().catch(() => {});
    return { ok: true };
  }

  function videoPrincipal() {
    if (videoRecorte && videoRecorte.isConnected) return videoRecorte;
    let mejor = null, area = 0;
    for (const v of document.querySelectorAll("video")) {
      const r = v.getBoundingClientRect();
      if (r.width * r.height > area && v.duration) { mejor = v; area = r.width * r.height; }
    }
    return mejor;
  }

  function estadoVideo() {
    const v = videoPrincipal();
    if (!v) return { url: location.href, titulo: document.title, hayVideo: false };
    return { url: location.href, titulo: document.title, hayVideo: true, actual: v.currentTime,
             duracion: Number.isFinite(v.duration) ? v.duration : null, enVivo: !Number.isFinite(v.duration),
             candidatas: candidatas(v, null, v === videoRecorte ? pilaRecorte : []) };
  }

  btnRecortar.addEventListener("click", (e) => {
    if (!e.isTrusted || !videoActual || enlaceActual || videoActual.tagName !== "VIDEO") return;
    abrirRecorte(videoActual, pilaActual);
  });
  rc.cerrar.addEventListener("click", cerrarRecorte);
  rc.desde.marcar.addEventListener("click", () => { if (videoRecorte) rc.desde.entrada.value = fmt(videoRecorte.currentTime); repetirRecorte = null; });
  rc.hasta.marcar.addEventListener("click", () => { if (videoRecorte) rc.hasta.entrada.value = fmt(videoRecorte.currentTime); repetirRecorte = null; });
  for (const x of [rc.desde.entrada, rc.hasta.entrada]) x.addEventListener("input", () => { repetirRecorte = null; rc.descargar.textContent = "Descargar trozo"; });
  const segundoEn = (clientX) => {
    const r = rc.fondo.getBoundingClientRect(), dur = videoRecorte.duration;
    return Math.min(Math.max((clientX - r.left) / r.width, 0), 1) * dur;
  };
  const mostrarFotograma = (s) => { if (videoRecorte && !videoRecorte.seeking) videoRecorte.currentTime = s; };

  function empezarArrastre(tipo) {
    return (e) => {
      if (!e.isTrusted || !videoRecorte || !Number.isFinite(videoRecorte.duration)) return;
      const { tramo } = leerTramo();
      if (!tramo) return;
      e.preventDefault(); e.stopPropagation();
      e.currentTarget.setPointerCapture(e.pointerId);
      videoRecorte.pause();
      arrastre = { tipo, t0: segundoEn(e.clientX), a0: tramo[0], b0: tramo[1] };
    };
  }
  function moverArrastre(e) {
    if (!arrastre || !videoRecorte) return;
    const dur = videoRecorte.duration, t = segundoEn(e.clientX), { a0, b0 } = arrastre;
    let a = a0, b = b0;
    if (arrastre.tipo === "a") { a = Math.min(Math.floor(t), b0 - 1); mostrarFotograma(a); }
    else if (arrastre.tipo === "b") { b = Math.max(Math.floor(t), a0 + 1); mostrarFotograma(b); }
    else {
      const largo = b0 - a0;
      a = Math.min(Math.max(Math.floor(a0 + t - arrastre.t0), 0), Math.floor(dur - largo));
      b = a + largo; mostrarFotograma(a);
    }
    rc.desde.entrada.value = fmt(Math.max(a, 0)); rc.hasta.entrada.value = fmt(Math.min(b, dur));
    repetirRecorte = null; rc.descargar.textContent = "Descargar trozo";
    pintarRecorte();
  }
  const terminarArrastre = () => { arrastre = null; };
  for (const [el, tipo] of [[rc.manijaA, "a"], [rc.manijaB, "b"], [rc.zona, "zona"]]) {
    el.addEventListener("pointerdown", empezarArrastre(tipo));
    el.addEventListener("pointermove", moverArrastre);
    el.addEventListener("pointerup", terminarArrastre);
    el.addEventListener("pointercancel", terminarArrastre);
  }
  rc.fondo.addEventListener("pointerdown", (e) => {     // clic en la franja (fuera del trozo): ir a ese punto
    if (!e.isTrusted || !videoRecorte || !Number.isFinite(videoRecorte.duration)) return;
    e.preventDefault(); e.stopPropagation();
    videoRecorte.currentTime = segundoEn(e.clientX);
  });
  rc.ver.addEventListener("click", () => { const { tramo } = leerTramo(); if (tramo) irA(tramo[0], tramo[1]); });
  rc.descargar.addEventListener("click", (e) => {
    if (!e.isTrusted || !videoRecorte) return;
    const { tramo, error } = leerTramo();
    if (!tramo) { rc.error.textContent = error; return; }
    const mensaje = { tipo: "recortar", candidatas: candidatas(videoRecorte, null, pilaRecorte), tramos: [tramo],
                      exacto: rc.exacto.checked, audio: rc.audio.checked, ...(repetirRecorte ? { repetidas: repetirRecorte } : {}) };
    repetirRecorte = null;
    rc.descargar.disabled = true; rc.descargar.textContent = "Enviando…";
    try {
      chrome.runtime.sendMessage(mensaje, (r) => {
        rc.descargar.disabled = false;
        if (chrome.runtime.lastError || !r) { rc.descargar.textContent = "Descargar trozo"; rc.error.textContent = "La extensión no respondió. Recarga la página."; return; }
        if (!r.ok && r.repetidas) {
          repetirRecorte = r.repetidas;
          rc.descargar.textContent = "Descargar otra vez";
          rc.error.textContent = "Ese trozo ya está en tu lista. Pulsa «Descargar otra vez» si lo quieres repetido.";
          return;
        }
        if (!r.ok) { rc.descargar.textContent = "Descargar trozo"; rc.error.textContent = [r.error && r.error.mensaje, r.error && r.error.solucion].filter(Boolean).join(" "); return; }
        rc.descargar.textContent = r.datos && r.datos.modo === "grupo" ? "✓ Añadido al grupo" : "✓ Descargando";
        setTimeout(cerrarRecorte, 1800);
      });
    } catch {
      rc.descargar.disabled = false;
      rc.error.textContent = "La extensión se actualizó: recarga la página.";
    }
  });

  (document.body || document.documentElement).appendChild(anfitrion);
})();
