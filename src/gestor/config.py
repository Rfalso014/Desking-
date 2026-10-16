"""Ubicaciones y preferencias globales.

Las preferencias viven en la base de datos (Fase 8); aquí está su forma y
los valores por defecto, más la búsqueda de FFmpeg.
"""
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parents[2]


def carpeta_datos() -> Path:
    """Carpeta de datos de la app (base de datos, clave IPC). Se crea si falta."""
    base = Path(os.environ.get("GESTOR_DATOS") or
                (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GestorDescargas"))
    base.mkdir(parents=True, exist_ok=True)
    return base


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
