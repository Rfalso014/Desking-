"""Consulta qué ofrece una URL usando yt-dlp, SIN descargar nada.

Dos capas separadas a propósito:
  1. `obtener_info`  -> habla con yt-dlp (necesita red).
  2. `normalizar_info` -> convierte el diccionario de yt-dlp a nuestros modelos
     (función pura: se prueba offline con datos de ejemplo).
"""
from collections.abc import Callable
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

from .modelos import (CodigoError, ErrorGestor, FormatoInfo, InfoContenido,
                      TipoFormato)
from .validacion import validar_url


def _tipo_de_formato(f: dict[str, Any]) -> TipoFormato:
    # yt-dlp escribe el texto "none" cuando una pista no existe.
    v, a = f.get("vcodec"), f.get("acodec")
    tiene_v = v not in (None, "none")
    tiene_a = a not in (None, "none")
    if tiene_v and tiene_a:
        return TipoFormato.VIDEO_Y_AUDIO
    if tiene_v:
        return TipoFormato.SOLO_VIDEO
    if tiene_a:
        return TipoFormato.SOLO_AUDIO
    return TipoFormato.DESCONOCIDO


def _formato(f: dict[str, Any]) -> FormatoInfo:
    exacto, estimado = f.get("filesize"), f.get("filesize_approx")
    tamano = exacto if exacto else estimado
    return FormatoInfo(
        id=str(f.get("format_id", "")),
        extension=f.get("ext") or "",
        tipo=_tipo_de_formato(f),
        altura=f.get("height"),
        tamano_bytes=int(tamano) if tamano else None,
        tamano_es_estimado=not exacto and bool(estimado),
        codec_video=None if f.get("vcodec") in (None, "none") else f["vcodec"],
        codec_audio=None if f.get("acodec") in (None, "none") else f["acodec"],
        nota=f.get("format_note"),
        # yt-dlp pone has_drm=True cuando el propio sitio lo declara.
        tiene_drm=bool(f.get("has_drm")),
    )


def normalizar_info(info: dict[str, Any], url: str) -> InfoContenido:
    """Convierte el diccionario de yt-dlp en un InfoContenido."""
    subs: dict[str, bool] = {}
    # Primero los automáticos, luego los manuales: si un idioma existe en
    # ambos, el manual (False) sobrescribe y gana.
    for idioma in (info.get("automatic_captions") or {}):
        subs[idioma] = True
    for idioma in (info.get("subtitles") or {}):
        subs[idioma] = False

    return InfoContenido(
        url=info.get("webpage_url") or url,
        titulo=info.get("title") or "Sin título",
        sitio=info.get("extractor_key") or info.get("extractor") or "Desconocido",
        id_contenido=info.get("id"),
        duracion_seg=info.get("duration"),
        miniatura_url=info.get("thumbnail"),
        autor=info.get("uploader") or info.get("channel"),
        es_en_vivo=bool(info.get("is_live")),
        es_lista=info.get("_type") in ("playlist", "multi_video"),
        formatos=tuple(_formato(f) for f in (info.get("formats") or [])),
        subtitulos=subs,
    )


def _traducir_error(url: str, exc: DownloadError) -> ErrorGestor:
    """Traduce el error de yt-dlp a uno entendible.

    Solo afirmamos una causa si el mensaje de yt-dlp la indica claramente.
    En cualquier otro caso: DESCONOCIDO, con el texto original como detalle.
    """
    texto = str(exc)
    bajo = texto.lower()
    if "unsupported url" in bajo:
        return ErrorGestor(CodigoError.SITIO_NO_COMPATIBLE,
                           "Este enlace no es compatible.",
                           causa="yt-dlp no reconoce el sitio o la página no contiene un video detectable.",
                           solucion="Prueba con el enlace directo del video, o revisa si yt-dlp está actualizado.",
                           detalle_tecnico=texto)
    if any(p in bajo for p in ("private video", "video unavailable", "has been removed",
                               "this video is not available", "does not exist", "http error 404")):
        return ErrorGestor(CodigoError.CONTENIDO_NO_DISPONIBLE,
                           "El contenido no está disponible.",
                           causa="Puede estar eliminado, privado o restringido por región.",
                           solucion="Comprueba que el enlace abre en tu navegador.",
                           detalle_tecnico=texto)
    if any(p in bajo for p in ("sign in", "log in", "login required", "http error 401", "http error 403")):
        return ErrorGestor(CodigoError.AUTENTICACION,
                           "El sitio pide iniciar sesión o negó el acceso.",
                           causa="El contenido requiere una cuenta o permisos.",
                           solucion="Más adelante podrás indicar cookies del navegador (fase posterior).",
                           detalle_tecnico=texto)
    if any(p in bajo for p in ("urlopen error", "timed out", "name or service not known",
                               "getaddrinfo failed", "connection")):
        return ErrorGestor(CodigoError.CONEXION,
                           "No se pudo conectar con el sitio.",
                           causa="Falla de red, o el sitio no responde.",
                           solucion="Revisa tu conexión a internet y reintenta.",
                           detalle_tecnico=texto)
    return ErrorGestor(CodigoError.DESCONOCIDO,
                       "No se pudo analizar el enlace.",
                       causa=None, solucion="Reintenta; si persiste, revisa los detalles técnicos.",
                       detalle_tecnico=texto)


# Un "extractor de info" es cualquier función URL -> diccionario de yt-dlp.
# Permite inyectar uno falso en las pruebas.
FuncionExtraer = Callable[[str], dict[str, Any]]


def _extraer_con_ytdlp(url: str) -> dict[str, Any]:
    opciones = {
        "quiet": True,          # no imprimir en consola
        "no_warnings": True,
        "skip_download": True,  # SOLO consultar, nunca descargar
        "noplaylist": True,     # si la URL es de un video dentro de lista, solo ese video
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(url, download=False)
        # sanitize_info deja solo tipos simples (dict/list/str/num), seguros de manejar.
        return ydl.sanitize_info(info)


def obtener_info(url: str, *, extraer: FuncionExtraer = _extraer_con_ytdlp,
                 permitir_interno: bool = False) -> InfoContenido:
    """Valida la URL, consulta al sitio y devuelve un InfoContenido."""
    url = validar_url(url, permitir_interno=permitir_interno)
    try:
        info = extraer(url)
    except DownloadError as exc:
        raise _traducir_error(url, exc) from exc
    if not info:
        raise ErrorGestor(CodigoError.DESCONOCIDO, "El sitio no devolvió información.")
    return normalizar_info(info, url)
