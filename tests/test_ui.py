"""Pruebas de la interfaz en modo "offscreen" (sin mostrar ventanas)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from gestor.cola import GestorCola
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.modelos import ErrorGestor, EstadoTarea
from gestor.ui.dialogos import regla_desde_valores

QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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


def test_ventana_muestra_tareas_y_reglas(qapp, tmp_path):
    from gestor.ui.ventana import VentanaPrincipal
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path))
    t = db.crear_tarea("https://a.com/v"); t.titulo, t.estado = "Mi video", EstadoTarea.ERROR
    t.error = {"mensaje": "Falló", "causa": None, "solucion": "Reintenta", "detalle": "x"}; db.guardar_tarea(t)
    db.guardar_regla({"nombre": "R", "condicion": {"dominio": "a.com"}, "accion": {"modo": "audio"}})
    cola = GestorCola(db)
    v = VentanaPrincipal(cola)
    assert v.tabla.rowCount() == 1 and v.tabla.item(0, 0).text() == "Mi video"
    assert v.tabla_hist.rowCount() == 1 and v.tabla_reglas.rowCount() == 1
    v.tabla.selectRow(0)
    assert "no se pudo determinar" in v.detalle.toPlainText() and "Reintenta" in v.detalle.toPlainText()
    v.url_prueba.setText("https://www.a.com/x"); v._probar_regla()
    assert "Reglas que coinciden: R" in v.resultado_prueba.toPlainText()
    v.buscar.setText("nada que coincida")
    assert v.tabla_hist.rowCount() == 0
    v.close(); db.cerrar()


def test_guardar_configuracion(qapp, tmp_path):
    from gestor.ui.ventana import VentanaPrincipal
    db = BaseDatos(":memory:")
    v = VentanaPrincipal(GestorCola(db))
    v.c_raiz.setText(str(tmp_path / "nueva")); v.c_alt.setCurrentIndex(v.c_alt.findData("720")); v.c_idiomas.setText("es,en")
    v._guardar_config()
    p = db.cargar_preferencias()
    assert p.carpeta_raiz == tmp_path / "nueva" and p.altura_max == 720 and p.idiomas_subtitulos == ("es", "en")
    assert (tmp_path / "nueva").is_dir()
    v.close(); db.cerrar()


def test_anadir_url_invalida_no_rompe(qapp, monkeypatch):
    from gestor.ui import ventana as vm
    from gestor.ui.ventana import VentanaPrincipal
    avisos = []
    monkeypatch.setattr(vm.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    db = BaseDatos(":memory:")
    v = VentanaPrincipal(GestorCola(db))
    v.url.setText("javascript:alert(1)"); v._anadir()
    assert avisos and "http" in avisos[0]
    v.close(); db.cerrar()
