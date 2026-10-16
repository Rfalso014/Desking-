"""Vinculación extensión <-> aplicación mediante un código que da la aplicación.

Cómo funciona (como emparejar un dispositivo Bluetooth):
  1. La aplicación muestra un CÓDIGO de 8 caracteres (p. ej. K7M2-9QXA) que dura 10 minutos y sirve una sola vez.
  2. El usuario lo escribe en la extensión.
  3. Si es correcto, la aplicación entrega a la extensión un TOKEN secreto (aleatorio, 256 bits).
  4. La extensión envía ese token en cada mensaje; sin token válido, la aplicación no hace nada.
  La aplicación solo guarda el HASH del token: si alguien lee la base de datos, no puede usarlo.
  Se puede revocar cualquier vínculo desde la aplicación.

Protección contra adivinar el código: tras 5 intentos fallidos se bloquea 60 s y el código se renueva.
"""
import hashlib
import secrets
import threading
import time
from collections.abc import Callable

from .db import BaseDatos
from .modelos import CodigoError, ErrorGestor

# Sin caracteres que se confunden (0/O, 1/I/L).
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
LARGO_CODIGO = 8


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalizar_codigo(texto: str) -> str:
    return "".join(c for c in str(texto).upper() if c.isalnum())


def formatear_codigo(codigo: str) -> str:
    return f"{codigo[:4]}-{codigo[4:]}"


class Vinculacion:
    def __init__(self, db: BaseDatos, *, duracion_codigo: float = 600, max_fallos: int = 5,
                 bloqueo: float = 60, reloj: Callable[[], float] = time.monotonic):
        self.db = db
        self._duracion, self._max_fallos, self._bloqueo, self._reloj = duracion_codigo, max_fallos, bloqueo, reloj
        self._lock = threading.RLock()
        self._codigo = ""
        self._vence = 0.0
        self._fallos = 0
        self._bloqueado_hasta = 0.0

    # --- código --------------------------------------------------------------------
    def renovar(self) -> str:
        with self._lock:
            self._codigo = "".join(secrets.choice(ALFABETO) for _ in range(LARGO_CODIGO))
            self._vence = self._reloj() + self._duracion
            self._fallos = 0
            return formatear_codigo(self._codigo)

    def codigo_actual(self) -> tuple[str, int]:
        """(código con formato, segundos que le quedan). Genera uno nuevo si venció."""
        with self._lock:
            if not self._codigo or self._reloj() >= self._vence:
                self.renovar()
            return formatear_codigo(self._codigo), max(0, int(self._vence - self._reloj()))

    # --- emparejar -----------------------------------------------------------------
    def emparejar(self, codigo: str, nombre: str = "Navegador") -> str:
        """Si el código es correcto devuelve un token nuevo; si no, lanza ErrorGestor."""
        with self._lock:
            ahora = self._reloj()
            if ahora < self._bloqueado_hasta:
                raise ErrorGestor(CodigoError.NO_VINCULADO, "Demasiados intentos fallidos.",
                                  causa="Por seguridad, la vinculación se bloquea un momento tras varios errores.",
                                  solucion=f"Espera {int(self._bloqueado_hasta - ahora) + 1} segundos y mira el código nuevo en la aplicación.")
            self.codigo_actual()                       # renueva si venció
            if secrets.compare_digest(normalizar_codigo(codigo), self._codigo):
                token = secrets.token_urlsafe(32)
                self.db.crear_vinculo(_hash(token), (nombre or "Navegador").strip()[:40] or "Navegador")
                self.renovar()                         # el código es de un solo uso
                return token
            self._fallos += 1
            if self._fallos >= self._max_fallos:
                self._bloqueado_hasta = ahora + self._bloqueo
                self.renovar()                         # el código anterior ya no vale
            raise ErrorGestor(CodigoError.NO_VINCULADO, "El código no es correcto.",
                              causa="El código es de 8 caracteres, dura 10 minutos y se usa una sola vez.",
                              solucion="Revisa el código que muestra la aplicación (pestaña «Extensión»).")

    # --- token ----------------------------------------------------------------------
    def validar_token(self, token: str | None) -> bool:
        if not token:
            return False
        h = _hash(token)
        v = self.db.buscar_vinculo(h)
        if v:
            self.db.tocar_vinculo(v["id"])
        return bool(v)

    def desvincular_token(self, token: str) -> bool:
        v = self.db.buscar_vinculo(_hash(token))
        if v:
            self.db.eliminar_vinculo(v["id"])
        return bool(v)

    def listar(self) -> list[dict]:
        return self.db.listar_vinculos()

    def revocar(self, id_: int) -> None:
        self.db.eliminar_vinculo(id_)
