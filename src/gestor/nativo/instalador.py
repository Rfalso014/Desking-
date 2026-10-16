"""Registro (y desregistro) del host de Native Messaging en Windows.

Chrome/Edge buscan el host así:
  1. Leen la clave de registro HKCU\\Software\\<navegador>\\NativeMessagingHosts\\<nombre>
     cuyo valor por defecto es la ruta de un archivo "manifiesto" JSON.
  2. El manifiesto indica el ejecutable (`path`) y qué extensiones pueden
     usarlo (`allowed_origins`). Sin comodines: solo el ID de nuestra extensión.
Todo se escribe en HKCU (usuario actual): no hace falta ser administrador.
"""
import base64
import hashlib
import json
import sys
from pathlib import Path

from ..config import EMPAQUETADO, RAIZ_PROYECTO
from .comun import NOMBRE_HOST, carpeta_datos

BASES_REGISTRO = (r"Software\Google\Chrome\NativeMessagingHosts",
                  r"Software\Microsoft\Edge\NativeMessagingHosts")


def id_extension(manifiesto: Path | None = None) -> str:
    """Calcula el ID de Chrome a partir de la clave pública del manifest.json de la extensión."""
    ruta = manifiesto or (RAIZ_PROYECTO / "extension" / "manifest.json")
    clave = json.loads(ruta.read_text(encoding="utf-8")).get("key")
    if not clave:
        raise ValueError("El manifest.json no tiene 'key'; ejecuta scripts/generar_clave_extension.py")
    hex_ = hashlib.sha256(base64.b64decode(clave)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in hex_)


def _pythonw(python: str) -> str:
    p = Path(python)
    w = p.with_name("pythonw.exe")
    return str(w if w.exists() else p)


def instalar(extension_id: str | None = None, *, python: str | None = None, proyecto: Path | None = None,
             datos: Path | None = None, bases: tuple[str, ...] = BASES_REGISTRO) -> dict:
    """Escribe lanzador, manifiesto, configuración y claves de registro. Devuelve lo creado."""
    import winreg
    python = python or sys.executable
    proyecto = proyecto or RAIZ_PROYECTO
    carpeta = (datos or carpeta_datos()) / "nativo"
    carpeta.mkdir(parents=True, exist_ok=True)
    ext_id = extension_id or id_extension()
    origen = f"chrome-extension://{ext_id}/"

    if EMPAQUETADO:      # versión instalada: el host es un .exe junto a la app
        lanzador = proyecto / "GestorHost.exe"
        comando_app = [str(proyecto / "GestorDescargas.exe")]
    else:
        lanzador = carpeta / "host.bat"
        # PYTHONPATH apunta al código; los argumentos del navegador (%*) se pasan al host.
        lanzador.write_text(f'@echo off\r\nset "PYTHONPATH={proyecto / "src"}"\r\n"{python}" -m gestor.nativo.host %*\r\n',
                            encoding="utf-8")
        comando_app = [_pythonw(python), "-m", "gestor.app"]
    manifiesto = carpeta / f"{NOMBRE_HOST}.json"
    manifiesto.write_text(json.dumps({
        "name": NOMBRE_HOST,
        "description": "Gestor de Descargas: puente entre la extensión y la aplicación de escritorio",
        "path": str(lanzador), "type": "stdio", "allowed_origins": [origen]}, indent=2), encoding="utf-8")
    (datos or carpeta_datos()).joinpath("host.json").write_text(json.dumps({
        "origenes_permitidos": [origen],
        "comando_app": comando_app}, indent=2), encoding="utf-8")

    for base in bases:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST}") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifiesto))
    return {"extension_id": ext_id, "manifiesto": manifiesto, "lanzador": lanzador, "bases": bases}


def desinstalar(*, datos: Path | None = None, bases: tuple[str, ...] = BASES_REGISTRO) -> None:
    import winreg
    for base in bases:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST}")
        except FileNotFoundError:
            pass
    raiz = datos or carpeta_datos()
    for ruta in ((raiz / "nativo").glob("*") if (raiz / "nativo").exists() else []):
        ruta.unlink()
    for ruta in (raiz / "nativo", raiz / "host.json"):
        if ruta.is_dir():
            ruta.rmdir()
        elif ruta.exists():
            ruta.unlink()


def estado(*, bases: tuple[str, ...] = BASES_REGISTRO) -> dict[str, str | None]:
    """Para diagnóstico: ruta del manifiesto registrada en cada navegador (o None)."""
    import winreg
    salida: dict[str, str | None] = {}
    for base in bases:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST}") as k:
                salida[base] = winreg.QueryValueEx(k, "")[0]
        except FileNotFoundError:
            salida[base] = None
    return salida
