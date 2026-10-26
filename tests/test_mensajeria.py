"""Protocolo, API (página web y extensión) y el servidor HTTP local real."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from gestor.api import CAMPOS_PREFERENCIAS, PREFERENCIAS_EDITABLES, Manejador
from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.modelos import CodigoError, ErrorGestor, InfoContenido
from gestor.protocolo import validar_mensaje
from gestor.vinculacion import Vinculacion
from gestor.web.servidor import ServidorWeb


def M(accion, datos=None, id_="m1", token=None, **extra):
    m = {"v": 1, "id": id_, "accion": accion, "datos": datos or {}, **extra}
    if token:
        m["token"] = token
    return m


# --- protocolo --------------------------------------------------------------
def test_mensaje_valido_se_sanea():
    m = validar_mensaje(M("encolar", {"url": " https://a.com/v ", "origen": "https://a.com", "opciones": {"modo": "audio"}}))
    assert m["datos"]["url"] == "https://a.com/v" and m["datos"]["opciones"] == {"modo": "audio"}


@pytest.mark.parametrize("bruto", [
    None, [], "hola", {}, M("ping", id_="a b"), M("ping", id_="x" * 100),
    {**M("ping"), "v": 2}, M("borrar_todo"), M("ping", {"extra": 1}),
    M("encolar", {}), M("encolar", {"url": 5}), {**M("ping"), "sorpresa": 1},
    M("encolar", {"url": "https://a.com", "opciones": {"formato_audio": "exe"}}),
    M("encolar", {"url": "https://a.com", "opciones": {"excluir": True}}),      # solo reglas, no la extensión
    M("encolar", {"url": "https://a.com", "opciones": {"destino": "C:/Windows"}}),  # nada de rutas desde fuera
    M("estado", {"id": "../../x"}), M("cancelar", {"id": "ZZZZZZZZZZZZ"}),
    M("listar", {"estados": ["hackeado"]}), M("listar", {"limite": 100000}), M("listar", {"limite": True}),
    M("listar", {"texto": "x" * 500}),
    M("anadir", {"url": "https://a.com", "modo": "ya"}),                          # modo fuera de la lista
    M("anadir", {"url": "https://a.com", "cookies": "a=b"}),                     # la sesión es una lista
    M("anadir", {"url": "https://a.com", "opciones": {"medios": ["file:///c:/x"]}}),
    M("grupo_crear", {"nombre": "x" * 61}), M("grupo_crear", {"nombre": "a\nb"}),
    M("preferencias", {"cambios": "todo"}), M("vinculos", {"revocar": True}),
])
def test_mensajes_invalidos(bruto):
    with pytest.raises(ErrorGestor):
        validar_mensaje(bruto)


@pytest.mark.parametrize("url", ["file:///c:/x", "javascript:alert(1)", "http://127.0.0.1/", "http://192.168.0.1/x",
                                 "https://user:pw@a.com/"])
def test_urls_peligrosas_se_rechazan_en_el_protocolo(url):
    with pytest.raises(ErrorGestor) as e:
        validar_mensaje(M("analizar", {"url": url}))
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_origen_raro_se_descarta_no_rompe():
    assert validar_mensaje(M("detectar", {"url": "https://a.com/v", "origen": "about:blank"}))["datos"]["origen"] is None


def test_las_preferencias_editables_existen():
    assert set(PREFERENCIAS_EDITABLES) <= CAMPOS_PREFERENCIAS


# --- API (sin red) ------------------------------------------------------------
@pytest.fixture
def cola(tmp_path):
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    c = GestorCola(db)       # sin hilos: solo probamos la API
    c._extraer = lambda url, **kw: InfoContenido(url, "Título", "Sitio")
    yield c
    db.cerrar()


@pytest.fixture
def vinc(cola):
    v = Vinculacion(cola.db)
    return v, v.emparejar(v.codigo_actual()[0], "Pruebas")      # (vinculación, token de una extensión)


@pytest.fixture
def mz(cola, vinc):
    return Manejador(cola, vinc[0], abrir_carpeta=lambda r: None, token_web="token-de-la-pagina-web-0123456789")


WEB = "token-de-la-pagina-web-0123456789"


def test_ciclo_basico_desde_la_extension(mz, vinc):
    tk = vinc[1]
    assert mz.manejar(M("ping"))["datos"]["vinculado"] is False
    assert mz.manejar(M("ping", token=tk))["datos"]["vinculado"] is True
    t = mz.manejar(M("detectar", {"url": "https://a.com/v", "origen": "https://a.com/"}, token=tk))["datos"]
    assert t["estado"] == "detectado"
    lista = mz.manejar(M("listar", {"estados": ["detectado"]}, token=tk))["datos"]["tareas"]
    assert [x["id"] for x in lista] == [t["id"]]
    assert mz.manejar(M("cancelar", {"id": t["id"]}, token=tk))["datos"]["estado"] == "cancelado"
    assert mz.manejar(M("eliminar", {"id": t["id"]}, token=tk))["ok"]
    r = mz.manejar(M("estado", {"id": t["id"]}, token=tk))
    assert not r["ok"] and r["error"]["mensaje"] == "La tarea no existe."


def test_la_pagina_web_entra_con_su_token_y_nadie_sin_token(mz):
    d = mz.manejar(M("ping", token=WEB))["datos"]
    assert d["vinculado"] is True and d["web"] is True
    assert mz.manejar(M("listar", token=WEB))["ok"]
    r = mz.manejar(M("listar", token="otro-token-que-no-vale-de-nada"))
    assert not r["ok"] and r["error"]["codigo"] == "no_vinculado"


def test_lo_delicado_solo_desde_la_pagina(mz, vinc):
    for accion in ("vinculos", "apagar", "reiniciar", "elegir_carpeta"):
        r = mz.manejar(M(accion, token=vinc[1]))
        assert not r["ok"] and r["error"]["codigo"] == "no_vinculado", accion
    v = mz.manejar(M("vinculos", token=WEB))["datos"]
    assert len(v["codigo"]) == 9 and v["vinculos"][0]["nombre"] == "Pruebas"


def test_la_extension_solo_cambia_lo_de_anadir(mz, vinc, tmp_path):
    tk = vinc[1]
    r = mz.manejar(M("preferencias", {"cambios": {"carpeta_propia": False, "modo_anadir": "grupo"}}, token=tk))
    assert r["ok"] and r["datos"]["carpeta_propia"] is False and r["datos"]["modo_anadir"] == "grupo"
    for cambio in ({"carpeta_raiz": str(tmp_path)}, {"velocidad": "maxima"}, {"inicio_windows": True}):
        r = mz.manejar(M("preferencias", {"cambios": cambio}, token=tk))
        assert not r["ok"], cambio
    r = mz.manejar(M("preferencias", {"cambios": {"velocidad": "maxima"}}, token=WEB))
    assert r["ok"] and r["datos"]["velocidad"] == "maxima"
    assert not mz.manejar(M("preferencias", {"cambios": {"velocidad": "luz"}}, token=WEB))["ok"]


def test_anadir_instantaneo_descarga_y_al_grupo_espera(mz, cola):
    r = mz.manejar(M("anadir", {"url": "https://a.com/v1", "modo": "instantanea"}, token=WEB))["datos"]
    assert r["estado"] == "pendiente" and r["modo"] == "instantanea" and r["grupo"] is None
    r = mz.manejar(M("anadir", {"url": "https://a.com/v2", "modo": "grupo", "grupo": "Curso"}, token=WEB))["datos"]
    assert r["estado"] == "detectado" and r["grupo"] == "Curso"
    assert "Curso" in cola.prefs().grupos                       # el grupo se crea solo
    # sin modo: se usa el que esté guardado (lo eligen la página o la extensión)
    mz.manejar(M("preferencias", {"cambios": {"modo_anadir": "grupo", "grupo_activo": "Música"}}, token=WEB))
    r = mz.manejar(M("anadir", {"url": "https://a.com/v3"}, token=WEB))["datos"]
    assert r["estado"] == "detectado" and r["grupo"] == "Música"


def test_anadir_repetido_pregunta_y_con_forzar_se_repite(mz):
    mz.manejar(M("anadir", {"url": "https://a.com/v", "modo": "grupo"}, token=WEB))
    r = mz.manejar(M("anadir", {"url": "https://a.com/v", "modo": "grupo"}, token=WEB))
    assert not r["ok"] and r["error"]["codigo"] == "duplicado"
    assert mz.manejar(M("anadir", {"url": "https://a.com/v", "modo": "grupo", "forzar": True}, token=WEB))["ok"]


def test_grupos_crear_renombrar_descargar_y_eliminar(mz, cola):
    for u in ("https://a.com/1", "https://a.com/2"):
        mz.manejar(M("anadir", {"url": u, "modo": "grupo", "grupo": "Viaje"}, token=WEB))
    g = {x["nombre"]: x for x in mz.manejar(M("grupos", token=WEB))["datos"]["grupos"]}
    assert g["Viaje"]["esperando"] == 2
    mz.manejar(M("grupo_renombrar", {"nombre": "Viaje", "nuevo": "Viaje 2026"}, token=WEB))
    r = mz.manejar(M("grupo_iniciar", {"nombre": "Viaje 2026"}, token=WEB))["datos"]
    assert r["iniciadas"] == 2
    assert {t.estado.value for t in cola.listar()} == {"pendiente"}
    assert all(t.opciones["grupo"] == "Viaje 2026" for t in cola.listar())
    mz.manejar(M("anadir", {"url": "https://a.com/3", "modo": "grupo", "grupo": "Borrar"}, token=WEB))
    r = mz.manejar(M("grupo_eliminar", {"nombre": "Borrar"}, token=WEB))["datos"]
    assert r["quitadas"] == 1 and "Borrar" not in [x["nombre"] for x in r["grupos"]]


def test_la_sesion_del_sitio_no_se_guarda_en_la_base_de_datos(mz, cola):
    cookies = [{"name": "sid", "value": "secreto", "domain": ".a.com", "path": "/", "secure": True, "expirationDate": 2e9}]
    t = mz.manejar(M("anadir", {"url": "https://a.com/v", "modo": "grupo", "cookies": cookies}, token=WEB))["datos"]
    assert "secreto" not in json.dumps([x.a_dict() for x in cola.db.listar_tareas()])
    assert cola._cookies[t["id"]][0]["value"] == "secreto"
    mz.manejar(M("eliminar", {"id": t["id"]}, token=WEB))
    assert t["id"] not in cola._cookies


def test_errores_y_basura(mz, cola, vinc):
    tk = vinc[1]
    assert mz.manejar("basura")["ok"] is False
    r = mz.manejar(M("encolar", {"url": "http://localhost/x"}, token=tk))
    assert not r["ok"] and r["error"]["codigo"] == "url_invalida"
    cola._extraer = lambda url, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    r = mz.manejar(M("analizar", {"url": "https://a.com/v"}, token=tk))
    assert not r["ok"] and r["error"]["codigo"] == "desconocido"     # fallo inesperado: sin detalles internos
    assert "boom" not in json.dumps(r)


# --- servidor HTTP real --------------------------------------------------------
@pytest.fixture
def servidor(mz):
    srv = ServidorWeb(mz, 0, extension_id="abcdefghijklmnopabcdefghijklmnop")
    hilo = threading.Thread(target=srv.servir, daemon=True)
    hilo.start()
    yield srv
    srv.detener()


def _pedir(srv, ruta="/", *, datos=None, cabeceras=None):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.puerto}{ruta}", method="POST" if datos is not None else "GET",
                                 data=json.dumps(datos).encode() if datos is not None else None,
                                 headers={"Content-Type": "application/json", **(cabeceras or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_la_pagina_lleva_su_token_y_cabeceras_de_seguridad(servidor):
    estado, cab, cuerpo = _pedir(servidor, "/")
    assert estado == 200 and WEB.encode() in cuerpo and b"{{TOKEN}}" not in cuerpo
    assert "default-src 'self'" in cab["Content-Security-Policy"] and cab["X-Content-Type-Options"] == "nosniff"
    assert _pedir(servidor, "/app.js")[0] == 200 and _pedir(servidor, "/app.css")[0] == 200
    for ruta in ("/../api.py", "/..%2F..%2Fapi.py", "/no-existe.js", "/servidor.py"):
        assert _pedir(servidor, ruta)[0] == 404, ruta


def test_api_por_http_con_token(servidor):
    estado, _, cuerpo = _pedir(servidor, "/api", datos=M("listar", token=WEB))
    assert estado == 200 and json.loads(cuerpo)["ok"] is True
    assert json.loads(_pedir(servidor, "/api", datos=M("listar"))[2])["error"]["codigo"] == "no_vinculado"
    assert json.loads(_pedir(servidor, "/api/salud")[2])["app"] == "gestor-descargas"


def test_otras_webs_no_pueden_usar_el_gestor(servidor):
    # Un sitio cualquiera abierto en el navegador (CSRF) o un dominio que apunta a 127.0.0.1 (DNS rebinding).
    assert _pedir(servidor, "/api", datos=M("ping"), cabeceras={"Origin": "https://malo.com"})[0] == 403
    assert _pedir(servidor, "/", cabeceras={"Host": f"malo.com:{servidor.puerto}"})[0] == 403
    assert _pedir(servidor, "/api", datos=M("ping"), cabeceras={"Origin": "chrome-extension://otraextensionqueno"})[0] == 403
    # La propia página y nuestra extensión sí.
    assert _pedir(servidor, "/api", datos=M("ping"), cabeceras={"Origin": f"http://127.0.0.1:{servidor.puerto}"})[0] == 200
    estado, cab, _ = _pedir(servidor, "/api", datos=M("ping"), cabeceras={"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"})
    assert estado == 200 and cab["Access-Control-Allow-Origin"] == "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def test_eventos_en_vivo_piden_token_y_avisan_de_los_cambios(servidor, mz):
    assert _pedir(servidor, "/api/eventos?token=nada")[0] == 401
    r = urllib.request.urlopen(f"http://127.0.0.1:{servidor.puerto}/api/eventos?token={WEB}", timeout=5)
    assert r.readline().startswith(b"retry:")
    r.readline()
    mz.manejar(M("anadir", {"url": "https://a.com/vivo", "modo": "grupo"}, token=WEB))
    linea = b""
    while not linea.startswith(b"data:"):
        linea = r.readline()
    evento = json.loads(linea[5:])
    assert evento["tipo"] == "tarea" and evento["tarea"]["url"] == "https://a.com/vivo"
    r.close()
