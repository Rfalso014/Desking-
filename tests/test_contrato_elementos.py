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
    dict(video=True, audio=False, subtitulos=False, portada=True, idiomas="es", altura="1080", formatoAudio="mp3", editable=True),
    dict(video=True, audio=True, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="mp3", editable=True),
    dict(video=False, audio=True, subtitulos=False, portada=False, idiomas="es", altura="", formatoAudio="mp3", editable=True),
]


def en_python(c: dict):
    try:
        return opciones_desde_elementos(video=c["video"], audio=c["audio"], subtitulos=c["subtitulos"], idiomas=parsear_idiomas(c["idiomas"]),
                                        portada=c["portada"], altura=c["altura"] or None, formato_audio=c["formatoAudio"],
                                        carpeta=c.get("carpeta"), editable=c.get("editable", False))
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


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_python_y_javascript_reconocen_el_mismo_video():
    from gestor.validacion import clave_video
    urls = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3", "https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://x.com/a/status/1/", "https://x.com/a/status/1",
            "https://vimeo.com/76979871#t=10", "https://www.facebook.com/watch/?v=123", "https://noticias.com/videos/abc/"]
    js = ("import { claveVideo } from './util.js';"
          f"console.log(JSON.stringify({json.dumps(urls)}.map(claveVideo)));")
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, cwd=str(EXT))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == [clave_video(u) for u in urls]
