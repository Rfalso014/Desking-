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


# Campos que una regla o una tarea puede cambiar, con su validador.
CAMPOS_ACCION = {
    "modo": lambda v: v in MODOS,
    "altura_max": _ok_altura,
    "contenedor_video": lambda v: v in CONTENEDORES_VIDEO,
    "formato_audio": lambda v: v in FORMATOS_AUDIO,
    "subtitulos": _ok_idiomas,
    "portada": _ok_bool,
    "subcarpeta": _ok_subcarpeta,
    "destino": _ok_destino,
    "excluir": _ok_bool,
}
