param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$LzoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$LzoVenv = Join-Path $LzoRoot '.venv-local-server'
& $Python -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 and rerun with -Python path/to/python.exe' }
if (-not (Test-Path -LiteralPath (Join-Path $LzoVenv 'Scripts/python.exe'))) {
    & $Python -m venv $LzoVenv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
}
& (Join-Path $LzoVenv 'Scripts/python.exe') -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements.lock')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
Write-Output 'Python runtime ready. Configure private.env/config.json and the independent native databases before init.'
