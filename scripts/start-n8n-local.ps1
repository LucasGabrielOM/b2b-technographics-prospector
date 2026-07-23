param(
    [int]$Port = 5678
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$n8nUserFolder = Join-Path $projectRoot ".n8n-local"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Node.js nao encontrado."
    Write-Host "Instale o Node.js LTS em https://nodejs.org/ e rode este script novamente."
    exit 1
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Host "npm nao encontrado. Reinstale o Node.js LTS marcando a opcao npm."
    exit 1
}

New-Item -ItemType Directory -Force -Path $n8nUserFolder | Out-Null

$env:N8N_USER_FOLDER = $n8nUserFolder
$env:N8N_PORT = "$Port"
$env:N8N_HOST = "localhost"
$env:N8N_PROTOCOL = "http"
$env:GENERIC_TIMEZONE = "America/Sao_Paulo"
$env:TZ = "America/Sao_Paulo"
$env:N8N_DEFAULT_BINARY_DATA_MODE = "filesystem"

Write-Host "Abrindo n8n local em http://localhost:$Port"
Write-Host "Dados locais do n8n: $n8nUserFolder"
Write-Host "Se for a primeira execucao, o npx vai baixar o n8n automaticamente."

npx --yes n8n@latest start
