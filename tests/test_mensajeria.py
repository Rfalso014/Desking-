"""Protocolo, servidor IPC y host nativo (este último como proceso real)."""
import io
import json
import os
import struct
import subprocess
import sys
import time
import uuid
from multiprocessing.connection import Client
from pathlib import Path

import pytest

from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.ipc import Manejador, ServidorIPC
from gestor.vinculacion import Vinculacion
from gestor.modelos import CodigoError, ErrorGestor, EstadoTarea, InfoContenido
from gestor.nativo import host
from gestor.protocolo import validar_mensaje

RAIZ = Path(__file__).resolve().parents[1]


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
    M("encolar", {"url": "https://a.com", "opciones": {"destino": "C:/Windows"}}),  # nada de rutas desde la extensión
    M("estado", {"id": "../../x"}), M("cancelar", {"id": "ZZZZZZZZZZZZ"}),
    M("listar", {"estados": ["hackeado"]}), M("listar", {"limite": 100000}), M("listar", {"limite": True}),
    M("listar", {"texto": "x" * 500}),
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


# --- manejador (sin red) ----------------------------------------------------
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
    return v, v.emparejar(v.codigo_actual()[0], "Pruebas")      # (vinculación, token válido)


def test_manejador_ciclo_basico(cola, vinc):
    v, tk = vinc
    mz = Manejador(cola, v, abrir_carpeta=lambda r: None)
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


def test_manejador_analizar(cola, vinc):
    r = Manejador(cola, vinc[0]).manejar(M("analizar", {"url": "https://a.com/v"}, token=vinc[1]))
    assert r["ok"] and r["datos"]["titulo"] == "Título" and r["datos"]["diagnostico"]["nivel"] == "desconocido"


def test_manejador_errores_y_basura(cola, vinc):
    mz = Manejador(cola, vinc[0])
    tk = vinc[1]
    assert mz.manejar("basura")["ok"] is False
    r = mz.manejar(M("encolar", {"url": "http://localhost/x"}, token=tk))
    assert not r["ok"] and r["error"]["codigo"] == "url_invalida"
    cola._extraer = lambda url, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    r = mz.manejar(M("analizar", {"url": "https://a.com/v"}, token=tk))
    assert not r["ok"] and r["error"]["codigo"] == "desconocido"     # fallo inesperado: sin detalles internos
    assert "boom" not in json.dumps(r)


# --- tubería real con clave -------------------------------------------------
@pytest.fixture
def servidor(cola):
    direccion = rf"\\.\pipe\GestorTest-{uuid.uuid4().hex}"
    clave = os.urandom(32)
    v = Vinculacion(cola.db)
    token = v.emparejar(v.codigo_actual()[0], "Host de prueba")
    s = ServidorIPC(cola, vinculacion=v, direccion=direccion, clave=clave)
    s.iniciar()
    yield direccion, clave, token
    s.detener()


def test_pipe_ida_y_vuelta(servidor):
    direccion, clave, _ = servidor
    with Client(direccion, family="AF_PIPE", authkey=clave) as c:
        c.send_bytes(json.dumps(M("ping")).encode())
        assert json.loads(c.recv_bytes())["ok"]
        c.send_bytes(b"no es json")                       # basura: responde error, no se cae
        assert json.loads(c.recv_bytes())["ok"] is False
        c.send_bytes(json.dumps(M("ping", id_="m2")).encode())
        assert json.loads(c.recv_bytes())["id"] == "m2"


def test_pipe_rechaza_clave_incorrecta(servidor):
    direccion = servidor[0]
    from multiprocessing import AuthenticationError
    with pytest.raises((AuthenticationError, OSError, EOFError)):
        Client(direccion, family="AF_PIPE", authkey=b"x" * 32)
    # y el servidor sigue atendiendo a quien sí tiene la clave
    with Client(direccion, family="AF_PIPE", authkey=servidor[1]) as c:
        c.send_bytes(json.dumps(M("ping")).encode())
        assert json.loads(c.recv_bytes())["ok"]


# --- marcos del protocolo nativo ---------------------------------------------
def test_leer_y_escribir_mensaje():
    buf = io.BytesIO()
    host.escribir_mensaje(buf, {"a": "ñ"})
    buf.seek(0)
    assert host.leer_mensaje(buf) == {"a": "ñ"}
    assert host.leer_mensaje(buf) is None                  # fin del canal


def test_mensaje_enorme_o_roto():
    with pytest.raises(ErrorGestor):
        host.leer_mensaje(io.BytesIO(struct.pack("=I", 50_000_000)))
    with pytest.raises(ErrorGestor):
        host.leer_mensaje(io.BytesIO(struct.pack("=I", 3) + b"{{{"))
    assert host.leer_mensaje(io.BytesIO(struct.pack("=I", 10) + b"corto")) is None


def test_respuesta_demasiado_grande_se_sustituye():
    buf = io.BytesIO()
    host.escribir_mensaje(buf, {"id": "m1", "ok": True, "datos": {"x": "a" * 2_000_000}})
    buf.seek(0)
    r = host.leer_mensaje(buf)
    assert r["ok"] is False and r["id"] == "m1"


def test_procesar_valida_antes_de_conectar():
    def no_conectar():
        raise AssertionError("no debió conectar")
    r = host.procesar(M("encolar", {"url": "file:///x"}), no_conectar)
    assert r["ok"] is False and r["error"]["codigo"] == "url_invalida"


# --- el host como proceso real ---------------------------------------------
def _hablar(datos_dir, direccion, mensajes, espera="1"):
    env = {**os.environ, "GESTOR_DATOS": str(datos_dir), "GESTOR_PIPE": direccion,
           "PYTHONPATH": str(RAIZ / "src"), "GESTOR_ESPERA_APP": espera}
    entrada = b"".join(struct.pack("=I", len(b)) + b for b in (json.dumps(m).encode() for m in mensajes))
    p = subprocess.run([sys.executable, "-m", "gestor.nativo.host", "chrome-extension://abc/"],
                       input=entrada, capture_output=True, env=env, timeout=60, cwd=str(RAIZ / "src"))
    salida, respuestas = p.stdout, []
    while salida:
        (n,) = struct.unpack("=I", salida[:4])
        respuestas.append(json.loads(salida[4:4 + n]))
        salida = salida[4 + n:]
    return p, respuestas


def test_host_real_de_extremo_a_extremo(servidor, tmp_path):
    direccion, clave, token = servidor
    (tmp_path / "ipc.key").write_bytes(clave)
    p, r = _hablar(tmp_path, direccion, [M("ping", id_="a"), M("detectar", {"url": "https://a.com/v"}, id_="b", token=token),
                                        M("encolar", {"url": "file:///x"}, id_="c", token=token)])
    assert p.returncode == 0, p.stderr
    assert [x["id"] for x in r] == ["a", "b", "c"]
    assert r[0]["ok"] and r[1]["datos"]["estado"] == "detectado"
    assert r[2]["ok"] is False and r[2]["error"]["codigo"] == "url_invalida"


def test_host_sin_app_da_mensaje_comprensible(tmp_path):
    (tmp_path / "ipc.key").write_bytes(os.urandom(32))
    inicio = time.time()
    p, r = _hablar(tmp_path, rf"\\.\pipe\NoExiste-{uuid.uuid4().hex}", [M("ping")])
    assert r[0]["ok"] is False and r[0]["error"]["codigo"] == "comunicacion"
    assert "aplicación" in r[0]["error"]["mensaje"] and r[0]["error"]["solucion"]
    assert time.time() - inicio < 30


def test_host_sin_clave_tampoco_se_cae(tmp_path):
    p, r = _hablar(tmp_path, r"\\.\pipe\NoExiste", [M("ping")])
    assert r[0]["error"]["codigo"] == "comunicacion"


def test_host_rechaza_origen_no_autorizado(tmp_path):
    (tmp_path / "host.json").write_text(json.dumps({"origenes_permitidos": ["chrome-extension://otro/"]}))
    p, r = _hablar(tmp_path, r"\\.\pipe\NoExiste", [M("ping")])
    assert p.returncode == 2 and r == []
