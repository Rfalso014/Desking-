import json
import re
import shutil
import subprocess
import uuid
import winreg
from pathlib import Path

import pytest

from gestor.nativo.comun import NOMBRE_HOST_ANTIGUO, quitar_puente_antiguo
from gestor.web.servidor import id_extension

RAIZ = Path(__file__).resolve().parents[1]
EXT = RAIZ / "extension"


def test_manifest_de_la_extension():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3
    # Sin Native Messaging: habla con el gestor web local. cookies = la sesión del sitio al añadir (opcional);
    # webRequest = ver los enlaces directos de video que carga el reproductor.
    assert set(m["permissions"]) == {"contextMenus", "storage", "activeTab", "scripting", "sidePanel", "notifications",
                                     "cookies", "webRequest"}
    assert set(m["host_permissions"]) == {"http://*/*", "https://*/*"}       # nada de file:// ni chrome://
    cs = m["content_scripts"]
    assert len(cs) == 1 and cs[0]["js"] == ["content.js"] and set(cs[0]["matches"]) == {"http://*/*", "https://*/*"}
    # La interfaz es una barra lateral (se abre con el ícono), no una ventanita emergente.
    assert "default_popup" not in m["action"]
    for ruta in [m["background"]["service_worker"], m["side_panel"]["default_path"], *m["icons"].values()]:
        assert (EXT / ruta).exists(), ruta


def test_id_estable_y_con_formato_de_chrome():
    i = id_extension()
    assert len(i) == 32 and set(i) <= set("abcdefghijklmnop")
    assert i == id_extension()


def test_content_script_es_seguro():
    c = (EXT / "content.js").read_text(encoding="utf-8")
    assert "isTrusted" in c                 # ignora clics falsos de la página
    assert 'mode: "closed"' in c            # la página no puede manipular el botón
    assert "import " not in c and "export " not in c    # los content scripts clásicos no usan módulos


def test_el_panel_solo_usa_elementos_que_existen_en_el_html():
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    usados = set(re.findall(r'\$\("([^"]+)"\)', js)) | {f"pestana-{n}" for n in ("pagina", "cola", "ajustes")}
    assert usados - ids_html == set(), f"El JS usa ids que no existen en el HTML: {usados - ids_html}"
    assert "popup.js" in html and 'type="module"' in html


def test_la_pagina_web_solo_usa_elementos_que_existen_en_el_html():
    estatico = RAIZ / "src" / "gestor" / "web" / "estatico"
    html = (estatico / "index.html").read_text(encoding="utf-8")
    js = (estatico / "app.js").read_text(encoding="utf-8")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    usados = set(re.findall(r'\$\("([^"]+)"\)', js)) | {f"vista-{n}" for n in ("descargas", "grupos", "ajustes")}
    assert usados - ids_html == set(), f"app.js usa ids que no existen en index.html: {usados - ids_html}"
    assert 'style="' not in html                         # la política de seguridad (CSP) no permite estilos en línea
    assert "{{TOKEN}}" in html and "{{VERSION}}" in html


def test_el_boton_flotante_respeta_el_ajuste_del_usuario():
    c = (EXT / "content.js").read_text(encoding="utf-8")
    assert "botonFlotante" in c and "if (!activo) return;" in c


def test_nada_usa_innerhtml():
    # Regla de seguridad: el texto de páginas externas se inserta solo con textContent.
    archivos = [EXT / f for f in ("popup.js", "background.js", "util.js", "content.js")]
    archivos.append(RAIZ / "src" / "gestor" / "web" / "estatico" / "app.js")
    for f in archivos:
        codigo = f.read_text(encoding="utf-8")
        assert "innerHTML" not in codigo and "eval(" not in codigo, f


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_pruebas_javascript_de_la_extension():
    r = subprocess.run(["node", "--test", str(EXT / "test" / "util.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_el_boton_y_el_menu_respetan_el_modo_elegido():
    """El botón sobre los videos, el clic derecho y el panel usan «anadir»: el gestor decide, según lo elegido
    («Descargar ya» o «Al grupo»), si descarga al momento o espera en el grupo. Nada llama a «encolar» por su cuenta."""
    fondo = (EXT / "background.js").read_text(encoding="utf-8")
    contenido = (EXT / "content.js").read_text(encoding="utf-8")
    assert '"encolar"' not in fondo and '"detectar"' not in fondo
    assert fondo.count('enviar("anadir"') == 1
    for parte in ("chrome.contextMenus.onClicked", 'msg.tipo === "detectar-pagina"', 'msg.tipo === "anadir-panel"'):
        assert "anadirConLoElegido(" in fondo[fondo.index(parte):fondo.index(parte) + 1500], parte
    assert "detectar-pagina" in contenido and "encolar" not in contenido
    boton_recorte = contenido[contenido.index('rc.descargar.addEventListener("click"'):]
    assert "e.isTrusted" in boton_recorte.splitlines()[1] and 'tipo: "recortar"' in boton_recorte


def test_la_sesion_solo_se_lee_al_anadir():
    fondo = (EXT / "background.js").read_text(encoding="utf-8")
    assert fondo.count("chrome.cookies.getAll") == 1
    funcion = fondo[fondo.index("async function anadirConLoElegido"):fondo.index("const conDefecto")]
    assert "cookiesPara(" in funcion and fondo.count("cookiesPara(") == 2       # la definición y ese único uso
    assert "usarSesion === false" in fondo                                       # se puede desactivar


def test_autoinicio_escribe_y_quita_en_una_clave_de_prueba():
    from gestor.nativo import autoinicio
    clave = rf"Software\GestorDescargasPrueba-{uuid.uuid4().hex}\Run"
    try:
        assert not autoinicio.activo(clave=clave)
        autoinicio.fijar(True, clave=clave)
        assert autoinicio.activo(clave=clave)
        assert autoinicio.comando().endswith("--servidor")          # enciende el servidor web, sin ventanas
        autoinicio.fijar(False, clave=clave)
        assert not autoinicio.activo(clave=clave)
    finally:
        for k in (clave, clave.rsplit("\\", 1)[0]):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, k)
            except OSError:
                pass


def test_se_quita_el_puente_de_la_version_de_escritorio(tmp_path):
    base = rf"Software\GestorPruebas-{uuid.uuid4().hex}\NativeMessagingHosts"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST_ANTIGUO}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "manifiesto.json")
    (tmp_path / "nativo").mkdir()
    (tmp_path / "nativo" / "manifiesto.json").write_text("{}", encoding="utf-8")
    for nombre in ("host.json", "ipc.key"):
        (tmp_path / nombre).write_text("x", encoding="utf-8")
    (tmp_path / "gestor.db").write_text("mis datos", encoding="utf-8")
    try:
        assert quitar_puente_antiguo(datos=tmp_path, bases=(base,)) is True
        with pytest.raises(OSError):
            winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\{NOMBRE_HOST_ANTIGUO}")
        assert sorted(p.name for p in tmp_path.iterdir()) == ["gestor.db"]          # los datos del usuario no se tocan
        assert quitar_puente_antiguo(datos=tmp_path, bases=(base,)) is False        # repetir no falla
    finally:
        for sub in (base, base.rsplit("\\", 1)[0]):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass
