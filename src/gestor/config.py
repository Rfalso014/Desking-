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
    descargas_simultaneas: int = 2
    reanudar_al_iniciar: bool = True         # recuperar tareas pendientes al abrir
