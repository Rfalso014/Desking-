"""Descarga video, audio, subtítulos y portada con yt-dlp.

Idea clave: cada tarea descarga en SU PROPIA carpeta de trabajo (temporal).
Cuando termina bien, el organizador (organizador.py) mueve los archivos a su
destino final. Así nunca quedan archivos a medias en las carpetas del usuario
y una tarea cancelada se limpia borrando solo su carpeta.
"""
import re
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from .catalogo import CONTENEDORES_VIDEO, FORMATOS_AUDIO, MODOS, _IDIOMA
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
    plantilla_nombre: str = "%(title).120B [%(id)s]"
    ffmpeg_dir: Path | None = None
    fragmentos: int = 8                       # fragmentos que se bajan a la vez
    trozo_http: int = 10 * 1024 * 1024        # 0 = sin trozos
    deno: Path | None = None                  # runtime JS para YouTube
    sesion: dict = field(default_factory=dict)   # cookies del navegador / cookies.txt (ver config.opciones_sesion)

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
        if not (isinstance(self.trozo_http, int) and 0 <= self.trozo_http <= 100 * 1024 * 1024):
            raise malo("El tamaño de trozo no es válido.")
        if self.altura_max is not None and not (isinstance(self.altura_max, int) and 100 <= self.altura_max <= 8640):
            raise malo("La altura máxima debe estar entre 100 y 8640.")
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
    if o.altura_max:
        h = o.altura_max
        return f"bv*[height<=?{h}]+ba/b[height<=?{h}]"
    return "bv*+ba/b"


def construir_opciones_ytdlp(o: OpcionesDescarga, carpeta: Path,
                             hook_progreso: Callable[[dict], None]) -> dict[str, Any]:
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
    pp: list[dict[str, Any]] = p["postprocessors"]

    if o.modo in ("subtitulos", "portada"):
        p["skip_download"] = True      # no se baja el video: solo los extras
    elif o.modo == "video":
        if o.contenedor_video != "mejor":
            p["merge_output_format"] = o.contenedor_video  # solo une pistas (sin recodificar)
    elif o.formato_audio != "original":
        q: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": _CODEC_YTDLP[o.formato_audio]}
        if o.formato_audio not in _SIN_CALIDAD:
            q["preferredquality"] = "192"
        pp.append(q)

    if o.subtitulos:
        p.update(writesubtitles=True, writeautomaticsub=o.subtitulos_automaticos,
                 subtitleslangs=list(o.subtitulos), subtitlesformat="srt/best")
        pp.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
    if o.portada or o.modo == "portada":
        p["writethumbnail"] = True
        pp.append({"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
    return p


def _necesita_ffmpeg(o: OpcionesDescarga) -> bool:
    if o.modo in ("subtitulos", "portada"):
        return True      # la conversión de subtítulos/portada usa FFmpeg
    solo_pista_original = o.modo == "audio" and o.formato_audio == "original" and not o.subtitulos and not o.portada
    return not solo_pista_original


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

    try:
        with yt_dlp.YoutubeDL(construir_opciones_ytdlp(opciones, carpeta_trabajo, hook)) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
    except DescargaCancelada:
        raise ErrorGestor(CodigoError.CANCELADO, "La descarga fue cancelada.") from None
    except ErrorGestor:
        raise
    except Exception as exc:  # yt-dlp lanza varios tipos; los traducimos todos
        raise traducir_excepcion(exc) from exc

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
