# Canon RAG 設計方向評分卡

更新：2026-06-26。路線 **A → B → C** 已封板；hybrid + survey + context 12288。

---

## 對投資人（商業與護城河）

**總評：8.2 / 10**（2026-06-26 hybrid 70q baseline）

| 維度 | 分 | 說明 |
|------|---|------|
| 市場差異化 | 8 | 檢索 + CBETA 坐標 + 綜述，可稽核 |
| 技術護城河 | 7 | hybrid 檢索、題型路由、eval 體系 |
| 可演示性 | 8 | Open WebUI 端到端；義理題 ~40s 級 |
| 可擴展 | 9 | B1 全藏出處 + B2 teaser + 三層分工清晰 |
| 風險 | 6 | LLM 綜述段需抽查；ingest 覆蓋非全 T 藏 |
| 里程碑 | 9 | go_live PASS；**70q pass_rate 98.6%** |

**投資人一句話**：**帶出處的佛典 Copilot** — 義理問答 + 全藏出處表 + CBETA 分工，非全文索引替代品。

**對外數字（hybrid baseline，2026-06-26）**

| 指標 | 值 | 報告 |
|------|-----|------|
| synthesis **pass_rate** | **98.6%** (69/70) | `data/logs/synthesis_hybrid_70q_baseline.json` |
| citation_valid_rate | **100%** | |
| faithfulness (rules) | **91.5%** | |
| cross_translation (D01/D02/D04) | **100%** | 禁「A 即 B」 |
| 唯一未過 | D13 戒律 | 可追蹤 |

---

## 對學者（考據與可用性）

**總評：7.8 / 10**

| 維度 | 分 | 說明 |
|------|---|------|
| 出處可追溯 | 8 | 【義理面向】摘錄 + `【T…】`；hybrid 綜述受坐標約束 |
| 覆蓋完整性 | 7 | top-k 義理 + `list_tripitaka_occurrences` 語料統計 |
| 綜述品質 | 8 | 跨譯本 prompt 禁硬對名相；eval 自動檢查 |
| 與 CBETA 關係 | 9 | [USER_GUIDE_ZH.md](USER_GUIDE_ZH.md) 三層分工 |
| 標籤可讀性 | 8 | 義理標籤如【雜阿含 T99】 |

**學者工作流**：佛典RAG 義理 → CBETA 核坐標 → 必要時全藏出處表。

---

## 對維運

**總評：8.0 / 10**

| 維度 | 分 | 說明 |
|------|---|------|
| 可測性 | 9 | recall + synthesis 70q + cross_translation golden |
| 可部署 | 8 | `install_openwebui_canon_rag.sh` 一鍵 |
| 配置 | 7 | env 見下；12288 context 已上 |
| 觀測 | 7 | 週一 cron smoke；`data/logs/` |
| 回滾 | 8 | `D_SYNTH=extractive`；`SURVEY_TEASER=0` |

**關鍵環境**

```bash
VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
VAJRA_RAG_D_SYNTH=hybrid
VAJRA_CANON_CACHE_KEY_VERSION=phase_2c_v6
VAJRA_RAG_SURVEY_TEASER=doctrine   # D 類義理才附 teaser；1=全開；0=關
VAJRA_LLM_CONTEXT=12288            # qwen35b max-model-len
VAJRA_WEBUI_CTX_BUDGET=11000
```

**重裝 WebUI**：`bash canon/scripts/install_openwebui_canon_rag.sh`  
**驗收**：`bash canon/scripts/go_live_acceptance.sh`  
**70q eval**：`python3 -m canon.eval.run_eval_synthesis --report data/logs/synthesis_hybrid_70q_baseline.json`

---

## 路線圖狀態

| 階段 | 狀態 | 內容 |
|------|------|------|
| **A** | ✅ | hybrid、guard、go_live、70q baseline |
| **B1** | ✅ | `canon_survey` + `list_tripitaka_occurrences` |
| **B2** | ✅ | RAG 後 teaser（doctrine 模式） |
| **C** | ✅ | 週 eval cron、canon-rag-ops skill |
| **P2-8** | ✅ | qwen35b context 12288 |

---

## 相關文檔

- [USER_GUIDE_ZH.md](USER_GUIDE_ZH.md)
- [GOLDEN_SET.md](../eval/GOLDEN_SET.md)
- [open-webui-canon-rag.md](open-webui-canon-rag.md)
