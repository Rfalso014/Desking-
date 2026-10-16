"""Funciones pequeñas para mostrar números de forma legible (sin dependencias de Qt)."""


def formato_velocidad(bps: float | None) -> str:
    if not bps or bps <= 0:
        return ""
    for unidad, f in (("GB/s", 1 << 30), ("MB/s", 1 << 20), ("KB/s", 1 << 10)):
        if bps >= f:
            return f"{bps / f:.1f} {unidad}"
    return f"{int(bps)} B/s"


def formato_eta(seg: float | None) -> str:
    if seg is None or seg < 0:
        return ""
    seg = int(seg)
    if seg >= 3600:
        return f"{seg // 3600} h {seg % 3600 // 60} min"
    if seg >= 60:
        return f"{seg // 60} min {seg % 60} s"
    return f"{seg} s"


def formato_duracion(seg: float | None) -> str:
    if not seg:
        return ""
    seg = int(seg)
    h, r = divmod(seg, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def formato_cuenta_atras(seg: int) -> str:
    return f"{seg // 60}:{seg % 60:02d}"
