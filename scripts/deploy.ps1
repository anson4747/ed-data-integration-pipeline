<#
.SYNOPSIS
    Deploy database changes to an environment (dev, ci, test or prod).

.DESCRIPTION
    1. Creates the databases if they do not exist (idempotent).
    2. Applies pending versioned migrations to the source and warehouse databases.
    3. Stops on schema drift: an already applied script that was edited since.

    Run with -DryRun first in test and prod to see exactly what will change.

.EXAMPLE
    ./scripts/deploy.ps1 -Environment dev
    ./scripts/deploy.ps1 -Environment prod -DryRun
#>
[CmdletBinding()]
param(
    [ValidateSet('dev', 'ci', 'test', 'prod')]
    [string] $Environment = 'dev',

    [ValidateSet('all', 'source_emr', 'warehouse')]
    [string] $Target = 'all',

    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $python = if ($env:EDP_PYTHON) { $env:EDP_PYTHON } else { 'python' }

    function Write-Step([string] $message) {
        Write-Host ("[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $message)
    }

    Write-Step "Deploying to '$Environment' (target: $Target$(if ($DryRun) { ', dry run' }))"

    $arguments = @('-m', 'edpipe.migrate', '--env', $Environment, '--target', $Target)
    if (-not $DryRun) { $arguments += '--bootstrap' }
    if ($DryRun) { $arguments += '--dry-run' }

    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Migration failed with exit code $LASTEXITCODE. Nothing after the failing script was applied."
    }

    Write-Step 'Deployment finished.'
}
finally {
    Pop-Location
}
