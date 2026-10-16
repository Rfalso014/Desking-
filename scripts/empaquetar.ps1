# Crea la versión instalable en dist\GestorDescargas (y un .zip).
# Uso (PowerShell, desde la raíz del proyecto):   .\scripts\empaquetar.ps1
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$py = Join-Path $raiz ".venv\Scripts\python.exe"

& $py -m pip install --quiet "pyinstaller==6.22.3"
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }

# 1) Aplicación de escritorio (carpeta con .exe; sin consola)
& $py -m PyInstaller --noconfirm --clean --windowed --name GestorDescargas `
    --paths src --collect-all yt_dlp_ejs `
    --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQuick `
    scripts\entrada_app.py
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de la aplicación" }

# 2) Host de Native Messaging (un solo .exe pequeño; con consola porque usa stdin/stdout)
& $py -m PyInstaller --noconfirm --clean --onefile --console --name GestorHost `
    --paths src --exclude-module PySide6 --exclude-module yt_dlp --exclude-module PIL --exclude-module httpx `
    scripts\entrada_host.py
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación del host" }

$destino = Join-Path $raiz "dist\GestorDescargas"
Copy-Item "dist\GestorHost.exe" $destino
Remove-Item "dist\GestorHost.exe"

# 3) Archivos que acompañan al programa
Copy-Item "extension" (Join-Path $destino "extension") -Recurse
Remove-Item (Join-Path $destino "extension\test") -Recurse -Force
if (Test-Path "tools\ffmpeg") { Copy-Item "tools\ffmpeg" (Join-Path $destino "tools\ffmpeg") -Recurse }
if (Test-Path ".venv\Scripts\deno.exe") { New-Item -ItemType Directory -Force (Join-Path $destino "tools\deno") | Out-Null; Copy-Item ".venv\Scripts\deno.exe" (Join-Path $destino "tools\deno") }
Copy-Item "docs\LEEME_INSTALACION.txt" $destino

Compress-Archive -Path $destino -DestinationPath "dist\GestorDescargas.zip" -Force
Write-Host "Listo: $destino"
