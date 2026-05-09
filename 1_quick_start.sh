#!/usr/bin/env bash
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
vllm serve TenzinGayche/Melong_preview \
  --host 0.0.0.0 \
  --port 8002 \
  --gpu-memory-utilization 0.30 \
  --trust-remote-code \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --served-model-name monlam-melong

# 注意：
# - 端口改為8002（您的8000/8001已被Qwen/Hermes佔用）
# - gpu-memory-utilization降為0.30（您已有兩個36B模型在跑）
# - 增加served-model-name方便API呼叫
