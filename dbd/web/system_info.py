"""Hardware capability detection — used by the Flask UI to show real
options for the device the user actually has, instead of fixed presets."""

import ctypes
import os
import platform
import sys


def detect_cpu():
    cores = os.cpu_count() or 4
    pe = detect_pe_cores()
    name = detect_cpu_name()
    return {
        "cores": cores,
        "name": name,
        "short_name": _short_cpu_name(name),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "p_threads": len(pe["p_logical"]),
        "e_threads": len(pe["e_logical"]),
        "p_physical": pe["p_physical"],
        "is_hybrid": pe["is_hybrid"],
        "cpu_summary": _build_cpu_summary(cores, pe, name),
    }


def detect_cpu_name():
    """Return the human-friendly CPU model name (e.g. 'Intel(R) Core(TM) i9-14900K').
    Falls back to platform.processor() / 'CPU' on non-Windows or failure."""
    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            try:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return value.strip()
            finally:
                winreg.CloseKey(key)
        except Exception:
            pass
    p = platform.processor()
    return p.strip() if p else "CPU"


def _short_cpu_name(name):
    """Compact label for the topbar chip. 'Intel(R) Core(TM) i9-14900K' -> 'i9-14900K'."""
    if not name:
        return "CPU"
    # Strip vendor/marketing prefixes
    cleaned = name
    for noise in ("Intel(R) ", "AMD ", "Core(TM) ", "Core ", "Processor", "CPU"):
        cleaned = cleaned.replace(noise, "")
    cleaned = cleaned.replace("  ", " ").strip(" -@")
    # Cut off freq trailers like "@ 3.20GHz"
    if "@" in cleaned:
        cleaned = cleaned.split("@")[0].strip()
    return cleaned or name


def _build_cpu_summary(cores, pe, name):
    short = _short_cpu_name(name)
    if pe["is_hybrid"]:
        return f"{short} · {pe['p_physical']}P+{len(pe['e_logical'])}E"
    return f"{short} · {cores} threads"


# ---------- Windows hybrid-CPU detection (P-cores vs E-cores) ----------

def detect_pe_cores():
    """Detect P/E cores on hybrid CPUs (Intel 12th gen+).
    Returns: p_logical, e_logical (lists of logical CPU indices),
             p_mask, e_mask (Windows affinity masks),
             p_physical (count of physical P-cores, accounting for HT),
             is_hybrid (bool).
    Falls back gracefully on non-Windows / older CPUs."""
    empty = {
        "p_logical": [], "e_logical": [],
        "p_mask": 0, "e_mask": 0,
        "p_physical": 0, "is_hybrid": False,
    }
    if not sys.platform.startswith("win"):
        return empty
    try:
        return _detect_pe_cores_windows()
    except Exception:
        return empty


def _detect_pe_cores_windows():
    from ctypes import wintypes

    ERROR_INSUFFICIENT_BUFFER = 122
    RelationProcessorCore = 0
    LTP_PC_SMT = 0x1  # Flag set when core is SMT (hyperthreaded)

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

    kernel32 = ctypes.windll.kernel32
    fn = kernel32.GetLogicalProcessorInformationEx
    fn.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    fn.restype = wintypes.BOOL

    length = wintypes.DWORD(0)
    fn(RelationProcessorCore, None, ctypes.byref(length))
    if ctypes.GetLastError() != ERROR_INSUFFICIENT_BUFFER:
        raise OSError("GetLogicalProcessorInformationEx initial sizing failed")

    buf = (ctypes.c_byte * length.value)()
    if not fn(RelationProcessorCore, buf, ctypes.byref(length)):
        raise OSError("GetLogicalProcessorInformationEx failed")

    cores = []  # [(eff_class, mask, is_smt)]
    offset = 0
    while offset < length.value:
        info = ctypes.cast(
            ctypes.addressof(buf) + offset,
            ctypes.POINTER(SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX),
        ).contents
        if info.Relationship == RelationProcessorCore:
            eff = int(info.u.Processor.EfficiencyClass)
            mask = int(info.u.Processor.GroupMask[0].Mask)
            is_smt = bool(info.u.Processor.Flags & LTP_PC_SMT)
            cores.append((eff, mask, is_smt))
        offset += info.Size

    if not cores:
        return {"p_logical": [], "e_logical": [], "p_mask": 0, "e_mask": 0,
                "p_physical": 0, "is_hybrid": False}

    eff_classes = sorted({c[0] for c in cores})
    is_hybrid = len(eff_classes) >= 2

    if not is_hybrid:
        all_mask = 0
        physical = len(cores)
        for _, m, _ in cores:
            all_mask |= m
        return {
            "p_logical": _mask_to_list(all_mask),
            "e_logical": [],
            "p_mask": all_mask,
            "e_mask": 0,
            "p_physical": physical,
            "is_hybrid": False,
        }

    p_class = eff_classes[-1]
    p_mask = 0
    e_mask = 0
    p_physical = 0
    for eff, mask, _smt in cores:
        if eff == p_class:
            p_mask |= mask
            p_physical += 1
        else:
            e_mask |= mask
    return {
        "p_logical": _mask_to_list(p_mask),
        "e_logical": _mask_to_list(e_mask),
        "p_mask": p_mask,
        "e_mask": e_mask,
        "p_physical": p_physical,
        "is_hybrid": True,
    }


def _mask_to_list(mask):
    return [i for i in range(64) if mask & (1 << i)]


def p_physical_affinity_mask(pe, n=None):
    """Mask covering one logical thread per physical P-core (no HT siblings).
    `n` limits the number of P-cores; defaults to all of them.
    Benchmark on 14900K: pinning to all 8 P-physical cores yields 980 fps
    vs 525 fps for 'all cores'."""
    if not pe["is_hybrid"] and pe["p_physical"] == 0:
        return 0
    p_logical = pe["p_logical"]
    n_phys = pe["p_physical"]
    if n is None:
        n = n_phys
    n = max(0, min(n, n_phys))
    if n == 0:
        return 0
    has_ht = len(p_logical) >= 2 * n_phys and n_phys > 0
    selected = (p_logical[::2][:n]) if has_ht else p_logical[:n]
    m = 0
    for idx in selected:
        m |= 1 << idx
    return m


def set_process_affinity(mask):
    """Pin the current process to the given affinity mask. Returns True on success.
    No-op + False on non-Windows or invalid mask."""
    if mask == 0 or not sys.platform.startswith("win"):
        return False
    try:
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
        kernel32.SetProcessAffinityMask.restype = wintypes.BOOL
        h = kernel32.GetCurrentProcess()
        return bool(kernel32.SetProcessAffinityMask(h, ctypes.c_size_t(mask)))
    except Exception:
        return False


# ---------- Adaptive presets ----------

def adaptive_cpu_presets(cores, pe=None):
    """Build CPU thread presets that scale with the actual CPU.
    On hybrid CPUs (Intel 12th gen+), generates multiple star-marked presets
    pinned to N physical P-cores (4, 6, all P), plus regular non-pinned
    presets for higher thread counts.
    Benchmark (i9-14900K, ONNX inference of the DBD model):
      - 8 threads pinned to P-physical: 980 fps
      - 32 threads no pinning (default): 525 fps  → 47 % slower
      - 8 threads mixed P+E:             195 fps  → 80 % slower"""
    if pe is None:
        pe = detect_pe_cores()

    base = _baseline_presets(cores)
    if not pe["is_hybrid"] or pe["p_physical"] <= 0:
        return [(label, threads, 0) for label, threads in base]

    # Build star-marked P-Core presets at sensible step sizes (<= p_physical),
    # always including the full-P preset.
    star_steps = []
    for n in (4, 6, pe["p_physical"]):
        if 2 <= n <= pe["p_physical"] and n not in star_steps:
            star_steps.append(n)
    star_presets = [
        (f"{n}t ★", n, p_physical_affinity_mask(pe, n))
        for n in star_steps
    ]

    # Filter baseline presets to those that ADD value over the star presets:
    # - drop entries with thread count <= the largest star step (they'd be
    #   strictly worse versions of the same workload)
    threshold = pe["p_physical"]
    higher_unpinned = [
        (label, threads, 0)
        for label, threads in base
        if threads > threshold
    ]
    return star_presets + higher_unpinned


def _baseline_presets(cores):
    """Adaptive presets — Max always == full core count, regardless of CPU size."""
    if cores <= 2:
        return [("Single", 1), ("Max", cores)]
    if cores <= 4:
        return [("Low", 1), ("Normal", 2), ("High", cores - 1), ("Max", cores)]
    if cores <= 6:
        return [("Low", 2), ("Normal", 3), ("High", cores - 1), ("Max", cores)]
    if cores <= 8:
        return [("Eco", 2), ("Low", 4), ("Normal", 6), ("Max", cores)]
    if cores <= 12:
        return [("Eco", 4), ("Low", 6), ("Normal", cores // 2), ("High", cores - 2), ("Max", cores)]
    # Large CPU (>= 13 logical): include 4 and 6 thread eco-tier for low-power scenarios
    return [
        ("Eco", 4),
        ("Low", 6),
        ("Normal", max(8, cores // 2)),
        ("High", max(12, int(cores * 0.75))),
        ("Max", cores),
    ]


def default_cpu_threads(cores, pe=None):
    """Default thread count for the UI. On hybrid CPUs, defaults to the
    full-P-Cores preset (last star entry) since it benchmarks ~2× faster.
    On non-hybrid CPUs, defaults to the second baseline preset."""
    if pe is None:
        pe = detect_pe_cores()
    presets = adaptive_cpu_presets(cores, pe)
    if pe["is_hybrid"] and pe["p_physical"] > 0:
        # Pick the star preset matching all P-cores
        for label, threads, mask in presets:
            if "★" in label and threads == pe["p_physical"]:
                return threads
    return presets[0][1]


# ---------- GPU detection ----------

def detect_gpu():
    """Detect available ONNX runtime providers and (best-effort) GPU device names.
    Never raises — missing libs degrade gracefully."""
    info = {
        "ort_providers": [],
        "cuda": {"available": False, "devices": []},
        "directml": {"available": False},
        "tensorrt": {"available": False},
        "torch_available": False,
        "gpu_summary": None,
    }

    try:
        import onnxruntime as ort
        info["ort_providers"] = list(ort.get_available_providers())
    except Exception as e:
        info["ort_error"] = str(e)
        return info

    if "DmlExecutionProvider" in info["ort_providers"]:
        info["directml"]["available"] = True

    try:
        import torch  # noqa: F401
        info["torch_available"] = True
        try:
            import torch as _torch
            if _torch.cuda.is_available():
                info["cuda"]["available"] = True
                count = _torch.cuda.device_count()
                info["cuda"]["devices"] = [
                    {"index": i, "name": _torch.cuda.get_device_name(i)} for i in range(count)
                ]
        except Exception as e:
            info["cuda"]["error"] = str(e)
    except ImportError:
        pass

    try:
        import tensorrt  # noqa: F401
        info["tensorrt"]["available"] = True
    except ImportError:
        pass

    if info["cuda"]["available"] and info["cuda"]["devices"]:
        primary = info["cuda"]["devices"][0]["name"]
        suffix = " (+TensorRT)" if info["tensorrt"]["available"] else ""
        info["gpu_summary"] = f"CUDA · {primary}{suffix}"
    elif info["directml"]["available"]:
        info["gpu_summary"] = "DirectML (Windows GPU)"
    elif "CUDAExecutionProvider" in info["ort_providers"]:
        info["gpu_summary"] = "CUDA (no torch — limited info)"
    else:
        info["gpu_summary"] = None

    return info


def gpu_unavailable_reason(gpu_info):
    """Why can't we use GPU? Returns a short hint string for the UI."""
    if gpu_info.get("gpu_summary"):
        return None
    if not gpu_info.get("torch_available"):
        return "Install PyTorch with CUDA support (or use DirectML on Windows)."
    providers = gpu_info.get("ort_providers", [])
    if "CUDAExecutionProvider" not in providers and "DmlExecutionProvider" not in providers:
        return "No GPU execution provider found. Install onnxruntime-gpu or onnxruntime-directml."
    return "GPU runtime detected but no usable device."
