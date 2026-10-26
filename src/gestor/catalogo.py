"""Valores permitidos para las opciones de descarga (listas blancas).

Está en un módulo propio y SIN dependencias pesadas para que lo use también el
host de Native Messaging, que debe arrancar rápido.
"""
import re

MODOS = ("video", "audio", "subtitulos", "portada")
CONTENEDORES_VIDEO = {"mp4", "mkv", "mejor"}
FORMATOS_AUDIO = {"original", "mp3", "m4a", "flac", "ogg", "opus", "wav"}
_IDIOMA = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$")


def _ok_altura(v): return v is None or (isinstance(v, int) and not isinstance(v, bool) and 100 <= v <= 8640)
def _ok_idiomas(v): return isinstance(v, (list, tuple)) and len(v) <= 20 and all(isinstance(i, str) and _IDIOMA.match(i) for i in v)
def _ok_destino(v): return v is None or (isinstance(v, str) and 0 < len(v) <= 260 and "\x00" not in v)
def _ok_bool(v): return isinstance(v, bool)
def _ok_subcarpeta(v): return v is None or (isinstance(v, str) and 0 < len(v) <= 80)
def _ok_grupo(v): return v is None or (isinstance(v, str) and 0 < len(v.strip()) <= 60 and "\x00" not in v)
def _ok_titulo(v): return v is None or (isinstance(v, str) and 0 < len(v) <= 300)
MAX_MEDIOS = 8


def _ok_medios(v):
    """Enlaces directos al video (m3u8, mp4...) que la extension vio pasar mientras se reproducia."""
    return (isinstance(v, (list, tuple)) and len(v) <= MAX_MEDIOS
            and all(isinstance(u, str) and u.startswith(("http://", "https://")) and len(u) <= 2048 for u in v))
MAX_TRAMOS, MAX_SEGUNDOS = 10, 24 * 3600


def _ok_segundo(x): return isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= MAX_SEGUNDOS


def _ok_tramos(v):
    """[[inicio, fin], ...] en segundos: trozos del video que se quieren (vacío = el video entero)."""
    return (isinstance(v, (list, tuple)) and len(v) <= MAX_TRAMOS
            and all(isinstance(t, (list, tuple)) and len(t) == 2 and _ok_segundo(t[0]) and _ok_segundo(t[1]) and t[0] < t[1] for t in v))


# Campos que una regla o una tarea puede cambiar, con su validador.
CAMPOS_ACCION = {
    "modo": lambda v: v in MODOS,
    "altura_max": _ok_altura,
    "contenedor_video": lambda v: v in CONTENEDORES_VIDEO,
    "formato_audio": lambda v: v in FORMATOS_AUDIO,
    "subtitulos": _ok_idiomas,
    "portada": _ok_bool,
    "editable": _ok_bool,          # MP4 H.264 + AAC que abre cualquier programa de edición
    "tramos": _ok_tramos,          # solo estos minutos del video
    "corte_exacto": _ok_bool,      # cortar en el segundo exacto (convierte el trozo; si no, corta en el fotograma clave)
    "subcarpeta": _ok_subcarpeta,
    "carpeta_propia": _ok_bool,    # cada descarga en su propia carpeta (con el titulo) o suelta en la de su tipo
    "grupo": _ok_grupo,            # grupo de descargas al que pertenece (se descarga junto con «Descargar grupo»)
    "medios": _ok_medios,          # enlaces directos para cuando la pagina no se puede analizar
    "titulo_pagina": _ok_titulo,   # titulo de la pagina, para nombrar lo que se baje por enlace directo
    "destino": _ok_destino,
    "excluir": _ok_bool,
}
