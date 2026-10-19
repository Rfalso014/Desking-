"""Modelos de datos del núcleo: cómo representamos un contenido y un error.

Usamos `dataclass`: una forma corta de declarar clases que solo guardan datos.
`frozen=True` las hace inmutables (no se pueden modificar después de crearlas),
lo que evita errores tontos como cambiar un valor sin querer.
"""
from dataclasses import dataclass, field
from enum import Enum


class TipoFormato(str, Enum):
    """Qué contiene un formato descargable."""

    VIDEO_Y_AUDIO = "video+audio"  # un solo archivo con ambas pistas
    SOLO_VIDEO = "solo_video"      # hay que combinarlo con un audio (FFmpeg)
    SOLO_AUDIO = "solo_audio"
    DESCONOCIDO = "desconocido"


@dataclass(frozen=True)
class FormatoInfo:
    """Un formato concreto que ofrece el sitio (p. ej. mp4 1080p)."""

    id: str
    extension: str
    tipo: TipoFormato
    altura: int | None = None          # 1080, 720... (None si no es video)
    tamano_bytes: int | None = None    # puede ser estimado o no existir
    tamano_es_estimado: bool = False
    codec_video: str | None = None
    codec_audio: str | None = None
    nota: str | None = None            # texto del sitio, p. ej. "1080p60"
    tiene_drm: bool = False            # indicio reportado por yt-dlp


@dataclass(frozen=True)
class InfoContenido:
    """Lo que sabemos de una URL, ya normalizado (independiente de yt-dlp)."""

    url: str
    titulo: str
    sitio: str                          # nombre del extractor, p. ej. "Youtube"
    id_contenido: str | None = None
    duracion_seg: float | None = None
    miniatura_url: str | None = None
    autor: str | None = None
    es_en_vivo: bool = False
    es_lista: bool = False
    entradas: tuple[tuple[str, str], ...] = ()   # (url, título) de cada video de una lista
    formatos: tuple[FormatoInfo, ...] = ()
    # idioma -> True si es automático. Ej: {"es": False, "en": True}
    subtitulos: dict[str, bool] = field(default_factory=dict)


class EstadoTarea(str, Enum):
    """Estados mínimos que pide el proyecto (se muestran igual en app y extensión)."""

    DETECTADO = "detectado"
    ANALIZANDO = "analizando"
    PENDIENTE = "pendiente"
    DESCARGANDO = "descargando"
    PROCESANDO = "procesando"
    COMPLETADO = "completado"
    CANCELADO = "cancelado"
    ERROR = "error"


ESTADOS_ACTIVOS = (EstadoTarea.ANALIZANDO, EstadoTarea.DESCARGANDO, EstadoTarea.PROCESANDO)
ESTADOS_FINALES = (EstadoTarea.COMPLETADO, EstadoTarea.CANCELADO, EstadoTarea.ERROR)


@dataclass
class Tarea:
    id: str
    url: str
    estado: EstadoTarea = EstadoTarea.DETECTADO
    origen: str | None = None            # página desde la que se envió
    titulo: str | None = None
    sitio: str | None = None
    progreso: float | None = None
    velocidad_bps: float | None = None
    eta_seg: float | None = None
    creado: str = ""
    actualizado: str = ""
    opciones: dict = field(default_factory=dict)   # elecciones del usuario para ESTA tarea
    destino_manual: str | None = None
    carpeta_final: str | None = None
    archivos: list = field(default_factory=list)
    error: dict | None = None
    intentos: int = 0
    notas: list = field(default_factory=list)      # p. ej. qué reglas se aplicaron
    miniatura: str | None = None
    duracion: float | None = None

    def a_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["estado"] = self.estado.value
        return d


class CodigoError(str, Enum):
    URL_INVALIDA = "url_invalida"
    SITIO_NO_COMPATIBLE = "sitio_no_compatible"
    CONTENIDO_NO_DISPONIBLE = "contenido_no_disponible"
    AUTENTICACION = "autenticacion"
    CONEXION = "conexion"
    FORMATO_NO_DISPONIBLE = "formato_no_disponible"
    SUBTITULOS_INEXISTENTES = "subtitulos_inexistentes"
    ESPACIO_INSUFICIENTE = "espacio_insuficiente"
    PERMISOS = "permisos"
    FFMPEG_AUSENTE = "ffmpeg_ausente"
    PROCESAMIENTO = "procesamiento"
    CONTENIDO_PROTEGIDO = "contenido_protegido"
    COMUNICACION = "comunicacion"
    NO_VINCULADO = "no_vinculado"
    CONFIGURACION = "configuracion"
    CANCELADO = "cancelado"
    DESCONOCIDO = "desconocido"


class ErrorGestor(Exception):
    """Error con el formato que pide el proyecto: mensaje, causa, solución, detalle.

    Regla: si no conocemos la causa, `causa` queda en None. No se inventa.
    """

    def __init__(self, codigo: CodigoError, mensaje: str, *,
                 causa: str | None = None, solucion: str | None = None,
                 detalle_tecnico: str | None = None):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje
        self.causa = causa
        self.solucion = solucion
        self.detalle_tecnico = detalle_tecnico
