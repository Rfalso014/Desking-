// Botón flotante sobre los videos: aparece al pasar el cursor y envía el video a la aplicación.
// Este script SOLO lee la página localmente; no envía nada hasta que el usuario hace clic.
// (Script clásico, no módulo: los content scripts no pueden usar "import".)
(() => {
  if (window.__gestorDescargasActivo) return; // evita duplicarlo si Chrome lo inyecta dos veces
  window.__gestorDescargasActivo = true;

  const MIN_ANCHO = 200, MIN_ALTO = 110;

  // --- Interfaz en un Shadow DOM cerrado: los estilos de la página no la rompen ---------
  const anfitrion = document.createElement("div");
  anfitrion.style.cssText = "all:initial;position:fixed;z-index:2147483647;top:0;left:0;width:0;height:0;";
  const sombra = anfitrion.attachShadow({ mode: "closed" });
  const estilo = document.createElement("style");
  estilo.textContent = `
      .pildora { position: fixed; display: none; align-items: stretch; font: 600 13px/1 system-ui, "Segoe UI", sans-serif;
                 background: #1a73e8; color: #fff; border-radius: 999px; box-shadow: 0 2px 10px rgba(0,0,0,.45);
                 overflow: hidden; user-select: none; }
      .pildora.visible { display: flex; }
      button { all: unset; cursor: pointer; padding: 8px 12px; display: flex; align-items: center; gap: 6px; }
      button:hover { background: rgba(255,255,255,.2); }
      button:focus-visible { outline: 2px solid #fff; outline-offset: -2px; }
      .sep { width: 1px; background: rgba(255,255,255,.4); }
    `;
  const crear = (tag, props = {}) => Object.assign(document.createElement(tag), props);
  const btnVideo = crear("button", { id: "video", textContent: "⬇ Descargar", title: "Descargar este video con Gestor de Descargas" });
  const btnAudio = crear("button", { id: "audio", textContent: "♪", title: "Descargar solo el audio" });
  const pildora = crear("div", { className: "pildora", role: "group" });
  pildora.setAttribute("aria-label", "Gestor de Descargas");
  pildora.append(btnVideo, crear("span", { className: "sep" }), btnAudio);
  sombra.append(estilo, pildora);

  let videoActual = null;
  let ocultarTimer = null;
  let ocupado = false; // mientras se muestra el resultado de un clic

  const esWeb = (u) => { try { return /^https?:$/.test(new URL(u, location.href).protocol); } catch { return false; } };

  function colocar() {
    if (!videoActual || !videoActual.isConnected) return ocultar();
    const r = videoActual.getBoundingClientRect();
    const visible = r.width >= MIN_ANCHO && r.height >= MIN_ALTO && r.bottom > 0 && r.top < innerHeight &&
                    r.right > 0 && r.left < innerWidth;
    if (!visible) return ocultar();
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
    videoActual = null;
  }

  function programarOcultar() {
    clearTimeout(ocultarTimer);
    ocultarTimer = setTimeout(ocultar, 700);
  }

  // Los reproductores ponen capas encima del <video>, así que se busca por posición del cursor.
  let pendiente = false, ultimoX = 0, ultimoY = 0;
  function alMover(e) {
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
          colocar();
          return;
        }
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
  function candidatas(v) {
    const enlace = v.closest("a[href]");
    return {
      enlace: enlace && esWeb(enlace.href) ? enlace.href : null,       // p. ej. la miniatura de YouTube
      fuente: v.currentSrc && esWeb(v.currentSrc) ? v.currentSrc : null, // vacía si es blob:
      pagina: location.href,
    };
  }

  function mostrar(boton, texto, ms = 2200) {
    const original = boton.dataset.original || boton.textContent;
    boton.dataset.original = original;
    boton.textContent = texto;
    ocupado = true;
    setTimeout(() => { boton.textContent = original; ocupado = false; programarOcultar(); }, ms);
  }

  function enviar(boton, modo) {
    return (e) => {
      if (!e.isTrusted || !videoActual) return;   // ignora clics fabricados por scripts de la página
      const datos = candidatas(videoActual);
      mostrar(boton, "Enviando…", 10000);
      chrome.runtime.sendMessage({ tipo: "encolar-pagina", candidatas: datos, modo }, (r) => {
        ocupado = false;
        if (chrome.runtime.lastError || !r) return mostrar(boton, "✗ Sin respuesta");
        mostrar(boton, r.ok ? "✓ Añadido" : `✗ ${(r.error && r.error.mensaje) || "Error"}`.slice(0, 60), r.ok ? 2200 : 4500);
      });
    };
  }
  btnVideo.addEventListener("click", enviar(btnVideo, "video"));
  btnAudio.addEventListener("click", enviar(btnAudio, "audio"));

  (document.body || document.documentElement).appendChild(anfitrion);
})();
