$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv .venv
}
uv pip install -r requirements.txt --python ".venv\Scripts\python.exe"

function Get-ConfigValue([string]$Name, [string]$Default) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if ($null -eq $v) { return $Default }
    $v = $v.Trim()
    if ($v.Length -eq 0) { return $Default }
    return $v
}

# Default is loopback only. Set HOST_BIND=0.0.0.0 to expose the GUI on the LAN.
$HostBind = Get-ConfigValue "HOST_BIND" "127.0.0.1"
$Port = Get-ConfigValue "PORT" "8100"
$LlamaBase = Get-ConfigValue "LLAMA_BASE" "http://127.0.0.1:8080/v1"
$LmstudioBase = Get-ConfigValue "LMSTUDIO_BASE" "http://127.0.0.1:1234/v1"
$ComfyUrl = Get-ConfigValue "COMFY_URL" "http://localhost:8000"

# LLM / ComfyUI can also be overridden by environment variables:
#   LLM_HOST, LLM_PORT, LLAMA_SERVER, LLM_MODEL, LLM_ALIAS

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$argList = @("-m", "uvicorn", "app.server:app", "--host", [string]$HostBind, "--port", [string]$Port)
$proc = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $PSScriptRoot -PassThru

Write-Host "GUI server starting (PID $($proc.Id))... http://${HostBind}:${Port}"
Write-Host "LLAMA_BASE=$LlamaBase"
Write-Host "LMSTUDIO_BASE=$LmstudioBase"
Write-Host "COMFY_URL=$ComfyUrl"

Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:$Port"
