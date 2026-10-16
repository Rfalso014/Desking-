"""Genera los iconos PNG de la extensión (flecha de descarga sobre fondo azul) con Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parent.parent / "extension" / "icons"
DESTINO.mkdir(exist_ok=True)

for tam in (16, 48, 128):
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, tam - 1, tam - 1), radius=tam // 5, fill=(26, 115, 232, 255))
    c, w = tam / 2, tam / 10
    d.rectangle((c - w, tam * 0.18, c + w, tam * 0.55), fill="white")                     # tallo
    d.polygon([(tam * 0.25, tam * 0.5), (tam * 0.75, tam * 0.5), (c, tam * 0.78)], fill="white")  # punta
    d.rectangle((tam * 0.2, tam * 0.82, tam * 0.8, tam * 0.82 + max(2, tam // 12)), fill="white")  # base
    img.save(DESTINO / f"{tam}.png")
print("Iconos generados en", DESTINO)
