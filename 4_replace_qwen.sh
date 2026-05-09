#!/usr/bin/env bash
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
