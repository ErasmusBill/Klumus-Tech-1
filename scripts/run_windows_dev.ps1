param(
    [int]$Port = 8000,
    [string]$VenvName = ".venv"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot "$VenvName\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at '$VenvName'. Run .\scripts\setup_windows_dev.ps1 first."
}

Set-Location $projectRoot
& $venvPython manage.py runserver "0.0.0.0:$Port"
