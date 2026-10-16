import pytest

from gestor.config import Preferencias
from gestor.elementos import opciones_desde_elementos as op, parsear_idiomas
from gestor.modelos import ErrorGestor
from gestor.protocolo import validar_mensaje
from gestor.reglas import resolver


def test_solo_video():
    assert op(video=True) == [{"modo": "video", "subtitulos": [], "portada": False}]


def test_video_con_subtitulos_portada_y_calidad():
    [o] = op(video=True, subtitulos=True, idiomas=["es", "en"], portada=True, altura=720)
    assert o == {"modo": "video", "subtitulos": ["es", "en"], "portada": True, "altura_max": 720}


def test_calidad_mejor_es_none():
    assert op(video=True, altura="mejor")[0]["altura_max"] is None


def test_solo_audio_con_formato():
    assert op(video=False, audio=True, formato_audio="m4a") == [
        {"modo": "audio", "subtitulos": [], "portada": False, "formato_audio": "m4a"}]


def test_video_y_audio_dan_dos_descargas_y_los_extras_van_solo_con_el_primero():
    a, b = op(video=True, audio=True, subtitulos=True, idiomas=["es"], portada=True, formato_audio="mp3")
    assert a == {"modo": "video", "subtitulos": ["es"], "portada": True}
    assert b == {"modo": "audio", "subtitulos": [], "portada": False, "formato_audio": "mp3"}


def test_solo_subtitulos_y_solo_portada():
    assert op(video=False, subtitulos=True, idiomas=["es"]) == [{"modo": "subtitulos", "subtitulos": ["es"], "portada": False}]
    assert op(video=False, subtitulos=True, idiomas=["es"], portada=True)[0]["portada"] is True
    assert op(video=False, portada=True) == [{"modo": "portada", "portada": True, "subtitulos": []}]


def test_subtitulos_sin_idioma_usan_espanol():
    assert op(video=False, subtitulos=True)[0]["subtitulos"] == ["es"]


def test_sin_nada_marcado_es_un_error_claro():
    with pytest.raises(ErrorGestor) as e:
        op(video=False)
    assert "al menos una casilla" in e.value.solucion


@pytest.mark.parametrize("texto, esperado", [("es, en", ["es", "en"]), ("", []), (" es ,, es , pt-BR", ["es", "pt-BR"]), (None, [])])
def test_parsear_idiomas(texto, esperado):
    assert parsear_idiomas(texto) == esperado


@pytest.mark.parametrize("malo", ["es;rm", "español", "e", "../x"])
def test_idiomas_invalidos(malo):
    with pytest.raises(ErrorGestor):
        parsear_idiomas(malo)


def test_las_opciones_generadas_las_acepta_el_protocolo_y_el_resolutor():
    """Contrato: lo que genera esta función es válido para la app (por la extensión y por la interfaz)."""
    combos = op(video=True, audio=True, subtitulos=True, idiomas=["es"], portada=True, altura=1080, formato_audio="mp3") \
        + op(video=False, subtitulos=True, idiomas=["es", "en"]) + op(video=False, portada=True)
    for o in combos:
        validar_mensaje({"v": 1, "id": "x", "accion": "detectar", "datos": {"url": "https://a.com/v", "opciones": o}})
        validar_mensaje({"v": 1, "id": "x", "accion": "iniciar", "datos": {"id": "0123456789ab", "opciones": o}})
        r = resolver("https://a.com/v", None, [], Preferencias(descargar_subtitulos=True, descargar_portada=True), o)
        assert r.campos["modo"] == o["modo"]
        assert r.campos["subtitulos"] == o["subtitulos"] and r.campos["portada"] == o["portada"]   # prevalece sobre la configuración global
        r.a_opciones(Preferencias(), None).validar()
