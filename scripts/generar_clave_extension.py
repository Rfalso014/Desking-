r"""Genera la clave de la extensión para que su ID de Chrome sea SIEMPRE el mismo.

Chrome calcula el ID de una extensión a partir de su clave pública. Si el
manifest.json incluye el campo "key", el ID queda fijo y el host nativo puede
autorizar exactamente ese ID en `allowed_origins`.

Uso (una sola vez):  .\.venv\Scripts\python.exe scripts\generar_clave_extension.py
Escribe: extension/clave_publica.txt (se publica) y tools/clave_privada.pem (NO se sube).
"""
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

RAIZ = Path(__file__).resolve().parent.parent


def id_desde_clave_publica(der: bytes) -> str:
    """ID de Chrome: primeros 32 caracteres hex del SHA-256, con 0-f cambiados a a-p."""
    hex_ = hashlib.sha256(der).hexdigest()[:32]
    return "".join(chr(ord("a") + int(c, 16)) for c in hex_)


def main() -> None:
    privada_ruta = RAIZ / "tools" / "clave_privada.pem"
    if privada_ruta.exists():
        privada = serialization.load_pem_private_key(privada_ruta.read_bytes(), password=None)
    else:
        privada = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        privada_ruta.parent.mkdir(exist_ok=True)
        privada_ruta.write_bytes(privada.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    der = privada.public_key().public_bytes(serialization.Encoding.DER,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
    clave_b64 = base64.b64encode(der).decode()
    (RAIZ / "extension" / "clave_publica.txt").write_text(clave_b64, encoding="utf-8")

    manifiesto = RAIZ / "extension" / "manifest.json"
    datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    datos["key"] = clave_b64
    manifiesto.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("ID de la extensión:", id_desde_clave_publica(der))


if __name__ == "__main__":
    main()
