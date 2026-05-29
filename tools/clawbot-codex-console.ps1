param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ConsoleArgs
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$consoleScript = Join-Path $scriptDir "clawbot_codex_console.py"
$python = (Get-Command python -ErrorAction SilentlyContinue).Source

if (-not $python) {
    Write-Error "Python was not found in PATH."
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
& $python -X utf8 $consoleScript @ConsoleArgs
exit $LASTEXITCODE
