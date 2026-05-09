# 生成三個優化版本的部署腳本

scripts = {
    "1_quick_start.sh": """#!/usr/bin/env bash
# Monlam Melong 快速啟動腳本（適合測試）
set -euo pipefail

# 環境變數（使用您tune.sh已配置的路徑）
export HF_HOME=/mnt/models/hf
export TRANSFORMERS_CACHE=/mnt/models/hf
export VLLM_CACHE_ROOT=/mnt/models/vllm

# 安裝vLLM（如果尚未安裝）
if ! python3 -c "import vllm" 2>/dev/null; then
    echo "正在安裝vLLM..."
    pip3 install vllm transformers huggingface_hub
fi

# 檢查端口是否被佔用
if ss -ltn | grep -q ':8002 '; then
    echo "錯誤：端口8002已被佔用"
    echo "當前佔用情況："
    ss -ltnp | grep ':800[0-2]'
    exit 1
fi

echo "正在啟動Monlam Melong服務..."
echo "首次啟動會自動下載模型到 $HF_HOME"

# 啟動vLLM服務器（使用8002避免衝突）
vllm serve TenzinGayche/Melong_preview \\
  --host 0.0.0.0 \\
  --port 8002 \\
  --gpu-memory-utilization 0.30 \\
  --trust-remote-code \\
  --dtype bfloat16 \\
  --max-model-len 8192 \\
  --served-model-name monlam-melong

# 注意：
# - 端口改為8002（您的8000/8001已被Qwen/Hermes佔用）
# - gpu-memory-utilization降為0.30（您已有兩個36B模型在跑）
# - 增加served-model-name方便API呼叫
""",

    "2_systemd_service.sh": """#!/usr/bin/env bash
# Monlam Melong systemd服務安裝腳本
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/monlam-melong.service"
USER="${SUDO_USER:-$USER}"
VENV_PATH="/home/$USER/.venvs/vllm"

echo "正在創建systemd服務..."

# 創建Python虛擬環境（隔離依賴）
if [ ! -d "$VENV_PATH" ]; then
    python3 -m venv "$VENV_PATH"
    "$VENV_PATH/bin/pip" install -U pip
    "$VENV_PATH/bin/pip" install vllm transformers huggingface_hub
fi

# 生成systemd service檔案
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Monlam Melong vLLM Translation Service
Documentation=https://huggingface.co/TenzinGayche/Melong_preview
After=network-online.target nvidia-persistenced.service
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER

# 環境變數（使用tune.sh配置的NVMe快取路徑）
Environment=HF_HOME=/mnt/models/hf
Environment=TRANSFORMERS_CACHE=/mnt/models/hf
Environment=VLLM_CACHE_ROOT=/mnt/models/vllm
Environment=PYTHONUNBUFFERED=1
Environment=CUDA_VISIBLE_DEVICES=0

# vLLM啟動指令
ExecStart=$VENV_PATH/bin/python -m vllm.entrypoints.openai.api_server \\
  --model TenzinGayche/Melong_preview \\
  --served-model-name monlam-melong \\
  --host 0.0.0.0 \\
  --port 8002 \\
  --dtype bfloat16 \\
  --gpu-memory-utilization 0.30 \\
  --max-model-len 8192 \\
  --trust-remote-code \\
  --enable-prefix-caching

# 自動重啟策略
Restart=always
RestartSec=10
KillMode=mixed
TimeoutStopSec=30

# 資源限制（防止OOM）
MemoryMax=60G
TasksMax=4096

[Install]
WantedBy=multi-user.target
EOF

# 啟用並啟動服務
sudo systemctl daemon-reload
sudo systemctl enable monlam-melong.service
sudo systemctl start monlam-melong.service

echo "服務已安裝並啟動"
echo "查看狀態：sudo systemctl status monlam-melong"
echo "查看日誌：sudo journalctl -u monlam-melong -f"
""",

    "3_test_api.sh": """#!/usr/bin/env bash
# Monlam Melong API測試腳本
set -euo pipefail

API_URL="http://localhost:8002"
MODEL_NAME="monlam-melong"

echo "=== Monlam Melong API 測試 ==="

# 1. 檢查服務健康狀態
echo -e "\\n[1] 檢查健康狀態..."
curl -s "$API_URL/health" | jq '.' || echo "服務未就緒"

# 2. 列出可用模型
echo -e "\\n[2] 列出可用模型..."
curl -s "$API_URL/v1/models" | jq '.data[].id'

# 3. 測試中譯藏（基礎）
echo -e "\\n[3] 測試中文→藏文翻譯..."
curl -s "$API_URL/v1/chat/completions" \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"model\\": \\"$MODEL_NAME\\",
    \\"messages\\": [
      {\\"role\\": \\"system\\", \\"content\\": \\"你是專業的藏漢佛典翻譯助手。\\"},
      {\\"role\\": \\"user\\", \\"content\\": \\"請將此譯成藏文：您好，祝您吉祥如意。\\"}
    ],
    \\"temperature\\": 0.2,
    \\"max_tokens\\": 200
  }" | jq -r '.choices[0].message.content'

# 4. 測試佛教經文翻譯（進階）
echo -e "\\n[4] 測試佛教經文翻譯..."
curl -s "$API_URL/v1/chat/completions" \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"model\\": \\"$MODEL_NAME\\",
    \\"messages\\": [
      {\\"role\\": \\"system\\", \\"content\\": \\"你是藏傳佛教經論翻譯專家，遵循格魯派註疏傳統。\\"},
      {\\"role\\": \\"user\\", \\"content\\": \\"請將《心經》開頭『觀自在菩薩，行深般若波羅蜜多時』譯成藏文，並保留宗教術語的標準譯法。\\"}
    ],
    \\"temperature\\": 0.1,
    \\"max_tokens\\": 300
  }" | jq -r '.choices[0].message.content'

# 5. 測試藏譯中
echo -e "\\n[5] 測試藏文→中文翻譯..."
curl -s "$API_URL/v1/chat/completions" \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"model\\": \\"$MODEL_NAME\\",
    \\"messages\\": [
      {\\"role\\": \\"user\\", \\"content\\": \\"Please translate this Tibetan text to Chinese: བཀྲ་ཤིས་བདེ་ལེགས\\"}
    ],
    \\"temperature\\": 0.2,
    \\"max_tokens\\": 100
  }" | jq -r '.choices[0].message.content'

echo -e "\\n=== 測試完成 ==="
echo "如需調整temperature（0.1-0.3適合經論翻譯）或max_tokens，請修改此腳本"
""",

    "4_replace_qwen.sh": """#!/usr/bin/env bash
# 替換Qwen為Monlam的遷移腳本
set -euo pipefail

echo "=== 準備將port 8000從Qwen切換到Monlam ==="

# 1. 停止Qwen容器
echo "[1] 停止Qwen容器..."
if docker ps | grep -q vajra-qwen-36b; then
    docker stop vajra-qwen-36b
    docker rm vajra-qwen-36b
    echo "✓ Qwen已停止並移除"
else
    echo "! Qwen容器不在運行中"
fi

# 2. 檢查端口釋放
echo "[2] 確認端口8000已釋放..."
sleep 3
if ss -ltn | grep -q ':8000 '; then
    echo "✗ 端口8000仍被佔用："
    ss -ltnp | grep ':8000'
    exit 1
fi

# 3. 修改Monlam服務端口為8000
echo "[3] 重新配置Monlam使用端口8000..."
sudo sed -i 's/--port 8002/--port 8000/g' /etc/systemd/system/monlam-melong.service
sudo systemctl daemon-reload

# 4. 停止舊8002服務並啟動新8000服務
if systemctl is-active monlam-melong.service >/dev/null 2>&1; then
    sudo systemctl stop monlam-melong.service
fi
sudo systemctl start monlam-melong.service

# 5. 驗證服務
echo "[4] 驗證新服務..."
sleep 5
curl -s http://localhost:8000/v1/models | jq '.data[].id'

echo ""
echo "=== 遷移完成 ==="
echo "Monlam現在運行在port 8000"
echo "Hermes仍運行在port 8001"
echo "檢查狀態：sudo systemctl status monlam-melong"
"""
}

# 寫入檔案
import os
os.makedirs('output', exist_ok=True)

for filename, content in scripts.items():
    filepath = f'output/{filename}'
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(filepath, 0o755)  # 加執行權限

print("✓ 已生成4個部署腳本到 output/ 目錄：")
print()
for i, name in enumerate(scripts.keys(), 1):
    print(f"{i}. {name}")
    print(f"   用途：{name.split('_', 1)[1].replace('.sh', '').replace('_', ' ')}")
print()
print("建議執行順序：")
print("1. 先用 1_quick_start.sh 測試（前台運行，方便除錯）")
print("2. 確認可用後執行 2_systemd_service.sh（背景常駐）")
print("3. 用 3_test_api.sh 驗證翻譯品質")
print("4. 滿意後執行 4_replace_qwen.sh（完全取代Qwen）")

