$ErrorActionPreference = "Stop"
$ContainerName = "finally-app"

$running = docker ps -q -f "name=$ContainerName"
if ($running) {
    docker stop $ContainerName
    docker rm $ContainerName
    Write-Host "FinAlly stopped. Data volume 'finally-data' preserved."
} else {
    $stopped = docker ps -aq -f "name=$ContainerName"
    if ($stopped) {
        docker rm $ContainerName
        Write-Host "Container removed. Data volume 'finally-data' preserved."
    } else {
        Write-Host "FinAlly is not running."
    }
}
