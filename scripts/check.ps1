<#
.SYNOPSIS
    Runs the quality checks from CONSTRAINTS.md.

.DESCRIPTION
    fast  - ruff, ruff format, mypy, import-linter, floor guard   (budget 10 s)
    task  - fast + pytest with the coverage gate                  (budget 90 s)
    full  - task + pip-audit                                      (no budget)
    Every check runs; the script exits 1 if any check fails or a budget is exceeded,
    2 if the environment cannot be prepared. The report is written to .reports/check.log.

    Tools run as `python -m <tool>` from the project venv: on machines with Windows Smart
    App Control the unsigned console-script .exe wrappers are blocked, python.exe is not.

.EXAMPLE
    .\scripts\check.ps1
    .\scripts\check.ps1 -Stage fast -Quiet
#>
[CmdletBinding()]
param(
    [ValidateSet('fast', 'task', 'full')]
    [string]$Stage = 'task',
    [string]$Base = 'origin/main',
    # Print only failures; used by the editor hook.
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$budgets = @{ fast = 10; task = 90; full = 0 }
$python = Join-Path $root '.venv\Scripts\python.exe'
$reportDir = Join-Path $root '.reports'
$report = Join-Path $reportDir 'check.log'
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

$checks = [System.Collections.Generic.List[object]]::new()
$checks.Add(@{ Name = 'ruff check';   Args = @('-m', 'ruff', 'check', '.') })
$checks.Add(@{ Name = 'ruff format';  Args = @('-m', 'ruff', 'format', '--check', '.') })
$checks.Add(@{ Name = 'mypy';         Args = @('-m', 'mypy') })
$checks.Add(@{ Name = 'import-linter'; Args = @('-c', 'import sys; from importlinter.cli import lint_imports_command; sys.exit(lint_imports_command())') })
$checks.Add(@{ Name = 'floor guard';  Args = @('scripts/floor_guard.py', '--base', $Base) })
if ($Stage -in @('task', 'full')) {
    # 85% floor, or the ratchet recorded in CONSTRAINTS.md minus 0.5 points if higher.
    $coverageGate = (& $python scripts/ratchet.py).Trim()
    $checks.Add(@{ Name = 'pytest';   Args = @('-m', 'pytest', '-q', '--cov', "--cov-fail-under=$coverageGate", '--cov-report=term-missing') })
}
if ($Stage -eq 'full') {
    # Audit exactly what uv.lock pins (with hashes); the project itself is not on PyPI.
    $requirements = Join-Path $reportDir 'requirements.txt'
    $checks.Add(@{
        Name = 'pip-audit'
        Before = { & uv export --frozen --no-emit-project --quiet -o $requirements }
        Args = @('-m', 'pip_audit', '-r', $requirements, '--strict', '--require-hashes',
                 '--disable-pip', '--progress-spinner', 'off')
    })
}

# Windows PowerShell wraps native stderr lines in ErrorRecords; keep only the text.
function ConvertTo-Text {
    process {
        if ($_ -is [System.Management.Automation.ErrorRecord]) {
            if ($_.TargetObject -is [string]) { $_.TargetObject } else { '' }
        } else { "$_" }
    }
}

$log = [System.Collections.Generic.List[string]]::new()
$log.Add("check.ps1 -Stage $Stage  $(Get-Date -Format s)")

$sync = & uv sync --locked --quiet 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "check: cannot prepare the environment (uv sync --locked failed)" -ForegroundColor Red
    $sync | ForEach-Object { Write-Host $_ }
    exit 2
}

$failed = [System.Collections.Generic.List[string]]::new()
$total = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($check in $checks) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    # Native stderr must not become a terminating error under ErrorActionPreference=Stop.
    $ErrorActionPreference = 'Continue'
    $output = @()
    $code = 0
    if ($check.Before) {
        $output = & $check.Before 2>&1 | ConvertTo-Text
        $code = $LASTEXITCODE
    }
    if ($code -eq 0) {
        $output += & $python @($check.Args) 2>&1 | ConvertTo-Text
        $code = $LASTEXITCODE
    }
    $ErrorActionPreference = 'Stop'
    $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 1)
    $ok = $code -eq 0
    if (-not $ok) { $failed.Add($check.Name) }

    $line = '{0,-14} {1,-4} {2,5}s' -f $check.Name, $(if ($ok) { 'ok' } else { 'FAIL' }), $seconds
    $log.Add($line)
    $log.AddRange([string[]]@($output))
    if (-not $Quiet -or -not $ok) {
        Write-Host $line -ForegroundColor $(if ($ok) { 'Green' } else { 'Red' })
        if (-not $ok -or $check.Name -eq 'pytest') { $output | ForEach-Object { Write-Host "    $_" } }
    }
}

$elapsed = [math]::Round($total.Elapsed.TotalSeconds, 1)
$budget = $budgets[$Stage]
if ($budget -gt 0 -and $elapsed -gt $budget) {
    $failed.Add("budget ($elapsed s > $budget s)")
}

$summary = if ($failed.Count -eq 0) { "check $Stage passed in $elapsed s" }
           else { "check $Stage FAILED in $elapsed s: $($failed -join ', ')" }
$log.Add($summary)
$log | Set-Content -Path $report -Encoding utf8
if ($failed.Count -eq 0) {
    if (-not $Quiet) { Write-Host $summary -ForegroundColor Green }
    exit 0
}
Write-Host $summary -ForegroundColor Red
exit 1
