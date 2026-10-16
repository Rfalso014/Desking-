# Gestor de Descargas

App de escritorio (Python + PySide6) y extensión de navegador (Chrome/Edge, Manifest V3) para descargar y organizar video, audio, subtítulos, portadas e imágenes. La extensión no descarga nada: delega en la app mediante Native Messaging.

```
Extensión (MV3) <-stdio-> Host nativo <-pipe con clave-> App (PySide6 + cola + SQLite + yt-dlp/FFmpeg)
```

## Preparar el entorno (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest                      # 190+ pruebas, sin depender de internet
```

FFmpeg: colócalo en `tools\ffmpeg\` (`ffmpeg.exe` y `ffprobe.exe`) o ponlo en el PATH.

## Usar

```powershell
python -m gestor.app                       # abre la aplicación
python scripts\instalar_host.py            # registra la conexión con Chrome y Edge (usuario actual)
python scripts\consultar.py "https://…"    # ver qué ofrece un enlace, sin descargar
```

Luego, en `chrome://extensions` activa «Modo desarrollador» → «Cargar descomprimida» → carpeta `extension`.
Clic derecho en un enlace/video → «Añadir a la cola de descargas».

## Estructura

| Carpeta | Contenido |
|---|---|
| `src/gestor/` | núcleo: validación, extractor, descargador, organizador, cola, reglas, DRM, db, IPC |
| `src/gestor/nativo/` | host de Native Messaging e instalador (registro de Windows) |
| `src/gestor/ui/` | interfaz PySide6 |
| `extension/` | extensión del navegador (JavaScript sin paso de compilación) |
| `scripts/` | utilidades: instalar host, empaquetar, actualizar yt-dlp, generar íconos/clave |
| `docs/REGISTRO.md` | decisiones, versiones, estado y límites conocidos |

## Empaquetar

```powershell
.\scripts\empaquetar.ps1      # genera dist\GestorDescargas (+ .zip) con PyInstaller
```

Ver `docs/REGISTRO.md` para el estado completo.
