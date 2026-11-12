param(
    [ValidateSet('install','doctor','browser','config')]
    [string]$Action = 'install',
    [string]$Python,
    [string]$RuntimeDir,
    [string]$Url = 'https://www.bilibili.com',
    [switch]$Browser
)
$ErrorActionPreference = 'Stop'
$taskPython = $Python
if (-not $taskPython) {
    $candidatePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $taskPython = if (Test-Path -LiteralPath $candidatePython) { $candidatePython } else { 'python' }
}
$taskArguments = @('-X', 'utf8', '-B', (Join-Path $PSScriptRoot 'scripts/setup.py'), $Action)
if ($Action -eq 'install' -and $RuntimeDir) { $taskArguments += @('--runtime-dir', $RuntimeDir) }
if ($Action -eq 'browser') { $taskArguments += @('--url', $Url) }
if ($Action -eq 'doctor' -and $Browser) { $taskArguments += '--browser' }
& $taskPython @taskArguments
exit $LASTEXITCODE
