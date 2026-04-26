"""Benchmark: BetterCam (DXGI) vs MSS (GDI BitBlt) screen-capture throughput.

Runs each backend in a separate Python subprocess to avoid COM cleanup
crosstalk between mss/comtypes/bettercam at interpreter shutdown.

Run: python bench_capture.py
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time

import psutil

WARMUP_FRAMES = 60
BENCH_FRAMES = 600
CROP = 224
# Simulate inference-loop behavior: ~10ms of work per frame.
# Set to 0 for raw grab throughput; the realistic scenario uses ~10ms.
WORK_MS = 10


def _bench_inproc(backend: str) -> dict:
    """Runs inside a subprocess. Imports only the backend it needs."""
    from dbd.utils.monitoring_mss import Monitoring_mss

    if backend == "mss":
        ctx = Monitoring_mss(monitor_id=1, crop_size=CROP)
    elif backend == "bettercam":
        from dbd.utils.monitoring_bettercam import Monitoring_bettercam
        ctx = Monitoring_bettercam(monitor_id=0, crop_size=CROP, target_fps=480)
    else:
        raise SystemExit(f"unknown backend {backend}")

    proc = psutil.Process()
    proc.cpu_percent(interval=None)

    ctx.start()
    if backend == "bettercam":
        time.sleep(0.5)

    for _ in range(WARMUP_FRAMES):
        ctx.get_frame_np()

    proc.cpu_percent(interval=None)
    latencies: list[float] = []
    t_start = time.perf_counter()

    work_s = WORK_MS / 1000.0
    for _ in range(BENCH_FRAMES):
        t0 = time.perf_counter()
        frame = ctx.get_frame_np()
        latencies.append((time.perf_counter() - t0) * 1000.0)
        if work_s > 0:
            target = t0 + work_s
            while time.perf_counter() < target:
                pass

    elapsed = time.perf_counter() - t_start
    cpu_pct = proc.cpu_percent(interval=None) / max(psutil.cpu_count(logical=True), 1)
    fps = BENCH_FRAMES / elapsed

    print(json.dumps({
        "backend": backend,
        "fps": fps,
        "p50_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[-1],
        "p99_ms": statistics.quantiles(latencies, n=100)[-1],
        "mean_ms": statistics.mean(latencies),
        "cpu_pct": cpu_pct,
        "shape": list(frame.shape),
    }))


def _run_subproc(backend: str) -> dict:
    out = subprocess.run(
        [sys.executable, "-u", __file__, "--child", backend],
        capture_output=True, text=True, timeout=120,
    )
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"bench failed for {backend}\nstdout:\n{out.stdout}\nstderr:\n{out.stderr}")


def fmt(r: dict) -> str:
    return (
        f"{r['backend']:10}  fps={r['fps']:7.1f}   "
        f"mean={r['mean_ms']:5.2f}ms  p50={r['p50_ms']:5.2f}ms  "
        f"p95={r['p95_ms']:5.2f}ms  p99={r['p99_ms']:5.2f}ms   "
        f"cpu={r['cpu_pct']:4.1f}%   shape={tuple(r['shape'])}"
    )


def main_parent() -> None:
    print(f"Bench: {BENCH_FRAMES} frames @ {CROP}x{CROP}, {WARMUP_FRAMES} warmup, separate subprocesses per backend")
    print(f"CPU cores (logical): {psutil.cpu_count(logical=True)}")
    print()

    print("Running MSS subprocess ...")
    mss_r = _run_subproc("mss")
    print(fmt(mss_r))
    print()

    print("Running BetterCam subprocess ...")
    bc_r = _run_subproc("bettercam")
    print(fmt(bc_r))
    print()

    speedup = bc_r["fps"] / mss_r["fps"]
    cpu_delta = bc_r["cpu_pct"] - mss_r["cpu_pct"]
    print("=" * 60)
    print(f"BetterCam is {speedup:.2f}x faster than MSS  ({bc_r['fps']:.0f} vs {mss_r['fps']:.0f} fps)")
    print(f"CPU usage: BetterCam={bc_r['cpu_pct']:.1f}%  MSS={mss_r['cpu_pct']:.1f}%  (delta {cpu_delta:+.1f}pp)")
    print(f"Latency p99: BetterCam={bc_r['p99_ms']:.2f}ms  MSS={mss_r['p99_ms']:.2f}ms")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        _bench_inproc(sys.argv[2])
    else:
        main_parent()
