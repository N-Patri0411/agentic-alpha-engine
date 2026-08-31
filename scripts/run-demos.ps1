[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "No local environment found. Run setup.cmd first."
}

Push-Location $projectRoot
try {
    Write-Host "`n=== Synthetic factor-backtest demo ==="
    & $python -m alpha_workbench backtest `
        --prices data/demo_prices.csv `
        --factors data/demo_factors.csv `
        --as-of 2024-01-05T21:00:00+00:00

    Write-Host "`n=== TSMC disruption scenario ==="
    & $python -m alpha_workbench scenario `
        --edges data/semiconductor_edges.json `
        --shock TSM `
        --severity 0.9 `
        --as-of 2024-01-15T00:00:00+00:00

    Write-Host "`n=== ASML equipment disruption scenario ==="
    & $python -m alpha_workbench scenario `
        --edges data/semiconductor_edges.json `
        --shock ASML `
        --severity 0.7 `
        --as-of 2024-01-15T00:00:00+00:00
} finally {
    Pop-Location
}
