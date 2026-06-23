# Vajra FastAPI 閘道 — 統一 API 規格（交付）

## 唯一入口

- **Base**: `POST /v1/task`（JSON），`GET /health`，`GET /v1/modes`（含路由與審核策略摘要）。
- **模型 URL / `model_id`**: `models.yaml`（閘道不硬編碼埠號）。

## 六種 `mode`（與本機預設埠對照）

| mode | 行為摘要 | 預設依賴（`models.yaml` 鍵） |
|------|-----------|------------------------------|
| `translate` | 藏文閾值達標 → **Monlam** (8001) 初譯 → **Qwen35B** (8003) 潤飾；否則直接 Qwen；**SQLite Translation Memory** 去重；可選 **`VAJRA_HERMES_TRANSLATE`** 於主鏈後附 `output.hermes_audit` | `monlam`, `qwen`（可選 `hermes`） |
| `ocr` | 單圖：`image_base64`；**批次**：`images_base64` 陣列並行送 **Qwen-VL** (8004) | `qwen_vl` |
| `deep_think` | **Qwen35B** 推理 → **Hermes** (8002) JSON 審核；H1 未通過時 `meta.hermes_review` 標記 | `qwen`, `hermes` |
| `canon_rag` | **Nemotron** embed → 可選 **Chroma**；可選 **語義擴散**（第二輪 embed）；**專家路由**（依問題語境調整合成 system／溫度）；回傳 `similar_sutra_links`（CBETA Online 連結）供前端／Bot 顯示；可選 **`VAJRA_HERMES_CANON_RAG`** 於合成後附 `output.hermes_audit` | `nemotron_embed`, `qwen`（可選 `hermes`） |
| `chat` | 輕量對話，直接 Qwen；**System** 含 `<Logic_Gate>`，要求模型標註「原文證據／邏輯推論」（`channel=internal` 且 `client_request_id` 前綴 `summarize-` 時略過，供 Session 摘要） | `qwen` |
| `model_admin` | 需 `X-Admin-Token` + `VAJRA_ADMIN_TOKEN`；見下節 | — |

## `docker-compose.yml` 與 `models.yaml` 對照（`/opt/vajra`）

閘道只讀 **`models.yaml` 的 URL / model_id`**；容器是否由 compose 啟動皆可，只要埠一致。

| `models.yaml` 鍵 | 預設主機埠 | 本倉 compose `service` | `container_name`（yaml 內） | 備註 |
|------------------|------------|-------------------------|-----------------------------|------|
| `qwen` | **8003** | `qwen35b-inference` | `qwen35b-vllm` | `chat` / `translate`（潤飾）/ `deep_think`（前半）/ `canon_rag`（合成） |
| `hermes` | **8002** | `hermes-8b-inference` | `vajra-hermes-8b` | `deep_think` 審核；可選 translate/canon_rag Hermes |
| （閘道不用） | **8000** | `qwen-36b-inference` | `vajra-qwen-36b` | 範例用另一文字模型；**勿與 8003 同時拉滿 GPU**，按需擇一 |
| （向量庫） | **8040** | `chromadb` | `vajra-chromadb` | 設定 `VAJRA_CHROMA_API_ROOT=http://127.0.0.1:8040` 後供 `canon_rag` |

下列 **`models.yaml` 鍵本 compose 未定義**，常見為獨立 `docker run`（埠須與 yaml 一致）：

| 鍵 | 預設埠 | 說明 |
|----|--------|------|
| `monlam` | **8001** | 藏文初譯 |
| `qwen_vl` | **8004** | `ocr` |
| `nemotron_embed` | **8005** | `canon_rag` 嵌入 |

### 常用指令（於 `/opt/vajra`）

```bash
cd /opt/vajra
docker compose config          # 語法檢查
docker compose ps              # 本專案容器狀態
docker compose up -d chromadb  # 只起向量庫（不占推理 GPU）
docker compose up -d qwen35b-inference hermes-8b-inference
```

勿在未評估 VRAM 下直接 **`docker compose up -d`**（會連 **`qwen-36b-inference`** 一併嘗試啟動）。若主機已有同名容器（例如先前 `docker run` 建立的 `qwen35b-vllm`），與 compose **`container_name` 衝突**時需先 `docker stop/rm` 再用 compose 接管。

## 改進項（實作狀態）

1. **Translation Memory** — `translate` 成功後寫入 `data/translation_memory.sqlite`（可用 `VAJRA_TM_DB` 覆寫）；`skip_translation_memory: true` 略過；`VAJRA_TRANSLATION_MEMORY=0` 關閉。
2. **Smart Routing** — `config/routing.yaml` 的 `language_detection`（藏文字元數與比例）決定是否走 Monlam。
3. **Batch OCR** — `images_base64`；並發受全域 LLM semaphore（預設 2）與 `VAJRA_OCR_BATCH_MAX`（預設 16，上限 48）約束。
4. **VRAM** — 啟動時可選記錄 `nvidia-smi` CSV（`VAJRA_VRAM_LOG_ON_START`，預設在測試關閉）；**自動改 vLLM 的 `gpu_memory_utilization` 需重啟容器**，閘道只提供 **`model_admin.ops.action=vram_json` 的文字建議**，不替你改運行中行程。
5. **Hermes 閘控** — `config/audit_policy.yaml`：`H0` 跳過審、`H1` 寬鬆（Hermes 掛時可降级）、`H2` 嚴格；`channel_default_audit` 依 `telegram` / `web` / `internal`。
6. **可選 Hermes（translate / canon_rag）** — 預設關閉。開啟後在主鏈成功後多打一輪 Hermes；若 Hermes 回錯或逾時，**不阻斷**主輸出，於 `output.hermes_audit` 附 `bypass: true` 與 `issues` 說明。`meta.hermes_translate_audit` / `meta.hermes_canon_audit` 標示本次是否嘗試審核。依賴 `models.yaml` 的 `hermes` 鍵。

## `model_admin` — `ops` 欄位

```json
{
  "mode": "model_admin",
  "channel": "internal",
  "ops": { "action": "snapshot" }
}
```

| `ops.action` | 說明 |
|---------------|------|
| `snapshot` | 全文 `nvidia-smi`（預設，舊行為相容） |
| `vram_json` | CSV + 每台 GPU MiB；`hints` 在閒餘 VRAM 低於 `VAJRA_VRAM_WARN_FREE_MIB`（預設 4096）時提示 |
| `docker_ps` | `docker ps -a` 摘要 |
| `docker_start` / `docker_stop` | 需提供 `container`；名稱必須列出在環境變數 **`VAJRA_DOCKER_ALLOWLIST`**（逗號分隔）；未設定則拒絕 |

## 環境變數速查

| 變數 | 預設 | 說明 |
|------|------|------|
| `VAJRA_TM_DB` | `data/translation_memory.sqlite` | TM 資料庫路徑 |
| `VAJRA_TRANSLATION_MEMORY` | `1` | 是否啟用 TM |
| `VAJRA_OCR_BATCH_MAX` | `16` | 單請求最多張數（上限 48） |
| `VAJRA_VRAM_LOG_ON_START` | `1` | 啟動時是否打 GPU 並寫 WARN（測試常關） |
| `VAJRA_VRAM_WARN_FREE_MIB` | `4096` | 閒 VRAM 低於此則告警 |
| `VAJRA_DOCKER_ALLOWLIST` | 空 | 允許 docker start/stop 的容器名 |
| `VAJRA_ADMIN_TOKEN` | — | **必填** admin 區 |
| `VAJRA_DISABLED_MODES` | 空 | 逗號分隔的 `mode` 名（如 `deep_think,ocr`）；被列舉者在閘道內一律 503 |
| `VAJRA_HERMES_TRANSLATE` | `0`（關） | `1`/`true`/`always`：非 TM 快取路徑在 `translate` 完成後呼叫 Hermes；`monlam_only`：僅藏文主路徑（`used_monlam`）時審；`0`/`false`/`off`/空：關閉 |
| `VAJRA_HERMES_CANON_RAG` | `0`（關） | `1`/`true`/`always`：每次 `canon_rag` 合成後審；`hits`/`auto`：僅 `meta.rag.hits > 0` 時審；關閉值同上 |

### 大藏經 RAG（Chroma，可選）

**本仓库 `docker-compose.yml` 已定義 `chromadb`：** 主机 **`8040`** → 容器 `8000`。啟動：

```bash
cd /opt/vajra && docker compose up -d chromadb
```

**環境變數（複製請用純數字 URL，不要使用 `<埠>`、`YOUR_PORT` 外加角括号）**，否則 bash 會把 `<` 當**輸入重定向**，出現「No such file or directory」。

現行 `chromadb/chroma` 映像已 **棄用 v1 REST**（`/api/v1/...` 多為 **HTTP 410**）。閘道預設會把「僅主機+埠」自動展開為 **v2** 路徑。

```bash
export VAJRA_CHROMA_API_ROOT=http://127.0.0.1:8040
export VAJRA_CHROMA_COLLECTION=canon
# 可選：VAJRA_CHROMA_TENANT、VAJRA_CHROMA_DATABASE（預設 default_tenant / default_database）
```

啟動後若立刻 `curl` 出現 **connection reset**，請等容器就緒後重試。檢查 v2 集合列表：

```bash
curl -sS 'http://127.0.0.1:8040/api/v2/tenants/default_tenant/databases/default_database/collections' | head -c 400
```

若需手動建空集合（名稱須與 `VAJRA_CHROMA_COLLECTION` 一致）：

```bash
curl -sS -X POST \
  'http://127.0.0.1:8040/api/v2/tenants/default_tenant/databases/default_database/collections' \
  -H 'Content-Type: application/json' \
  -d '{"name":"canon","get_or_create":true}'
```

| 變數 | 預設 | 說明 |
|------|------|------|
| `VAJRA_RAG_BACKEND` | `auto` | `auto`：若有 `VAJRA_CHROMA_API_ROOT` 則走 Chroma；`chroma`：強制檢索（失敗則無片段）；`none`：關閉檢索（僅 embed 摘要 + Qwen 保守作答） |
| `VAJRA_CHROMA_API_ROOT` | （空） | 建議 **`http://127.0.0.1:8040`**（自動接 v2）；或完整前綴 **`.../api/v2/tenants/.../databases/...`**；舊 **`.../api/v1`** 僅相容老部署（常 410） |
| `VAJRA_CHROMA_TENANT` / `VAJRA_CHROMA_DATABASE` | `default_tenant` / `default_database` | 僅在 API_ROOT 為「主機+埠」自動展開時使用 |
| `VAJRA_CHROMA_COLLECTION` | `canon` | 集合 **name**（非 UUID 時會先 `GET …/collections` 解析 id） |
| `VAJRA_RAG_TOP_K` | `8` | 每問最多返回片段數 |
| `VAJRA_RAG_DIFFUSION` | `1` | `1`/`true`：在 Chroma 首輪命中後，再以首幾條片段拼成 **種子句** 做第二次 embed + 檢索，合併去重（語義擴散）；`0`/`false`/`off` 關閉 |
| `VAJRA_RAG_SYNTH_TEMP_BASE` | `0.2` | `canon_rag` 合成 Qwen 的溫度基底；專家路由（如藏文語境）可能略為加減並 clamp 於安全區間 |
| `VAJRA_RAG_VERBOSE_JSON` | `0` | `1` 時回傳完整 `embedding_response` 與每條 `full_text`/`metadata` |

Chroma 需在 collection 內已寫入與 Nemotron **相容維度** 的向量；否則檢索會失敗並在 `meta.rag.status` 留下原因。

### CBETA 本地語料檢索（grep／ripgrep）

與上一節 **`canon_rag` 向量檢索（Chroma）** 不同：下列變數用於對**本機 CBETA 純文字語料目錄**做子程序全文搜尋（例如周邊 Telegram 機器人的 `/grep`、RAG 問答前嵌入的本地片段）。語料根路徑另由 **`CBETA_GREP_PATH`** 指定（預設常為本機掛載之 `cbeta-text` 目錄）。

| 變數 | 預設 | 說明 |
|------|------|------|
| `VAJRA_CBETA_USE_RG` | `auto` | `auto`：`PATH` 上存在 **`rg`（ripgrep）** 則使用 `rg`，否則退回 **GNU `grep`**。`1` / `true` / `yes` / `rg` / `ripgrep`：優先走 `rg`（仍須能解析到可執行檔，否則與實作一致時會退回 `grep`）。`0` / `false` / `no` / `grep`：強制使用 **`grep`**。 |
| `CBETA_GREP_TIMEOUT_SEC` | `120` | 單次子程序 **`grep`／`rg` 逾時**（秒，浮點數可）。逾時時服務應向使用者回報「搜尋逾時」並建議縮小關鍵詞。 |

修改後需**重啟**載入該邏輯的行程（例如 Telegram gateway）；無需重啟 vLLM。

### vLLM 逾時與 `ReadError`

若閘道回 **503** 且日誌出現 **`httpx.ReadError`**，多半為下游 vLLM 在回傳 body 過程中斷線（重啟、OOM、或生成太久）。

| 變數 | 預設 | 說明 |
|------|------|------|
| `VAJRA_VLLM_CHAT_TIMEOUT_SEC` | `180` | `chat` / `translate` 等 **chat/completions** 單次 HTTP 逾時（秒），範圍約 30–900 |
| `VAJRA_VLLM_EMBED_TIMEOUT_SEC` | `120` | `/v1/embeddings` 逾時（秒） |

修改後需**重啟閘道**；並用 `docker logs qwen35b-vllm`（或對應服務）對照錯誤。

