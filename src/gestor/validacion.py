"""Validación de URL antes de tocar la red.

Objetivos de seguridad:
  - Solo http/https (nada de file://, javascript:, ftp:...).
  - Sin usuario/contraseña dentro de la URL (se filtrarían a logs e historial).
  - Bloquear destinos locales o de red privada (SSRF): localhost, 192.168.x.x, etc.

Límite conocido: aquí solo miramos IPs escritas directamente en la URL. Un
dominio público podría apuntar a una IP privada vía DNS; eso se cubrirá en la
Fase 13 (pruebas y seguridad integrales).
"""
import ipaddress
from urllib.parse import urlsplit

from .modelos import CodigoError, ErrorGestor

_MAX_LARGO_URL = 2048
_NOMBRES_LOCALES = {"localhost", "localhost.localdomain"}


def _es_destino_interno(host: str) -> bool:
    if host.lower().rstrip(".") in _NOMBRES_LOCALES or host.lower().endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False  # es un nombre de dominio, no una IP literal
    # is_global es False para loopback, privadas, link-local, reservadas...
    return not ip.is_global


def validar_url(url: str, *, permitir_interno: bool = False) -> str:
    """Devuelve la URL limpia (sin espacios) o lanza ErrorGestor(URL_INVALIDA).

    `permitir_interno=True` existe solo para pruebas con servidores locales.
    """
    if not isinstance(url, str) or not url.strip():
        raise _invalida("La URL está vacía.")
    url = url.strip()
    if len(url) > _MAX_LARGO_URL:
        raise _invalida("La URL es demasiado larga.")
    if any(c.isspace() or ord(c) < 32 for c in url):
        raise _invalida("La URL contiene espacios o caracteres de control.")

    try:
        partes = urlsplit(url)
        host = partes.hostname  # ya viene en minúsculas y sin corchetes IPv6
        partes.port  # fuerza la validación del puerto (lanza ValueError si es malo)
    except ValueError:
        raise _invalida("La URL tiene un formato inválido.") from None

    if partes.scheme not in ("http", "https"):
        raise _invalida("Solo se admiten enlaces http:// o https://.")
    if not host:
        raise _invalida("La URL no tiene un dominio.")
    if partes.username or partes.password:
        raise _invalida("No se admiten usuario ni contraseña dentro de la URL.")
    if not permitir_interno and _es_destino_interno(host):
        raise _invalida("No se admiten direcciones locales ni de red privada.")
    return url


def _invalida(mensaje: str) -> ErrorGestor:
    return ErrorGestor(
        CodigoError.URL_INVALIDA, mensaje,
        causa="La dirección no cumple las reglas de seguridad de la aplicación.",
        solucion="Copia el enlace completo desde la barra de direcciones del navegador.",
    )
