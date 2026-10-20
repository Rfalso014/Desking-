"""Prueba de humo de la Fase 2: ¿el entorno tiene todo lo necesario?

No descarga nada ni usa internet. Solo comprueba que las piezas se pueden
importar y que las versiones son las esperadas.
"""
import sys


def test_python_es_suficientemente_nuevo():
    # sys.version_info es una tupla como (3, 13, 14, ...); la comparamos con (3, 11).
    assert sys.version_info >= (3, 11)


def test_paquete_gestor_se_importa():
    import gestor

    # La versión vive en tres sitios (paquete, pyproject, extensión): deben coincidir.
    import json
    import tomllib
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    assert tomllib.loads((raiz / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"] == gestor.__version__
    assert json.loads((raiz / "extension" / "manifest.json").read_text(encoding="utf-8"))["version"] == gestor.__version__


def test_yt_dlp_se_importa_y_tiene_version():
    from yt_dlp.version import __version__

    assert __version__  # no vacío
    print("yt-dlp", __version__)


def test_pyside6_se_importa():
    # Solo importamos el módulo base (QtCore); no abrimos ventanas.
    from PySide6 import QtCore

    assert QtCore.qVersion()
