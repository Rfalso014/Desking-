# Registro del proyecto

## Decisiones tomadas
- UI: Python + PySide6 (un solo lenguaje para núcleo y UI). Núcleo sin UI, probado con pytest.
- Solo Windows; Chrome/Edge primero (Firefox después). Uso personal. Repo propio.
- Native Messaging: host corto por stdio + IPC local (tubería con nombre + clave HMAC) hacia la app.
- yt-dlp como librería; FFmpeg y gallery-dl siempre como procesos con lista de argumentos (nunca shell).
- **Cambio respecto al plan inicial:** la extensión está en JavaScript (módulos ES) en vez de TypeScript, para no
  añadir un paso de compilación. Se prueba con `node --test`. Migrar a TypeScript es posible más adelante.
- Cada tarea descarga en una carpeta temporal propia (`<raíz>/.tmp/<id>`); al terminar, el organizador mueve a destino.
- **Vinculación por código (2026-10-16):** la app muestra un código de 8 caracteres (10 min, un solo uso, bloqueo tras 5 fallos); la extensión lo escribe y recibe un token aleatorio de 256 bits que envía en cada mensaje. La app solo guarda su hash SHA-256 y puede revocarlo. Sin token válido solo responden `ping` y `emparejar`.
- **Quién hace qué:** la extensión solo obtiene datos (detecta recursos, pide análisis) y da órdenes (descargar, cancelar, reintentar, eliminar, abrir carpeta, limpiar). Toda descarga la ejecuta la aplicación. Los recursos enviados con «Enviar a la app» quedan en estado Detectado hasta que se pulsa Descargar.
- **Velocidad:** perfiles Normal/Rápida/Máxima = fragmentos simultáneos (1/8/16) + trozos HTTP de 10 MB (evita el estrangulamiento de YouTube) + 3 descargas a la vez; Deno (2.9.7, paquete `deno` de PyPI) como runtime JS para yt-dlp. No hay medición comparativa fiable: con un video de 19 s la diferencia es nula.
- La extensión NO puede elegir rutas absolutas: solo una `subcarpeta` relativa. Las rutas manuales se eligen en la app.
- El DRM solo se bloquea cuando está **confirmado** (todos los formatos con `has_drm`); un servicio "conocido" es solo indicio.

## Versiones verificadas (2026-10-16, fuentes oficiales)
| Pieza | Versión | Nota |
|---|---|---|
| Python | 3.13.14 | PySide6 exige >=3.10 |
| PySide6 | 6.12.0 | |
| yt-dlp | 2026.08.19 | para YouTube puede requerir runtime JS externo (Deno >= 2.3.0); no está instalado aquí |
| FFmpeg | 9.0.2 (gyan.dev, SHA256 verificado) | en `tools/ffmpeg` (ignorado por git) |
| PyInstaller | 6.22.3 | |
| httpx / Pillow / gallery-dl | 0.28.1 / 12.3.0 / 1.32.16 | |

## Estado por fase
| Fase | Estado | Evidencia |
|---|---|---|
| 1-2 Análisis, entorno | Hecha | |
| 3 Extractor yt-dlp | Hecha | pruebas + consulta real a YouTube (24 formatos) |
| 4 Video y audio | Hecha | descargas reales contra servidor local + FFmpeg (mp4, mp3, pista original) |
| 5 Subtítulos, portadas, imágenes | Hecha | subtítulo `.es.srt` y portada reales desde una página local; imágenes con HTTPX/Pillow/gallery-dl |
| 6 Organización | Hecha | modos tipo/contenido/manual, duplicados (omitir/reemplazar/renombrar, idénticos nunca se duplican) |
| 7 Cola | Hecha | estados, cancelar, reintentar, recuperar tras cierre |
| 8 SQLite, reglas | Hecha | historial con búsqueda, reglas con prioridad y explicación del origen de cada opción |
| 9 Interfaz | Hecha (probada offscreen) | **No revisada visualmente por una persona** |
| 10 Native Messaging | Hecha | host real como subproceso, tubería con clave, E2E con la app real |
| 11 Extensión | Escrita; **no probada en un navegador real** | `node --check`, 8 pruebas JS, manifiesto y ID verificados |
| 12 DRM | Hecha | compatible / parcial / protegido (confirmado vs indicio) / desconocido |
| 13 Seguridad | Parcial | ver abajo |
| 14 Empaquetado | Hecha y probada | exe + host + pipe funcionan; zip ≈ 142 MB |

## Seguridad aplicada
- URL: solo http/https, sin credenciales, sin IPs locales/privadas, y resolución DNS comprobada antes de analizar/descargar.
- Protocolo extensión↔app con lista blanca de acciones y campos; se valida en el host y otra vez en la app.
- IPC autenticado con clave aleatoria en `%LOCALAPPDATA%\GestorDescargas\ipc.key`.
- Host verifica el origen de la extensión (`allowed_origins`, sin comodines) y limita tamaños.
- Rutas: títulos saneados (nombres reservados de Windows, `..`), destino confinado a la raíz, limpieza solo dentro de `.tmp`.
- Imágenes: redirecciones revalidadas, límite de tamaño, verificación con Pillow.
- Extensión: permisos mínimos (sin `host_permissions`), texto de páginas insertado como texto plano.

## Límites conocidos / pendiente
- La extensión debe cargarse y probarse a mano en Chrome/Edge (no pude automatizarlo).
- DNS rebinding: la comprobación de DNS reduce el riesgo pero no lo elimina (hay una ventana entre comprobar y descargar).
- Sin soporte de cookies/login todavía (no se guarda ningún secreto). Los errores de autenticación se explican pero no se resuelven.
- Las URL guardadas en el historial pueden contener tokens firmados en la query.
- La versión empaquetada no incluye Deno ni gallery-dl.
- Formatos HLS sin códecs informados aparecen como «desconocido».
- Sin firma de código: Windows SmartScreen/antivirus pueden advertir sobre los .exe.
- Actualizaciones: manuales (`scripts/actualizar_ytdlp.py` en desarrollo; versión nueva del zip en la empaquetada).
- ~~Sin instalador~~: resuelto en 1.0.0 (Inno Setup, ver abajo).

## Trampa encontrada (2026-10-16)
- El Python de la Microsoft Store redirige las escrituras en %LOCALAPPDATA% a una carpeta oculta (LocalCache). Chrome no veia el manifiesto del host. Los datos de la app ahora viven en %USERPROFILE%\.gestor-descargas.
- Verificado por el usuario: la extension en Chrome muestra Conectado.

## Boton flotante sobre videos (2026-10-16)
- content.js: boton al pasar el cursor sobre un <video> (>=200x110) con 'Descargar' y 'solo audio'. Verificado en un navegador con una pagina local y chrome.runtime simulado (aparece aunque haya una capa encima, usa el enlace que envuelve al video, no aparece en videos pequenos, se oculta al salir).
- Coste de privacidad: la extension ahora corre en todas las paginas http/https (aviso de Chrome 'leer y cambiar datos en todos los sitios'). El script solo lee el DOM localmente y envia algo unicamente tras un clic de confianza (isTrusted).
- El menu contextual quedo con un solo elemento para que no sea submenu.

## Rediseño y extensión v2 (2026-10-16)
- Aplicación: barra lateral, tarjetas por descarga (miniatura, estado, progreso, velocidad, ETA, errores con causa/solución), filtros, tema claro/oscuro/automático, página «Extensión» con el código de vinculación, sugerencia al copiar un enlace.
- Extensión: pestañas Esta página / Cola / Ajustes, análisis con compatibilidad, recursos detectados con selección múltiple, cola con filtros y búsqueda, ajustes (botón flotante, valores por defecto, desvincular).
- Verificado: popup en un navegador con la API de Chrome simulada; ventana de la app con capturas reales (claro y oscuro). NO verificado: la extensión cargada en un Chrome real con YouTube.

## Versión 1.0.0: instalador y releases (2026-10-20)
- Instalador por usuario con Inno Setup 6 (`instalador/GestorDescargas.iss`): sin administrador, `%LOCALAPPDATA%\Programs\GestorDescargas`,
  registra el host al instalar (`--instalar-host`), tarea opcional de inicio con Windows (mismo valor de registro que la app),
  cierra la app antes de actualizar y al desinstalar ejecuta `--limpiar-sistema` (host + inicio con Windows). Los datos del usuario se conservan.
- Los .exe llevan icono y ficha de versión (`scripts/preparar_recursos.py`).
- Paquete más ligero: se quitan piezas de Qt que una app de Widgets no usa (OpenGL por software, Qt Quick/QML del teclado virtual, PDF, traducciones).
- «Buscar actualizaciones» (Configuración → Acerca de) consulta la API de GitHub Releases; solo informa y abre la página, nunca descarga ni instala solo.
  Si el repositorio es privado, la API responde 404 y la app muestra «no se pudo comprobar».
- Versión única en `gestor.__version__`, comprobada contra `pyproject.toml` y `extension/manifest.json` en las pruebas.

## Publicar el instalador (2026-10-21)
- Problema: quien entraba al repositorio solo veía el código (pedía Python, FFmpeg…) porque el instalador nunca se publicó
  (`dist/` no se sube a git y no había ningún release).
- `scripts/publicar_release.ps1` crea el release `v<versión>` sobre el commit actual y sube instalador y .zip portátil
  (notas en `docs/NOTAS_RELEASE.md`). El README empieza con el enlace de descarga y el paso de SmartScreen.
- El repositorio sigue privado: solo quien tenga acceso ve el release; «Buscar actualizaciones» sigue sin poder comprobar.

## Versión 2.0.0: de aplicación de escritorio a web local (2026-10-26)
- **Decisión:** la interfaz PySide6 y el puente de Native Messaging se sustituyen por un servidor HTTP local
  (`gestor/web/servidor.py`, biblioteca estándar, solo `127.0.0.1:7878`) que sirve la página (`web/estatico`, HTML/CSS/JS sin
  compilación, igual que la extensión) y la API. `api.Manejador` es el antiguo manejador del IPC, ampliado. La extensión
  habla por `fetch` con el servidor (sin host nativo). `GestorDescargas.exe` (= `gestor/control.py`) es un panel tkinter
  para encender/apagar/reiniciar; con `--servidor` ES el servidor. PySide6 deja de ser dependencia.
- No se usó la plantilla React + shadcn del generador de artefactos: la página la sirve el propio gestor y el
  proyecto evita a propósito los pasos de compilación.
- Seguridad del servidor: Host solo 127.0.0.1/localhost (DNS rebinding), Origin solo la propia página o el ID de nuestra
  extensión (CSRF), token local nuevo en cada encendido (va dentro de la página; `servidor.json` lo guarda para el
  panel), CSP estricta. Acciones solo de la página: vínculos, apagar, reiniciar, elegir carpeta. La extensión solo
  puede cambiar `carpeta_propia`, `carpeta_grupo`, `modo_anadir` y `grupo_activo`.
- **Fallos fuera de YouTube (diagnóstico con los errores reales de `gestor.db`):** SharePoint/Outlook pedían sesión,
  Vimeo exige iniciar sesión, otros daban 403. Arreglos: (1) la extensión manda las cookies del sitio con `anadir`
  (permiso `cookies`); el servidor las tiene solo en memoria y escribe un cookies.txt temporal que borra al terminar;
  (2) la extensión apunta con `webRequest` los enlaces directos (m3u8/mpd/mp4) que carga el reproductor y los manda
  como `opciones.medios`; (3) `curl_cffi` + `impersonate` (presentarse como Chrome). La cola prueba en orden: página,
  página como Chrome, cada enlace directo (Referer = la página), enlace directo como Chrome (`GestorCola._candidatos`).
  Verificado: página sin video + enlace m3u8 público → descargado y recortado con el título de la página.
- **Recortar lento:** FFmpeg pedía el archivo en una sola petición y YouTube la frena. Con `-request_size 10M`
  (FFmpeg 8+; aquí 9.0.2) se pide por partes. Medido con un video de 10 min, trozo de 30 s a 1080p: 25,4 s → 5,8 s.
  `FACTOR_TROZOS` baja de 20 a 5 (solo se baja entero si los trozos ocupan más de 1/5 del video).
- Grupos y carpetas: `opciones.grupo` (detectadas = esperando en el grupo), `Preferencias.grupos/grupo_activo/
  modo_anadir/carpeta_grupo/carpeta_propia`; `organizar(..., carpeta_propia=False)` deja el archivo suelto.
- Arreglos encontrados al probar: rutas de más de 260 caracteres en carpetas profundas (plantilla de nombre y
  organizador acortan el título según la ruta real expandida); carrera entre el hilo que lee el título de una tarea
  detectada y «Descargar grupo»/renombrar grupo (la tarea podía volver a «detectado» y quedarse parada): ahora con candado.
- Diseño: misma paleta en página, extensión, botón sobre los videos y panel. Oscuro: fondo #1e2124, superficies #262a2e,
  texto #dcdad5, acento #7fb8a8 (antes violeta #17132b con coral y texto casi blanco).
- Al encender, el servidor quita lo que registró la 1.x (claves NativeMessagingHosts, `nativo/`, `host.json`, `ipc.key`).
- **No verificado:** la extensión cargada en un Chrome real (webRequest, cookies, barra lateral): se probó el panel con
  la API de Chrome simulada y el servidor con las mismas peticiones que manda la extensión.
