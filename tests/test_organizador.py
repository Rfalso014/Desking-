from dataclasses import replace

import pytest

from gestor.config import Preferencias
from gestor.descargador import ArchivoDescargado, RolArchivo
from gestor.modelos import ErrorGestor
from gestor.organizador import carpeta_destino, colocar_archivo, confinar, organizar, sanear_nombre


@pytest.mark.parametrize("entrada, esperado", [
    ("Hola: mundo?", "Hola_ mundo_"),
    ("  espacios  ", "espacios"),
    ("punto final...", "punto final"),
    ("CON", "_CON"), ("nul.txt", "_nul.txt"), ("", "Sin nombre"), ("???", "___"),
    ("..\\..\\sistema", "_.._sistema"),
])
def test_sanear_nombre(entrada, esperado):
    assert sanear_nombre(entrada) == esperado


def test_sanear_nombre_largo():
    assert len(sanear_nombre("a" * 500)) == 100


def test_confinar(tmp_path):
    assert confinar(tmp_path / "a" / "b", tmp_path)
    with pytest.raises(ErrorGestor):
        confinar(tmp_path / ".." / "fuera", tmp_path)


@pytest.mark.parametrize("org, esperado", [
    ("tipo_y_contenido", ("Videos", "Mi título")),
    ("tipo", ("Videos",)),
    ("contenido", ("Mi título",)),
])
def test_carpeta_destino(tmp_path, org, esperado):
    p = Preferencias(carpeta_raiz=tmp_path, organizacion=org)
    assert carpeta_destino(p, RolArchivo.VIDEO, "Mi título") == tmp_path.resolve().joinpath(*esperado)


def test_titulo_malicioso_no_escapa_de_la_raiz(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path)
    d = carpeta_destino(p, RolArchivo.VIDEO, "..\\..\\..\\Windows\\System32")
    assert tmp_path.resolve() in d.parents


def test_regla_con_subcarpeta(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path, organizacion="tipo")
    assert carpeta_destino(p, RolArchivo.AUDIO, "x", subcarpeta="Cursos") == tmp_path.resolve() / "Cursos" / "Musica"


def test_manual_exige_carpeta(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path, organizacion="manual")
    with pytest.raises(ErrorGestor):
        carpeta_destino(p, RolArchivo.VIDEO, "x")
    assert carpeta_destino(p, RolArchivo.VIDEO, "x", carpeta_manual=tmp_path / "mia") == tmp_path / "mia"


def _archivo(carpeta, nombre, contenido):
    f = carpeta / nombre
    f.write_bytes(contenido)
    return f


def test_duplicados_politicas(tmp_path):
    dest, tmp = tmp_path / "d", tmp_path / "t"
    tmp.mkdir()
    colocar_archivo(_archivo(tmp, "a.mp4", b"uno"), dest, "a.mp4", "renombrar")

    # idéntico -> nunca se duplica, sea cual sea la política
    r = colocar_archivo(_archivo(tmp, "a.mp4", b"uno"), dest, "a.mp4", "renombrar")
    assert r.accion == "omitido_identico" and len(list(dest.iterdir())) == 1

    # distinto + renombrar
    r = colocar_archivo(_archivo(tmp, "a.mp4", b"dos"), dest, "a.mp4", "renombrar")
    assert r.accion == "renombrado" and r.ruta.name == "a (2).mp4"
    # distinto + omitir
    r = colocar_archivo(_archivo(tmp, "a.mp4", b"tres"), dest, "a.mp4", "omitir")
    assert r.accion == "omitido_existente" and (dest / "a.mp4").read_bytes() == b"uno"
    # distinto + reemplazar
    r = colocar_archivo(_archivo(tmp, "a.mp4", b"cuatro"), dest, "a.mp4", "reemplazar")
    assert r.accion == "reemplazado" and (dest / "a.mp4").read_bytes() == b"cuatro"
    assert not list(tmp.iterdir())            # la carpeta temporal queda vacía


def test_politica_invalida(tmp_path):
    with pytest.raises(ErrorGestor):
        colocar_archivo(_archivo(tmp_path, "a", b"x"), tmp_path / "d", "a", "borrar_todo")


def test_organizar_junta_todo_con_el_principal(tmp_path):
    tmp = tmp_path / "t"
    tmp.mkdir()
    archivos = (ArchivoDescargado(_archivo(tmp, "v.mp4", b"v"), RolArchivo.VIDEO),
                ArchivoDescargado(_archivo(tmp, "v.es.srt", b"s"), RolArchivo.SUBTITULO),
                ArchivoDescargado(_archivo(tmp, "v.jpg", b"p"), RolArchivo.PORTADA))
    p = Preferencias(carpeta_raiz=tmp_path / "raiz")
    organizar(archivos, p, "Mi video")
    final = tmp_path / "raiz" / "Videos" / "Mi video"
    assert sorted(f.name for f in final.iterdir()) == ["v.es.srt", "v.jpg", "v.mp4"]


def test_organizar_por_tipo_separa(tmp_path):
    tmp = tmp_path / "t"
    tmp.mkdir()
    archivos = (ArchivoDescargado(_archivo(tmp, "v.mp4", b"v"), RolArchivo.VIDEO),
                ArchivoDescargado(_archivo(tmp, "v.jpg", b"p"), RolArchivo.PORTADA))
    organizar(archivos, replace(Preferencias(carpeta_raiz=tmp_path / "r"), organizacion="tipo"), "x")
    assert (tmp_path / "r" / "Videos" / "v.mp4").exists() and (tmp_path / "r" / "Portadas" / "v.jpg").exists()


def test_carpeta_elegida_separa_por_tipo_en_el_lugar_elegido(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path / "defecto")
    otro = tmp_path / "otro"
    for rol, sub in ((RolArchivo.VIDEO, "Videos"), (RolArchivo.AUDIO, "Musica"),
                     (RolArchivo.SUBTITULO, "Subtitulos"), (RolArchivo.PORTADA, "Portadas")):
        assert carpeta_destino(p, rol, "titulo", subcarpeta="Curso", base=otro) == otro.resolve() / "Curso" / sub


def test_carpeta_con_nombre_malicioso_no_sale_del_lugar_elegido(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path)
    d = carpeta_destino(p, RolArchivo.VIDEO, "x", subcarpeta=r"..\..\Windows", base=tmp_path / "otro")
    assert (tmp_path / "otro").resolve() in d.parents
