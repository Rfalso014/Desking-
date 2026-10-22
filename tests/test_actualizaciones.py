"""Comprobación de versiones nuevas (sin internet: se prueba la interpretación de la respuesta)."""
from gestor import __version__
from gestor.actualizaciones import comparar_versiones, interpretar_release


def test_comparar_versiones():
    assert comparar_versiones("v1.2.0", "1.1.9") == 1
    assert comparar_versiones("1.0", "1.0.0") == 0
    assert comparar_versiones("1.0.0", "v1.0.1") == -1
    assert comparar_versiones("1.10.0", "1.9.0") == 1
    assert comparar_versiones("2.0.0-beta", "1.9") == 1


def test_release_mas_nuevo_se_ofrece():
    r = interpretar_release({"tag_name": "v99.0.0", "html_url": "https://github.com/x/y/releases/tag/v99.0.0", "body": "notas"})
    assert r == {"version": "99.0.0", "nueva": True, "url": "https://github.com/x/y/releases/tag/v99.0.0", "notas": "notas",
                 "instalador": None}


def test_misma_version_o_respuesta_vacia_no_es_nueva():
    assert interpretar_release({"tag_name": f"v{__version__}"})["nueva"] is False
    assert interpretar_release({})["nueva"] is False
