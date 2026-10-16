import json
import shutil
import subprocess
import uuid
import winreg
from pathlib import Path

import pytest

from gestor.nativo import instalador
from gestor.nativo.comun import NOMBRE_HOST

RAIZ = Path(__file__).resolve().parents[1]
EXT = RAIZ / "extension"


def test_manifest_de_la_extension():
    m = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3
    # Permisos mínimos: nada de acceso a todos los sitios.
    assert set(m["permissions"]) == {"contextMenus", "nativeMessaging", "storage", "activeTab", "scripting"}
    assert "host_permissions" not in m
    # El botón flotante necesita un content script en las páginas web (solo http/https; nunca file:// ni chrome://).
    cs = m["content_scripts"]
    assert len(cs) == 1 and cs[0]["js"] == ["content.js"] and set(cs[0]["matches"]) == {"http://*/*", "https://*/*"}
    for ruta in [m["background"]["service_worker"], m["action"]["default_popup"], *m["icons"].values()]:
        assert (EXT / ruta).exists(), ruta


def test_id_estable_y_con_formato_de_chrome():
    i = instalador.id_extension()
    assert len(i) == 32 and set(i) <= set("abcdefghijklmnop")
    assert i == instalador.id_extension()


def test_content_script_es_seguro():
    c = (EXT / "content.js").read_text(encoding="utf-8")
    assert "isTrusted" in c                 # ignora clics falsos de la página
    assert 'mode: "closed"' in c            # la página no puede manipular el botón
    assert "import " not in c and "export " not in c    # los content scripts clásicos no usan módulos


def test_el_popup_solo_usa_elementos_que_existen_en_el_html():
    import re
    html = (EXT / "popup.html").read_text(encoding="utf-8")
    js = (EXT / "popup.js").read_text(encoding="utf-8")
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    usados = set(re.findall(r'\$\("([^"]+)"\)', js)) | {f"pestana-{n}" for n in ("pagina", "cola", "ajustes")}
    assert usados - ids_html == set(), f"El JS usa ids que no existen en el HTML: {usados - ids_html}"
    assert "popup.js" in html and 'type="module"' in html


def test_el_boton_flotante_respeta_el_ajuste_del_usuario():
    c = (EXT / "content.js").read_text(encoding="utf-8")
    assert "botonFlotante" in c and "if (!activo) return;" in c


def test_popup_no_usa_innerhtml():
    # Regla de seguridad: el texto de páginas externas se inserta solo con textContent.
    for f in ("popup.js", "background.js", "util.js", "content.js"):
        codigo = (EXT / f).read_text(encoding="utf-8")
        assert "innerHTML" not in codigo and "eval(" not in codigo, f


@pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")
def test_pruebas_javascript_de_la_extension():
    r = subprocess.run(["node", "--test", str(EXT / "test" / "util.test.mjs")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.fixture
def base_falsa():
    base = rf"Software\GestorPruebas-{uuid.uuid4().hex}\NativeMessagingHosts"
    yield (base,)
    for sub in (rf"{base}\{NOMBRE_HOST}", base, base.split("\\")[0] + "\\" + base.split("\\")[1]):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
        except OSError:
            pass


def test_instalar_y_desinstalar(tmp_path, base_falsa):
    r = instalador.instalar(python="C:/Python/python.exe", proyecto=tmp_path / "proy", datos=tmp_path, bases=base_falsa)
    man = json.loads(Path(r["manifiesto"]).read_text(encoding="utf-8"))
    assert man["name"] == NOMBRE_HOST and man["type"] == "stdio"
    assert man["allowed_origins"] == [f"chrome-extension://{instalador.id_extension()}/"]   # sin comodines
    assert Path(man["path"]).exists()
    bat = Path(man["path"]).read_text(encoding="utf-8")
    assert "gestor.nativo.host" in bat and "%*" in bat
    cfg = json.loads((tmp_path / "host.json").read_text(encoding="utf-8"))
    assert cfg["origenes_permitidos"] == man["allowed_origins"] and cfg["comando_app"][-2:] == ["-m", "gestor.app"]
    assert instalador.estado(bases=base_falsa)[base_falsa[0]] == str(r["manifiesto"])

    instalador.desinstalar(datos=tmp_path, bases=base_falsa)
    assert instalador.estado(bases=base_falsa)[base_falsa[0]] is None
    assert not (tmp_path / "nativo").exists() and not (tmp_path / "host.json").exists()
    instalador.desinstalar(datos=tmp_path, bases=base_falsa)           # repetir no falla


def test_el_boton_flotante_y_el_menu_no_descargan_solo_anaden_a_la_lista():
    """Regla de producto: nada se descarga sin que el usuario pulse «Descargar»."""
    fondo = (EXT / "background.js").read_text(encoding="utf-8")
    contenido = (EXT / "content.js").read_text(encoding="utf-8")
    menu = fondo[fondo.index("const MENU"):fondo.index("chrome.runtime.onInstalled")]
    assert 'id: "detectar"' in menu and "encolar" not in menu
    manejador_menu = fondo[fondo.index("chrome.contextMenus.onClicked"):fondo.index("// --- Insignia")]
    assert 'enviar("detectar"' in manejador_menu and 'enviar("encolar"' not in manejador_menu
    manejador_boton = fondo[fondo.index('msg.tipo === "detectar-pagina"'):]
    assert 'enviar("detectar"' in manejador_boton and 'enviar("encolar"' not in manejador_boton
    assert "detectar-pagina" in contenido and "encolar" not in contenido
