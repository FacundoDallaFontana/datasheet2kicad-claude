# Prepara el entorno: venv + kicad-footprint-generator (commit fijado) + dependencias.
# Uso:  powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$KfgRepo = "https://gitlab.com/kicad/libraries/kicad-footprint-generator.git"
$KfgCommit = "eaee2837c34188adbf652ce7e5b2374541108cd1"
$KfgDir = "vendor/kicad-footprint-generator"

if (-not (Test-Path $KfgDir)) {
    git -c core.longpaths=true clone $KfgRepo $KfgDir
}
git -C $KfgDir -c core.longpaths=true checkout -q $KfgCommit

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install ./$KfgDir -e . pytest

Write-Host "Listo. Abrir la GUI con:  .venv/Scripts/python -m dsgen"
