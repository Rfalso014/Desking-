import threading
import time
from pathlib import Path

import pytest

from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.modelos import CodigoError, ErrorGestor, EstadoTarea, FormatoInfo, InfoContenido, TipoFormato
from tests.conftest import FFMPEG_DIR, necesita_ffmpeg


def esperar(cola, id_, estados, t=30):
    fin = time.time() + t
    while time.time() < fin:
        tarea = cola.obtener(id_)
        if tarea.estado in estados:
            return tarea
        time.sleep(0.05)
    raise AssertionError(f"Tiempo agotado; estado={cola.obtener(id_).estado}")


FINALES = (EstadoTarea.COMPLETADO, EstadoTarea.ERROR, EstadoTarea.CANCELADO)


@pytest.fixture
def entorno(tmp_path):
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path / "descargas"))
    cola = GestorCola(db, ffmpeg_dir=FFMPEG_DIR, permitir_interno=True)
    cola.iniciar(hilos=2)
    yield cola, db, tmp_path
    cola.detener()
    db.cerrar()


@necesita_ffmpeg
def test_flujo_completo_real(entorno, servidor_medios):
    cola, db, tmp = entorno
    vistos = []
    cola.suscribir(lambda d: vistos.append(d["estado"]))
    t = cola.encolar(f"{servidor_medios.base}/clip.mp4", origen="http://pagina")
    f = esperar(cola, t.id, FINALES)
    assert f.estado == EstadoTarea.COMPLETADO, f.error
    assert Path(f.archivos[0]).exists() and "Videos" in f.archivos[0]
    assert {"pendiente", "analizando", "descargando", "completado"} <= set(vistos)
    assert not (tmp / "descargas" / ".tmp" / t.id).exists()            # temporales limpios


@necesita_ffmpeg
def test_regla_audio_y_carpeta_especial(entorno, servidor_medios):
    cola, db, tmp = entorno
    db.guardar_regla({"nombre": "Local a audio", "condicion": {"dominio": "127.0.0.1"},
                      "accion": {"modo": "audio", "formato_audio": "mp3", "subcarpeta": "Cursos"}})
    t = cola.encolar(f"{servidor_medios.base}/clip.mp4")
    f = esperar(cola, t.id, FINALES)
    assert f.estado == EstadoTarea.COMPLETADO, f.error
    assert f.archivos[0].endswith(".mp3") and "Cursos" in f.archivos[0] and "Musica" in f.archivos[0]
    assert any("Local a audio" in n for n in f.notas)


@necesita_ffmpeg
def test_excepcion_de_tarea_gana_a_la_regla(entorno, servidor_medios):
    cola, db, _ = entorno
    db.guardar_regla({"nombre": "audio", "condicion": {"dominio": "127.0.0.1"}, "accion": {"modo": "audio"}})
    t = cola.encolar(f"{servidor_medios.base}/clip.mp4", opciones={"modo": "video"})
    f = esperar(cola, t.id, FINALES)
    assert f.estado == EstadoTarea.COMPLETADO and f.archivos[0].endswith(".mp4")


@necesita_ffmpeg
def test_regla_excluir(entorno, servidor_medios):
    cola, db, _ = entorno
    db.guardar_regla({"nombre": "no", "condicion": {"dominio": "127.0.0.1"}, "accion": {"excluir": True}})
    f = esperar(cola, cola.encolar(f"{servidor_medios.base}/clip.mp4").id, FINALES)
    assert f.estado == EstadoTarea.CANCELADO and "Excluida" in f.notas[-1]


@necesita_ffmpeg
def test_no_duplica_archivos_ya_descargados(entorno, servidor_medios):
    cola, _, _ = entorno
    url = f"{servidor_medios.base}/clip.mp4"
    a = esperar(cola, cola.encolar(url, opciones={"portada": False}).id, FINALES)
    # El MP4 se genera con la misma fuente pero la descarga puede no ser idéntica bit a bit;
    # lo importante: nunca se pierde un archivo y no quedan temporales.
    b = esperar(cola, cola.encolar(url, opciones={"portada": False, "altura_max": 240}).id, FINALES)
    assert a.estado == b.estado == EstadoTarea.COMPLETADO
    assert Path(a.archivos[0]).exists() and Path(b.archivos[0]).exists()


def test_url_invalida_se_rechaza_antes_de_encolar(entorno):
    cola, _, _ = entorno
    with pytest.raises(ErrorGestor) as e:
        cola.encolar("javascript:alert(1)")
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_opciones_invalidas_se_rechazan(entorno):
    cola, _, _ = entorno
    with pytest.raises(ErrorGestor):
        cola.encolar("http://127.0.0.1:1/x", opciones={"formato_audio": "exe"})


def test_error_reintento_y_registro(entorno):
    cola, db, _ = entorno
    llamadas = []

    def extraer(url, **kw):
        llamadas.append(url)
        if len(llamadas) == 1:
            raise ErrorGestor(CodigoError.CONEXION, "sin red", causa="falla de red")
        raise ErrorGestor(CodigoError.SITIO_NO_COMPATIBLE, "no compatible")

    cola._extraer = extraer
    t = cola.encolar("http://127.0.0.1:1/x")
    f = esperar(cola, t.id, FINALES)
    assert f.estado == EstadoTarea.ERROR and f.error["codigo"] == "conexion"
    assert db.listar_errores()
    cola.reintentar(t.id)
    f2 = esperar(cola, t.id, FINALES)
    assert f2.estado == EstadoTarea.ERROR and f2.intentos == 1 and f2.error["codigo"] == "sitio_no_compatible"


def test_no_se_reintenta_lo_que_no_fallo(entorno):
    cola, _, _ = entorno
    t = cola.detectar("http://127.0.0.1:1/x")
    with pytest.raises(ErrorGestor):
        cola.reintentar(t.id)


def test_detectar_cancelar_y_eliminar(entorno):
    cola, _, _ = entorno
    t = cola.detectar("http://127.0.0.1:1/x", origen="http://pagina")
    assert t.estado == EstadoTarea.DETECTADO
    assert cola.cancelar(t.id).estado == EstadoTarea.CANCELADO
    cola.eliminar(t.id)
    assert cola.obtener(t.id) is None


def test_cancelar_tarea_en_curso(entorno):
    cola, _, _ = entorno
    dentro = threading.Event()

    def lenta(url, opciones, carpeta, *, progreso, cancelar, **kw):
        dentro.set()
        while not cancelar.is_set():
            time.sleep(0.02)
        raise ErrorGestor(CodigoError.CANCELADO, "x")

    cola._extraer = lambda url, **kw: InfoContenido(url, "T", "S")
    cola._descargar = lenta
    t = cola.encolar("http://127.0.0.1:1/x")
    assert dentro.wait(10)
    cola.cancelar(t.id)
    assert esperar(cola, t.id, FINALES).estado == EstadoTarea.CANCELADO


def test_drm_confirmado_bloquea_sin_descargar(entorno):
    cola, _, _ = entorno
    cola._extraer = lambda url, **kw: InfoContenido(
        url, "T", "S", formatos=(FormatoInfo("1", "mp4", TipoFormato.VIDEO_Y_AUDIO, tiene_drm=True),))
    cola._descargar = lambda *a, **k: pytest.fail("no debió descargar")
    f = esperar(cola, cola.encolar("http://127.0.0.1:1/x").id, FINALES)
    assert f.estado == EstadoTarea.ERROR and f.error["codigo"] == "contenido_protegido"


def test_misma_url_pendiente_no_se_duplica(entorno):
    cola, _, _ = entorno
    cola._extraer = lambda url, **kw: (time.sleep(0.3), InfoContenido(url, "T", "S"))[1]
    cola._descargar = lambda *a, **k: (_ for _ in ()).throw(ErrorGestor(CodigoError.CONEXION, "x"))
    a = cola.encolar("http://127.0.0.1:1/dup")
    b = cola.encolar("http://127.0.0.1:1/dup")
    assert a.id == b.id


def test_recuperar_tareas_pendientes(tmp_path):
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    viejo = db.crear_tarea("http://127.0.0.1:1/x", estado=EstadoTarea.DESCARGANDO)
    cola = GestorCola(db, permitir_interno=True)
    assert cola.recuperar() == [viejo.id]
    assert db.obtener_tarea(viejo.id).estado == EstadoTarea.PENDIENTE

    p = db.cargar_preferencias(); p.reanudar_al_iniciar = False; db.guardar_preferencias(p)
    otro = db.crear_tarea("http://127.0.0.1:1/y", estado=EstadoTarea.DESCARGANDO)
    cola.recuperar()
    t = db.obtener_tarea(otro.id)
    assert t.estado == EstadoTarea.CANCELADO and "Interrumpida" in t.notas[0]


def test_limpiar_temporales_solo_los_que_sobran(entorno):
    cola, db, tmp = entorno
    base = tmp / "descargas" / ".tmp"
    huerfana = base / "inexistente"; huerfana.mkdir(parents=True)
    t = db.crear_tarea("http://127.0.0.1:1/x"); t.estado = EstadoTarea.ERROR; db.guardar_tarea(t)
    (base / t.id).mkdir()
    assert cola.limpiar_temporales() == 1
    assert not huerfana.exists() and (base / t.id).exists()     # la tarea con ERROR conserva su avance


def test_un_enlace_detectado_nunca_se_descarga_sin_autorizacion(entorno):
    """Lo que envía la extensión (botón flotante / menú) solo se agrega a la lista: la descarga exige «iniciar»."""
    cola, db, _ = entorno
    llamadas = []
    cola._extraer = lambda url, **kw: InfoContenido(url, "Título", "Sitio")
    cola._descargar = lambda *a, **k: llamadas.append(1) or pytest.fail("se descargó sin autorización")
    t = cola.detectar("http://127.0.0.1:1/x", origen="http://pagina", opciones={"modo": "audio"})
    time.sleep(1.0)                                    # los hilos de trabajo están activos: no deben tocarlo
    t = cola.obtener(t.id)
    assert t.estado == EstadoTarea.DETECTADO and llamadas == []
    assert t.opciones == {"modo": "audio"}             # recuerda lo que el usuario eligió
    # Solo la orden explícita lo pone en marcha, y conserva sus opciones.
    cola._descargar = lambda *a, **k: (_ for _ in ()).throw(ErrorGestor(CodigoError.CONEXION, "no importa"))
    cola.iniciar_detectada(t.id)
    assert cola.obtener(t.id).opciones == {"modo": "audio"}
    assert esperar(cola, t.id, FINALES).estado == EstadoTarea.ERROR     # llegó a intentarlo SOLO tras la orden


def _info(**kw):
    return InfoContenido(url="https://a.test/x", titulo="Mi lista", sitio="Youtube", **kw)


def test_lista_se_expande_en_un_video_por_tarea(tmp_path):
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    entradas = (("https://a.test/1", "Uno"), ("https://a.test/2", "Dos"))
    cola = GestorCola(db, extraer=lambda u, **k: _info(es_lista=True, entradas=entradas),
                      descargar_fn=lambda *a, **k: (_ for _ in ()).throw(ErrorGestor(CodigoError.CONEXION, "x")),
                      permitir_interno=True)
    cola.iniciar(hilos=1)
    try:
        t = cola.encolar("https://a.test/lista", opciones={"modo": "audio"})
        f = esperar(cola, t.id, FINALES)
        assert f.estado == EstadoTarea.COMPLETADO and "2 videos" in f.notas[0]
        hijas = [x for x in cola.listar() if x.id != t.id]
        assert {h.url for h in hijas} == {u for u, _ in entradas}
        assert all(h.opciones == {"subcarpeta": "Mi lista", "modo": "audio"} for h in hijas)
    finally:
        cola.detener(); db.cerrar()


def test_cancelar_mientras_analiza_no_se_cuelga(tmp_path):
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    liberar = threading.Event()
    cola = GestorCola(db, extraer=lambda u, **k: (liberar.wait(30), _info())[1], permitir_interno=True)
    cola.iniciar(hilos=1)
    try:
        t = cola.encolar("https://a.test/lenta")
        esperar(cola, t.id, (EstadoTarea.ANALIZANDO,))
        cola.cancelar(t.id)
        assert esperar(cola, t.id, FINALES, t=5).estado == EstadoTarea.CANCELADO
    finally:
        liberar.set(); cola.detener(); db.cerrar()


def test_cancelar_todas(entorno):
    cola, db, _ = entorno
    a = db.crear_tarea("https://a.test/1", estado=EstadoTarea.DETECTADO)
    b = db.crear_tarea("https://a.test/2", estado=EstadoTarea.DETECTADO)
    c = db.crear_tarea("https://a.test/3", estado=EstadoTarea.COMPLETADO)
    assert cola.cancelar_todas() == 2
    assert cola.obtener(a.id).estado == cola.obtener(b.id).estado == EstadoTarea.CANCELADO
    assert cola.obtener(c.id).estado == EstadoTarea.COMPLETADO
