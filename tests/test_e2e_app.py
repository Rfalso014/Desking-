"""Prueba de extremo a extremo: la aplicación real (sin ventana visible) + el host nativo real."""
import json
import os
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _hablar_con_host(env, mensajes):
    mensajes = [{**m, "token": env["TOKEN_E2E"]} if m["accion"] != "ping" else m for m in mensajes]
    entrada = b"".join(struct.pack("=I", len(b)) + b for b in (json.dumps(m).encode() for m in mensajes))
    p = subprocess.run([sys.executable, "-m", "gestor.nativo.host", "chrome-extension://x/"], input=entrada,
                       capture_output=True, env=env, timeout=60, cwd=str(RAIZ / "src"))
    out, res = p.stdout, []
    while out:
        (n,) = struct.unpack("=I", out[:4]); res.append(json.loads(out[4:4 + n])); out = out[4 + n:]
    return res


@pytest.fixture
def app_en_marcha(tmp_path):
    from gestor.db import BaseDatos
    from gestor.vinculacion import Vinculacion
    db = BaseDatos(tmp_path / "gestor.db")              # se vincula ANTES de abrir la app (como haría el usuario con el código)
    v = Vinculacion(db)
    token = v.emparejar(v.codigo_actual()[0], "E2E")
    db.cerrar()
    env = {"TOKEN_E2E": token, **os.environ, "GESTOR_DATOS": str(tmp_path), "GESTOR_PIPE": rf"\\.\pipe\GestorE2E-{uuid.uuid4().hex}",
           "PYTHONPATH": str(RAIZ / "src"), "QT_QPA_PLATFORM": "offscreen", "GESTOR_ESPERA_APP": "20"}
    p = subprocess.Popen([sys.executable, "-m", "gestor.app"], env=env, cwd=str(RAIZ / "src"),
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    yield env, p
    p.kill()
    p.wait(10)


def test_la_app_arranca_y_responde_por_el_host(app_en_marcha):
    env, proc = app_en_marcha
    fin = time.time() + 30
    r = None
    while time.time() < fin:
        assert proc.poll() is None, proc.stderr.read().decode(errors="replace")
        r = _hablar_con_host({**env, "GESTOR_ESPERA_APP": "1"}, [{"v": 1, "id": "p1", "accion": "ping", "datos": {}}])
        if r[0]["ok"]:
            break
        time.sleep(0.5)
    assert r[0]["ok"], r
    # Flujo real: detectar -> listar -> cancelar -> eliminar, todo a través del host y la tubería.
    ms = [{"v": 1, "id": "a", "accion": "detectar", "datos": {"url": "https://ejemplo.com/video"}}]
    tid = _hablar_con_host(env, ms)[0]["datos"]["id"]
    r = _hablar_con_host(env, [
        {"v": 1, "id": "b", "accion": "listar", "datos": {"estados": ["detectado"]}},
        {"v": 1, "id": "c", "accion": "cancelar", "datos": {"id": tid}},
        {"v": 1, "id": "d", "accion": "eliminar", "datos": {"id": tid}},
        {"v": 1, "id": "e", "accion": "estado", "datos": {"id": tid}}])
    assert [x["id"] for x in r[0]["datos"]["tareas"]] == [tid]
    assert r[1]["datos"]["estado"] == "cancelado" and r[2]["ok"] and not r[3]["ok"]
    assert (Path(env["GESTOR_DATOS"]) / "gestor.db").exists()          # el historial se guarda en disco
