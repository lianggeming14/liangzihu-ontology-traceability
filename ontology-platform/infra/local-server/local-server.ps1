[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)][string[]]$CommandArgs,
    [string]$Config = $env:LZO_LOCAL_CONFIG
)
$ErrorActionPreference = 'Stop'
$LzoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$LzoPython = Join-Path $LzoRoot '.venv-local-server/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $LzoPython)) { throw 'Run infra/local-server/setup.ps1 to prepare Python runtime.' }
if (-not $Config) { $Config = Join-Path $LzoRoot '.runtime/local-server/config.json' }
if (-not $CommandArgs) { $CommandArgs = @('status') }
& $LzoPython (Join-Path $LzoRoot 'scripts/run_local_server.py') --config $Config @CommandArgs
exit $LASTEXITCODE
