"""Punto de entrada del ejecutable GestorDescargas.exe (aplicación de escritorio)."""
import sys

from gestor import componentes

componentes.activar()       # yt-dlp actualizado desde la app (si lo hay) va antes que el incluido en el .exe

from gestor.app import main  # noqa: E402  (debe importarse después de activar los componentes)

if __name__ == "__main__":
    sys.exit(main())
