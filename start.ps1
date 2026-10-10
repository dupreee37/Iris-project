$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$irisPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $irisPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
}
& $irisPython -m pip install -e '.[voice]' -c requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
if (-not (Test-Path -LiteralPath 'work/models/vosk-model-small-es-0.42/am/final.mdl')) {
    & $irisPython -m iris --download-model
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar el reconocimiento local.' }
}
Write-Host 'IRIS: demo por voz. Ctrl+C para terminar.'
& $irisPython -m iris --demo --monitor
