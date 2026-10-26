"""Piezas del sistema compartidas (sin dependencias pesadas): carpeta de datos y limpieza de la versión anterior."""
import os
from pathlib import Path

# Hasta la versión 1.x la extensión hablaba con una aplicación de escritorio por Native Messaging.
NOMBRE_HOST_ANTIGUO = "com.gestor.descargas"
BASES_REGISTRO_ANTIGUAS = (r"Software\Google\Chrome\NativeMessagingHosts", r"Software\Microsoft\Edge\NativeMessagingHosts")


def carpeta_datos() -> Path:
    # OJO: no usar %LOCALAPPDATA%. El Python de la Microsoft Store redirige lo que se escribe allí a una
    # carpeta oculta, y otros programas no verían los archivos.
    base = Path(os.environ.get("GESTOR_DATOS") or (Path.home() / ".gestor-descargas"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def quitar_puente_antiguo(*, datos: Path | None = None, bases: tuple[str, ...] = BASES_REGISTRO_ANTIGUAS) -> bool:
    """Quita lo que registró la versión de escritorio (host de Native Messaging). Devuelve True si había algo."""
    import winreg
    habia = False
    for base in bases:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST_ANTIGUO}")
            habia = True
        except OSError:
            pass
    raiz = datos or carpeta_datos()
    nativo = sorted((raiz / "nativo").glob("*")) if (raiz / "nativo").is_dir() else []
    # Cada cosa por separado: si una está en uso (p. ej. el navegador tiene abierta la carpeta), se sigue con las
    # demás y se reintenta en el próximo encendido.
    for ruta in (*nativo, raiz / "nativo", raiz / "host.json", raiz / "host.log", raiz / "ipc.key"):
        try:
            if ruta.is_dir():
                ruta.rmdir()
                habia = True
            elif ruta.exists():
                ruta.unlink()
                habia = True
        except OSError:
            pass
    return habia
