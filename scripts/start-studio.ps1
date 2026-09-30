[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$Lean
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop is required. Install/start Docker Desktop and retry."
    }
    $compose = @("compose")
    if ($Lean) { $compose += "--profile", "lean" }
    $compose += "up", "-d", "--wait"
    if ($Build) { $compose += "--build" }
    Write-Host "Starting Alpha Studio services on localhost..."
    & docker @compose
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Alpha Studio service status:" -ForegroundColor Yellow
        & docker compose ps
        throw "Docker Compose failed to start a healthy Alpha Studio stack."
    }
    Write-Host "Alpha Studio: http://127.0.0.1:5173"
    Write-Host "API health:   http://127.0.0.1:8000/api/health"
} finally {
    Pop-Location
}
