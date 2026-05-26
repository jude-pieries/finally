param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$ImageName = "finally"
$ContainerName = "finally-app"
$VolumeName = "finally-data"
$Port = 8000

# Change to project root
Set-Location (Split-Path $PSScriptRoot)

# Build if needed
$imageExists = docker image inspect $ImageName 2>$null
if ($Build -or -not $imageExists) {
    Write-Host "Building FinAlly Docker image..."
    docker build -t $ImageName .
}

# Stop existing container
$running = docker ps -q -f "name=$ContainerName"
if ($running) {
    docker stop $ContainerName
    docker rm $ContainerName
} else {
    $stopped = docker ps -aq -f "name=$ContainerName"
    if ($stopped) { docker rm $ContainerName }
}

# Build env args
$envArgs = @()
if (Test-Path ".env") {
    $envArgs = @("--env-file", ".env")
} else {
    Write-Warning ".env not found. Copy .env.example to .env and set your API keys."
    Write-Host "Continuing without .env (market data simulator will be used)..."
}

# Run
docker run -d `
    --name $ContainerName `
    -v "${VolumeName}:/app/db" `
    -p "${Port}:8000" `
    @envArgs `
    $ImageName

Write-Host ""
Write-Host "FinAlly is running at http://localhost:$Port"
Write-Host ""

Start-Sleep -Seconds 2
Start-Process "http://localhost:$Port"
