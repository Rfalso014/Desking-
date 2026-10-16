r"""Registra el host de Native Messaging para Chrome y Edge (usuario actual, sin administrador).

  .\.venv\Scripts\python.exe scripts\instalar_host.py              # instalar
  .\.venv\Scripts\python.exe scripts\instalar_host.py --estado     # ver qué hay registrado
  .\.venv\Scripts\python.exe scripts\instalar_host.py --desinstalar
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gestor.nativo import instalador  # noqa: E402


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--desinstalar":
        instalador.desinstalar()
        print("Host desinstalado.")
    elif arg == "--estado":
        for base, ruta in instalador.estado().items():
            print(f"{base}: {ruta or 'NO registrado'}")
    elif arg == "":
        r = instalador.instalar()
        print("Host instalado.")
        print("ID de la extensión autorizada:", r["extension_id"])
        print("Manifiesto:", r["manifiesto"])
        print("Ahora carga la carpeta 'extension' en chrome://extensions (Modo desarrollador > Cargar descomprimida).")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
