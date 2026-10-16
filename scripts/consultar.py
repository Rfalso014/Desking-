r"""Prueba manual: muestra lo que ofrece una URL (no descarga nada).

Uso:  .\.venv\Scripts\python.exe scripts\consultar.py "https://..."
"""
import sys
from pathlib import Path

# Permite ejecutar este script sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gestor.extractor import obtener_info  # noqa: E402
from gestor.modelos import ErrorGestor  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        info = obtener_info(sys.argv[1])
    except ErrorGestor as e:
        print(f"ERROR [{e.codigo.value}]: {e.mensaje}")
        print(f"  Causa:    {e.causa or '(no se pudo determinar)'}")
        print(f"  Solución: {e.solucion or '-'}")
        print(f"  Detalle:  {e.detalle_tecnico or '-'}")
        return 1

    print(f"Título : {info.titulo}\nSitio  : {info.sitio}\nAutor  : {info.autor}")
    print(f"Duración: {info.duracion_seg} s | En vivo: {info.es_en_vivo} | Lista: {info.es_lista}")
    subs = [k + (" (auto)" if auto else "") for k, auto in info.subtitulos.items()]
    print("Subtítulos:", ", ".join(subs) or "ninguno")
    print(f"Formatos ({len(info.formatos)}):")
    for f in info.formatos:
        tam = f"{f.tamano_bytes / 1_048_576:.1f} MB{'~' if f.tamano_es_estimado else ''}" if f.tamano_bytes else "?"
        drm = "  [DRM]" if f.tiene_drm else ""
        print(f"  {f.id:>8} {f.extension:<5} {f.tipo.value:<12} {f.altura or '':>5}  {tam}{drm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
