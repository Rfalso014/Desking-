import pytest

from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.api import Manejador
from gestor.modelos import CodigoError, ErrorGestor, EstadoTarea, InfoContenido
from gestor.protocolo import validar_mensaje
from gestor.vinculacion import ALFABETO, Vinculacion


class Reloj:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


@pytest.fixture
def db():
    d = BaseDatos(":memory:")
    yield d
    d.cerrar()


def test_formato_del_codigo(db):
    cod, resto = Vinculacion(db).codigo_actual()
    assert len(cod) == 9 and cod[4] == "-" and set(cod.replace("-", "")) <= set(ALFABETO)
    assert 590 <= resto <= 600


def test_emparejar_da_token_y_el_codigo_es_de_un_solo_uso(db):
    v = Vinculacion(db)
    cod = v.codigo_actual()[0]
    token = v.emparejar(cod.lower().replace("-", " "), "Mi Chrome")     # tolera minúsculas y separadores
    assert v.validar_token(token) and len(token) >= 40
    assert v.listar()[0]["nombre"] == "Mi Chrome"
    with pytest.raises(ErrorGestor):
        v.emparejar(cod)                                                 # el mismo código ya no sirve
    assert v.codigo_actual()[0] != cod


def test_solo_se_guarda_el_hash_del_token(db):
    v = Vinculacion(db)
    token = v.emparejar(v.codigo_actual()[0])
    fila = db._con.execute("SELECT token_hash FROM vinculos").fetchone()[0]
    assert token not in fila and len(fila) == 64 and not v.validar_token(fila)   # el hash no sirve como token


def test_token_falso_o_vacio(db):
    v = Vinculacion(db)
    v.emparejar(v.codigo_actual()[0])
    for t in (None, "", "x" * 43, "no-es-el-token"):
        assert not v.validar_token(t)


def test_codigo_incorrecto(db):
    v = Vinculacion(db)
    with pytest.raises(ErrorGestor) as e:
        v.emparejar("AAAA-AAAA")
    assert e.value.codigo == CodigoError.NO_VINCULADO and v.listar() == []


def test_el_codigo_vence(db):
    reloj = Reloj()
    v = Vinculacion(db, duracion_codigo=600, reloj=reloj)
    viejo = v.codigo_actual()[0]
    reloj.t += 601
    with pytest.raises(ErrorGestor):
        v.emparejar(viejo)
    assert v.codigo_actual()[0] != viejo


def test_bloqueo_tras_varios_fallos_y_el_codigo_se_renueva(db):
    reloj = Reloj()
    v = Vinculacion(db, max_fallos=3, bloqueo=60, reloj=reloj)
    bueno = v.codigo_actual()[0]
    for _ in range(3):
        with pytest.raises(ErrorGestor):
            v.emparejar("ZZZZ-ZZZZ")
    with pytest.raises(ErrorGestor) as e:
        v.emparejar(bueno)                       # aunque fuera el correcto: bloqueado
    assert "Demasiados intentos" in e.value.mensaje
    reloj.t += 61
    nuevo = v.codigo_actual()[0]
    assert nuevo != bueno
    assert v.validar_token(v.emparejar(nuevo))


def test_revocar_y_desvincular(db):
    v = Vinculacion(db)
    t1 = v.emparejar(v.codigo_actual()[0], "A")
    t2 = v.emparejar(v.codigo_actual()[0], "B")
    v.revocar(v.listar()[1]["id"])               # revoca el más antiguo (A)
    assert not v.validar_token(t1) and v.validar_token(t2)
    assert v.desvincular_token(t2) and not v.validar_token(t2)


# --- protocolo y manejador con vinculación -------------------------------------
def M(accion, datos=None, token=None, id_="m1"):
    m = {"v": 1, "id": id_, "accion": accion, "datos": datos or {}}
    if token:
        m["token"] = token
    return m


@pytest.mark.parametrize("token", ["corto", "con espacios " * 3, "a" * 200, 123, ["x"]])
def test_token_mal_formado_se_rechaza_en_el_protocolo(token):
    with pytest.raises(ErrorGestor):
        validar_mensaje({**M("ping"), "token": token})


@pytest.mark.parametrize("datos", [{"codigo": "x"}, {"codigo": "a;b;c;d;e"}, {"codigo": 5}, {"codigo": "ABCD-EFGH", "nombre": ""},
                                   {"codigo": "ABCD-EFGH", "nombre": "x" * 99}])
def test_emparejar_valida_sus_datos(datos):
    with pytest.raises(ErrorGestor):
        validar_mensaje(M("emparejar", datos))


@pytest.fixture
def entorno(tmp_path, db):
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    cola = GestorCola(db)
    cola._extraer = lambda url, **kw: InfoContenido(url, "Título largo", "Sitio", miniatura_url="https://a.com/t.jpg", duracion_seg=61)
    abiertas = []
    v = Vinculacion(db)
    return cola, v, Manejador(cola, v, abrir_carpeta=abiertas.append), abiertas


def test_sin_token_nada_funciona_salvo_ping_y_emparejar(entorno):
    cola, v, mz, _ = entorno
    for accion, datos in [("listar", {}), ("encolar", {"url": "https://a.com/v"}), ("analizar", {"url": "https://a.com/v"}),
                          ("limpiar", {}), ("detectar", {"url": "https://a.com/v"})]:
        r = mz.manejar(M(accion, datos))
        assert not r["ok"] and r["error"]["codigo"] == "no_vinculado", accion
    assert cola.listar() == []                                  # no se creó nada
    assert mz.manejar(M("ping"))["ok"]


def test_token_incorrecto_es_igual_que_sin_token(entorno):
    _, _, mz, _ = entorno
    r = mz.manejar(M("listar", {}, token="A" * 43))
    assert not r["ok"] and r["error"]["codigo"] == "no_vinculado"


def test_flujo_de_vinculacion_por_mensajes(entorno):
    _, v, mz, _ = entorno
    mala = mz.manejar(M("emparejar", {"codigo": "AAAA-AAAA"}))
    assert not mala["ok"] and mala["error"]["codigo"] == "no_vinculado"
    ok = mz.manejar(M("emparejar", {"codigo": v.codigo_actual()[0], "nombre": "Chrome del trabajo"}))
    tk = ok["datos"]["token"]
    assert mz.manejar(M("listar", {}, token=tk))["ok"]
    assert mz.manejar(M("desvincular", {}, token=tk))["datos"]["desvinculado"] is True
    assert not mz.manejar(M("listar", {}, token=tk))["ok"]      # ya no sirve


def test_detectar_obtiene_datos_y_espera_la_orden_de_descargar(entorno):
    import time
    cola, v, mz, _ = entorno
    tk = v.emparejar(v.codigo_actual()[0])
    t = mz.manejar(M("detectar", {"url": "https://a.com/v"}, token=tk))["datos"]
    assert t["estado"] == "detectado"
    for _ in range(100):                                        # los datos llegan en segundo plano
        d = mz.manejar(M("estado", {"id": t["id"]}, token=tk))["datos"]
        if d["titulo"]:
            break
        time.sleep(0.05)
    assert (d["titulo"], d["miniatura"], d["duracion"], d["estado"]) == ("Título largo", "https://a.com/t.jpg", 61, "detectado")
    # «Eliminar» desde la extensión quita la tarea; la app no descarga nada hasta recibir «iniciar».
    assert mz.manejar(M("eliminar", {"id": t["id"]}, token=tk))["ok"]
    assert cola.listar() == []


def test_limpiar_y_abrir_carpeta(entorno, tmp_path):
    cola, v, mz, abiertas = entorno
    tk = v.emparejar(v.codigo_actual()[0])
    t = cola.db.crear_tarea("https://a.com/v")
    sin_carpeta = mz.manejar(M("abrir_carpeta", {"id": t.id}, token=tk))
    assert not sin_carpeta["ok"]
    t.estado, t.carpeta_final = EstadoTarea.COMPLETADO, str(tmp_path)
    cola.db.guardar_tarea(t)
    assert mz.manejar(M("abrir_carpeta", {"id": t.id}, token=tk))["ok"] and abiertas == [str(tmp_path)]
    assert mz.manejar(M("limpiar", {}, token=tk))["datos"]["eliminadas"] == 1
    assert cola.listar() == []


def test_base_de_datos_antigua_se_migra(tmp_path):
    import sqlite3
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript("CREATE TABLE tareas (id TEXT PRIMARY KEY, url TEXT NOT NULL, origen TEXT, titulo TEXT, sitio TEXT, "
                      "estado TEXT NOT NULL, progreso REAL, velocidad_bps REAL, eta_seg REAL, creado TEXT NOT NULL, "
                      "actualizado TEXT NOT NULL, opciones TEXT NOT NULL DEFAULT '{}', destino_manual TEXT, carpeta_final TEXT, "
                      "archivos TEXT NOT NULL DEFAULT '[]', error TEXT, intentos INTEGER NOT NULL DEFAULT 0, "
                      "notas TEXT NOT NULL DEFAULT '[]'); INSERT INTO tareas (id,url,estado,creado,actualizado) VALUES ('a','https://x.com','pendiente','t','t');")
    con.commit(); con.close()
    d = BaseDatos(ruta)
    t = d.obtener_tarea("a")
    assert t.miniatura is None and t.duracion is None
    d.cerrar()
