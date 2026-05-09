#!/usr/bin/env bash
# =============================================================================
# DGX Spark (GB10) 系統調校腳本
# 用法：
#   ./tune.sh check       # 只檢查目前狀態，不做任何改動
#   ./tune.sh apply       # 套用所有調校（會 sudo）
#   ./tune.sh apply <sec> # 只套用某一節，例如：./tune.sh apply cpu
#                         # 可選: snapd, sysctl, thp, cpu, nvme, persistence, hf
#
# 設計原則：
#   - 每個函式對應一節，可單獨呼叫
#   - 全部冪等（多次執行結果一致）
#   - 改動前先備份 / 印出 diff
# =============================================================================
set -euo pipefail

YELLOW=$'\033[33m'; GREEN=$'\033[32m'; RED=$'\033[31m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
log()  { printf "${CYAN}[tune]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[ok]${RESET}   %s\n" "$*"; }
warn() { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
err()  { printf "${RED}[err]${RESET}  %s\n" "$*" >&2; }

require_root() {
  if [[ $EUID -ne 0 ]]; then
    log "重新以 sudo 執行..."
    exec sudo --preserve-env=USER,HOME "$0" "$@"
  fi
}

# ----------------------------------------------------------------------- check
check_state() {
  log "=== DGX Spark 健康檢查 ==="
  echo
  log "1) 驅動與 CUDA"
  nvidia-smi --query-gpu=name,driver_version,vbios_version --format=csv,noheader || err "nvidia-smi 失敗"
  echo

  log "2) Persistence mode"
  nvidia-smi -q | awk '/Persistence Mode/ {print "   "$0; exit}'

  log "3) CPU governor (cpu0)"
  echo "   $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo 'N/A')"

  log "4) NVMe schedulers"
  for d in /sys/block/nvme*; do
    [[ -e $d ]] && echo "   $(basename $d): $(cat $d/queue/scheduler)"
  done

  log "5) Transparent HugePages"
  echo "   enabled: $(cat /sys/kernel/mm/transparent_hugepage/enabled)"
  echo "   defrag:  $(cat /sys/kernel/mm/transparent_hugepage/defrag)"

  log "6) 記憶體與 swap"
  grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree|Hugepagesize):' /proc/meminfo | sed 's/^/   /'

  log "7) snapd 狀態"
  echo "   active: $(systemctl is-active snapd 2>/dev/null || echo unknown)"

  log "8) Throttle reasons (這幾個要全 Not Active 才健康)"
  nvidia-smi -q -d PERFORMANCE | awk '/Clocks Event Reasons/,/Compute Mode/' | grep -E '(SW|HW|Sync|Idle|Setting)' | head -10 | sed 's/^/   /'

  log "9) 溫度與功耗"
  nvidia-smi --query-gpu=temperature.gpu,power.draw,power.limit --format=csv | sed 's/^/   /'

  log "10) ConnectX-7 (雙機才相關)"
  if command -v ibstat &>/dev/null; then
    ibstat 2>/dev/null | grep -E "(CA|State|Rate)" | head -10 | sed 's/^/   /' || echo "   未偵測到 InfiniBand 設備"
  else
    echo "   ibstat 未安裝（apt install infiniband-diags）"
  fi

  echo
  ok "檢查完畢。任何標 N/A 或異常的項目，可用 './tune.sh apply <section>' 修正。"
}

# ---------------------------------------------------------------------- snapd
disable_snapd() {
  log "停用 snapd（DGX OS 7.4 已知會吃滿 CPU）"
  systemctl disable --now snapd.service snapd.socket snapd.seeded.service 2>/dev/null || true
  systemctl mask snapd.service 2>/dev/null || true
  ok "snapd 已 disable + mask"
}

# --------------------------------------------------------------------- sysctl
apply_sysctl() {
  log "寫入 /etc/sysctl.d/99-dgx-spark.conf"
  cat > /etc/sysctl.d/99-dgx-spark.conf <<'EOF'
# DGX Spark optimized sysctl (UMA-aware)
# 推論機：盡量避免 swap，但保留少量緊急用
vm.swappiness=10
vm.dirty_ratio=10
vm.dirty_background_ratio=5
# 允許 perf 抓 trace
kernel.perf_event_paranoid=-1
kernel.kptr_restrict=0
# 提高網路 buffer（ConnectX-7 200GbE 需要）
net.core.rmem_max=536870912
net.core.wmem_max=536870912
net.core.rmem_default=33554432
net.core.wmem_default=33554432
net.core.netdev_max_backlog=250000
net.ipv4.tcp_rmem=4096 87380 536870912
net.ipv4.tcp_wmem=4096 87380 536870912
EOF
  sysctl --system >/dev/null
  ok "sysctl 已套用"
}

# ------------------------------------------------------------------------ thp
apply_thp() {
  log "Transparent HugePages → madvise（讓推論引擎決定）"
  echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
  echo madvise > /sys/kernel/mm/transparent_hugepage/defrag
  # 永久化（rc.local 風格 systemd unit）
  cat > /etc/systemd/system/thp-madvise.service <<'EOF'
[Unit]
Description=Set Transparent HugePages to madvise (DGX Spark)
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'echo madvise > /sys/kernel/mm/transparent_hugepage/enabled'
ExecStart=/bin/sh -c 'echo madvise > /sys/kernel/mm/transparent_hugepage/defrag'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl enable --now thp-madvise.service >/dev/null
  ok "THP 已設為 madvise，並建立 systemd 服務"
}

# ------------------------------------------------------------------------ cpu
apply_cpu_governor() {
  log "CPU governor → performance（全部 core）"
  if ! command -v cpupower &>/dev/null; then
    apt-get install -y "linux-tools-$(uname -r)" linux-tools-generic >/dev/null
  fi
  cpupower frequency-set -g performance >/dev/null
  # 永久化
  cat > /etc/systemd/system/cpu-perf.service <<'EOF'
[Unit]
Description=Set CPU governor to performance (DGX Spark)
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/bin/cpupower frequency-set -g performance
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl enable --now cpu-perf.service >/dev/null
  ok "CPU governor 已設 performance + systemd 開機自動套用"
  warn "提示：跑 vLLM/TRT-LLM 時建議手動釘 P-core： taskset -c 0-4 numactl --membind=0 ..."
}

# ----------------------------------------------------------------------- nvme
apply_nvme_scheduler() {
  log "NVMe scheduler → none"
  for d in /sys/block/nvme*; do
    [[ -e $d ]] && echo none > "$d/queue/scheduler"
  done
  cat > /etc/udev/rules.d/60-nvme-scheduler.rules <<'EOF'
ACTION=="add|change", KERNEL=="nvme[0-9]*", ATTR{queue/scheduler}="none"
EOF
  udevadm control --reload-rules
  ok "NVMe scheduler 已設 none + udev rule"
}

# ---------------------------------------------------------------- persistence
apply_persistence() {
  log "啟用 NVIDIA persistence mode"
  systemctl enable --now nvidia-persistenced 2>/dev/null || warn "nvidia-persistenced 服務不存在，使用 nvidia-smi 設定"
  nvidia-smi -pm 1 >/dev/null
  ok "Persistence mode 已啟用"
}

# ------------------------------------------------------------------------- hf
configure_hf_cache() {
  log "建議 HF/模型快取放到 NVMe（不會自動移動現有檔案）"
  local target_user="${SUDO_USER:-$USER}"
  local home_dir
  home_dir=$(getent passwd "$target_user" | cut -d: -f6)
  local profile="$home_dir/.bashrc"
  local cache_dir="/mnt/models/hf"

  mkdir -p "$cache_dir"
  chown -R "$target_user:$target_user" /mnt/models 2>/dev/null || true

  if ! grep -q "HF_HOME=$cache_dir" "$profile" 2>/dev/null; then
    {
      echo ""
      echo "# DGX Spark: model caches on NVMe"
      echo "export HF_HOME=$cache_dir"
      echo "export TRANSFORMERS_CACHE=$cache_dir"
      echo "export VLLM_CACHE_ROOT=/mnt/models/vllm"
    } >> "$profile"
    ok "已寫入 $profile（重新登入生效）"
  else
    ok "HF_HOME 已存在於 $profile"
  fi
}

# ----------------------------------------------------------------------- main
usage() {
  cat <<EOF
DGX Spark (GB10) 調校腳本

用法:
  $0 check                    只看狀態，不改動
  $0 apply [section ...]      套用調校；不指定 section 就全做

可用 section:
  snapd        停用 snapd（避免 CPU 暴衝）
  sysctl       套用 vm/perf/網路核心參數
  thp          THP → madvise + systemd 永久化
  cpu          governor → performance + systemd 永久化
  nvme         NVMe scheduler → none + udev
  persistence  啟用 nvidia-persistenced + -pm 1
  hf           設定 HF_HOME 到 /mnt/models/hf

範例:
  $0 check
  $0 apply                    全部
  $0 apply cpu nvme           只做這兩節
EOF
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    check) check_state ;;
    apply)
      require_root "$cmd" "$@"
      local sections=("$@")
      if [[ ${#sections[@]} -eq 0 ]]; then
        sections=(snapd sysctl thp cpu nvme persistence hf)
      fi
      for s in "${sections[@]}"; do
        case "$s" in
          snapd)       disable_snapd ;;
          sysctl)      apply_sysctl ;;
          thp)         apply_thp ;;
          cpu)         apply_cpu_governor ;;
          nvme)        apply_nvme_scheduler ;;
          persistence) apply_persistence ;;
          hf)          configure_hf_cache ;;
          *) err "未知 section: $s"; usage; exit 1 ;;
        esac
      done
      echo
      ok "全部完成。建議重啟一次以確保所有 systemd 服務正確啟動。"
      ;;
    -h|--help|help|"") usage ;;
    *) err "未知指令: $cmd"; usage; exit 1 ;;
  esac
}

main "$@"
