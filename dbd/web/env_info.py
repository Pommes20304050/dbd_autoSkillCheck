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
    ("BetterCam",      "bettercam",      True,  "fast Windows screen capture"),
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
        "executable": sys.executable,
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
        "home": home,
        "nvcc_path": nvcc,
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
    pkgs = []
    for display, dist, optional, role in REQUIRED_PACKAGES:
        v = _pkg_version(dist)
        pkgs.append({
            "display_name": display,
            "dist": dist,
            "optional": optional,
            "role": role,
            "installed": v is not None,
            "version": v,
        })

    return {
        "python": _python_info(),
        "os": _os_info(),
        "nvidia": _nvidia_info(),
        "cuda_toolkit": _cuda_toolkit(),
        "torch": _torch_cuda(),
        "packages": pkgs,
    }
