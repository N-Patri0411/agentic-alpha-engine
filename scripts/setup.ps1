[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"

function Find-Python311 {
    $candidates = @(
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ Command = "python"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }
        try {
            $version = & $candidate.Command @($candidate.Arguments) --version 2>&1
            if ($LASTEXITCODE -eq 0 -and $version -match "Python 3\.1[1-9]") {
                return $candidate
            }
        } catch {
            continue
        }
    }

    throw "Python 3.11 or newer is required. Install Python from python.org, then rerun setup.cmd."
}

Push-Location $projectRoot
try {
    if (-not (Test-Path $venvPython)) {
        $python = Find-Python311
        Write-Host "Creating the local virtual environment..."
        & $python.Command @($python.Arguments) -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Virtual-environment creation failed."
        }
    }

    Write-Host "Installing project and development dependencies..."
    & $venvPython -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }

    Write-Host "Running verification..."
    & $venvPython -m pytest -p no:cacheprovider
    & $venvPython -m ruff check .
    & $venvPython -m mypy
    if ($LASTEXITCODE -ne 0) {
        throw "Verification failed. Resolve the reported errors before continuing."
    }

    Write-Host "Setup complete. Double-click run-demos.cmd to see the offline demos."
} finally {
    Pop-Location
}
