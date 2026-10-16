"""Protocolo de mensajes extensión <-> host <-> aplicación (JSON, versión 1).

Petición : {"v": 1, "id": "abc", "accion": "encolar", "token": "<token de vinculación>", "datos": {...}}
Respuesta: {"v": 1, "id": "abc", "ok": true,  "datos": {...}}
           {"v": 1, "id": "abc", "ok": false, "error": {"codigo", "mensaje", "causa", "solucion"}}

Se valida de forma ESTRICTA (lista blanca de acciones y de campos). El host lo
valida primero y la aplicación lo vuelve a validar (nunca se confía en quien
envía). Este módulo no importa nada pesado: el host debe arrancar rápido.
"""
import re
from typing import Any

from .catalogo import CAMPOS_ACCION
from .modelos import CodigoError, ErrorGestor, EstadoTarea
from .validacion import validar_url

VERSION = 1
MAX_BYTES_MENSAJE = 1024 * 1024        # 1 MiB (el navegador acepta menos en la respuesta)
_ID_MENSAJE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ID_TAREA = re.compile(r"^[0-9a-f]{12}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_CODIGO = re.compile(r"^[A-Za-z0-9 -]{4,16}$")

# Acciones que se pueden usar SIN estar vinculado.
SIN_TOKEN = {"ping", "emparejar"}
_ESTADOS = {e.value for e in EstadoTarea}

# accion -> (campos obligatorios, campos opcionales)
ACCIONES: dict[str, tuple[set[str], set[str]]] = {
    "ping": (set(), set()),
    "analizar": ({"url"}, set()),
    "detectar": ({"url"}, {"origen"}),
    "encolar": ({"url"}, {"origen", "opciones"}),
    "iniciar": ({"id"}, {"opciones"}),
    "listar": (set(), {"estados", "texto", "limite"}),
    "estado": ({"id"}, set()),
    "cancelar": ({"id"}, set()),
    "reintentar": ({"id"}, set()),
    "eliminar": ({"id"}, set()),
    "emparejar": ({"codigo"}, {"nombre"}),
    "desvincular": (set(), set()),
    "abrir_carpeta": ({"id"}, set()),
    "limpiar": (set(), set()),
}


def _malo(msg: str) -> ErrorGestor:
    return ErrorGestor(CodigoError.COMUNICACION, msg, causa="El mensaje recibido no cumple el protocolo.",
                       solucion="Actualiza la extensión y la aplicación a la misma versión.")


def validar_mensaje(msg: Any) -> dict:
    """Devuelve un mensaje saneado (copia) o lanza ErrorGestor(COMUNICACION / URL_INVALIDA)."""
    if not isinstance(msg, dict):
        raise _malo("El mensaje debe ser un objeto JSON.")
    extra = set(msg) - {"v", "id", "accion", "datos", "token"}
    if extra:
        raise _malo(f"Campos no permitidos: {sorted(extra)}.")
    if msg.get("v") != VERSION:
        raise _malo(f"Versión de protocolo no admitida: {msg.get('v')!r}.")
    if not isinstance(msg.get("id"), str) or not _ID_MENSAJE.match(msg["id"]):
        raise _malo("Identificador de mensaje no válido.")
    accion = msg.get("accion")
    if accion not in ACCIONES:
        raise _malo(f"Acción desconocida: {accion!r}.")
    token = msg.get("token")
    if token is not None and (not isinstance(token, str) or not _TOKEN.match(token)):
        raise _malo("Token no válido.")
    datos = msg.get("datos", {})
    if not isinstance(datos, dict):
        raise _malo("'datos' debe ser un objeto.")
    obligatorios, opcionales = ACCIONES[accion]
    if set(datos) - obligatorios - opcionales:
        raise _malo(f"Datos no permitidos para {accion!r}: {sorted(set(datos) - obligatorios - opcionales)}.")
    if obligatorios - set(datos):
        raise _malo(f"Faltan datos para {accion!r}: {sorted(obligatorios - set(datos))}.")

    limpio: dict[str, Any] = {}
    if "url" in datos:
        if not isinstance(datos["url"], str):
            raise _malo("La URL debe ser texto.")
        limpio["url"] = validar_url(datos["url"])           # lanza URL_INVALIDA si es peligrosa
    if "origen" in datos:
        o = datos["origen"]
        try:                                                 # el origen es informativo: si es raro, se descarta
            limpio["origen"] = validar_url(o) if isinstance(o, str) else None
        except ErrorGestor:
            limpio["origen"] = None
    if "id" in datos:
        if not isinstance(datos["id"], str) or not _ID_TAREA.match(datos["id"]):
            raise _malo("Identificador de tarea no válido.")
        limpio["id"] = datos["id"]
    if "opciones" in datos:
        op = datos["opciones"]
        if not isinstance(op, dict):
            raise _malo("'opciones' debe ser un objeto.")
        for k, v in op.items():
            if k not in CAMPOS_ACCION or k == "excluir" or not CAMPOS_ACCION[k](v):
                raise _malo(f"Opción no válida: {k!r}.")
        limpio["opciones"] = op
    if "codigo" in datos:
        if not isinstance(datos["codigo"], str) or not _CODIGO.match(datos["codigo"]):
            raise _malo("Código de vinculación no válido.")
        limpio["codigo"] = datos["codigo"]
    if "nombre" in datos:
        n = datos["nombre"]
        if not isinstance(n, str) or not 1 <= len(n.strip()) <= 40:
            raise _malo("Nombre no válido (1 a 40 caracteres).")
        limpio["nombre"] = n.strip()
    if "estados" in datos:
        e = datos["estados"]
        if not isinstance(e, list) or len(e) > 8 or not all(isinstance(x, str) and x in _ESTADOS for x in e):
            raise _malo("Lista de estados no válida.")
        limpio["estados"] = e
    if "texto" in datos:
        if not isinstance(datos["texto"], str) or len(datos["texto"]) > 200:
            raise _malo("Texto de búsqueda no válido.")
        limpio["texto"] = datos["texto"]
    if "limite" in datos:
        l = datos["limite"]
        if not isinstance(l, int) or isinstance(l, bool) or not 1 <= l <= 200:
            raise _malo("Límite no válido (1 a 200).")
        limpio["limite"] = l
    return {"v": VERSION, "id": msg["id"], "accion": accion, "token": token, "datos": limpio}


def respuesta_ok(id_: str, datos: dict | None = None) -> dict:
    return {"v": VERSION, "id": id_, "ok": True, "datos": datos or {}}


def respuesta_error(id_: str, e: ErrorGestor) -> dict:
    return {"v": VERSION, "id": id_, "ok": False,
            "error": {"codigo": e.codigo.value, "mensaje": e.mensaje, "causa": e.causa, "solucion": e.solucion}}
