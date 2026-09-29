$ErrorActionPreference = "Stop"

# 単一GPU(GPU0)用 llama-server ランチャー (GUI の llm_manager も同じ引数で起動する)
# 必須環境変数: LLAMA_SERVER, LLM_MODEL
# 任意環境変数: LLM_ALIAS, LLM_HOST, LLM_PORT
$env:CUDA_VISIBLE_DEVICES = "0"

if (-not $Env:LLAMA_SERVER -or -not $Env:LLM_MODEL) {
  Write-Host "LLAMA_SERVER and LLM_MODEL environment variables are required." -ForegroundColor Red
  exit 1
}

$Server = $Env:LLAMA_SERVER
$Model  = $Env:LLM_MODEL
$Alias  = if ($Env:LLM_ALIAS) { $Env:LLM_ALIAS } else { "local-model" }
$Host   = if ($Env:LLM_HOST)  { $Env:LLM_HOST }  else { "127.0.0.1" }
$Port   = if ($Env:LLM_PORT)  { $Env:LLM_PORT }  else { "8080" }

& $Server `
  --model $Model `
  --alias $Alias `
  --device CUDA0 `
  --gpu-layers all `
  --fit on `
  --ctx-size 32768 `
  --batch-size 2048 `
  --ubatch-size 512 `
  --flash-attn on `
  --cache-type-k q4_0 `
  --cache-type-v q4_0 `
  --cpu-ram 4096 `
  --jinja `
  --host $Host `
  --port $Port `
  --spec-type draft-mtp `
  --spec-draft-n-max 3 `
  --spec-draft-p-min 0 `
  --spec-draft-type-k q4_0 `
  --spec-draft-type-v q4_0 `
  --device-draft CUDA0 `
  --spec-draft-ngl all
