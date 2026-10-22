<#
.SYNOPSIS
    Run the whole pipeline, in order, with one command.

.DESCRIPTION
    Steps: replicate the EMR, ingest AIHW, build the dimension and facts, run the data quality rules,
    then print the health report.

    Fails fast: the first step that fails stops the run, the health report is printed so the cause is
    visible, and the script exits with a non-zero code so a scheduler (Task Scheduler, a CI job) sees it.
    Every step also records itself in etl.pipeline_run, etl.step_run and etl.alert, so a failure is visible
    in the database as well as in the console. Re-running is safe: each step is idempotent.

    A copy of everything printed is written to logs/run-<timestamp>.log.

.EXAMPLE
    ./scripts/run-pipeline.ps1 -Environment dev
    ./scripts/run-pipeline.ps1 -Environment dev -ForceAihw
    ./scripts/run-pipeline.ps1 -Environment ci -AihwFixture tests/fixtures/aihw/myhospitals-sample.json.gz
#>
[CmdletBinding()]
param(
    [ValidateSet('dev', 'ci', 'test', 'prod')]
    [string] $Environment = 'dev',

    # Reload AIHW data even if the published release is unchanged.
    [switch] $ForceAihw,

    # Skip the AIHW step (for example when the API is unreachable and the rest still needs to run).
    [switch] $SkipAihw,

    # Replay a recorded API sample instead of calling the live API (offline runs, CI).
    [string] $AihwFixture
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $python = if ($env:EDP_PYTHON) { $env:EDP_PYTHON } else { 'python' }
    New-Item -ItemType Directory -Force logs | Out-Null
    $logFile = Join-Path 'logs' ("run-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
    $trigger = 'run-pipeline.ps1'

    function Write-Step([string] $message) {
        $line = "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $message
        Write-Host $line
        Add-Content -Path $logFile -Value $line -Encoding UTF8
    }

    # Runs python, copies every output line to the console and the log, and returns only the exit code.
    # Error action is relaxed inside: Windows PowerShell 5.1 turns native stderr text into a terminating
    # error under 'Stop', which would hide the real exit code.
    function Invoke-Python([string[]] $arguments) {
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $python @arguments 2>&1 | ForEach-Object {
                $text = "$_"
                Write-Host $text
                Add-Content -Path $logFile -Value $text -Encoding UTF8
            }
            return $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previous
        }
    }

    $steps = @(
        @{ Name = 'Replicate EMR changes'; Args = @('-m', 'edpipe.replicate', '--env', $Environment, '--triggered-by', $trigger) }
    )
    if (-not $SkipAihw) {
        $aihw = @('-m', 'edpipe.aihw_ingest', '--env', $Environment, '--triggered-by', $trigger)
        if ($ForceAihw) { $aihw += '--force' }
        if ($AihwFixture) { $aihw += @('--from-fixture', $AihwFixture) }
        $steps += @{ Name = 'Ingest AIHW MyHospitals'; Args = $aihw }
    }
    $steps += @{ Name = 'Build dimension and facts'; Args = @('-m', 'edpipe.dw_build', '--env', $Environment, '--triggered-by', $trigger) }
    $steps += @{ Name = 'Run data quality rules'; Args = @('-m', 'edpipe.dq', '--env', $Environment, '--triggered-by', $trigger) }

    Write-Step "Pipeline run starting (environment: $Environment). Log: $logFile"
    $started = Get-Date

    foreach ($step in $steps) {
        Write-Step ("START  " + $step.Name)
        $code = Invoke-Python $step.Args
        if ($code -ne 0) {
            Write-Step ("FAILED {0} (exit code {1}). Later steps were not run." -f $step.Name, $code)
            Write-Step 'Health report follows. See docs/runbook.md for what to do next.'
            Invoke-Python @('-m', 'edpipe.health', '--env', $Environment) | Out-Null
            exit 1
        }
        Write-Step ("DONE   " + $step.Name)
    }

    Write-Step 'Health report'
    Invoke-Python @('-m', 'edpipe.health', '--env', $Environment) | Out-Null
    Write-Step ("Pipeline run finished in {0:N0} seconds." -f ((Get-Date) - $started).TotalSeconds)
}
finally {
    Pop-Location
}
