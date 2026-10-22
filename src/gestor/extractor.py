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
from .config import localizar_deno
from .errores import traducir_excepcion
from .validacion import validar_url


MAX_VIDEOS_LISTA = 500   # tope de videos que se toman de una lista


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

    entradas = []
    for e in (info.get("entries") or []):
        if not isinstance(e, dict):
            continue
        u = e.get("webpage_url") or e.get("url")
        if isinstance(u, str) and u.startswith(("http://", "https://")):
            entradas.append((u, e.get("title") or "Sin título"))

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
        entradas=tuple(entradas),
        formatos=tuple(_formato(f) for f in (info.get("formats") or [])),
        subtitulos=subs,
    )


def tamanos_por_calidad(info: InfoContenido, maximo: int = 3) -> list[tuple[int, int]]:
    """[(altura, bytes)] aproximados de la mejor calidad, 1080p y 720p (video + su audio).

    Sirve para ver ANTES de descargar cuánto pesa cada opción: un 4K suele pesar 5 o 6 veces más que 1080p.
    Se toma el formato más pesado de cada altura (cota alta): yt-dlp puede elegir uno algo más ligero.
    """
    audio = max((f.tamano_bytes or 0 for f in info.formatos if f.tipo == TipoFormato.SOLO_AUDIO), default=0)
    por_altura: dict[int, int] = {}
    for f in info.formatos:
        if f.altura and f.tamano_bytes and f.tipo in (TipoFormato.SOLO_VIDEO, TipoFormato.VIDEO_Y_AUDIO):
            total = f.tamano_bytes + (audio if f.tipo == TipoFormato.SOLO_VIDEO else 0)
            por_altura[f.altura] = max(por_altura.get(f.altura, 0), total)
    if not por_altura:
        return []
    alturas = sorted(por_altura, reverse=True)
    elegidas = [alturas[0]] + [next((a for a in alturas if a <= tope), None) for tope in (1080, 720)]
    salida: list[tuple[int, int]] = []
    for a in elegidas:
        if a is not None and a not in [x for x, _ in salida]:
            salida.append((a, por_altura[a]))
    return salida[:maximo]


def texto_tamanos(info: InfoContenido) -> str | None:
    """«Tamaño aproximado: 2160p ≈ 679 MB · 1080p ≈ 118 MB · 720p ≈ 62 MB» (None si el sitio no lo informa)."""
    t = tamanos_por_calidad(info)
    if not t:
        return None
    mb = lambda b: f"{b / 1073741824:.1f} GB" if b >= 1073741824 else f"{b / 1048576:.0f} MB"  # noqa: E731
    return "Tamaño aproximado: " + " · ".join(f"{a}p ≈ {mb(b)}" for a, b in t)


# Un "extractor de info" es cualquier función URL -> diccionario de yt-dlp.
# Permite inyectar uno falso en las pruebas.
FuncionExtraer = Callable[[str], dict[str, Any]]


def _extraer_con_ytdlp(url: str, sesion: dict | None = None) -> dict[str, Any]:
    opciones = {
        "quiet": True,          # no imprimir en consola
        "no_warnings": True,
        "skip_download": True,  # SOLO consultar, nunca descargar
        "noplaylist": True,     # si la URL es de un video dentro de lista, solo ese video
        "socket_timeout": 20,
        # En una lista solo se leen los títulos y enlaces (rápido); cada video se analiza al descargarlo.
        "extract_flat": "in_playlist",
        "playlistend": MAX_VIDEOS_LISTA,
    }
    opciones.update(sesion or {})
    deno = localizar_deno()
    if deno:
        opciones["js_runtimes"] = {"deno": {"path": str(deno)}}
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
        raise traducir_excepcion(exc) from exc
    if not info:
        raise ErrorGestor(CodigoError.DESCONOCIDO, "El sitio no devolvió información.")
    return normalizar_info(info, url)
