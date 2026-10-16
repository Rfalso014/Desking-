# Registro del proyecto

## Decisiones tomadas
- UI: Python + PySide6 (un solo lenguaje para núcleo y UI). Núcleo sin UI, probado con pytest.
- Solo Windows; Chrome/Edge primero (Firefox después). Uso personal. Repo propio.
- Native Messaging: host corto por stdio + IPC local (tubería con nombre + clave HMAC) hacia la app.
- yt-dlp como librería; FFmpeg y gallery-dl siempre como procesos con lista de argumentos (nunca shell).
- **Cambio respecto al plan inicial:** la extensión está en JavaScript (módulos ES) en vez de TypeScript, para no
  añadir un paso de compilación. Se prueba con `node --test`. Migrar a TypeScript es posible más adelante.
- Cada tarea descarga en una carpeta temporal propia (`<raíz>/.tmp/<id>`); al terminar, el organizador mueve a destino.
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
- Sin instalador (Inno Setup/MSI): se distribuye un zip con `--instalar-host`.

## Trampa encontrada (2026-10-16)
- El Python de la Microsoft Store redirige las escrituras en %LOCALAPPDATA% a una carpeta oculta (LocalCache). Chrome no veia el manifiesto del host. Los datos de la app ahora viven en %USERPROFILE%\.gestor-descargas.
- Verificado por el usuario: la extension en Chrome muestra Conectado.

## Boton flotante sobre videos (2026-10-16)
- content.js: boton al pasar el cursor sobre un <video> (>=200x110) con 'Descargar' y 'solo audio'. Verificado en un navegador con una pagina local y chrome.runtime simulado (aparece aunque haya una capa encima, usa el enlace que envuelve al video, no aparece en videos pequenos, se oculta al salir).
- Coste de privacidad: la extension ahora corre en todas las paginas http/https (aviso de Chrome 'leer y cambiar datos en todos los sitios'). El script solo lee el DOM localmente y envia algo unicamente tras un clic de confianza (isTrusted).
- El menu contextual quedo con un solo elemento para que no sea submenu.
