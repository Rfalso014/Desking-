"""Punto de entrada de la aplicación de escritorio.

    python -m gestor.app            (abre la ventana)
    pythonw -m gestor.app           (sin consola; lo usa el host nativo para abrirla)
"""
import sys
import time

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
    elif arg == "--limpiar-sistema":     # lo usa el desinstalador: quita todo lo que la app escribió en el registro
        from .nativo import autoinicio
        instalador.desinstalar()
        if autoinicio.activo():          # solo abre «Run» para escribir si de verdad hay algo que quitar
            autoinicio.fijar(False)
        print("Conexión con el navegador e inicio con Windows quitados.")
    elif arg == "--version":
        from . import __version__
        print(__version__)
    else:
        return None
    return 0


def _pedir_mostrar() -> bool:
    """Hay otra copia en marcha (quizá oculta en la bandeja): le pide que muestre su ventana."""
    import json
    from multiprocessing.connection import Client
    from .nativo.comun import clave_ipc, direccion_pipe
    try:
        con = Client(direccion_pipe(), family="AF_PIPE", authkey=clave_ipc())
        with con:
            con.send_bytes(json.dumps({"v": 1, "id": "mostrar", "accion": "mostrar", "datos": {}}).encode())
            con.recv_bytes()
        return True
    except Exception:
        return False


def main() -> int:
    codigo_cli = _comandos_instalacion()
    if codigo_cli is not None:
        return codigo_cli
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QAction, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QStyle
    from .config import RAIZ_PROYECTO
    from .ui.ventana import VentanaPrincipal

    segundo_plano = "--segundo-plano" in sys.argv
    app = QApplication(sys.argv)
    app.setStyle("Fusion")        # base uniforme sobre la que se aplica nuestro tema
    app.setApplicationName("Gestor de Descargas")
    from . import __version__
    app.setApplicationVersion(__version__)
    db, cola = crear_nucleo()
    vinculacion = Vinculacion(db)
    # Tras «Actualizar» la copia anterior tarda un momento en cerrarse: se espera a que libere la tubería.
    intentos = 40 if "--reiniciado" in sys.argv else 1
    for i in range(intentos):
        try:
            ipc = ServidorIPC(cola, vinculacion=vinculacion)   # falla si ya hay otra copia abierta (la tubería está ocupada)
            break
        except OSError:
            if i + 1 < intentos:
                time.sleep(0.5)
                continue
            if not segundo_plano and not _pedir_mostrar():
                QMessageBox.information(None, "Gestor de Descargas", "La aplicación ya está abierta.")
            db.cerrar()
            return 0
    from .actualizador import ARGS_INSTALADOR, Actualizador, comando_reinicio, lanzar_desacoplado
    from .modelos import ESTADOS_ACTIVOS
    actualizador = Actualizador(hay_descargas=lambda: bool(cola.listar(estados=list(ESTADOS_ACTIVOS), limite=1)),
                                automatico=lambda: db.cargar_preferencias().actualizar_solo)
    ipc.manejador.actualizador = actualizador        # antes de atender a la extensión
    ipc.iniciar()
    cola.iniciar()
    cola.recuperar()
    cola.limpiar_temporales()
    ventana = VentanaPrincipal(cola, vinculacion, actualizador)

    class _Aviso(QObject):               # el IPC corre en otro hilo; Qt exige tocar la ventana desde el principal
        mostrar = Signal()
        reiniciar = Signal()
        instalar = Signal(str)
    aviso = _Aviso()
    aviso.mostrar.connect(ventana.mostrar_al_frente)
    ipc.manejador.al_mostrar = aviso.mostrar.emit

    def _cerrar_para_actualizar(cmd: list[str]) -> None:
        lanzar_desacoplado(cmd)
        ventana.saliendo = True
        app.quit()
    aviso.reiniciar.connect(lambda: _cerrar_para_actualizar(comando_reinicio(ventana.isVisible())))
    aviso.instalar.connect(lambda ruta: _cerrar_para_actualizar([ruta, *ARGS_INSTALADOR]))   # el instalador vuelve a abrir la app
    actualizador.al_reiniciar = aviso.reiniciar.emit
    actualizador.al_instalar = lambda ruta: aviso.instalar.emit(str(ruta))
    actualizador.al_abrir_url = lambda url: __import__("webbrowser").open(url)
    actualizador.iniciar_vigilancia()           # busca cada 6 h y, si está activado, se actualiza sola

    bandeja = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        app.setQuitOnLastWindowClosed(False)           # cerrar la ventana no detiene las descargas
        ruta_icono = RAIZ_PROYECTO / "extension" / "icons" / "128.png"
        icono = QIcon(str(ruta_icono)) if ruta_icono.exists() else app.style().standardIcon(QStyle.SP_ArrowDown)
        bandeja = QSystemTrayIcon(icono, app)
        bandeja.setToolTip("Gestor de Descargas")
        menu = QMenu()
        abrir = QAction("Abrir Gestor de Descargas", menu); abrir.triggered.connect(ventana.mostrar_al_frente)
        salir = QAction("Salir (detiene las descargas)", menu)

        def _salir() -> None:
            ventana.saliendo = True
            app.quit()
        salir.triggered.connect(_salir)
        menu.addAction(abrir); menu.addSeparator(); menu.addAction(salir)
        bandeja.setContextMenu(menu)
        bandeja.activated.connect(lambda r: ventana.mostrar_al_frente() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        bandeja.show()
        hechos = actualizador.aviso_tras_reinicio()
        if hechos:                                  # volvió a abrirse tras actualizarse sola: se avisa una vez
            bandeja.showMessage("Gestor de Descargas se actualizó", "\n".join(hechos[:4]) or "Ya tienes la última versión.")
        ventana.ocultar_al_cerrar = True
    if not (segundo_plano and bandeja):
        ventana.show()
    codigo = app.exec()
    ipc.detener()
    cola.detener()
    db.cerrar()
    return codigo


if __name__ == "__main__":
    sys.exit(main())
