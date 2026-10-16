"""Piezas compartidas por la app y el host nativo (sin dependencias pesadas)."""
import getpass
import json
import os
import re
import secrets
from pathlib import Path

NOMBRE_HOST = "com.gestor.descargas"


def carpeta_datos() -> Path:
    base = Path(os.environ.get("GESTOR_DATOS") or
                (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GestorDescargas"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def direccion_pipe() -> str:
    """Nombre de la tubería (pipe) de Windows; una por usuario."""
    if os.environ.get("GESTOR_PIPE"):
        return os.environ["GESTOR_PIPE"]
    usuario = re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())
    return rf"\\.\pipe\GestorDescargas-{usuario}"


def clave_ipc(crear: bool = False) -> bytes:
    """Secreto compartido app<->host. Solo la app lo crea; el host lo lee.

    Se guarda en la carpeta de datos del usuario (LocalAppData), que otros
    usuarios de Windows no pueden leer. Quien no tenga la clave no puede hablar
    con la aplicación aunque conozca el nombre de la tubería.
    """
    ruta = carpeta_datos() / "ipc.key"
    if not ruta.exists():
        if not crear:
            raise FileNotFoundError("La aplicación aún no ha creado la clave de comunicación.")
        ruta.write_bytes(secrets.token_bytes(32))
    return ruta.read_bytes()


def config_host() -> dict:
    """Configuración escrita por el instalador: orígenes permitidos y comando para abrir la app."""
    ruta = carpeta_datos() / "host.json"
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
