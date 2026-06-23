"""GPU / Docker helpers for model_admin (allowlisted Docker control)."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


def docker_allowlist() -> frozenset[str]:
    raw = os.environ.get("VAJRA_DOCKER_ALLOWLIST", "").strip()
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def _validate_container(name: str | None, allow: frozenset[str]) -> str:
    if not name or not name.strip():
        raise ValueError("container name required")
    n = name.strip()
    if not allow:
        raise ValueError("VAJRA_DOCKER_ALLOWLIST is empty; refusing docker start/stop")
    if n not in allow:
        raise ValueError(f"container {n!r} not in allowlist")
    return n


async def nvidia_smi_text(*, timeout_sec: float = 30.0) -> str:
    proc = await asyncio.to_thread(
        subprocess.run,
        ["nvidia-smi"],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    return (proc.stdout or "") + (proc.stderr or "")


async def nvidia_gpu_memory_csv(*, timeout_sec: float = 15.0) -> tuple[str, list[dict[str, Any]]]:
    """Parse `nvidia-smi --query-gpu=...csv` into list of dicts."""
    proc = await asyncio.to_thread(
        subprocess.run,
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.used,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    out = proc.stdout.strip() + (proc.stderr.strip() if proc.returncode != 0 else "")
    rows: list[dict[str, Any]] = []
    for line in (proc.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        try:
            idx, name, used, total, free = parts
            rows.append(
                {
                    "index": int(float(idx)),
                    "name": name,
                    "memory_used_mib": int(float(used)),
                    "memory_total_mib": int(float(total)),
                    "memory_free_mib": int(float(free)),
                }
            )
        except ValueError:
            logger.warning("nvidia CSV parse skipped line: %s", line)
    return out, rows


def vram_advisory_rows(rows: list[dict[str, Any]], *, warn_below_mib: int) -> dict[str, Any]:
    hints: list[str] = []
    for g in rows:
        free_m = int(g.get("memory_free_mib", 0))
        if free_m < warn_below_mib:
            hints.append(
                f"GPU {g.get('index')}: free VRAM ~{free_m} MiB < threshold "
                f"{warn_below_mib}; consider stopping unused vLLM containers or "
                f"reducing --gpu-memory-utilization / --max-model-len on next start."
            )
    return {"gpus": rows, "hints": hints, "threshold_free_mib": warn_below_mib}


async def docker_run_json_subprocess(cmd: list[str], *, timeout_sec: float = 120.0) -> dict[str, Any]:
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    return {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[:8000],
        "stderr": (proc.stderr or "")[:8000],
    }


async def docker_ps_lines(*, timeout_sec: float = 30.0) -> str:
    proc = await asyncio.to_thread(
        subprocess.run,
        [
            "docker",
            "ps",
            "-a",
            "--format",
            "{{.Names}}\t{{.Status}}\t{{.Ports}}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    return (proc.stdout or "") + ("\nstderr: " + (proc.stderr or "") if proc.stderr else "")


async def docker_start_allowed(name: str, *, timeout_sec: float = 180.0) -> dict[str, Any]:
    n = _validate_container(name, docker_allowlist())
    return await docker_run_json_subprocess(["docker", "start", n], timeout_sec=timeout_sec)


async def docker_stop_allowed(name: str, *, timeout_sec: float = 120.0) -> dict[str, Any]:
    n = _validate_container(name, docker_allowlist())
    return await docker_run_json_subprocess(["docker", "stop", n], timeout_sec=timeout_sec)
