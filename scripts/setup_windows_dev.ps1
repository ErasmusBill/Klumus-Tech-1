param(
    [string]$PythonExe = "",
    [string]$VenvName = ".venv",
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Resolve-PythonExecutable {
    param([string]$RequestedPython)

    if ($RequestedPython) {
        return $RequestedPython
    }

    $uvPython = Join-Path $env:APPDATA "uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
    if (Test-Path $uvPython) {
        return $uvPython
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        return "python"
    }

    throw "No Python executable found. Install Python 3.12+ or pass -PythonExe <path-to-python.exe>."
}

$python = Resolve-PythonExecutable -RequestedPython $PythonExe
$pythonVersion = (& $python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if ($LASTEXITCODE -ne 0) {
    throw "Unable to execute Python with '$python'. Pass a valid interpreter via -PythonExe."
}

if ($pythonVersion -notin @("3.12", "3.13")) {
    throw "Unsupported Python version $pythonVersion. Use Python 3.12 or 3.13."
}

$venvPath = Join-Path $projectRoot $VenvName
if ($RecreateVenv -and (Test-Path $venvPath)) {
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}

if (-not (Test-Path $venvPath)) {
    & $python -m venv $VenvName
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment was not created successfully at '$venvPath'."
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

$envLocalPath = Join-Path $projectRoot ".env.local"
$envLocalExample = Join-Path $projectRoot ".env.local.example"
if ((-not (Test-Path $envLocalPath)) -and (Test-Path $envLocalExample)) {
    Copy-Item -LiteralPath $envLocalExample -Destination $envLocalPath
    Write-Host "Created .env.local from .env.local.example"
}

& $venvPython manage.py migrate --noinput
& $venvPython manage.py check

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run the app with:"
Write-Host "  .\scripts\run_windows_dev.ps1"
