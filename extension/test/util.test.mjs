// Ejecutar: node --test extension/test
import assert from "node:assert/strict";
import test from "node:test";
import {
  accionesDisponibles, elegirUrlParaMenu, elegirUrlParaVideo, esUrlWeb, filtrarTareas, formatearCodigo, formatearDuracion, formatearEta,
  formatearTamano, formatearVelocidad, mensajeErrorNativo, miniaturaSegura, nombreNavegador, nombreSitio, resumenCola,
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
  const pagina = "https://youtube.com/";
  assert.equal(elegirUrlParaVideo({ enlace: "https://youtube.com/watch?v=1", fuente: null, pagina }), "https://youtube.com/watch?v=1");
  assert.equal(elegirUrlParaVideo({ enlace: null, fuente: "https://cdn.a.com/v.mp4", pagina }), "https://cdn.a.com/v.mp4");
  assert.equal(elegirUrlParaVideo({ enlace: null, fuente: null, pagina }), pagina);
  assert.equal(elegirUrlParaVideo({ enlace: "javascript:x", fuente: "blob:https://a.com/1", pagina: "about:blank" }), null);
  assert.equal(elegirUrlParaVideo(null), null);
});

test("errores nativos se traducen", () => {
  assert.match(mensajeErrorNativo("Specified native messaging host not found.").mensaje, /No está instalado/);
  assert.match(mensajeErrorNativo("Access to the specified native messaging host is forbidden.").mensaje, /no permite/);
  const otro = mensajeErrorNativo("algo raro");
  assert.equal(otro.detalle, "algo raro");
  assert.ok(otro.solucion);
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
