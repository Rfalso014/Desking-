"""Ubicaciones y preferencias globales.

Las preferencias viven en la base de datos (Fase 8); aquí está su forma y
los valores por defecto, más la búsqueda de FFmpeg.
"""
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .nativo.comun import carpeta_datos as _carpeta_datos

EMPAQUETADO = bool(getattr(sys, "frozen", False))     # True dentro del .exe creado con PyInstaller
# Raíz de la instalación: la carpeta del .exe, o la raíz del repositorio en desarrollo.
RAIZ_PROYECTO = Path(sys.executable).parent if EMPAQUETADO else Path(__file__).resolve().parents[2]


carpeta_datos = _carpeta_datos  # misma función que usa el host nativo


def localizar_ffmpeg() -> Path | None:
    """Devuelve la CARPETA que contiene ffmpeg y ffprobe, o None si no están.

    Orden: variable GESTOR_FFMPEG, tools/ffmpeg del proyecto, PATH del sistema.
    """
    candidatos: list[Path] = []
    if os.environ.get("GESTOR_FFMPEG"):
        candidatos.append(Path(os.environ["GESTOR_FFMPEG"]))
    candidatos.append(RAIZ_PROYECTO / "tools" / "ffmpeg")
    en_path = shutil.which("ffmpeg")
    if en_path:
        candidatos.append(Path(en_path).parent)
    for c in candidatos:
        if (c / "ffmpeg.exe").exists() or (c / "ffmpeg").exists():
            return c
    return None


def localizar_deno() -> Path | None:
    """Ruta del ejecutable de Deno (runtime de JavaScript que yt-dlp usa para YouTube), o None.

    Orden: GESTOR_DENO, tools/deno del proyecto, la carpeta Scripts del entorno virtual, el PATH.
    """
    candidatos: list[Path] = []
    if os.environ.get("GESTOR_DENO"):
        candidatos.append(Path(os.environ["GESTOR_DENO"]))
    candidatos += [RAIZ_PROYECTO / "tools" / "deno" / "deno.exe", Path(sys.prefix) / "Scripts" / "deno.exe"]
    en_path = shutil.which("deno")
    if en_path:
        candidatos.append(Path(en_path))
    return next((c for c in candidatos if c.is_file()), None)


# velocidad -> (fragmentos simultáneos, tamaño de trozo HTTP en bytes).
# Fragmentos: muchos sitios dividen el video en trocitos (HLS/DASH) que se pueden bajar a la vez.
# Trozo HTTP: pedir el archivo en partes de 10 MB evita que YouTube limite la velocidad.
PERFILES_VELOCIDAD = {"normal": (1, 0), "rapida": (8, 10 * 1024 * 1024), "maxima": (16, 10 * 1024 * 1024)}


NAVEGADORES_SESION = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")


def opciones_sesion(prefs: "Preferencias") -> dict:
    """Opciones de yt-dlp para usar la sesión ya iniciada en el navegador (o un cookies.txt). Vacío = sin sesión.

    No se guardan contraseñas ni cookies: solo qué navegador usar o la ruta de un archivo.
    """
    if prefs.archivo_cookies and Path(prefs.archivo_cookies).is_file():
        return {"cookiefile": str(prefs.archivo_cookies)}
    if prefs.sesion_navegador in NAVEGADORES_SESION:
        return {"cookiesfrombrowser": (prefs.sesion_navegador,)}
    return {}


@dataclass
class Preferencias:
    carpeta_raiz: Path = field(default_factory=lambda: Path.home() / "Downloads" / "GestorDescargas")
    organizacion: str = "tipo_y_contenido"   # "tipo_y_contenido" | "tipo" | "contenido" | "manual"
    duplicados: str = "renombrar"            # "omitir" | "reemplazar" | "renombrar"
    altura_max: int | None = None            # None = mejor calidad
    contenedor_video: str = "mp4"            # "mp4" | "mkv" | "mejor"
    formato_audio: str = "mp3"               # "original" | "mp3" | "m4a" | "flac" | "ogg" | "opus"
    idiomas_subtitulos: tuple[str, ...] = ("es",)
    descargar_subtitulos: bool = False
    descargar_portada: bool = True
    plantilla_nombre: str = "%(title).120B [%(id)s]"
    descargas_simultaneas: int = 3
    tema: str = "auto"                       # "auto" | "claro" | "oscuro"
    velocidad: str = "rapida"               # "normal" | "rapida" | "maxima" (ver PERFILES_VELOCIDAD)
    reanudar_al_iniciar: bool = True         # recuperar tareas pendientes al abrir
    actualizar_solo: bool = True             # instalar las versiones nuevas sin preguntar (cuando no hay descargas)
    sesion_navegador: str = "ninguno"        # "ninguno" | uno de NAVEGADORES_SESION: usar su sesión iniciada
    archivo_cookies: str = ""                # alternativa: ruta de un cookies.txt exportado
