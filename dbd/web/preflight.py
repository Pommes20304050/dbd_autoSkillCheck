"""Preflight advisor — checks runtime dependencies and surfaces missing
packages / drivers / runtimes as banner messages in the UI.

Returns a list of issues, each with severity and a localizable code so the
frontend can render the message in the user's language. The list is sorted
by severity: danger > warn > info.

Cached for 30s — collecting calls importlib.metadata up to ~12 times and
optionally probes onnxruntime providers, which is too slow to repeat per poll.
"""
from __future__ import annotations

import importlib.metadata as md
import os
import shutil
import sys
import time

_CACHE = {"ts": 0.0, "base": None}
_CACHE_TTL = 30.0


def _pkg_installed(dist):
    try:
        return md.version(dist)
    except md.PackageNotFoundError:
        return None
    except Exception:
        return None


def _ort_providers():
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return None


def _collect_base():
    """Heavy probes — packages, providers, nvidia-smi presence. Cached."""
    base = {
        "py_major_minor": (sys.version_info.major, sys.version_info.minor),
        "is_windows": sys.platform.startswith("win"),
        "onnxruntime": _pkg_installed("onnxruntime"),
        "onnxruntime_gpu": _pkg_installed("onnxruntime-gpu"),
        "torch": _pkg_installed("torch"),
        "tensorrt": _pkg_installed("tensorrt"),
        "pycuda": _pkg_installed("pycuda"),
        "mss": _pkg_installed("mss"),
        "opencv": _pkg_installed("opencv-python"),
        "numpy": _pkg_installed("numpy"),
        "pillow": _pkg_installed("pillow"),
        "flask": _pkg_installed("flask"),
        "psutil": _pkg_installed("psutil"),
        "ort_providers": _ort_providers(),
        "nvidia_smi": shutil.which("nvidia-smi"),
        "models_folder_exists": os.path.isdir("models"),
        "models_folder_files": [],
    }

    if base["models_folder_exists"]:
        try:
            base["models_folder_files"] = sorted(
                f for f in os.listdir("models")
                if f.lower().endswith((".onnx", ".trt"))
            )
        except OSError:
            base["models_folder_files"] = []

    # Probe torch CUDA availability only if torch is installed (slow first call)
    base["torch_cuda_available"] = None
    if base["torch"] is not None:
        try:
            import torch
            base["torch_cuda_available"] = bool(torch.cuda.is_available())
        except Exception:
            base["torch_cuda_available"] = False

    return base


def _get_base():
    now = time.monotonic()
    if _CACHE["base"] is None or (now - _CACHE["ts"]) > _CACHE_TTL:
        _CACHE["base"] = _collect_base()
        _CACHE["ts"] = now
    return _CACHE["base"]


def invalidate_cache():
    _CACHE["base"] = None
    _CACHE["ts"] = 0.0


def _issue(code, severity, **fmt):
    """Build an issue dict. `code` is a stable i18n key; `fmt` provides
    placeholder values the frontend will splice into the translated string."""
    return {"code": code, "severity": severity, "fmt": fmt}


def collect_issues(device=None, model=None):
    """Return a list of issues for the given (optional) selected configuration.

    `device`         — "CPU" or "GPU" (the user's currently selected device)
    `model`          — selected model filename (".onnx" or ".trt")

    Both may be None — in that case only environment-wide issues are returned
    (still useful on first page-load before any selection happens).
    """
    base = _get_base()
    issues = []

    # ── Hard requirements (fail-fast: app cannot run without these) ──
    for dist, code in (
        ("flask", "preflight.missing.flask"),
        ("numpy", "preflight.missing.numpy"),
        ("opencv", "preflight.missing.opencv"),
        ("mss", "preflight.missing.mss"),
        ("pillow", "preflight.missing.pillow"),
        ("psutil", "preflight.missing.psutil"),
    ):
        if base[dist] is None:
            pkg = "opencv-python" if dist == "opencv" else dist
            issues.append(_issue(code, "danger", pkg=pkg))

    # ── ONNX Runtime ──
    has_ort = base["onnxruntime"] is not None or base["onnxruntime_gpu"] is not None
    if not has_ort:
        issues.append(_issue("preflight.missing.onnxruntime", "danger"))

    # ── Models folder / files ──
    if not base["models_folder_exists"]:
        issues.append(_issue("preflight.models.folderMissing", "danger"))
    elif not base["models_folder_files"]:
        issues.append(_issue("preflight.models.empty", "danger"))

    # ── Selected-model presence ──
    if model:
        if model not in base["models_folder_files"]:
            issues.append(_issue("preflight.models.notFound", "danger", model=model))
        elif model.lower().endswith(".trt"):
            # TensorRT model implies extra requirements
            if base["torch"] is None:
                issues.append(_issue("preflight.trt.needsTorch", "danger"))
            if base["tensorrt"] is None:
                issues.append(_issue("preflight.trt.needsTensorrt", "danger"))
            if base["pycuda"] is None:
                issues.append(_issue("preflight.trt.needsPycuda", "danger"))

    # ── GPU device selected — verify the GPU stack is actually usable ──
    # Note: PyTorch is NOT required for ONNX GPU inference. It's only needed
    # for TensorRT (.trt) models, which is checked separately above.
    if device == "GPU":
        providers = base["ort_providers"] or []
        has_gpu_ep = any(p in providers for p in ("CUDAExecutionProvider",
                                                  "DmlExecutionProvider",
                                                  "TensorrtExecutionProvider"))
        if not has_gpu_ep:
            if base["onnxruntime"] is not None and base["onnxruntime_gpu"] is None:
                # User has CPU-only ORT — needs the GPU build
                issues.append(_issue("preflight.gpu.needsOrtGpu", "warn"))
            elif providers is None:
                # ort itself unimportable — already covered by missing.onnxruntime
                pass
            else:
                issues.append(_issue("preflight.gpu.noProvider", "warn"))

    # ── Optional/info-level checks ──
    if base["nvidia_smi"] is None and (base["onnxruntime_gpu"] is not None
                                       or base["torch_cuda_available"]):
        # Likely NVIDIA system but nvidia-smi not on PATH → perf monitor will be blank
        issues.append(_issue("preflight.nvidiaSmi.missing", "info"))

    py_major, py_minor = base["py_major_minor"]
    if py_major != 3 or py_minor < 10 or py_minor > 12:
        issues.append(_issue("preflight.python.versionUntested", "info",
                             version=f"{py_major}.{py_minor}"))

    # ── Sort by severity (danger first), preserving input order within a tier ──
    SEV_ORDER = {"danger": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: SEV_ORDER.get(i["severity"], 9))
    return issues


def build_advice(device=None, model=None):
    """Return a payload ready for /api/preflight: list + summary severity."""
    issues = collect_issues(device=device, model=model)
    if not issues:
        summary = "ok"
    else:
        # Highest severity wins
        if any(i["severity"] == "danger" for i in issues):
            summary = "danger"
        elif any(i["severity"] == "warn" for i in issues):
            summary = "warn"
        else:
            summary = "info"
    return {"summary": summary, "issues": issues}
