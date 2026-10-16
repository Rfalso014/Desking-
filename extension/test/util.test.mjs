// Ejecutar: node --test extension/test
import assert from "node:assert/strict";
import test from "node:test";
import { accionesDisponibles, elegirUrlParaMenu, elegirUrlParaVideo, esUrlWeb, formatearTamano, mensajeErrorNativo, nombreSitio } from "../util.js";

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
