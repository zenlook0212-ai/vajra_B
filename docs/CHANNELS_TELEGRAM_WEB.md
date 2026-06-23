# Telegram + Web 雙渠道與統一 API

## 定位

- **FastAPI 閘道**（本目錄 `gateway/`）為**唯一業務入口**：六種 `mode` + `channel`；完整欄位與改進項見 **`docs/GATEWAY_SPEC.md`**。
- **Telegram Bot**、**Web 前端**只做鉴权、上传、Session UI，**不重寫翻譯／RAG／審核邏輯**，一律 `POST` 到閘道。
- **推理服務**維持現有 vLLM 容器；端點載入自 `models.yaml`（勿硬編碼 URL）。

## Channel 欄位

| `channel` | 說明 | Hermes 預設（見 `config/audit_policy.yaml`） |
|-----------|------|-----------------------------------------------|
| `web` | 瀏覽器客戶端 | `H2`（對外嚴格） |
| `telegram` | Telegram Bot | `H2` |
| `internal` | 內網工具／管理 | `H1`（可改） |

請求體帶 `channel`，閘道決定 `audit_level`（可用 query 或 header `X-Audit-Level` 覆寫，須受服务端白名單約束，實作見 `gateway/app.py`）。

## 模式對照表

| mode | 流程摘要 |
|------|----------|
| `translate` | 藏文達閾值 → Monlam → Qwen 潤飾；否則 Qwen 主翻 |
| `ocr` | Qwen-VL（須 `image_base64`） |
| `deep_think` | Qwen → Hermes JSON 審核 |
| `canon_rag` | Nemotron `/v1/embeddings` +（可選）關鍵字；此版僅占位檢索 hooks |
| `chat` | 直接 Qwen |
| `model_admin` | 唯讀：`nvidia-smi` 快照（需啟用 admin） |

## Telegram 整合要點

- **`hermes-gateway/telegram_bot.py`**：環境變數 **`VAJRA_GATEWAY_URL`**（預設 `http://127.0.0.1:8081`；8080 常被 ephemeris/Open WebUI 佔用）、**`VAJRA_GATEWAY_TASK_PATH`**（預設 `/v1/task`），所有對話／`/ask`／圖片皆 **`POST`** 至閘道；`/grep` 仍為本機 subprocess。

### 啟動 Bot（`/home/zenlook/hermes-gateway`）

1. 備妥 **`TELEGRAM_BOT_TOKEN`**（向 BotFather 取得）。
2. `cp .env.example .env` 並編輯 `.env`，填入 token。
3. **必須**先在本機啟動 Vajra 閘道（例：`cd /opt/vajra && VAJRA_GATEWAY_PORT=8081 ./scripts/run_gateway.sh`），並確認  
   `curl -sS http://127.0.0.1:8081/v1/modes` 含 `canon_rag`。未啟動時 Bot 會顯示「無法連接閘道」。
4. **前台**：`./run_telegram_bot.sh`  
   **systemd（user）**：`systemctl --user enable --now vajra-telegram-bot`（僅在有 `.env` 時會啟動；無 `.env` 會標記為條件未滿而略過）。
- **長文／多圖**：Bot 可分段送 `POST /v1/task` 或回覆「完整結果見 Web 連結」。
- **同 Session**：`client_request_id`（可選）便於日誌對齊 Telegram `chat_id`。
- **Rate limit**：Bot 層與閘道層雙重限制；閘道對外 `Semaphore(2)`（與 `.cursorrules` 一致）。

## Web 整合要點

- **CORS**：生產環境限制為你的前端 origin。
- **JWT / Session Cookie**：在 Web 邊完成，閘道使用 `Authorization: Bearer` 或反向代理傳遞身份（依你部署）。

## 運行（必須用 venv：PEP 668）

Ubuntu／Debian 預設 **禁止** `pip install` 寫入系統 Python，請用專案內 **虚拟环境**：

```bash
chmod +x /opt/vajra/scripts/setup_gateway_venv.sh /opt/vajra/scripts/run_gateway.sh
/opt/vajra/scripts/setup_gateway_venv.sh
```

啟動閘道：

```bash
export VAJRA_MODELS_YAML=/opt/vajra/models.yaml
export VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
VAJRA_GATEWAY_PORT=8081 /opt/vajra/scripts/run_gateway.sh
```

等同手動：

```bash
export VAJRA_MODELS_YAML=/opt/vajra/models.yaml
export PYTHONPATH=/opt/vajra
export VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
/opt/vajra/.venv/bin/uvicorn gateway.app:app --host 0.0.0.0 --port 8081
```

可選環境變數：`VAJRA_GATEWAY_HOST`、`VAJRA_GATEWAY_PORT`。

排錯：若出現 500，可先設 **`export VAJRA_GATEWAY_DEBUG=1`** 再啟動，回應 JSON 會含 `detail`。並確認 `curl` 對 **`/v1/task` 使用 `-X POST`**（不可用 GET）。

`run_gateway.sh` 已改為 **`venv/bin/python -m uvicorn`**，避免呼叫到系統其他 Python 的套件。

## 交付物核對

- [ ] `models.yaml` 與 `curl /v1/models` 各端口 `id` 一致  
- [ ] `config/routing.yaml` + `config/audit_policy.yaml` 版本化  
- [ ] Telegram／Web 共用 OpenAPI：`GET /openapi.json`  
- [ ] 生产：`hermes_down` + `H2` 時**不靜默對外出稿**（見審核策略）
