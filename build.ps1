# Empaqueta GranizApp como programa de Windows (carpeta con GranizApp.exe + un .zip).
#
# Uso (PowerShell, desde la carpeta del proyecto):
#   python -m venv C:\venvs\granizapp
#   C:\venvs\granizapp\Scripts\pip install -r requirements.txt
#   .\build.ps1 -Python C:\venvs\granizapp\Scripts\python.exe
#
# Se compila en una carpeta temporal de ruta corta porque Windows limita las rutas a
# 260 caracteres y Qt trae archivos con rutas largas.
# (Mensajes sin tildes a proposito: PowerShell 5 lee los .ps1 sin BOM como ANSI.)
param(
    [string]$Python = "python",
    [string]$Work = "$env:TEMP\granizapp_build"
)
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Version = (& $Python -c "import sys; sys.path.insert(0, r'$Root'); import granizapp; print(granizapp.__version__)").Trim()

if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force "$Work\src" | Out-Null
Copy-Item -Recurse "$Root\granizapp" "$Work\src\granizapp"
Copy-Item "$Root\run.py" "$Work\src\run.py"
Get-ChildItem -Recurse -Directory "$Work\src" -Filter "__pycache__" | Remove-Item -Recurse -Force
$Assets = "$Work\src\granizapp\assets"

Push-Location "$Work\src"
# PyInstaller escribe su bitacora por stderr: en PowerShell 5 eso no debe tratarse como error
$ErrorActionPreference = "Continue"
& $Python -m PyInstaller run.py `
    --name GranizApp `
    --windowed `
    --noconfirm `
    --clean `
    --icon "$Assets\icon.ico" `
    --add-data "$Assets;granizapp\assets" `
    --collect-submodules granizapp `
    --hidden-import psycopg_binary `
    --hidden-import sqlalchemy.dialects.sqlite `
    --hidden-import sqlalchemy.dialects.postgresql.psycopg `
    --exclude-module tkinter `
    --exclude-module pytest `
    --distpath "$Work\dist" `
    --workpath "$Work\build" `
    --specpath "$Work" 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match "ERROR|completed successfully" }
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
Pop-Location
if ($code -ne 0) { throw "PyInstaller fallo (codigo $code)" }

$Zip = "$Root\dist\GranizApp-$Version-windows.zip"
New-Item -ItemType Directory -Force "$Root\dist" | Out-Null
if (Test-Path $Zip) { Remove-Item $Zip }
Compress-Archive -Path "$Work\dist\GranizApp" -DestinationPath $Zip
Write-Host "Listo: $Zip"
Write-Host "Programa: $Work\dist\GranizApp\GranizApp.exe (copie la carpeta GranizApp donde quiera)"
