"""Comprobar si hay una versión nueva publicada en GitHub (Releases).

Solo consulta. La descarga e instalación las hace `actualizador.py`, y solo cuando la persona pulsa
«Actualizar aplicación y extensión».
"""
import json
import re
import urllib.request

from . import __version__

REPOSITORIO = "Rfalso014/Desking-"
URL_API = f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"
URL_RELEASES = f"https://github.com/{REPOSITORIO}/releases"


def comparar_versiones(a: str, b: str) -> int:
    """-1 si a < b, 0 si son iguales, 1 si a > b. Acepta «v1.2.3» y partes de distinto largo."""
    def partes(v: str) -> tuple[int, ...]:
        numeros = [int(n) for n in re.findall(r"\d+", v.split("-")[0])]
        while numeros and numeros[-1] == 0:
            numeros.pop()
        return tuple(numeros)
    pa, pb = partes(a), partes(b)
    return (pa > pb) - (pa < pb)


def interpretar_release(datos: dict, actual: str = __version__) -> dict:
    """Convierte la respuesta de la API de GitHub en lo que necesita la interfaz."""
    etiqueta = str(datos.get("tag_name") or "")
    return {"version": etiqueta.lstrip("vV"),
            "nueva": bool(etiqueta) and comparar_versiones(etiqueta, actual) > 0,
            "url": datos.get("html_url") or URL_RELEASES,
            "notas": str(datos.get("body") or "")[:2000],
            "instalador": _instalador(datos.get("assets") or [])}


def _instalador(assets: list) -> dict | None:
    """El .exe del instalador y su SHA-256 (GitHub lo publica en «digest»). Sin huella no se usa."""
    for a in assets:
        nombre, digest = str(a.get("name", "")), str(a.get("digest") or "")
        if re.fullmatch(r"GestorDescargas-[\w.]+-instalador\.exe", nombre) and digest.startswith("sha256:"):
            return {"nombre": nombre, "url": a.get("browser_download_url"), "sha256": digest[7:], "tamano": a.get("size")}
    return None


def buscar(timeout: float = 8.0) -> dict:
    """Consulta el último release. Lanza OSError/ValueError si no hay conexión o la respuesta no sirve."""
    pedido = urllib.request.Request(URL_API, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"GestorDescargas/{__version__}"})
    with urllib.request.urlopen(pedido, timeout=timeout) as r:
        return interpretar_release(json.loads(r.read(200_000)))
