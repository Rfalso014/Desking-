r"""Actualiza yt-dlp (y su solucionador de desafíos JS) en el entorno de desarrollo.

yt-dlp se rompe cuando los sitios cambian; actualizarlo es el mantenimiento más frecuente.
Después de actualizar se ejecutan las pruebas para detectar incompatibilidades.

  .\.venv\Scripts\python.exe scripts\actualizar_ytdlp.py
"""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    # Lista de argumentos (sin shell). Se descarga solo desde PyPI, el repositorio oficial.
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp[default]"])
    if r.returncode != 0:
        return r.returncode
    import importlib.metadata as md
    print("yt-dlp instalado:", md.version("yt-dlp"))
    print("Ejecutando pruebas…")
    return subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=RAIZ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
