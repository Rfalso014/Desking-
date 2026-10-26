"""API de la aplicación: traduce una petición ya validada en una llamada a la cola.

La usan la página web (con el token local que el servidor pone en la propia página) y la extensión (con el token
que recibió al vincularse con el código). Cada mensaje se valida otra vez aquí con `protocolo.validar_mensaje`.

Recuerda: la extensión y la página solo piden cosas; las descargas las ejecuta el servidor.
"""
import os
import secrets
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

from . import __version__, drm
from .actualizador import Actualizador, version_extension
from .catalogo import CONTENEDORES_VIDEO, FORMATOS_AUDIO
from .cola import GestorCola
from .config import NAVEGADORES_SESION, PERFILES_VELOCIDAD, Preferencias
from .modelos import CodigoError, ErrorGestor, EstadoTarea, Tarea
from .organizador import ORGANIZACIONES, POLITICAS
from .protocolo import SIN_TOKEN, SOLO_WEB, respuesta_error, respuesta_ok, validar_mensaje
from .vinculacion import Vinculacion

_CLAVES_RESUMEN = ("id", "url", "titulo", "sitio", "estado", "progreso", "velocidad_bps", "eta_seg", "origen", "miniatura",
                   "duracion", "error", "notas", "intentos", "carpeta_final", "archivos", "opciones", "creado")


def tarea_resumen(t: Tarea | dict) -> dict:
    """Versión compacta de una tarea (sin rutas de archivos ni detalles técnicos del error)."""
    d = t.a_dict() if isinstance(t, Tarea) else t
    err = d.get("error") and {k: d["error"].get(k) for k in ("codigo", "mensaje", "causa", "solucion")}
    op = {k: v for k, v in (d.get("opciones") or {}).items() if k != "medios"}
    estado = d["estado"].value if isinstance(d["estado"], EstadoTarea) else d["estado"]
    return {"id": d["id"], "url": d["url"], "titulo": d.get("titulo"), "sitio": d.get("sitio"), "estado": estado,
            "progreso": d.get("progreso"), "velocidad": d.get("velocidad_bps"), "eta": d.get("eta_seg"),
            "origen": d.get("origen"), "miniatura": d.get("miniatura"), "duracion": d.get("duracion"), "error": err,
            "notas": (d.get("notas") or [])[:5], "intentos": d.get("intentos", 0), "carpeta_final": d.get("carpeta_final"),
            "archivos": len(d.get("archivos") or []), "opciones": op, "grupo": op.get("grupo"), "creado": d.get("creado")}


def info_resumen(info, diag: drm.Diagnostico) -> dict:
    formatos = [{"id": f.id, "ext": f.extension, "tipo": f.tipo.value, "altura": f.altura,
                 "tamano": f.tamano_bytes, "estimado": f.tamano_es_estimado, "drm": f.tiene_drm}
                for f in info.formatos[-100:]]          # los últimos son los de más calidad
    return {"titulo": info.titulo, "sitio": info.sitio, "autor": info.autor, "duracion": info.duracion_seg,
            "miniatura": info.miniatura_url, "en_vivo": info.es_en_vivo, "es_lista": info.es_lista,
            "formatos": formatos, "subtitulos": info.subtitulos,
            "diagnostico": {"nivel": diag.nivel.value, "confianza": diag.confianza.value,
                            "motivo": diag.motivo, "alternativas": list(diag.alternativas)}}


def _sin_detalles(estado: dict) -> dict:
    """La interfaz solo necesita qué se actualiza, no las direcciones de descarga."""
    return {**estado, "pendientes": [{k: p.get(k) for k in ("tipo", "nombre", "actual", "nueva")} for p in estado["pendientes"]]}


def _abrir_en_explorador(ruta: str) -> None:
    os.startfile(ruta)  # noqa: S606  (solo carpetas que ya existen: la de una tarea o la de descargas)


def _bool(v): return isinstance(v, bool)


# Preferencias que se pueden leer y cambiar desde la página y la extensión, con su validador.
# La extensión solo puede cambiar las de CAMBIABLES_EXTENSION (lo que se elige al añadir); el resto, la página.
PREFERENCIAS_EDITABLES: dict[str, Callable] = {
    "organizacion": lambda v: v in ORGANIZACIONES and v != "manual",
    "duplicados": lambda v: v in POLITICAS,
    "altura_max": lambda v: v is None or (isinstance(v, int) and not isinstance(v, bool) and 100 <= v <= 8640),
    "contenedor_video": lambda v: v in CONTENEDORES_VIDEO,
    "formato_audio": lambda v: v in FORMATOS_AUDIO,
    "idiomas_subtitulos": lambda v: isinstance(v, list) and 0 < len(v) <= 10 and all(isinstance(i, str) and 2 <= len(i) <= 12 for i in v),
    "descargar_subtitulos": _bool, "descargar_portada": _bool,
    "descargas_simultaneas": lambda v: isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 8,
    "tema": lambda v: v in ("auto", "claro", "oscuro"),
    "velocidad": lambda v: v in PERFILES_VELOCIDAD,
    "reanudar_al_iniciar": _bool, "actualizar_solo": _bool,
    "sesion_navegador": lambda v: v == "ninguno" or v in NAVEGADORES_SESION,
    "carpeta_propia": _bool, "carpeta_grupo": _bool,
    "modo_anadir": lambda v: v in ("instantanea", "grupo"),
    "grupo_activo": lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 60,
}
CAMBIABLES_EXTENSION = {"carpeta_propia", "carpeta_grupo", "modo_anadir", "grupo_activo"}


class Manejador:
    """Ejecuta las acciones del protocolo. `token_web` es el de la página servida por este mismo equipo."""

    def __init__(self, cola: GestorCola, vinculacion: Vinculacion | None = None,
                 abrir_carpeta: Callable[[str], None] = _abrir_en_explorador, token_web: str | None = None):
        self.cola = cola
        self.actualizador: Actualizador | None = None          # el servidor lo fija: «Actualizar»
        self.al_apagar: Callable[[], None] | None = None        # el servidor lo fija
        self.al_reiniciar: Callable[[], None] | None = None     # el servidor lo fija
        self.elegir_carpeta: Callable[[str], str | None] | None = None   # abre el selector de carpetas de Windows
        self.vinculacion = vinculacion or Vinculacion(cola.db)
        self.token_web = token_web or secrets.token_urlsafe(32)
        self._abrir = abrir_carpeta

    def es_web(self, token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(token, self.token_web)

    def manejar(self, bruto) -> dict:
        id_ = bruto.get("id", "?") if isinstance(bruto, dict) and isinstance(bruto.get("id"), str) else "?"
        try:
            m = validar_mensaje(bruto)
            id_ = m["id"]
            web = self.es_web(m["token"])
            if m["accion"] in SOLO_WEB and not web:
                raise ErrorGestor(CodigoError.NO_VINCULADO, "Esta acción solo se puede hacer desde la página del gestor.",
                                  solucion="Ábrela en http://127.0.0.1 desde este equipo.")
            if m["accion"] not in SIN_TOKEN and not web and not self.vinculacion.validar_token(m["token"]):
                raise ErrorGestor(CodigoError.NO_VINCULADO, "La extensión no está vinculada con el gestor.",
                                  causa="Falta el código de vinculación o fue revocado.",
                                  solucion="En la página del gestor abre «Ajustes → Extensión» y escribe su código en la extensión.")
            return respuesta_ok(id_, self._ejecutar(m["accion"], m["datos"], m["token"], web))
        except ErrorGestor as e:
            return respuesta_error(id_, e)
        except Exception as exc:     # nunca dejar caer el servidor por un fallo inesperado
            return respuesta_error(id_, ErrorGestor(CodigoError.DESCONOCIDO, "Error interno del gestor.",
                                                    detalle_tecnico=type(exc).__name__))

    # --- preferencias ------------------------------------------------------------------------------
    def preferencias(self) -> dict:
        from .nativo import autoinicio
        p = self.cola.prefs()
        d = {k: getattr(p, k) for k in PREFERENCIAS_EDITABLES}
        d["idiomas_subtitulos"] = list(p.idiomas_subtitulos)
        d.update(carpeta_raiz=str(p.carpeta_raiz), grupos=list(p.grupos), inicio_windows=autoinicio.activo())
        return d

    def _cambiar_preferencias(self, cambios: dict, web: bool) -> dict:
        from .nativo import autoinicio
        permitidas = set(PREFERENCIAS_EDITABLES) | ({"inicio_windows", "carpeta_raiz"} if web else set())
        if not web:
            permitidas &= CAMBIABLES_EXTENSION
        p = self.cola.prefs()
        for k, v in cambios.items():
            if k not in permitidas:
                raise ErrorGestor(CodigoError.CONFIGURACION, f"No se puede cambiar {k!r} desde aquí.")
            if k == "inicio_windows":
                if not isinstance(v, bool):
                    raise ErrorGestor(CodigoError.CONFIGURACION, "Valor no válido para «Iniciar con Windows».")
                autoinicio.fijar(v)
                continue
            if k == "carpeta_raiz":
                setattr(p, k, _carpeta_valida(v))
                continue
            if not PREFERENCIAS_EDITABLES[k](v):
                raise ErrorGestor(CodigoError.CONFIGURACION, f"Valor no válido para {k!r}.")
            if k == "grupo_activo":
                v = v.strip()
                if v not in p.grupos:
                    p.grupos = (*p.grupos, v)
            setattr(p, k, tuple(v) if isinstance(getattr(p, k), tuple) else v)
        self.cola.db.guardar_preferencias(p)
        return self.preferencias()

    # --- acciones ------------------------------------------------------------------------------------
    def _ejecutar(self, accion: str, d: dict, token: str | None, web: bool) -> dict:
        c, v = self.cola, self.vinculacion
        if accion == "ping":
            r = {"app": "gestor-descargas", "version": 1, "vinculado": web or v.validar_token(token), "web": web,
                 "version_app": __version__, "version_extension": version_extension()}
            if self.actualizador and r["vinculado"]:
                marca = self.actualizador.marca()
                r["actualizacion_id"] = marca.get("id") if marca.get("recargar_extension") else None
                r["hay_actualizacion"] = bool(self.actualizador.estado()["pendientes"])
            return r
        if accion == "mostrar":
            return {}
        if accion == "emparejar":
            return {"token": v.emparejar(d["codigo"], d.get("nombre", "Navegador"))}
        if accion == "desvincular":
            return {"desvinculado": False if web else v.desvincular_token(token)}
        if accion == "analizar":
            r = c.analizar(d["url"])
            return info_resumen(r["info"], r["diagnostico"])
        if accion == "anadir":
            return self._anadir(d)
        if accion in ("detectar", "encolar") and not d.get("forzar"):
            c.exigir_no_repetida(d["url"], d.get("opciones"))       # se pregunta y se reintenta con «forzar»
        if accion == "detectar":
            return tarea_resumen(c.detectar(d["url"], d.get("origen"), d.get("opciones"), cookies=d.get("cookies")))
        if accion == "encolar":
            return tarea_resumen(c.encolar(d["url"], origen=d.get("origen"), opciones=d.get("opciones"),
                                           permitir_repetida=bool(d.get("forzar")), cookies=d.get("cookies")))
        if accion == "cancelar_todas":
            return {"canceladas": c.cancelar_todas()}
        if accion == "iniciar_todas":
            ts = c.listar(estados=[EstadoTarea.DETECTADO], limite=5000)
            for t in reversed(ts):
                c.iniciar_detectada(t.id)
            return {"iniciadas": len(ts)}
        if accion == "limpiar":
            return {"eliminadas": c.limpiar_terminadas()}
        if accion == "iniciar":
            return tarea_resumen(c.iniciar_detectada(d["id"], d.get("opciones")))
        if accion == "resumen":
            return self._resumen()
        if accion == "grupos":
            return {"grupos": c.grupos()}
        if accion == "grupo_crear":
            c.crear_grupo(d["nombre"], activar=True)
            return {"grupos": c.grupos()}
        if accion == "grupo_activar":
            self._cambiar_preferencias({"grupo_activo": d["nombre"]}, web=False)
            return {"grupos": c.grupos()}
        if accion == "grupo_renombrar":
            c.renombrar_grupo(d["nombre"], d["nuevo"])
            return {"grupos": c.grupos()}
        if accion == "grupo_eliminar":
            return {"quitadas": c.eliminar_grupo(d["nombre"]), "grupos": c.grupos()}
        if accion == "grupo_iniciar":
            return {"iniciadas": c.iniciar_grupo(d["nombre"]), "grupos": c.grupos()}
        if accion == "preferencias":
            return self._cambiar_preferencias(d["cambios"], web) if d.get("cambios") else self.preferencias()
        if accion == "vinculos":
            if "revocar" in d:
                v.revocar(d["revocar"])
            codigo, segundos = v.codigo_actual()
            return {"codigo": codigo, "segundos": segundos, "vinculos": v.listar()}
        if accion == "abrir_raiz":
            raiz = c.prefs().carpeta_raiz
            raiz.mkdir(parents=True, exist_ok=True)
            self._abrir(str(raiz))
            return {}
        if accion == "elegir_carpeta":
            if self.elegir_carpeta is None:
                raise ErrorGestor(CodigoError.CONFIGURACION, "No se puede abrir el selector de carpetas.")
            elegida = self.elegir_carpeta(str(c.prefs().carpeta_raiz))
            if elegida:
                return self._cambiar_preferencias({"carpeta_raiz": elegida}, web=True)
            return self.preferencias()
        if accion == "apagar":
            if self.al_apagar:
                self.al_apagar()
            return {}
        if accion in ("actualizacion", "actualizar", "reiniciar"):
            if accion == "reiniciar":
                if self.al_reiniciar is None:
                    raise ErrorGestor(CodigoError.CONFIGURACION, "Este gestor no puede reiniciarse solo.")
                self.al_reiniciar()
                return {}
            a = self.actualizador
            if a is None:
                raise ErrorGestor(CodigoError.CONFIGURACION, "Este gestor no puede actualizarse solo.")
            if accion == "actualizar":
                return _sin_detalles(a.iniciar())
            if "automatico" in d:                                   # casilla «Actualizar automáticamente»
                p = c.db.cargar_preferencias()
                p.actualizar_solo = d["automatico"]
                c.db.guardar_preferencias(p)
            if d.get("buscar") and not a.ocupado():
                a.buscar_en_segundo_plano()
            return _sin_detalles(a.estado())
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

    def _anadir(self, d: dict) -> dict:
        """Añadir con el modo elegido: «instantánea» (empieza ya) o «grupo» (espera en el grupo hasta descargarlo)."""
        c = self.cola
        prefs = c.prefs()
        modo = d.get("modo") or prefs.modo_anadir
        opciones = dict(d.get("opciones") or {})
        if modo == "grupo":
            grupo = (d.get("grupo") or prefs.grupo_activo).strip()
            if grupo not in prefs.grupos:
                c.crear_grupo(grupo, activar=False)
            opciones["grupo"] = grupo
        if not d.get("forzar"):
            c.exigir_no_repetida(d["url"], opciones)
        if modo == "grupo":
            t = c.detectar(d["url"], d.get("origen"), opciones, cookies=d.get("cookies"))
        else:
            t = c.encolar(d["url"], origen=d.get("origen"), opciones=opciones,
                          permitir_repetida=bool(d.get("forzar")), cookies=d.get("cookies"))
        return {**tarea_resumen(t), "modo": modo}

    def _resumen(self) -> dict:
        cuenta = {e.value: 0 for e in EstadoTarea}
        for t in self.cola.listar(limite=5000):
            cuenta[t.estado.value] += 1
        return {"estados": cuenta, "grupos": self.cola.grupos()}


def _carpeta_valida(ruta) -> Path:
    if not isinstance(ruta, str) or not 2 < len(ruta) <= 260 or "\x00" in ruta:
        raise ErrorGestor(CodigoError.CONFIGURACION, "La carpeta no es válida.")
    p = Path(ruta).expanduser()
    if not p.is_absolute():
        raise ErrorGestor(CodigoError.CONFIGURACION, "Escribe la ruta completa de la carpeta (por ejemplo D:\\Videos).")
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ErrorGestor(CodigoError.PERMISOS, "No se pudo usar esa carpeta.", detalle_tecnico=str(e)) from None
    return p


# Para las pruebas: qué campos de Preferencias existen (evita que PREFERENCIAS_EDITABLES se desfase).
CAMPOS_PREFERENCIAS = {f.name for f in fields(Preferencias)}
