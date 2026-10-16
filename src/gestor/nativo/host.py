"""Host de Native Messaging: puente entre el navegador y la aplicación.

El navegador lo lanza como proceso hijo y habla con él por stdin/stdout:
cada mensaje = 4 bytes (longitud, orden nativo) + JSON UTF-8.
El host NO descarga nada: valida el mensaje y lo reenvía a la app por IPC.

IMPORTANTE: stdout es el canal con el navegador. Nunca usar print().
"""
import json
import os
import struct
import subprocess
import sys
import time
from multiprocessing.connection import Client
from pathlib import Path
from typing import BinaryIO

from ..modelos import CodigoError, ErrorGestor
from ..protocolo import MAX_BYTES_MENSAJE, VERSION, respuesta_error, validar_mensaje
from .comun import carpeta_datos, clave_ipc, config_host, direccion_pipe

_MAX_RESPUESTA = 1024 * 1024 - 1024    # el navegador rechaza respuestas del host de más de 1 MiB


def _log(texto: str) -> None:
    """Registro mínimo en un archivo (sin URLs ni datos del usuario)."""
    try:
        with (carpeta_datos() / "host.log").open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {texto}\n")
    except OSError:
        pass


def leer_mensaje(entrada: BinaryIO) -> dict | None:
    """Lee un mensaje del navegador. Devuelve None al cerrarse el canal."""
    cabecera = entrada.read(4)
    if len(cabecera) < 4:
        return None
    (largo,) = struct.unpack("=I", cabecera)
    if largo > MAX_BYTES_MENSAJE:
        raise ErrorGestor(CodigoError.COMUNICACION, "Mensaje demasiado grande.")
    cuerpo = entrada.read(largo)
    if len(cuerpo) < largo:
        return None
    try:
        return json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ErrorGestor(CodigoError.COMUNICACION, "El mensaje no es JSON válido.") from None


def escribir_mensaje(salida: BinaryIO, obj: dict) -> None:
    cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    if len(cuerpo) > _MAX_RESPUESTA:
        id_ = obj.get("id", "?")
        cuerpo = json.dumps(respuesta_error(id_, ErrorGestor(
            CodigoError.COMUNICACION, "La respuesta es demasiado grande."))).encode("utf-8")
    salida.write(struct.pack("=I", len(cuerpo)) + cuerpo)
    salida.flush()


def _abrir_app() -> None:
    """Intenta arrancar la aplicación si el instalador dejó el comando."""
    cmd = config_host().get("comando_app")
    if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd)):
        return
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(cmd, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _conectar(esperar_app: float | None = None):
    """Abre la conexión con la app; si no está abierta, intenta lanzarla y espera."""
    if esperar_app is None:
        esperar_app = float(os.environ.get("GESTOR_ESPERA_APP", "8"))
    lanzada = False
    fin = time.monotonic() + esperar_app
    while True:
        try:
            return Client(direccion_pipe(), family="AF_PIPE", authkey=clave_ipc())
        except (OSError, FileNotFoundError, EOFError):
            if not lanzada:
                lanzada = True
                try:
                    _abrir_app()
                except OSError as exc:
                    _log(f"no se pudo abrir la app: {type(exc).__name__}")
            if time.monotonic() > fin:
                raise ErrorGestor(
                    CodigoError.COMUNICACION, "No se pudo comunicar con la aplicación de escritorio.",
                    causa="La aplicación no está abierta o no está instalada.",
                    solucion="Abre «Gestor de Descargas» e inténtalo de nuevo.") from None
            time.sleep(0.4)


def origen_permitido(origen: str | None) -> bool:
    """Defensa extra: además del navegador, el host comprueba quién lo llamó."""
    permitidos = config_host().get("origenes_permitidos")
    if permitidos is None:
        return True            # sin instalación configurada (desarrollo): confiamos en el navegador
    return origen in permitidos


def procesar(msg_bruto, conexion_app) -> dict:
    """Valida y reenvía. `conexion_app` es una función que devuelve la conexión (inyectable en pruebas)."""
    id_ = msg_bruto.get("id", "?") if isinstance(msg_bruto, dict) and isinstance(msg_bruto.get("id"), str) else "?"
    try:
        msg = validar_mensaje(msg_bruto)           # primera validación, antes de molestar a la app
        con = conexion_app()
        try:
            con.send_bytes(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
            return json.loads(con.recv_bytes(maxlength=MAX_BYTES_MENSAJE).decode("utf-8"))
        finally:
            con.close()
    except ErrorGestor as e:
        return respuesta_error(id_, e)
    except (OSError, EOFError, ValueError):
        return respuesta_error(id_, ErrorGestor(CodigoError.COMUNICACION, "Se perdió la comunicación con la aplicación.",
                                                solucion="Reinicia la aplicación e inténtalo de nuevo."))


def main() -> int:
    if sys.platform == "win32":          # evita que Windows convierta saltos de línea en los bytes binarios
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    entrada, salida = sys.stdin.buffer, sys.stdout.buffer

    origen = sys.argv[1] if len(sys.argv) > 1 else None
    if not origen_permitido(origen):
        _log("origen no permitido")
        return 2
    _log("host iniciado")
    while True:
        try:
            msg = leer_mensaje(entrada)
        except ErrorGestor as e:
            escribir_mensaje(salida, respuesta_error("?", e))
            return 1
        if msg is None:
            return 0                      # el navegador cerró el canal
        escribir_mensaje(salida, procesar(msg, _conectar))


if __name__ == "__main__":
    sys.exit(main())
