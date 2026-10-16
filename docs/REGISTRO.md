# Registro del proyecto

## Decisiones tomadas
- UI: Python + PySide6 (un solo lenguaje para núcleo y UI).
- Plataforma inicial: solo Windows. Navegador inicial: Chrome/Edge (Firefox después).
- Uso personal. Repo propio, separado del Portal de Formularios.
- Núcleo sin UI (`src/gestor`), probado con pytest.
- Native Messaging: host corto (stdio) + IPC local hacia la app.
- yt-dlp como librería; FFmpeg siempre con lista de argumentos (nunca shell).

## Versiones verificadas (2026-10-16, fuentes oficiales)
| Pieza | Versión | Nota |
|---|---|---|
| Python | 3.13.14 (instalado) | PySide6 exige >=3.10 |
| PySide6 | 6.12.0 | |
| yt-dlp | 2026.08.19 | requiere runtime JS externo para YouTube (Deno >= 2.3.0 recomendado) |
| FFmpeg | 9.0.2 / 8.1.3 | builds Windows: gyan.dev o BtbN. Se instala en Fase 4 |
| PyInstaller | 6.22.3 | Fase 14 |

## Hecho
- Fase 1: análisis y arquitectura.
- Fase 2: estructura inicial y entorno.
- Fase 3 (código): `modelos.py`, `validacion.py` (anti-SSRF), `extractor.py`
  (yt-dlp sin descargar, errores traducidos), `scripts/consultar.py`. 43 pruebas offline OK.
  Probado a mano con YouTube real (24 formatos listados, sin Deno instalado).

## Notas de Fase 3
- Formatos 233/234 (HLS) salen como "desconocido": yt-dlp no informa codecs. Revisar en Fase 4.
- La validación de URL no resuelve DNS (riesgo de DNS rebinding): se cubre en Fase 13.

## Pendiente / conocido
- Instalar Deno (Fase 3, solo si probamos YouTube) y FFmpeg (Fase 4).
- Chrome: manifiesto del host con `allowed_origins`, clave de registro en HKCU.
