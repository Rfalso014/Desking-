"""Reglas y excepciones: qué opciones se aplican a cada tarea, y POR QUÉ.

Orden de precedencia (el último gana):
    1. Preferencias globales
    2. Reglas activas que coinciden, de menor a mayor prioridad
    3. Elecciones del usuario para esa tarea concreta (las excepciones)

`resolver` devuelve además una explicación campo por campo, para que el
usuario pueda entender qué regla decidió cada cosa.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .config import PERFILES_VELOCIDAD, Preferencias
from .catalogo import CAMPOS_ACCION
from .descargador import OpcionesDescarga
from .modelos import CodigoError, ErrorGestor

CAMPOS_CONDICION = ("dominio", "url_contiene", "sitio")


def validar_regla(regla: dict) -> None:
    def malo(msg): return ErrorGestor(CodigoError.CONFIGURACION, msg, solucion="Corrige la regla.")
    if not isinstance(regla.get("nombre"), str) or not regla["nombre"].strip():
        raise malo("La regla necesita un nombre.")
    cond, acc = regla.get("condicion", {}), regla.get("accion", {})
    if not isinstance(cond, dict) or not cond:
        raise malo("La regla necesita al menos una condición (dominio, texto en la URL o sitio).")
    for k, v in cond.items():
        if k not in CAMPOS_CONDICION or not isinstance(v, str) or not v.strip():
            raise malo(f"Condición no válida: {k!r}.")
    if not isinstance(acc, dict) or not acc:
        raise malo("La regla necesita al menos una acción.")
    for k, v in acc.items():
        if k not in CAMPOS_ACCION:
            raise malo(f"Acción desconocida: {k!r}.")
        if not CAMPOS_ACCION[k](v):
            raise malo(f"Valor no válido para {k!r}: {v!r}.")
    if not isinstance(regla.get("prioridad", 0), int):
        raise malo("La prioridad debe ser un número entero.")


def coincide(regla: dict, url: str, sitio: str | None) -> bool:
    """Todas las condiciones de la regla deben cumplirse (Y lógico)."""
    host = (urlsplit(url).hostname or "").lower()
    for k, v in regla["condicion"].items():
        v = v.strip().lower()
        if k == "dominio":
            d = v.lstrip(".")
            if not (host == d or host.endswith("." + d)):
                return False
        elif k == "url_contiene":
            if v not in url.lower():
                return False
        elif k == "sitio":
            if v != (sitio or "").lower():
                return False
    return True


@dataclass
class Resolucion:
    campos: dict
    subcarpeta: str | None
    excluir: bool
    explicacion: dict[str, str] = field(default_factory=dict)   # campo -> origen
    reglas_aplicadas: list[str] = field(default_factory=list)

    def a_opciones(self, prefs: Preferencias, ffmpeg_dir: Path | None, deno: Path | None = None) -> OpcionesDescarga:
        c = self.campos
        fragmentos, trozo = PERFILES_VELOCIDAD.get(prefs.velocidad, PERFILES_VELOCIDAD["rapida"])
        return OpcionesDescarga(
            modo=c["modo"], altura_max=c["altura_max"], contenedor_video=c["contenedor_video"],
            formato_audio=c["formato_audio"], subtitulos=tuple(c["subtitulos"]), portada=c["portada"],
            plantilla_nombre=prefs.plantilla_nombre, ffmpeg_dir=ffmpeg_dir,
            fragmentos=fragmentos, trozo_http=trozo, deno=deno)

    def texto(self) -> list[str]:
        return [f"{k} = {self.campos.get(k)!r}  (origen: {o})" for k, o in self.explicacion.items()]


def resolver(url: str, sitio: str | None, reglas: list[dict], prefs: Preferencias,
             elecciones_tarea: dict | None = None) -> Resolucion:
    campos = {
        "modo": "video", "altura_max": prefs.altura_max, "contenedor_video": prefs.contenedor_video,
        "formato_audio": prefs.formato_audio,
        "subtitulos": list(prefs.idiomas_subtitulos) if prefs.descargar_subtitulos else [],
        "portada": prefs.descargar_portada, "subcarpeta": None, "excluir": False,
    }
    origen = {k: "preferencias globales" for k in campos}
    aplicadas: list[str] = []

    activas = [r for r in reglas if r.get("activa", True) and coincide(r, url, sitio)]
    for r in sorted(activas, key=lambda r: (r.get("prioridad", 0), r.get("id") or 0)):
        aplicadas.append(r["nombre"])
        for k, v in r["accion"].items():
            campos[k] = v
            origen[k] = f"regla «{r['nombre']}»"

    for k, v in (elecciones_tarea or {}).items():
        if k not in CAMPOS_ACCION or not CAMPOS_ACCION[k](v):
            raise ErrorGestor(CodigoError.CONFIGURACION, f"Elección no válida para {k!r}: {v!r}.")
        campos[k] = v
        origen[k] = "elección para esta descarga"

    # Coherencia: en modo "solo subtítulos" no se pide portada salvo que se haya elegido a propósito.
    if campos["modo"] == "subtitulos" and origen["portada"] == "preferencias globales":
        campos["portada"] = False
    if campos["modo"] == "subtitulos" and not campos["subtitulos"]:
        campos["subtitulos"] = list(prefs.idiomas_subtitulos) or ["es"]
        origen["subtitulos"] = "idioma por defecto (modo solo subtítulos)"

    return Resolucion(campos, campos["subcarpeta"], bool(campos["excluir"]), origen, aplicadas)
