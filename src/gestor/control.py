"""Encender, apagar y reiniciar el gestor web desde este equipo, y su panel de control.

    GestorDescargas.exe                 abre el panel (Encender / Apagar / Reiniciar / Abrir la página)
    GestorDescargas.exe --encender      enciende el servidor en segundo plano (si ya está encendido, no hace nada)
    GestorDescargas.exe --apagar        lo apaga (las descargas en curso se retoman al volver a encender)
    GestorDescargas.exe --reiniciar     lo apaga y lo vuelve a encender
    GestorDescargas.exe --abrir         lo enciende si hace falta y abre la página en el navegador
    GestorDescargas.exe --servidor      ES el servidor (lo usan --encender y el inicio con Windows)

Desde el código: `python -m gestor.control [opción]` (con `src` en el PYTHONPATH).
El servidor deja en `servidor.json` (carpeta de datos del usuario) su puerto, su proceso y el token local; solo el
usuario de Windows puede leer esa carpeta, así que solo él (y la página que abre) puede apagarlo.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .config import EMPAQUETADO, carpeta_datos

PUERTO = int(os.environ.get("GESTOR_PUERTO") or 7878)
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def archivo_estado() -> Path:
    return carpeta_datos() / "servidor.json"


def leer_estado() -> dict:
    try:
        return json.loads(archivo_estado().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def url_pagina(puerto: int | None = None) -> str:
    return f"http://127.0.0.1:{puerto or leer_estado().get('puerto') or PUERTO}/"


def encendido(puerto: int | None = None, espera: float = 1.5) -> bool:
    """¿Responde el gestor en ese puerto? (y es el nuestro, no otro programa)."""
    try:
        with urllib.request.urlopen(f"{url_pagina(puerto)}api/salud", timeout=espera) as r:
            return json.loads(r.read().decode("utf-8")).get("app") == "gestor-descargas"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def comando_servidor(*extra: str) -> list[str]:
    if EMPAQUETADO:
        return [sys.executable, "--servidor", *extra]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else sys.executable), "-m", "gestor.control", "--servidor", *extra]


def _lanzar(cmd: list[str]) -> None:
    from .actualizador import lanzar_desacoplado
    lanzar_desacoplado(cmd)


def esperar(condicion, segundos: float) -> bool:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.3)
    return condicion()


def encender() -> bool:
    if encendido():
        return True
    _lanzar(comando_servidor())
    return esperar(encendido, 30)


def apagar() -> bool:
    """Pide al servidor que se apague; si no responde, termina su proceso."""
    est = leer_estado()
    if not encendido(est.get("puerto")):
        return True
    try:
        datos = json.dumps({"v": 1, "id": "control", "accion": "apagar", "token": est.get("token"), "datos": {}}).encode()
        req = urllib.request.Request(f"{url_pagina(est.get('puerto'))}api", data=datos,
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()
    except (OSError, urllib.error.URLError):
        pass
    if esperar(lambda: not encendido(est.get("puerto"), 0.5), 15):
        return True
    pid = est.get("pid")
    if isinstance(pid, int) and pid > 0:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=_SIN_VENTANA)
    return esperar(lambda: not encendido(est.get("puerto"), 0.5), 5)


def reiniciar() -> bool:
    return apagar() and encender()


def abrir_pagina() -> bool:
    ok = encender()
    if ok:
        webbrowser.open(url_pagina())
    return ok


# --- el servidor --------------------------------------------------------------------------------
def _registro():
    """En segundo plano no hay consola: los errores van a servidor.log (se recorta si crece mucho)."""
    ruta = carpeta_datos() / "servidor.log"
    if ruta.exists() and ruta.stat().st_size > 1_000_000:
        ruta.replace(ruta.with_suffix(".log.1"))
    return ruta.open("a", encoding="utf-8", buffering=1)


def _proceso_vivo(pid: int) -> bool:
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, creationflags=_SIN_VENTANA)
    return str(pid) in (r.stdout or "")


def ejecutar_servidor(argv: list[str]) -> int:
    log = _registro()
    if sys.stderr is None:                        # pythonw o el .exe sin consola
        sys.stderr = log
    if "--esperar" in argv:                       # reinicio: espera a que la copia anterior suelte el puerto
        try:
            pid = int(argv[argv.index("--esperar") + 1])
            esperar(lambda: not _proceso_vivo(pid), 30)
        except (ValueError, IndexError):
            pass
    if encendido(PUERTO):
        return 0                                  # ya hay uno encendido: no se duplica
    from . import __version__
    from .actualizador import ARGS_INSTALADOR, Actualizador, lanzar_desacoplado
    from .api import Manejador
    from .cola import GestorCola
    from .config import localizar_ffmpeg
    from .db import BaseDatos
    from .modelos import ESTADOS_ACTIVOS
    from .vinculacion import Vinculacion
    from .web.servidor import ServidorWeb, nuevo_token

    db = BaseDatos(carpeta_datos() / "gestor.db")
    cola = GestorCola(db, ffmpeg_dir=localizar_ffmpeg())
    manejador = Manejador(cola, Vinculacion(db), token_web=nuevo_token())
    try:
        srv = ServidorWeb(manejador, PUERTO)
    except OSError as e:
        print(time.strftime("%Y-%m-%d %H:%M:%S"), f"No se pudo usar el puerto {PUERTO}: {e}", file=log)
        db.cerrar()
        return 1
    archivo_estado().write_text(json.dumps({"puerto": srv.puerto, "pid": os.getpid(), "token": manejador.token_web,
                                            "version": __version__}), encoding="utf-8")
    try:
        from .nativo.comun import quitar_puente_antiguo
        if quitar_puente_antiguo():
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "Quitado el puente de la versión de escritorio", file=log)
    except OSError:
        pass

    def parar(despues=None):
        def trabajo():
            time.sleep(0.4)                       # deja que la respuesta llegue a la página
            if despues:
                despues()
            srv.detener()
        threading.Thread(target=trabajo, daemon=True).start()

    manejador.al_apagar = parar
    manejador.al_reiniciar = lambda: parar(lambda: lanzar_desacoplado(comando_servidor("--esperar", str(os.getpid()))))
    manejador.elegir_carpeta = elegir_carpeta_en_proceso
    actualizador = Actualizador(hay_descargas=lambda: bool(cola.listar(estados=list(ESTADOS_ACTIVOS), limite=1)),
                                automatico=lambda: db.cargar_preferencias().actualizar_solo)
    actualizador.al_reiniciar = manejador.al_reiniciar
    actualizador.al_instalar = lambda ruta: parar(lambda: lanzar_desacoplado([str(ruta), *ARGS_INSTALADOR]))
    actualizador.al_abrir_url = webbrowser.open
    manejador.actualizador = actualizador

    cola.iniciar()
    cola.recuperar()
    cola.limpiar_temporales()
    actualizador.iniciar_vigilancia()
    print(time.strftime("%Y-%m-%d %H:%M:%S"), f"Encendido en {url_pagina(srv.puerto)} (versión {__version__})", file=log)
    try:
        srv.servir()
    finally:
        cola.detener()
        db.cerrar()
        if leer_estado().get("pid") == os.getpid():
            archivo_estado().unlink(missing_ok=True)
        print(time.strftime("%Y-%m-%d %H:%M:%S"), "Apagado", file=log)
    return 0


# --- selector de carpetas (en un proceso aparte: tkinter no se puede usar desde los hilos del servidor) --------
def elegir_carpeta_en_proceso(inicial: str) -> str | None:
    salida = carpeta_datos() / f"carpeta-{os.getpid()}-{threading.get_ident()}.txt"
    salida.unlink(missing_ok=True)
    cmd = ([sys.executable] if EMPAQUETADO else [sys.executable, "-m", "gestor.control"]) + ["--elegir-carpeta", inicial, str(salida)]
    from .actualizador import entorno_app
    subprocess.run(cmd, env=entorno_app(), timeout=600, creationflags=_SIN_VENTANA)
    try:
        return salida.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
    finally:
        salida.unlink(missing_ok=True)


def _elegir_carpeta(inicial: str, salida: str) -> int:
    import tkinter as tk
    from tkinter import filedialog
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)            # que el diálogo salga delante del navegador
    elegida = filedialog.askdirectory(parent=raiz, initialdir=inicial, title="¿Dónde se guardan las descargas?")
    raiz.destroy()
    Path(salida).write_text(str(Path(elegida)) if elegida else "", encoding="utf-8")
    return 0


# --- panel de control --------------------------------------------------------------------------
def _tema_oscuro() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


# Mismos colores que la página (estatico/app.css): grafito suave en oscuro, sin negro puro ni blanco puro.
_COLORES = {
    False: {"fondo": "#f6f5f2", "tarjeta": "#ffffff", "texto": "#23262b", "tenue": "#646a73", "borde": "#e2e0da",
            "acento": "#2f7d6d", "sobre": "#ffffff", "ok": "#2f7d4f", "apagado": "#8a8f98", "boton": "#ecebe6"},
    True: {"fondo": "#1e2124", "tarjeta": "#262a2e", "texto": "#dcdad5", "tenue": "#9a9d9f", "borde": "#33383d",
           "acento": "#7fb8a8", "sobre": "#17201d", "ok": "#8cc49c", "apagado": "#7b8085", "boton": "#30353a"},
}


def panel() -> int:
    import tkinter as tk
    from tkinter import ttk
    from .nativo import autoinicio

    c = _COLORES[_tema_oscuro()]
    raiz = tk.Tk()
    raiz.title("Gestor de Descargas")
    raiz.configure(bg=c["fondo"])
    raiz.resizable(False, False)
    icono = Path(__file__).with_name("web") / "estatico" / "icono.png"
    if icono.exists():
        try:
            raiz.iconphoto(True, tk.PhotoImage(file=str(icono)))
        except tk.TclError:
            pass
    fuente = ("Segoe UI", 10)
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")
    for nombre, fondo, texto in (("Primario.TButton", c["acento"], c["sobre"]), ("TButton", c["boton"], c["texto"])):
        estilo.configure(nombre, background=fondo, foreground=texto, borderwidth=0, focusthickness=0,
                         padding=(14, 8), font=("Segoe UI Semibold", 10))
        estilo.map(nombre, background=[("disabled", c["borde"]), ("active", fondo)], foreground=[("disabled", c["tenue"])])
    estilo.configure("TCheckbutton", background=c["tarjeta"], foreground=c["texto"], font=fuente)
    estilo.map("TCheckbutton", background=[("active", c["tarjeta"])])

    marco = tk.Frame(raiz, bg=c["fondo"], padx=18, pady=16)
    marco.pack(fill="both", expand=True)
    tk.Label(marco, text="Gestor de Descargas", bg=c["fondo"], fg=c["texto"], font=("Segoe UI Semibold", 15)).pack(anchor="w")
    tk.Label(marco, text="Panel de control del servidor web", bg=c["fondo"], fg=c["tenue"], font=fuente).pack(anchor="w")

    tarjeta = tk.Frame(marco, bg=c["tarjeta"], padx=14, pady=12, highlightthickness=1, highlightbackground=c["borde"])
    tarjeta.pack(fill="x", pady=(12, 10))
    fila = tk.Frame(tarjeta, bg=c["tarjeta"])
    fila.pack(fill="x")
    punto = tk.Canvas(fila, width=12, height=12, bg=c["tarjeta"], highlightthickness=0)
    circulo = punto.create_oval(1, 1, 11, 11, fill=c["apagado"], outline="")
    punto.pack(side="left", padx=(0, 8))
    estado_txt = tk.Label(fila, text="Comprobando…", bg=c["tarjeta"], fg=c["texto"], font=("Segoe UI Semibold", 11))
    estado_txt.pack(side="left")
    direccion = tk.Label(tarjeta, text="", bg=c["tarjeta"], fg=c["tenue"], font=fuente, cursor="hand2")
    direccion.pack(anchor="w", pady=(4, 0))
    direccion.bind("<Button-1>", lambda _e: webbrowser.open(url_pagina()) if encendido() else None)

    botones = tk.Frame(marco, bg=c["fondo"])
    botones.pack(fill="x")
    b_encender = ttk.Button(botones, text="Encender", style="Primario.TButton")
    b_apagar = ttk.Button(botones, text="Apagar")
    b_reiniciar = ttk.Button(botones, text="Reiniciar")
    b_abrir = ttk.Button(botones, text="Abrir la página")
    for b in (b_encender, b_apagar, b_reiniciar):
        b.pack(side="left", padx=(0, 6))
    b_abrir.pack(side="right")

    opciones = tk.Frame(marco, bg=c["tarjeta"], padx=12, pady=8, highlightthickness=1, highlightbackground=c["borde"])
    opciones.pack(fill="x", pady=(12, 0))
    inicio = tk.BooleanVar(value=autoinicio.activo())
    ttk.Checkbutton(opciones, text="Encender con Windows (en segundo plano)", variable=inicio,
                    command=lambda: autoinicio.fijar(inicio.get())).pack(anchor="w")
    tk.Label(marco, text="Cerrar esta ventana no apaga el gestor: las descargas siguen.", bg=c["fondo"], fg=c["tenue"],
             font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 0))

    ocupado = {"v": False, "texto": ""}

    def pintar(esta: bool) -> None:
        if ocupado["v"]:
            estado_txt.config(text=ocupado["texto"])
            punto.itemconfig(circulo, fill=c["acento"])
        else:
            estado_txt.config(text="Encendido" if esta else "Apagado")
            punto.itemconfig(circulo, fill=c["ok"] if esta else c["apagado"])
        direccion.config(text=url_pagina() if esta and not ocupado["v"] else
                         ("" if ocupado["v"] else "La página y la extensión no funcionan mientras está apagado."))
        b_encender.state(["disabled"] if esta or ocupado["v"] else ["!disabled"])
        for b in (b_apagar, b_reiniciar):
            b.state(["!disabled"] if esta and not ocupado["v"] else ["disabled"])
        b_abrir.state(["disabled"] if ocupado["v"] else ["!disabled"])

    def comprobar() -> None:
        def trabajo():
            esta = encendido()
            raiz.after(0, lambda: pintar(esta))
        threading.Thread(target=trabajo, daemon=True).start()
        raiz.after(2500, comprobar)

    def accion(texto: str, fn) -> None:
        ocupado.update(v=True, texto=texto)
        pintar(False)

        def trabajo():
            fn()
            ocupado["v"] = False
            esta = encendido()
            raiz.after(0, lambda: pintar(esta))
        threading.Thread(target=trabajo, daemon=True).start()

    b_encender.config(command=lambda: accion("Encendiendo…", encender))
    b_apagar.config(command=lambda: accion("Apagando…", apagar))
    b_reiniciar.config(command=lambda: accion("Reiniciando…", reiniciar))
    b_abrir.config(command=lambda: accion("Abriendo…", abrir_pagina))
    comprobar()
    raiz.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--servidor" in argv:
        return ejecutar_servidor(argv)
    if argv[:1] == ["--elegir-carpeta"] and len(argv) >= 3:
        return _elegir_carpeta(argv[1], argv[2])
    ordenes = {"--encender": encender, "--apagar": apagar, "--reiniciar": reiniciar, "--abrir": abrir_pagina,
               "--estado": encendido}
    if argv and argv[0] in ordenes:
        ok = ordenes[argv[0]]()
        if sys.stdout:
            print("Encendido" if encendido() else "Apagado")
        return 0 if ok else 1
    if argv[:1] == ["--version"]:
        from . import __version__
        if sys.stdout:
            print(__version__)
        return 0
    if argv[:1] == ["--limpiar-sistema"]:          # lo usa el desinstalador
        from .nativo import autoinicio
        apagar()
        if autoinicio.activo():
            autoinicio.fijar(False)
        return 0
    return panel()


if __name__ == "__main__":
    sys.exit(main())
