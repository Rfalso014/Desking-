# Gestor de Descargas

> ## ⬇️ [Descargar el instalador para Windows](https://github.com/Rfalso014/Desking-/releases/latest)
> Abre el enlace, baja **`GestorDescargas-…-instalador.exe`** (en *Assets*) y ábrelo con doble clic. No necesitas Python ni nada más.
> Si Windows muestra «Windows protegió su PC»: **Más información → Ejecutar de todas formas**.
> Una vez instalado se **actualiza solo** (busca versiones nuevas cada 6 horas; se puede desactivar en Ajustes).
>
> *No descargues el código («Code → Download ZIP»): eso es para programadores y necesita Python.*

Aplicación de escritorio (Python + PySide6) y extensión de navegador (Chrome/Edge, Manifest V3) para descargar y organizar **video, audio, subtítulos, portadas e imágenes** de muchos sitios (usa [yt-dlp](https://github.com/yt-dlp/yt-dlp), FFmpeg y gallery-dl).

**Regla de oro: la extensión no descarga nada.** Solo detecta videos y manda órdenes («descargar», «cancelar», «eliminar»…). Quien descarga siempre es la aplicación, y **nada se descarga hasta que tú lo autorices**.

```
Extensión (MV3) ──stdio──► Host nativo ──pipe con clave──► Aplicación (PySide6 · cola · SQLite · yt-dlp · FFmpeg)
   (lee la página)         (puente)                         (valida, descarga, organiza)
```

## Novedades de la versión 1.1.0

- **La extensión es una barra lateral** (se abre con su ícono y se queda abierta mientras navegas), con tema **día y noche**. La aplicación de escritorio tiene el mismo diseño.
- **Recortar: descargar solo unos minutos.** En YouTube pulsa **✂** sobre el video y arrastra las asas de inicio y fin sobre el propio video, o usa la página **Recortar** de la barra lateral (hasta 10 trozos). Corte rápido o exacto.
- **Modo edición:** guarda los videos en MP4 H.264 + AAC, que abren Premiere, DaVinci, CapCut, Final Cut y Vegas. Convierte con la tarjeta gráfica si puede.
- **El botón «＋ Añadir» también sale sobre las miniaturas** (sugeridos, inicio, búsquedas) y encuentra el enlace correcto en inicios y feeds.
- **Videos repetidos:** si un video ya está en tu lista, te pregunta antes de añadirlo otra vez.
- **Tamaño aproximado por calidad** antes de descargar (p. ej. «2160p ≈ 679 MB · 1080p ≈ 118 MB»).
- **Actualizar aplicación y extensión** con un botón (en Configuración de la app o en Ajustes de la extensión): pone al día la app, la extensión y yt-dlp.
- **Procesado más rápido:** usa la tarjeta gráfica para convertir y evita AV1 cuando hay que convertir.

## Qué hace

- **Qué descargar, combinable:** Video, Audio (MP3, M4A, FLAC, OGG, OPUS, WAV o pista original), Subtítulos (con idiomas, p. ej. `es,en`) y Portada; más calidad máxima.
- **Botón sobre los videos y las miniaturas** («＋ Añadir», «♪» solo audio, «✂» recortar) y menú de clic derecho: «＋» y el clic derecho solo agregan el enlace a tu lista como *Detectado*; tú eliges qué quieres y pulsas **Descargar**. «✂ Descargar trozo» descarga directamente porque ya elegiste qué quieres.
- **Recortar** uno o varios trozos de un video (corte rápido sin convertir, o exacto al segundo).
- **Modo edición** (MP4 H.264 + AAC) para cualquier programa de edición.
- **Cola** con progreso, velocidad y tiempo restante, cancelar, reintentar, recuperar tareas tras cerrar, y errores explicados (causa, qué hacer, detalles técnicos).
- **Organización** automática por tipo y por contenido, detección de duplicados (archivos y videos ya añadidos), reglas por sitio (p. ej. «en youtube.com solo audio»).
- **Actualizaciones** de la app, la extensión y yt-dlp desde la propia app o la extensión, verificadas con SHA-256.
- **Historial** con búsqueda, en SQLite.
- **DRM:** solo *detecta y explica* (compatible / parcial / protegido / desconocido). No elude ninguna protección.
- **Vinculación segura:** la aplicación solo obedece a extensiones vinculadas con un código que ella misma muestra.

## Instalar (Windows 10/11, usuarios)

1. Descarga **`GestorDescargas-<versión>-instalador.exe`** desde [Releases](https://github.com/Rfalso014/Desking-/releases/latest) (sección *Assets*).
2. Ejecútalo (si sale «Windows protegió su PC»: *Más información → Ejecutar de todas formas*). No pide administrador: se instala en `%LOCALAPPDATA%\Programs\GestorDescargas`, crea accesos directos y registra la conexión con Chrome y Edge. Opcional: «Iniciar con Windows en segundo plano».
3. Conecta la extensión (abajo). La carpeta `extension` está en el menú Inicio → *Gestor de Descargas* → «Carpeta de la extensión del navegador».

También hay una versión **portátil** (`…-portable.zip`): descomprímela y ejecuta `GestorDescargas.exe --instalar-host` una vez.
Se actualiza sola: cada 6 horas busca versiones nuevas y, si hay, las instala cuando no hay descargas en curso (casilla «Actualizar automáticamente», activada por defecto). También puedes pulsar **«Actualizar aplicación y extensión»** en *Configuración → Actualizaciones* (app) o en *Ajustes → Actualizaciones* (extensión). Con el instalador descarga e instala la versión nueva sin perder tus datos; la app se reinicia y la extensión se recarga sola (si la cargaste desde la carpeta de la instalación).
Desinstalar: *Configuración de Windows → Aplicaciones*; quita también la conexión con el navegador y el inicio con Windows.

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
$env:PYTHONPATH = "src"              # el paquete `gestor` está en src (no se instala)
python -m gestor.app                 # abre la aplicación
python scripts\instalar_host.py      # registra la conexión con Chrome y Edge (solo tu usuario, sin administrador)
```

Después de instalar la conexión, la extensión abre la aplicación sola (en segundo plano) cuando la necesita.
Para actualizar el código y las librerías: botón **«Actualizar aplicación y extensión»** (hace `git pull` si no tienes cambios sin guardar y actualiza yt-dlp, gallery-dl y Deno con pip).

## Conectar la extensión (3 pasos)

1. **Cargar la extensión:** en `chrome://extensions` activa «Modo de desarrollador» → «Cargar descomprimida» → elige la carpeta `extension`. Su ID es fijo (`hdfnobaminegfbnoidambnkhgjmdldfb`) y es el único autorizado.
2. **Obtener el código:** en la aplicación, pestaña **Extensión**, aparece un código como `K7M2-9QXA` (dura 10 minutos y sirve una sola vez).
3. **Vincular:** pulsa el ícono de la extensión (se abre la **barra lateral**) y escribe el código. Desde ese momento la extensión puede hablar con la aplicación. Puedes revocarla cuando quieras desde la misma pestaña.

Si fijas el ícono (🧩 → 📌), tendrás la barra lateral a un clic. Si la extensión avisa de que «la aplicación abierta es una versión anterior», pulsa **Reiniciar aplicación**.

## Usar

| Quiero… | Hago… |
|---|---|
| Descargar un enlace | Pégalo en **Descargas**, marca qué quieres y pulsa **Descargar** |
| Agregar un video de una web | Pasa el cursor sobre el video **o su miniatura** → **＋ Añadir** (o clic derecho → «Añadir a Gestor de Descargas») |
| Descargar solo unos minutos | En YouTube, cursor sobre el video → **✂** → arrastra las asas sobre el video (o «Marcar ahora») → **Descargar trozo**. Varios trozos: barra lateral → **Recortar** |
| Usar el video en Premiere, DaVinci, CapCut… | Marca **Para edición** (o actívalo siempre en la página **Edición** de la extensión) |
| Volver a bajar algo que ya tengo | Añádelo como siempre: te preguntará si lo quieres repetido |
| Autorizar lo agregado | Extensión → pestaña **Cola** (o la aplicación): elige qué descargar y pulsa **Descargar** |
| Ver qué ofrece un enlace | **Analizar** (calidades, subtítulos, compatibilidad) |
| Fijar lo que se descarga por defecto | Extensión → **Ajustes** → «Qué descargar por defecto» |
| Ir más rápido | Aplicación → Configuración → **Velocidad** y **Descargas a la vez**. Mira el tamaño aproximado: el 4K pesa unas 5 veces más que 1080p |
| Cambiar entre día y noche | Botón de abajo del riel (app y extensión): automático → día → noche |
| Actualizar todo | **Actualizar aplicación y extensión** (Configuración de la app o Ajustes de la extensión) |

Sin interfaz: `python scripts\consultar.py "https://…"` muestra lo que ofrece un enlace sin descargar nada.

## Probar

```powershell
pytest                                       # ~330 pruebas, sin depender de internet
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
.\scripts\empaquetar.ps1      # PyInstaller + FFmpeg + Deno → dist\GestorDescargas, .zip portátil e instalador
```

Genera en `dist\`:
- `GestorDescargas-<versión>-instalador.exe` — instalador por usuario hecho con [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`instalador\GestorDescargas.iss`). El script busca `ISCC.exe` en las rutas habituales o en la variable `ISCC`; si no lo encuentra, solo avisa.
- `GestorDescargas-<versión>-portable.zip` — la misma carpeta comprimida.

Para que otras personas puedan descargarlo, publícalo en GitHub Releases (después de `git push`):

```powershell
.\scripts\publicar_release.ps1   # crea el release v<versión> y sube el instalador y el .zip (notas: docs\NOTAS_RELEASE.md)
```

Usa la variable `GITHUB_TOKEN` o, si no existe, la misma credencial con la que git sube los cambios. Si el release ya existe, reemplaza sus archivos.

La versión sale de `src/gestor/__init__.py` (y debe coincidir con `pyproject.toml` y `extension/manifest.json`; una prueba lo comprueba).
Opciones del ejecutable: `--instalar-host`, `--desinstalar-host`, `--estado-host`, `--limpiar-sistema` (quita conexión e inicio con Windows), `--segundo-plano`, `--version`.

## Seguridad

- URL: solo http/https, sin credenciales, sin direcciones locales ni privadas (también tras resolver DNS).
- Mensajes extensión↔aplicación con lista blanca de acciones; se validan en el host y otra vez en la aplicación.
- Actualizaciones: solo por https desde PyPI y los releases de GitHub, y cada archivo se comprueba con su huella SHA-256 antes de usarlo.
- Canal local autenticado con clave + **token de vinculación** (la aplicación solo guarda su hash).
- Rutas confinadas a la carpeta de descargas; nombres saneados; temporales en carpeta propia por tarea.
- La extensión pide permisos mínimos y no inserta contenido de páginas como HTML.

## Límites conocidos

- Probado en Windows con Chrome. **Firefox** y otros sistemas no están soportados todavía.
- Los sitios cambian: yt-dlp hay que actualizarlo con frecuencia (botón **Actualizar aplicación y extensión**).
- Convertir 4K a 60 fps (corte exacto o modo edición) va más o menos a la velocidad del propio video en gráficas integradas; el AV1 solo lo decodifican las gráficas de 2020 en adelante. El corte rápido y 1080p son casi instantáneos.
- Recortar no funciona en directos que siguen emitiéndose ni en contenido protegido, y en pantalla completa no se ve la franja de recorte.
- Inicio de sesión: solo reutilizando la sesión de tu navegador o un `cookies.txt` (Configuración → Sesión); la aplicación no guarda contraseñas.
- Sin firma de código: Windows SmartScreen o el antivirus pueden advertir sobre los `.exe`.
- La velocidad extra depende del sitio; con videos cortos la diferencia es imperceptible.

Más detalle y estado de cada fase en [`docs/REGISTRO.md`](docs/REGISTRO.md).

## Aviso legal

Descarga solo contenido que tengas derecho a guardar. Respeta los términos de uso de cada sitio y las leyes de derechos de autor de tu país. Esta herramienta no elude DRM ni otras protecciones.
