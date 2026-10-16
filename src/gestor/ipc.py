"""Servidor IPC de la aplicación: recibe las peticiones que reenvía el host nativo.

Canal: tubería con nombre de Windows (multiprocessing.connection, AF_PIPE) con
autenticación por clave compartida (HMAC): sin la clave no se puede ni enviar
un mensaje. Cada mensaje se valida otra vez aquí con `protocolo.validar_mensaje`.
"""
import json
import threading
from multiprocessing.connection import Connection, Listener

from . import drm
from .cola import GestorCola
from .modelos import CodigoError, ErrorGestor, EstadoTarea, Tarea
from .nativo.comun import clave_ipc, direccion_pipe
from .protocolo import MAX_BYTES_MENSAJE, respuesta_error, respuesta_ok, validar_mensaje


def tarea_resumen(t: Tarea) -> dict:
    """Versión compacta de una tarea para la extensión (la respuesta no puede ser enorme)."""
    err = t.error and {k: t.error.get(k) for k in ("codigo", "mensaje", "causa", "solucion")}
    return {"id": t.id, "url": t.url, "titulo": t.titulo, "sitio": t.sitio, "estado": t.estado.value,
            "progreso": t.progreso, "origen": t.origen, "error": err, "notas": t.notas[:5],
            "intentos": t.intentos, "carpeta_final": t.carpeta_final}


def info_resumen(info, diag: drm.Diagnostico) -> dict:
    formatos = [{"id": f.id, "ext": f.extension, "tipo": f.tipo.value, "altura": f.altura,
                 "tamano": f.tamano_bytes, "estimado": f.tamano_es_estimado, "drm": f.tiene_drm}
                for f in info.formatos[:40]]
    return {"titulo": info.titulo, "sitio": info.sitio, "autor": info.autor, "duracion": info.duracion_seg,
            "miniatura": info.miniatura_url, "en_vivo": info.es_en_vivo, "es_lista": info.es_lista,
            "formatos": formatos, "subtitulos": info.subtitulos,
            "diagnostico": {"nivel": diag.nivel.value, "confianza": diag.confianza.value,
                            "motivo": diag.motivo, "alternativas": list(diag.alternativas)}}


class Manejador:
    """Traduce una petición ya validada en una llamada a la cola."""

    def __init__(self, cola: GestorCola):
        self.cola = cola

    def manejar(self, bruto) -> dict:
        id_ = bruto.get("id", "?") if isinstance(bruto, dict) and isinstance(bruto.get("id"), str) else "?"
        try:
            m = validar_mensaje(bruto)
            id_ = m["id"]
            return respuesta_ok(id_, self._ejecutar(m["accion"], m["datos"]))
        except ErrorGestor as e:
            return respuesta_error(id_, e)
        except Exception as exc:     # nunca dejar caer el servidor por un fallo inesperado
            return respuesta_error(id_, ErrorGestor(CodigoError.DESCONOCIDO, "Error interno de la aplicación.",
                                                    detalle_tecnico=type(exc).__name__))

    def _ejecutar(self, accion: str, d: dict) -> dict:
        c = self.cola
        if accion == "ping":
            return {"app": "gestor-descargas", "version": 1}
        if accion == "analizar":
            r = c.analizar(d["url"])
            return info_resumen(r["info"], r["diagnostico"])
        if accion == "detectar":
            return tarea_resumen(c.detectar(d["url"], d.get("origen")))
        if accion == "encolar":
            return tarea_resumen(c.encolar(d["url"], origen=d.get("origen"), opciones=d.get("opciones")))
        if accion == "iniciar":
            return tarea_resumen(c.iniciar_detectada(d["id"], d.get("opciones")))
        if accion == "listar":
            estados = [EstadoTarea(e) for e in d["estados"]] if d.get("estados") else None
            ts = c.listar(estados=estados, texto=d.get("texto"), limite=d.get("limite", 100))
            return {"tareas": [tarea_resumen(t) for t in ts]}
        t = c.obtener(d["id"])
        if t is None:
            raise ErrorGestor(CodigoError.CONFIGURACION, "La tarea no existe.")
        if accion == "estado":
            return tarea_resumen(t)
        if accion == "cancelar":
            return tarea_resumen(c.cancelar(d["id"]))
        if accion == "reintentar":
            return tarea_resumen(c.reintentar(d["id"]))
        if accion == "eliminar":
            c.eliminar(d["id"])
            return {}
        raise ErrorGestor(CodigoError.COMUNICACION, "Acción no implementada.")


class ServidorIPC:
    def __init__(self, cola: GestorCola, *, direccion: str | None = None, clave: bytes | None = None):
        self.manejador = Manejador(cola)
        self._listener = Listener(address=direccion or direccion_pipe(), family="AF_PIPE",
                                  authkey=clave or clave_ipc(crear=True))
        self._activo = True
        self._hilo = threading.Thread(target=self._aceptar, name="ipc", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._activo = False
        try:
            self._listener.close()
        except OSError:
            pass

    def _aceptar(self) -> None:
        while self._activo:
            try:
                con = self._listener.accept()      # incluye la comprobación de la clave
            except Exception:
                if not self._activo:
                    return
                continue                           # cliente sin clave correcta: se ignora
            threading.Thread(target=self._atender, args=(con,), daemon=True).start()

    def _atender(self, con: Connection) -> None:
        with con:
            while True:
                try:
                    datos = con.recv_bytes(maxlength=MAX_BYTES_MENSAJE)
                except (EOFError, OSError):
                    return
                try:
                    bruto = json.loads(datos.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    bruto = None
                resp = self.manejador.manejar(bruto)
                try:
                    con.send_bytes(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
                except OSError:
                    return
