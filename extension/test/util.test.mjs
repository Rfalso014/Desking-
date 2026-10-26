// Ejecutar: node --test extension/test
import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  accionesDisponibles, armarRecursos, formatearTiempo, opcionesRecorte, parsearTiempo, textoTramos, validarTramos, compararVersiones, esErrorDeVersion, tamanosPorCalidad, atributoTema, claveRecurso, claveVideo, construirOpciones, elementosDesdeOpciones, fusionarRecursos, siguienteTema, elegirUrlParaMenu, elegirUrlParaVideo, enlaceVecino, esEnlaceDeVideo, esPaginaDeFeed, esUrlWeb, filtrarTareas, formatearCodigo, formatearDuracion, formatearEta,
  formatearTamano, formatearVelocidad, mensajeSinServidor, esMedioDirecto, ordenarMedios, miniaturaSegura, nombreNavegador, nombreSitio, resumenCola,
} from "../util.js";

test("solo http/https son URLs web", () => {
  assert.equal(esUrlWeb("https://a.com/x"), true);
  for (const u of ["blob:https://a.com/1", "data:text/html,x", "javascript:alert(1)", "file:///c:/x", "", "no url", null])
    assert.equal(esUrlWeb(u), false, String(u));
});

test("clic en enlace usa el enlace", () => {
  assert.equal(elegirUrlParaMenu({ linkUrl: "https://a.com/v", srcUrl: "https://a.com/i.png", pageUrl: "https://a.com/" }, {}), "https://a.com/v");
});

test("clic en video usa su fuente", () => {
  assert.equal(elegirUrlParaMenu({ srcUrl: "https://cdn.a.com/v.mp4", pageUrl: "https://a.com/p" }, {}), "https://cdn.a.com/v.mp4");
});

test("fuente blob: cae a la página", () => {
  assert.equal(elegirUrlParaMenu({ srcUrl: "blob:https://a.com/123", pageUrl: "https://a.com/p" }, {}), "https://a.com/p");
});

test("sin nada válido devuelve null", () => {
  assert.equal(elegirUrlParaMenu({ srcUrl: "blob:x", pageUrl: "chrome://extensions" }, { url: "about:blank" }), null);
});

test("video: prioriza el enlace que lo envuelve, luego la fuente directa, luego la página", () => {
  const pagina = "https://noticias.com/articulo";
  assert.equal(elegirUrlParaVideo({ enlace: "https://youtube.com/watch?v=1", fuente: null, pagina }), "https://youtube.com/watch?v=1");
  assert.equal(elegirUrlParaVideo({ enlace: null, fuente: "https://cdn.a.com/v.mp4", pagina }), "https://cdn.a.com/v.mp4");
  assert.equal(elegirUrlParaVideo({ enlace: null, fuente: null, pagina }), pagina);
  assert.equal(elegirUrlParaVideo({ enlace: "javascript:x", fuente: "blob:https://a.com/1", pagina: "about:blank" }), null);
  assert.equal(elegirUrlParaVideo(null), null);
});

test("permalinks de video frente a inicios y feeds", () => {
  for (const u of ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/abcdefghijk",
    "https://x.com/nasa/status/123456", "https://www.instagram.com/reel/Cabc12/", "https://www.tiktok.com/@a/video/123",
    "https://www.facebook.com/pagina/videos/123456/", "https://www.facebook.com/watch/?v=123", "https://www.reddit.com/r/videos/comments/ab12/x/",
    "https://vimeo.com/76979871", "https://www.dailymotion.com/video/x8abc"])
    assert.equal(esEnlaceDeVideo(u), true, u);
  const feeds = ["https://www.youtube.com/", "https://www.youtube.com/feed/subscriptions", "https://www.youtube.com/results?search_query=x",
    "https://www.youtube.com/@canal/videos", "https://x.com/home", "https://twitter.com/nasa", "https://www.instagram.com/",
    "https://www.tiktok.com/foryou", "https://www.facebook.com/", "https://www.facebook.com/watch/", "https://www.reddit.com/r/videos/"];
  for (const u of feeds) {
    assert.equal(esEnlaceDeVideo(u), false, u);
    assert.equal(esPaginaDeFeed(u), true, u);
  }
  for (const u of ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/playlist?list=PL1", "https://noticias.com/"])
    assert.equal(esPaginaDeFeed(u), false, u);
});

test("el mismo video con otros parámetros tiene la misma clave", () => {
  assert.equal(claveVideo("https://youtu.be/abcdefghijk"), claveVideo("https://www.youtube.com/watch?v=abcdefghijk&t=30"));
  assert.equal(claveVideo("https://x.com/a/status/1"), claveVideo("https://x.com/a/status/1/"));
});

test("enlace vecino: el permalink de la tarjeta, pero nunca uno adivinado en un feed", () => {
  const v1 = "https://www.youtube.com/watch?v=aaaaaaaaaaa", v2 = "https://www.youtube.com/watch?v=bbbbbbbbbbb";
  assert.equal(enlaceVecino([["https://www.youtube.com/@canal"], [v1, `${v1}&t=5`, "https://www.youtube.com/@canal"], [v1, v2]]), v1);
  assert.equal(enlaceVecino([[], [v1, v2]]), null);
  assert.equal(enlaceVecino("basura"), null);
});

test("vista previa en el inicio de YouTube: usa la miniatura bajo el cursor, nunca la página", () => {
  const pagina = "https://www.youtube.com/", v = "https://www.youtube.com/watch?v=aaaaaaaaaaa";
  assert.equal(elegirUrlParaVideo({ bajoCursor: ["https://www.youtube.com/@canal", v], cercanos: [], pagina }), v);
  assert.equal(elegirUrlParaVideo({ bajoCursor: [], cercanos: [[v]], pagina }), v);
  assert.equal(elegirUrlParaVideo({ bajoCursor: [], cercanos: [], fuente: null, pagina }), null);
  assert.equal(elegirUrlParaVideo({ cercanos: [[v]], pagina: "https://x.com/home" }), v);
});

test("menú contextual: no manda la dirección de un feed", () => {
  assert.equal(elegirUrlParaMenu({ srcUrl: "blob:https://x.com/1", pageUrl: "https://x.com/home" }, { url: "https://x.com/home" }), null);
  assert.equal(elegirUrlParaMenu({ srcUrl: "blob:https://x.com/1", pageUrl: "https://x.com/a/status/1" }, {}), "https://x.com/a/status/1");
});

test("gestor apagado o sin respuesta: mensaje comprensible", () => {
  assert.match(mensajeSinServidor().mensaje, /apagado/);
  assert.match(mensajeSinServidor(true).mensaje, /a tiempo/);
  assert.match(mensajeSinServidor().solucion, /GestorDescargas\.exe/);
});

test("enlaces directos de video: listas completas sí, trozos y anuncios no", () => {
  assert.deepEqual(esMedioDirecto("https://cdn.x.com/v/master.m3u8?t=1"), { tipo: "hls", prioridad: 0 });
  assert.equal(esMedioDirecto("https://cdn.x.com/v/manifest", "application/dash+xml").tipo, "dash");
  assert.equal(esMedioDirecto("https://cdn.x.com/peli.mp4", "", 9e6).tipo, "video");
  assert.equal(esMedioDirecto("https://cdn.x.com/stream", "video/mp4").tipo, "video");
  assert.equal(esMedioDirecto("https://cdn.x.com/cancion.mp3").tipo, "audio");
  assert.equal(esMedioDirecto("https://cdn.x.com/v/seg-12.ts"), null);
  assert.equal(esMedioDirecto("https://cdn.x.com/v/chunk-3.m4s"), null);
  assert.equal(esMedioDirecto("https://cdn.x.com/v/x", "video/mp2t"), null);
  assert.equal(esMedioDirecto("https://cdn.x.com/v/a.mp4?range=0-1000"), null);
  assert.equal(esMedioDirecto("https://rr1---sn-x.googlevideo.com/videoplayback?x=1", "video/webm"), null);
  assert.equal(esMedioDirecto("https://cdn.x.com/anuncio.mp4", "", 20000), null);
  assert.equal(esMedioDirecto("https://cdn.x.com/pagina.html", "text/html"), null);
  assert.equal(esMedioDirecto("blob:https://x.com/1"), null);
});

test("enlaces directos: primero la lista maestra, luego video, luego audio", () => {
  const orden = ordenarMedios([
    { url: "a.mp3", tipo: "audio", prioridad: 3, visto: 1 }, { url: "v.mp4", tipo: "video", prioridad: 2, visto: 2 },
    { url: "variante.m3u8", tipo: "hls", prioridad: 0, visto: 5 }, { url: "maestra.m3u8", tipo: "hls", prioridad: 0, visto: 3 },
  ]).map((m) => m.url);
  assert.deepEqual(orden, ["maestra.m3u8", "variante.m3u8", "v.mp4", "a.mp3"]);
});

test("acciones por estado", () => {
  assert.deepEqual(accionesDisponibles("descargando"), ["cancelar"]);
  assert.deepEqual(accionesDisponibles("error"), ["reintentar", "eliminar"]);
  assert.deepEqual(accionesDisponibles("detectado"), ["iniciar", "eliminar"]);
  assert.deepEqual(accionesDisponibles("completado"), ["eliminar"]);
});

test("utilidades de texto", () => {
  assert.equal(nombreSitio("https://www.youtube.com/watch?v=1"), "youtube.com");
  assert.equal(formatearTamano(0), "?");
  assert.equal(formatearTamano(1048576 * 5), "5.0 MB");
});

test("el código de vinculación se formatea mientras se escribe", () => {
  assert.equal(formatearCodigo("k7m2"), "K7M2");
  assert.equal(formatearCodigo("k7m29qxa"), "K7M2-9QXA");
  assert.equal(formatearCodigo(" k7m2-9q?x!a999 "), "K7M2-9QXA");   // limpia símbolos y recorta a 8
  assert.equal(formatearCodigo(null), "");
});

test("nombre del navegador para la lista de vinculados", () => {
  assert.equal(nombreNavegador("Mozilla/5.0 Chrome/120 Safari/537 Edg/120"), "Edge en este equipo");
  assert.equal(nombreNavegador("Mozilla/5.0 Chrome/120 Safari/537"), "Chrome en este equipo");
  assert.equal(nombreNavegador(""), "Navegador en este equipo");
});

test("formatos de velocidad, tiempo y duración", () => {
  assert.equal(formatearVelocidad(0), "");
  assert.equal(formatearVelocidad(2048), "2 KB/s");
  assert.equal(formatearVelocidad(6.4 * 1048576), "6.4 MB/s");
  assert.equal(formatearEta(45), "45 s");
  assert.equal(formatearEta(125), "2 min 5 s");
  assert.equal(formatearEta(3700), "1 h 1 min");
  assert.equal(formatearEta(null), "");
  assert.equal(formatearDuracion(65), "1:05");
  assert.equal(formatearDuracion(3725), "1:02:05");
});

const COLA = [
  { id: "1", estado: "descargando", titulo: "Python avanzado", sitio: "Youtube", url: "https://y.com/1", velocidad: 2e6 },
  { id: "2", estado: "completado", titulo: "Cocina", sitio: "Vimeo", url: "https://v.com/2" },
  { id: "3", estado: "error", titulo: "Privado", sitio: "Youtube", url: "https://y.com/3" },
  { id: "4", estado: "detectado", titulo: null, sitio: null, url: "https://a.com/musica" },
  { id: "5", estado: "pendiente", titulo: "En espera", sitio: "Ejemplo", url: "https://e.com/5" },
];

test("filtros de la cola", () => {
  const ids = (f, q) => filtrarTareas(COLA, f, q).map((t) => t.id);
  assert.deepEqual(ids("todas"), ["1", "2", "3", "4", "5"]);
  assert.deepEqual(ids("activas"), ["1", "4", "5"]);
  assert.deepEqual(ids("completadas"), ["2"]);
  assert.deepEqual(ids("errores"), ["3"]);
  assert.deepEqual(ids("todas", "YOUTUBE"), ["1", "3"]);        // busca sin distinguir mayúsculas, en título/sitio/URL
  assert.deepEqual(ids("todas", "musica"), ["4"]);
  assert.deepEqual(ids("errores", "cocina"), []);
});

test("resumen de la cola", () => {
  assert.deepEqual(resumenCola(COLA), { descargando: 1, enEspera: 1, detectados: 1, velocidad: 2e6 });
});

test("solo se cargan miniaturas http/https", () => {
  assert.equal(miniaturaSegura("https://a.com/t.jpg"), "https://a.com/t.jpg");
  for (const u of ["javascript:alert(1)", "data:image/png;base64,AAA", "blob:x", "", null, 5]) assert.equal(miniaturaSegura(u), null, String(u));
});

import { nombreDeArchivo as _nombre, ordenarRecursos as _ordenar } from "../util.js";
test("nombreDeArchivo usa el último tramo de la ruta, sin parámetros", () => {
  assert.equal(_nombre("https://i.ytimg.com/vi/a58/hq720.jpg?sqp=-oaym&rs=AOn4"), "hq720.jpg");
  assert.equal(_nombre("https://sitio.com/"), "sitio.com");
});
test("ordenarRecursos pone videos primero e imágenes al final", () => {
  const r = _ordenar([{ tipo: "imagen", url: "1" }, { tipo: "video", url: "2" }, { tipo: "enlace", url: "3" }, { tipo: "imagen", url: "4" }]);
  assert.deepEqual(r.map((x) => x.url), ["2", "3", "1", "4"]);
});

test("esta página: arma la lista con la página, los <video>, las miniaturas de un feed y los archivos", () => {
  const v1 = "https://www.youtube.com/watch?v=aaaaaaaaaaa", v2 = "https://www.youtube.com/watch?v=bbbbbbbbbbb";
  const r = armarRecursos({
    url: "https://www.youtube.com/", titulo: "YouTube",
    medios: [{ tipo: "video", nombre: "YouTube", candidatas: { cercanos: [[v1]], pagina: "https://www.youtube.com/" } }],
    enlaces: [{ url: v1, nombre: "12:34" }, { url: `${v1}&t=5`, nombre: "Tutorial completo de edición" }, { url: v2, nombre: "Otro" },
      { url: "https://www.youtube.com/@canal", nombre: "Canal" }, { url: "javascript:alert(1)", nombre: "x" }],
    archivos: [{ tipo: "imagen", url: "https://i.ytimg.com/a.jpg", nombre: "" }, { tipo: "raro", url: "https://a.com/x", nombre: "" }],
  });
  assert.deepEqual(r.map((x) => [x.tipo, x.url]), [["video", v1], ["video", v2], ["imagen", "https://i.ytimg.com/a.jpg"]]);
  assert.equal(r[0].nombre, "Tutorial completo de edición");      // se queda con el nombre más completo
  assert.deepEqual(armarRecursos(null), []);
});

test("esta página: al recargar no se pierde lo encontrado antes", () => {
  const a = { tipo: "video", url: "https://x.com/a/status/1", nombre: "A" }, b = { tipo: "video", url: "https://x.com/b/status/2", nombre: "B" };
  const c = { tipo: "video", url: "https://x.com/c/status/3", nombre: "C" };
  const primera = fusionarRecursos([], [a, b]);
  assert.deepEqual(primera.map((r) => r.anterior), [false, false]);
  const segunda = fusionarRecursos(primera, [{ ...b, url: "https://x.com/b/status/2/" }, c]);
  assert.deepEqual(segunda.map((r) => [r.nombre, r.anterior]), [["A", true], ["B", false], ["C", false]]);
  assert.equal(fusionarRecursos(segunda, [], 2).length, 2);
  assert.equal(claveRecurso(b), claveRecurso({ url: "https://x.com/b/status/2/" }));
});

test("modo edición: viaja solo con el video y se recupera al reabrir", () => {
  const [video, audio] = construirOpciones({ video: true, audio: true, editable: true, portada: false });
  assert.equal(video.editable, true);
  assert.equal("editable" in audio, false);
  assert.equal(elementosDesdeOpciones(video).editable, true);
  assert.equal("editable" in construirOpciones({ video: true })[0], false);
});

test("tema: automático -> día -> noche -> automático", () => {
  assert.equal(siguienteTema("auto"), "dia");
  assert.equal(siguienteTema("dia"), "noche");
  assert.equal(siguienteTema("noche"), "auto");
  assert.equal(siguienteTema("raro"), "auto");
  assert.deepEqual(["auto", "dia", "noche"].map(atributoTema), [null, "light", "dark"]);
});

test("versiones: detecta una aplicación anterior a la extensión", () => {
  assert.equal(compararVersiones("1.0.0", "1.1.0"), -1);
  assert.equal(compararVersiones("1.10.0", "1.9.2"), 1);
  assert.equal(compararVersiones("1.1", "1.1.0"), 0);
  assert.equal(compararVersiones(undefined, "1.1.0"), -1);
  assert.equal(esErrorDeVersion({ mensaje: "Opción no válida: 'editable'." }), true);
  assert.equal(esErrorDeVersion({ mensaje: "La URL es demasiado larga." }), false);
});

test("tamaño aproximado por calidad (igual que en la aplicación)", () => {
  const MB = 1048576;
  const f = (tipo, altura, mb) => ({ tipo, altura, tamano: mb * MB });
  const r = tamanosPorCalidad([f("solo_audio", null, 10), f("solo_video", 2160, 669), f("solo_video", 1080, 108), f("solo_video", 1080, 90),
    f("solo_video", 720, 52), f("video+audio", 360, 20)]);
  assert.deepEqual(r, [[2160, 679 * MB], [1080, 118 * MB], [720, 62 * MB]]);
  assert.deepEqual(tamanosPorCalidad([]), []);
});

test("el botón sobre miniaturas reconoce los mismos videos que util.js", () => {
  const codigo = readFileSync(new URL("../content.js", import.meta.url), "utf8");
  const literal = codigo.match(/const PARECE_VIDEO = (\/.*\/i);/)[1];
  const PARECE_VIDEO = new Function(`return ${literal}`)();
  const urls = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/abcdefghijk",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://x.com/nasa/status/123456", "https://www.instagram.com/reel/Cabc12/",
    "https://www.tiktok.com/@a/video/123", "https://www.facebook.com/pagina/videos/123456/", "https://www.facebook.com/watch/?v=123",
    "https://www.reddit.com/r/videos/comments/ab12/x/", "https://vimeo.com/76979871", "https://www.dailymotion.com/video/x8abc",
    "https://www.twitch.tv/videos/123", "https://noticias.com/videos/mi-video", "https://www.youtube.com/", "https://www.youtube.com/@canal/videos",
    "https://www.youtube.com/feed/subscriptions", "https://x.com/home", "https://www.instagram.com/", "https://noticias.com/articulo",
    "https://www.youtube.com/results?search_query=x", "https://www.facebook.com/watch/", "https://www.youtube.com/playlist?list=PL1"];
  for (const u of urls) assert.equal(PARECE_VIDEO.test(u), esEnlaceDeVideo(u), u);
});

test("recortar: tiempos escritos a mano", () => {
  assert.deepEqual(["80", "1:20", "01:02:03", "1:20.5", "0:05", " 2:00 "].map(parsearTiempo), [80, 80, 3723, 80.5, 5, 120]);
  for (const malo of ["", "abc", "1:75", "-3", "1::2", "1:2:3:4", null]) assert.equal(parsearTiempo(malo), null, String(malo));
  assert.deepEqual([80, 3723, 5, 0].map(formatearTiempo), ["1:20", "1:02:03", "0:05", "0:00"]);
});

test("recortar: valida los trozos contra la duración del video", () => {
  assert.deepEqual(validarTramos([{ desde: "1:20", hasta: "3:45" }], 600), { tramos: [[80, 225]] });
  assert.deepEqual(validarTramos([{ desde: "9:00", hasta: "12:00" }], 600), { tramos: [[540, 600]] });     // se ajusta al final
  assert.match(validarTramos([{ desde: "3:00", hasta: "1:00" }]).error, /después del inicio/);
  assert.match(validarTramos([{ desde: "11:00", hasta: "12:00" }], 600).error, /después del final del video/);
  assert.match(validarTramos([{ desde: "", hasta: "" }]).error, /al menos un trozo/);
  assert.match(validarTramos([{ desde: "1:00", hasta: "2:00" }, { desde: "x", hasta: "3:00" }]).error, /inicio del trozo 2/);
});

test("recortar: opciones con los trozos y sin extras", () => {
  const [video] = opcionesRecorte({ video: true, portada: true, editable: true }, [[80, 225]], { exacto: true });
  assert.deepEqual(video, { modo: "video", subtitulos: [], portada: false, editable: true, tramos: [[80, 225]], corte_exacto: true });
  const [audio] = opcionesRecorte({ video: true }, [[1, 2]], { audio: true });
  assert.equal(audio.modo, "audio");
  assert.equal(textoTramos([[80, 225], [300, 330]]), "✂ 1:20–3:45 · 5:00–5:30");
});
