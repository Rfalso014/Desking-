"""Punto de entrada de GestorDescargas.exe: el panel de control y el servidor web (ver gestor/control.py)."""
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):           # desde el código: `gestor` está en src
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gestor import componentes  # noqa: E402

componentes.activar()       # yt-dlp actualizado desde el gestor (si lo hay) va antes que el incluido en el .exe

from gestor.control import main  # noqa: E402  (debe importarse después de activar los componentes)

if __name__ == "__main__":
    sys.exit(main())
