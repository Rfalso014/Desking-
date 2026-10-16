"""Descarga de imágenes: enlaces directos (HTTPX + Pillow) y galerías (gallery-dl).

Seguridad:
  - Cada redirección se vuelve a validar (un sitio no puede mandarnos a localhost).
  - Límite de tamaño mientras se descarga (no confiamos en Content-Length).
  - Pillow verifica que el archivo SÍ es una imagen y decide la extensión real.
  - gallery-dl se ejecuta como proceso aparte con lista de argumentos (sin shell).
"""
import io
import re
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from .modelos import CodigoError, ErrorGestor
from .validacion import validar_url

MAX_BYTES = 50 * 1024 * 1024
MAX_REDIRECCIONES = 5
_FORMATO_A_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp", "TIFF": ".tif"}


def _nombre_seguro(url: str) -> str:
    base = unquote(Path(urlsplit(url).path).stem) or "imagen"
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip(" .")[:100]
    return base or "imagen"


def _error(msg: str, causa: str | None = None) -> ErrorGestor:
    return ErrorGestor(CodigoError.PROCESAMIENTO, msg, causa=causa)


def descargar_imagen(url: str, carpeta: Path, *, permitir_interno: bool = False,
                     max_bytes: int = MAX_BYTES, cliente: httpx.Client | None = None) -> Path:
    """Descarga una imagen a `carpeta` y devuelve su ruta. Nunca sobrescribe."""
    url = validar_url(url, permitir_interno=permitir_interno)
    carpeta.mkdir(parents=True, exist_ok=True)
    propio = cliente is None
    cliente = cliente or httpx.Client(timeout=20.0, follow_redirects=False)
    try:
        datos = bytearray()
        actual = url
        for _ in range(MAX_REDIRECCIONES + 1):
            with cliente.stream("GET", actual) as r:
                if r.is_redirect:
                    actual = validar_url(urljoin(actual, r.headers.get("location", "")),
                                         permitir_interno=permitir_interno)
                    continue
                if r.status_code >= 400:
                    raise ErrorGestor(CodigoError.CONTENIDO_NO_DISPONIBLE, "No se pudo descargar la imagen.",
                                      causa=f"El sitio respondió con el código {r.status_code}.",
                                      solucion="Comprueba que el enlace abre en tu navegador.")
                tipo = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not tipo.startswith("image/"):
                    raise _error("El enlace no es una imagen.", f"Tipo de contenido recibido: {tipo or 'desconocido'}.")
                for trozo in r.iter_bytes():
                    datos += trozo
                    if len(datos) > max_bytes:
                        raise _error("La imagen supera el tamaño máximo permitido.",
                                     f"Límite: {max_bytes // 1_048_576} MB.")
                break
        else:
            raise _error("Demasiadas redirecciones.")
    except httpx.HTTPError as exc:
        raise ErrorGestor(CodigoError.CONEXION, "No se pudo conectar con el sitio.",
                          causa="Falla de red, o el sitio no responde.",
                          solucion="Revisa tu conexión y reintenta.", detalle_tecnico=str(exc)) from exc
    finally:
        if propio:
            cliente.close()

    try:
        with Image.open(io.BytesIO(datos)) as img:
            img.verify()                       # comprueba que no esté corrupta
            ext = _FORMATO_A_EXT.get(img.format or "")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise _error("El archivo descargado no es una imagen válida.", None) from exc
    if ext is None:
        raise _error("Formato de imagen no admitido.")

    destino = carpeta / (_nombre_seguro(url) + ext)
    n = 1
    while destino.exists():                    # no sobrescribir: añade -2, -3...
        n += 1
        destino = carpeta / f"{_nombre_seguro(url)}-{n}{ext}"
    destino.write_bytes(bytes(datos))
    return destino


def construir_comando_galeria(url: str, carpeta: Path) -> list[str]:
    """Lista de argumentos para gallery-dl (nunca un texto de shell)."""
    url = validar_url(url, permitir_interno=True)   # solo esquema y formato; el host lo valida quien llama
    return [sys.executable, "-m", "gallery_dl", "--quiet", "--directory", str(carpeta),
            "--filename", "{filename}.{extension}", url]


def descargar_galeria(url: str, carpeta: Path, *, cancelar: threading.Event | None = None,
                      permitir_interno: bool = False, timeout: float = 600) -> list[Path]:
    """Descarga una galería con gallery-dl. Devuelve los archivos nuevos."""
    validar_url(url, permitir_interno=permitir_interno)
    carpeta.mkdir(parents=True, exist_ok=True)
    antes = {p for p in carpeta.rglob("*") if p.is_file()}
    proc = subprocess.Popen(construir_comando_galeria(url, carpeta), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        espera = 0.0
        while True:
            try:
                _, err = proc.communicate(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                espera += 0.5
                if (cancelar is not None and cancelar.is_set()) or espera > timeout:
                    proc.terminate()
                    proc.wait(timeout=10)
                    raise ErrorGestor(CodigoError.CANCELADO if cancelar and cancelar.is_set()
                                      else CodigoError.CONEXION, "La descarga de la galería se detuvo.")
    finally:
        if proc.poll() is None:
            proc.kill()
    nuevos = sorted(p for p in carpeta.rglob("*") if p.is_file() and p not in antes)
    if proc.returncode != 0 and not nuevos:
        raise ErrorGestor(CodigoError.SITIO_NO_COMPATIBLE, "No se pudo descargar la galería.",
                          causa="gallery-dl no reconoce el sitio o no encontró imágenes.",
                          solucion="Comprueba que el sitio es compatible con gallery-dl.",
                          detalle_tecnico=(err or "")[-500:])
    return nuevos
