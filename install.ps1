# Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-fA-F0-9]{64}$')][string]$Sha256,
    [string]$Distribution = 'Ubuntu'
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL2 is required. Follow https://learn.microsoft.com/windows/wsl/install and run this installer again. Windows features are not changed automatically.'
}
if ($Distribution -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') { throw 'Use an explicit distribution name from wsl --list --verbose.' }
$inventory = ((& wsl.exe --list --verbose) -join "`n") -replace "`0", ''
if ($LASTEXITCODE -ne 0 -or $inventory -notmatch ('(?m)^\s*\*?\s*' + [regex]::Escape($Distribution) + '\s+.+\s+2\s*$')) {
    throw "Select an installed WSL2 distribution with -Distribution. Run wsl --list --verbose. Requested: $Distribution"
}
$archivePath = (Resolve-Path -LiteralPath $Archive).Path
if ((Get-Item -LiteralPath $archivePath).PSIsContainer) { throw 'Archive must be a regular package file.' }
if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ine $Sha256) { throw 'Package SHA-256 mismatch; nothing was installed.' }
$scriptPath = Join-Path $PSScriptRoot 'install.sh'
function Convert-MediaWslPath([string]$Path) {
    $converted = (& wsl.exe --distribution $Distribution --exec wslpath -a $Path) -join "`n"
    if ($LASTEXITCODE -ne 0 -or $converted -notmatch '^/' -or $converted -match "[`r`n]") { throw 'Could not translate the package path into WSL.' }
    return $converted
}
$linuxArchive = Convert-MediaWslPath $archivePath
$linuxScript = Convert-MediaWslPath $scriptPath
& wsl.exe --distribution $Distribution --exec sh $linuxScript --archive $linuxArchive --sha256 $Sha256
if ($LASTEXITCODE -ne 0) { throw 'WSL installation did not finish. Follow the reported prerequisite; do not switch HOME or clear collection state.' }
Write-Output "CLI installed in WSL2 distribution $Distribution. Continue AGENT_INSTALL.md inside this same distribution. The browser must run in its Linux desktop/WSLg session; Windows Chrome is not attached."
