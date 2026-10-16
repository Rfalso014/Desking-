"""Punto de entrada de la aplicación de escritorio.

    python -m gestor.app            (abre la ventana)
    pythonw -m gestor.app           (sin consola; lo usa el host nativo para abrirla)
"""
import sys

from .cola import GestorCola
from .config import carpeta_datos, localizar_ffmpeg
from .db import BaseDatos
from .ipc import ServidorIPC


def crear_nucleo(ruta_db=None) -> tuple[BaseDatos, GestorCola]:
    db = BaseDatos(ruta_db or carpeta_datos() / "gestor.db")
    cola = GestorCola(db, ffmpeg_dir=localizar_ffmpeg())
    return db, cola


def main() -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .ui.ventana import VentanaPrincipal

    app = QApplication(sys.argv)
    app.setApplicationName("Gestor de Descargas")
    db, cola = crear_nucleo()
    try:
        ipc = ServidorIPC(cola)       # falla si ya hay otra copia abierta (la tubería está ocupada)
    except OSError:
        QMessageBox.information(None, "Gestor de Descargas", "La aplicación ya está abierta.")
        return 0
    ipc.iniciar()
    cola.iniciar()
    cola.recuperar()
    cola.limpiar_temporales()
    ventana = VentanaPrincipal(cola)
    ventana.show()
    codigo = app.exec()
    ipc.detener()
    cola.detener()
    db.cerrar()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
