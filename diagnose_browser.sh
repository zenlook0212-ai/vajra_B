#!/usr/bin/env bash
# diagnose_browser.sh — 瀏覽器 / snap / 顯示 / 網路診斷報告
# 用法: bash diagnose_browser.sh   或   chmod +x diagnose_browser.sh && ./diagnose_browser.sh

set +e

REPORT_LINE() { printf '%s\n' "$*"; }
SECTION() {
  REPORT_LINE ""
  REPORT_LINE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  REPORT_LINE "$1"
  REPORT_LINE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

RUN_CMD() {
  local title=$1
  shift
  REPORT_LINE ""
  REPORT_LINE "▶ $title"
  REPORT_LINE "   指令: $*"
  REPORT_LINE "   ───"
  bash -c "$*" 2>&1 | sed 's/^/   /'
  local ec=${PIPESTATUS[0]}
  REPORT_LINE "   (結束代碼: ${ec})"
}

REPORT_LINE "══════════════════════════════════════════════════════════════════════════════"
REPORT_LINE "  瀏覽器環境診斷報告"
REPORT_LINE "  主機: $(hostname 2>/dev/null || echo '?')"
REPORT_LINE "  時間: $(date -Iseconds 2>/dev/null || date)"
REPORT_LINE "  使用者: ${USER:-$(whoami 2>/dev/null)}"
REPORT_LINE "══════════════════════════════════════════════════════════════════════════════"

# --- 1. snapd ---
SECTION "1. snapd 服務與 Firefox / Chromium (snap)"
RUN_CMD "snapd 服務狀態" "systemctl status snapd --no-pager 2>&1"
RUN_CMD "snap 中的 Firefox" "snap list 2>&1 | grep -i firefox || true"
RUN_CMD "snap 中的 Chromium" "snap list 2>&1 | grep -i chromium || true"

# --- 2. 瀏覽器進程 ---
SECTION "2. 瀏覽器相關進程"
RUN_CMD "Firefox 進程" "ps aux 2>/dev/null | grep -i '[f]irefox' || true"
RUN_CMD "Chromium 進程" "ps aux 2>/dev/null | grep -i '[c]hromium' || true"
RUN_CMD "Chrome 進程" "ps aux 2>/dev/null | grep -i '[c]hrome' || true"

# --- 3. 網路 ---
SECTION "3. 網路連線與 DNS"
RUN_CMD "ping google.com (3 次)" "ping -c 3 google.com 2>&1"
RUN_CMD "HTTPS 標頭 google.com" "curl -sS -I --max-time 15 https://google.com 2>&1"
RUN_CMD "resolv.conf" "cat /etc/resolv.conf 2>&1"

# --- 4. 顯示環境 ---
SECTION "4. X11 / Wayland 顯示環境"
RUN_CMD "DISPLAY" 'echo "DISPLAY=${DISPLAY:-<未設定>}"'
RUN_CMD "WAYLAND_DISPLAY" 'echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<未設定>}"'
RUN_CMD "ps 中含 X 字樣 (grep X；可能含雜訊)" "ps aux 2>/dev/null | grep X || true"
RUN_CMD "Xorg / Wayland 相關 (精簡篩選)" "ps aux 2>/dev/null | grep -E '[X]org|[X]wayland' || true"

# --- 5. snap 遮罩與 snapd 日誌 ---
SECTION "5. 最近 snap 相關 (masked units / snapd 錯誤)"
RUN_CMD "masked 的 snap 相關 unit" "systemctl list-unit-files 2>&1 | grep snap | grep masked || true"
RUN_CMD "snapd journal 錯誤 (24h 內)" "journalctl -u snapd --since '24 hours ago' --no-pager 2>&1 | grep -i error || true"

# --- 6. 瀏覽器版本 ---
SECTION "6. 瀏覽器可執行檔版本 (timeout 5s)"
RUN_CMD "firefox --version" "timeout 5 firefox --version 2>&1"
RUN_CMD "chromium --version" "timeout 5 chromium --version 2>&1"

# --- 7. 系統錯誤日誌 ---
SECTION "7. 最近系統 err 等級日誌 (24h 內, 最後 50 行)"
RUN_CMD "journalctl -p err" "journalctl -p err --since '24 hours ago' -n 50 --no-pager 2>&1"

# --- 總結與建議 ---
SECTION "8. 可能原因與修復建議 (自動推論，需人工對照上方輸出)"

ISSUES=()
HINTS=()

if ! systemctl is-active --quiet snapd 2>/dev/null; then
  ISSUES+=("snapd 未在 running 狀態")
  HINTS+=("檢查: sudo systemctl status snapd；嘗試 sudo systemctl start snapd；若安裝異常可 sudo apt install --reinstall snapd")
fi

if ! ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1 && ! ping -c 1 -W 2 google.com >/dev/null 2>&1; then
  ISSUES+=("ICMP/對外連線可能失敗 (ping 不通)")
  HINTS+=("檢查實體線路/VPN/防火牆；嘗試 curl；確認路由與 /etc/resolv.conf")
fi

if ! curl -sS -I --max-time 8 https://google.com >/dev/null 2>&1; then
  ISSUES+=("HTTPS 連線 google.com 失敗或逾時")
  HINTS+=("檢查代理環境變數 http_proxy/https_proxy；SSL/證書；公司網路攔截")
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  ISSUES+=("DISPLAY 與 WAYLAND_DISPLAY 皆未設定 (可能無圖形工作階段)")
  HINTS+=("本機桌面登入後再試；SSH 需 X11 轉發 (-X) 或改用無頭/遠端桌面；在終端機只做 diagnose 時可忽略")
fi

if ! timeout 3 bash -c 'command -v firefox >/dev/null' 2>/dev/null; then
  :
else
  if ! timeout 6 firefox --version >/dev/null 2>&1; then
    ISSUES+=("firefox 指令存在但 --version 逾時或失敗")
    HINTS+=("可能 DISPLAY 缺失、設定檔鎖定、或 snap/套件衝突；試 snap run firefox 或完整路徑")
  fi
fi

if snap list 2>/dev/null | grep -qi firefox; then
  if ! timeout 6 snap run firefox --version >/dev/null 2>&1; then
    ISSUES+=("snap Firefox 可能無法正常啟動 (可手動對照)")
    HINTS+=("試 snap run firefox；檢查 snap interfaces；確保有圖形環境")
  fi
fi

RUN_CMD "snapd 日誌 error 行數 (簡檢)" 'c=$(journalctl -u snapd --since "24 hours ago" --no-pager 2>&1 | grep -ic error || true); echo "error 行數(約): $c"'

if [ ${#ISSUES[@]} -eq 0 ]; then
  REPORT_LINE "   自動檢查未偵測到明確異常條件；請仍閱讀各段落原始輸出。"
else
  REPORT_LINE "   推論到的問題點:"
  for i in "${!ISSUES[@]}"; do
    REPORT_LINE "   • ${ISSUES[$i]}"
  done
fi
REPORT_LINE ""
REPORT_LINE "   一般修復方向:"
REPORT_LINE "   • 套件: sudo apt update && sudo apt install firefox chromium-browser (或發行版對應套件名)"
REPORT_LINE "   • Snap: sudo snap refresh；確保預先 sudo systemctl enable --now snapd"
REPORT_LINE "   • 顯示: 確認已登入圖形介面；Wayland 下某些舊版應用需 XWayland"
REPORT_LINE "   • 日誌: journalctl -u snapd -b 與 journalctl -p err -b 進一步追蹤"
if [ ${#HINTS[@]} -gt 0 ]; then
  REPORT_LINE ""
  REPORT_LINE "   依目前結果的額外建議:"
  for h in "${HINTS[@]}"; do
    REPORT_LINE "   • $h"
  done
fi

REPORT_LINE ""
REPORT_LINE "══════════════════════════════════════════════════════════════════════════════"
REPORT_LINE "  報告結束"
REPORT_LINE "══════════════════════════════════════════════════════════════════════════════"
