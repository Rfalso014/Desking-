# Gestor de Descargas

> ## ⬇️ [Descargar el instalador para Windows](https://github.com/Rfalso014/Desking-/releases/latest)
> Abre el enlace, baja **`GestorDescargas-…-instalador.exe`** (en *Assets*) y ábrelo con doble clic. No necesitas Python ni nada más.
> Si Windows muestra «Windows protegió su PC»: **Más información → Ejecutar de todas formas**.
> Una vez instalado se **actualiza solo** (busca versiones nuevas cada 6 horas; se puede desactivar en Ajustes).
>
> *No descargues el código («Code → Download ZIP»): eso es para programadores y necesita Python.*

**Página web local** (http://127.0.0.1:7878, solo accesible desde tu equipo) y extensión de navegador (Chrome/Edge, Manifest V3) para descargar y organizar **video, audio, subtítulos, portadas e imágenes** de muchos sitios (usa [yt-dlp](https://github.com/yt-dlp/yt-dlp), FFmpeg y gallery-dl).

**Regla de oro: la extensión y la página no descargan nada.** Solo piden cosas («descargar», «al grupo», «cancelar»…). Quien descarga es el servidor del gestor, en segundo plano.

```
Página web (127.0.0.1:7878) ─┐
                             ├─ HTTP + token ─► Servidor del gestor (Python · cola · SQLite · yt-dlp · FFmpeg)
Extensión (MV3) ─────────────┘                    (valida, descarga, organiza)
GestorDescargas.exe ── panel para encender, apagar y reiniciar el servidor
```

## Novedades de la versión 2.0.0

- **Es una web.** La aplicación de escritorio se sustituye por una página en tu navegador, servida por tu propio equipo. `GestorDescargas.exe` es un panel pequeño para **encender, apagar y reiniciar** el servidor (también `--encender`, `--apagar`, `--reiniciar`, `--abrir`), con la casilla «Encender con Windows».
- **Descargar ya o en grupo** (en la página y en la extensión): «Descargar ya» empieza al momento; «Al grupo» espera en un grupo con nombre hasta que pulses **Descargar grupo**. Cada grupo se guarda en una carpeta con su nombre.
- **En su propia carpeta o no:** cada descarga en `Videos\Título\archivo.mp4` o suelta en `Videos\archivo.mp4`.
- **Más sitios funcionan:**
  - la extensión manda **tu sesión del sitio** solo para esa descarga (Vimeo, SharePoint, Outlook, cursos…; antes daban «inicia sesión» o 403);
  - si la página no se puede analizar, la extensión manda los **enlaces directos** que cargó el reproductor (m3u8, mpd, mp4) y el gestor los prueba solo, con la página como Referer;
  - en sitios con protección anti-bots (Cloudflare) se reintenta **presentándose como Chrome** (curl_cffi).
- **Recortar, 4 veces más rápido:** el trozo se pide por partes de 10 MB (como el navegador) y YouTube no lo frena. Medido: 30 s de un video de 10 min en **5,8 s** (antes 25,4 s).
- **Diseño reorganizado** en la página (Descargas · Grupos · Ajustes) y en la extensión (Esta página · Descargas · Ajustes, con «Descargar ya / Al grupo» siempre arriba). **Modo oscuro suave:** grafito y texto crema, sin negro ni blanco puros, acento apagado.
- Arreglos: nombres que pasaban de 260 caracteres en carpetas profundas; una carrera que podía dejar una descarga parada al pulsar «Descargar grupo» mientras se leía su título.

## Qué hace

- **Qué descargar, combinable:** Video, Audio (MP3, M4A, FLAC, OGG, OPUS, WAV o pista original), Subtítulos (con idiomas, p. ej. `es,en`) y Portada; más calidad máxima.
- **Botón sobre los videos y las miniaturas** («＋ Descargar», «♪» solo audio, «✂» recortar) y clic derecho: se descarga ya o va al grupo, según lo elegido.
- **Grupos** con nombre: junta enlaces y descárgalos de una vez, en su carpeta.
- **Recortar** uno o varios trozos de un video (corte rápido sin convertir, o exacto al segundo).
- **Modo edición** (MP4 H.264 + AAC) para cualquier programa de edición.
- **Cola en vivo** con progreso, velocidad y tiempo restante, cancelar, reintentar, recuperar tareas tras apagar, y errores explicados (qué pasó y qué hacer).
- **Organización** automática por tipo y por contenido, detección de duplicados, reglas por sitio (p. ej. «en youtube.com solo audio»).
- **Actualizaciones** del gestor, la extensión y yt-dlp, verificadas con SHA-256.
- **DRM:** solo *detecta y explica* (compatible / parcial / protegido / desconocido). No elude ninguna protección.
- **Vinculación segura:** el gestor solo obedece a la página que él mismo sirve y a extensiones vinculadas con un código.

## Instalar (Windows 10/11, usuarios)

1. Descarga **`GestorDescargas-<versión>-instalador.exe`** desde [Releases](https://github.com/Rfalso014/Desking-/releases/latest) (sección *Assets*).
2. Ejecútalo (si sale «Windows protegió su PC»: *Más información → Ejecutar de todas formas*). No pide administrador: se instala en `%LOCALAPPDATA%\Programs\GestorDescargas` y crea accesos directos. Opcional: «Encender el gestor con Windows». Al terminar enciende el gestor y abre su página.
3. Conecta la extensión (abajo). La carpeta `extension` está en el menú Inicio → *Gestor de Descargas* → «Carpeta de la extensión del navegador».

También hay una versión **portátil** (`…-portable.zip`): descomprímela y abre `GestorDescargas.exe`.
Desinstalar: *Configuración de Windows → Aplicaciones*; quita también el inicio con Windows.

## Instalar y ejecutar (Windows, desarrollo)

Requisitos: Python 3.11+ (probado con 3.13), Chrome o Edge.

```powershell
git clone https://github.com/Rfalso014/Desking-.git
cd Desking-
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**FFmpeg** (necesario para unir, convertir y recortar; para recortar rápido hace falta FFmpeg 8 o posterior): descarga una build para Windows (por ejemplo la de [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)), verifica su SHA256 y coloca `ffmpeg.exe` y `ffprobe.exe` en `tools\ffmpeg\` (o ponlos en el PATH).
**Deno** (opcional, mejora YouTube): `pip install deno` ya lo trae en el entorno virtual.

```powershell
python scripts\entrada_app.py              # panel de control (Encender / Apagar / Reiniciar / Abrir la página)
python scripts\entrada_app.py --abrir      # o directamente: enciende el servidor y abre http://127.0.0.1:7878
```

## Conectar la extensión (3 pasos)

1. **Cargar la extensión:** en `chrome://extensions` activa «Modo de desarrollador» → «Cargar descomprimida» → elige la carpeta `extension`. Su ID es fijo (`hdfnobaminegfbnoidambnkhgjmdldfb`) y es la única extensión a la que el gestor responde.
2. **Obtener el código:** en la página del gestor, **Ajustes → Extensión del navegador**, aparece un código como `K7M2-9QXA` (dura 10 minutos y sirve una sola vez).
3. **Vincular:** pulsa el ícono de la extensión (se abre la **barra lateral**) y escribe el código. Puedes desvincularla desde la página.

Si fijas el ícono (🧩 → 📌), tendrás la barra lateral a un clic.

## Usar

| Quiero… | Hago… |
|---|---|
| Descargar un enlace | Pégalo arriba en **Descargas** (página) y pulsa **Descargar** |
| Descargar un video de una web | Cursor sobre el video **o su miniatura** → **＋ Descargar** (o clic derecho → «Descargar con Gestor de Descargas») |
| Juntar varios y bajarlos después | Elige **Al grupo** (arriba en la extensión o al añadir en la página) y luego **Descargar grupo** |
| Que no cree una carpeta por video | Apaga **«En su propia carpeta»** |
| Bajar de un sitio que pide iniciar sesión | Inicia sesión en el navegador y añádelo **desde la extensión** |
| Un sitio cuyo video no se encuentra | Pon el video a reproducir unos segundos y añádelo desde la extensión (manda los enlaces directos) |
| Descargar solo unos minutos | **Recortar** (página o extensión), o en YouTube **✂** sobre el video |
| Usar el video en Premiere, DaVinci, CapCut… | Marca **Para edición** en la extensión |
| Encender, apagar o reiniciar | Abre **GestorDescargas.exe** (o la página → Ajustes → Servidor) |
| Cambiar la carpeta de descargas | Página → **Ajustes → Dónde se guarda → Cambiar…** |
| Actualizar todo | Página → Ajustes → **Actualizaciones** (o en la extensión) |

Sin interfaz: `python scripts\consultar.py "https://…"` muestra lo que ofrece un enlace sin descargar nada.

## Probar

```powershell
pytest                                       # ~315 pruebas, sin depender de internet
node --test extension/test/util.test.mjs     # pruebas de la extensión
```

Las pruebas descargan de verdad contra un servidor local con medios generados por FFmpeg; si FFmpeg no está, esas pruebas se omiten. Las del servidor web levantan el servidor HTTP real en un puerto libre.

## Estructura

| Carpeta | Contenido |
|---|---|
| `src/gestor/` | núcleo: validación, extractor, descargador, organizador, cola, reglas, DRM, base de datos, vinculación, API |
| `src/gestor/web/` | servidor HTTP local (`servidor.py`) y la página (`estatico/`: HTML, CSS y JavaScript sin paso de compilación) |
| `src/gestor/control.py` | encender / apagar / reiniciar el servidor y el panel de control (tkinter) |
| `src/gestor/nativo/` | carpeta de datos, encender con Windows y limpieza de la versión de escritorio 1.x |
| `extension/` | extensión del navegador (JavaScript sin paso de compilación) |
| `scripts/` | punto de entrada, empaquetar, publicar, actualizar yt-dlp, generar íconos/clave de la extensión |
| `docs/REGISTRO.md` | decisiones, versiones verificadas, estado y límites conocidos |
| `docs/LEEME_INSTALACION.txt` | guía para la versión empaquetada |

## Empaquetar un ejecutable

```powershell
.\scripts\empaquetar.ps1      # PyInstaller + FFmpeg + Deno → dist\GestorDescargas, .zip portátil e instalador
```

Genera en `dist\`:
- `GestorDescargas-<versión>-instalador.exe` — instalador por usuario hecho con [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`instalador\GestorDescargas.iss`). El script busca `ISCC.exe` en las rutas habituales o en la variable `ISCC`; si no lo encuentra, solo avisa.
- `GestorDescargas-<versión>-portable.zip` — la misma carpeta comprimida.

Para publicarlo en GitHub Releases (después de `git push`): `.\scripts\publicar_release.ps1`.

La versión sale de `src/gestor/__init__.py` (y debe coincidir con `pyproject.toml` y `extension/manifest.json`; una prueba lo comprueba).
Opciones del ejecutable: `--encender`, `--apagar`, `--reiniciar`, `--abrir`, `--estado`, `--servidor` (es el servidor; lo usa el inicio con Windows), `--limpiar-sistema`, `--version`. Puerto: variable `GESTOR_PUERTO` (por defecto 7878).

## Seguridad

- El servidor solo escucha en `127.0.0.1`: nadie de tu red puede entrar.
- Cualquier web abierta en tu navegador podría intentar hablar con `127.0.0.1`; por eso: la cabecera `Host` debe ser `127.0.0.1`/`localhost` (contra *DNS rebinding*), un `POST` con `Origin` solo se acepta desde la propia página o nuestra extensión (contra CSRF), y toda acción exige el token local de la página (cambia en cada encendido) o el de una extensión vinculada. La página lleva una CSP estricta.
- Lo delicado (código de vinculación, apagar, reiniciar, carpeta de descargas) solo se puede pedir desde la página; la extensión solo puede cambiar lo que se elige al añadir.
- La sesión del sitio que manda la extensión vive **solo en memoria** para esa descarga (el `cookies.txt` temporal se borra al terminar); nunca se guarda en la base de datos.
- URL: solo http/https, sin credenciales, sin direcciones locales ni privadas (también tras resolver DNS).
- Actualizaciones: solo por https desde PyPI y los releases de GitHub, comprobadas con SHA-256.
- Rutas confinadas a la carpeta de descargas; nombres saneados; temporales en carpeta propia por tarea.

## Límites conocidos

- Probado en Windows con Chrome. **Firefox** y otros sistemas no están soportados todavía.
- Los sitios cambian: yt-dlp hay que actualizarlo con frecuencia (botón **Actualizar**).
- La extensión necesita permiso para leer los sitios (para tu sesión y los enlaces directos de video); al actualizar desde la 1.x Chrome lo pide.
- Los enlaces directos solo aparecen si el video se reprodujo en la pestaña; los que caducan pronto (firmados) pueden fallar si se descargan mucho después.
- Convertir 4K a 60 fps (corte exacto o modo edición) va más o menos a la velocidad del propio video en gráficas integradas.
- Recortar no funciona en directos que siguen emitiéndose ni en contenido protegido.
- Sin firma de código: Windows SmartScreen o el antivirus pueden advertir sobre los `.exe`.

Más detalle en [`docs/REGISTRO.md`](docs/REGISTRO.md).

## Aviso legal

Descarga solo contenido que tengas derecho a guardar. Respeta los términos de uso de cada sitio y las leyes de derechos de autor de tu país. Esta herramienta no elude DRM ni otras protecciones.
