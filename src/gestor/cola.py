"""Cola de descargas: hilos de trabajo, estados, cancelación y reintentos.

Flujo de una tarea:
    PENDIENTE -> ANALIZANDO -> DESCARGANDO -> PROCESANDO -> COMPLETADO
                                   |-> CANCELADO / ERROR  (se puede reintentar)
"""
import queue
import threading
from dataclasses import replace
import time
from collections.abc import Callable
from pathlib import Path

from . import drm, reglas
from .config import Preferencias, carpeta_datos, localizar_deno, opciones_sesion
from .db import BaseDatos
from .descargador import (Progreso, asegurar_ffmpeg_en_path, descargar, limpiar_carpeta_trabajo, opciones_red,
                          puede_imitar_navegador)
from .errores import traducir_excepcion
from .extractor import texto_tamanos
from .extractor import _extraer_con_ytdlp, obtener_info
from .modelos import (ESTADOS_ACTIVOS, CodigoError, ErrorGestor, EstadoTarea, InfoContenido,
                      Tarea)
from .organizador import organizar, sanear_nombre
from .validacion import clave_video, validar_url, verificar_resolucion

ETIQUETA_ESTADO = {EstadoTarea.DETECTADO: "detectado, esperando que lo autorices", EstadoTarea.PENDIENTE: "en espera",
                   EstadoTarea.ANALIZANDO: "analizándose", EstadoTarea.DESCARGANDO: "descargándose ahora",
                   EstadoTarea.PROCESANDO: "procesándose", EstadoTarea.COMPLETADO: "ya descargado"}
_INTERVALO_PROGRESO = 0.5   # segundos mínimos entre escrituras de progreso a la base de datos
MAX_COOKIES = 400

# Errores que NO se arreglan probando otra forma de bajar el mismo video (presentarse como Chrome, enlace directo...).
_SIN_RESPALDO = {CodigoError.CANCELADO, CodigoError.ESPACIO_INSUFICIENTE, CodigoError.PERMISOS, CodigoError.FFMPEG_AUSENTE,
                 CodigoError.CONTENIDO_PROTEGIDO, CodigoError.SUBTITULOS_INEXISTENTES, CodigoError.URL_INVALIDA,
                 CodigoError.CONFIGURACION, CodigoError.PROCESAMIENTO}


def limpiar_cookies(cookies) -> list[dict]:
    """Cookies que envía la extensión (las del sitio del video), saneadas. Lista vacía si algo no cuadra."""
    if not isinstance(cookies, list) or len(cookies) > MAX_COOKIES:
        return []
    limpias = []
    for c in cookies:
        if not isinstance(c, dict):
            continue
        nombre, valor, dominio, ruta = c.get("name"), c.get("value"), c.get("domain"), c.get("path") or "/"
        campos = (nombre, valor, dominio, ruta)
        if not all(isinstance(x, str) and len(x) <= 4096 for x in campos) or not nombre or not dominio:
            continue
        if any(ch in x for x in campos for ch in "\t\r\n\x00"):
            continue
        vence = c.get("expirationDate")
        limpias.append({"name": nombre, "value": valor, "domain": dominio, "path": ruta, "secure": c.get("secure") is True,
                        "expires": int(vence) if isinstance(vence, (int, float)) and not isinstance(vence, bool) and vence > 0 else 0})
    return limpias


def escribir_cookies(ruta: Path, cookies: list[dict]) -> Path:
    """Archivo cookies.txt (formato Netscape, el que lee yt-dlp)."""
    lineas = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        sub = "TRUE" if c["domain"].startswith(".") else "FALSE"
        lineas.append("\t".join([c["domain"], sub, c["path"], "TRUE" if c["secure"] else "FALSE", str(c["expires"]),
                                 c["name"], c["value"]]))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def _lista_vacia() -> ErrorGestor:
    # Lo típico: se envió la dirección de un inicio o feed (youtube.com/ -> «recommended») en vez de la del video.
    return ErrorGestor(CodigoError.CONTENIDO_NO_DISPONIBLE, "En esta dirección no hay ningún video que descargar.",
                       causa="Es una página de inicio, un feed o una lista privada o vacía, no un video concreto.",
                       solucion="Abre el video en su propia página y añádelo desde ahí, o haz clic derecho "
                                "sobre su miniatura → «Añadir a Gestor de Descargas».")


class GestorCola:
    def __init__(self, db: BaseDatos, *, ffmpeg_dir: Path | None = None, deno: Path | None = None,
                 extraer: Callable[..., InfoContenido] = obtener_info,
                 descargar_fn: Callable = descargar, permitir_interno: bool = False):
        self.db = db
        self.ffmpeg_dir = ffmpeg_dir
        asegurar_ffmpeg_en_path(ffmpeg_dir)           # antes de cualquier descarga: yt-dlp lo necesita para bajar trozos
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
        # Sesión del navegador (cookies) que mandó la extensión para cada tarea. Solo en memoria: nunca se guarda
        # en la base de datos y desaparece al apagar el servidor o al terminar la descarga.
        self._cookies: dict[str, list[dict]] = {}

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
    def detectar(self, url: str, origen: str | None = None, opciones: dict | None = None,
                 cookies: list | None = None) -> Tarea:
        """Registra un recurso detectado (estado DETECTADO) SIN descargar: espera la autorización del usuario.

        Las opciones elegidas (p. ej. «solo audio») se guardan y se usan cuando el usuario pulse «Descargar».
        """
        url = validar_url(url, permitir_interno=self._permitir_interno)
        self._validar_elecciones(opciones)
        t = self.db.crear_tarea(url, origen=origen, opciones=opciones, estado=EstadoTarea.DETECTADO)
        self._guardar_cookies(t.id, cookies)
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
            info, _fuente = self._analizar_con_respaldo(t, None)
            if info.es_lista and not info.entradas:
                raise _lista_vacia()             # se avisa ya, no al pulsar «Descargar»
            d = None if info.es_lista else drm.evaluar(t.url, info)
        except Exception as exc:
            e = drm.enriquecer_error(t.url, exc if isinstance(exc, ErrorGestor) else traducir_excepcion(exc))
            with self._lock:                         # que no pise un «Descargar» o un renombrado de grupo a la vez
                t = self.db.obtener_tarea(id_)
                if t is not None and t.estado == EstadoTarea.DETECTADO:
                    t.error = {"codigo": e.codigo.value, "mensaje": e.mensaje, "causa": e.causa,
                               "solucion": e.solucion, "detalle": e.detalle_tecnico}
                    self._publicar(t)
            return
        with self._lock:
            t = self.db.obtener_tarea(id_)
            if t is None or t.estado != EstadoTarea.DETECTADO:
                return                               # mientras tanto se inició o se eliminó
            t.titulo, t.sitio, t.miniatura, t.duracion = self._titulo(t, info), info.sitio, info.miniatura_url, info.duracion_seg
            if info.es_lista:
                t.titulo = f"Lista: {info.titulo} ({len(info.entradas)} videos)"
                t.notas = ["Es una lista de reproducción: al descargarla se agrega cada video a la cola."]
            else:
                t.notas = [d.motivo] if d.nivel != drm.Compatibilidad.COMPATIBLE else []
                tamanos = texto_tamanos(info)
                if tamanos:
                    t.notas.append(tamanos)
            self._publicar(t)

    def buscar_repetida(self, url: str, opciones: dict | None = None) -> Tarea | None:
        """La tarea de la lista con el MISMO video y el mismo tipo de descarga (video, audio…), si la hay.

        No cuentan las canceladas ni las que fallaron: volver a añadirlas es lo normal.
        """
        clave = clave_video(url)
        tipo = lambda o: ((o or {}).get("modo", "video"), [list(map(float, x)) for x in (o or {}).get("tramos") or []])  # noqa: E731
        vigentes = [e for e in EstadoTarea if e not in (EstadoTarea.CANCELADO, EstadoTarea.ERROR)]
        for t in self.db.listar_tareas(estados=vigentes, limite=2000):
            if clave_video(t.url) == clave and tipo(t.opciones) == tipo(opciones):     # otro trozo del mismo video no es repetido
                return t
        return None

    def exigir_no_repetida(self, url: str, opciones: dict | None = None) -> None:
        """Lanza ErrorGestor(DUPLICADO) si ese video ya está en la lista; quien llama pregunta si añadirlo otra vez."""
        t = self.buscar_repetida(url, opciones)
        if t is not None:
            raise ErrorGestor(CodigoError.DUPLICADO, "Este video ya está en tu lista.",
                              causa=f"«{t.titulo or t.url}» ({ETIQUETA_ESTADO.get(t.estado, t.estado.value)}).",
                              solucion="Si quieres descargarlo otra vez, confírmalo.")

    def encolar(self, url: str, *, origen: str | None = None, opciones: dict | None = None,
                destino_manual: str | None = None, permitir_repetida: bool = False,
                cookies: list | None = None) -> Tarea:
        url = validar_url(url, permitir_interno=self._permitir_interno)
        self._validar_elecciones(opciones)
        with self._lock:
            for t in ([] if permitir_repetida else self.db.listar_tareas(estados=[EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS])):
                if t.url == url and t.opciones == (opciones or {}):
                    return t                       # ya está en la cola: no se duplica
            t = self.db.crear_tarea(url, origen=origen, opciones=opciones, destino_manual=destino_manual)
        self._guardar_cookies(t.id, cookies)
        self._publicar(t)
        self._cola.put(t.id)
        return t

    # --- grupos -----------------------------------------------------------------
    def grupos(self) -> list[dict]:
        """Grupos creados y cuántas descargas tiene cada uno («esperando» = añadidas al grupo, sin descargar aún)."""
        prefs = self.prefs()
        vacio = lambda g: {"nombre": g, "esperando": 0, "activas": 0, "listas": 0, "errores": 0, "total": 0}  # noqa: E731
        cuenta: dict[str, dict] = {g: vacio(g) for g in prefs.grupos}
        for t in self.db.listar_tareas(limite=5000):
            g = (t.opciones or {}).get("grupo")
            if not g:
                continue
            c = cuenta.setdefault(g, vacio(g))
            c["total"] += 1
            if t.estado == EstadoTarea.DETECTADO:
                c["esperando"] += 1
            elif t.estado in (EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS):
                c["activas"] += 1
            elif t.estado == EstadoTarea.COMPLETADO:
                c["listas"] += 1
            elif t.estado == EstadoTarea.ERROR:
                c["errores"] += 1
        return [{**c, "activo": c["nombre"] == prefs.grupo_activo} for c in cuenta.values()]

    def crear_grupo(self, nombre: str, activar: bool = True) -> None:
        nombre = nombre.strip()
        prefs = self.prefs()
        if nombre not in prefs.grupos:
            prefs.grupos = (*prefs.grupos, nombre)
        if activar:
            prefs.grupo_activo = nombre
        self.db.guardar_preferencias(prefs)
        self._notificar({"id": "*", "estado": "grupos"})

    def renombrar_grupo(self, nombre: str, nuevo: str) -> None:
        nuevo = nuevo.strip()
        prefs = self.prefs()
        prefs.grupos = tuple(dict.fromkeys(nuevo if g == nombre else g for g in prefs.grupos))
        if prefs.grupo_activo == nombre:
            prefs.grupo_activo = nuevo
        self.db.guardar_preferencias(prefs)
        with self._lock:
            for t in self.db.listar_tareas(limite=5000):
                if (t.opciones or {}).get("grupo") == nombre:
                    t.opciones = {**t.opciones, "grupo": nuevo}
                    self._publicar(t)
        self._notificar({"id": "*", "estado": "grupos"})

    def eliminar_grupo(self, nombre: str) -> int:
        """Quita el grupo y lo que esperaba en él (lo ya descargado sigue en el historial y en el disco)."""
        n = 0
        for t in self.db.listar_tareas(estados=[EstadoTarea.DETECTADO], limite=5000):
            if (t.opciones or {}).get("grupo") == nombre:
                self.eliminar(t.id)
                n += 1
        prefs = self.prefs()
        prefs.grupos = tuple(g for g in prefs.grupos if g != nombre) or ("General",)
        if prefs.grupo_activo not in prefs.grupos:
            prefs.grupo_activo = prefs.grupos[0]
        self.db.guardar_preferencias(prefs)
        self._notificar({"id": "*", "estado": "grupos"})
        return n

    def iniciar_grupo(self, nombre: str) -> int:
        """Descarga todo lo que espera en el grupo, en el orden en que se añadió. Devuelve cuántas empezaron."""
        n = 0
        for t in reversed(self.db.listar_tareas(estados=[EstadoTarea.DETECTADO], limite=5000)):
            if (t.opciones or {}).get("grupo") == nombre:
                self.iniciar_detectada(t.id)
                n += 1
        return n

    def iniciar_detectada(self, id_: str, opciones: dict | None = None, destino_manual: str | None = None) -> Tarea:
        self._validar_elecciones(opciones)
        with self._lock:                           # el hilo que lee el título podría guardar la tarea a la vez
            t = self._requerir(id_)
            if t.estado != EstadoTarea.DETECTADO:
                raise ErrorGestor(CodigoError.CONFIGURACION, "Solo se pueden iniciar tareas detectadas.")
            if opciones:                           # lo elegido ahora manda, pero el grupo y los enlaces directos se conservan
                opciones = {**{k: v for k, v in (t.opciones or {}).items() if k in ("grupo", "medios", "titulo_pagina")}, **opciones}
            t.estado, t.opciones, t.destino_manual = EstadoTarea.PENDIENTE, opciones or t.opciones or {}, destino_manual or t.destino_manual
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

    def cancelar_todas(self) -> int:
        """Cancela todo lo que está detectado, en espera o en curso. Devuelve cuántas tareas afectó."""
        n = 0
        for t in self.db.listar_tareas(estados=[EstadoTarea.DETECTADO, EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS], limite=10000):
            self.cancelar(t.id)
            n += 1
        return n

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
        self._cookies.pop(id_, None)
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
            info = self._consultar(url)
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

    def _guardar_cookies(self, id_: str, cookies: list | None) -> None:
        limpias = limpiar_cookies(cookies)
        if limpias:
            self._cookies[id_] = limpias

    def _sesion(self, id_: str | None) -> dict:
        """Sesión para yt-dlp: las cookies que mandó la extensión para esa tarea o, si no hay, lo elegido en Ajustes."""
        if id_ and id_ in self._cookies:
            return {"cookiefile": str(escribir_cookies(carpeta_datos() / "sesiones" / f"{id_}.txt", self._cookies[id_]))}
        return opciones_sesion(self.prefs())

    def _consultar(self, url: str, extra: dict | None = None, id_: str | None = None) -> InfoContenido:
        """Consulta la URL con la sesión del navegador (si hay) y las opciones de red extra (Referer, imitar a Chrome)."""
        if self._extraer is obtener_info:
            opciones = {**self._sesion(id_), **(extra or {})}
            return obtener_info(url, extraer=lambda u: _extraer_con_ytdlp(u, opciones), permitir_interno=self._permitir_interno)
        return self._extraer(url, permitir_interno=self._permitir_interno)

    def _candidatos(self, t: Tarea) -> list[tuple[str, str | None, bool]]:
        """Formas de bajar el video, de la más normal a la de respaldo: (url, página de origen, imitar a Chrome).

        1. la página tal cual; 2. la página presentándose como Chrome (Cloudflare y similares);
        3. los enlaces directos que la extensión vio pasar mientras el video se reproducía (con la página como Referer).
        """
        imitar = puede_imitar_navegador() and not self._permitir_interno
        # Si se añadió un enlace directo desde una página, esa página va como Referer (muchos servidores lo exigen).
        propio = t.origen if t.origen and t.origen != t.url else None
        salida = [(t.url, propio, False)] + ([(t.url, propio, True)] if imitar else [])
        referer = t.origen or t.url
        for m in (t.opciones or {}).get("medios") or []:
            try:
                m = validar_url(m, permitir_interno=self._permitir_interno)
            except ErrorGestor:
                continue
            if m != t.url:
                salida.append((m, referer, False))
                if imitar:
                    salida.append((m, referer, True))
        return salida

    def _analizar_con_respaldo(self, t: Tarea, ev: threading.Event | None) -> tuple[InfoContenido, tuple]:
        """Analiza probando cada candidato hasta que uno funcione; devuelve (info, candidato que funcionó)."""
        primer_error: ErrorGestor | None = None
        for url, referer, imitar in self._candidatos(t):
            if ev is not None and ev.is_set():
                raise ErrorGestor(CodigoError.CANCELADO, "Cancelada.")
            try:
                if not self._permitir_interno:
                    verificar_resolucion(url)
                extra = opciones_red(referer, imitar)
                info = self._extraer_cancelable(url, ev, extra, t.id) if ev is not None else self._consultar(url, extra, t.id)
                return info, (url, referer, imitar)
            except Exception as exc:
                e = exc if isinstance(exc, ErrorGestor) else traducir_excepcion(exc)
                if e.codigo == CodigoError.CANCELADO or (primer_error is None and e.codigo in _SIN_RESPALDO):
                    raise e from None
                primer_error = primer_error or e        # el error de la página es el que mejor explica qué pasó
        raise primer_error or ErrorGestor(CodigoError.DESCONOCIDO, "No se pudo analizar el enlace.")

    @staticmethod
    def _titulo(t: Tarea, info: InfoContenido) -> str:
        """Si se bajó por enlace directo, yt-dlp da como título el nombre del archivo: mejor el de la página."""
        pagina = (t.opciones or {}).get("titulo_pagina")
        if pagina and (info.sitio or "").lower() in ("generic", "html5mediaembed") and info.url != t.url:
            return pagina
        return info.titulo or pagina or "Sin título"

    def _extraer_cancelable(self, url: str, ev: threading.Event, extra: dict | None = None,
                            id_: str | None = None) -> InfoContenido:
        """Consulta la URL sin quedarse colgado: si el usuario cancela, deja de esperar al sitio."""
        resultado: dict = {}

        def trabajo() -> None:
            try:
                resultado["info"] = self._consultar(url, extra, id_)
            except BaseException as exc:      # se re-lanza en el hilo que espera
                resultado["error"] = exc
        h = threading.Thread(target=trabajo, name="analisis", daemon=True)
        h.start()
        while h.is_alive():
            h.join(0.2)
            if ev.is_set():
                raise ErrorGestor(CodigoError.CANCELADO, "Cancelada.")
        if "error" in resultado:
            raise resultado["error"]
        return resultado["info"]

    def _expandir_lista(self, t: Tarea, info: InfoContenido) -> None:
        """Una lista de reproducción se convierte en una descarga por video, todas en una misma carpeta."""
        if not info.entradas:
            raise _lista_vacia()
        carpeta = sanear_nombre(info.titulo, maximo=80)
        opciones = {"subcarpeta": carpeta, **t.opciones}      # lo que el usuario eligió prevalece
        ya = {x.url for x in self.db.listar_tareas(estados=[EstadoTarea.PENDIENTE, *ESTADOS_ACTIVOS])
              if x.opciones == opciones}
        nuevas = []
        for url, titulo in info.entradas:
            try:
                url = validar_url(url, permitir_interno=self._permitir_interno)
            except ErrorGestor:
                continue
            if url in ya:
                continue
            h = self.db.crear_tarea(url, origen=t.origen, opciones={k: v for k, v in opciones.items() if k != "medios"},
                                    destino_manual=t.destino_manual)
            if t.id in self._cookies:
                self._cookies[h.id] = self._cookies[t.id]
            h.titulo = titulo
            self.db.guardar_tarea(h)
            nuevas.append(h)
        t.titulo = f"Lista: {info.titulo}"
        t.estado, t.progreso = EstadoTarea.COMPLETADO, 100.0
        t.notas = [f"Lista de {len(nuevas)} videos agregada a la cola; se guardan en la carpeta «{carpeta}»."]
        self._publicar(t)
        for h in nuevas:
            self._publicar(h)
            self._cola.put(h.id)

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
                (carpeta_datos() / "sesiones" / f"{id_}.txt").unlink(missing_ok=True)

    def _procesar(self, id_: str) -> None:
        t = self._requerir(id_)
        ev = self._eventos[id_]
        prefs = self.prefs()
        trabajo = prefs.carpeta_raiz / ".tmp" / id_
        try:
            t.estado, t.error = EstadoTarea.ANALIZANDO, None
            self._publicar(t)
            info, fuente = self._analizar_con_respaldo(t, ev)
            t.titulo, t.sitio, t.miniatura, t.duracion = self._titulo(t, info), info.sitio, info.miniatura_url, info.duracion_seg
            if info.es_lista:
                self._expandir_lista(t, info)
                return

            res = reglas.resolver(t.url, info.sitio, self.db.listar_reglas(solo_activas=True), prefs, t.opciones)
            t.notas = [*(f"Regla aplicada: {n}" for n in res.reglas_aplicadas)]
            if fuente[0] != t.url:
                t.notas.append("La página no se pudo analizar: se baja por el enlace directo que vio la extensión.")
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
            opciones = replace(res.a_opciones(prefs, self.ffmpeg_dir, self.deno), duracion_video=info.duracion_seg,
                               sesion=self._sesion(id_))
            resultado = self._descargar_con_respaldo(t, fuente, opciones, trabajo, alprogreso, ev)

            t.estado, t.progreso = EstadoTarea.PROCESANDO, 100.0
            self._publicar(t)
            manual = Path(t.destino_manual) if t.destino_manual else None
            subcarpeta = res.subcarpeta
            if not subcarpeta and res.campos.get("grupo") and prefs.carpeta_grupo:
                subcarpeta = res.campos["grupo"]           # el grupo se guarda junto, en una carpeta con su nombre
            colocados = organizar(resultado.archivos, prefs, t.titulo or "Sin título",
                                  carpeta_manual=manual, subcarpeta=subcarpeta,
                                  base=Path(res.destino).expanduser() if res.destino else None,
                                  carpeta_propia=bool(res.campos.get("carpeta_propia", True)))
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
        finally:
            if t.estado in (EstadoTarea.COMPLETADO, EstadoTarea.CANCELADO):
                self._cookies.pop(id_, None)      # si falló se conservan: «Reintentar» las vuelve a usar

    def _descargar_con_respaldo(self, t: Tarea, fuente: tuple, opciones, trabajo: Path, alprogreso, ev: threading.Event):
        """Descarga con el candidato que funcionó al analizar y, si falla, prueba los siguientes."""
        candidatos = self._candidatos(t)
        inicio = candidatos.index(fuente) if fuente in candidatos else 0
        primer_error: ErrorGestor | None = None
        for url, referer, imitar in [fuente, *candidatos[inicio + 1:]]:
            if ev.is_set():
                raise ErrorGestor(CodigoError.CANCELADO, "Cancelada.")
            try:
                return self._descargar(url, replace(opciones, referer=referer, imitar_navegador=imitar), trabajo,
                                       progreso=alprogreso, cancelar=ev, permitir_interno=self._permitir_interno)
            except Exception as exc:
                e = exc if isinstance(exc, ErrorGestor) else traducir_excepcion(exc)
                if e.codigo in _SIN_RESPALDO or ev.is_set():
                    raise e from None
                primer_error = primer_error or e
                self._limpiar_trabajo(t)                # el siguiente intento empieza con la carpeta vacía
        raise primer_error or ErrorGestor(CodigoError.DESCONOCIDO, "No se pudo descargar.")
