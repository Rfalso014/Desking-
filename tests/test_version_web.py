"""Lo nuevo de la versión web en el motor: carpeta propia o suelta, carpeta del grupo, respaldo por enlace directo,
sesión del navegador solo en memoria y nombres cortos en carpetas profundas."""
import time
from pathlib import Path

import pytest

from gestor import cola as modulo_cola
from gestor.cola import GestorCola, escribir_cookies, limpiar_cookies
from gestor.config import Preferencias
from gestor.db import BaseDatos
from gestor.descargador import (ARGS_FFMPEG_ENTRADA, ArchivoDescargado, OpcionesDescarga, RolArchivo,
                                construir_opciones_ytdlp, estrategia_tramos, opciones_red)
from gestor.modelos import EstadoTarea
from gestor.organizador import carpeta_destino, colocar_archivo
from tests.conftest import FFMPEG_DIR, necesita_ffmpeg

FINALES = (EstadoTarea.COMPLETADO, EstadoTarea.ERROR, EstadoTarea.CANCELADO)


def esperar(cola, id_, t=60):
    fin = time.time() + t
    while time.time() < fin:
        tarea = cola.obtener(id_)
        if tarea.estado in FINALES:
            return tarea
        time.sleep(0.05)
    raise AssertionError(f"Tiempo agotado; estado={cola.obtener(id_).estado}")


# --- carpetas -------------------------------------------------------------------------------------
def test_carpeta_propia_o_suelta(tmp_path):
    p = Preferencias(carpeta_raiz=tmp_path)
    assert carpeta_destino(p, RolArchivo.VIDEO, "Mi video") == (tmp_path / "Videos" / "Mi video").resolve()
    assert carpeta_destino(p, RolArchivo.VIDEO, "Mi video", carpeta_propia=False) == (tmp_path / "Videos").resolve()
    p.organizacion = "contenido"
    assert carpeta_destino(p, RolArchivo.AUDIO, "Canción", carpeta_propia=False) == tmp_path.resolve()
    # dentro del grupo ya no hay carpeta por título: el grupo agrupa
    p.organizacion = "tipo_y_contenido"
    assert carpeta_destino(p, RolArchivo.VIDEO, "Mi video", subcarpeta="Viaje") == (tmp_path / "Viaje" / "Videos").resolve()


def _profunda(tmp_path: Path, largo: int = 190) -> Path:
    return tmp_path / ("x" * (largo - len(str(tmp_path)) - 1))


def test_en_carpetas_profundas_el_nombre_se_acorta(tmp_path):
    origen = tmp_path / "o.mp4"
    origen.write_bytes(b"1")
    c = colocar_archivo(origen, _profunda(tmp_path), "T" * 200 + ".mp4", "renombrar")
    assert len(str(c.ruta)) <= 250 and c.ruta.suffix == ".mp4" and c.ruta.exists()


def test_la_plantilla_se_acorta_en_carpetas_profundas(tmp_path):
    import re
    o = OpcionesDescarga()
    maximo = lambda carpeta: int(re.search(r"%\(title\)\.(\d+)B", construir_opciones_ytdlp(o, carpeta, lambda d: None)["outtmpl"]).group(1))  # noqa: E731
    assert maximo(Path("C:/D")) == 120                    # carpeta normal: el título completo (120 bytes)
    assert maximo(_profunda(tmp_path)) < 60               # carpeta profunda: más corto, para no pasar de 260


# --- red: Referer, presentarse como Chrome y trozos rápidos --------------------------------------------
def test_opciones_de_red():
    assert opciones_red() == {}
    assert opciones_red("https://pagina.com/v")["http_headers"] == {"Referer": "https://pagina.com/v"}
    imitar = opciones_red(None, True)
    assert "impersonate" in imitar and imitar["extractor_args"]["generic"]["impersonate"] == [""]
    with pytest.raises(Exception):
        OpcionesDescarga(referer="javascript:x").validar()


def test_los_trozos_se_piden_por_partes_y_casi_siempre_solo_el_trozo(tmp_path):
    o = OpcionesDescarga(tramos=((300.0, 330.0),), duracion_video=600.0)
    assert estrategia_tramos(o) == "rangos"            # 30 s de 10 min: se baja solo el trozo
    p = construir_opciones_ytdlp(o, tmp_path, lambda d: None)
    assert p["external_downloader_args"]["ffmpeg_i"] == ARGS_FFMPEG_ENTRADA and "-request_size" in ARGS_FFMPEG_ENTRADA
    assert estrategia_tramos(OpcionesDescarga(tramos=((0.0, 400.0),), duracion_video=600.0)) == "completo"


# --- sesión del navegador ---------------------------------------------------------------------------
def test_las_cookies_se_sanean_y_se_escriben_en_formato_netscape(tmp_path):
    crudas = [{"name": "sid", "value": "abc", "domain": ".sitio.com", "path": "/", "secure": True, "expirationDate": 2e9},
              {"name": "mala\tcookie", "value": "x", "domain": "a.com"}, {"name": "sin_dominio", "value": "x"}, "basura"]
    limpias = limpiar_cookies(crudas)
    assert [c["name"] for c in limpias] == ["sid"]
    assert limpiar_cookies("no es lista") == [] and limpiar_cookies([{}] * 500) == []
    texto = escribir_cookies(tmp_path / "c.txt", limpias).read_text(encoding="utf-8")
    assert texto.startswith("# Netscape HTTP Cookie File") and ".sitio.com\tTRUE\t/\tTRUE\t2000000000\tsid\tabc" in texto


# --- respaldo: la página no se puede analizar pero la extensión vio el enlace directo -------------------------
@pytest.fixture
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("GESTOR_DATOS", str(tmp_path / "datos"))
    db = BaseDatos(":memory:")
    db.guardar_preferencias(Preferencias(carpeta_raiz=tmp_path / "descargas"))
    c = GestorCola(db, ffmpeg_dir=FFMPEG_DIR, permitir_interno=True)
    c.iniciar(hilos=1)
    yield c, tmp_path
    c.detener()
    db.cerrar()


@necesita_ffmpeg
def test_si_la_pagina_falla_se_usa_el_enlace_directo(entorno, servidor_medios):
    cola, tmp = entorno
    (servidor_medios.carpeta / "sin_video.html").write_text("<html><title>Nada</title><body>hola</body></html>", encoding="utf-8")
    pagina = f"{servidor_medios.base}/sin_video.html"
    t = cola.encolar(pagina, origen=pagina, opciones={"medios": [f"{servidor_medios.base}/clip.mp4"],
                                                      "titulo_pagina": "Mi clip favorito", "carpeta_propia": False})
    f = esperar(cola, t.id)
    assert f.estado == EstadoTarea.COMPLETADO, f.error
    assert Path(f.archivos[0]).parent == (tmp / "descargas" / "Videos")          # sin carpeta propia
    assert f.titulo == "Mi clip favorito"
    assert any("enlace directo" in n for n in f.notas)


@necesita_ffmpeg
def test_un_grupo_se_guarda_junto_en_su_carpeta(entorno, servidor_medios):
    cola, tmp = entorno
    t = cola.detectar(f"{servidor_medios.base}/clip.mp4", opciones={"grupo": "Viaje"})
    assert cola.iniciar_grupo("Viaje") == 1
    f = esperar(cola, t.id)
    assert f.estado == EstadoTarea.COMPLETADO, f.error
    assert Path(f.archivos[0]).parent == (tmp / "descargas" / "Viaje" / "Videos")


@necesita_ffmpeg
def test_la_sesion_se_usa_y_se_borra_al_terminar(entorno, servidor_medios, monkeypatch):
    cola, tmp = entorno
    usadas = []
    original = modulo_cola.escribir_cookies

    def espiar(ruta, cookies):
        usadas.append(ruta)
        return original(ruta, cookies)
    monkeypatch.setattr(modulo_cola, "escribir_cookies", espiar)
    cookies = [{"name": "sid", "value": "secreto", "domain": "127.0.0.1", "path": "/"}]
    t = cola.encolar(f"{servidor_medios.base}/clip.mp4", cookies=cookies)
    f = esperar(cola, t.id)
    assert f.estado == EstadoTarea.COMPLETADO, f.error
    time.sleep(0.2)
    assert usadas and not any(r.exists() for r in usadas)          # el cookies.txt temporal ya no está
    assert t.id not in cola._cookies
