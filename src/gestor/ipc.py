"""Servidor IPC de la aplicación: recibe las peticiones que reenvía el host nativo.

Dos capas de seguridad:
  1. Canal: tubería con nombre de Windows autenticada con una clave compartida (HMAC).
  2. Vinculación: cada petición (salvo «ping» y «emparejar») debe llevar el TOKEN que la aplicación
     entregó a la extensión cuando el usuario escribió el código de vinculación.
Cada mensaje se valida otra vez aquí con `protocolo.validar_mensaje`.

Recuerda: la extensión solo pide cosas; las descargas las ejecuta la aplicación.
"""
import json
import os
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection, Listener
from pathlib import Path

from . import drm
from .cola import GestorCola
from .modelos import CodigoError, ErrorGestor, EstadoTarea, Tarea
from .nativo.comun import clave_ipc, direccion_pipe
from .protocolo import MAX_BYTES_MENSAJE, SIN_TOKEN, respuesta_error, respuesta_ok, validar_mensaje
from .vinculacion import Vinculacion


def tarea_resumen(t: Tarea) -> dict:
    """Versión compacta de una tarea para la extensión (la respuesta no puede ser enorme)."""
    err = t.error and {k: t.error.get(k) for k in ("codigo", "mensaje", "causa", "solucion")}
    return {"id": t.id, "url": t.url, "titulo": t.titulo, "sitio": t.sitio, "estado": t.estado.value,
            "progreso": t.progreso, "velocidad": t.velocidad_bps, "eta": t.eta_seg, "origen": t.origen,
            "miniatura": t.miniatura, "duracion": t.duracion, "error": err, "notas": t.notas[:5],
            "intentos": t.intentos, "carpeta_final": t.carpeta_final, "archivos": len(t.archivos),
            "opciones": t.opciones}


def info_resumen(info, diag: drm.Diagnostico) -> dict:
    formatos = [{"id": f.id, "ext": f.extension, "tipo": f.tipo.value, "altura": f.altura,
                 "tamano": f.tamano_bytes, "estimado": f.tamano_es_estimado, "drm": f.tiene_drm}
                for f in info.formatos[:40]]
    return {"titulo": info.titulo, "sitio": info.sitio, "autor": info.autor, "duracion": info.duracion_seg,
            "miniatura": info.miniatura_url, "en_vivo": info.es_en_vivo, "es_lista": info.es_lista,
            "formatos": formatos, "subtitulos": info.subtitulos,
            "diagnostico": {"nivel": diag.nivel.value, "confianza": diag.confianza.value,
                            "motivo": diag.motivo, "alternativas": list(diag.alternativas)}}


def _abrir_en_explorador(ruta: str) -> None:
    os.startfile(ruta)  # noqa: S606  (solo se llama con la carpeta de una tarea que ya existe en la base de datos)


class Manejador:
    """Traduce una petición ya validada en una llamada a la cola."""

    def __init__(self, cola: GestorCola, vinculacion: Vinculacion | None = None,
                 abrir_carpeta: Callable[[str], None] = _abrir_en_explorador):
        self.cola = cola
        self.vinculacion = vinculacion or Vinculacion(cola.db)
        self._abrir = abrir_carpeta

    def manejar(self, bruto) -> dict:
        id_ = bruto.get("id", "?") if isinstance(bruto, dict) and isinstance(bruto.get("id"), str) else "?"
        try:
            m = validar_mensaje(bruto)
            id_ = m["id"]
            if m["accion"] not in SIN_TOKEN and not self.vinculacion.validar_token(m["token"]):
                raise ErrorGestor(CodigoError.NO_VINCULADO, "La extensión no está vinculada con la aplicación.",
                                  causa="Falta el código de vinculación o fue revocado.",
                                  solucion="En la aplicación abre la pestaña «Extensión» y escribe su código en la extensión.")
            return respuesta_ok(id_, self._ejecutar(m["accion"], m["datos"], m["token"]))
        except ErrorGestor as e:
            return respuesta_error(id_, e)
        except Exception as exc:     # nunca dejar caer el servidor por un fallo inesperado
            return respuesta_error(id_, ErrorGestor(CodigoError.DESCONOCIDO, "Error interno de la aplicación.",
                                                    detalle_tecnico=type(exc).__name__))

    def _ejecutar(self, accion: str, d: dict, token: str | None) -> dict:
        c, v = self.cola, self.vinculacion
        if accion == "ping":
            return {"app": "gestor-descargas", "version": 1, "vinculado": v.validar_token(token)}
        if accion == "emparejar":
            return {"token": v.emparejar(d["codigo"], d.get("nombre", "Navegador"))}
        if accion == "desvincular":
            return {"desvinculado": v.desvincular_token(token)}
        if accion == "analizar":
            r = c.analizar(d["url"])
            return info_resumen(r["info"], r["diagnostico"])
        if accion == "detectar":
            return tarea_resumen(c.detectar(d["url"], d.get("origen"), d.get("opciones")))
        if accion == "encolar":
            return tarea_resumen(c.encolar(d["url"], origen=d.get("origen"), opciones=d.get("opciones")))
        if accion == "limpiar":
            return {"eliminadas": c.limpiar_terminadas()}
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
        if accion == "abrir_carpeta":
            carpeta = Path(t.carpeta_final) if t.carpeta_final else None
            if not carpeta or not carpeta.is_dir():
                raise ErrorGestor(CodigoError.CONFIGURACION, "Esa descarga todavía no tiene carpeta.",
                                  solucion="Espera a que termine la descarga.")
            self._abrir(str(carpeta))
            return {}
        raise ErrorGestor(CodigoError.COMUNICACION, "Acción no implementada.")


class ServidorIPC:
    def __init__(self, cola: GestorCola, *, vinculacion: Vinculacion | None = None,
                 direccion: str | None = None, clave: bytes | None = None):
        self.manejador = Manejador(cola, vinculacion)
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
