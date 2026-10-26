"""Descarga video, audio, subtítulos y portada con yt-dlp.

Idea clave: cada tarea descarga en SU PROPIA carpeta de trabajo (temporal).
Cuando termina bien, el organizador (organizador.py) mueve los archivos a su
destino final. Así nunca quedan archivos a medias en las carpetas del usuario
y una tarea cancelada se limpia borrando solo su carpeta.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import DownloadCancelled, download_range_func

from .catalogo import CONTENEDORES_VIDEO, FORMATOS_AUDIO, MAX_TRAMOS, MODOS, _IDIOMA, _ok_tramos
from .errores import traducir_excepcion
from .extractor import normalizar_info
from .modelos import CodigoError, ErrorGestor, InfoContenido
from .validacion import validar_url

# --- Listas blancas: lo que NO está aquí se rechaza (seguridad) --------------
# Nombre que usa yt-dlp para cada códec de salida.
_CODEC_YTDLP = {"mp3": "mp3", "m4a": "m4a", "flac": "flac", "ogg": "vorbis", "opus": "opus", "wav": "wav"}
_SIN_CALIDAD = {"flac", "wav"}  # formatos sin pérdida: no llevan bitrate
_EXT_SUBS = {".srt", ".vtt", ".ass", ".lrc"}
_EXT_IMAGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_EXT_TEMPORALES = {".part", ".ytdl", ".temp", ".tmp"}


class DescargaCancelada(DownloadCancelled):
    """Se lanza desde el hook de progreso para detener a yt-dlp limpiamente."""


class RolArchivo(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITULO = "subtitulo"
    PORTADA = "portada"


@dataclass(frozen=True)
class OpcionesDescarga:
    modo: str = "video"   # "video" | "audio" | "subtitulos" (solo subtítulos) | "portada" (solo portada)
    altura_max: int | None = None             # None = mejor calidad
    contenedor_video: str = "mp4"
    formato_audio: str = "mp3"
    subtitulos: tuple[str, ...] = ()          # idiomas, p. ej. ("es", "en")
    subtitulos_automaticos: bool = True       # usar automáticos si no hay manuales
    portada: bool = True
    editable: bool = False                    # video listo para editar: MP4 con H.264 + AAC
    tramos: tuple[tuple[float, float], ...] = ()   # solo estos trozos (inicio, fin) en segundos; vacío = todo
    corte_exacto: bool = False                # cortar en el segundo exacto (convierte) o en el fotograma clave (rápido)
    duracion_video: float | None = None       # la pone la cola tras analizar: decide cómo bajar los trozos
    plantilla_nombre: str = "%(title).120B [%(id)s]"
    ffmpeg_dir: Path | None = None
    fragmentos: int = 8                       # fragmentos que se bajan a la vez
    trozo_http: int = 10 * 1024 * 1024        # 0 = sin trozos
    deno: Path | None = None                  # runtime JS para YouTube
    sesion: dict = field(default_factory=dict)   # cookies del navegador / cookies.txt (ver config.opciones_sesion)
    referer: str | None = None                # pagina donde estaba el video (lo exigen muchos servidores de video)
    imitar_navegador: bool = False            # presentarse como Chrome (sitios con proteccion anti-bots, Cloudflare)

    def validar(self) -> None:
        def malo(msg: str) -> ErrorGestor:
            return ErrorGestor(CodigoError.CONFIGURACION, msg,
                               solucion="Revisa las opciones de descarga.")
        if self.modo not in MODOS:
            raise malo(f"Modo no válido: {self.modo!r}.")
        if self.modo == "subtitulos" and not self.subtitulos:
            raise malo("Para descargar solo subtítulos hay que elegir al menos un idioma.")
        if self.contenedor_video not in CONTENEDORES_VIDEO:
            raise malo(f"Contenedor de video no válido: {self.contenedor_video!r}.")
        if self.formato_audio not in FORMATOS_AUDIO:
            raise malo(f"Formato de audio no válido: {self.formato_audio!r}.")
        if set(self.sesion) - {"cookiesfrombrowser", "cookiefile"}:
            raise malo("Opciones de sesión no válidas.")
        if not (isinstance(self.fragmentos, int) and 1 <= self.fragmentos <= 32):
            raise malo("Los fragmentos simultáneos deben estar entre 1 y 32.")
        if self.referer is not None and not (isinstance(self.referer, str) and self.referer.startswith(("http://", "https://"))
                                             and len(self.referer) <= 2048 and not any(c in self.referer for c in "\r\n")):
            raise malo("La página de origen no es válida.")
        if not (isinstance(self.trozo_http, int) and 0 <= self.trozo_http <= 100 * 1024 * 1024):
            raise malo("El tamaño de trozo no es válido.")
        if self.altura_max is not None and not (isinstance(self.altura_max, int) and 100 <= self.altura_max <= 8640):
            raise malo("La altura máxima debe estar entre 100 y 8640.")
        if not _ok_tramos(self.tramos) or len(self.tramos) > MAX_TRAMOS:
            raise malo("Los trozos no son válidos: cada uno necesita un inicio menor que su fin.")
        if self.tramos and self.modo not in ("video", "audio"):
            raise malo("Los trozos solo sirven para descargar video o audio.")
        if len(self.subtitulos) > 20 or not all(_IDIOMA.match(i) for i in self.subtitulos):
            raise malo("Código de idioma de subtítulos no válido.")
        # La plantilla la interpreta yt-dlp: prohibimos separadores de ruta
        # para que no pueda escribir fuera de la carpeta de trabajo.
        t = self.plantilla_nombre
        if not t or any(c in t for c in "/\\") or ".." in t or ":" in t.replace("%(", "").replace(")s", ""):
            raise malo("La plantilla de nombre no puede contener rutas.")


@dataclass(frozen=True)
class Progreso:
    estado: str                    # "descargando" | "procesando" | "completado"
    porcentaje: float | None = None
    velocidad_bps: float | None = None
    eta_seg: float | None = None
    descargado: int | None = None
    total: int | None = None
    archivo: str | None = None


@dataclass(frozen=True)
class ArchivoDescargado:
    ruta: Path
    rol: RolArchivo


@dataclass(frozen=True)
class ResultadoDescarga:
    archivos: tuple[ArchivoDescargado, ...]
    info: InfoContenido


def construir_selector(o: OpcionesDescarga) -> str:
    """Texto de selección de formato de yt-dlp (función pura, fácil de probar).

    Sintaxis: 'A+B' une A (video) y B (audio); 'X/Y' = si X no existe, usa Y.
    bv* = mejor video, ba = mejor audio, b = mejor archivo combinado.
    """
    if o.modo == "audio":
        # Si el destino es m4a, preferimos una pista m4a ya existente (sin recodificar).
        return "ba[ext=m4a]/ba/b" if o.formato_audio == "m4a" else "ba/b"
    h = f"[height<=?{o.altura_max}]" if o.altura_max else ""
    return f"bv*{h}+ba/b{h}"


# Bajar un trozo con FFmpeg sigue siendo mas lento por segundo de video que bajar el archivo entero (FFmpeg lee de forma
# secuencial). Desde que se piden partes de 10 MB (`-request_size`, ver ARGS_FFMPEG_ENTRADA) un trozo de 30 s de YouTube
# baja en ~6 s en vez de ~25 s (medido 2026-10-26), asi que solo conviene bajarlo todo y cortar aqui si los trozos
# ocupan mas de una quinta parte del video.
FACTOR_TROZOS = 5

# YouTube frena las peticiones HTTP largas (una sola conexion que pide el archivo entero). FFmpeg 8+ puede pedir el
# archivo por partes, como hace el navegador, y asi no se le aplica el freno.
ARGS_FFMPEG_ENTRADA = ["-request_size", str(10 * 1024 * 1024), "-multiple_requests", "1",
                       "-reconnect", "1", "-reconnect_on_network_error", "1", "-reconnect_delay_max", "10"]


def estrategia_tramos(o: OpcionesDescarga) -> str | None:
    """None (sin trozos) | "rangos" (yt-dlp baja solo los trozos) | "completo" (se baja todo y se corta en el equipo)."""
    if not o.tramos:
        return None
    total = sum(b - a for a, b in o.tramos)
    return "completo" if o.duracion_video and total * FACTOR_TROZOS > o.duracion_video else "rangos"


def _hms(seg: float) -> str:
    s = int(seg)
    return f"{s // 3600:02d}-{s % 3600 // 60:02d}-{s % 60:02d}"


MAX_RUTA = 240       # Windows no admite rutas de más de 260 caracteres (margen para archivos temporales de FFmpeg)


def _plantilla_corta(plantilla: str, carpeta: Path, extra: int) -> str:
    """Acorta el título de la plantilla si la carpeta es profunda, para que la ruta completa no pase de MAX_RUTA.

    `extra` = caracteres que se añaden al nombre (p. ej. « (00-01-30 a 00-02-00)» de un trozo). Se mide la ruta
    expandida: una carpeta escrita en forma corta (C:\\Users\\ADMINI~1) se alarga al usarla.
    """
    sobra = MAX_RUTA - len(str(carpeta.resolve())) - 1 - len(" [xxxxxxxxxxx].f000-0.webm.part") - extra
    maximo = max(20, min(120, sobra))
    return plantilla.replace("%(title).120B", f"%(title).{maximo}B")


def construir_opciones_ytdlp(o: OpcionesDescarga, carpeta: Path, hook_progreso: Callable[[dict], None],
                             codificador_rangos: list[str] | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {
        "format": construir_selector(o),
        "paths": {"home": str(carpeta)},
        "outtmpl": o.plantilla_nombre + ".%(ext)s",
        "quiet": True, "no_warnings": True, "noprogress": True,
        "noplaylist": True,
        "windowsfilenames": True,       # quita caracteres prohibidos en Windows
        "overwrites": True,             # la carpeta de trabajo es nuestra y está vacía
        "continuedl": True,             # permite reanudar si se reintenta
        "retries": 3, "fragment_retries": 3, "socket_timeout": 20,
        "concurrent_fragment_downloads": o.fragmentos,   # velocidad: varios fragmentos a la vez
        "buffersize": 1024 * 256,
        "progress_hooks": [hook_progreso],
        "postprocessor_hooks": [hook_progreso],
        "postprocessors": [],
    }
    if o.ffmpeg_dir:
        p["ffmpeg_location"] = str(o.ffmpeg_dir)
    if o.trozo_http:
        p["http_chunk_size"] = o.trozo_http
    if o.deno:
        p["js_runtimes"] = {"deno": {"path": str(o.deno)}}
    p.update(o.sesion)
    p.update(opciones_red(o.referer, o.imitar_navegador))
    pp: list[dict[str, Any]] = p["postprocessors"]

    if o.modo in ("subtitulos", "portada"):
        p["skip_download"] = True      # no se baja el video: solo los extras
    elif o.modo == "video" and (o.editable or (o.tramos and o.corte_exacto)):
        # Va a haber que convertir: primero la resolución y, a igual resolución, H.264 > VP9 > AV1 (lo que la gráfica
        # decodifica; AV1 4K va casi al doble de lento en un equipo sin decodificador AV1) y audio AAC.
        p["format_sort"] = ["res", "vcodec:h264", "acodec:aac"]
        p["merge_output_format"] = "mp4"
    elif o.modo == "video":
        if o.contenedor_video != "mejor":
            p["merge_output_format"] = o.contenedor_video  # solo une pistas (sin recodificar)
    elif o.formato_audio != "original":
        q: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": _CODEC_YTDLP[o.formato_audio]}
        if o.formato_audio not in _SIN_CALIDAD:
            q["preferredquality"] = "192"
        pp.append(q)

    if estrategia_tramos(o) == "rangos":
        p["download_ranges"] = download_range_func(None, [tuple(t) for t in o.tramos])
        p["external_downloader_args"] = {"ffmpeg_i": list(ARGS_FFMPEG_ENTRADA)}
        if o.corte_exacto and o.modo == "video":
            codificador_rangos = codificador_rangos or codificador_h264(o.ffmpeg_dir)[1]
            # yt-dlp, con «force_keyframes_at_cuts», convierte con x264 «medium» (lo más lento). En su lugar se le pasa
            # a FFmpeg el codificador rápido de este equipo: al convertir, FFmpeg ya corta en el segundo exacto.
            p["external_downloader_args"]["ffmpeg_o"] = [*codificador_rangos, "-c:a", "aac", "-b:a", "192k"]
        p["outtmpl"] = _plantilla_corta(o.plantilla_nombre, carpeta, 30) + " (%(section_start>%H-%M-%S)s a %(section_end>%H-%M-%S)s).%(ext)s"
    else:
        p["outtmpl"] = _plantilla_corta(o.plantilla_nombre, carpeta, 0) + ".%(ext)s"

    if o.subtitulos:
        p.update(writesubtitles=True, writeautomaticsub=o.subtitulos_automaticos,
                 subtitleslangs=list(o.subtitulos), subtitlesformat="srt/best")
        pp.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
    if o.portada or o.modo == "portada":
        p["writethumbnail"] = True
        pp.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
    return p


def opciones_red(referer: str | None = None, imitar_navegador: bool = False) -> dict[str, Any]:
    """Opciones de yt-dlp para sitios exigentes: la pagina de origen (Referer) y presentarse como Chrome.

    Muchos servidores de video responden 403 si la peticion no dice desde que pagina se mira el video, y los sitios
    con proteccion anti-bots (Cloudflare) rechazan a quien no parece un navegador real. Imitar al navegador necesita
    `curl_cffi`; si no esta instalado no se pide (yt-dlp fallaria al arrancar).
    """
    p: dict[str, Any] = {}
    if referer:
        p["http_headers"] = {"Referer": referer}
    if imitar_navegador and puede_imitar_navegador():
        p["impersonate"] = ImpersonateTarget()
        p["extractor_args"] = {"generic": {"impersonate": [""]}}
    return p


_imitar: list[bool] = []


def puede_imitar_navegador() -> bool:
    if not _imitar:
        try:
            import curl_cffi  # noqa: F401
            _imitar.append(True)
        except ImportError:
            _imitar.append(False)
    return _imitar[0]


def _necesita_ffmpeg(o: OpcionesDescarga) -> bool:
    if o.modo in ("subtitulos", "portada"):
        return True      # la conversión de subtítulos/portada usa FFmpeg
    solo_pista_original = o.modo == "audio" and o.formato_audio == "original" and not o.subtitulos and not o.portada
    return not solo_pista_original


def _ejecutable(ffmpeg_dir: Path | None, nombre: str) -> str:
    for c in ((ffmpeg_dir / f"{nombre}.exe", ffmpeg_dir / nombre) if ffmpeg_dir else ()):
        if c.exists():
            return str(c)
    return shutil.which(nombre) or nombre


_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # que no parpadee una consola en Windows


def codecs_de(ruta: Path, ffmpeg_dir: Path | None) -> tuple[str | None, str | None]:
    """(códec de video, códec de audio) del archivo según ffprobe; None si esa pista no existe."""
    r = subprocess.run([_ejecutable(ffmpeg_dir, "ffprobe"), "-v", "error", "-show_entries", "stream=codec_type,codec_name",
                        "-of", "json", str(ruta)], capture_output=True, text=True, timeout=60, creationflags=_SIN_VENTANA)
    pistas = json.loads(r.stdout or "{}").get("streams", [])
    primero = lambda tipo: next((s.get("codec_name") for s in pistas if s.get("codec_type") == tipo), None)
    return primero("video"), primero("audio")


# Codificadores H.264 por tarjeta gráfica (NVIDIA, Intel Quick Sync, AMD): convierten varias veces más rápido
# que el procesador. Se prueba cuál funciona en este equipo; si ninguno, se usa libx264 (procesador).
_CODIFICADORES_GPU = [
    ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]),
    ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-look_ahead", "0", "-global_quality", "20", "-pix_fmt", "nv12"]),
    ("h264_amf", ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20", "-pix_fmt", "nv12"]),
]
_X264 = ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"])
_codificador_elegido: dict[str, tuple[str, list[str]]] = {}


def codificador_h264(ffmpeg_dir: Path | None) -> tuple[str, list[str]]:
    """(nombre, argumentos) del codificador H.264 más rápido que funciona aquí. Se prueba una sola vez."""
    clave = str(ffmpeg_dir)
    if clave not in _codificador_elegido:
        _codificador_elegido[clave] = _X264
        for nombre, args in _CODIFICADORES_GPU:
            try:
                r = subprocess.run([_ejecutable(ffmpeg_dir, "ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x144:d=0.2",
                                    *args, "-f", "null", "-"], capture_output=True, timeout=30, creationflags=_SIN_VENTANA)
            except (OSError, subprocess.SubprocessError):
                continue
            if r.returncode == 0:
                _codificador_elegido[clave] = (nombre, args)
                break
    return _codificador_elegido[clave]


# Lo que la gráfica Intel/NVIDIA decodifica por hardware (AV1 solo en gráficas recientes: se deja al procesador).
_DECODIFICA_GPU = {"h264", "hevc", "vp9"}
_HWACCEL = {"h264_qsv": ["-hwaccel", "qsv", "-hwaccel_output_format", "qsv"], "h264_nvenc": ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]}


def intentos_conversion(ffmpeg_dir: Path | None, codec_origen: str | None) -> list[tuple[list[str], list[str]]]:
    """[(argumentos de entrada, argumentos de video)] del más rápido al más seguro.

    Medido en un i7-7700 con HD 630, 20 s de VP9 4K: decodificar con la gráfica + Quick Sync 17,7 s; solo Quick Sync
    23 s; x264 31,8 s. Si un intento falla con un video concreto, se prueba el siguiente.
    """
    nombre, args = codificador_h264(ffmpeg_dir)
    salida: list[tuple[list[str], list[str]]] = []
    if nombre in _HWACCEL and codec_origen in _DECODIFICA_GPU:
        sin_pix = [x for i, x in enumerate(args) if x != "-pix_fmt" and (i == 0 or args[i - 1] != "-pix_fmt")]
        salida.append((_HWACCEL[nombre], sin_pix))          # los fotogramas no salen de la gráfica
    salida.append(([], args))
    if nombre != _X264[0]:
        salida.append(([], _X264[1]))
    return salida


def _duracion(ruta: Path, ffmpeg_dir: Path | None) -> float | None:
    try:
        r = subprocess.run([_ejecutable(ffmpeg_dir, "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                           capture_output=True, text=True, timeout=60, creationflags=_SIN_VENTANA)
        return float(r.stdout.strip()) or None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _ejecutar_ffmpeg(args: list[str], duracion: float | None, cancelar: threading.Event | None,
                     progreso: Callable[[float], None] | None) -> tuple[int, str]:
    """Ejecuta FFmpeg informando el % convertido (-progress) y cortándolo si se cancela. Devuelve (código, errores)."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=_SIN_VENTANA)
    errores: list[str] = []
    threading.Thread(target=lambda: errores.extend(proc.stderr), daemon=True).start()   # que no se llene la tubería

    def leer_progreso():
        for linea in proc.stdout:
            if progreso and duracion and linea.startswith("out_time_us="):
                try:
                    progreso(min(99.0, round(int(linea.split("=", 1)[1]) / 1e6 * 100 / duracion, 1)))
                except ValueError:
                    pass
    threading.Thread(target=leer_progreso, daemon=True).start()
    while proc.poll() is None:
        if cancelar is not None and cancelar.is_set():
            proc.kill(); proc.wait()
            return -1, "cancelado"
        time.sleep(0.3)
    return proc.returncode, "".join(errores)[-500:]


def preparar_para_edicion(ruta: Path, ffmpeg_dir: Path | None, cancelar: threading.Event | None = None,
                          progreso: Callable[[float], None] | None = None) -> Path:
    """Deja el video como MP4 con H.264 + AAC (lo abren Premiere, DaVinci, CapCut, Final Cut, Vegas...).

    Si ya lo es no hace nada; si solo falla el contenedor o una pista, copia lo que sirve y convierte el resto.
    Para convertir usa la tarjeta gráfica si puede (mucho más rápido) y, si falla, el procesador.
    """
    v, a = codecs_de(ruta, ffmpeg_dir)
    if v is None:
        return ruta                                   # no es un video (p. ej. solo audio): nada que hacer
    if v == "h264" and a in ("aac", None) and ruta.suffix.lower() == ".mp4":
        return ruta
    temporal = ruta.with_name(f"{ruta.stem}.edicion.mp4")
    duracion = _duracion(ruta, ffmpeg_dir)
    intentos = [([], ["-c:v", "copy"])] if v == "h264" else intentos_conversion(ffmpeg_dir, v)
    codigo, errores = 1, ""
    for entrada, video in intentos:
        args = [_ejecutable(ffmpeg_dir, "ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1",
                *entrada, "-i", str(ruta), "-map", "0:v:0", "-map", "0:a:0?", *video]
        args += ["-c:a", "copy"] if a == "aac" else ["-c:a", "aac", "-b:a", "192k"]
        args += ["-movflags", "+faststart", str(temporal)]
        codigo, errores = _ejecutar_ffmpeg(args, duracion, cancelar, progreso)
        if codigo == -1:
            temporal.unlink(missing_ok=True)
            raise ErrorGestor(CodigoError.CANCELADO, "La descarga fue cancelada.")
        if codigo == 0:
            break
        temporal.unlink(missing_ok=True)          # la tarjeta gráfica falló con este video: se reintenta con el procesador
    if codigo != 0:
        raise ErrorGestor(CodigoError.PROCESAMIENTO, "No se pudo convertir el video a un formato para edición.",
                          causa="FFmpeg no pudo recodificar el archivo descargado.",
                          solucion="Reintenta, o desactiva «Para edición» y conviértelo con tu editor.",
                          detalle_tecnico=errores or None)
    final = ruta.with_suffix(".mp4")
    ruta.unlink()
    temporal.replace(final)
    return final


def cortar_tramos(ruta: Path, tramos: tuple[tuple[float, float], ...], exacto: bool, ffmpeg_dir: Path | None,
                  cancelar: threading.Event | None = None) -> list[Path]:
    """Corta en el equipo los trozos de un archivo ya descargado (estrategia «completo») y borra el original.

    Rápido: copia sin convertir y empieza en el fotograma clave anterior (puede adelantarse unos segundos).
    Exacto: convierte cada trozo (con la tarjeta gráfica si se puede) para que empiece en el segundo pedido.
    """
    v, _a = codecs_de(ruta, ffmpeg_dir)
    salidas = []
    for a, b in tramos:
        convertir = exacto and v is not None
        destino = ruta.with_name(f"{ruta.stem} ({_hms(a)} a {_hms(b)}){'.mp4' if convertir else ruta.suffix}")
        base = [_ejecutable(ffmpeg_dir, "ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
        corte = ["-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(ruta), "-map", "0:v:0?", "-map", "0:a:0?"]
        intentos = [(e, [*vid, "-c:a", "aac", "-b:a", "192k"]) for e, vid in intentos_conversion(ffmpeg_dir, v)] \
            if convertir else [([], ["-c", "copy", "-avoid_negative_ts", "make_zero"])]
        codigo, errores = 1, ""
        for entrada, extra in intentos:
            codigo, errores = _ejecutar_ffmpeg([*base, *entrada, *corte, *extra, str(destino)], None, cancelar, None)
            if codigo in (0, -1):
                break
            destino.unlink(missing_ok=True)
        if codigo == -1:
            for x in [destino, *salidas]:
                x.unlink(missing_ok=True)
            raise ErrorGestor(CodigoError.CANCELADO, "La descarga fue cancelada.")
        if codigo != 0:
            raise ErrorGestor(CodigoError.PROCESAMIENTO, "No se pudo cortar el trozo del video.",
                              solucion="Reintenta, o prueba con «Corte exacto».", detalle_tecnico=errores or None)
        salidas.append(destino)
    ruta.unlink()
    return salidas


def asegurar_ffmpeg_en_path(ffmpeg_dir: Path | None) -> None:
    """yt-dlp busca FFmpeg en el PATH (no en ffmpeg_location) para bajar trozos: se añade su carpeta.

    Además yt-dlp RECUERDA «no encontrado» la primera vez que lo busca (p. ej. en una descarga normal anterior):
    se borra ese recuerdo para que vuelva a buscarlo con el PATH nuevo.
    """
    if not ffmpeg_dir:
        return
    if str(ffmpeg_dir) not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    cache = getattr(FFmpegPostProcessor, "_version_cache", None)
    if isinstance(cache, dict):
        for nombre in ("ffmpeg", "ffprobe"):
            if not cache.get(nombre):
                cache.pop(nombre, None)


def _clasificar(carpeta: Path, modo: str) -> tuple[ArchivoDescargado, ...]:
    salida = []
    for f in sorted(carpeta.iterdir()):
        if not f.is_file() or f.suffix.lower() in _EXT_TEMPORALES:
            continue
        ext = f.suffix.lower()
        if ext in _EXT_SUBS:
            rol = RolArchivo.SUBTITULO
        elif ext in _EXT_IMAGEN:
            rol = RolArchivo.PORTADA
        else:
            rol = RolArchivo.AUDIO if modo == "audio" else RolArchivo.VIDEO
        salida.append(ArchivoDescargado(f, rol))
    return tuple(salida)


def descargar(url: str, opciones: OpcionesDescarga, carpeta_trabajo: Path, *,
              progreso: Callable[[Progreso], None] | None = None,
              cancelar: threading.Event | None = None,
              tamano_estimado: int | None = None,
              permitir_interno: bool = False) -> ResultadoDescarga:
    """Descarga `url` en `carpeta_trabajo`. Lanza ErrorGestor si algo falla."""
    url = validar_url(url, permitir_interno=permitir_interno)
    opciones.validar()
    if _necesita_ffmpeg(opciones) and not opciones.ffmpeg_dir:
        raise traducir_excepcion(RuntimeError("ffmpeg not found"))

    carpeta_trabajo.mkdir(parents=True, exist_ok=True)
    if opciones.tramos:
        asegurar_ffmpeg_en_path(opciones.ffmpeg_dir)
    if tamano_estimado:
        libre = shutil.disk_usage(carpeta_trabajo).free
        if libre < tamano_estimado * 1.2:   # 20 % de margen para archivos temporales
            raise ErrorGestor(CodigoError.ESPACIO_INSUFICIENTE, "No hay espacio suficiente en el disco.",
                              causa=f"Se necesitan ~{tamano_estimado // 1_048_576} MB y hay {libre // 1_048_576} MB libres.",
                              solucion="Libera espacio o elige otro disco.")

    def hook(d: dict) -> None:
        # Este hook lo llama yt-dlp muy a menudo: es el lugar para cancelar.
        if cancelar is not None and cancelar.is_set():
            raise DescargaCancelada("Descarga cancelada por el usuario")
        if progreso is None:
            return
        if "postprocessor" in d:   # evento de un post-procesador (FFmpeg)
            progreso(Progreso("procesando" if d.get("status") != "finished" else "completado"))
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        hecho = d.get("downloaded_bytes")
        pct = round(hecho * 100 / total, 1) if total and hecho is not None else None
        estado = "descargando" if d.get("status") == "downloading" else "procesando"
        progreso(Progreso(estado, pct, d.get("speed"), d.get("eta"), hecho, total,
                          Path(d["filename"]).name if d.get("filename") else None))

    def bajar(codificador_rangos: list[str] | None = None) -> dict:
        with yt_dlp.YoutubeDL(construir_opciones_ytdlp(opciones, carpeta_trabajo, hook, codificador_rangos)) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=True))

    try:
        try:
            info = bajar()
        except DescargaCancelada:
            raise
        except Exception:
            # Trozo con corte exacto: si el codificador de la tarjeta gráfica falla con este video, se reintenta con x264.
            if not (estrategia_tramos(opciones) == "rangos" and opciones.corte_exacto and opciones.modo == "video"
                    and codificador_h264(opciones.ffmpeg_dir)[0] != _X264[0]):
                raise
            info = bajar(_X264[1])
    except DescargaCancelada:
        raise ErrorGestor(CodigoError.CANCELADO, "La descarga fue cancelada.") from None
    except ErrorGestor:
        raise
    except Exception as exc:  # yt-dlp lanza varios tipos; los traducimos todos
        raise traducir_excepcion(exc) from exc

    archivos = _clasificar(carpeta_trabajo, opciones.modo)
    if estrategia_tramos(opciones) == "completo":
        if progreso:
            progreso(Progreso("procesando"))
        for a in archivos:
            if a.rol in (RolArchivo.VIDEO, RolArchivo.AUDIO):
                cortar_tramos(a.ruta, opciones.tramos, opciones.corte_exacto, opciones.ffmpeg_dir, cancelar)
        archivos = _clasificar(carpeta_trabajo, opciones.modo)
    if opciones.editable and opciones.modo == "video":
        for a in archivos:
            if a.rol == RolArchivo.VIDEO:
                if progreso:
                    progreso(Progreso("procesando"))
                preparar_para_edicion(a.ruta, opciones.ffmpeg_dir, cancelar,
                                      (lambda pct: progreso(Progreso("procesando", pct))) if progreso else None)
        archivos = _clasificar(carpeta_trabajo, opciones.modo)
    roles = {a.rol for a in archivos}
    if opciones.modo == "subtitulos" and RolArchivo.SUBTITULO not in roles:
        raise ErrorGestor(CodigoError.SUBTITULOS_INEXISTENTES, "No hay subtítulos en los idiomas pedidos.",
                          causa="El sitio no ofrece subtítulos (manuales ni automáticos) en ese idioma.",
                          solucion="Prueba con otro idioma, o desactiva los subtítulos automáticos si el problema es su calidad.")
    if opciones.modo == "portada" and RolArchivo.PORTADA not in roles:
        raise ErrorGestor(CodigoError.PROCESAMIENTO, "El sitio no ofrece portada para este contenido.")
    if opciones.modo in ("video", "audio") and not roles & {RolArchivo.VIDEO, RolArchivo.AUDIO}:
        raise ErrorGestor(CodigoError.PROCESAMIENTO, "La descarga terminó sin producir un archivo.",
                          causa=None, solucion="Reintenta la descarga.")
    if progreso:
        progreso(Progreso("completado", 100.0))
    return ResultadoDescarga(archivos, normalizar_info(info or {}, url))


def limpiar_carpeta_trabajo(carpeta: Path, raiz_permitida: Path) -> None:
    """Borra una carpeta de trabajo, SOLO si está dentro de `raiz_permitida`.

    Protección contra borrar por error una carpeta importante (p. ej. si una
    ruta llegara mal calculada).
    """
    carpeta, raiz = carpeta.resolve(), raiz_permitida.resolve()
    if carpeta == raiz or raiz not in carpeta.parents:
        raise ErrorGestor(CodigoError.CONFIGURACION, "Ruta de limpieza fuera de la carpeta permitida.")
    shutil.rmtree(carpeta, ignore_errors=True)
