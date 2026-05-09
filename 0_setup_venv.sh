#!/usr/bin/env bash
# Monlam vLLM環境建立腳本
set -euo pipefail

echo "=== 建立 vLLM 虛擬環境 ==="

# 1. 檢查Python版本
echo "[1/6] 檢查Python版本..."
if ! command -v python3 &> /dev/null; then
    echo "錯誤：找不到python3"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo "✓ Python版本: $PYTHON_VERSION"

# 2. 安裝python3-venv模組（如果未安裝）
echo "[2/6] 檢查python3-venv模組..."
if ! python3 -m venv --help &> /dev/null; then
    echo "正在安裝python3-venv..."
    sudo apt update
    sudo apt install -y python3-venv
fi
echo "✓ python3-venv已安裝"

# 3. 建立虛擬環境
VENV_PATH="$HOME/.venvs/vllm"
echo "[3/6] 建立虛擬環境於 $VENV_PATH ..."

if [ -d "$VENV_PATH" ]; then
    echo "! 虛擬環境已存在，將重新建立"
    rm -rf "$VENV_PATH"
fi

mkdir -p "$HOME/.venvs"
python3 -m venv "$VENV_PATH"
echo "✓ 虛擬環境已建立"

# 4. 激活虛擬環境
echo "[4/6] 激活虛擬環境..."
source "$VENV_PATH/bin/activate"
echo "✓ 虛擬環境已激活: $(which python3)"

# 5. 升級pip
echo "[5/6] 升級pip..."
python3 -m pip install --upgrade pip --quiet
PIP_VERSION=$(pip --version | awk '{print $2}')
echo "✓ pip版本: $PIP_VERSION"

# 6. 安裝vLLM及相關套件
echo "[6/6] 安裝vLLM、transformers、huggingface_hub..."
echo "（這步需要5-10分鐘，請稍候...）"

pip install vllm transformers huggingface_hub --quiet

echo ""
echo "=== 安裝完成 ==="
echo ""
echo "虛擬環境位置: $VENV_PATH"
echo "已安裝套件:"
pip list | grep -E "vllm|transformers|huggingface"
echo ""
echo "下一步指令："
echo "  1. 激活環境: source ~/.venvs/vllm/bin/activate"
echo "  2. 啟動Monlam: vllm serve TenzinGayche/Melong_preview --port 8002 ..."
