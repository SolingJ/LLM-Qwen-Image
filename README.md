# LLM-Image-Generation

ローカル LLM（llama-server / LM Studio）でチャットする FastAPI ベースの Web GUI。
ComfyUI を使う任意の画像生成機能も含まれます。

## 機能

- チャット（OpenAI 互換 API: llama.cpp / LM Studio）
- thinking 内容の表示・切替（thinking ON/OFF）
- ボタン操作でのみ実行される任意の画像生成（ComfyUI）と生成進捗表示
- セッション履歴（SQLite）
- システムプロンプト / max_tokens を UI から設定
- LLM の起動/停止を GUI から管理

## 必要条件

- Python 3.12 以上（uv 推奨）
- llama-server（llama.cpp の CUDA ビルド）
- 使うモデルの GGUF ファイル
- ComfyUI（画像生成用）
- ComfyUI のカスタムノード:
  - `TextEncodeQwenImage21`
  - `QwenImage21Cache`
  - `SaveImageAdvanced`
  - `ResolutionSelector`
- ComfyUI のモデルディレクトリへのモデルファイル:
  - UNET: `qwen_image_2.1_int8_convrot.safetensors`
  - CLIP: `qwen3vl_8b_int8_convrot.safetensors`
  - VAE: `qwen_image_2.1_vae_bf16.safetensors`

## 起動方法

```powershell
uv venv .venv
uv pip install -r requirements.txt
.\run_gui.ps1
```

`run_gui.ps1` は依存関係のインストール・サーバー起動・ブラウザ表示まで行います。
llama-server を別途起動したい場合は `start_llm.ps1` を使えます
（GUI の「LLM 起動/停止」ボタンの内部で同じ引数を使用します）。

## 環境変数

| 変数 | デフォルト | 用途 |
|---|---|---|
| `HOST_BIND` | `0.0.0.0` | GUI のバインドアドレス |
| `PORT` | `8100` | GUI のポート |
| `LLM_HOST` | `127.0.0.1` | llama-server のホスト |
| `LLM_PORT` | `8080` | llama-server のポート |
| `LLAMA_BASE` | `http://127.0.0.1:8080/v1` | llama.cpp の API base（モデル一覧取得） |
| `LMSTUDIO_BASE` | `http://127.0.0.1:1234/v1` | LM Studio の API base |
| `COMFY_URL` | `http://localhost:8000` | ComfyUI の URL |
| `LLAMA_SERVER` | （未設定） | llama-server の実行ファイル（GUI から LLM 起動する場合に必須） |
| `LLM_MODEL` | （未設定） | GGUF モデルファイルのパス（GUI から LLM 起動する場合に必須） |
| `LLM_ALIAS` | `local-model` | llama-server のモデルエイリアス |

例:

```powershell
$Env:LLM_PORT   = "9999"
$Env:LLAMA_BASE = "http://127.0.0.1:9999/v1"
$Env:COMFY_URL  = "http://localhost:8188"
$Env:LLAMA_SERVER = "D:\tools\llama-server.exe"
$Env:LLM_MODEL  = "D:\models\my-model.gguf"
$Env:LLM_ALIAS  = "my-model"
.\run_gui.ps1
```

## 補足

- 画像生成には ComfyUI の事前起動が必要です。
- thinking 内容の表示は、モデルが thinking タグを出力した場合にのみ有効です。
- タグを出さないモデルでは、すべて通常の内容として表示されます。
- `.gitignore` で `.venv/`, `history.db`, `assets/`, `llm.log`, `.llm_state.json`, `opencode.json`, ローカル用ワークフロー/スクリプトは公開対象外です。
