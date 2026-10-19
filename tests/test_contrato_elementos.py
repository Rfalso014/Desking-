"""La lógica «qué descargar» existe en Python (aplicación) y en JavaScript (extensión): deben dar lo MISMO."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from gestor.elementos import opciones_desde_elementos, parsear_idiomas
from gestor.modelos import ErrorGestor

EXT = Path(__file__).resolve().parents[1] / "extension"

CASOS = [
    dict(video=True, audio=False, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="mp3"),
    dict(video=True, audio=False, subtitulos=True, portada=True, idiomas="es, en", altura="720", formatoAudio="mp3"),
    dict(video=True, audio=False, subtitulos=False, portada=False, idiomas="", altura="mejor", formatoAudio="mp3"),
    dict(video=False, audio=True, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="m4a"),
    dict(video=False, audio=True, subtitulos=True, portada=True, idiomas="es", altura="", formatoAudio="original"),
    dict(video=True, audio=True, subtitulos=True, portada=True, idiomas="es,en", altura="1080", formatoAudio="mp3"),
    dict(video=False, audio=False, subtitulos=True, portada=False, idiomas="", altura="", formatoAudio="mp3"),
    dict(video=False, audio=False, subtitulos=True, portada=True, idiomas="pt-BR", altura="", formatoAudio="mp3"),
    dict(video=False, audio=False, subtitulos=False, portada=True, idiomas="es", altura="", formatoAudio="mp3"),
    dict(video=False, audio=False, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="mp3"),   # nada marcado
    dict(video=True, audio=False, subtitulos=True, portada=False, idiomas="es;rm", altura="", formatoAudio="mp3"),   # idioma inválido
    dict(video=True, audio=True, subtitulos=True, portada=True, idiomas="es", altura="720", formatoAudio="mp3", carpeta="  Mi curso "),
    dict(video=False, audio=True, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="mp3", carpeta=""),
]


def en_python(c: dict):
    try:
        return opciones_desde_elementos(video=c["video"], audio=c["audio"], subtitulos=c["subtitulos"], idiomas=parsear_idiomas(c["idiomas"]),
                                        portada=c["portada"], altura=c["altura"] or None, formato_audio=c["formatoAudio"],
                                        carpeta=c.get("carpeta"))
    except ErrorGestor:
        return "error"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_python_y_javascript_generan_las_mismas_opciones():
    js = ("import { construirOpciones } from './util.js';"
          f"const casos = {json.dumps(CASOS)};"
          "console.log(JSON.stringify(casos.map((c) => { try { return construirOpciones(c); } catch { return 'error'; } })));")
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, cwd=str(EXT))
    assert r.returncode == 0, r.stderr
    desde_js = json.loads(r.stdout)
    for caso, resultado_js in zip(CASOS, desde_js):
        assert resultado_js == en_python(caso), caso
