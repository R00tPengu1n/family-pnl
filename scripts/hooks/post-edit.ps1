# Claude Code PostToolUse hook: runs the fast stage of CONSTRAINTS.md after every edit.
# Exit code 2 sends the failure report back to the agent; 0 stays silent.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$output = & (Join-Path $root 'scripts\check.ps1') -Stage fast -Quiet *>&1 | Out-String
if ($LASTEXITCODE -eq 0) { exit 0 }
[Console]::Error.WriteLine($output.Trim())
exit 2
