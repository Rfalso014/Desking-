"""Pruebas del extractor. Casi todas son offline: usan datos de ejemplo."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from yt_dlp.utils import DownloadError

from gestor.extractor import normalizar_info, obtener_info
from gestor.modelos import CodigoError, ErrorGestor, TipoFormato

# Diccionario parecido al que devuelve yt-dlp (recortado a lo que usamos).
INFO_EJEMPLO = {
    "id": "abc123",
    "title": "Video de prueba",
    "extractor_key": "Ejemplo",
    "webpage_url": "https://example.com/v/abc123",
    "duration": 61.5,
    "thumbnail": "https://example.com/t.jpg",
    "uploader": "Canal X",
    "formats": [
        {"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a",
         "height": 360, "filesize": 1000},
        {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none",
         "height": 1080, "filesize_approx": 5000, "format_note": "1080p"},
        {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"},
        {"format_id": "drm1", "ext": "mp4", "vcodec": "avc1", "acodec": "none",
         "has_drm": True},
    ],
    "subtitles": {"es": [{}]},
    "automatic_captions": {"es": [{}], "en": [{}]},
}


def test_normalizar_campos_basicos():
    r = normalizar_info(INFO_EJEMPLO, "https://example.com/v/abc123")
    assert (r.titulo, r.sitio, r.id_contenido) == ("Video de prueba", "Ejemplo", "abc123")
    assert r.duracion_seg == 61.5 and not r.es_lista and not r.es_en_vivo


def test_tipos_de_formato():
    f = {x.id: x for x in normalizar_info(INFO_EJEMPLO, "u").formatos}
    assert f["18"].tipo == TipoFormato.VIDEO_Y_AUDIO
    assert f["137"].tipo == TipoFormato.SOLO_VIDEO
    assert f["140"].tipo == TipoFormato.SOLO_AUDIO
    assert f["140"].codec_video is None


def test_tamano_exacto_vs_estimado():
    f = {x.id: x for x in normalizar_info(INFO_EJEMPLO, "u").formatos}
    assert (f["18"].tamano_bytes, f["18"].tamano_es_estimado) == (1000, False)
    assert (f["137"].tamano_bytes, f["137"].tamano_es_estimado) == (5000, True)
    assert f["140"].tamano_bytes is None  # sin dato: no inventamos


def test_indicio_de_drm_se_conserva():
    f = {x.id: x for x in normalizar_info(INFO_EJEMPLO, "u").formatos}
    assert f["drm1"].tiene_drm and not f["18"].tiene_drm


def test_subtitulos_manual_gana_sobre_automatico():
    subs = normalizar_info(INFO_EJEMPLO, "u").subtitulos
    assert subs == {"es": False, "en": True}


def test_info_minima_no_rompe():
    r = normalizar_info({}, "https://example.com/x")
    assert r.titulo == "Sin título" and r.formatos == () and r.url == "https://example.com/x"


def test_lista_se_detecta():
    assert normalizar_info({"_type": "playlist"}, "u").es_lista


def test_obtener_info_con_extractor_falso():
    r = obtener_info("https://example.com/v/abc123", extraer=lambda u: INFO_EJEMPLO)
    assert r.titulo == "Video de prueba"


def test_obtener_info_valida_la_url_antes_de_extraer():
    def no_debe_llamarse(url):
        raise AssertionError("no debió llegar a la red")

    with pytest.raises(ErrorGestor) as e:
        obtener_info("http://127.0.0.1/", extraer=no_debe_llamarse)
    assert e.value.codigo == CodigoError.URL_INVALIDA


@pytest.mark.parametrize("mensaje, codigo", [
    ("ERROR: Unsupported URL: https://example.com/", CodigoError.SITIO_NO_COMPATIBLE),
    ("ERROR: Private video. Sign in if you've been granted access", CodigoError.CONTENIDO_NO_DISPONIBLE),
    ("ERROR: Sign in to confirm you're not a bot", CodigoError.AUTENTICACION),
    ("ERROR: <urlopen error [Errno 11001] getaddrinfo failed>", CodigoError.CONEXION),
    ("ERROR: algo rarísimo que nadie conoce", CodigoError.DESCONOCIDO),
])
def test_errores_de_ytdlp_se_traducen(mensaje, codigo):
    def falla(url):
        raise DownloadError(mensaje)

    with pytest.raises(ErrorGestor) as e:
        obtener_info("https://example.com/v", extraer=falla)
    assert e.value.codigo == codigo
    assert e.value.detalle_tecnico == mensaje      # el texto original se conserva
    if codigo == CodigoError.DESCONOCIDO:
        assert e.value.causa is None               # no se inventa una causa


# --- Prueba "real" contra un servidor local (sin internet) ------------------
class _Manejador(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", "10")
        self.end_headers()
        self.wfile.write(b"0123456789")

    do_HEAD = do_GET

    def log_message(self, *args):  # silencia el log del servidor en la consola
        pass


@pytest.fixture
def servidor_local():
    srv = HTTPServer(("127.0.0.1", 0), _Manejador)  # puerto 0 = el sistema elige uno libre
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_port}/clip.mp4"
    srv.shutdown()


def test_yt_dlp_real_contra_servidor_local(servidor_local):
    r = obtener_info(servidor_local, permitir_interno=True)
    assert r.formatos, "yt-dlp debería ver al menos un formato del enlace directo"
    assert r.formatos[0].extension == "mp4"


def test_lista_trae_sus_videos():
    info = {"_type": "playlist", "title": "Mi lista", "entries": [
        {"url": "https://www.youtube.com/watch?v=a", "title": "Uno"},
        {"webpage_url": "https://www.youtube.com/watch?v=b"},
        {"url": "javascript:alert(1)", "title": "malo"}, None]}
    r = normalizar_info(info, "u")
    assert r.es_lista and r.entradas == (("https://www.youtube.com/watch?v=a", "Uno"),
                                         ("https://www.youtube.com/watch?v=b", "Sin título"))


def test_tamanos_por_calidad_muestra_cuanto_pesa_cada_opcion():
    from gestor.extractor import tamanos_por_calidad, texto_tamanos
    from gestor.modelos import FormatoInfo, InfoContenido, TipoFormato
    MB = 1048576
    f = lambda i, t, h, mb: FormatoInfo(id=i, extension="mp4", tipo=t, altura=h, tamano_bytes=mb * MB)  # noqa: E731
    info = InfoContenido(url="https://a.test/v", titulo="v", sitio="x", formatos=(
        f("a", TipoFormato.SOLO_AUDIO, None, 10), f("v4k", TipoFormato.SOLO_VIDEO, 2160, 669), f("v1080", TipoFormato.SOLO_VIDEO, 1080, 108),
        f("v1080b", TipoFormato.SOLO_VIDEO, 1080, 90), f("v720", TipoFormato.SOLO_VIDEO, 720, 52), f("c360", TipoFormato.VIDEO_Y_AUDIO, 360, 20)))
    assert tamanos_por_calidad(info) == [(2160, 679 * MB), (1080, 118 * MB), (720, 62 * MB)]
    assert texto_tamanos(info) == "Tamaño aproximado: 2160p ≈ 679 MB · 1080p ≈ 118 MB · 720p ≈ 62 MB"
    assert texto_tamanos(InfoContenido(url="https://a.test/v", titulo="v", sitio="x")) is None
