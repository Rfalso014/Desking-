# Gestor de Descargas

Aplicación de escritorio (Python + PySide6) y extensión de navegador (Chrome/Edge, Manifest V3) para descargar y organizar **video, audio, subtítulos, portadas e imágenes** de muchos sitios (usa [yt-dlp](https://github.com/yt-dlp/yt-dlp), FFmpeg y gallery-dl).

**Regla de oro: la extensión no descarga nada.** Solo detecta videos y manda órdenes («descargar», «cancelar», «eliminar»…). Quien descarga siempre es la aplicación, y **nada se descarga hasta que tú lo autorices**.

```
Extensión (MV3) ──stdio──► Host nativo ──pipe con clave──► Aplicación (PySide6 · cola · SQLite · yt-dlp · FFmpeg)
   (lee la página)         (puente)                         (valida, descarga, organiza)
```

## Qué hace

- **Qué descargar, combinable:** Video, Audio (MP3, M4A, FLAC, OGG, OPUS, WAV o pista original), Subtítulos (con idiomas, p. ej. `es,en`) y Portada; más calidad máxima.
- **Botón sobre los videos** («＋ Añadir») y menú de clic derecho: solo agregan el enlace a tu lista como *Detectado*. Tú eliges qué quieres y pulsas **Descargar**.
- **Cola** con progreso, velocidad y tiempo restante, cancelar, reintentar, recuperar tareas tras cerrar, y errores explicados (causa, qué hacer, detalles técnicos).
- **Organización** automática por tipo y por contenido, detección de duplicados, reglas por sitio (p. ej. «en youtube.com solo audio»).
- **Historial** con búsqueda, en SQLite.
- **DRM:** solo *detecta y explica* (compatible / parcial / protegido / desconocido). No elude ninguna protección.
- **Vinculación segura:** la aplicación solo obedece a extensiones vinculadas con un código que ella misma muestra.

## Instalar y ejecutar (Windows, desarrollo)

Requisitos: Python 3.11+ (probado con 3.13), Chrome o Edge.

```powershell
git clone https://github.com/Rfalso014/Desking-.git
cd Desking-
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**FFmpeg** (necesario para unir y convertir): descarga una build para Windows (por ejemplo la de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)), verifica su SHA256 y coloca `ffmpeg.exe` y `ffprobe.exe` en `tools\ffmpeg\` (o ponlos en el PATH).
**Deno** (opcional, mejora YouTube): `pip install deno` ya lo trae en el entorno virtual.

```powershell
python -m gestor.app                 # abre la aplicación
python scripts\instalar_host.py      # registra la conexión con Chrome y Edge (solo tu usuario, sin administrador)
```

## Conectar la extensión (3 pasos)

1. **Cargar la extensión:** en `chrome://extensions` activa «Modo de desarrollador» → «Cargar descomprimida» → elige la carpeta `extension`. Su ID es fijo (`hdfnobaminegfbnoidambnkhgjmdldfb`) y es el único autorizado.
2. **Obtener el código:** en la aplicación, pestaña **Extensión**, aparece un código como `K7M2-9QXA` (dura 10 minutos y sirve una sola vez).
3. **Vincular:** abre la extensión y escribe el código. Desde ese momento la extensión puede hablar con la aplicación. Puedes revocarla cuando quieras desde la misma pestaña.

## Usar

| Quiero… | Hago… |
|---|---|
| Descargar un enlace | Pégalo en **Descargas**, marca qué quieres y pulsa **Descargar** |
| Agregar un video de una web | Pasa el cursor sobre el video → **＋ Añadir** (o clic derecho → «Añadir a Gestor de Descargas») |
| Autorizar lo agregado | Extensión → pestaña **Cola** (o la aplicación): elige qué descargar y pulsa **Descargar** |
| Ver qué ofrece un enlace | **Analizar** (calidades, subtítulos, compatibilidad) |
| Fijar lo que se descarga por defecto | Extensión → **Ajustes** → «Qué descargar por defecto» |
| Ir más rápido | Aplicación → Configuración → **Velocidad** (Normal / Rápida / Máxima) |

Sin interfaz: `python scripts\consultar.py "https://…"` muestra lo que ofrece un enlace sin descargar nada.

## Probar

```powershell
pytest                                       # ~270 pruebas, sin depender de internet
node --test extension/test/util.test.mjs     # pruebas de la extensión
```

Las pruebas descargan de verdad contra un servidor local con medios generados por FFmpeg; si FFmpeg no está, esas pruebas se omiten.

## Estructura

| Carpeta | Contenido |
|---|---|
| `src/gestor/` | núcleo: validación, extractor, descargador, organizador, cola, reglas, DRM, base de datos, vinculación, IPC |
| `src/gestor/nativo/` | host de Native Messaging e instalador (registro de Windows) |
| `src/gestor/ui/` | interfaz PySide6 (tema claro/oscuro) |
| `extension/` | extensión del navegador (JavaScript sin paso de compilación) |
| `scripts/` | instalar host, empaquetar, actualizar yt-dlp, generar íconos/clave de la extensión |
| `docs/REGISTRO.md` | decisiones, versiones verificadas, estado por fase y límites conocidos |
| `docs/LEEME_INSTALACION.txt` | guía para la versión empaquetada |

## Empaquetar un ejecutable

```powershell
.\scripts\empaquetar.ps1      # crea dist\GestorDescargas (+ .zip) con PyInstaller, FFmpeg y Deno incluidos
```

La versión empaquetada se instala con `GestorDescargas.exe --instalar-host` (ver `docs/LEEME_INSTALACION.txt`).

## Seguridad

- URL: solo http/https, sin credenciales, sin direcciones locales ni privadas (también tras resolver DNS).
- Mensajes extensión↔aplicación con lista blanca de acciones; se validan en el host y otra vez en la aplicación.
- Canal local autenticado con clave + **token de vinculación** (la aplicación solo guarda su hash).
- Rutas confinadas a la carpeta de descargas; nombres saneados; temporales en carpeta propia por tarea.
- La extensión pide permisos mínimos y no inserta contenido de páginas como HTML.

## Límites conocidos

- Probado en Windows con Chrome. **Firefox** y otros sistemas no están soportados todavía.
- Los sitios cambian: yt-dlp hay que actualizarlo con frecuencia (`python scripts\actualizar_ytdlp.py`).
- No hay soporte de cookies/inicio de sesión: los contenidos que lo exigen darán un error explicado.
- Sin firma de código: Windows SmartScreen o el antivirus pueden advertir sobre los `.exe`.
- La velocidad extra depende del sitio; con videos cortos la diferencia es imperceptible.

Más detalle y estado de cada fase en [`docs/REGISTRO.md`](docs/REGISTRO.md).

## Aviso legal

Descarga solo contenido que tengas derecho a guardar. Respeta los términos de uso de cada sitio y las leyes de derechos de autor de tu país. Esta herramienta no elude DRM ni otras protecciones.
