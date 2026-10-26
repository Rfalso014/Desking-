"""Servidor web local: sirve la página del gestor y la API que usan la página y la extensión.

    GET  /               la página (lleva dentro el token local, que solo puede leer quien abre la página aquí)
    GET  /api/salud      ¿está encendido? (sin token; lo usa el panel de control)
    GET  /api/eventos    cambios de las descargas en vivo (Server-Sent Events)
    POST /api            una acción del protocolo (ver protocolo.py)

Seguridad, porque cualquier página web abierta en el navegador puede intentar hablar con 127.0.0.1:
  - Solo escucha en 127.0.0.1 (nadie de la red local puede entrar).
  - La cabecera Host debe ser 127.0.0.1 o localhost (evita el «DNS rebinding»).
  - Un POST con cabecera Origin solo se acepta desde la propia página o desde nuestra extensión (evita CSRF).
  - Toda acción, salvo ping y vincular, exige el token local de la página o el de una extensión vinculada.
"""
import base64
import hashlib
import json
import queue
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from ..api import Manejador, tarea_resumen
from ..config import RAIZ_PROYECTO
from ..protocolo import MAX_BYTES_MENSAJE

PUERTO_POR_DEFECTO = 7878
ESTATICO = Path(__file__).with_name("estatico")
_TIPOS = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".json": "application/json"}
_CSP = ("default-src 'self'; img-src 'self' https: http: data:; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
_LATIDO_SEG = 15


def id_extension(manifiesto: Path | None = None) -> str | None:
    """ID de Chrome de nuestra extensión, calculado con la clave pública de su manifest.json."""
    ruta = manifiesto or (RAIZ_PROYECTO / "extension" / "manifest.json")
    try:
        clave = json.loads(ruta.read_text(encoding="utf-8")).get("key")
    except (OSError, ValueError):
        return None
    if not clave:
        return None
    hex_ = hashlib.sha256(base64.b64decode(clave)).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in hex_)


class ServidorWeb:
    def __init__(self, manejador: Manejador, puerto: int = PUERTO_POR_DEFECTO, *, extension_id: str | None = None):
        self.manejador = manejador
        self._clientes: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.extension_id = extension_id if extension_id is not None else id_extension()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", puerto), _crear_handler(self))
        self.httpd.daemon_threads = True
        self.puerto = self.httpd.server_port
        manejador.cola.suscribir(self._difundir)

    # --- orígenes permitidos -----------------------------------------------------------------------
    def hosts_validos(self) -> set[str]:
        return {f"127.0.0.1:{self.puerto}", f"localhost:{self.puerto}"}

    def origen_valido(self, origen: str | None) -> bool:
        if origen is None:
            return True               # peticiones que no vienen de una página (p. ej. el panel de control)
        propios = {f"http://{h}" for h in self.hosts_validos()}
        return origen in propios or (bool(self.extension_id) and origen == f"chrome-extension://{self.extension_id}")

    def token_valido(self, token: str | None) -> bool:
        return self.manejador.es_web(token) or self.manejador.vinculacion.validar_token(token)

    # --- eventos en vivo ---------------------------------------------------------------------------
    def _difundir(self, d: dict) -> None:
        if "url" in d:
            evento = {"tipo": "tarea", "tarea": tarea_resumen(d)}
        else:
            evento = {"tipo": d.get("estado"), "id": d.get("id")}      # «eliminado» o «grupos»
        datos = json.dumps(evento, ensure_ascii=False)
        with self._lock:
            for q in self._clientes:
                q.put(datos)

    def suscribir(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._clientes.append(q)
        return q

    def desuscribir(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clientes:
                self._clientes.remove(q)

    # --- ciclo de vida -------------------------------------------------------------------------------
    def servir(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def detener(self) -> None:
        with self._lock:
            for q in self._clientes:
                q.put(None)                   # cierra los flujos de eventos abiertos
        self.httpd.shutdown()
        self.httpd.server_close()


def _crear_handler(srv: ServidorWeb):
    class Handler(BaseHTTPRequestHandler):
        server_version = "GestorDescargas"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):           # sin registro en consola (el servidor corre en segundo plano)
            pass

        # --- utilidades ---
        def _host_ok(self) -> bool:
            if (self.headers.get("Host") or "").lower() in srv.hosts_validos():
                return True
            self._enviar(HTTPStatus.FORBIDDEN, b"Host no permitido", "text/plain; charset=utf-8")
            return False

        def _enviar(self, estado: HTTPStatus, cuerpo: bytes, tipo: str, extra: dict | None = None) -> None:
            self.send_response(estado)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, datos: dict, estado: HTTPStatus = HTTPStatus.OK) -> None:
            self._enviar(estado, json.dumps(datos, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8",
                         self._cors())

        def _cors(self) -> dict:
            origen = self.headers.get("Origin")
            if origen and srv.extension_id and origen == f"chrome-extension://{srv.extension_id}":
                return {"Access-Control-Allow-Origin": origen, "Vary": "Origin"}
            return {}

        # --- GET ---
        def do_GET(self):
            if not self._host_ok():
                return
            ruta = urlsplit(self.path)
            if ruta.path in ("/", "/index.html"):
                html = (ESTATICO / "index.html").read_text(encoding="utf-8")
                html = html.replace("{{TOKEN}}", srv.manejador.token_web).replace("{{VERSION}}", __version__)
                return self._enviar(HTTPStatus.OK, html.encode("utf-8"), _TIPOS[".html"], {"Content-Security-Policy": _CSP})
            if ruta.path == "/api/salud":
                return self._json({"app": "gestor-descargas", "version": __version__})
            if ruta.path == "/api/eventos":
                return self._eventos(parse_qs(ruta.query).get("token", [""])[0])
            nombre = ruta.path.lstrip("/")
            archivo = (ESTATICO / nombre).resolve()
            if (nombre and "/" not in nombre and "\\" not in nombre and archivo.parent == ESTATICO.resolve()
                    and archivo.is_file() and archivo.suffix in _TIPOS):
                return self._enviar(HTTPStatus.OK, archivo.read_bytes(), _TIPOS[archivo.suffix])
            self._enviar(HTTPStatus.NOT_FOUND, b"No encontrado", "text/plain; charset=utf-8")

        def _eventos(self, token: str) -> None:
            if not srv.token_valido(token):
                return self._enviar(HTTPStatus.UNAUTHORIZED, b"Sin permiso", "text/plain; charset=utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            for k, v in self._cors().items():
                self.send_header(k, v)
            self.end_headers()
            q = srv.suscribir()
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        dato = q.get(timeout=_LATIDO_SEG)
                    except queue.Empty:
                        self.wfile.write(b": latido\n\n")     # mantiene viva la conexión y detecta si se cerró
                        self.wfile.flush()
                        continue
                    if dato is None:
                        return
                    self.wfile.write(f"data: {dato}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except OSError:
                return                                   # la página se cerró
            finally:
                srv.desuscribir(q)
                self.close_connection = True

        # --- POST ---
        def do_POST(self):
            if not self._host_ok():
                return
            if not srv.origen_valido(self.headers.get("Origin")):
                return self._enviar(HTTPStatus.FORBIDDEN, b"Origen no permitido", "text/plain; charset=utf-8")
            if urlsplit(self.path).path != "/api":
                return self._enviar(HTTPStatus.NOT_FOUND, b"No encontrado", "text/plain; charset=utf-8")
            if "json" not in (self.headers.get("Content-Type") or ""):
                return self._enviar(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, b"Se espera JSON", "text/plain; charset=utf-8")
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = -1
            if not 0 < largo <= MAX_BYTES_MENSAJE:
                return self._enviar(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b"Mensaje no valido", "text/plain; charset=utf-8")
            try:
                bruto = json.loads(self.rfile.read(largo).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                bruto = None
            self._json(srv.manejador.manejar(bruto))

        def do_OPTIONS(self):
            # Preflight de la extensión (la página es del mismo origen y no lo necesita).
            cors = self._cors()
            if not self._host_ok():
                return
            if not cors:
                return self._enviar(HTTPStatus.FORBIDDEN, b"", "text/plain")
            self._enviar(HTTPStatus.NO_CONTENT, b"", "text/plain", {**cors, "Access-Control-Allow-Methods": "GET, POST",
                                                                     "Access-Control-Allow-Headers": "Content-Type",
                                                                     "Access-Control-Max-Age": "600"})

    return Handler


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)
