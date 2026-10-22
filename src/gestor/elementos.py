"""Qué descargar: de casillas («video», «audio», «subtítulos», «portada») a opciones de descarga.

El usuario marca elementos combinables; internamente cada DESCARGA tiene un «modo»:
  - video     -> el video con su audio (+ subtítulos y portada si se marcaron); con «para edición»
                 sale en MP4 H.264 + AAC (lleva "editable": True)
  - audio     -> solo el audio (+ subtítulos y portada si se marcaron)
  - subtitulos-> solo subtítulos (y portada, si se marcó)
  - portada   -> solo la portada
Si se marcan VIDEO y AUDIO a la vez, salen dos descargas (una de cada); los subtítulos y la portada
acompañan solo a la primera para no repetirlos.

Hay una copia equivalente en JavaScript (extension/util.js, `construirOpciones`); si cambias una, cambia la otra.
"""
import re

from .modelos import CodigoError, ErrorGestor

_IDIOMA = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?$")


def parsear_idiomas(texto: str | list | tuple | None) -> list[str]:
    """«es, en» -> ["es", "en"]. Descarta vacíos y repetidos; lanza error si hay un código raro."""
    if texto is None:
        return []
    trozos = texto.split(",") if isinstance(texto, str) else list(texto)
    salida: list[str] = []
    for t in (str(x).strip() for x in trozos):
        if not t:
            continue
        if not _IDIOMA.match(t):
            raise ErrorGestor(CodigoError.CONFIGURACION, f"Idioma de subtítulos no válido: {t!r}.",
                              solucion="Usa códigos de 2 o 3 letras separados por comas, por ejemplo: es,en")
        if t not in salida:
            salida.append(t)
    return salida


def opciones_desde_elementos(*, video: bool = True, audio: bool = False, subtitulos: bool | list = False,
                             idiomas: list[str] | None = None, portada: bool = False,
                             altura: int | str | None = None, formato_audio: str | None = None,
                             carpeta: str | None = None, editable: bool = False) -> list[dict]:
    """Devuelve 1 o 2 diccionarios de opciones (uno por descarga). Lanza ErrorGestor si no hay nada marcado."""
    langs = parsear_idiomas(idiomas or [])
    quiere_subs = bool(subtitulos)
    if quiere_subs and not langs:
        langs = ["es"]                               # marcó subtítulos pero no escribió idioma: español por defecto
    if not (video or audio or quiere_subs or portada):
        raise ErrorGestor(CodigoError.CONFIGURACION, "No hay nada marcado para descargar.",
                          solucion="Marca al menos una casilla: video, audio, subtítulos o portada.")

    def extras(con_subs: bool, con_portada: bool) -> dict:
        # Siempre se indica explícitamente: así el elegido prevalece sobre la configuración general.
        return {"subtitulos": langs if (quiere_subs and con_subs) else [], "portada": bool(portada and con_portada)}

    def con_calidad(d: dict) -> dict:
        if editable:
            d["editable"] = True
        if altura == "mejor":
            d["altura_max"] = None
        elif altura not in (None, ""):
            d["altura_max"] = int(altura)
        return d

    def con_audio(d: dict) -> dict:
        if formato_audio:
            d["formato_audio"] = formato_audio
        return d

    def con_carpeta(lista: list[dict]) -> list[dict]:
        nombre = (carpeta or "").strip()
        return [{**d, "subcarpeta": nombre} for d in lista] if nombre else lista

    if video and audio:
        return con_carpeta([con_calidad({"modo": "video", **extras(True, True)}), con_audio({"modo": "audio", **extras(False, False)})])
    if video:
        return con_carpeta([con_calidad({"modo": "video", **extras(True, True)})])
    if audio:
        return con_carpeta([con_audio({"modo": "audio", **extras(True, True)})])
    if quiere_subs:
        return con_carpeta([{"modo": "subtitulos", **extras(True, True)}])
    return con_carpeta([{"modo": "portada", "portada": True, "subtitulos": []}])
