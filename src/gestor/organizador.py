"""Decide DÓNDE queda cada archivo y evita pisar o duplicar lo que ya existe."""
import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Preferencias
from .descargador import ArchivoDescargado, RolArchivo
from .modelos import CodigoError, ErrorGestor

CARPETA_POR_ROL = {
    RolArchivo.VIDEO: "Videos",
    RolArchivo.AUDIO: "Musica",
    RolArchivo.SUBTITULO: "Subtitulos",
    RolArchivo.PORTADA: "Portadas",
}
CARPETA_IMAGENES = "Imagenes"
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
POLITICAS = ("omitir", "reemplazar", "renombrar")
ORGANIZACIONES = ("tipo_y_contenido", "tipo", "contenido", "manual")


def sanear_nombre(texto: str, *, maximo: int = 100, por_defecto: str = "Sin nombre") -> str:
    """Convierte un texto cualquiera en un nombre de carpeta/archivo seguro en Windows."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", texto or "")
    s = re.sub(r"\s+", " ", s).strip(" .")[:maximo].strip(" .")
    if not s or s.split(".")[0].upper() in _RESERVADOS:
        s = f"_{s}" if s else por_defecto
    return s


def confinar(ruta: Path, raiz: Path) -> Path:
    """Devuelve la ruta resuelta si está DENTRO de `raiz`; si no, lanza error."""
    r, base = ruta.resolve(), raiz.resolve()
    if r != base and base not in r.parents:
        raise ErrorGestor(CodigoError.CONFIGURACION, "El destino queda fuera de la carpeta de descargas.",
                          solucion="Revisa la configuración de carpetas.", detalle_tecnico=str(r))
    return r


def carpeta_destino(prefs: Preferencias, rol: RolArchivo | str, titulo: str, *,
                    carpeta_manual: Path | None = None, subcarpeta: str | None = None,
                    base: Path | None = None, carpeta_propia: bool = True) -> Path:
    """Carpeta final para un archivo según la organización elegida.

    `subcarpeta` es la carpeta con nombre propio (de una regla o elegida por el usuario, p. ej. "Cursos"):
    dentro quedan Videos, Musica, Subtitulos y Portadas. `base` es el lugar elegido para guardar; sin él
    se usa la carpeta de descargas predeterminada. Con `carpeta_propia=False` no se crea la carpeta con el
    titulo del contenido: el archivo queda suelto en la de su tipo (o en la raiz, con organizacion «contenido»).
    """
    if prefs.organizacion not in ORGANIZACIONES:
        raise ErrorGestor(CodigoError.CONFIGURACION, f"Organización no válida: {prefs.organizacion!r}.")
    base = base or prefs.carpeta_raiz
    raiz = base
    if subcarpeta:
        raiz = raiz / sanear_nombre(subcarpeta)
    if prefs.organizacion == "manual":
        if carpeta_manual is None:
            raise ErrorGestor(CodigoError.CONFIGURACION, "Falta elegir la carpeta de destino.")
        return carpeta_manual            # el usuario la eligió a propósito: no se confina
    tipo = CARPETA_POR_ROL.get(RolArchivo(rol), CARPETA_IMAGENES) if rol != "imagen" else CARPETA_IMAGENES
    contenido = sanear_nombre(titulo)
    if prefs.organizacion == "tipo":
        destino = raiz / tipo
    elif prefs.organizacion == "contenido":
        destino = raiz / contenido if carpeta_propia else raiz
    elif not carpeta_propia:
        destino = raiz / tipo
    elif subcarpeta:   # la carpeta ya agrupa el contenido: dentro solo se separa por tipo
        destino = raiz / tipo
    else:  # tipo_y_contenido: el tipo lo decide el archivo PRINCIPAL; el resto va junto
        destino = raiz / tipo / contenido
    return confinar(destino, base)


def _hash(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _identicos(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and _hash(a) == _hash(b)


@dataclass(frozen=True)
class Colocado:
    ruta: Path | None
    accion: str      # "movido" | "renombrado" | "reemplazado" | "omitido_identico" | "omitido_existente"


def colocar_archivo(origen: Path, carpeta: Path, nombre: str, politica: str) -> Colocado:
    """Mueve `origen` a `carpeta/nombre` aplicando la política de duplicados."""
    if politica not in POLITICAS:
        raise ErrorGestor(CodigoError.CONFIGURACION, f"Política de duplicados no válida: {politica!r}.")
    carpeta.mkdir(parents=True, exist_ok=True)
    # Windows no admite rutas de más de 260 caracteres: en carpetas profundas se acorta el nombre (con margen
    # para « (2)» si hay que renombrar).
    maximo = max(20, min(150, 250 - len(str(carpeta)) - 1 - len(Path(nombre).suffix) - 5))
    nombre = sanear_nombre(Path(nombre).stem, maximo=maximo) + Path(nombre).suffix
    destino = carpeta / nombre

    if destino.exists():
        if _identicos(origen, destino):
            origen.unlink()
            return Colocado(destino, "omitido_identico")     # ya existe exactamente igual
        if politica == "omitir":
            origen.unlink()
            return Colocado(destino, "omitido_existente")
        if politica == "reemplazar":
            shutil.move(str(origen), str(destino))             # shutil.move reemplaza en el mismo disco
            return Colocado(destino, "reemplazado")
        n = 2
        while True:
            candidato = carpeta / f"{destino.stem} ({n}){destino.suffix}"
            if not candidato.exists():
                shutil.move(str(origen), str(candidato))
                return Colocado(candidato, "renombrado")
            if _identicos(origen, candidato):
                origen.unlink()
                return Colocado(candidato, "omitido_identico")
            n += 1
    shutil.move(str(origen), str(destino))
    return Colocado(destino, "movido")


def organizar(archivos: tuple[ArchivoDescargado, ...], prefs: Preferencias, titulo: str, *,
              carpeta_manual: Path | None = None, subcarpeta: str | None = None,
              base: Path | None = None, carpeta_propia: bool = True) -> list[Colocado]:
    """Mueve todos los archivos de una tarea a su destino final."""
    principal = next((a for a in archivos if a.rol in (RolArchivo.VIDEO, RolArchivo.AUDIO)), archivos[0])
    resultados = []
    for a in archivos:
        # Con organización "contenido" o "tipo_y_contenido" todo va junto (carpeta del principal).
        rol_carpeta = principal.rol if prefs.organizacion in ("contenido", "tipo_y_contenido") else a.rol
        destino = carpeta_destino(prefs, rol_carpeta, titulo, carpeta_manual=carpeta_manual, subcarpeta=subcarpeta,
                                  base=base, carpeta_propia=carpeta_propia)
        resultados.append(colocar_archivo(a.ruta, destino, a.ruta.name, prefs.duplicados))
    return resultados
