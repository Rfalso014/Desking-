import httpx
import pytest

from gestor.imagenes import construir_comando_galeria, descargar_galeria, descargar_imagen
from gestor.modelos import CodigoError, ErrorGestor
from tests.conftest import necesita_ffmpeg


@necesita_ffmpeg
def test_imagen_directa(servidor_medios, tmp_path):
    ruta = descargar_imagen(f"{servidor_medios.base}/foto.png", tmp_path, permitir_interno=True)
    assert ruta.suffix == ".png" and ruta.stat().st_size > 0
    # Segunda descarga: no sobrescribe, renombra.
    ruta2 = descargar_imagen(f"{servidor_medios.base}/foto.png", tmp_path, permitir_interno=True)
    assert ruta2 != ruta and ruta2.exists() and ruta.exists()


@necesita_ffmpeg
def test_no_imagen_se_rechaza(servidor_medios, tmp_path):
    with pytest.raises(ErrorGestor):
        descargar_imagen(f"{servidor_medios.base}/pagina.html", tmp_path, permitir_interno=True)


@necesita_ffmpeg
def test_limite_de_tamano(servidor_medios, tmp_path):
    with pytest.raises(ErrorGestor) as e:
        descargar_imagen(f"{servidor_medios.base}/foto.png", tmp_path, permitir_interno=True, max_bytes=10)
    assert "tamaño" in e.value.mensaje


def test_url_interna_rechazada(tmp_path):
    with pytest.raises(ErrorGestor) as e:
        descargar_imagen("http://127.0.0.1/x.png", tmp_path)
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_redireccion_a_interno_se_bloquea(tmp_path):
    def app(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    cliente = httpx.Client(transport=httpx.MockTransport(app), follow_redirects=False)
    with pytest.raises(ErrorGestor) as e:
        descargar_imagen("https://example.com/a.png", tmp_path, cliente=cliente)
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_imagen_corrupta_se_rechaza(tmp_path):
    def app(request):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"no soy una imagen")

    cliente = httpx.Client(transport=httpx.MockTransport(app))
    with pytest.raises(ErrorGestor):
        descargar_imagen("https://example.com/a.png", tmp_path, cliente=cliente)


def test_comando_galeria_es_lista_sin_shell(tmp_path):
    cmd = construir_comando_galeria("https://example.com/g?x=1&y=2", tmp_path)
    assert isinstance(cmd, list) and cmd[-1] == "https://example.com/g?x=1&y=2"
    with pytest.raises(ErrorGestor):
        construir_comando_galeria("--exec calc", tmp_path)   # no es una URL: no llega al comando


@necesita_ffmpeg
def test_galeria_enlace_directo_con_gallery_dl(servidor_medios, tmp_path):
    archivos = descargar_galeria(f"{servidor_medios.base}/foto.png", tmp_path, permitir_interno=True)
    assert archivos and archivos[0].suffix == ".png"
