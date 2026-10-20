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
