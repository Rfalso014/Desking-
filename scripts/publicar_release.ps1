# Publica la versión actual en GitHub Releases para que se pueda descargar el instalador sin compilar nada:
# crea el release v<versión> (con su etiqueta) sobre el commit actual y le sube el instalador y el .zip portátil.
# Antes: .\scripts\empaquetar.ps1 y subir los commits (git push); el commit actual tiene que estar en GitHub.
# Uso (PowerShell, desde la raíz del proyecto):   .\scripts\publicar_release.ps1
# Credencial: la variable GITHUB_TOKEN o, si no existe, la misma que usa git (Administrador de credenciales).
# Si el release ya existe, reemplaza sus archivos (sirve para corregir una subida).
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz
$repo = "Rfalso014/Desking-"
$api = "https://api.github.com/repos/$repo"

$version = [regex]::Match((Get-Content "src\gestor\__init__.py" -Raw), '__version__\s*=\s*"([^"]+)"').Groups[1].Value
if (-not $version) { throw "No se encontro __version__ en src\gestor\__init__.py" }
$etiqueta = "v$version"
$archivos = @("dist\GestorDescargas-$version-instalador.exe", "dist\GestorDescargas-$version-portable.zip")
foreach ($a in $archivos) { if (-not (Test-Path $a)) { throw "Falta $a. Ejecuta antes .\scripts\empaquetar.ps1" } }

# El release apunta al commit actual: tiene que estar subido.
git fetch --quiet origin
$commit = (git rev-parse HEAD).Trim()
if (-not (git branch -r --contains $commit)) { throw "El commit $commit no esta en GitHub. Haz git push primero." }

$token = $env:GITHUB_TOKEN
if (-not $token) {
    $credencial = "protocol=https`nhost=github.com`n" | git credential fill
    $token = ($credencial | Where-Object { $_ -like "password=*" }) -replace "^password=", ""
}
if (-not $token) { throw "Sin credencial de GitHub: define GITHUB_TOKEN o inicia sesion con git." }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$cabeceras = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json"; "User-Agent" = "GestorDescargas-publicar" }

try {
    $release = Invoke-RestMethod "$api/releases/tags/$etiqueta" -Headers $cabeceras
    Write-Host "El release $etiqueta ya existe: se reemplazan sus archivos."
} catch {
    if ($_.Exception.Response.StatusCode.value__ -ne 404) { throw }
    $notas = Get-Content "docs\NOTAS_RELEASE.md" -Raw -Encoding UTF8
    $cuerpo = @{ tag_name = $etiqueta; target_commitish = $commit; name = "Gestor de Descargas $version"; body = $notas } | ConvertTo-Json
    $release = Invoke-RestMethod "$api/releases" -Method Post -Headers $cabeceras `
        -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($cuerpo))
    Write-Host "Release $etiqueta creado."
}

# Los archivos pesan >100 MB: se suben con curl.exe (incluido en Windows 10/11), que no corta las subidas largas.
foreach ($a in $archivos) {
    $nombre = Split-Path $a -Leaf
    foreach ($viejo in @($release.assets | Where-Object { $_.name -eq $nombre })) {
        Invoke-RestMethod "$api/releases/assets/$($viejo.id)" -Method Delete -Headers $cabeceras | Out-Null
    }
    Write-Host "Subiendo $nombre ..."
    curl.exe --fail --silent --show-error -o NUL -X POST `
        -H "Authorization: Bearer $token" -H "Accept: application/vnd.github+json" -H "Content-Type: application/octet-stream" `
        --upload-file $a "https://uploads.github.com/repos/$repo/releases/$($release.id)/assets?name=$nombre"
    if ($LASTEXITCODE -ne 0) { throw "Fallo la subida de $nombre" }
}
Write-Host "Listo: $($release.html_url)"
