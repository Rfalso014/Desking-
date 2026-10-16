import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from gestor.descargador import (OpcionesDescarga, RolArchivo, construir_opciones_ytdlp,
                                construir_selector, descargar, limpiar_carpeta_trabajo)
from gestor.modelos import CodigoError, ErrorGestor
from tests.conftest import FFMPEG_DIR, necesita_ffmpeg

OP = OpcionesDescarga(ffmpeg_dir=FFMPEG_DIR, portada=False)


# --- puras ------------------------------------------------------------------
@pytest.mark.parametrize("opc, esperado", [
    (OpcionesDescarga(), "bv*+ba/b"),
    (OpcionesDescarga(altura_max=720), "bv*[height<=?720]+ba/b[height<=?720]"),
    (OpcionesDescarga(modo="audio", formato_audio="mp3"), "ba/b"),
    (OpcionesDescarga(modo="audio", formato_audio="m4a"), "ba[ext=m4a]/ba/b"),
])
def test_selector(opc, esperado):
    assert construir_selector(opc) == esperado


def test_audio_original_no_convierte_pero_mp3_si():
    h = lambda d: None  # noqa: E731
    orig = construir_opciones_ytdlp(OpcionesDescarga(modo="audio", formato_audio="original", portada=False), Path("x"), h)
    assert orig["postprocessors"] == []
    mp3 = construir_opciones_ytdlp(OpcionesDescarga(modo="audio", formato_audio="mp3"), Path("x"), h)
    assert mp3["postprocessors"][0]["preferredcodec"] == "mp3"
    ogg = construir_opciones_ytdlp(OpcionesDescarga(modo="audio", formato_audio="ogg"), Path("x"), h)
    assert ogg["postprocessors"][0]["preferredcodec"] == "vorbis"


@pytest.mark.parametrize("cambio", [
    dict(modo="otro"), dict(contenedor_video="avi"), dict(formato_audio="exe"),
    dict(altura_max=5), dict(altura_max=99999), dict(subtitulos=("es; rm -rf",)),
    dict(plantilla_nombre="../fuera/%(title)s"), dict(plantilla_nombre="a\\b"),
    dict(plantilla_nombre=""),
])
def test_opciones_invalidas_se_rechazan(cambio):
    with pytest.raises(ErrorGestor) as e:
        replace(OpcionesDescarga(), **cambio).validar()
    assert e.value.codigo == CodigoError.CONFIGURACION


def test_sin_ffmpeg_da_error_claro(tmp_path):
    with pytest.raises(ErrorGestor) as e:
        descargar("https://example.com/v", OpcionesDescarga(ffmpeg_dir=None), tmp_path)
    assert e.value.codigo == CodigoError.FFMPEG_AUSENTE


def test_poco_espacio_se_detecta_antes_de_descargar(tmp_path):
    with pytest.raises(ErrorGestor) as e:
        descargar("https://example.com/v", OP, tmp_path, tamano_estimado=10**18)
    assert e.value.codigo == CodigoError.ESPACIO_INSUFICIENTE


def test_limpieza_solo_dentro_de_la_raiz(tmp_path):
    raiz = tmp_path / "tmp"
    (raiz / "t1").mkdir(parents=True)
    limpiar_carpeta_trabajo(raiz / "t1", raiz)
    assert not (raiz / "t1").exists()
    with pytest.raises(ErrorGestor):
        limpiar_carpeta_trabajo(tmp_path, raiz)      # fuera de la raÃ­z
    with pytest.raises(ErrorGestor):
        limpiar_carpeta_trabajo(raiz, raiz)          # la propia raÃ­z tampoco


# --- reales (servidor local + FFmpeg) --------------------------------------
def _duracion(ruta: Path) -> float:
    r = subprocess.run([str(FFMPEG_DIR / "ffprobe"), "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(ruta)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


@necesita_ffmpeg
def test_descarga_video(servidor_medios, tmp_path):
    eventos = []
    r = descargar(f"{servidor_medios.base}/clip.mp4", OP, tmp_path / "t", progreso=eventos.append,
                  permitir_interno=True)
    video = [a for a in r.archivos if a.rol == RolArchivo.VIDEO]
    assert len(video) == 1 and video[0].ruta.suffix == ".mp4"
    assert 1.5 < _duracion(video[0].ruta) < 2.5
    assert eventos and eventos[-1].estado == "completado"


@necesita_ffmpeg
def test_descarga_audio_convertido_a_mp3(servidor_medios, tmp_path):
    o = replace(OP, modo="audio", formato_audio="mp3")
    r = descargar(f"{servidor_medios.base}/clip.mp4", o, tmp_path / "t", permitir_interno=True)
    audio = [a for a in r.archivos if a.rol == RolArchivo.AUDIO]
    assert len(audio) == 1 and audio[0].ruta.suffix == ".mp3"


@necesita_ffmpeg
def test_audio_original_sin_conversion(servidor_medios, tmp_path):
    o = OpcionesDescarga(modo="audio", formato_audio="original", portada=False, ffmpeg_dir=None)
    r = descargar(f"{servidor_medios.base}/clip.mp4", o, tmp_path / "t", permitir_interno=True)
    assert r.archivos[0].ruta.suffix == ".mp4"      # la pista tal cual, sin recodificar


@necesita_ffmpeg
def test_subtitulos_y_portada(servidor_medios, tmp_path):
    o = replace(OP, subtitulos=("es",), portada=True)
    r = descargar(f"{servidor_medios.base}/pagina.html", o, tmp_path / "t", permitir_interno=True)
    roles = {a.rol for a in r.archivos}
    assert RolArchivo.VIDEO in roles
    assert RolArchivo.SUBTITULO in roles, [a.ruta.name for a in r.archivos]
    assert RolArchivo.PORTADA in roles, [a.ruta.name for a in r.archivos]
    sub = next(a for a in r.archivos if a.rol == RolArchivo.SUBTITULO)
    assert ".es." in sub.ruta.name                  # el idioma queda en el nombre


@necesita_ffmpeg
def test_cancelacion(servidor_medios, tmp_path):
    ev = threading.Event()
    ev.set()                                        # ya cancelada antes de empezar
    with pytest.raises(ErrorGestor) as e:
        descargar(f"{servidor_medios.base}/clip.mp4", OP, tmp_path / "t", cancelar=ev, permitir_interno=True)
    assert e.value.codigo == CodigoError.CANCELADO
