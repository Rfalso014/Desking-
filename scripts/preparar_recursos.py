"""Prepara lo que necesita el empaquetado: icono .ico y ficha de versión de Windows para los .exe.

Lo llama scripts/empaquetar.ps1. Escribe en build/recursos/ (ignorado por git).
Uso: python scripts/preparar_recursos.py   (imprime la versión, para que el script la use en el instalador)
"""
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
from gestor import __version__  # noqa: E402

DESTINO = RAIZ / "build" / "recursos"
DESTINO.mkdir(parents=True, exist_ok=True)

# Icono con varios tamaños (Windows elige el adecuado para la barra de tareas, el escritorio, etc.)
Image.open(RAIZ / "extension" / "icons" / "128.png").convert("RGBA").save(
    DESTINO / "icono.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128)])

numeros = tuple(int(n) for n in __version__.split(".")) + (0,) * (4 - len(__version__.split(".")))
(DESTINO / "version.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeros}, prodvers={numeros}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040A04B0', [
      StringStruct('CompanyName', 'Desking'),
      StringStruct('FileDescription', 'Gestor de Descargas'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductName', 'Gestor de Descargas'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('OriginalFilename', 'GestorDescargas.exe')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])
  ]
)
""", encoding="utf-8")
print(__version__)
