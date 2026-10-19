"""Traducción de excepciones (yt-dlp, sistema operativo) a ErrorGestor.

Regla de oro: solo afirmamos una causa si el mensaje original la indica
claramente. Si no, CodigoError.DESCONOCIDO y causa=None.
"""
import errno

from .modelos import CodigoError, ErrorGestor

# (fragmentos en minúsculas, código, mensaje, causa, solución)
_REGLAS: list[tuple[tuple[str, ...], CodigoError, str, str, str]] = [
    (("drm protected", "drm-protected", "protected by drm", "has drm", "widevine"), CodigoError.CONTENIDO_PROTEGIDO,
     "El contenido parece estar protegido.",
     "El sitio indica que usa protección anticopia (DRM).",
     "Este contenido no se puede descargar con la aplicación. Usa la opción oficial del servicio, si existe."),
    (("unsupported url",), CodigoError.SITIO_NO_COMPATIBLE,
     "Este enlace no es compatible.",
     "yt-dlp no reconoce el sitio o la página no contiene un video detectable.",
     "Prueba con el enlace directo del video, o actualiza yt-dlp."),
    (("requested format is not available", "no video formats found"), CodigoError.FORMATO_NO_DISPONIBLE,
     "El formato pedido no está disponible.",
     "El sitio no ofrece esa combinación de calidad o formato.",
     "Elige otra calidad o 'mejor disponible'."),
    (("ffmpeg not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"), CodigoError.FFMPEG_AUSENTE,
     "No se encontró FFmpeg.",
     "FFmpeg es necesario para unir o convertir audio y video.",
     "Instala FFmpeg o colócalo en la carpeta tools/ffmpeg."),
    (("private video", "video unavailable", "has been removed", "this video is not available",
      "does not exist", "http error 404", "video is private"), CodigoError.CONTENIDO_NO_DISPONIBLE,
     "El contenido no está disponible.",
     "Puede estar eliminado, privado o restringido por región.",
     "Comprueba que el enlace abre en tu navegador."),
    (("cookie database", "cookies database", "failed to decrypt", "could not copy", "dpapi"), CodigoError.AUTENTICACION,
     "No se pudo leer la sesión del navegador.",
     "El navegador elegido tiene su base de cookies bloqueada o cifrada.",
     "Cierra ese navegador por completo y reintenta, prueba con Firefox, o usa un archivo cookies.txt (Configuración → Sesión)."),
    (("sign in", "log in", "login required", "http error 401", "http error 403"), CodigoError.AUTENTICACION,
     "El sitio pide iniciar sesión o negó el acceso.",
     "El contenido requiere una cuenta o permisos.",
     "Inicia sesión en tu navegador y, en Configuración → Sesión, elige ese navegador para que la aplicación use tu sesión."),
    (("urlopen error", "timed out", "name or service not known", "getaddrinfo failed", "connection"),
     CodigoError.CONEXION,
     "No se pudo conectar con el sitio.",
     "Falla de red, o el sitio no responde.",
     "Revisa tu conexión a internet y reintenta."),
]


def traducir_excepcion(exc: BaseException) -> ErrorGestor:
    if isinstance(exc, ErrorGestor):
        return exc
    texto = str(exc)
    if isinstance(exc, PermissionError):
        return ErrorGestor(CodigoError.PERMISOS, "No hay permisos para escribir ahí.",
                           causa="Windows negó el acceso a la carpeta o el archivo.",
                           solucion="Elige otra carpeta de destino o cierra el programa que usa el archivo.",
                           detalle_tecnico=texto)
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return ErrorGestor(CodigoError.ESPACIO_INSUFICIENTE, "No queda espacio en el disco.",
                           causa="El disco de destino está lleno.",
                           solucion="Libera espacio o elige otro disco.", detalle_tecnico=texto)
    bajo = texto.lower()
    for fragmentos, codigo, msg, causa, solucion in _REGLAS:
        if any(f in bajo for f in fragmentos):
            return ErrorGestor(codigo, msg, causa=causa, solucion=solucion, detalle_tecnico=texto)
    return ErrorGestor(CodigoError.DESCONOCIDO, "No se pudo completar la operación.",
                       causa=None, solucion="Reintenta; si persiste, revisa los detalles técnicos.",
                       detalle_tecnico=texto)
