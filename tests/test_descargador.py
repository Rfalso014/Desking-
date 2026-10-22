import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from gestor.descargador import (OpcionesDescarga, RolArchivo, codecs_de, construir_opciones_ytdlp,
                                construir_selector, descargar, limpiar_carpeta_trabajo, preparar_para_edicion)
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


def test_modo_edicion_prefiere_h264_aac_en_mp4():
    h = lambda d: None  # noqa: E731
    p = construir_opciones_ytdlp(OpcionesDescarga(editable=True, contenedor_video="mkv"), Path("x"), h)
    assert p["format_sort"] == ["res", "vcodec:h264", "acodec:aac"] and p["merge_output_format"] == "mp4"
    normal = construir_opciones_ytdlp(OpcionesDescarga(), Path("x"), h)
    assert "format_sort" not in normal


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


def test_sesion_del_navegador_llega_a_yt_dlp(tmp_path):
    from gestor.config import Preferencias, opciones_sesion
    assert opciones_sesion(Preferencias()) == {}
    assert opciones_sesion(Preferencias(sesion_navegador="firefox")) == {"cookiesfrombrowser": ("firefox",)}
    assert opciones_sesion(Preferencias(sesion_navegador="notepad")) == {}
    ck = tmp_path / "c.txt"; ck.write_text("# Netscape")
    assert opciones_sesion(Preferencias(sesion_navegador="firefox", archivo_cookies=str(ck))) == {"cookiefile": str(ck)}
    o = OpcionesDescarga(sesion={"cookiesfrombrowser": ("firefox",)})
    assert construir_opciones_ytdlp(o, Path("x"), lambda d: None)["cookiesfrombrowser"] == ("firefox",)
    with pytest.raises(ErrorGestor):
        OpcionesDescarga(sesion={"exec": "calc"}).validar()


def _clip(ruta: Path, *args: str) -> Path:
    subprocess.run([str(FFMPEG_DIR / "ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=15",
                    "-f", "lavfi", "-i", "sine=duration=1", "-shortest", *args, str(ruta)], check=True)
    return ruta


@necesita_ffmpeg
def test_preparar_para_edicion_convierte_a_h264_aac(tmp_path):
    origen = _clip(tmp_path / "raro.mkv", "-c:v", "mpeg4", "-c:a", "mp2")
    final = preparar_para_edicion(origen, FFMPEG_DIR)
    assert final == tmp_path / "raro.mp4" and not origen.exists()
    assert codecs_de(final, FFMPEG_DIR) == ("h264", "aac")
    assert [f.name for f in tmp_path.iterdir()] == ["raro.mp4"]      # sin temporales


@necesita_ffmpeg
def test_preparar_para_edicion_no_toca_lo_que_ya_sirve(tmp_path):
    bueno = _clip(tmp_path / "ok.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac")
    antes = bueno.stat().st_mtime_ns
    assert preparar_para_edicion(bueno, FFMPEG_DIR) == bueno and bueno.stat().st_mtime_ns == antes


@necesita_ffmpeg
def test_preparar_para_edicion_se_puede_cancelar(tmp_path):
    origen = _clip(tmp_path / "raro.mkv", "-c:v", "mpeg4", "-c:a", "mp2")
    ev = threading.Event(); ev.set()
    with pytest.raises(ErrorGestor) as e:
        preparar_para_edicion(origen, FFMPEG_DIR, ev)
    assert e.value.codigo == CodigoError.CANCELADO and not (tmp_path / "raro.edicion.mp4").exists()


@necesita_ffmpeg
def test_descarga_para_edicion(servidor_medios, tmp_path):
    r = descargar(f"{servidor_medios.base}/clip.mp4", replace(OP, editable=True), tmp_path / "t", permitir_interno=True)
    video = [a for a in r.archivos if a.rol == RolArchivo.VIDEO]
    assert len(video) == 1 and video[0].ruta.suffix == ".mp4"
    assert codecs_de(video[0].ruta, FFMPEG_DIR) == ("h264", "aac")


@necesita_ffmpeg
def test_conversion_para_edicion_informa_el_progreso(tmp_path):
    origen = _clip(tmp_path / "raro.mkv", "-c:v", "mpeg4", "-c:a", "mp2")
    vistos = []
    preparar_para_edicion(origen, FFMPEG_DIR, progreso=vistos.append)
    assert vistos and all(0 <= x <= 99 for x in vistos)


def test_si_la_tarjeta_grafica_falla_se_usa_el_procesador(tmp_path, monkeypatch):
    import gestor.descargador as d
    llamadas = []

    def falso(args, duracion, cancelar, progreso):
        llamadas.append(args[args.index("-c:v") + 1])
        if args[args.index("-c:v") + 1] != "libx264":
            return 1, "fallo de la tarjeta"
        Path(args[-1]).write_bytes(b"ok")
        return 0, ""
    monkeypatch.setattr(d, "codecs_de", lambda r, f: ("vp9", "opus"))
    monkeypatch.setattr(d, "codificador_h264", lambda f: ("h264_qsv", ["-c:v", "h264_qsv"]))
    monkeypatch.setattr(d, "_ejecutar_ffmpeg", falso)
    origen = tmp_path / "v.webm"; origen.write_bytes(b"x")
    assert d.preparar_para_edicion(origen, None) == tmp_path / "v.mp4"
    assert llamadas == ["h264_qsv", "h264_qsv", "libx264"]        # gráfica decodificando, gráfica sola, procesador


def test_intentos_de_conversion_decodifican_con_la_grafica_cuando_pueden(monkeypatch):
    import gestor.descargador as d
    monkeypatch.setattr(d, "codificador_h264", lambda f: ("h264_qsv", ["-c:v", "h264_qsv", "-pix_fmt", "nv12"]))
    vp9 = d.intentos_conversion(None, "vp9")
    assert vp9[0] == (["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"], ["-c:v", "h264_qsv"]) and len(vp9) == 3
    av1 = d.intentos_conversion(None, "av1")                       # AV1: la HD 630 no lo decodifica
    assert [e for e, _ in av1] == [[], []]


# --- descargar solo unos minutos ----------------------------------------------------------------
def test_estrategia_de_trozos_elige_lo_mas_rapido():
    from gestor.descargador import estrategia_tramos
    assert estrategia_tramos(OpcionesDescarga()) is None
    assert estrategia_tramos(OpcionesDescarga(tramos=((60, 120),), duracion_video=7200)) == "rangos"      # 1 min de 2 h
    assert estrategia_tramos(OpcionesDescarga(tramos=((60, 240),), duracion_video=600)) == "completo"     # 3 min de 10 min
    assert estrategia_tramos(OpcionesDescarga(tramos=((60, 240),))) == "rangos"                            # sin duración


def test_trozos_por_rangos_llegan_a_yt_dlp():
    h = lambda d: None  # noqa: E731
    p = construir_opciones_ytdlp(OpcionesDescarga(tramos=((80, 95),), corte_exacto=True, duracion_video=7200), Path("x"), h)
    assert callable(p["download_ranges"]) and "section_start" in p["outtmpl"]
    assert "force_keyframes_at_cuts" not in p                         # yt-dlp convertiría con x264 «medium» (lo más lento)
    assert "-c:v" in p["external_downloader_args"]["ffmpeg_o"] and p["format_sort"][1] == "vcodec:h264"
    assert "download_ranges" not in construir_opciones_ytdlp(OpcionesDescarga(tramos=((1, 300),), duracion_video=600), Path("x"), h)


@pytest.mark.parametrize("tramos", [((5, 3),), ((-1, 3),), ((0, 99999),), tuple((i, i + 1) for i in range(11))])
def test_trozos_invalidos_se_rechazan(tramos):
    with pytest.raises(ErrorGestor):
        OpcionesDescarga(tramos=tramos).validar()
    with pytest.raises(ErrorGestor):
        OpcionesDescarga(modo="portada", tramos=((1, 2),)).validar()


@necesita_ffmpeg
@pytest.mark.parametrize("exacto", [False, True])
def test_cortar_tramos_en_el_equipo(tmp_path, exacto):
    from gestor.descargador import cortar_tramos
    origen = subprocess.run([str(FFMPEG_DIR / "ffmpeg"), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=15",
                             "-f", "lavfi", "-i", "sine=duration=6", "-shortest", "-g", "15", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")], check=True)
    trozos = cortar_tramos(tmp_path / "v.mp4", ((1.0, 2.5), (4.0, 5.0)), exacto, FFMPEG_DIR)
    assert [t.name for t in trozos] == ["v (00-00-01 a 00-00-02).mp4", "v (00-00-04 a 00-00-05).mp4"]
    assert not (tmp_path / "v.mp4").exists()
    assert abs(_duracion(trozos[0]) - 1.5) < (0.15 if exacto else 1.1)


@necesita_ffmpeg
def test_descarga_de_un_trozo(servidor_medios, tmp_path):
    o = replace(OP, tramos=((0.5, 1.5),), corte_exacto=True, duracion_video=2.0)     # trozo largo: baja todo y corta aquí
    r = descargar(f"{servidor_medios.base}/clip.mp4", o, tmp_path / "t", permitir_interno=True)
    video = [a for a in r.archivos if a.rol == RolArchivo.VIDEO]
    assert len(video) == 1 and "(00-00-00 a 00-00-01)" in video[0].ruta.name
    assert abs(_duracion(video[0].ruta) - 1.0) < 0.15


@necesita_ffmpeg
def test_ffmpeg_para_trozos_aunque_yt_dlp_ya_lo_hubiera_buscado(monkeypatch):
    # El fallo real: una descarga normal hacía que yt-dlp recordara «FFmpeg no está» y luego los trozos fallaban.
    from yt_dlp.downloader.external import FFmpegFD
    from gestor.descargador import asegurar_ffmpeg_en_path
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    FFmpegFD.available()                       # yt-dlp lo busca sin éxito y lo recuerda
    asegurar_ffmpeg_en_path(FFMPEG_DIR)
    assert FFmpegFD.available() is True
