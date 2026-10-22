"""«Actualizar aplicación y extensión»: un solo botón (en la app y en la extensión) que pone todo al día.

Qué se actualiza según cómo esté instalado el programa:
  - desarrollo (código con git + .venv): `git pull` del código (la extensión sale de esa misma carpeta)
    y pip para yt-dlp, su solucionador de JavaScript, gallery-dl y Deno.
  - instalada (instalador de Inno Setup): el instalador del último release de GitHub (trae la app, la
    extensión, FFmpeg y Deno) y, aparte, yt-dlp desde PyPI.
  - portátil (.zip): yt-dlp desde PyPI; para la app se abre la página de descarga.
Al terminar la app se reinicia y la extensión se recarga sola: la «marca» (actualizacion.json) le dice
que hubo una actualización. Todo lo descargado se verifica con SHA-256 antes de usarlo.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import __version__, actualizaciones, componentes
from .config import RAIZ_PROYECTO, localizar_deno, localizar_ffmpeg
from .modelos import CodigoError, ErrorGestor
from .nativo.comun import carpeta_datos

HOSTS_GITHUB = frozenset({"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})
BUSQUEDA_AUTOMATICA_SEG = 24 * 3600
_SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def modo_instalacion(exe_dir: Path | None = None) -> str:
    if not componentes.EMPAQUETADO:
        return "desarrollo"
    import sys
    carpeta = exe_dir or Path(sys.executable).parent
    return "instalada" if any(carpeta.glob("unins*.exe")) else "portatil"


def version_extension() -> str | None:
    """Versión de la extensión que acompaña a esta app (la que el navegador debería tener cargada)."""
    try:
        return json.loads((RAIZ_PROYECTO / "extension" / "manifest.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def _primera_linea(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, creationflags=_SIN_VENTANA)
        return (r.stdout or "").splitlines()[0].strip() if r.returncode == 0 and r.stdout else None
    except (OSError, subprocess.SubprocessError):
        return None


class Actualizador:
    """Guarda el estado (lo consultan la ventana y la extensión) y hace el trabajo en un hilo aparte."""

    def __init__(self, *, modo: str | None = None, leer_json=componentes.leer_json, ejecutar=subprocess.run,
                 descargar=componentes.descargar_verificado, hay_descargas: Callable[[], bool] = lambda: False):
        self.modo = modo or modo_instalacion()
        self._leer, self._ejecutar, self._descargar, self._hay_descargas = leer_json, ejecutar, descargar, hay_descargas
        self.al_reiniciar: Callable[[], None] | None = None      # la app lo fija: se cierra y vuelve a abrir
        self.al_instalar: Callable[[Path], None] | None = None   # la app lo fija: lanza el instalador y se cierra
        self.al_abrir_url: Callable[[str], None] | None = None
        self._lock = threading.Lock()
        self._oyentes: list[Callable[[dict], None]] = []
        self._hilo: threading.Thread | None = None
        self._versiones_programas: dict | None = None
        self.pausa = 2.0
        self._estado = {"fase": "inactivo", "mensaje": "", "pendientes": [], "avisos": [], "hechos": [],
                        "ultima_busqueda": self._leer_archivo("busqueda.json").get("cuando"), "reiniciar": False}

    # --- estado ------------------------------------------------------------------------------------
    def suscribir(self, cb: Callable[[dict], None]) -> None:
        self._oyentes.append(cb)

    def _fijar(self, **cambios) -> None:
        with self._lock:
            self._estado.update(cambios)
        e = self.estado()
        for cb in list(self._oyentes):
            try:
                cb(e)
            except Exception:
                pass

    def estado(self) -> dict:
        with self._lock:
            e = dict(self._estado)
        return {**e, "modo": self.modo, "versiones": self.versiones(), "marca": self.marca(),
                "version_extension": version_extension(), "carpeta_extension": str(RAIZ_PROYECTO / "extension")}

    def versiones(self) -> dict:
        if self._versiones_programas is None:          # ffmpeg/deno se consultan una vez (lanzan procesos)
            ff, deno = localizar_ffmpeg(), localizar_deno()
            self._versiones_programas = {
                "ffmpeg": ff and (_primera_linea([str(ff / "ffmpeg"), "-version"]) or "").split(" Copyright")[0].replace("ffmpeg version ", "") or None,
                "deno": deno and (_primera_linea([str(deno), "--version"]) or "").replace("deno ", "").split(" ")[0] or None}
        return {"app": __version__, **{p: componentes.version_instalada(p) for p in componentes.paquetes()}, **self._versiones_programas}

    def ocupado(self) -> bool:
        return self._estado["fase"] in ("buscando", "actualizando")

    # --- marca de «hubo una actualización» (sobrevive al reinicio) ----------------------------------
    def _leer_archivo(self, nombre: str) -> dict:
        try:
            d = json.loads((carpeta_datos() / nombre).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _escribir_archivo(self, nombre: str, datos: dict) -> None:
        (carpeta_datos() / nombre).write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    def marca(self) -> dict:
        return self._leer_archivo("actualizacion.json")

    # --- buscar ------------------------------------------------------------------------------------
    def buscar(self) -> dict:
        """Consulta qué hay nuevo (no descarga nada). Devuelve el estado."""
        self._fijar(fase="buscando", mensaje="Buscando actualizaciones…", avisos=[])
        pendientes, avisos = [], []
        try:
            app = self._buscar_app(avisos)
            if app:
                pendientes.append(app)
        except Exception:
            avisos.append("No se pudo consultar si hay una versión nueva de la aplicación (¿sin conexión?).")
        for p in componentes.paquetes():
            try:
                nueva = componentes.ultima_pypi(p, self._leer)
                actual = componentes.version_instalada(p)
                if actual and actualizaciones.comparar_versiones(nueva["version"], actual) > 0:
                    pendientes.append({"tipo": "componente", "nombre": p, "actual": actual, "nueva": nueva["version"], "info": nueva})
            except Exception:
                avisos.append(f"No se pudo consultar la última versión de {p}.")
        cuando = time.time()
        self._escribir_archivo("busqueda.json", {"cuando": cuando})
        self._fijar(fase="inactivo", pendientes=pendientes, avisos=avisos, ultima_busqueda=cuando,
                    mensaje="Hay actualizaciones disponibles." if pendientes else "Todo está al día.")
        return self.estado()

    def buscar_si_toca(self) -> None:
        """Al abrir la app: busca (sin instalar) si hace más de un día de la última vez."""
        if time.time() - (self._estado.get("ultima_busqueda") or 0) > BUSQUEDA_AUTOMATICA_SEG:
            self.buscar_en_segundo_plano()

    def buscar_en_segundo_plano(self) -> None:
        self._en_hilo(self.buscar)

    def _git(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return self._ejecutar(["git", "-C", str(RAIZ_PROYECTO), *args], capture_output=True, text=True,
                              timeout=timeout, creationflags=_SIN_VENTANA)

    def _buscar_app(self, avisos: list[str]) -> dict | None:
        if self.modo == "desarrollo":
            if self._git("fetch", "--quiet", timeout=120).returncode != 0:
                avisos.append("No se pudo consultar el repositorio del código (git fetch).")
                return None
            r = self._git("rev-list", "--count", "HEAD..@{u}")
            atrasados = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
            if not atrasados:
                return None
            if self._git("status", "--porcelain", "--untracked-files=no").stdout.strip():
                avisos.append(f"Hay {atrasados} cambios nuevos del código, pero tienes cambios sin guardar: "
                              "guárdalos (commit) para poder actualizar.")
                return None
            return {"tipo": "app", "nombre": "Aplicación y extensión", "actual": __version__, "nueva": f"{atrasados} cambios nuevos"}
        rel = actualizaciones.interpretar_release(self._leer(actualizaciones.URL_API))
        if not rel["nueva"]:
            return None
        return {"tipo": "app", "nombre": "Aplicación y extensión", "actual": __version__, "nueva": rel["version"],
                "url": rel["url"], "instalador": rel["instalador"]}

    def reiniciar(self) -> None:
        """Cierra y vuelve a abrir la app (la respuesta a quien lo pidió sale antes de cerrarse)."""
        if self._hay_descargas():
            raise ErrorGestor(CodigoError.CONFIGURACION, "Hay descargas en curso.",
                              solucion="Espera a que terminen (o cancélalas) y vuelve a intentarlo.")
        if self.al_reiniciar is None:
            raise ErrorGestor(CodigoError.CONFIGURACION, "Esta aplicación no puede reiniciarse sola.")
        threading.Timer(0.5, self.al_reiniciar).start()

    # --- actualizar --------------------------------------------------------------------------------
    def iniciar(self) -> dict:
        """Busca y aplica todo lo pendiente en un hilo aparte. Devuelve el estado inmediatamente."""
        if self.ocupado():
            return self.estado()
        if self._hay_descargas():
            raise ErrorGestor(CodigoError.CONFIGURACION, "Hay descargas en curso.",
                              causa="Para actualizar hay que reiniciar la aplicación.",
                              solucion="Espera a que terminen (o cancélalas) y vuelve a pulsar «Actualizar».")
        self._fijar(fase="actualizando", mensaje="Preparando…", hechos=[], reiniciar=False)
        self._en_hilo(self._actualizar)
        return self.estado()

    def _en_hilo(self, fn) -> None:
        def seguro():
            try:
                fn()
            except ErrorGestor as e:
                self._fijar(fase="error", mensaje=" ".join(x for x in (e.mensaje, e.solucion) if x))
            except Exception as e:      # nunca dejar la app colgada en «actualizando»
                self._fijar(fase="error", mensaje=f"No se pudo terminar la actualización ({type(e).__name__}).")
        self._hilo = threading.Thread(target=seguro, name="actualizador", daemon=True)
        self._hilo.start()

    def _actualizar(self) -> None:
        self.buscar()
        self._fijar(fase="actualizando")
        with self._lock:
            pendientes = list(self._estado["pendientes"])
        if not pendientes:
            self._fijar(fase="listo", mensaje="Todo está al día: no había nada que actualizar.")
            return
        hechos: list[str] = []
        comps = [p for p in pendientes if p["tipo"] == "componente"]
        app = next((p for p in pendientes if p["tipo"] == "app"), None)

        if comps:
            nombres = ", ".join(p["nombre"] for p in comps)
            self._fijar(mensaje=f"Actualizando {nombres}…")
            if self.modo == "desarrollo":
                componentes.actualizar_con_pip(tuple(p["nombre"] for p in comps), self._ejecutar)
            else:
                for p in comps:
                    componentes.instalar_rueda(p["nombre"], p["info"], self._descargar)
            hechos += [f"{p['nombre']} {p['actual']} → {p['nueva']}" for p in comps]

        instalador = None
        if app and self.modo == "desarrollo":
            self._fijar(mensaje="Descargando el código nuevo de la aplicación y la extensión…")
            req = RAIZ_PROYECTO / "requirements.txt"
            antes = req.read_bytes() if req.exists() else b""
            r = self._git("pull", "--ff-only", timeout=180)
            if r.returncode != 0:
                raise ErrorGestor(CodigoError.CONFIGURACION, "No se pudo actualizar el código (git pull).",
                                  detalle_tecnico=(r.stderr or "")[-500:])
            if req.exists() and req.read_bytes() != antes:
                self._fijar(mensaje="Instalando las librerías nuevas…")
                pip = componentes.comando_pip(())[:4] + ["-r", str(req)]
                self._ejecutar(pip, capture_output=True, text=True, timeout=900, creationflags=_SIN_VENTANA)
            hechos.append(f"Aplicación y extensión: {app['nueva']}")
        elif app and self.modo == "instalada" and app.get("instalador"):
            self._fijar(mensaje=f"Descargando la versión {app['nueva']}…")
            ins = app["instalador"]
            destino = Path(tempfile.mkdtemp(prefix="gestor-act-")) / ins["nombre"]
            self._descargar(ins["url"], ins["sha256"], destino, hosts=HOSTS_GITHUB, maximo=600 * 1024 * 1024, timeout=120)
            instalador = destino
            hechos.append(f"Aplicación y extensión {app['actual']} → {app['nueva']}")
        elif app:
            if self.al_abrir_url and app.get("url"):
                self.al_abrir_url(app["url"])
            hechos.append(f"Versión {app['nueva']} disponible: descárgala desde la página que se abrió")

        recargar = bool(app) and self.modo != "portatil"
        self._escribir_archivo("actualizacion.json", {"id": time.time_ns() // 1_000_000, "recargar_extension": recargar,
                                                      "hechos": hechos, "version": __version__})
        reiniciar = bool(comps) or (bool(app) and self.modo != "portatil")
        mensaje = "Listo. " + ("Reiniciando la aplicación; la extensión se recargará sola." if reiniciar else "")
        self._fijar(fase="listo", mensaje=mensaje.strip(), hechos=hechos, pendientes=[], reiniciar=reiniciar)
        if instalador is not None and self.al_instalar:
            time.sleep(self.pausa)     # deja que la extensión vea «listo» antes de que se cierre la app
            self.al_instalar(instalador)
        elif reiniciar and self.al_reiniciar:
            time.sleep(self.pausa)
            self.al_reiniciar()


def comando_reinicio(mostrar_ventana: bool) -> list[str]:
    """Cómo volver a abrir esta misma aplicación (empaquetada o desde el código)."""
    import sys
    extra = ["--reiniciado"] + ([] if mostrar_ventana else ["--segundo-plano"])
    if componentes.EMPAQUETADO:
        return [sys.executable, *extra]
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pyw if pyw.exists() else sys.executable), "-m", "gestor.app", *extra]


ARGS_INSTALADOR = ["/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]


def entorno_app() -> dict:
    """Variables de entorno para volver a abrir la app: desde el código, `gestor` está en src (no instalado)."""
    env = dict(os.environ)
    if not componentes.EMPAQUETADO:
        src = str(RAIZ_PROYECTO / "src")
        env["PYTHONPATH"] = os.pathsep.join(x for x in (src, env.get("PYTHONPATH")) if x)
    return env


def lanzar_desacoplado(cmd: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=os.path.expanduser("~"), env=entorno_app(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
