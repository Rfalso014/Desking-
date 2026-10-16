"""Diagnóstico de contenido protegido (DRM). SOLO detecta y explica.

Este módulo NO intenta eludir protecciones, extraer claves ni interceptar
licencias. Su trabajo es decirle al usuario, con honestidad, qué sabemos:

  - CONFIRMADO: el propio sitio (vía yt-dlp) declara que el contenido tiene DRM.
  - INDICIO:    el servicio es conocido por usar DRM, pero no hay confirmación.
  - SIN EVIDENCIA: no sabemos por qué falló; no se acusa a DRM sin pruebas.
"""
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit

from .modelos import CodigoError, ErrorGestor, InfoContenido


class Compatibilidad(str, Enum):
    COMPATIBLE = "compatible"
    PARCIAL = "parcialmente_compatible"
    PROTEGIDO = "protegido"
    DESCONOCIDO = "desconocido"


class Confianza(str, Enum):
    CONFIRMADO = "confirmado"
    INDICIO = "indicio"
    NO_APLICA = "no_aplica"


# Servicios cuyo catálogo principal usa DRM (Widevine/PlayReady/FairPlay).
# Es una lista de INDICIOS: sirve para explicar, nunca para bloquear por sí sola.
SERVICIOS_CON_DRM = {
    "netflix.com": ("Netflix", "Usa la descarga para ver sin conexión dentro de la app oficial de Netflix."),
    "disneyplus.com": ("Disney+", "Usa la descarga sin conexión de la app oficial de Disney+."),
    "primevideo.com": ("Prime Video", "Usa la descarga sin conexión de la app oficial de Prime Video."),
    "max.com": ("Max", "Usa la descarga sin conexión de la app oficial."),
    "hbomax.com": ("Max", "Usa la descarga sin conexión de la app oficial."),
    "hulu.com": ("Hulu", "Usa la descarga sin conexión de la app oficial, si tu plan la incluye."),
    "tv.apple.com": ("Apple TV+", "Usa la descarga sin conexión de la app oficial de Apple TV."),
    "paramountplus.com": ("Paramount+", "Usa la descarga sin conexión de la app oficial."),
    "spotify.com": ("Spotify", "Usa la descarga sin conexión de la app oficial de Spotify (plan Premium)."),
}


@dataclass(frozen=True)
class Diagnostico:
    nivel: Compatibilidad
    confianza: Confianza
    motivo: str
    alternativas: tuple[str, ...] = ()
    detalles: tuple[str, ...] = field(default_factory=tuple)   # para registro/diagnóstico

    @property
    def bloquea(self) -> bool:
        """Solo se bloquea una descarga cuando el DRM está CONFIRMADO."""
        return self.nivel == Compatibilidad.PROTEGIDO and self.confianza == Confianza.CONFIRMADO


def _servicio(url: str) -> tuple[str, str] | None:
    host = (urlsplit(url).hostname or "").lower()
    for dominio, datos in SERVICIOS_CON_DRM.items():
        if host == dominio or host.endswith("." + dominio):
            return datos
    return None


def evaluar(url: str, info: InfoContenido | None = None, error: ErrorGestor | None = None) -> Diagnostico:
    servicio = _servicio(url)
    alt = (servicio[1],) if servicio else ("Busca si el servicio ofrece descarga oficial para ver sin conexión.",)
    detalles = [f"url_host={urlsplit(url).hostname}", f"servicio_conocido={servicio[0] if servicio else None}"]

    if info is not None and info.formatos:
        con_drm = [f for f in info.formatos if f.tiene_drm]
        sin_drm = [f for f in info.formatos if not f.tiene_drm]
        detalles.append(f"formatos={len(info.formatos)} con_drm={len(con_drm)}")
        if con_drm and not sin_drm:
            return Diagnostico(Compatibilidad.PROTEGIDO, Confianza.CONFIRMADO,
                               "El sitio declara que todos los formatos de este contenido tienen protección anticopia (DRM).",
                               alt, tuple(detalles))
        if con_drm:
            return Diagnostico(Compatibilidad.PARCIAL, Confianza.CONFIRMADO,
                               "Algunos formatos tienen DRM y no se pueden descargar; los demás sí.",
                               alt, tuple(detalles))
        if info.es_en_vivo:
            return Diagnostico(Compatibilidad.PARCIAL, Confianza.NO_APLICA,
                               "Es una transmisión en vivo: la descarga puede ser incompleta.", (), tuple(detalles))
        return Diagnostico(Compatibilidad.COMPATIBLE, Confianza.NO_APLICA, "No se detectó protección.",
                           (), tuple(detalles))

    if error is not None:
        detalles.append(f"error={error.codigo.value}")
        if error.codigo == CodigoError.CONTENIDO_PROTEGIDO:
            return Diagnostico(Compatibilidad.PROTEGIDO, Confianza.CONFIRMADO,
                               "yt-dlp informa que el contenido está protegido por DRM.", alt, tuple(detalles))
        if servicio and error.codigo in (CodigoError.SITIO_NO_COMPATIBLE, CodigoError.DESCONOCIDO,
                                         CodigoError.FORMATO_NO_DISPONIBLE):
            return Diagnostico(Compatibilidad.PROTEGIDO, Confianza.INDICIO,
                               f"{servicio[0]} suele proteger su contenido con DRM; es la explicación más probable "
                               "de que no se pueda descargar, pero no está confirmada.", alt, tuple(detalles))
    return Diagnostico(Compatibilidad.DESCONOCIDO, Confianza.NO_APLICA,
                       "No hay evidencia de protección; el problema tiene otro origen o no se pudo determinar.",
                       (), tuple(detalles))


def enriquecer_error(url: str, error: ErrorGestor) -> ErrorGestor:
    """Si hay DRM confirmado o indicio fuerte, añade esa explicación al error; si no, lo deja igual."""
    d = evaluar(url, error=error)
    if d.nivel != Compatibilidad.PROTEGIDO:
        return error
    if d.confianza == Confianza.CONFIRMADO:
        nuevo = ErrorGestor(CodigoError.CONTENIDO_PROTEGIDO, "Este contenido está protegido y no se puede descargar.",
                            causa=d.motivo, solucion=" ".join(d.alternativas), detalle_tecnico=error.detalle_tecnico)
    else:   # indicio: conservamos el código original y aclaramos que es una probabilidad
        nuevo = ErrorGestor(error.codigo, error.mensaje, causa=d.motivo,
                            solucion=" ".join(d.alternativas), detalle_tecnico=error.detalle_tecnico)
    return nuevo
