"""Fixtures compartidas: un servidor HTTP local con medios generados por FFmpeg.

Así probamos descargas REALES sin depender de internet.
"""
import functools
import subprocess
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

from gestor.config import localizar_ffmpeg

FFMPEG_DIR = localizar_ffmpeg()
necesita_ffmpeg = pytest.mark.skipif(FFMPEG_DIR is None, reason="FFmpeg no está disponible")


class _Silencioso(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ServidorMedios:
    def __init__(self, carpeta: Path):
        self.carpeta = carpeta
        handler = functools.partial(_Silencioso, directory=str(carpeta))
        self._srv = HTTPServer(("127.0.0.1", 0), handler)
        self.base = f"http://127.0.0.1:{self._srv.server_port}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def cerrar(self):
        self._srv.shutdown()


def _ffmpeg(*args: str):
    subprocess.run([str(FFMPEG_DIR / "ffmpeg"), "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="session")
def servidor_medios(tmp_path_factory):
    if FFMPEG_DIR is None:
        pytest.skip("FFmpeg no está disponible")
    d = tmp_path_factory.mktemp("web")
    # video de 2 s con audio, y una imagen
    _ffmpeg("-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=15",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest", "-pix_fmt", "yuv420p", str(d / "clip.mp4"))
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x120", "-frames:v", "1", str(d / "foto.png"))
    (d / "es.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHola\n", encoding="utf-8")
    s = ServidorMedios(d)
    (d / "pagina.html").write_text(
        f'<html><head><title>Mi clip</title>'
        f'<meta property="og:image" content="{s.base}/foto.png"></head><body>'
        f'<video controls><source src="clip.mp4" type="video/mp4">'
        f'<track kind="subtitles" src="es.vtt" srclang="es" label="Espanol" default></video>'
        f'</body></html>', encoding="utf-8")
    yield s
    s.cerrar()
