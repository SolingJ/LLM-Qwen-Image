$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    uv venv .venv
}
uv pip install -r requirements.txt --python ".venv\Scripts\python.exe"

# デフォルトはローカルホストのみ。LAN 公開する場合は HOST_BIND=0.0.0.0 に設定
$HostBind = if ($Env:HOST_BIND) { $Env:HOST_BIND } else { "127.0.0.1" }
$Port = if ($Env:PORT) { $Env:PORT } else { "8100" }

# LLM / ComfyUI の port・URL・パスは環境変数で上書き可 (例: $Env:LLM_PORT=9999)
#   LLM_HOST, LLM_PORT, LLAMA_BASE, LMSTUDIO_BASE, COMFY_URL
#   LLAMA_SERVER, LLM_MODEL, LLM_ALIAS (llama-server 管理起動用)

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$proc = Start-Process -FilePath $py -ArgumentList @("-m","uvicorn","app.server:app","--host",$HostBind,"--port",$Port) -WorkingDirectory $PSScriptRoot -PassThru
Write-Host "GUI server starting (PID $($proc.Id))... http://${HostBind}:${Port}"
Write-Host "LLAMA_BASE=" + $(if ($Env:LLAMA_BASE) { $Env:LLAMA_BASE } else { "http://127.0.0.1:8080/v1" })
Write-Host "LMSTUDIO_BASE=" + $(if ($Env:LMSTUDIO_BASE) { $Env:LMSTUDIO_BASE } else { "http://127.0.0.1:1234/v1" })
Write-Host "COMFY_URL=" + $(if ($Env:COMFY_URL) { $Env:COMFY_URL } else { "http://localhost:8000" })
Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:${Port}"
