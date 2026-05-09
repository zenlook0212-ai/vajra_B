#!/usr/bin/env bash
# Monlam Melong API測試腳本
set -euo pipefail

API_URL="http://localhost:8002"
MODEL_NAME="monlam-melong"

echo "=== Monlam Melong API 測試 ==="

# 1. 檢查服務健康狀態
echo -e "\n[1] 檢查健康狀態..."
curl -s "$API_URL/health" | jq '.' || echo "服務未就緒"

# 2. 列出可用模型
echo -e "\n[2] 列出可用模型..."
curl -s "$API_URL/v1/models" | jq '.data[].id'

# 3. 測試中譯藏（基礎）
echo -e "\n[3] 測試中文→藏文翻譯..."
curl -s "$API_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL_NAME\",
    \"messages\": [
      {\"role\": \"system\", \"content\": \"你是專業的藏漢佛典翻譯助手。\"},
      {\"role\": \"user\", \"content\": \"請將此譯成藏文：您好，祝您吉祥如意。\"}
    ],
    \"temperature\": 0.2,
    \"max_tokens\": 200
  }" | jq -r '.choices[0].message.content'

# 4. 測試佛教經文翻譯（進階）
echo -e "\n[4] 測試佛教經文翻譯..."
curl -s "$API_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL_NAME\",
    \"messages\": [
      {\"role\": \"system\", \"content\": \"你是藏傳佛教經論翻譯專家，遵循格魯派註疏傳統。\"},
      {\"role\": \"user\", \"content\": \"請將《心經》開頭『觀自在菩薩，行深般若波羅蜜多時』譯成藏文，並保留宗教術語的標準譯法。\"}
    ],
    \"temperature\": 0.1,
    \"max_tokens\": 300
  }" | jq -r '.choices[0].message.content'

# 5. 測試藏譯中
echo -e "\n[5] 測試藏文→中文翻譯..."
curl -s "$API_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"$MODEL_NAME\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"Please translate this Tibetan text to Chinese: བཀྲ་ཤིས་བདེ་ལེགས\"}
    ],
    \"temperature\": 0.2,
    \"max_tokens\": 100
  }" | jq -r '.choices[0].message.content'

echo -e "\n=== 測試完成 ==="
echo "如需調整temperature（0.1-0.3適合經論翻譯）或max_tokens，請修改此腳本"
