# Canon RAG 設計方向評分卡（7.8 / 10）

更新：2026-06。完整路線：**A 上線固化 → B 全藏出處 → C 運維自動化**。

---

## 對投資人（商業與護城河）

**總評：7.8 / 10 — 方向正確，差在規模證明與產品閉環未做完。**

| 維度 | 分 | 說明 |
|------|---|------|
| 市場差異化 | 8 | 非通用佛學聊天；**檢索 + CBETA 坐標 + 綜述**，可稽核 |
| 技術護城河 | 7 | hybrid 檢索、題型路由、eval 體系； corpus 與模型非獨占 |
| 可演示性 | 8 | Open WebUI 端到端可展示；40s 級延遲可接受 |
| 可擴展 | 8 | B 階段「全藏出處」補齊與 CBETA 分工，不正面硬剛全文索引 |
| 風險 | 6 | LLM 幻覺（已 guard）、ingest 覆蓋、運維複雜度 |
| 里程碑 | 7 | recall@5 100%、synthesis pass ~93%；需 A 階段 commit + 全量 re-eval |

**投資人一句話**：這是 **「帶出處的佛典 Copilot」**，不是 CBETA 複製品；B1 全藏出處上線後敘事可升至 **8.5+**。

**接下來 90 天**：A 封板 → B1 出處列表 → 種子用戶（寺院／佛學院）→ 週報 eval 指標。

---

## 對學者（考據與可用性）

**總評：7.5 / 10 — 適合作「初探與講義草稿」，不可替代 CBETA 逐條核對。**

| 維度 | 分 | 說明 |
|------|---|------|
| 出處可追溯 | 8 | 答案含 `【T…】` 坐標；hybrid 面向段直接來自 chunk |
| 覆蓋完整性 | 6 | top-k 摘錄，**非**全藏每一處（B1 將改善） |
| 綜述品質 | 8 | hybrid 綜合回答可讀；需回原文核對 |
| 與 CBETA 關係 | 9 | 定位清晰：義理問答 vs [CBETA 關鍵字搜](https://cbetaonline.dila.edu.tw/) |
| 幻覺控制 | 7 | 無坐標回答會被擋；綜述段偶發多引坐標需抽查 |

**學者一句話**：當 **研究助理初稿** 用；定稿與廣泛普查仍用 CBETA。見 [USER_GUIDE_ZH.md](USER_GUIDE_ZH.md)。

**建議工作流**：
1. 佛典RAG 問義理 → 得面向 + 綜述 + 連結  
2. CBETA 核對坐標原文  
3. （B1 後）同一對話「列出全藏出處」補經目  

---

## 對維運（你自己／團隊）

**總評：7.5 / 10 — 架構清晰，patch 與 env 需 runbook 統一。**

| 維度 | 分 | 說明 |
|------|---|------|
| 可測性 | 8 | `run_eval`、`run_eval_synthesis`、golden set |
| 可部署 | 7 | `install_openwebui_canon_rag.sh`、`run_gateway.sh` |
| 配置複雜度 | 6 | `VAJRA_RAG_D_SYNTH`、`CACHE_KEY_VERSION`、多 patch |
| 觀測 | 6 | logs 在 `data/logs/`；synthesis cron 待 C 階段 |
| 回滾 | 8 | `D_SYNTH=extractive|hybrid|llm` 一行切換 |

**關鍵環境（gateway）**

```bash
VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
VAJRA_RAG_D_SYNTH=hybrid          # extractive | llm | hybrid
VAJRA_CANON_CACHE_KEY_VERSION=phase_2c_v5
```

**重裝 WebUI patches**：`bash canon/scripts/install_openwebui_canon_rag.sh`

**驗收**：`bash canon/scripts/go_live_acceptance.sh`

**維運一句話**：先完成 **A（commit + 驗收 + eval）**，再加 **B1 survey**，最後 **C cron**。

---

## 路線圖與評分預期

| 階段 | 內容 | 預期總分 |
|------|------|----------|
| **現在** | hybrid + guard + USER_GUIDE | **7.8** |
| **A 完成** | git 封板、go_live、70q eval | **8.0** |
| **B1** | 全藏出處 tool + CBETA 連結 | **8.5** |
| **C** | 週 eval cron、ops skill | **8.7** |

---

## 相關文檔

- [USER_GUIDE_ZH.md](USER_GUIDE_ZH.md) — 使用者：何時用 RAG vs CBETA  
- [GOLDEN_SET.md](../eval/GOLDEN_SET.md) — 評測指標與門檻  
- [open-webui-canon-rag.md](open-webui-canon-rag.md) — WebUI 接入  
