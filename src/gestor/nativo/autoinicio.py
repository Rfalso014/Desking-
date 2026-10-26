"""Encender con Windows el servidor del gestor (en segundo plano), para que la página y la extensión funcionen siempre.

Escribe un valor en la clave «Run» del USUARIO actual (no pide permisos de administrador) y se puede quitar
desde la misma casilla de Configuración.
"""
import sys

from ..config import EMPAQUETADO, RAIZ_PROYECTO

CLAVE = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE = "GestorDescargas"


def comando() -> str:
    if EMPAQUETADO:
        return f'"{RAIZ_PROYECTO / "GestorDescargas.exe"}" --servidor'
    pythonw = RAIZ_PROYECTO / ".venv" / "Scripts" / "pythonw.exe"
    # Desde el código, `gestor` está en src: se arranca con el script de entrada, que lo añade al camino de búsqueda.
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{RAIZ_PROYECTO / "scripts" / "entrada_app.py"}" --servidor'


def activo(*, clave: str = CLAVE) -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave) as k:
            winreg.QueryValueEx(k, NOMBRE)
            return True
    except OSError:
        return False


def fijar(encender: bool, *, clave: str = CLAVE) -> None:
    if sys.platform != "win32":
        return
    import winreg
    if encender:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, clave) as k:
            winreg.SetValueEx(k, NOMBRE, 0, winreg.REG_SZ, comando())
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, clave, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, NOMBRE)
        except OSError:
            pass
