#!/usr/bin/env bash
# =============================================================================
# DGX Spark (GB10) 基準測試腳本
# 用法：
#   ./benchmark.sh sysinfo          # 抓系統 + GPU 規格快照（套用 tune.sh 前後對比用）
#   ./benchmark.sh memory           # 記憶體頻寬（STREAM-like）
#   ./benchmark.sh gpu_compute      # GPU compute（cuBLAS GEMM）
#   ./benchmark.sh vllm <model>     # vLLM 端到端 throughput / latency
#   ./benchmark.sh all <model>      # 全部跑一輪
#
# 結果寫入 ./benchmark_results/<timestamp>/，方便 diff 前後。
# =============================================================================
set -euo pipefail

TS=$(date +%Y%m%d-%H%M%S)
OUTDIR="./benchmark_results/$TS"
mkdir -p "$OUTDIR"

CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
log() { printf "${CYAN}[bench]${RESET} %s\n" "$*"; }
ok()  { printf "${GREEN}[ok]${RESET}    %s\n" "$*"; }
warn(){ printf "${YELLOW}[warn]${RESET}  %s\n" "$*"; }

# --------------------------------------------------------------------- sysinfo
bench_sysinfo() {
  log "收集系統快照 → $OUTDIR/sysinfo.txt"
  {
    echo "=== timestamp ==="; date -Iseconds
    echo; echo "=== uname ==="; uname -a
    echo; echo "=== os-release ==="; cat /etc/os-release
    echo; echo "=== cpu (lscpu) ==="; lscpu
    echo; echo "=== cpu topology (P/E core) ==="; lscpu --extended
    echo; echo "=== meminfo ==="; grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree|HugePages|Hugepagesize)' /proc/meminfo
    echo; echo "=== nvidia-smi ==="; nvidia-smi
    echo; echo "=== nvidia-smi -q (excerpt) ==="
    nvidia-smi -q | grep -E '(Product Name|Driver Version|CUDA Version|Persistence Mode|Power Limit|Default Power Limit|Performance State|Memory Clock|SM Clock|Throttle Reasons|Idle|Setting|HW Slowdown|HW Power|Sync Boost|SW Power|SW Thermal|HW Thermal)' | head -40
    echo; echo "=== governor ==="; cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor | sort -u
    echo; echo "=== thp ==="; cat /sys/kernel/mm/transparent_hugepage/enabled
    echo; echo "=== nvme schedulers ==="; for d in /sys/block/nvme*; do echo "$d: $(cat $d/queue/scheduler)"; done
    echo; echo "=== docker ==="; docker --version 2>/dev/null || echo "docker 未安裝"
    echo; echo "=== nvcc ==="; nvcc --version 2>/dev/null || echo "nvcc 未安裝"
    echo; echo "=== python / pytorch ==="
    python3 - <<'PY' 2>/dev/null || true
import sys
print("python:", sys.version)
try:
    import torch
    print("torch:", torch.__version__, "cuda:", torch.version.cuda, "available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device 0:", torch.cuda.get_device_name(0))
        print("capability:", torch.cuda.get_device_capability(0))
except Exception as e:
    print("torch 未安裝或失敗:", e)
PY
  } > "$OUTDIR/sysinfo.txt"
  ok "sysinfo 完成"
}

# ---------------------------------------------------------------------- memory
bench_memory() {
  log "記憶體頻寬測試（用 sysbench memory，免額外編譯）"
  if ! command -v sysbench &>/dev/null; then
    warn "sysbench 未安裝；apt install sysbench 後重試。跳過。"
    return
  fi
  {
    echo "=== read 64GB total, 1MB block ==="
    sysbench memory --memory-block-size=1M --memory-total-size=64G --memory-oper=read run
    echo
    echo "=== write 64GB total, 1MB block ==="
    sysbench memory --memory-block-size=1M --memory-total-size=64G --memory-oper=write run
  } > "$OUTDIR/memory_bw.txt" 2>&1
  ok "記憶體頻寬 → $OUTDIR/memory_bw.txt"
}

# ----------------------------------------------------------------- gpu compute
bench_gpu_compute() {
  log "GPU compute 基準（PyTorch matmul，跑 BF16 / FP16 / FP8 if available）"
  python3 - > "$OUTDIR/gpu_compute.txt" 2>&1 <<'PY'
import time, torch
if not torch.cuda.is_available():
    print("CUDA 不可用，跳過"); raise SystemExit
dev = torch.device('cuda:0')
print("Device:", torch.cuda.get_device_name(0), "cap:", torch.cuda.get_device_capability(0))

def bench(dtype, label, n=8192, iters=50, warmup=5):
    a = torch.randn(n, n, device=dev, dtype=dtype)
    b = torch.randn(n, n, device=dev, dtype=dtype)
    for _ in range(warmup):
        c = a @ b
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(iters):
        c = a @ b
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / iters
    flops = 2 * n**3 / dt
    print(f"{label:8} {n}x{n} matmul: {dt*1000:7.2f} ms/iter, {flops/1e12:7.2f} TFLOPS")

for dt, name in [(torch.float32, 'FP32'), (torch.bfloat16, 'BF16'), (torch.float16, 'FP16')]:
    try:
        bench(dt, name)
    except Exception as e:
        print(f"{name} 失敗:", e)

# FP8 (Blackwell tensor core)
try:
    import torch._scaled_mm  # exists on recent torch
    n = 8192
    a = torch.randn(n, n, device=dev).to(torch.float8_e4m3fn)
    b = torch.randn(n, n, device=dev).to(torch.float8_e4m3fn).t().contiguous().t()
    scale = torch.tensor(1.0, device=dev)
    for _ in range(5):
        c = torch._scaled_mm(a, b, scale_a=scale, scale_b=scale, out_dtype=torch.bfloat16)
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(50):
        c = torch._scaled_mm(a, b, scale_a=scale, scale_b=scale, out_dtype=torch.bfloat16)
    torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / 50
    flops = 2 * n**3 / dt
    print(f"FP8e4m3 {n}x{n} scaled_mm: {dt*1000:7.2f} ms/iter, {flops/1e12:7.2f} TFLOPS")
except Exception as e:
    print("FP8 scaled_mm 不支援或失敗:", e)
PY
  ok "GPU compute → $OUTDIR/gpu_compute.txt"
}

# ------------------------------------------------------------------------ vllm
# 需要先有跑著的 vLLM OpenAI-compatible server。
# 預設端點 http://127.0.0.1:8000/v1 ，可用 VLLM_URL 環境變數覆寫。
bench_vllm() {
  local model="${1:-}"
  if [[ -z "$model" ]]; then
    warn "用法: $0 vllm <model_name_advertised_by_server>"
    return 1
  fi
  local url="${VLLM_URL:-http://127.0.0.1:8000/v1}"
  log "vLLM 端到端跑分（model=$model, url=$url）"

  # 測試 server 活著
  if ! curl -sf "$url/models" >/dev/null; then
    warn "無法連到 $url ；請先起一個 vLLM server 再跑。"
    return 1
  fi

  python3 - "$model" "$url" > "$OUTDIR/vllm_bench.txt" 2>&1 <<'PY'
import sys, time, json, asyncio, statistics
import httpx

model, url = sys.argv[1], sys.argv[2]

PROMPT_LONG = (
  "請將以下藏文佛典片段翻譯成現代中文，並保留術語的原始拼寫於括號中。"
  "翻譯時請依寧瑪派傳統詮釋，並注意句法的緊密度。\n\n"
) + ("བདག་ནི་སྔོན་ཆད་སེམས་ཅན་ཐམས་ཅད་ཀྱི་དོན་དུ་སངས་རྒྱས་ཀྱི་གོ་འཕང་ཐོབ་པར་འགྱུར་བའི་སེམས་བསྐྱེད་པར་བྱའོ། " * 30)

async def one(client, prompt, max_tokens):
    t0 = time.perf_counter()
    r = await client.post(f"{url}/completions", json={
        "model": model, "prompt": prompt, "max_tokens": max_tokens,
        "temperature": 0.0, "stream": False,
    }, timeout=600)
    r.raise_for_status()
    dt = time.perf_counter() - t0
    out = r.json()
    n_out = out["usage"]["completion_tokens"]
    n_in = out["usage"]["prompt_tokens"]
    return dt, n_in, n_out

async def streaming_ttft(client, prompt, max_tokens):
    t0 = time.perf_counter()
    ttft = None; n = 0
    async with client.stream("POST", f"{url}/completions", json={
        "model": model, "prompt": prompt, "max_tokens": max_tokens,
        "temperature": 0.0, "stream": True,
    }, timeout=600) as r:
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            if ttft is None:
                ttft = time.perf_counter() - t0
            try:
                obj = json.loads(data)
                n += len(obj["choices"][0].get("text", ""))
            except Exception:
                pass
    total = time.perf_counter() - t0
    return ttft, total, n

async def main():
    async with httpx.AsyncClient() as c:
        # 1) 單請求 short prompt
        print("=== single short prompt, 128 tokens ===")
        dt, ni, no = await one(c, "Translate to Chinese: I want to attain enlightenment for all beings.", 128)
        print(f"  total {dt*1000:.1f} ms, in={ni}, out={no}, throughput={no/dt:.1f} tok/s")

        # 2) 單請求 long prompt
        print("\n=== single long prompt, 256 tokens ===")
        dt, ni, no = await one(c, PROMPT_LONG, 256)
        print(f"  total {dt*1000:.1f} ms, in={ni}, out={no}, throughput={no/dt:.1f} tok/s")

        # 3) TTFT (streaming)
        print("\n=== streaming TTFT, long prompt ===")
        ttft, tot, n = await streaming_ttft(c, PROMPT_LONG, 256)
        print(f"  TTFT {ttft*1000:.1f} ms, total {tot*1000:.1f} ms, output_chars={n}")

        # 4) 並行 throughput
        for conc in (4, 8, 16):
            print(f"\n=== concurrency={conc}, 256 tokens each ===")
            t0 = time.perf_counter()
            tasks = [one(c, PROMPT_LONG, 256) for _ in range(conc)]
            results = await asyncio.gather(*tasks)
            wall = time.perf_counter() - t0
            total_out = sum(r[2] for r in results)
            print(f"  wall {wall:.2f}s, total_out_tokens={total_out}, "
                  f"aggregate_throughput={total_out/wall:.1f} tok/s, "
                  f"per_req_avg_latency={statistics.mean(r[0] for r in results)*1000:.0f} ms")

asyncio.run(main())
PY
  ok "vLLM 跑分 → $OUTDIR/vllm_bench.txt"
}

# ------------------------------------------------------------------------- all
bench_all() {
  bench_sysinfo
  bench_memory
  bench_gpu_compute
  if [[ -n "${1:-}" ]]; then
    bench_vllm "$1"
  else
    warn "未提供模型名稱，跳過 vLLM 部分。"
  fi
  echo
  ok "全部完成 → $OUTDIR"
  echo "下次跑分前後對比："
  echo "  diff -u <old>/sysinfo.txt $OUTDIR/sysinfo.txt"
  echo "  diff -u <old>/gpu_compute.txt $OUTDIR/gpu_compute.txt"
}

usage() {
  cat <<EOF
DGX Spark (GB10) 基準測試

用法:
  $0 sysinfo          系統 + GPU 快照
  $0 memory           記憶體頻寬（需 sysbench）
  $0 gpu_compute      cuBLAS / scaled_mm 跑分（需 PyTorch with CUDA）
  $0 vllm <model>     vLLM 端到端（需先起 server，預設 http://127.0.0.1:8000/v1）
  $0 all [model]      全部跑一輪
  $0 help

環境變數:
  VLLM_URL=...        覆寫 vLLM 端點
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  sysinfo)     bench_sysinfo ;;
  memory)      bench_memory ;;
  gpu_compute) bench_gpu_compute ;;
  vllm)        bench_vllm "$@" ;;
  all)         bench_all "$@" ;;
  help|-h|--help) usage ;;
  *) usage; exit 1 ;;
esac