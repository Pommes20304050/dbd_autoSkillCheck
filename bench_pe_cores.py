"""Benchmark: P-cores vs E-cores vs mixed for ONNX inference of the DBD model.

Pins the *whole process* via SetProcessAffinityMask before each run, then
runs N forward passes on a synthetic 224x224 image and reports throughput.
"""

import ctypes
from ctypes import wintypes
import os
import sys
import time

import numpy as np
import onnxruntime as ort


# ---------- Windows API: detect P/E cores via EfficiencyClass ----------

ERROR_INSUFFICIENT_BUFFER = 122
RelationProcessorCore = 0


class GROUP_AFFINITY(ctypes.Structure):
    _fields_ = [
        ("Mask", ctypes.c_uint64),
        ("Group", wintypes.WORD),
        ("Reserved", wintypes.WORD * 3),
    ]


class PROCESSOR_RELATIONSHIP(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.BYTE),
        ("EfficiencyClass", wintypes.BYTE),
        ("Reserved", wintypes.BYTE * 20),
        ("GroupCount", wintypes.WORD),
        ("GroupMask", GROUP_AFFINITY * 1),
    ]


class _UNION(ctypes.Union):
    _fields_ = [("Processor", PROCESSOR_RELATIONSHIP)]


class SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(ctypes.Structure):
    _fields_ = [
        ("Relationship", wintypes.DWORD),
        ("Size", wintypes.DWORD),
        ("u", _UNION),
    ]


def detect_pe_cores():
    """Returns dict: {'p_mask': int, 'e_mask': int, 'p_logical': [int], 'e_logical': [int]}.
    Empty lists if not a hybrid CPU."""
    kernel32 = ctypes.windll.kernel32
    GetLogicalProcessorInformationEx = kernel32.GetLogicalProcessorInformationEx
    GetLogicalProcessorInformationEx.argtypes = [
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    GetLogicalProcessorInformationEx.restype = wintypes.BOOL

    length = wintypes.DWORD(0)
    GetLogicalProcessorInformationEx(RelationProcessorCore, None, ctypes.byref(length))
    if ctypes.GetLastError() != ERROR_INSUFFICIENT_BUFFER:
        raise OSError("GetLogicalProcessorInformationEx initial sizing failed")

    buf = (ctypes.c_byte * length.value)()
    if not GetLogicalProcessorInformationEx(
        RelationProcessorCore, buf, ctypes.byref(length)
    ):
        raise OSError("GetLogicalProcessorInformationEx failed")

    cores = []  # [(eff_class, mask)]
    offset = 0
    while offset < length.value:
        info = ctypes.cast(
            ctypes.addressof(buf) + offset,
            ctypes.POINTER(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX),
        ).contents
        if info.Relationship == RelationProcessorCore:
            eff = int(info.u.Processor.EfficiencyClass)
            mask = int(info.u.Processor.GroupMask[0].Mask)
            cores.append((eff, mask))
        offset += info.Size

    if not cores:
        return {"p_mask": 0, "e_mask": 0, "p_logical": [], "e_logical": []}

    eff_classes = sorted({c[0] for c in cores})
    if len(eff_classes) < 2:
        # Homogeneous CPU — treat all as P-cores
        all_mask = 0
        for _, m in cores:
            all_mask |= m
        return {
            "p_mask": all_mask,
            "e_mask": 0,
            "p_logical": _mask_to_list(all_mask),
            "e_logical": [],
        }

    p_class = eff_classes[-1]
    p_mask = 0
    e_mask = 0
    for eff, mask in cores:
        if eff == p_class:
            p_mask |= mask
        else:
            e_mask |= mask
    return {
        "p_mask": p_mask,
        "e_mask": e_mask,
        "p_logical": _mask_to_list(p_mask),
        "e_logical": _mask_to_list(e_mask),
    }


def _mask_to_list(mask):
    return [i for i in range(64) if mask & (1 << i)]


def list_to_mask(lst):
    m = 0
    for i in lst:
        m |= 1 << i
    return m


def set_process_affinity(mask):
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
    kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    if not kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)):
        err = ctypes.get_last_error() or ctypes.GetLastError()
        raise OSError(f"SetProcessAffinityMask failed for mask 0x{mask:x} (err={err})")


# ---------- Benchmark ----------

def run_benchmark(model_path, mask, threads, n_iters=400, warmup=30):
    set_process_affinity(mask)

    sess_options = ort.SessionOptions()
    sess_options.intra_op_num_threads = threads
    sess_options.inter_op_num_threads = threads
    session = ort.InferenceSession(
        model_path, providers=["CPUExecutionProvider"], sess_options=sess_options
    )
    input_name = session.get_inputs()[0].name

    img = np.random.rand(1, 3, 224, 224).astype(np.float32)

    for _ in range(warmup):
        session.run(None, {input_name: img})

    t0 = time.perf_counter()
    for _ in range(n_iters):
        session.run(None, {input_name: img})
    dt = time.perf_counter() - t0

    fps = n_iters / dt
    latency_ms = (dt / n_iters) * 1000
    return fps, latency_ms


def main():
    model_path = os.path.join(os.path.dirname(__file__), "models", "model.onnx")
    if not os.path.exists(model_path):
        print(f"Model not found: {model_path}")
        sys.exit(1)

    pe = detect_pe_cores()
    p_logical = pe["p_logical"]
    e_logical = pe["e_logical"]

    print("=" * 70)
    print("CPU topology")
    print("=" * 70)
    print(f"Total logical cores : {os.cpu_count()}")
    print(f"P-core logical IDs  : {p_logical}  ({len(p_logical)} threads)")
    print(f"E-core logical IDs  : {e_logical}  ({len(e_logical)} threads)")
    print(f"P-mask              : 0x{pe['p_mask']:x}")
    print(f"E-mask              : 0x{pe['e_mask']:x}")
    print()

    if not e_logical:
        print("No E-cores detected — homogeneous CPU. Test trivial. Exiting.")
        return

    all_mask = pe["p_mask"] | pe["e_mask"]

    n_p_phys = len(p_logical) // 2 if len(p_logical) > 0 else 0  # P-cores have HT

    p_phys_only_logical = p_logical[::2][:n_p_phys] if n_p_phys else p_logical
    p_phys_only_mask = list_to_mask(p_phys_only_logical)

    p_first_8_logical = p_logical[:8] if len(p_logical) >= 8 else p_logical
    p_first_8_mask = list_to_mask(p_first_8_logical)

    e_first_8_logical = e_logical[:8] if len(e_logical) >= 8 else e_logical
    e_first_8_mask = list_to_mask(e_first_8_logical)

    mix_8_logical = p_logical[:4] + e_logical[:4]
    mix_8_mask = list_to_mask(mix_8_logical)

    configs = [
        ("8 threads on P physical cores (no HT)",
         p_phys_only_mask, len(p_phys_only_logical)),
        ("8 threads on P logical (4P+HT)",
         p_first_8_mask, len(p_first_8_logical)),
        ("8 threads on E cores only",
         e_first_8_mask, len(e_first_8_logical)),
        ("8 threads mixed 4P + 4E",
         mix_8_mask, len(mix_8_logical)),
        (f"All P logical ({len(p_logical)} threads)",
         pe["p_mask"], len(p_logical)),
        (f"All cores ({len(p_logical) + len(e_logical)} threads — typical default)",
         all_mask, len(p_logical) + len(e_logical)),
        ("1 thread on a P core (single-thread baseline)",
         1 << p_logical[0], 1),
        ("1 thread on an E core (single-thread baseline)",
         1 << e_logical[0], 1),
    ]

    print("=" * 70)
    print("Benchmark (higher FPS = better; lower ms = better)")
    print("=" * 70)
    print(f"{'config':<55} {'fps':>7}  {'ms/inf':>8}")
    print("-" * 70)

    results = []
    for label, mask, threads in configs:
        if mask == 0 or threads == 0:
            continue
        try:
            fps, lat = run_benchmark(model_path, mask, threads)
            results.append((label, fps, lat))
            print(f"{label:<55} {fps:>7.1f}  {lat:>8.2f}")
        except Exception as e:
            print(f"{label:<55}  FAILED: {e}")

    print("-" * 70)
    if results:
        baseline = max(results, key=lambda r: r[1])
        print(f"\nFastest config: {baseline[0]} ({baseline[1]:.1f} fps)")
        print()
        print("Relative throughput (vs fastest):")
        for label, fps, _ in results:
            pct = fps / baseline[1] * 100
            bar = "#" * int(pct / 2)
            print(f"  {label:<55} {pct:>5.1f}% {bar}")

    set_process_affinity(list_to_mask(list(range(os.cpu_count() or 32))))


if __name__ == "__main__":
    main()
