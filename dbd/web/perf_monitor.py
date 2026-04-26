"""Live CPU + GPU performance metrics for the Performance Monitor tab.

GPU: shells out to nvidia-smi (no extra deps; ships with the NVIDIA driver).
CPU: uses psutil for utilization and frequency. CPU temperature and package
power are read through LibreHardwareMonitorLib.dll directly via pythonnet
(primary path — fast, no WMI/GUI needed) with a fallback to the WMI namespace
that LHM publishes when running externally as admin.
"""

import ctypes
import math
import os
import shutil
import subprocess
import sys
import threading
import time

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

# Own delta tracker for CPU %. We can't use psutil.cpu_percent(interval=None)
# because it mutates module-global cookies on every call — when multiple HTTP
# request threads (browser poll + manual probes) race through it, the second
# caller reads a cookie that was just bumped by the first and gets ~0 % back.
# Tracking deltas ourselves with a refresh window lets every caller see real
# values regardless of how often the endpoint is hit.
_CPU_LOCK = threading.Lock()
_CPU_PREV = None            # psutil.cpu_times()
_CPU_PREV_PERCPU = None     # list[psutil.cpu_times]
_CPU_PREV_T = 0.0
_CPU_BASELINE_REFRESH_S = 0.5


_NVIDIA_SMI = shutil.which("nvidia-smi")

# WMI fallback: PowerShell spawn is ~700ms per call so we cache aggressively.
_LHM_WMI_PROBED = False
_LHM_WMI_AVAILABLE = False
_LHM_WMI_CACHE = {}  # key -> (ts, value)
_LHM_TTL_SEC = 3.0

# Direct DLL backend (pythonnet → LibreHardwareMonitorLib.dll)
_LHM_DIRECT_TRIED = False
_LHM_DIRECT_OK = False
_LHM_DIRECT_REASON = None
_LHM_DIRECT_COMPUTER = None
_LHM_DIRECT_CPU_HW = None
_LHM_DIRECT_LAST = (0.0, None, None)  # (ts, temp_c, power_w)

# LibreHardwareMonitor.Hardware.SensorType enum
_LHM_SENSOR_POWER = 2
_LHM_SENSOR_TEMPERATURE = 4

GPU_QUERY_FIELDS = [
    "name",
    "temperature.gpu",
    "power.draw",
    "power.limit",
    "utilization.gpu",
    "utilization.memory",
    "memory.used",
    "memory.total",
    "fan.speed",
    "clocks.gr",
    "clocks.mem",
]


def _to_float(s):
    s = s.strip() if isinstance(s, str) else s
    if s is None or s == "" or (isinstance(s, str) and s.lower() in ("[n/a]", "n/a", "[not supported]")):
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    # Reject NaN/Inf — Flask's default jsonify will silently emit "NaN"/"Infinity"
    # which is not strict JSON and breaks JSON.parse on the client.
    if not math.isfinite(v):
        return None
    return v


# ─── GPU (nvidia-smi) ──────────────────────────────────────────────
_GPU_CACHE = {"ts": 0.0, "value": None}
_GPU_TTL_SEC = 0.4


def gpu_stats():
    if not _NVIDIA_SMI:
        return {"available": False, "reason": "nvidia-smi not on PATH"}

    now = time.monotonic()
    if _GPU_CACHE["value"] and now - _GPU_CACHE["ts"] < _GPU_TTL_SEC:
        return _GPU_CACHE["value"]

    try:
        out = subprocess.check_output(
            [_NVIDIA_SMI,
             f"--query-gpu={','.join(GPU_QUERY_FIELDS)}",
             "--format=csv,noheader,nounits"],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as e:
        # Cache the failure too — otherwise a stuck driver will let every
        # poll re-spawn nvidia-smi and burn 600ms × 2s for nothing.
        snap = {"available": False, "reason": f"nvidia-smi failed: {e}"}
        _GPU_CACHE["ts"] = now
        _GPU_CACHE["value"] = snap
        return snap

    line = out.splitlines()[0] if out else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < len(GPU_QUERY_FIELDS):
        return {"available": False, "reason": "unexpected nvidia-smi output"}

    snap = {
        "available": True,
        "name": parts[0],
        "temp_c": _to_float(parts[1]),
        "power_w": _to_float(parts[2]),
        "power_limit_w": _to_float(parts[3]),
        "util_gpu_pct": _to_float(parts[4]),
        "util_mem_pct": _to_float(parts[5]),
        "mem_used_mib": _to_float(parts[6]),
        "mem_total_mib": _to_float(parts[7]),
        "fan_pct": _to_float(parts[8]),
        "clock_gr_mhz": _to_float(parts[9]),
        "clock_mem_mhz": _to_float(parts[10]),
    }
    _GPU_CACHE["ts"] = now
    _GPU_CACHE["value"] = snap
    return snap


# ─── CPU (psutil + LHM backends) ───────────────────────────────────
def _is_admin():
    if not sys.platform.startswith("win"):
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _delta_pct(prev, curr):
    """Compute busy% from two psutil.cpu_times snapshots."""
    prev_all = sum(getattr(prev, f) for f in prev._fields)
    curr_all = sum(getattr(curr, f) for f in curr._fields)
    busy_d = (curr_all - curr.idle) - (prev_all - prev.idle)
    total_d = curr_all - prev_all
    if total_d <= 0:
        return 0.0
    return max(0.0, min(100.0, (busy_d / total_d) * 100.0))


def _read_cpu_pct():
    """(total_pct, [per_cpu_pct]) using our own delta tracker (race-safe)."""
    global _CPU_PREV, _CPU_PREV_PERCPU, _CPU_PREV_T
    with _CPU_LOCK:
        now = time.monotonic()
        curr_total = psutil.cpu_times()
        curr_percpu = psutil.cpu_times(percpu=True)

        # First call: prime the baseline, can't compute a delta yet.
        if _CPU_PREV is None:
            _CPU_PREV = curr_total
            _CPU_PREV_PERCPU = curr_percpu
            _CPU_PREV_T = now
            return (0.0, [0.0] * len(curr_percpu))

        pct_total = _delta_pct(_CPU_PREV, curr_total)
        pct_percpu = [_delta_pct(p, c) for p, c in zip(_CPU_PREV_PERCPU, curr_percpu)]

        # Refresh the baseline only every _CPU_BASELINE_REFRESH_S so rapid-fire
        # callers all see deltas vs. the same anchor instead of vs. each other.
        if now - _CPU_PREV_T >= _CPU_BASELINE_REFRESH_S:
            _CPU_PREV = curr_total
            _CPU_PREV_PERCPU = curr_percpu
            _CPU_PREV_T = now
        return (pct_total, pct_percpu)


def cpu_stats():
    """CPU utilization, frequency, and per-core utilization.
    Falls back gracefully if psutil isn't installed."""
    if not _PSUTIL:
        return {"available": False, "reason": "psutil not installed"}

    util_total, util_per = _read_cpu_pct()
    freq = psutil.cpu_freq()
    freq_now = freq.current if freq else None
    freq_max = freq.max if freq else None

    # Direct DLL is preferred (fast, no WMI dance). Falls back to LHM-via-WMI
    # if the direct path isn't available (DLL missing, pythonnet missing, or
    # this Python process isn't elevated).
    temp_c, power_w = _read_cpu_temp_power_direct()
    backend = "direct" if _LHM_DIRECT_OK else None
    if temp_c is None and power_w is None:
        wmi_temp = _read_cpu_temp_wmi()
        wmi_power = _read_cpu_power_wmi()
        if wmi_temp is not None or wmi_power is not None:
            temp_c = wmi_temp
            power_w = wmi_power
            backend = "wmi"

    return {
        "available": True,
        "util_pct": util_total,
        "util_per_core": util_per,
        "freq_mhz": freq_now,
        "freq_max_mhz": freq_max,
        "temp_c": temp_c,
        "power_w": power_w,
        "lhm_backend": backend,
        "lhm_admin": _is_admin(),
        "lhm_reason": _LHM_DIRECT_REASON if backend is None else None,
        "temp_power_hint": (
            None if (temp_c is not None or power_w is not None)
            else _hint_when_unavailable()
        ),
    }


def _hint_when_unavailable():
    if not sys.platform.startswith("win"):
        return "CPU temp/power require Windows + LibreHardwareMonitor."
    if not _is_admin():
        return ("Run this Flask server as Administrator to read CPU temp/power "
                "directly. Otherwise start LibreHardwareMonitor as admin and "
                "enable Options > Publish to WMI.")
    return ("LibreHardwareMonitorLib.dll not found and no LHM-WMI namespace "
            "available. Install LibreHardwareMonitor.")


# ─── Direct DLL backend (pythonnet) ────────────────────────────────
_LHM_DLL_CANDIDATES = [
    r"C:\Users\l\AppData\Local\Microsoft\WinGet\Packages\LibreHardwareMonitor.LibreHardwareMonitor_Microsoft.Winget.Source_8wekyb3d8bbwe\LibreHardwareMonitorLib.dll",
    r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
    r"C:\Program Files (x86)\LibreHardwareMonitor\LibreHardwareMonitorLib.dll",
]


def _find_lhm_dll():
    for p in _LHM_DLL_CANDIDATES:
        if os.path.exists(p):
            return p
    base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.isdir(base):
        for entry in os.listdir(base):
            if entry.startswith("LibreHardwareMonitor"):
                cand = os.path.join(base, entry, "LibreHardwareMonitorLib.dll")
                if os.path.exists(cand):
                    return cand
    return None


def _init_lhm_direct():
    global _LHM_DIRECT_TRIED, _LHM_DIRECT_OK, _LHM_DIRECT_REASON
    global _LHM_DIRECT_COMPUTER, _LHM_DIRECT_CPU_HW
    if _LHM_DIRECT_TRIED:
        return _LHM_DIRECT_OK
    _LHM_DIRECT_TRIED = True

    if not sys.platform.startswith("win"):
        _LHM_DIRECT_REASON = "non-Windows host"
        return False

    dll = _find_lhm_dll()
    if not dll:
        _LHM_DIRECT_REASON = "LibreHardwareMonitorLib.dll not found"
        return False

    try:
        sys.path.insert(0, os.path.dirname(dll))
        import clr  # pythonnet
        clr.AddReference(dll)
        from LibreHardwareMonitor.Hardware import Computer
    except Exception as e:
        _LHM_DIRECT_REASON = f"pythonnet/clr unavailable: {e.__class__.__name__}"
        return False

    try:
        c = Computer()
        c.IsCpuEnabled = True
        c.IsGpuEnabled = False
        c.IsMemoryEnabled = False
        c.IsMotherboardEnabled = False
        c.IsControllerEnabled = False
        c.IsStorageEnabled = False
        c.IsNetworkEnabled = False
        c.Open()
        cpu_hw = next(iter(c.Hardware), None)
        if cpu_hw is None:
            c.Close()
            _LHM_DIRECT_REASON = "no CPU sensor hardware reported by LHM"
            return False
        _LHM_DIRECT_COMPUTER = c
        _LHM_DIRECT_CPU_HW = cpu_hw
        _LHM_DIRECT_OK = True
        return True
    except Exception as e:
        _LHM_DIRECT_REASON = f"LHM init failed: {e}"
        return False


def _read_cpu_temp_power_direct():
    """Returns (temp_c, power_w) via direct LHM DLL. Cached for _LHM_TTL_SEC."""
    global _LHM_DIRECT_LAST
    if not _init_lhm_direct():
        return (None, None)
    now = time.monotonic()
    ts, t, p = _LHM_DIRECT_LAST
    if now - ts < _LHM_TTL_SEC:
        return (t, p)
    try:
        _LHM_DIRECT_CPU_HW.Update()
        temp = None
        power = None
        for s in _LHM_DIRECT_CPU_HW.Sensors:
            stype = int(s.SensorType)
            if s.Value is None:
                continue
            if stype == _LHM_SENSOR_TEMPERATURE and s.Name == "CPU Package":
                temp = float(s.Value)
            elif stype == _LHM_SENSOR_POWER and s.Name == "CPU Package":
                power = float(s.Value)
        _LHM_DIRECT_LAST = (now, temp, power)
        return (temp, power)
    except Exception:
        return (None, None)


# ─── WMI fallback (LHM published its namespace) ────────────────────
def _read_cpu_temp_wmi():
    if not sys.platform.startswith("win"):
        return None
    return _read_lhm_wmi_sensor("Temperature", "CPU Package")


def _read_cpu_power_wmi():
    if not sys.platform.startswith("win"):
        return None
    return _read_lhm_wmi_sensor("Power", "CPU Package")


def _probe_lhm_wmi_once():
    global _LHM_WMI_PROBED, _LHM_WMI_AVAILABLE
    if _LHM_WMI_PROBED:
        return _LHM_WMI_AVAILABLE
    _LHM_WMI_PROBED = True
    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Hardware "
                "-ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Name",
            ],
            text=True, timeout=3, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _LHM_WMI_AVAILABLE = bool(out.strip())
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        _LHM_WMI_AVAILABLE = False
    return _LHM_WMI_AVAILABLE


def _read_lhm_wmi_sensor(sensor_type, name_contains):
    if not _probe_lhm_wmi_once():
        return None

    cache_key = (sensor_type, name_contains)
    now = time.monotonic()
    cached = _LHM_WMI_CACHE.get(cache_key)
    if cached and now - cached[0] < _LHM_TTL_SEC:
        return cached[1]

    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor "
                f"-Filter \"SensorType='{sensor_type}'\" "
                f"| Where-Object {{ $_.Name -like '*{name_contains}*' }} "
                f"| Select-Object -First 1 -ExpandProperty Value",
            ],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        _LHM_WMI_CACHE[cache_key] = (now, None)
        return None
    val = _to_float(out)
    _LHM_WMI_CACHE[cache_key] = (now, val)
    return val


def perf_snapshot():
    return {
        "gpu": gpu_stats(),
        "cpu": cpu_stats(),
    }
