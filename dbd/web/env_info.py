"""Environment/version inspection for the Info page.

Reports Python version, CUDA toolkit version (when detectable), NVIDIA driver
version, OS, and installed/missing state for the packages the project needs.
Uses importlib.metadata so we don't actually import optional heavy modules
(torch, tensorrt) — that would slow the page and pull GPU runtimes for nothing.
"""
from __future__ import annotations

import importlib.metadata as md
import os
import platform
import shutil
import subprocess
import sys
import time


# Cache the whole collect() result for a short window so repeatedly opening
# the Info page doesn't re-spawn nvidia-smi / nvcc / re-import torch.
_CACHE = {"ts": 0.0, "value": None}
_CACHE_TTL_S = 60.0


def _redact(p):
    """Replace the user's home directory with `~` so /api/info doesn't leak
    the OS username to the browser."""
    if not p:
        return p
    try:
        home = os.path.expanduser("~")
        if home and home in p:
            return p.replace(home, "~")
    except Exception:
        pass
    return p


# (display_name, dist_name, optional?, role)
REQUIRED_PACKAGES = [
    ("Flask",          "flask",          False, "web server"),
    ("NumPy",          "numpy",          False, "tensors / arrays"),
    ("OpenCV",         "opencv-python",  False, "image preprocessing"),
    ("MSS",            "mss",            False, "screen capture (cross-platform)"),
    ("Pillow",         "pillow",         False, "image encoding"),
    ("psutil",         "psutil",         False, "CPU monitor"),
    ("ONNX Runtime",   "onnxruntime",    True,  "AI inference (CPU)"),
    ("ONNX Runtime GPU","onnxruntime-gpu",True, "AI inference (CUDA)"),
    ("PyTorch",        "torch",          True,  "AI inference (alt.)"),
    ("TensorRT",       "tensorrt",       True,  "AI inference (NVIDIA)"),
    ("pywin32",        "pywin32",        True,  "Windows key sender"),
]


def _pkg_version(dist):
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None
    except Exception:
        return None


def _python_info():
    return {
        "version": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "executable": _redact(sys.executable),
        "bits": "64-bit" if sys.maxsize > 2**32 else "32-bit",
    }


def _os_info():
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    }


def _nvidia_info():
    """Driver + CUDA version reported by nvidia-smi. None on non-NVIDIA / no driver."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"available": False, "reason": "nvidia-smi not on PATH"}
    try:
        out = subprocess.check_output(
            [smi, "--query-gpu=driver_version,name", "--format=csv,noheader"],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as e:
        return {"available": False, "reason": f"nvidia-smi failed: {e}"}
    line = out.splitlines()[0] if out else ""
    parts = [p.strip() for p in line.split(",")] if line else []
    driver = parts[0] if len(parts) > 0 else None
    name = parts[1] if len(parts) > 1 else None

    cuda_runtime = None
    try:
        out2 = subprocess.check_output(
            [smi], text=True, timeout=2, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        for ln in out2.splitlines():
            if "CUDA Version" in ln:
                # "| NVIDIA-SMI 555.85   Driver Version: 555.85   CUDA Version: 12.5 |"
                tail = ln.split("CUDA Version:", 1)[-1].strip().rstrip("|").strip()
                cuda_runtime = tail.split()[0] if tail else None
                break
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        pass

    return {
        "available": True,
        "driver": driver,
        "gpu_name": name,
        "cuda_runtime": cuda_runtime,
    }


def _cuda_toolkit():
    """CUDA toolkit reported via env vars or nvcc, independent of driver."""
    home = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")
    nvcc = shutil.which("nvcc")
    version = None
    if nvcc:
        try:
            out = subprocess.check_output(
                [nvcc, "--version"], text=True, timeout=2, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for ln in out.splitlines():
                if "release" in ln.lower():
                    # "Cuda compilation tools, release 12.5, V12.5.40"
                    parts = ln.split("release")
                    if len(parts) > 1:
                        version = parts[1].split(",")[0].strip()
                        break
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
            pass
    return {
        "home": _redact(home),
        "nvcc_path": _redact(nvcc),
        "version": version,
    }


def _torch_cuda():
    """Whether torch was built with CUDA, reported by torch itself if installed."""
    if _pkg_version("torch") is None:
        return {"installed": False}
    try:
        import torch  # type: ignore
        return {
            "installed": True,
            "version": getattr(torch, "__version__", None),
            "cuda_built": bool(getattr(torch.version, "cuda", None)),
            "cuda_version": getattr(torch.version, "cuda", None),
            "cuda_available": bool(torch.cuda.is_available()),
        }
    except Exception as e:
        return {"installed": True, "error": str(e)}


def collect():
    now = time.monotonic()
    if _CACHE["value"] is not None and (now - _CACHE["ts"]) < _CACHE_TTL_S:
        return _CACHE["value"]

    pkgs = []
    for display, dist, optional, role in REQUIRED_PACKAGES:
        try:
            v = _pkg_version(dist)
        except Exception:
            v = None
        pkgs.append({
            "display_name": display,
            "dist": dist,
            "optional": optional,
            "role": role,
            "installed": v is not None,
            "version": v,
        })

    # Each sub-probe is wrapped — a single failure shouldn't blank the whole page.
    def _safe(fn, fallback):
        try:
            return fn()
        except Exception as e:
            return {**fallback, "error": str(e)}

    result = {
        "python": _safe(_python_info, {"version": None}),
        "os": _safe(_os_info, {"system": None}),
        "nvidia": _safe(_nvidia_info, {"available": False, "reason": "probe failed"}),
        "cuda_toolkit": _safe(_cuda_toolkit, {"home": None, "nvcc_path": None, "version": None}),
        "torch": _safe(_torch_cuda, {"installed": False}),
        "packages": pkgs,
    }
    _CACHE["ts"] = now
    _CACHE["value"] = result
    return result
