#!/usr/bin/env bash
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
ExecStart=$VENV_PATH/bin/python -m vllm.entrypoints.openai.api_server \
  --model TenzinGayche/Melong_preview \
  --served-model-name monlam-melong \
  --host 0.0.0.0 \
  --port 8002 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.30 \
  --max-model-len 8192 \
  --trust-remote-code \
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
