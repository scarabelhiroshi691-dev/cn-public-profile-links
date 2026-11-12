param([string]$Url = 'https://www.bilibili.com', [string]$Python)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Setup.ps1') -Action browser -Url $Url -Python $Python
exit $LASTEXITCODE
