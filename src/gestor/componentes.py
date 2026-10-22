"""Componentes que se actualizan sin reinstalar la aplicación (yt-dlp y su solucionador de JavaScript).

yt-dlp deja de funcionar cuando los sitios cambian, así que es lo que más a menudo hay que actualizar.
  - Versión con Python (desarrollo): se actualiza el entorno con pip.
  - Versión empaquetada (.exe): lo que va dentro no se puede tocar. Se descarga la «rueda» oficial de PyPI,
    se comprueba su SHA-256 y se descomprime en ~/.gestor-descargas/componentes; al arrancar, esa carpeta va
    primero en sys.path (`activar`). Si algo sale mal basta con borrar la carpeta: vuelve la versión incluida.

Este módulo NO importa yt_dlp: `activar` se ejecuta antes de que se cargue.
"""
import hashlib
import importlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from .modelos import CodigoError, ErrorGestor
from .nativo.comun import carpeta_datos

EMPAQUETADO = bool(getattr(sys, "frozen", False))
PAQUETES_EMPAQUETADO = ("yt-dlp", "yt-dlp-ejs")                        # solo Python puro: sirven en cualquier equipo
PAQUETES_DESARROLLO = ("yt-dlp", "yt-dlp-ejs", "gallery-dl", "deno")
_PIP = {"yt-dlp": "yt-dlp[default]"}                                     # con sus extras (incluye yt-dlp-ejs)
_MODULO_VERSION = {"yt-dlp": "yt_dlp.version", "yt-dlp-ejs": "yt_dlp_ejs", "gallery-dl": "gallery_dl.version"}
HOSTS_PYPI = frozenset({"pypi.org", "files.pythonhosted.org"})
_NOMBRE_DIR = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LeerJson = Callable[[str], dict]


def carpeta() -> Path:
    return carpeta_datos() / "componentes"


def _ruta_activos() -> Path:
    return carpeta() / "activos.json"


def _leer_activos() -> dict:
    try:
        datos = json.loads(_ruta_activos().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in datos.items()
            if isinstance(v, dict) and isinstance(v.get("dir"), str) and _NOMBRE_DIR.match(v["dir"])}


def _guardar_activos(activos: dict) -> None:
    carpeta().mkdir(parents=True, exist_ok=True)
    _ruta_activos().write_text(json.dumps(activos, indent=2), encoding="utf-8")


def activar(ruta: list[str] = sys.path) -> list[str]:
    """Pone primero en `ruta` (sys.path) los componentes descargados. Devuelve las carpetas añadidas."""
    añadidas = []
    for datos in _leer_activos().values():
        d = carpeta() / datos["dir"]
        if d.is_dir() and str(d) not in ruta:
            ruta.insert(0, str(d))
            añadidas.append(str(d))
    return añadidas


def version_instalada(paquete: str) -> str | None:
    if EMPAQUETADO and paquete in _leer_activos():
        return _leer_activos()[paquete].get("version")
    try:
        return importlib.metadata.version(paquete)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:      # el .exe no siempre lleva los metadatos: se lee del propio módulo
        return getattr(importlib.import_module(_MODULO_VERSION[paquete]), "__version__", None)
    except (KeyError, ImportError):
        return None


def paquetes() -> tuple[str, ...]:
    if EMPAQUETADO:
        return PAQUETES_EMPAQUETADO
    return tuple(p for p in PAQUETES_DESARROLLO if version_instalada(p))   # Deno es opcional


def leer_json(url: str, timeout: float = 15.0) -> dict:
    _exigir_host(url, HOSTS_PYPI | {"api.github.com"})
    pedido = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GestorDescargas"})
    with urllib.request.urlopen(pedido, timeout=timeout) as r:
        return json.loads(r.read(5_000_000))


def ultima_pypi(paquete: str, leer: LeerJson = leer_json) -> dict:
    """Última versión publicada en PyPI y su rueda «py3-none-any» (url + SHA-256), si la hay."""
    d = leer(f"https://pypi.org/pypi/{paquete}/json")
    rueda = next((f for f in d.get("urls") or [] if f.get("packagetype") == "bdist_wheel"
                  and str(f.get("filename", "")).endswith("-py3-none-any.whl")), None)
    return {"version": str(d["info"]["version"]),
            "url": rueda and rueda.get("url"), "sha256": rueda and (rueda.get("digests") or {}).get("sha256"),
            "tamano": rueda and rueda.get("size")}


def _exigir_host(url: str, hosts: frozenset[str] | set[str]) -> None:
    p = urlsplit(url)
    if p.scheme != "https" or (p.hostname or "") not in hosts:
        raise ErrorGestor(CodigoError.CONFIGURACION, "Dirección de descarga no permitida.",
                          causa=f"Solo se descarga por https desde: {', '.join(sorted(hosts))}.")


def descargar_verificado(url: str, sha256: str, destino: Path, *, hosts: frozenset[str] = HOSTS_PYPI,
                         maximo: int = 80 * 1024 * 1024, timeout: float = 60.0) -> Path:
    """Descarga `url` en `destino` y comprueba su SHA-256. Si no coincide, lo borra y lanza ErrorGestor."""
    _exigir_host(url, hosts)
    if not (isinstance(sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha256)):
        raise ErrorGestor(CodigoError.CONFIGURACION, "La descarga no trae una huella SHA-256 para verificarla.")
    h, total = hashlib.sha256(), 0
    pedido = urllib.request.Request(url, headers={"User-Agent": "GestorDescargas"})
    with urllib.request.urlopen(pedido, timeout=timeout) as r, open(destino, "wb") as f:
        while bloque := r.read(1024 * 256):
            total += len(bloque)
            if total > maximo:
                break
            h.update(bloque)
            f.write(bloque)
    if total > maximo or h.hexdigest() != sha256.lower():
        destino.unlink(missing_ok=True)
        raise ErrorGestor(CodigoError.CONFIGURACION, "El archivo descargado no es el esperado.",
                          causa="Su huella SHA-256 no coincide con la publicada (o es demasiado grande).",
                          solucion="Reintenta más tarde; no se instaló nada.")
    return destino


Descargar = Callable[..., Path]


def instalar_rueda(paquete: str, info: dict, descargar: Descargar = descargar_verificado) -> str:
    """Descarga y descomprime la rueda de `info` (de `ultima_pypi`) y la deja activa. Devuelve la versión."""
    if not info.get("url"):
        raise ErrorGestor(CodigoError.CONFIGURACION, f"{paquete} no publica una versión instalable sin Python.")
    nombre = f"{paquete}-{info['version']}"
    if not _NOMBRE_DIR.match(nombre):
        raise ErrorGestor(CodigoError.CONFIGURACION, "Versión con un nombre no válido.")
    base = carpeta()
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        rueda = descargar(info["url"], info["sha256"], Path(tmp) / "rueda.whl")
        salida = Path(tmp) / "x"
        with zipfile.ZipFile(rueda) as z:
            for m in z.namelist():         # «zip slip»: nada fuera de la carpeta de destino
                if m.startswith(("/", "\\")) or ".." in Path(m).parts or ":" in m:
                    raise ErrorGestor(CodigoError.CONFIGURACION, "La rueda descargada contiene rutas no válidas.")
            z.extractall(salida)
        final = base / nombre
        if final.exists():
            shutil.rmtree(final)
        salida.replace(final)
    activos = _leer_activos()
    viejo = activos.get(paquete)
    activos[paquete] = {"version": info["version"], "dir": nombre}
    _guardar_activos(activos)
    if viejo and viejo["dir"] != nombre:
        shutil.rmtree(base / viejo["dir"], ignore_errors=True)
    return info["version"]


def comando_pip(lista: tuple[str, ...]) -> list[str]:
    """pip del mismo entorno (python.exe, no pythonw.exe, para que pip pueda escribir su salida)."""
    py = Path(sys.executable)
    consola = py.with_name("python.exe")
    return [str(consola if consola.exists() else py), "-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
            *(_PIP.get(p, p) for p in lista)]


def actualizar_con_pip(lista: tuple[str, ...], ejecutar=subprocess.run) -> None:
    r = ejecutar(comando_pip(lista), capture_output=True, text=True, timeout=600, creationflags=_SIN_VENTANA)
    if r.returncode != 0:
        raise ErrorGestor(CodigoError.CONFIGURACION, "pip no pudo actualizar las librerías.",
                          solucion="Revisa tu conexión y reintenta.", detalle_tecnico=(r.stderr or r.stdout or "")[-500:])
