[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "The project .venv is missing. Run setup.cmd first."
}

Push-Location $projectRoot
try {
    Write-Host "Checking the Python application..."
    $pytestTemp = ".test-tmp-verify-$PID"
    & $python -m pytest -q -p no:cacheprovider --basetemp $pytestTemp
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed." }
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Python lint checks failed." }
    & $python -m mypy src
    if ($LASTEXITCODE -ne 0) { throw "Python type checks failed." }

    Write-Host "Checking the web application..."
    $npmCache = Join-Path $projectRoot ".npm-cache"
    Push-Location (Join-Path $projectRoot "web")
    try {
        & npm.cmd ci --cache $npmCache
        if ($LASTEXITCODE -ne 0) { throw "Web dependency installation failed." }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw "Web build failed." }
        & npm.cmd test -- --run
        if ($LASTEXITCODE -ne 0) { throw "Web tests failed." }
    } finally {
        Pop-Location
    }

    Write-Host "All pre-push checks passed."
} finally {
    Pop-Location
}
