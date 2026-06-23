# Golden Set v2

评测集 `golden_set.jsonl`（v2）用于 canon RAG 回归测试。旧版备份：`golden_set_v1_legacy.jsonl`。

## 分类

| 类别 | 含义 | 目标 recall@5 |
|------|------|----------------|
| **A** | 问题中 **明确经名**（长阿含、金刚经等） | ≥ 0.95 |
| **B** | **别名 / 经号**（金剛般若、T08n0235 等） | ≥ 0.90 |
| **C** | **范围内义理**（「長阿含經中如何說緣起」） | ≥ 0.75 |
| **D** | **开放义理**，`expected_canon_ids` 列多个可接受经号 | ≥ 0.60 |

## 字段

```json
{
  "id": "A01",
  "category": "A",
  "question": "...",
  "expected_canon_ids": ["T01n0001"],
  "sample_answer": "可选，含【坐标】用于 citation_accuracy",
  "notes": "可选"
}
```

- `expected_canon_id`（单数）仍兼容，但新题请用 `expected_canon_ids`。
- D 类：top-5 命中列表中 **任一** `expected_canon_ids` 即计为正确。

## 运行

```bash
export PYTHONPATH=/opt/vajra VAJRA_CANON_PG_DSN=postgresql://vajra:vajra@127.0.0.1:5433/canon
python -m canon.eval.run_eval --k 5 --report /opt/vajra/data/logs/canon_eval.json
```

报告含 `by_category`、`recall@5_AB_only`（经名+别名）、`recall@5_ABC_only`（不含开放 D 类）。

## 注意

- v2 分数 **不可** 与 v1 legacy（50 题全绑 T01）直接比较。
- 新增失败 case 请带 `id` 追加到对应类别，并注明 `notes`。
