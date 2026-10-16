import pytest

from gestor.modelos import CodigoError, ErrorGestor
from gestor.validacion import validar_url


@pytest.mark.parametrize("url", [
    "https://example.com/watch?v=abc",
    "http://example.com",
    "  https://example.com/a  ",          # los espacios de los bordes se limpian
    "https://8.8.8.8/video",              # IP pública: permitida
])
def test_urls_validas(url):
    assert validar_url(url) == url.strip()


@pytest.mark.parametrize("url", [
    "", "   ", "not a url", "example.com",          # sin esquema
    "file:///C:/Windows/win.ini",                    # esquema peligroso
    "javascript:alert(1)", "ftp://example.com/a",
    "https://user:pass@example.com/",                # credenciales en la URL
    "http://localhost:8000/", "http://sub.localhost/",
    "http://127.0.0.1/", "http://192.168.1.10/", "http://10.0.0.5/",
    "http://169.254.169.254/latest/meta-data",       # metadatos de la nube
    "http://[::1]/",
    "https://example.com/a b",                       # espacio dentro
    "https://example.com:99999/",                    # puerto inválido
    "https://" + "a" * 3000 + ".com",                # demasiado larga
])
def test_urls_rechazadas(url):
    with pytest.raises(ErrorGestor) as e:
        validar_url(url)
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_permitir_interno_solo_para_pruebas():
    assert validar_url("http://127.0.0.1:8000/x", permitir_interno=True)


def test_dominio_que_resuelve_a_ip_privada_se_rechaza(monkeypatch):
    from gestor import validacion

    def falso(host, puerto):
        return [(2, 1, 6, "", ("10.0.0.7", 0))]
    monkeypatch.setattr(validacion.socket, "getaddrinfo", falso)
    with pytest.raises(ErrorGestor) as e:
        validacion.verificar_resolucion("https://parece-publico.com/x")
    assert e.value.codigo == CodigoError.URL_INVALIDA


def test_dominio_publico_y_no_resoluble_pasan(monkeypatch):
    import socket as s
    from gestor import validacion
    monkeypatch.setattr(validacion.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    validacion.verificar_resolucion("https://example.com/x")

    def no_resuelve(h, p):
        raise s.gaierror("no existe")
    monkeypatch.setattr(validacion.socket, "getaddrinfo", no_resuelve)
    validacion.verificar_resolucion("https://no-existe.invalid/x")      # que falle luego como error de conexión


def test_no_acepta_tipos_que_no_son_texto():
    with pytest.raises(ErrorGestor):
        validar_url(None)  # type: ignore[arg-type]
