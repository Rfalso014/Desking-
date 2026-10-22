"""Pruebas de la interfaz en modo "offscreen" (sin mostrar ventanas)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.modelos import ErrorGestor, EstadoTarea
from gestor.ui.dialogos import regla_desde_valores
from gestor.ui.formatos import formato_cuenta_atras, formato_duracion, formato_eta, formato_velocidad

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize("f, entrada, esperado", [
    (formato_velocidad, None, ""), (formato_velocidad, 0, ""), (formato_velocidad, 500, "500 B/s"),
    (formato_velocidad, 2048, "2.0 KB/s"), (formato_velocidad, 5 * 1048576, "5.0 MB/s"),
    (formato_eta, None, ""), (formato_eta, 45, "45 s"), (formato_eta, 125, "2 min 5 s"), (formato_eta, 3700, "1 h 1 min"),
    (formato_duracion, None, ""), (formato_duracion, 65, "1:05"), (formato_duracion, 3725, "1:02:05"),
    (formato_cuenta_atras, 598, "9:58"),
])
def test_formatos(f, entrada, esperado):
    assert f(entrada) == esperado


def test_regla_desde_valores_ok():
    r = regla_desde_valores({"nombre": " Cursos ", "prioridad": 3, "dominio": "ejemplo.com", "modo": "audio",
                             "altura": "720", "portada": "no", "subtitulos": "es, en", "subcarpeta": "Cursos"})
    assert r["nombre"] == "Cursos" and r["condicion"] == {"dominio": "ejemplo.com"}
    assert r["accion"] == {"modo": "audio", "altura_max": 720, "portada": False, "subtitulos": ["es", "en"], "subcarpeta": "Cursos"}


def test_regla_desde_valores_mejor_calidad_es_none():
    assert regla_desde_valores({"nombre": "x", "dominio": "a.com", "altura": "mejor"})["accion"] == {"altura_max": None}


@pytest.mark.parametrize("v", [{"nombre": "", "dominio": "a.com", "modo": "audio"},
                               {"nombre": "x", "modo": "audio"},                      # sin condición
                               {"nombre": "x", "dominio": "a.com"},                   # sin acción
                               {"nombre": "x", "dominio": "a.com", "subtitulos": "es;rm"}])
def test_regla_desde_valores_invalida(v):
    with pytest.raises(ErrorGestor):
        regla_desde_valores(v)


@pytest.fixture
def ventana(qapp, tmp_path):
    from gestor.ui.ventana import VentanaPrincipal
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path, tema="oscuro"))
    v = VentanaPrincipal(GestorCola(db))
    yield v, db
    v.close(); db.cerrar()


def _tarea(db, estado, titulo, **kw):
    t = db.crear_tarea(f"https://a.com/{titulo.replace(' ', '')}", estado=estado)
    t.titulo = titulo
    for k, val in kw.items():
        setattr(t, k, val)
    db.guardar_tarea(t)
    return t


def test_tarjetas_por_estado_y_botones(ventana):
    v, db = ventana
    _tarea(db, EstadoTarea.DESCARGANDO, "Bajando", progreso=40.0, velocidad_bps=3 * 1048576, eta_seg=30)
    _tarea(db, EstadoTarea.ERROR, "Fallida", error={"mensaje": "Falló", "causa": None, "solucion": "Reintenta", "detalle": "x"})
    _tarea(db, EstadoTarea.DETECTADO, "Detectada")
    v.refrescar()
    assert len(v.tarjetas) == 3 and v.vacio.isHidden()
    por_titulo = {t.titulo.text(): t for t in v.tarjetas.values()}
    bajando, fallida, detectada = por_titulo["Bajando"], por_titulo["Fallida"], por_titulo["Detectada"]
    assert "40 %" in bajando.progreso.text() and "3.0 MB/s" in bajando.progreso.text() and "30 s" in bajando.progreso.text()
    assert [b.text() for b in bajando._botones] == ["Cancelar"]
    assert [b.text() for b in fallida._botones] == ["Reintentar", "Eliminar"]
    assert "no se pudo determinar" in fallida.error.text() and "Reintenta" in fallida.error.text()   # no inventa causas
    assert [b.text() for b in detectada._botones] == ["Descargar", "Eliminar"]
    assert "MB/s" in v.dato_velocidad.text() and v.dato_descargando.text() == "1" and v.dato_espera.text() == "1"


def test_las_descargas_activas_van_arriba(ventana):
    v, db = ventana
    _tarea(db, EstadoTarea.COMPLETADO, "Vieja")
    _tarea(db, EstadoTarea.DESCARGANDO, "Activa")
    v.refrescar()
    primero = v.lista_lay.itemAt(0).widget()
    assert primero.titulo.text() == "Activa"


def test_filtros(ventana):
    v, db = ventana
    _tarea(db, EstadoTarea.COMPLETADO, "Ok"); _tarea(db, EstadoTarea.ERROR, "Mal"); _tarea(db, EstadoTarea.DESCARGANDO, "Activa")
    for filtro, esperado in [("todas", 3), ("completadas", 1), ("errores", 1), ("activas", 1)]:
        v._filtrar(filtro)
        assert len(v.tarjetas) == esperado, filtro
    v._filtrar("errores"); db.limpiar_historial(); v.refrescar()
    assert len(v.tarjetas) == 0 and not v.vacio.isHidden()


def test_acciones_de_tarjeta_llaman_a_la_cola(ventana):
    v, db = ventana
    t = _tarea(db, EstadoTarea.ERROR, "Fallida")
    v._accion_tarjeta("eliminar", t.id)
    assert db.obtener_tarea(t.id) is None and len(v.tarjetas) == 0


def test_pagina_de_extension_muestra_codigo_y_revoca(ventana):
    v, db = ventana
    v.ir_a("extension")
    codigo = v.etiqueta_codigo.text()
    assert len(codigo) == 9 and codigo[4] == "-" and "Vence en" in v.vence.text()
    token = v.vinc.emparejar(codigo, "Chrome de prueba")
    v._pintar_vinculos()
    assert v.tabla_vinculos.rowCount() == 1 and v.tabla_vinculos.item(0, 0).text() == "Chrome de prueba"
    v.vinc.revocar(v.tabla_vinculos.item(0, 0).data(0x100))        # Qt.UserRole
    assert not v.vinc.validar_token(token)
    v._pintar_codigo()
    assert v.etiqueta_codigo.text() != codigo                      # el código usado ya no se muestra


def test_historial_reglas_y_prueba_de_reglas(ventana):
    v, db = ventana
    t = _tarea(db, EstadoTarea.ERROR, "Mi video")
    db.guardar_regla({"nombre": "R", "condicion": {"dominio": "a.com"}, "accion": {"modo": "audio"}})
    v.refrescar(); v._cargar_reglas()
    assert v.tabla_hist.rowCount() == 1 and v.tabla_reglas.rowCount() == 1
    v.url_prueba.setText("https://www.a.com/x"); v._probar_regla()
    assert "Reglas que coinciden: R" in v.resultado_prueba.toPlainText()
    v.buscar.setText("nada que coincida")
    assert v.tabla_hist.rowCount() == 0


def test_guardar_configuracion_y_tema(ventana, tmp_path):
    v, db = ventana
    v.c_raiz.setText(str(tmp_path / "nueva")); v.c_alt.setCurrentIndex(v.c_alt.findData("720")); v.c_idiomas.setText("es,en")
    v.c_vel.setCurrentIndex(v.c_vel.findData("maxima")); v.c_tema.setCurrentIndex(v.c_tema.findData("claro"))
    v._guardar_config()
    p = db.cargar_preferencias()
    assert (p.carpeta_raiz, p.altura_max, p.idiomas_subtitulos, p.velocidad, p.tema) == (tmp_path / "nueva", 720, ("es", "en"), "maxima", "claro")
    assert (tmp_path / "nueva").is_dir()


def test_anadir_url_invalida_no_rompe(ventana, monkeypatch):
    from gestor.ui import ventana as vm
    avisos = []
    monkeypatch.setattr(vm.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    v, _ = ventana
    v.url.setText("javascript:alert(1)"); v._anadir()
    assert avisos and "http" in avisos[0]


def test_sugerencia_del_portapapeles(ventana, qapp):
    v, _ = ventana
    qapp.clipboard().setText("https://example.com/video")
    v._revisar_portapapeles()
    assert not v.sugerencia.isHidden() and "example.com" in v.texto_sugerencia.text()
    v.sugerencia.hide(); qapp.clipboard().setText("texto cualquiera")
    v._revisar_portapapeles()
    assert v.sugerencia.isHidden()                                  # lo que no es un enlace válido no se sugiere


def test_selector_de_elementos_por_defecto_y_combinaciones(ventana):
    v, db = ventana
    assert v.selector.opciones() == [{"modo": "video", "subtitulos": [], "portada": True}]       # valores por defecto de la configuración
    v.selector.audio.setChecked(True); v.selector.subs.setChecked(True); v.selector.idiomas.setText("es, en")
    v.selector.calidad.setCurrentIndex(v.selector.calidad.findData("720")); v.selector.formato_audio.setCurrentIndex(v.selector.formato_audio.findData("m4a"))
    video, audio = v.selector.opciones()
    assert video == {"modo": "video", "subtitulos": ["es", "en"], "portada": True, "altura_max": 720}
    assert audio == {"modo": "audio", "subtitulos": [], "portada": False, "formato_audio": "m4a"}


def test_selector_habilita_solo_lo_que_aplica(ventana):
    v, _ = ventana
    s = v.selector
    s.video.setChecked(False); s.audio.setChecked(False); s.subs.setChecked(False)
    assert not s.calidad.isEnabled() and not s.formato_audio.isEnabled() and not s.idiomas.isEnabled()
    s.audio.setChecked(True)
    assert s.formato_audio.isEnabled() and not s.calidad.isEnabled()


def test_selector_nada_marcado_o_idioma_raro_da_error_claro(ventana):
    v, _ = ventana
    s = v.selector
    s.video.setChecked(False); s.portada.setChecked(False)
    with pytest.raises(ErrorGestor) as e:
        s.opciones()
    assert "al menos una casilla" in e.value.solucion
    s.subs.setChecked(True); s.idiomas.setText("es;rm")
    with pytest.raises(ErrorGestor):
        s.opciones()


def test_anadir_con_video_y_audio_crea_dos_descargas(ventana):
    v, db = ventana
    v.selector.audio.setChecked(True)
    v.url.setText("https://a.com/v"); v._anadir()
    tareas = db.listar_tareas()
    assert sorted(t.opciones["modo"] for t in tareas) == ["audio", "video"]
    v.cola.detener()


def test_el_dialogo_recuerda_lo_que_se_eligio_al_detectar(ventana):
    from gestor.ui.dialogos import SelectorElementos
    _, db = ventana
    sel = SelectorElementos(db.cargar_preferencias(), {"modo": "audio", "subtitulos": ["en"], "portada": False, "formato_audio": "flac"})
    assert sel.audio.isChecked() and not sel.video.isChecked() and sel.subs.isChecked() and not sel.portada.isChecked()
    assert sel.idiomas.text() == "en" and sel.formato_audio.currentData() == "flac"
    assert sel.opciones() == [{"modo": "audio", "subtitulos": ["en"], "portada": False, "formato_audio": "flac"}]


def test_autorizar_detectada_inicia_y_crea_la_descarga_extra(ventana, monkeypatch):
    from gestor.ui import ventana as vm
    v, db = ventana
    t = _tarea(db, EstadoTarea.DETECTADO, "Detectada")

    class Falso:
        resultado = [{"modo": "video", "subtitulos": [], "portada": False}, {"modo": "audio", "subtitulos": [], "portada": False}]
        def __init__(self, *a, **k): pass
        def exec(self): return 1
    monkeypatch.setattr(vm, "DialogoElementos", Falso)
    llamadas = []
    monkeypatch.setattr(v.cola, "iniciar_detectada", lambda id_, op: llamadas.append(("iniciar", id_, op)))
    monkeypatch.setattr(v.cola, "encolar", lambda url, **kw: llamadas.append(("encolar", url, kw["opciones"])))
    v._accion_tarjeta("iniciar_detectada", t.id)
    assert llamadas[0] == ("iniciar", t.id, {"modo": "video", "subtitulos": [], "portada": False})
    assert llamadas[1][0] == "encolar" and llamadas[1][2]["modo"] == "audio"


def test_cancelar_el_dialogo_no_descarga_nada(ventana, monkeypatch):
    from gestor.ui import ventana as vm
    v, db = ventana
    t = _tarea(db, EstadoTarea.DETECTADO, "Detectada")

    class Falso:
        resultado = None
        def __init__(self, *a, **k): pass
        def exec(self): return 0
    monkeypatch.setattr(vm, "DialogoElementos", Falso)
    monkeypatch.setattr(v.cola, "iniciar_detectada", lambda *a: pytest.fail("no debió iniciar"))
    v._accion_tarjeta("iniciar_detectada", t.id)
    assert db.obtener_tarea(t.id).estado == EstadoTarea.DETECTADO
