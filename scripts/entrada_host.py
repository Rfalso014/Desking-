"""Punto de entrada del ejecutable GestorHost.exe (host de Native Messaging)."""
import sys

from gestor.nativo.host import main

if __name__ == "__main__":
    sys.exit(main())
