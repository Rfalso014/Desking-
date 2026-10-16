"""Cola de descargas: hilos de trabajo, estados, cancelación y reintentos.

Flujo de una tarea:
    PENDIENTE -> ANALIZANDO -> DESCARGANDO -> PROCESANDO -> COMPLETADO
                                   |-> CANCELADO / ERROR  (se puede reintentar)
"""
import queue
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import drm, reglas
from .config import Preferencias, localizar_deno
from .db import BaseDatos
from .descargador import Progreso, descargar, limpiar_carpeta_trabajo
from .errores import traducir_excepcion
from .extractor import obtener_info
from .modelos import (ESTADOS_ACTIVOS, CodigoError, ErrorGestor, EstadoTarea, InfoContenido,
                      Tarea)
from .organizador import organizar
from .validacion import validar_url, verificar_resolucion

_INTERVALO_PROGRESO = 0.5   # segundos mínimos entre escrituras de progreso a la base de datos


class GestorCola:
    def __init__(self, db: BaseDatos, *, ffmpeg_dir: Path | None = None, deno: Path | None = None,
                 extraer: Callable[..., InfoContenido] = obtener_info,
                 descargar_fn: Callable = descargar, permitir_interno: bool = False):
        self.db = db
        self.ffmpeg_dir = ffmpeg_dir
        self.deno = deno if deno is not None else localizar_deno()
        self._extraer = extraer
        self._descargar = descargar_fn
        self._permitir_interno = permitir_interno      # solo pruebas con servidores locales
        self._cola: queue.Queue[str | None] = queue.Queue()
        self._eventos: dict[str, threading.Event] = {}  # id -> señal de cancelación
        self._en_proceso: set[str] = set()
        self._hilos: list[threading.Thread] = []
        self._oyentes: list[Callable[[dict], None]] = []
        self._lock = threading.RLock()
        self._ultimo_progreso: dict[str, float] = {}

    # --- ciclo de vida ----------------------------------------------------------
    def prefs(self) -> Preferencias:
        return self.db.cargar_preferencias()

    def iniciar(self, hilos: int | None = None) -> None:
        n = hilos or max(1, min(self.prefs().descargas_simultaneas, 8))
        for i in range(n):
            h = threading.Thread(target=self._bucle, name=f"descarga-{i}", daemon=True)
            h.start()
            self._hilos.append(h)

    def detener(self, esperar: float = 5.0) -> None:
        for ev in list(self._eventos.values()):
            ev.set()
        for _ in self._hilos:
            self._cola.put(None)
        for h in self._hilos:
            h.join(timeout=esperar)
        self._hilos.clear()

    def suscribir(self, cb: Callable[[dict], None]) -> None:
        self._oyentes.append(cb)

    def recuperar(self) -> list[str]:
        """Al abrir la app: reanuda (o marca como interrumpidas) las tareas que quedaron a medias."""
        reanudar = self.prefs().reanudar_al_iniciar
        ids = []
        for t in self.db.listar_tareas(estados=[EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS]):
            if reanudar:
                t.estado, t.progreso = EstadoTarea.PENDIENTE, None
                self._publicar(t)
                self._cola.put(t.id)
                ids.append(t.id)
            else:
                t.estado = EstadoTarea.CANCELADO
                t.notas = [*t.notas, "Interrumpida al cerrar la aplicación; puedes reintentarla."]
                self._publicar(t)
        return ids

    # --- API pública ------------------------------------------------------------
    def detectar(self, url: str, origen: str | None = None) -> Tarea:
        """Registra un recurso detectado (estado DETECTADO) sin empezar a descargar."""
        url = validar_url(url, permitir_interno=self._permitir_interno)
        t = self.db.crear_tarea(url, origen=origen, estado=EstadoTarea.DETECTADO)
        self._publicar(t)
        # Los datos (título, miniatura, compatibilidad) se obtienen en segundo plano; la tarea espera en
        # «Detectado» hasta que el usuario pulse «Descargar» (o la elimine).
        threading.Thread(target=self._leer_datos_seguro, args=(t.id,), daemon=True).start()
        return t

    def _leer_datos_seguro(self, id_: str) -> None:
        try:
            self._leer_datos(id_)
        except Exception:        # p. ej. la base de datos se cerró mientras se leían los datos
            pass

    def _leer_datos(self, id_: str) -> None:
        t = self.db.obtener_tarea(id_)
        if t is None:
            return
        try:
            if not self._permitir_interno:
                verificar_resolucion(t.url)
            info = self._extraer(t.url, permitir_interno=self._permitir_interno)
            d = drm.evaluar(t.url, info)
        except Exception as exc:
            e = drm.enriquecer_error(t.url, exc if isinstance(exc, ErrorGestor) else traducir_excepcion(exc))
            t = self.db.obtener_tarea(id_)
            if t is not None and t.estado == EstadoTarea.DETECTADO:
                t.error = {"codigo": e.codigo.value, "mensaje": e.mensaje, "causa": e.causa,
                           "solucion": e.solucion, "detalle": e.detalle_tecnico}
                self._publicar(t)
            return
        t = self.db.obtener_tarea(id_)
        if t is None or t.estado != EstadoTarea.DETECTADO:
            return                                   # mientras tanto se inició o se eliminó
        t.titulo, t.sitio, t.miniatura, t.duracion = info.titulo, info.sitio, info.miniatura_url, info.duracion_seg
        t.notas = [d.motivo] if d.nivel != drm.Compatibilidad.COMPATIBLE else []
        self._publicar(t)

    def encolar(self, url: str, *, origen: str | None = None, opciones: dict | None = None,
                destino_manual: str | None = None) -> Tarea:
        url = validar_url(url, permitir_interno=self._permitir_interno)
        self._validar_elecciones(opciones)
        with self._lock:
            for t in self.db.listar_tareas(estados=[EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS]):
                if t.url == url and t.opciones == (opciones or {}):
                    return t                       # ya está en la cola: no se duplica
            t = self.db.crear_tarea(url, origen=origen, opciones=opciones, destino_manual=destino_manual)
        self._publicar(t)
        self._cola.put(t.id)
        return t

    def iniciar_detectada(self, id_: str, opciones: dict | None = None, destino_manual: str | None = None) -> Tarea:
        t = self._requerir(id_)
        if t.estado != EstadoTarea.DETECTADO:
            raise ErrorGestor(CodigoError.CONFIGURACION, "Solo se pueden iniciar tareas detectadas.")
        self._validar_elecciones(opciones)
        t.estado, t.opciones, t.destino_manual = EstadoTarea.PENDIENTE, opciones or {}, destino_manual
        self._publicar(t)
        self._cola.put(t.id)
        return t

    def cancelar(self, id_: str) -> Tarea:
        t = self._requerir(id_)
        with self._lock:
            if id_ in self._eventos:
                self._eventos[id_].set()           # tarea en curso: el hilo la detendrá
            elif t.estado in (EstadoTarea.PENDIENTE, EstadoTarea.DETECTADO):
                t.estado = EstadoTarea.CANCELADO
                self._publicar(t)
        return self._requerir(id_)

    def reintentar(self, id_: str) -> Tarea:
        t = self._requerir(id_)
        if t.estado not in (EstadoTarea.ERROR, EstadoTarea.CANCELADO):
            raise ErrorGestor(CodigoError.CONFIGURACION, "Solo se pueden reintentar tareas con error o canceladas.")
        t.estado, t.error, t.progreso, t.intentos = EstadoTarea.PENDIENTE, None, None, t.intentos + 1
        self._publicar(t)
        self._cola.put(t.id)
        return t

    def eliminar(self, id_: str) -> None:
        t = self._requerir(id_)
        if id_ in self._eventos:
            self._eventos[id_].set()
        self._limpiar_trabajo(t)
        self.db.eliminar_tarea(id_)
        self._notificar({"id": id_, "estado": "eliminado"})

    def limpiar_terminadas(self) -> int:
        """Quita del historial las tareas completadas, canceladas o con error (no borra archivos)."""
        n = self.db.limpiar_historial()
        self._notificar({"id": "*", "estado": "eliminado"})
        return n

    def obtener(self, id_: str) -> Tarea | None:
        return self.db.obtener_tarea(id_)

    def listar(self, **kw) -> list[Tarea]:
        return self.db.listar_tareas(**kw)

    def analizar(self, url: str) -> dict:
        """Consulta una URL (sin crear tarea) y devuelve info + diagnóstico de compatibilidad."""
        try:
            if not self._permitir_interno:
                verificar_resolucion(validar_url(url))
            info = self._extraer(url, permitir_interno=self._permitir_interno)
        except ErrorGestor as e:
            e = drm.enriquecer_error(url, e)
            raise e from None
        d = drm.evaluar(url, info)
        return {"info": info, "diagnostico": d}

    def limpiar_temporales(self) -> int:
        """Borra carpetas de trabajo de tareas que ya no las necesitan (no toca las de ERROR)."""
        base = self.prefs().carpeta_raiz / ".tmp"
        if not base.exists():
            return 0
        borradas = 0
        for d in base.iterdir():
            t = self.db.obtener_tarea(d.name)
            if d.is_dir() and (t is None or t.estado in (EstadoTarea.COMPLETADO, EstadoTarea.CANCELADO)):
                limpiar_carpeta_trabajo(d, base)
                borradas += 1
        return borradas

    # --- internos ---------------------------------------------------------------
    def _requerir(self, id_: str) -> Tarea:
        t = self.db.obtener_tarea(id_)
        if t is None:
            raise ErrorGestor(CodigoError.CONFIGURACION, "La tarea no existe.")
        return t

    @staticmethod
    def _validar_elecciones(opciones: dict | None) -> None:
        for k, v in (opciones or {}).items():
            if k not in reglas.CAMPOS_ACCION or not reglas.CAMPOS_ACCION[k](v):
                raise ErrorGestor(CodigoError.CONFIGURACION, f"Opción no válida: {k!r} = {v!r}.")

    def _notificar(self, d: dict) -> None:
        for cb in list(self._oyentes):
            try:
                cb(d)
            except Exception:       # un oyente roto no debe tumbar la cola
                pass

    def _publicar(self, t: Tarea) -> None:
        self.db.guardar_tarea(t)
        self._notificar(t.a_dict())

    def _limpiar_trabajo(self, t: Tarea) -> None:
        d = self.prefs().carpeta_raiz / ".tmp" / t.id
        if d.exists():
            limpiar_carpeta_trabajo(d, self.prefs().carpeta_raiz / ".tmp")

    def _bucle(self) -> None:
        while True:
            id_ = self._cola.get()
            if id_ is None:
                return
            with self._lock:
                t = self.db.obtener_tarea(id_)
                if t is None or t.estado != EstadoTarea.PENDIENTE or id_ in self._en_proceso:
                    continue                      # cancelada, eliminada o ya atendida
                self._en_proceso.add(id_)
                self._eventos[id_] = threading.Event()
            try:
                self._procesar(id_)
            finally:
                with self._lock:
                    self._en_proceso.discard(id_)
                    self._eventos.pop(id_, None)
                    self._ultimo_progreso.pop(id_, None)

    def _procesar(self, id_: str) -> None:
        t = self._requerir(id_)
        ev = self._eventos[id_]
        prefs = self.prefs()
        trabajo = prefs.carpeta_raiz / ".tmp" / id_
        try:
            t.estado, t.error = EstadoTarea.ANALIZANDO, None
            self._publicar(t)
            if not self._permitir_interno:
                verificar_resolucion(t.url)
            info = self._extraer(t.url, permitir_interno=self._permitir_interno)
            t.titulo, t.sitio, t.miniatura, t.duracion = info.titulo, info.sitio, info.miniatura_url, info.duracion_seg

            res = reglas.resolver(t.url, info.sitio, self.db.listar_reglas(solo_activas=True), prefs, t.opciones)
            t.notas = [*(f"Regla aplicada: {n}" for n in res.reglas_aplicadas)]
            if res.excluir:
                t.estado = EstadoTarea.CANCELADO
                t.notas.append("Excluida por una regla.")
                self._publicar(t)
                return
            diag = drm.evaluar(t.url, info)
            if diag.bloquea:
                raise ErrorGestor(CodigoError.CONTENIDO_PROTEGIDO, "Este contenido está protegido y no se puede descargar.",
                                  causa=diag.motivo, solucion=" ".join(diag.alternativas),
                                  detalle_tecnico="; ".join(diag.detalles))
            if diag.nivel == drm.Compatibilidad.PARCIAL:
                t.notas.append(diag.motivo)
            self._publicar(t)
            if ev.is_set():
                raise ErrorGestor(CodigoError.CANCELADO, "Cancelada.")

            def alprogreso(p: Progreso) -> None:
                ahora = time.monotonic()
                nuevo = {"descargando": EstadoTarea.DESCARGANDO, "procesando": EstadoTarea.PROCESANDO,
                         "completado": t.estado}[p.estado]
                cambia = nuevo != t.estado
                if not cambia and ahora - self._ultimo_progreso.get(id_, 0) < _INTERVALO_PROGRESO:
                    return
                self._ultimo_progreso[id_] = ahora
                t.estado, t.progreso = nuevo, p.porcentaje if p.porcentaje is not None else t.progreso
                t.velocidad_bps, t.eta_seg = p.velocidad_bps, p.eta_seg
                self._publicar(t)

            t.estado = EstadoTarea.DESCARGANDO
            self._publicar(t)
            resultado = self._descargar(t.url, res.a_opciones(prefs, self.ffmpeg_dir, self.deno), trabajo,
                                        progreso=alprogreso, cancelar=ev,
                                        permitir_interno=self._permitir_interno)

            t.estado, t.progreso = EstadoTarea.PROCESANDO, 100.0
            self._publicar(t)
            manual = Path(t.destino_manual) if t.destino_manual else None
            colocados = organizar(resultado.archivos, prefs, t.titulo or "Sin título",
                                  carpeta_manual=manual, subcarpeta=res.subcarpeta)
            rutas = [c.ruta for c in colocados if c.ruta]
            t.archivos = [str(r) for r in rutas]
            t.carpeta_final = str(rutas[0].parent) if rutas else None
            t.estado, t.velocidad_bps, t.eta_seg = EstadoTarea.COMPLETADO, None, None
            if all(c.accion.startswith("omitido") for c in colocados):
                t.notas.append("Los archivos ya existían; no se duplicó nada.")
            self._limpiar_trabajo(t)       # antes de publicar COMPLETADO: nadie ve el estado a medias
            self._publicar(t)
        except Exception as exc:
            e = exc if isinstance(exc, ErrorGestor) else traducir_excepcion(exc)
            if e.codigo == CodigoError.CANCELADO or ev.is_set():
                t.estado, t.error = EstadoTarea.CANCELADO, None
                self._limpiar_trabajo(t)
            else:
                e = drm.enriquecer_error(t.url, e)
                t.estado = EstadoTarea.ERROR
                t.error = {"codigo": e.codigo.value, "mensaje": e.mensaje, "causa": e.causa,
                           "solucion": e.solucion, "detalle": e.detalle_tecnico}
                self.db.registrar_error(id_, e)
            t.velocidad_bps = t.eta_seg = None
            self._publicar(t)
