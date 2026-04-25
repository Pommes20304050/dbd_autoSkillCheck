"""Hardware capability detection — used by the Flask UI to show real
options for the device the user actually has, instead of fixed presets."""

import os
import platform


def detect_cpu():
    cores = os.cpu_count() or 4
    return {
        "cores": cores,
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def adaptive_cpu_presets(cores):
    """Build CPU thread presets that scale with the actual CPU.
    Goal: Low ~ idle-friendly, Normal ~ default, High ~ aggressive,
    Max ~ near-saturation but leaves at least 1 core for OS on big systems."""
    if cores <= 2:
        return [("Single", 1), ("All", cores)]
    if cores <= 4:
        return [("Low", 1), ("Normal", 2), ("High", cores - 1), ("Max", cores)]
    if cores <= 6:
        # Tighter spacing on 5-6 core CPUs so High != Max
        return [("Low", 2), ("Normal", 3), ("High", cores - 1), ("Max", cores)]
    if cores <= 8:
        return [("Low", 2), ("Normal", 4), ("High", 6), ("Max", cores)]
    # 9+ cores: leave 2 for OS at Max
    return [
        ("Low", max(2, cores // 4)),
        ("Normal", max(4, cores // 2)),
        ("High", max(6, int(cores * 0.75))),
        ("Max", max(8, cores - 2)),
    ]


def default_cpu_threads(cores):
    """Default to the 'Normal' preset (second entry) so the UI's seg-control has an active match."""
    presets = adaptive_cpu_presets(cores)
    if len(presets) >= 2:
        return presets[1][1]
    return presets[0][1]


def detect_gpu():
    """Detect available ONNX runtime providers and (best-effort) GPU device names.
    Never raises — missing libs degrade gracefully."""
    info = {
        "ort_providers": [],
        "cuda": {"available": False, "devices": []},
        "directml": {"available": False},
        "tensorrt": {"available": False},
        "torch_available": False,
        "gpu_summary": None,  # one human-readable line
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

    # Build the human-readable summary used by the UI
    if info["cuda"]["available"] and info["cuda"]["devices"]:
        primary = info["cuda"]["devices"][0]["name"]
        suffix = " (+TensorRT)" if info["tensorrt"]["available"] else ""
        info["gpu_summary"] = f"CUDA · {primary}{suffix}"
    elif info["directml"]["available"]:
        info["gpu_summary"] = "DirectML (Windows GPU)"
    elif "CUDAExecutionProvider" in info["ort_providers"]:
        info["gpu_summary"] = "CUDA (no torch — limited info)"
    else:
        info["gpu_summary"] = None  # GPU not available

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
