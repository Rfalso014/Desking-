# Crea la versión instalable: dist\GestorDescargas (carpeta), un .zip portátil y, si Inno Setup 6 está
# instalado, el instalador dist\GestorDescargas-<versión>-instalador.exe.
# Uso (PowerShell, desde la raíz del proyecto):   .\scripts\empaquetar.ps1
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$py = Join-Path $raiz ".venv\Scripts\python.exe"

& $py -m pip install --quiet "pyinstaller==6.22.3"
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist) { Remove-Item dist -Recurse -Force }

# 0) Icono y ficha de versión de los .exe (build\recursos)
$version = (& $py scripts\preparar_recursos.py).Trim()
if ($LASTEXITCODE -ne 0) { throw "No se pudieron preparar los recursos" }
$recursos = Join-Path $raiz "build\recursos"

# 1) Aplicación de escritorio (carpeta con .exe; sin consola)
& $py -m PyInstaller --noconfirm --clean --windowed --name GestorDescargas `
    --icon "$recursos\icono.ico" --version-file "$recursos\version.txt" `
    --paths src --collect-all yt_dlp_ejs `
    --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQml --exclude-module PySide6.QtPdf `
    scripts\entrada_app.py
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de la aplicación" }

# 2) Host de Native Messaging (un solo .exe pequeño; con consola porque usa stdin/stdout)
& $py -m PyInstaller --noconfirm --clean --onefile --console --name GestorHost `
    --icon "$recursos\icono.ico" --version-file "$recursos\version.txt" `
    --paths src --exclude-module PySide6 --exclude-module yt_dlp --exclude-module PIL --exclude-module httpx `
    scripts\entrada_host.py
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación del host" }

$destino = Join-Path $raiz "dist\GestorDescargas"
Copy-Item "dist\GestorHost.exe" $destino
Remove-Item "dist\GestorHost.exe"

# 3) Quitar piezas de Qt que una app de Widgets no usa (~45 MB): render OpenGL por software,
#    teclado virtual (arrastra Qt Quick/QML), PDF y traducciones de Qt.
$qt = Join-Path $destino "_internal\PySide6"
foreach ($f in @("opengl32sw.dll", "Qt6Pdf.dll", "Qt6VirtualKeyboard.dll", "Qt6Quick.dll", "Qt6Qml.dll",
                 "Qt6QmlMeta.dll", "Qt6QmlModels.dll", "Qt6QmlWorkerScript.dll", "translations",
                 "plugins\platforminputcontexts", "plugins\imageformats\qpdf.dll")) {
    $ruta = Join-Path $qt $f
    if (Test-Path $ruta) { Remove-Item $ruta -Recurse -Force }
}

# 4) Archivos que acompañan al programa
Copy-Item "extension" (Join-Path $destino "extension") -Recurse
Remove-Item (Join-Path $destino "extension\test") -Recurse -Force
if (Test-Path "tools\ffmpeg") { Copy-Item "tools\ffmpeg" (Join-Path $destino "tools\ffmpeg") -Recurse }
if (Test-Path ".venv\Scripts\deno.exe") { New-Item -ItemType Directory -Force (Join-Path $destino "tools\deno") | Out-Null; Copy-Item ".venv\Scripts\deno.exe" (Join-Path $destino "tools\deno") }
Copy-Item "docs\LEEME_INSTALACION.txt" $destino

# 5) Comprobación rápida: el .exe (sin consola) arranca y termina bien con --version
$prueba = Start-Process (Join-Path $destino "GestorDescargas.exe") -ArgumentList "--version" -Wait -PassThru
if ($prueba.ExitCode -ne 0) { throw "GestorDescargas.exe --version terminó con código $($prueba.ExitCode)" }

# El antivirus suele bloquear un momento el .exe recién ejecutado: se reintenta la compresión.
for ($i = 1; $i -le 5; $i++) {
    try { Compress-Archive -Path $destino -DestinationPath "dist\GestorDescargas-$version-portable.zip" -Force; break }
    catch { if ($i -eq 5) { throw }; Start-Sleep -Seconds 5 }
}

# 6) Instalador (Inno Setup 6). Se busca en las rutas habituales o en la variable ISCC.
$iscc = @($env:ISCC, "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DVersion=$version" "instalador\GestorDescargas.iss"
    if ($LASTEXITCODE -ne 0) { throw "Falló la compilación del instalador" }
    Write-Host "Instalador: dist\GestorDescargas-$version-instalador.exe"
} else {
    Write-Warning "Inno Setup 6 no encontrado: no se creó el instalador (instálalo o define la variable ISCC)."
}
Write-Host "Listo: $destino"
