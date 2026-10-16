"""Punto de entrada de la aplicación de escritorio.

    python -m gestor.app            (abre la ventana)
    pythonw -m gestor.app           (sin consola; lo usa el host nativo para abrirla)
"""
import sys

from .cola import GestorCola
from .config import carpeta_datos, localizar_ffmpeg
from .db import BaseDatos
from .ipc import ServidorIPC
from .vinculacion import Vinculacion


def crear_nucleo(ruta_db=None) -> tuple[BaseDatos, GestorCola]:
    db = BaseDatos(ruta_db or carpeta_datos() / "gestor.db")
    cola = GestorCola(db, ffmpeg_dir=localizar_ffmpeg())
    return db, cola


def _comandos_instalacion() -> int | None:
    """Opciones de línea de comandos para registrar/quitar la conexión con el navegador."""
    from .nativo import instalador
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--instalar-host":
        r = instalador.instalar()
        print("Conexión instalada. ID de la extensión:", r["extension_id"])
    elif arg == "--desinstalar-host":
        instalador.desinstalar()
        print("Conexión desinstalada.")
    elif arg == "--estado-host":
        for base, ruta in instalador.estado().items():
            print(f"{base}: {ruta or 'NO registrado'}")
    else:
        return None
    return 0


def main() -> int:
    codigo_cli = _comandos_instalacion()
    if codigo_cli is not None:
        return codigo_cli
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .ui.ventana import VentanaPrincipal

    app = QApplication(sys.argv)
    app.setStyle("Fusion")        # base uniforme sobre la que se aplica nuestro tema
    app.setApplicationName("Gestor de Descargas")
    db, cola = crear_nucleo()
    try:
        vinculacion = Vinculacion(db)
        ipc = ServidorIPC(cola, vinculacion=vinculacion)       # falla si ya hay otra copia abierta (la tubería está ocupada)
    except OSError:
        QMessageBox.information(None, "Gestor de Descargas", "La aplicación ya está abierta.")
        return 0
    ipc.iniciar()
    cola.iniciar()
    cola.recuperar()
    cola.limpiar_temporales()
    ventana = VentanaPrincipal(cola, vinculacion)
    ventana.show()
    codigo = app.exec()
    ipc.detener()
    cola.detener()
    db.cerrar()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
