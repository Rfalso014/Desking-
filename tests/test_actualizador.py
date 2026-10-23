"""«Actualizar aplicación y extensión»: componentes (yt-dlp desde PyPI), app (git / instalador) y protocolo."""
import hashlib
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

from gestor import __version__, actualizaciones, actualizador, componentes
from gestor.actualizador import Actualizador
from gestor.modelos import CodigoError, ErrorGestor
from gestor.protocolo import validar_mensaje

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def datos_aislados(tmp_path, monkeypatch):
    monkeypatch.setenv("GESTOR_DATOS", str(tmp_path / "datos"))


def _rueda(archivos: dict[str, str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for nombre, texto in archivos.items():
            z.writestr(nombre, texto)
    return b.getvalue()


def _descargador(contenido: bytes, llamadas: list | None = None):
    def descargar(url, sha256, destino, **kw):
        if llamadas is not None:
            llamadas.append((url, sha256, kw))
        Path(destino).write_bytes(contenido)
        return Path(destino)
    return descargar


def _pypi(version: str, contenido: bytes = b"x") -> dict:
    return {"info": {"version": version}, "urls": [
        {"packagetype": "sdist", "filename": f"yt_dlp-{version}.tar.gz", "url": "https://files.pythonhosted.org/s"},
        {"packagetype": "bdist_wheel", "filename": f"yt_dlp-{version}-py3-none-any.whl",
         "url": "https://files.pythonhosted.org/w.whl", "digests": {"sha256": hashlib.sha256(contenido).hexdigest()}, "size": 1}]}


# --- componentes -----------------------------------------------------------------------------------------
def test_ultima_pypi_elige_la_rueda_universal():
    r = componentes.ultima_pypi("yt-dlp", lambda url: _pypi("2099.1.1"))
    assert r["version"] == "2099.1.1" and r["url"].endswith("w.whl") and len(r["sha256"]) == 64


def test_instalar_rueda_la_activa_y_borra_la_anterior():
    rueda = _rueda({"modulo_falso/__init__.py": "__version__ = '2'\n", "modulo_falso-2.dist-info/METADATA": "Name: x\n"})
    info = {"version": "2099.1.1", "url": "https://files.pythonhosted.org/w.whl", "sha256": "a" * 64}
    componentes.instalar_rueda("yt-dlp", {**info, "version": "2099.1.0"}, _descargador(rueda))
    componentes.instalar_rueda("yt-dlp", info, _descargador(rueda))
    base = componentes.carpeta()
    assert (base / "yt-dlp-2099.1.1" / "modulo_falso" / "__init__.py").exists()
    assert not (base / "yt-dlp-2099.1.0").exists()                     # la vieja se borra
    ruta: list[str] = []
    assert componentes.activar(ruta) == [str(base / "yt-dlp-2099.1.1")] and ruta[0] == str(base / "yt-dlp-2099.1.1")


def test_instalar_rueda_rechaza_rutas_fuera_de_su_carpeta():
    malo = _rueda({"../../fuera.py": "x"})
    with pytest.raises(ErrorGestor):
        componentes.instalar_rueda("yt-dlp", {"version": "1", "url": "https://files.pythonhosted.org/w", "sha256": "a" * 64}, _descargador(malo))
    assert not (componentes.carpeta().parent.parent / "fuera.py").exists()


@pytest.mark.parametrize("url, sha", [
    ("http://files.pythonhosted.org/w.whl", "a" * 64),              # sin https
    ("https://evil.example.com/w.whl", "a" * 64),                   # otro dominio
    ("https://files.pythonhosted.org/w.whl", "no-es-un-hash"),      # sin huella válida
])
def test_descargar_verificado_rechaza_antes_de_tocar_la_red(tmp_path, url, sha):
    with pytest.raises(ErrorGestor):
        componentes.descargar_verificado(url, sha, tmp_path / "x")
    assert not (tmp_path / "x").exists()


def test_activos_con_nombres_raros_se_ignoran():
    componentes.carpeta().mkdir(parents=True)
    (componentes.carpeta() / "activos.json").write_text(json.dumps({"yt-dlp": {"dir": "..\\..\\Windows"}}), encoding="utf-8")
    assert componentes.activar([]) == []


def test_pip_usa_el_python_del_entorno_con_extras():
    cmd = componentes.comando_pip(("yt-dlp", "deno"))
    assert cmd[1:5] == ["-m", "pip", "install", "--upgrade"] and cmd[-2:] == ["yt-dlp[default]", "deno"]


# --- release de GitHub ---------------------------------------------------------------------------------
def test_release_con_instalador_y_huella():
    r = actualizaciones.interpretar_release({"tag_name": "v99.0.0", "assets": [
        {"name": "GestorDescargas-99.0.0-portable.zip", "digest": "sha256:" + "b" * 64},
        {"name": "GestorDescargas-99.0.0-instalador.exe", "digest": "sha256:" + "c" * 64,
         "browser_download_url": "https://github.com/x/y/releases/download/v99.0.0/i.exe", "size": 10}]})
    assert r["instalador"]["sha256"] == "c" * 64 and r["instalador"]["url"].startswith("https://github.com/")
    sin_huella = actualizaciones.interpretar_release({"tag_name": "v99", "assets": [{"name": "GestorDescargas-99-instalador.exe"}]})
    assert sin_huella["instalador"] is None


# --- actualizador ----------------------------------------------------------------------------------------
class Git:
    """Simula git y pip: guarda los comandos y responde lo configurado."""

    def __init__(self, atrasados=0, sucio=False):
        self.atrasados, self.sucio, self.comandos = atrasados, sucio, []

    def __call__(self, cmd, **kw):
        self.comandos.append(cmd)
        salida = ""
        if "rev-list" in cmd:
            salida = str(self.atrasados)
        elif "status" in cmd:
            salida = " M algo.py\n" if self.sucio else ""
        return subprocess.CompletedProcess(cmd, 0, salida, "")


@pytest.fixture
def con_ytdlp(monkeypatch):
    monkeypatch.setattr(componentes, "paquetes", lambda: ("yt-dlp",))
    monkeypatch.setattr(componentes, "version_instalada", lambda p: "2026.1.1")


def _act(modo, git=None, pypi="2026.1.1", release=None, **kw):
    def leer(url):
        return release if "api.github.com" in url else _pypi(pypi)
    a = Actualizador(modo=modo, leer_json=leer, ejecutar=git or Git(), **kw)
    a._versiones_programas = {"ffmpeg": None, "deno": None}
    a.pausa = 0
    return a


def _esperar(a: Actualizador, fases=("listo", "error")) -> dict:
    for _ in range(200):
        if a.estado()["fase"] in fases:
            return a.estado()
        time.sleep(0.02)
    raise AssertionError(a.estado())


def test_buscar_en_desarrollo_lista_codigo_y_librerias(con_ytdlp):
    e = _act("desarrollo", Git(atrasados=3), pypi="2026.9.9").buscar()
    assert [(p["tipo"], p["nueva"]) for p in e["pendientes"]] == [("app", "3 cambios nuevos"), ("componente", "2026.9.9")]
    assert e["ultima_busqueda"] and e["mensaje"] == "Hay actualizaciones disponibles."


def test_con_cambios_sin_guardar_no_se_toca_el_codigo(con_ytdlp):
    e = _act("desarrollo", Git(atrasados=2, sucio=True)).buscar()
    assert e["pendientes"] == [] and "cambios sin guardar" in e["avisos"][0]


def test_todo_al_dia(con_ytdlp):
    a = _act("desarrollo", Git())
    a.iniciar()
    e = _esperar(a)
    assert e["fase"] == "listo" and "al día" in e["mensaje"] and not e["reiniciar"]


def test_actualizar_en_desarrollo_hace_pull_pip_y_reinicia(con_ytdlp):
    git, reinicios = Git(atrasados=1), []
    a = _act("desarrollo", git, pypi="2026.9.9")
    a.al_reiniciar = lambda: reinicios.append(1)
    a.iniciar()
    e = _esperar(a)
    assert e["fase"] == "listo" and e["reiniciar"] and reinicios == [1]
    planos = [" ".join(c) for c in git.comandos]
    assert any("pip install --upgrade" in c and "yt-dlp[default]" in c for c in planos)
    assert any(c.endswith("pull --ff-only") for c in planos)
    assert a.marca()["recargar_extension"] is True                     # la extensión se recargará


def test_actualizar_instalada_descarga_el_instalador_verificado_y_lo_lanza(con_ytdlp):
    release = {"tag_name": "v99.0.0", "html_url": "https://github.com/x", "assets": [
        {"name": "GestorDescargas-99.0.0-instalador.exe", "digest": "sha256:" + "c" * 64,
         "browser_download_url": "https://github.com/x/y/releases/download/v99.0.0/i.exe"}]}
    llamadas, lanzados = [], []
    a = _act("instalada", release=release, descargar=_descargador(b"MZ", llamadas))
    a.al_instalar = lanzados.append
    a.iniciar()
    assert _esperar(a)["fase"] == "listo"
    url, sha, kw = llamadas[0]
    assert sha == "c" * 64 and kw["hosts"] == actualizador.HOSTS_GITHUB
    assert lanzados and lanzados[0].name == "GestorDescargas-99.0.0-instalador.exe"


def test_actualizar_instalada_tambien_trae_ytdlp_desde_pypi(con_ytdlp):
    rueda = _rueda({"yt_dlp/__init__.py": ""})
    a = _act("portatil", release={"tag_name": f"v{__version__}"}, pypi="2026.9.9", descargar=_descargador(rueda))
    reinicios = []
    a.al_reiniciar = lambda: reinicios.append(1)
    a.iniciar()
    e = _esperar(a)
    assert e["fase"] == "listo" and reinicios == [1] and "yt-dlp 2026.1.1 → 2026.9.9" in e["hechos"]
    assert (componentes.carpeta() / "yt-dlp-2026.9.9").is_dir()


def test_no_se_actualiza_con_descargas_en_curso(con_ytdlp):
    a = _act("desarrollo", hay_descargas=lambda: True)
    with pytest.raises(ErrorGestor) as e:
        a.iniciar()
    assert "descargas en curso" in e.value.mensaje and a.estado()["fase"] == "inactivo"


def test_comando_de_reinicio_en_desarrollo():
    cmd = actualizador.comando_reinicio(mostrar_ventana=False)
    assert cmd[1:3] == ["-m", "gestor.app"] and "--reiniciado" in cmd and "--segundo-plano" in cmd
    assert "--segundo-plano" not in actualizador.comando_reinicio(mostrar_ventana=True)


# --- protocolo e IPC -------------------------------------------------------------------------------------
def test_protocolo_admite_las_acciones_de_actualizacion():
    m = validar_mensaje({"v": 1, "id": "a", "accion": "actualizacion", "datos": {"buscar": True}})
    assert m["datos"] == {"buscar": True}
    with pytest.raises(ErrorGestor):
        validar_mensaje({"v": 1, "id": "a", "accion": "actualizacion", "datos": {"buscar": "si"}})
    validar_mensaje({"v": 1, "id": "a", "accion": "actualizar", "datos": {}})


def test_ipc_informa_versiones_y_estado(con_ytdlp, tmp_path):
    from gestor.cola import GestorCola
    from gestor.db import BaseDatos
    from gestor.ipc import Manejador
    db = BaseDatos(":memory:")
    try:
        man = Manejador(GestorCola(db))
        token = man.vinculacion.emparejar(man.vinculacion.codigo_actual()[0], "Prueba")
        ping = man.manejar({"v": 1, "id": "p", "accion": "ping", "datos": {}, "token": token})["datos"]
        assert ping["version_app"] == __version__ and ping["version_extension"] == __version__
        sin = man.manejar({"v": 1, "id": "a", "accion": "actualizacion", "datos": {}, "token": token})
        assert sin["ok"] is False
        man.actualizador = _act("desarrollo", Git(atrasados=1))
        man.actualizador.buscar()
        e = man.manejar({"v": 1, "id": "a", "accion": "actualizacion", "datos": {}, "token": token})["datos"]
        assert e["pendientes"][0] == {"tipo": "app", "nombre": "Aplicación y extensión", "actual": __version__, "nueva": "1 cambios nuevos"}
        assert "info" not in e["pendientes"][0]
    finally:
        db.cerrar()


def test_versiones_de_app_extension_y_proyecto_coinciden():
    manifest = json.loads((RAIZ / "extension" / "manifest.json").read_text(encoding="utf-8"))
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    assert manifest["version"] == __version__ and f'version = "{__version__}"' in pyproject


def test_reiniciar_respeta_las_descargas_en_curso():
    a = _act("desarrollo", hay_descargas=lambda: True)
    a.al_reiniciar = lambda: None
    with pytest.raises(ErrorGestor):
        a.reiniciar()
    hecho = []
    b = _act("desarrollo")
    b.al_reiniciar = lambda: hecho.append(1)
    b.reiniciar()
    time.sleep(0.8)
    assert hecho == [1]
    validar_mensaje({"v": 1, "id": "r", "accion": "reiniciar", "datos": {}})


def test_al_reiniciar_desde_el_codigo_se_encuentra_el_paquete():
    env = actualizador.entorno_app()
    assert str(actualizador.RAIZ_PROYECTO / "src") in env["PYTHONPATH"].split(";")


def test_ipc_pregunta_antes_de_repetir_un_video():
    from gestor.cola import GestorCola
    from gestor.db import BaseDatos
    from gestor.ipc import Manejador
    db = BaseDatos(":memory:")
    try:
        man = Manejador(GestorCola(db))
        token = man.vinculacion.emparejar(man.vinculacion.codigo_actual()[0], "Prueba")
        pedir = lambda datos: man.manejar({"v": 1, "id": "d", "accion": "detectar", "datos": datos, "token": token})  # noqa: E731
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert pedir({"url": url})["ok"]
        r = pedir({"url": "https://youtu.be/dQw4w9WgXcQ"})
        assert r["ok"] is False and r["error"]["codigo"] == "duplicado"
        assert pedir({"url": "https://youtu.be/dQw4w9WgXcQ", "forzar": True})["ok"]              # confirmado: se añade
        assert len(db.listar_tareas()) == 2
        with pytest.raises(ErrorGestor):
            validar_mensaje({"v": 1, "id": "d", "accion": "encolar", "datos": {"url": url, "forzar": "si"}})
    finally:
        db.cerrar()


# --- actualización automática ---------------------------------------------------------------------------
def test_se_actualiza_sola_si_esta_activado(con_ytdlp):
    reinicios = []
    a = _act("desarrollo", Git(atrasados=2), pypi="2026.9.9", automatico=lambda: True)
    a.al_reiniciar = lambda: reinicios.append(1)
    assert a.revisar_automatico() == "actualizando"
    e = _esperar(a)
    assert e["fase"] == "listo" and reinicios == [1] and a.marca()["automatica"] is True
    assert a.aviso_tras_reinicio() and a.aviso_tras_reinicio() is None          # se avisa una sola vez


def test_sin_permiso_solo_avisa(con_ytdlp):
    a = _act("desarrollo", Git(atrasados=2), automatico=lambda: False)
    assert a.revisar_automatico() == "nada" and a.estado()["pendientes"]          # lo nuevo queda a la vista en Ajustes


def test_espera_a_que_terminen_las_descargas(con_ytdlp):
    a = _act("desarrollo", Git(atrasados=2), automatico=lambda: True, hay_descargas=lambda: True)
    assert a.revisar_automatico() == "esperando" and a.estado()["fase"] == "inactivo"


def test_la_portatil_no_se_reinstala_sola(con_ytdlp):
    release = {"tag_name": "v99.0.0", "html_url": "https://github.com/x"}
    a = _act("portatil", release=release, automatico=lambda: True)
    assert a.revisar_automatico() == "nada"


def test_no_busca_en_cada_revision(con_ytdlp):
    git = Git()
    a = _act("desarrollo", git, automatico=lambda: True)
    a.revisar_automatico(); a.revisar_automatico()
    assert sum("fetch" in c for c in git.comandos) == 1                           # cada 6 horas, no cada hora


def test_la_extension_activa_y_desactiva_la_actualizacion_automatica():
    from gestor.cola import GestorCola
    from gestor.db import BaseDatos
    from gestor.ipc import Manejador
    db = BaseDatos(":memory:")
    try:
        man = Manejador(GestorCola(db))
        man.actualizador = _act("desarrollo", automatico=lambda: db.cargar_preferencias().actualizar_solo)
        token = man.vinculacion.emparejar(man.vinculacion.codigo_actual()[0], "Prueba")
        r = man.manejar({"v": 1, "id": "a", "accion": "actualizacion", "datos": {"automatico": False}, "token": token})
        assert r["ok"] and r["datos"]["automatico"] is False and db.cargar_preferencias().actualizar_solo is False
    finally:
        db.cerrar()
