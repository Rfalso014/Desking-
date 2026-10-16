from pathlib import Path

import pytest

from gestor import drm, reglas
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.modelos import (CodigoError, ErrorGestor, EstadoTarea, FormatoInfo, InfoContenido, TipoFormato)


# --- base de datos ----------------------------------------------------------
@pytest.fixture
def db():
    d = BaseDatos(":memory:")
    yield d
    d.cerrar()


def test_tarea_ida_y_vuelta(db):
    t = db.crear_tarea("https://example.com/a", origen="https://example.com", opciones={"modo": "audio"})
    t.titulo, t.archivos, t.notas = "Hola ñandú", ["C:/x/a.mp3"], ["nota"]
    db.guardar_tarea(t)
    r = db.obtener_tarea(t.id)
    assert (r.titulo, r.archivos, r.notas, r.opciones) == ("Hola ñandú", ["C:/x/a.mp3"], ["nota"], {"modo": "audio"})
    assert r.estado == EstadoTarea.PENDIENTE


def test_busqueda_y_filtro_y_sql_seguro(db):
    a = db.crear_tarea("https://a.com/1"); a.titulo = "Gatos 100%"; a.estado = EstadoTarea.COMPLETADO; db.guardar_tarea(a)
    b = db.crear_tarea("https://b.com/2"); b.titulo = "Perros"; db.guardar_tarea(b)
    assert [t.id for t in db.listar_tareas(texto="gatos")] == [a.id]
    assert [t.id for t in db.listar_tareas(texto="100%")] == [a.id]       # % se trata como texto literal
    assert [t.id for t in db.listar_tareas(estados=[EstadoTarea.PENDIENTE])] == [b.id]
    assert db.listar_tareas(texto="'; DROP TABLE tareas; --") == []
    assert len(db.listar_tareas()) == 2                                   # la tabla sigue viva


def test_eliminar_y_limpiar(db):
    a = db.crear_tarea("https://a.com/1"); a.estado = EstadoTarea.ERROR; db.guardar_tarea(a)
    b = db.crear_tarea("https://b.com/2")
    assert db.limpiar_historial() == 1
    assert [t.id for t in db.listar_tareas()] == [b.id]
    db.eliminar_tarea(b.id)
    assert db.listar_tareas() == []


def test_errores_registrados(db):
    db.registrar_error("x", ErrorGestor(CodigoError.CONEXION, "sin red", detalle_tecnico="timeout"))
    assert db.listar_errores()[0]["codigo"] == "conexion"


def test_preferencias_persisten(db, tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path / "d", altura_max=720, idiomas_subtitulos=("es", "en"))
    db.guardar_preferencias(p)
    r = db.cargar_preferencias()
    assert (r.carpeta_raiz, r.altura_max, r.idiomas_subtitulos) == (tmp_path / "d", 720, ("es", "en"))


def test_persistencia_en_archivo(tmp_path):
    ruta = tmp_path / "g.db"
    d1 = BaseDatos(ruta); t = d1.crear_tarea("https://a.com/1"); d1.cerrar()
    d2 = BaseDatos(ruta)
    assert d2.obtener_tarea(t.id).url == "https://a.com/1"
    d2.cerrar()


def test_crud_reglas(db):
    id_ = db.guardar_regla({"nombre": "R1", "condicion": {"dominio": "a.com"}, "accion": {"modo": "audio"}})
    db.guardar_regla({"id": id_, "nombre": "R1b", "condicion": {"dominio": "a.com"}, "accion": {"modo": "audio"}, "prioridad": 5})
    assert db.listar_reglas()[0]["nombre"] == "R1b"
    db.activar_regla(id_, False)
    assert db.listar_reglas(solo_activas=True) == []
    db.eliminar_regla(id_)
    assert db.listar_reglas() == []


# --- reglas -----------------------------------------------------------------
P = Preferencias(altura_max=1080)


def R(nombre, cond, acc, prioridad=0, activa=True, id=None):
    return {"id": id, "nombre": nombre, "condicion": cond, "accion": acc, "prioridad": prioridad, "activa": activa}


def test_sin_reglas_usa_preferencias():
    r = reglas.resolver("https://youtube.com/watch?v=1", "Youtube", [], P)
    assert r.campos["altura_max"] == 1080 and r.explicacion["altura_max"] == "preferencias globales"


def test_regla_por_dominio_incluye_subdominios():
    regla = R("YT 720", {"dominio": "youtube.com"}, {"altura_max": 720})
    assert reglas.resolver("https://www.youtube.com/x", None, [regla], P).campos["altura_max"] == 720
    assert reglas.resolver("https://notyoutube.com/x", None, [regla], P).campos["altura_max"] == 1080
    assert reglas.resolver("https://evil.com/?u=youtube.com", None, [regla], P).campos["altura_max"] == 1080


def test_prioridad_y_excepcion_de_tarea():
    baja = R("baja", {"dominio": "a.com"}, {"modo": "audio", "altura_max": 480}, prioridad=1)
    alta = R("alta", {"dominio": "a.com"}, {"altura_max": 360}, prioridad=9)
    r = reglas.resolver("https://a.com/x", None, [alta, baja], P)
    assert r.campos["modo"] == "audio" and r.campos["altura_max"] == 360     # la de más prioridad gana por campo
    assert "alta" in r.explicacion["altura_max"] and "baja" in r.explicacion["modo"]
    r2 = reglas.resolver("https://a.com/x", None, [alta, baja], P, {"altura_max": 1080})
    assert r2.campos["altura_max"] == 1080 and "esta descarga" in r2.explicacion["altura_max"]


def test_regla_desactivada_no_aplica():
    assert reglas.resolver("https://a.com", None, [R("x", {"dominio": "a.com"}, {"modo": "audio"}, activa=False)], P).campos["modo"] == "video"


def test_condiciones_son_y_logico():
    regla = R("x", {"dominio": "a.com", "url_contiene": "/curso/"}, {"modo": "audio"})
    assert reglas.coincide(regla, "https://a.com/curso/1", None)
    assert not reglas.coincide(regla, "https://a.com/otro/1", None)


def test_solo_subtitulos_no_pide_portada_ni_deja_idiomas_vacios():
    r = reglas.resolver("https://a.com/x", None, [R("subs", {"dominio": "a.com"}, {"modo": "subtitulos"})], P)
    assert r.campos["portada"] is False and r.campos["subtitulos"]
    assert r.a_opciones(P, None).modo == "subtitulos"


def test_excluir_y_subcarpeta():
    r = reglas.resolver("https://a.com/x", None, [R("c", {"dominio": "a.com"}, {"subcarpeta": "Cursos", "excluir": True})], P)
    assert r.excluir and r.subcarpeta == "Cursos"


@pytest.mark.parametrize("regla", [
    R("", {"dominio": "a.com"}, {"modo": "audio"}),
    R("x", {}, {"modo": "audio"}),
    R("x", {"dominio": "a.com"}, {}),
    R("x", {"dominio": "a.com"}, {"modo": "hackear"}),
    R("x", {"dominio": "a.com"}, {"comando": "calc"}),
    R("x", {"magia": "a.com"}, {"modo": "audio"}),
    R("x", {"dominio": "a.com"}, {"altura_max": "alta"}),
    R("x", {"dominio": "a.com"}, {"subtitulos": ["es;rm"]}),
])
def test_reglas_invalidas(regla):
    with pytest.raises(ErrorGestor):
        reglas.validar_regla(regla)


def test_eleccion_de_tarea_invalida():
    with pytest.raises(ErrorGestor):
        reglas.resolver("https://a.com", None, [], P, {"formato_audio": "exe"})


# --- DRM --------------------------------------------------------------------
def _info(*formatos):
    return InfoContenido("u", "t", "S", formatos=tuple(formatos))


def _f(id, drm_=False):
    return FormatoInfo(id, "mp4", TipoFormato.VIDEO_Y_AUDIO, tiene_drm=drm_)


def test_compatible():
    d = drm.evaluar("https://a.com/v", _info(_f("1"), _f("2")))
    assert d.nivel == drm.Compatibilidad.COMPATIBLE and not d.bloquea


def test_parcial_no_bloquea():
    d = drm.evaluar("https://a.com/v", _info(_f("1", True), _f("2")))
    assert d.nivel == drm.Compatibilidad.PARCIAL and not d.bloquea


def test_todo_drm_confirmado_bloquea():
    d = drm.evaluar("https://a.com/v", _info(_f("1", True)))
    assert d.nivel == drm.Compatibilidad.PROTEGIDO and d.confianza == drm.Confianza.CONFIRMADO and d.bloquea


def test_netflix_con_error_es_indicio_no_confirmacion():
    err = ErrorGestor(CodigoError.SITIO_NO_COMPATIBLE, "x")
    d = drm.evaluar("https://www.netflix.com/title/123", error=err)
    assert d.nivel == drm.Compatibilidad.PROTEGIDO and d.confianza == drm.Confianza.INDICIO and not d.bloquea
    assert "oficial" in d.alternativas[0]
    e2 = drm.enriquecer_error("https://www.netflix.com/title/123", err)
    assert e2.codigo == CodigoError.SITIO_NO_COMPATIBLE and "no está confirmada" in e2.causa


def test_error_sin_evidencia_es_desconocido_y_no_acusa_a_drm():
    err = ErrorGestor(CodigoError.DESCONOCIDO, "x")
    d = drm.evaluar("https://a.com/v", error=err)
    assert d.nivel == drm.Compatibilidad.DESCONOCIDO
    assert drm.enriquecer_error("https://a.com/v", err) is err


def test_error_de_drm_de_ytdlp_es_confirmado():
    err = ErrorGestor(CodigoError.CONTENIDO_PROTEGIDO, "x")
    assert drm.evaluar("https://a.com/v", error=err).bloquea


def test_dominio_parecido_no_cuenta_como_netflix():
    assert drm.evaluar("https://notnetflix.com/x", error=ErrorGestor(CodigoError.DESCONOCIDO, "x")).nivel == drm.Compatibilidad.DESCONOCIDO
