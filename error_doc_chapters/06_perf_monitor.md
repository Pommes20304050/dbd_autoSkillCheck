# Chapter 6 — Performance Monitor Errors

The Performance Monitor tab in `dbd_autoSkillCheck` surfaces live CPU and GPU telemetry by stitching together three very different data sources: `psutil` (cross-platform), `nvidia-smi` (NVIDIA driver shell-out), and LibreHardwareMonitor (LHM) accessed either directly through `pythonnet`/`clr` or as a fallback via WMI/PowerShell. Each layer has its own failure modes — missing executables, locale-sensitive parsing, NaN/Inf leaking into JSON, admin-token requirements, multi-GPU ambiguity, processor groups on >64-core boxes, and stale TTL caches that hide real failures. This chapter enumerates every observed and reasonably foreseeable error path in `dbd/web/perf_monitor.py`, with triggers, root causes, fixes, and hardening notes.

All line references are against `dbd/web/perf_monitor.py` as currently committed.

---

## E.PRF.001 — psutil missing / failed import
**Trigger:** `import psutil` raises `ImportError` at module load.
**Where:** perf_monitor.py:19-23
**What it means (plain English):** The `psutil` wheel is not installed in the active interpreter, so the module degrades to a stub that returns `{"available": False, "reason": "psutil not installed"}`.
**Symptoms:** CPU panel shows "psutil not installed"; per-core bars empty; frequency missing; GPU panel may still work.
**Root cause(s):** Missing dependency; wrong virtualenv activated; psutil wheel for the current Python ABI not available; corporate proxy blocked the install.
**How to fix:**
1. `pip install psutil` inside the active venv.
2. Verify with `python -c "import psutil; print(psutil.__version__)"`.
3. On Python 3.13 / pre-release Pythons, install from source if no wheel: `pip install --no-binary :all: psutil`.
**Prevention / hardening:** Pin `psutil` in `requirements.txt`; add a smoke test that asserts `_PSUTIL` is `True` on CI.
**Related:** E.PRF.002, E.PRF.029.

## E.PRF.002 — psutil.cpu_percent first-call returns 0 (interval=None gotcha)
**Trigger:** Calling `psutil.cpu_percent(interval=None)` before the module has primed its internal cookie.
**Where:** perf_monitor.py:25-30 (comment), 162-186
**What it means (plain English):** `psutil.cpu_percent` with `interval=None` returns the delta since the previous call. The first call has no previous baseline, so it always returns 0.0. The author worked around it with a custom delta tracker.
**Symptoms:** First sample after server start reads 0% CPU even on a busy box; per-core bars all flatline once.
**Root cause(s):** psutil's documented behavior; cookie is process-global and mutated on every call.
**How to fix:**
1. The current code already returns `(0.0, [0.0]*N)` on the very first call (line 175) — accept the zero or discard the first sample on the client.
2. Alternatively, prime once at startup with a throwaway `_read_cpu_pct()`.
**Prevention / hardening:** Document the prime-then-poll contract; UI can hide samples until the second tick.
**Related:** E.PRF.029, E.PRF.039.

## E.PRF.003 — Race between concurrent psutil.cpu_percent callers
**Trigger:** Multiple HTTP threads (browser poll + manual probes) call `psutil.cpu_percent(interval=None)` near-simultaneously.
**Where:** perf_monitor.py:25-30 (the documented reason for the custom tracker)
**What it means (plain English):** psutil shares one module-global cookie. Thread A bumps it, then Thread B reads against the just-updated cookie and sees ~0%.
**Symptoms:** Random 0% spikes in the CPU chart whenever two clients are watching at once.
**Root cause(s):** Shared mutable state in psutil internals.
**How to fix:** Already mitigated — the file uses `_CPU_LOCK` + its own delta tracker that refreshes only every `_CPU_BASELINE_REFRESH_S` (0.5s).
**Prevention / hardening:** Never call `psutil.cpu_percent(interval=None)` directly elsewhere in the codebase — always go through `_read_cpu_pct()`.
**Related:** E.PRF.002, E.PRF.039.

## E.PRF.004 — Per-CPU bar count desync on hotplug / set-affinity
**Trigger:** A core is offlined, onlined, or affinity changes between two `psutil.cpu_times(percpu=True)` calls.
**Where:** perf_monitor.py:178 (`zip(_CPU_PREV_PERCPU, curr_percpu)`)
**What it means (plain English):** `zip` silently truncates to the shorter list. If core count changes, the per-core array shrinks/grows mid-flight and bars desync.
**Symptoms:** Per-core array length changes between snapshots; UI bars flicker or disappear; in extreme cases an `IndexError` if downstream code indexes by fixed N.
**Root cause(s):** Hotplug, VM resize, Windows processor-group churn.
**How to fix:**
1. On length mismatch, reset the baseline (`_CPU_PREV_PERCPU = curr_percpu`) and return zeros for that tick.
2. Detect with `len(_CPU_PREV_PERCPU) != len(curr_percpu)` before the `zip`.
**Prevention / hardening:** Log when core count changes; expose the count in the snapshot so the client can re-render.
**Related:** E.PRF.020, E.PRF.030.

## E.PRF.005 — nvidia-smi missing on PATH
**Trigger:** `shutil.which("nvidia-smi")` returns `None` at import time.
**Where:** perf_monitor.py:38, 94-95
**What it means (plain English):** Either there is no NVIDIA GPU, the driver is broken, or `nvidia-smi.exe` is in a folder not on `PATH` (e.g. an old DCH-installed driver where the binary lives under `C:\Windows\System32` only for the SYSTEM user).
**Symptoms:** GPU panel shows `available=False, reason="nvidia-smi not on PATH"`.
**Root cause(s):** AMD/Intel-only system; driver not installed; PATH not refreshed after driver install; running under a service account with a stripped PATH.
**How to fix:**
1. Add `C:\Program Files\NVIDIA Corporation\NVSMI` (or `System32`) to PATH.
2. Or hard-code `_NVIDIA_SMI = r"C:\Windows\System32\nvidia-smi.exe"` as a fallback.
3. Reinstall the GPU driver.
**Prevention / hardening:** Re-probe `shutil.which` on every call instead of caching at import — drivers can be installed at runtime.
**Related:** E.PRF.006, E.PRF.011.

## E.PRF.006 — nvidia-smi TimeoutExpired (2s)
**Trigger:** `subprocess.check_output(..., timeout=2)` raises `TimeoutExpired`.
**Where:** perf_monitor.py:102-115
**What it means (plain English):** `nvidia-smi` did not return within 2 seconds. Common when the driver is hung, the GPU is in a deep low-power state, or a kernel is blocking the queue.
**Symptoms:** GPU panel reports `nvidia-smi failed: Command ... timed out after 2 seconds`; failure cached for `_GPU_TTL_SEC` (0.4s).
**Root cause(s):** TDR in progress, MIG re-config, contended GPU under heavy compute, faulty driver.
**How to fix:**
1. Restart the NVIDIA Display Container service.
2. Update the driver.
3. Increase the timeout (it's already conservative at 2s).
**Prevention / hardening:** The code already caches the failure (line 113-114) so it doesn't re-spawn nvidia-smi for every poll.
**Related:** E.PRF.005, E.PRF.011.

## E.PRF.007 — CSV parse failure on locale (decimal comma)
**Trigger:** `nvidia-smi` outputs `"45,3"` instead of `"45.3"` because Windows is set to a German/French/etc. locale.
**Where:** perf_monitor.py:73-85 (`_to_float`)
**What it means (plain English):** `float("45,3")` raises `ValueError`, `_to_float` returns `None`, the field becomes a missing value.
**Symptoms:** Random fields show as `null` (temp, power, mem) on non-en-US Windows; UI shows `--`.
**Root cause(s):** `nvidia-smi` historically respects the system decimal separator on some driver versions.
**How to fix:**
1. Force locale: invoke with `env={"LC_ALL": "C", **os.environ}`.
2. Replace `,` with `.` in `_to_float` before `float()`.
3. Update the driver — recent versions emit `.` regardless of locale.
**Prevention / hardening:** Add `s = s.replace(",", ".")` inside `_to_float` for defense in depth.
**Related:** E.PRF.014, E.PRF.025.

## E.PRF.008 — `nvidia-smi` reports CUDA Version that's the driver-bundled API, not the toolkit
**Trigger:** A user reads "CUDA Version: 12.6" from `nvidia-smi` and assumes the CUDA Toolkit is installed.
**Where:** Not parsed here, but commonly confused given the GPU panel labels.
**What it means (plain English):** `nvidia-smi` shows the highest CUDA runtime that the *driver* supports — it does not mean a Toolkit is installed.
**Symptoms:** `nvcc --version` fails even though the GPU panel "shows CUDA 12.6"; PyTorch CUDA wheels still mismatch.
**Root cause(s):** UX ambiguity in the NVIDIA tool itself.
**How to fix:** Don't rely on `nvidia-smi`'s CUDA Version for toolkit detection; check `nvcc` or `torch.version.cuda`.
**Prevention / hardening:** If the project later adds a CUDA badge, query `nvcc --version` separately.
**Related:** E.PRF.005.

## E.PRF.009 — Multi-GPU systems pick GPU 0 (might be the iGPU / wrong card)
**Trigger:** Laptop with NVIDIA dGPU + Intel iGPU, or workstation with multiple NVIDIA cards.
**Where:** perf_monitor.py:117 (`out.splitlines()[0]`)
**What it means (plain English):** Code reads only the *first* CSV line. On multi-GPU systems, `nvidia-smi` enumerates all NVIDIA GPUs and the first one may be the headless / unused card.
**Symptoms:** Numbers don't match the active gaming/inference GPU; utilization stuck at 0% while the other card is at 100%.
**Root cause(s):** Implicit "GPU 0" assumption.
**How to fix:**
1. Add `--id=<n>` to the `nvidia-smi` query, or `index` to the field list and let the user pick.
2. Pick the GPU with highest utilization across all rows.
**Prevention / hardening:** Surface a GPU selector in the UI when `len(out.splitlines()) > 1`.
**Related:** E.PRF.010.

## E.PRF.010 — Optimus / NVIDIA dGPU sleeping reads util as 0
**Trigger:** Laptop with Optimus where the NVIDIA card is currently parked in P8 / D3 idle.
**Where:** perf_monitor.py:122-138
**What it means (plain English):** The dGPU is power-gated. `nvidia-smi` still answers but reports near-zero util, idle clocks, and sometimes `[N/A]` for fan/temp.
**Symptoms:** GPU shows 0% even when running games (because Optimus routes display through the iGPU and the dGPU is asleep).
**Root cause(s):** Hybrid graphics power management.
**How to fix:**
1. Force the app/game onto the dGPU via NVIDIA Control Panel or `NVIDIA_VISIBLE_DEVICES`.
2. Treat `[N/A]` as "GPU asleep" rather than "broken".
**Prevention / hardening:** Display a "GPU sleeping" badge when temp + util + fan are all 0/None.
**Related:** E.PRF.009, E.PRF.026.

## E.PRF.011 — Unexpected nvidia-smi output (column count mismatch)
**Trigger:** `len(parts) < len(GPU_QUERY_FIELDS)` after CSV split.
**Where:** perf_monitor.py:119-120
**What it means (plain English):** Fewer comma-separated fields than queried. Old driver, virtual GPU (vGPU), or a passthrough quirk dropped one or more fields.
**Symptoms:** GPU panel shows `available=False, reason="unexpected nvidia-smi output"`.
**Root cause(s):** Driver version too old for one of the requested fields (e.g. `power.limit` on Quadro cards from 2014); GRID/vGPU.
**How to fix:**
1. Drop the offending field from `GPU_QUERY_FIELDS`.
2. Probe each field individually on first run and disable unsupported ones.
**Prevention / hardening:** Defensively pad `parts` to length on parse: `parts += [""] * (len(GPU_QUERY_FIELDS) - len(parts))`.
**Related:** E.PRF.005, E.PRF.027.

## E.PRF.012 — LHM via pythonnet missing DLL path
**Trigger:** `_find_lhm_dll()` returns `None` because LibreHardwareMonitor isn't installed in any of the candidate locations.
**Where:** perf_monitor.py:243-261, 275-278
**What it means (plain English):** The DLL backend can't initialize without `LibreHardwareMonitorLib.dll`.
**Symptoms:** `lhm_reason: "LibreHardwareMonitorLib.dll not found"`; CPU temp/power show `null`; UI hint asks user to install LHM.
**Root cause(s):** LHM not installed; installed to a non-standard location not in `_LHM_DLL_CANDIDATES`.
**How to fix:**
1. Install LibreHardwareMonitor (winget install LibreHardwareMonitor.LibreHardwareMonitor).
2. Or symlink/copy the DLL into one of the candidate paths.
3. Add a custom path to `_LHM_DLL_CANDIDATES`.
**Prevention / hardening:** Read an env var (`DBD_LHM_DLL`) for an explicit override path.
**Related:** E.PRF.013, E.PRF.018.

## E.PRF.013 — LHM needs Admin / process not elevated
**Trigger:** LHM is installed but `_init_lhm_direct()` succeeds while `c.Open()` returns sensors with `s.Value is None` for everything.
**Where:** perf_monitor.py:289-310, 142-148 (`_is_admin`)
**What it means (plain English):** LHM reads MSRs and SMBus. Without admin / `SeSystemEnvironmentPrivilege`, the sensor objects exist but their values stay `None`.
**Symptoms:** `lhm_admin: false`, `temp_c: null`, `power_w: null`, hint "Run this Flask server as Administrator…"; per-core util fine.
**Root cause(s):** Standard user token; UAC limited.
**How to fix:**
1. Right-click → "Run as administrator" on the launcher script / cmd.
2. Or run LibreHardwareMonitor.exe as admin with "Publish to WMI" enabled and let the WMI fallback handle it.
**Prevention / hardening:** Surface the elevation hint prominently when `lhm_admin=false` and values are `None`.
**Related:** E.PRF.012, E.PRF.015.

## E.PRF.014 — `clr` import on non-Windows
**Trigger:** Module imported on Linux/macOS, `_init_lhm_direct` reaches `import clr`.
**Where:** perf_monitor.py:271-273, 282
**What it means (plain English):** Even though the early `sys.platform.startswith("win")` guard exists at line 271, the module also tries `import clr` later. On non-Windows, `clr` either is missing or imports a different package (Python's `clr` namespace clash).
**Symptoms:** On Linux: `_LHM_DIRECT_REASON = "non-Windows host"` (well-handled); CPU temp/power simply unavailable.
**Root cause(s):** pythonnet is Windows-leaning; the `clr` PyPI namespace conflict.
**How to fix:** Already handled — the platform guard short-circuits before `clr` is touched. Keep it that way; never move the import outside the guard.
**Prevention / hardening:** Add a unit test that imports `perf_monitor` cleanly on Linux CI.
**Related:** E.PRF.024.

## E.PRF.015 — LHM WMI namespace missing if "Publish to WMI" disabled
**Trigger:** LibreHardwareMonitor.exe is running but its Options → Publish to WMI checkbox is off.
**Where:** perf_monitor.py:353-371
**What it means (plain English):** The probe `Get-CimInstance -Namespace root/LibreHardwareMonitor` returns nothing; `_LHM_WMI_AVAILABLE` becomes `False`.
**Symptoms:** WMI fallback never returns values; both backends report unavailable.
**Root cause(s):** Default LHM install does not publish to WMI.
**How to fix:**
1. In LHM: Options → Publish to WMI → enable.
2. Restart LibreHardwareMonitor as Administrator.
**Prevention / hardening:** Update the user hint to mention this exact menu path (it already does at line 235-237).
**Related:** E.PRF.013, E.PRF.016.

## E.PRF.016 — WMI permissions error
**Trigger:** `Get-CimInstance` raises an Access Denied that gets swallowed by `-ErrorAction SilentlyContinue` or by the `except` block.
**Where:** perf_monitor.py:358-371, 384-398
**What it means (plain English):** The current user lacks DCOM/WMI rights to the LHM namespace.
**Symptoms:** Probe silently fails; appears identical to "LHM not running"; cached as unavailable.
**Root cause(s):** GPO restrictions; non-admin user; corrupted WMI repository.
**How to fix:**
1. Run the Flask server as admin.
2. Repair WMI: `winmgmt /verifyrepository`, then `/salvagerepository` if needed.
3. Add the user to the WMI Control Properties → Security tab for that namespace.
**Prevention / hardening:** Promote stderr from PowerShell instead of `DEVNULL` for one diagnostic call to surface the real error to logs.
**Related:** E.PRF.015, E.PRF.034.

## E.PRF.017 — NaN/Inf reaching json.dumps (math.isfinite check)
**Trigger:** `nvidia-smi` or LHM returns `nan` / `inf` for a sensor (sensor disconnected mid-poll).
**Where:** perf_monitor.py:81-85 (`_to_float`)
**What it means (plain English):** Python's `float("nan")` succeeds. Flask's default `jsonify` emits the literal token `NaN`/`Infinity` which is not strict JSON; browsers' `JSON.parse` rejects it.
**Symptoms:** Frontend gets a parse error and the entire perf snapshot disappears, not just the bad field.
**Root cause(s):** Sensor glitch; division-by-zero in driver math; partial sensor init.
**How to fix:** Already mitigated by the `math.isfinite(v)` reject at line 83-84 — `_to_float` returns `None` instead.
**Prevention / hardening:** Apply the same `isfinite` filter to any direct LHM `s.Value` reads (lines 331, 333) before converting.
**Related:** E.PRF.007, E.PRF.025.

## E.PRF.018 — gpu_stats failure caching TTL semantics
**Trigger:** First successful `nvidia-smi` call returns within `_GPU_TTL_SEC=0.4s` of a *previous failure cache*.
**Where:** perf_monitor.py:89-99, 110-115
**What it means (plain English):** The failure path caches `{"available": False, ...}` *and* sets `ts`, so the next 0.4s of polls return the failure even after the driver recovers.
**Symptoms:** GPU panel sticks on "unavailable" for ~400ms after the underlying problem is resolved.
**Root cause(s):** Same TTL is used for both success and failure caches.
**How to fix:**
1. Use a shorter TTL (e.g. 0.1s) for failures so recovery is fast.
2. Or invalidate the cache when `available` flips.
**Prevention / hardening:** Add a `_GPU_FAIL_TTL_SEC` constant and branch on success vs failure.
**Related:** E.PRF.005, E.PRF.006, E.PRF.040.

## E.PRF.019 — `_to_float` on stringified values with comma decimals
**Trigger:** WMI on German Windows returns a `Value` like `"56,2"`.
**Where:** perf_monitor.py:73-85, 399
**What it means (plain English):** `_to_float("56,2")` → `None`. Same locale issue as E.PRF.007 but coming through the WMI/PowerShell pipeline.
**Symptoms:** `temp_c`/`power_w` from WMI fallback always `None` on de-DE/fr-FR locales.
**Root cause(s):** PowerShell formats floats per `Get-Culture`.
**How to fix:**
1. In the PS pipeline, append `| ForEach-Object { $_.ToString([System.Globalization.CultureInfo]::InvariantCulture) }`.
2. Or pre-process in Python: `s = s.replace(",", ".")` inside `_to_float`.
**Prevention / hardening:** Set `[System.Threading.Thread]::CurrentThread.CurrentCulture = 'en-US'` at the start of every PS one-liner.
**Related:** E.PRF.007, E.PRF.025.

## E.PRF.020 — CPU package power not exposed by older LHM versions
**Trigger:** LHM ≤ 0.9.2 on certain AMD Ryzen pre-Zen2 platforms simply doesn't enumerate a "CPU Package" power sensor.
**Where:** perf_monitor.py:330-333
**What it means (plain English):** The loop only matches `s.Name == "CPU Package"`. Older builds may name it "Package", "CPU Cores", or split rails.
**Symptoms:** `temp_c` populated, `power_w` always `null`.
**Root cause(s):** Sensor-naming churn between LHM versions.
**How to fix:**
1. Match `"Package" in s.Name` or fall back to summing per-core power.
2. Update LibreHardwareMonitor to the latest release.
**Prevention / hardening:** Log the full set of `(SensorType, Name, Value)` once at init for diagnosis.
**Related:** E.PRF.013, E.PRF.033.

## E.PRF.021 — Per-core util on >64 cores (Windows processor groups)
**Trigger:** Threadripper / Xeon system with more than 64 logical cores.
**Where:** perf_monitor.py:168, 178
**What it means (plain English):** Windows splits >64 cores into "processor groups". `psutil.cpu_times(percpu=True)` may return only the cores in the *current* group depending on how the process is bound.
**Symptoms:** Per-core array length = 64 on a 96-core box; the other 32 cores invisible.
**Root cause(s):** Windows processor-group affinity; the host process is single-group by default.
**How to fix:**
1. Set affinity across all groups via `SetProcessAffinityMask`/`SetThreadGroupAffinity` (advanced).
2. Read per-NUMA-node counters via `wmic` or PDH instead.
**Prevention / hardening:** Display a warning if `psutil.cpu_count(logical=True)` differs from `len(util_per)`.
**Related:** E.PRF.004, E.PRF.030.

## E.PRF.022 — Refresh interval 600ms vs interval=None first-call
**Trigger:** Client polls at 600ms; backend baseline refresh is 500ms. Misaligned ticks return slightly different deltas every other poll.
**Where:** perf_monitor.py:35, 182
**What it means (plain English):** `_CPU_BASELINE_REFRESH_S=0.5` means the baseline rotates every 500ms. Polls landing 100ms after the rotation see a different anchor than polls landing 100ms before.
**Symptoms:** CPU% chart jitters with a regular rhythm; appears as "saw-tooth" noise.
**Root cause(s):** TTL/poll-interval mismatch.
**How to fix:**
1. Align poll interval to a multiple of the baseline (e.g. 500ms or 250ms).
2. Or shrink `_CPU_BASELINE_REFRESH_S` to e.g. 0.25.
**Prevention / hardening:** Document the relationship and surface both knobs.
**Related:** E.PRF.002, E.PRF.039.

## E.PRF.023 — GPU temp sensor returns 0 on idle
**Trigger:** Some laptop GPUs report `temperature.gpu = 0` when in deep idle / fan-off.
**Where:** perf_monitor.py:125
**What it means (plain English):** `_to_float("0")` is a valid finite zero, not `None`. UI shows 0°C even though the sensor is just unavailable.
**Symptoms:** Temperature dial pegged at 0; suspicious during light load.
**Root cause(s):** Vendor firmware reports 0 instead of `[N/A]` when the sensor is gated.
**How to fix:**
1. Treat `temp_c < 5` as "GPU sleeping" in UI rendering.
2. Cross-check with util — if util is also 0 and temp is 0, mark as parked.
**Prevention / hardening:** Add a `gpu_parked: bool` derived field server-side.
**Related:** E.PRF.010, E.PRF.024.

## E.PRF.024 — Fan speed 0% on liquid-cooled GPUs / passive cards
**Trigger:** AIO-cooled or passively-cooled GPU; `nvidia-smi` returns `[N/A]` or `0` for `fan.speed`.
**Where:** perf_monitor.py:132
**What it means (plain English):** Cards without a controllable fan don't advertise one.
**Symptoms:** Fan dial reads 0% even at full load — alarms users into thinking the cooler died.
**Root cause(s):** Hardware design; correctly reported as not-applicable.
**How to fix:**
1. If `fan_pct is None`, hide the fan widget.
2. Display "passive" / "AIO" badge instead of 0%.
**Prevention / hardening:** Distinguish `[N/A]` (sensor missing) from `0` (sensor present, fan off).
**Related:** E.PRF.023, E.PRF.027.

## E.PRF.025 — Memory utilization vs frame buffer confusion
**Trigger:** UI labels `util_mem_pct` and `mem_used_mib` interchangeably.
**Where:** perf_monitor.py:129-131
**What it means (plain English):** `utilization.memory` from `nvidia-smi` is the percentage of *time* the memory controller was active — not the percentage of VRAM used. `memory.used / memory.total` is the actual VRAM occupancy.
**Symptoms:** "Memory" gauge sometimes diverges wildly from "VRAM Used / Total" — users assume one of them is broken.
**Root cause(s):** NVIDIA's two distinct memory metrics share the word "memory".
**How to fix:**
1. Rename `util_mem_pct` to `mem_controller_pct` in the UI.
2. Rename or co-locate the two so the distinction is obvious.
**Prevention / hardening:** Add a tooltip explaining the difference.
**Related:** E.PRF.027.

## E.PRF.026 — Driver crash during nvidia-smi causes CalledProcessError
**Trigger:** `nvidia-smi` returns non-zero exit (driver TDR, license server unreachable on vGPU).
**Where:** perf_monitor.py:109
**What it means (plain English):** `subprocess.check_output` raises `CalledProcessError`, caught and cached as failure.
**Symptoms:** GPU panel reports `nvidia-smi failed: Command returned non-zero exit status N`.
**Root cause(s):** TDR; vGPU license expired; driver mismatch.
**How to fix:**
1. Check Event Viewer for nvlddmkm errors.
2. Reinstall driver clean (DDU + fresh install).
3. For vGPU, verify the license server.
**Prevention / hardening:** Surface stderr from nvidia-smi to logs (currently silenced via `stderr=DEVNULL`).
**Related:** E.PRF.006, E.PRF.018.

## E.PRF.027 — `[Not Supported]` markers in nvidia-smi output
**Trigger:** Querying `power.limit` or `clocks.mem` on a GPU that doesn't expose them (e.g. a laptop GPU with locked power table).
**Where:** perf_monitor.py:75 (`"[not supported]"` recognized)
**What it means (plain English):** `_to_float` correctly returns `None` for those fields, which is the right behavior.
**Symptoms:** Some metric tiles show `--`.
**Root cause(s):** Vendor lock; consumer-only feature gating.
**How to fix:** Already handled. Hide the tile in UI when `None`.
**Prevention / hardening:** Add `[unknown error]` and `[insufficient permissions]` tokens to the same recognized list.
**Related:** E.PRF.011, E.PRF.024.

## E.PRF.028 — Missing pythonnet wheel for Python 3.13
**Trigger:** Project switches to Python 3.13 / 3.14 before pythonnet ships matching wheels.
**Where:** perf_monitor.py:282 (`import clr`)
**What it means (plain English):** `pip install pythonnet` fails or installs a stub. `import clr` raises `ImportError`/`FileNotFoundError`.
**Symptoms:** `_LHM_DIRECT_REASON = "pythonnet/clr unavailable: <ExceptionClass>"`. WMI fallback still works.
**Root cause(s):** pythonnet release lag.
**How to fix:**
1. Pin Python ≤ 3.12 until pythonnet 3.x ships 3.13 wheels.
2. Use a pre-release pythonnet: `pip install pythonnet --pre`.
3. Rely solely on the WMI fallback.
**Prevention / hardening:** Catch the import error eagerly (already done at line 285) and degrade gracefully.
**Related:** E.PRF.012, E.PRF.014.

## E.PRF.029 — psutil.cpu_freq() returns None on some Linux/VM hosts
**Trigger:** `psutil.cpu_freq()` returns `None` (Hyper-V VMs without `/proc/cpuinfo` MHz, some ARM macOS versions).
**Where:** perf_monitor.py:196-198
**What it means (plain English):** No frequency telemetry. The code already guards with `if freq else None`.
**Symptoms:** `freq_mhz` and `freq_max_mhz` are `null`.
**Root cause(s):** Virtualization, missing kernel support.
**How to fix:** Acceptable degradation; UI should hide the dial when null.
**Prevention / hardening:** Already correctly guarded.
**Related:** E.PRF.001.

## E.PRF.030 — cgroup-limited CPU pct in containers reports host-level numbers
**Trigger:** Running the Flask server inside Docker with CPU quota (e.g. `--cpus=2`) on a 16-core host.
**Where:** perf_monitor.py:167-168, 195
**What it means (plain English):** `psutil.cpu_times()` reads `/proc/stat` which reports the host, not the cgroup. The CPU% reflects the host machine, not the container's slice.
**Symptoms:** Inside a container, util shows 6% even when the container is at 100% of its quota.
**Root cause(s):** psutil pre-cgroup-aware semantics.
**How to fix:**
1. Read `/sys/fs/cgroup/cpu.stat` (cgroup v2) or `/sys/fs/cgroup/cpuacct/cpuacct.usage` (v1) directly.
2. Use `psutil.Process().cpu_percent()` for self-only metric.
**Prevention / hardening:** Document that perf_monitor is host-level on bare metal; show "container mode" badge if `/.dockerenv` exists.
**Related:** E.PRF.031, E.PRF.021.

## E.PRF.031 — Container/Docker host CPU exposes other tenants
**Trigger:** Multi-tenant container host where the user expects isolation.
**Where:** perf_monitor.py:195
**What it means (plain English):** Same root as E.PRF.030; the panel inadvertently exposes other tenants' load.
**Symptoms:** CPU% spikes that have nothing to do with the user's workload.
**Root cause(s):** Cgroup vs host accounting mismatch.
**How to fix:** Switch to per-process accounting where the user only sees the Flask process and its children.
**Prevention / hardening:** Add a config flag `PERF_SCOPE = "host" | "process"`.
**Related:** E.PRF.030.

## E.PRF.032 — WMI initialization throwing on first call (long latency)
**Trigger:** First `Get-CimInstance` call takes >3s on a freshly booted Windows.
**Where:** perf_monitor.py:359-369
**What it means (plain English):** WMI service cold-starts the providers; the 3-second timeout fires; probe is recorded as unavailable forever (until process restart).
**Symptoms:** Right after boot, WMI fallback is permanently disabled even though it would work after warm-up.
**Root cause(s):** `_LHM_WMI_PROBED = True` is set unconditionally at line 357, so a single timeout is sticky.
**How to fix:**
1. Don't latch the probe on `TimeoutExpired`; only latch on a clean negative result.
2. Re-probe periodically (every N minutes).
**Prevention / hardening:** Convert the probe into a TTL-cached helper, not a one-shot latch.
**Related:** E.PRF.015, E.PRF.040.

## E.PRF.033 — LHM .NET assembly version mismatch
**Trigger:** A newer LHM DLL is dropped in but the API surface (`Computer`, `IsCpuEnabled`, `Hardware.Update()`) changed.
**Where:** perf_monitor.py:284, 290-307, 323
**What it means (plain English):** `clr.AddReference(dll)` succeeds, but `from LibreHardwareMonitor.Hardware import Computer` raises `ImportError`, or property setters fail.
**Symptoms:** `_LHM_DIRECT_REASON = "pythonnet/clr unavailable: ImportError"`.
**Root cause(s):** Upstream LHM API breakage; mixing ARM64 vs x64 DLL with a mismatched Python.
**How to fix:**
1. Pin a known-good LHM version.
2. Verify `Get-Item LibreHardwareMonitorLib.dll | Select VersionInfo`.
3. Match Python bitness to the DLL bitness.
**Prevention / hardening:** Add a startup probe that prints the resolved DLL path + version.
**Related:** E.PRF.012, E.PRF.020.

## E.PRF.034 — PowerShell stderr swallowed hides real WMI errors
**Trigger:** Any PS one-liner failure inside the WMI fallback.
**Where:** perf_monitor.py:367, 393
**What it means (plain English):** `stderr=subprocess.DEVNULL` discards the actual error message; debugging is reduced to "it didn't work".
**Symptoms:** Logs show "WMI fallback unavailable" with no diagnostic.
**Root cause(s):** Quiet-by-default subprocess settings.
**How to fix:**
1. For diagnostics, run a one-time probe that captures stderr and logs it.
2. Add a `DBD_PERF_DEBUG=1` env var that enables stderr passthrough.
**Prevention / hardening:** Always capture stderr to a buffer and only print it on failure.
**Related:** E.PRF.016, E.PRF.026.

## E.PRF.035 — Refresh races between samples (lost increment)
**Trigger:** Two callers within the same 500ms window — one rotates the baseline, the other reads against the new baseline expecting the old one.
**Where:** perf_monitor.py:177-185
**What it means (plain English):** The baseline rotation happens *after* the deltas are computed, but two near-simultaneous callers can have the rotation interleaved between their `_delta_pct` calls.
**Symptoms:** One of two concurrent callers occasionally returns 0% for a single tick.
**Root cause(s):** The `with _CPU_LOCK` correctly serializes the *snapshot*, but the rotation decision is per-call.
**How to fix:** Acceptable — locking already prevents corruption; only one caller per tick rotates. The "loser" still reads valid (possibly tiny) deltas, not zero.
**Prevention / hardening:** No change required; covered by the `if total_d <= 0: return 0.0` guard.
**Related:** E.PRF.003, E.PRF.022.

## E.PRF.036 — perf_snapshot returns the failure dicts, never raises
**Trigger:** Both `gpu_stats()` and `cpu_stats()` fail.
**Where:** perf_monitor.py:404-408
**What it means (plain English):** `perf_snapshot()` always returns `{"gpu": {...}, "cpu": {...}}` where each sub-dict has its own `available: false` and reason. There's no top-level error path.
**Symptoms:** Frontend always gets a 200 OK; must check `gpu.available` and `cpu.available` itself.
**Root cause(s):** Intentional design — graceful degradation.
**How to fix:** Document the contract; ensure the UI checks both flags.
**Prevention / hardening:** Add a defensive `try/except` around the call site that wraps `perf_snapshot` so a future refactor can't accidentally raise.
**Related:** E.PRF.018, E.PRF.040.

## E.PRF.037 — Sensor `s.Value` returns a System.Nullable<float> with weird truthiness
**Trigger:** LHM sensor returns a .NET `Nullable<Single>` that pythonnet marshals as a special object.
**Where:** perf_monitor.py:328-333
**What it means (plain English):** `if s.Value is None` works for the unset case, but `float(s.Value)` may raise `TypeError` on truly null nullables in some pythonnet versions.
**Symptoms:** `_read_cpu_temp_power_direct` raises and is silenced by the bare `except Exception`, returning `(None, None)`.
**Root cause(s):** pythonnet marshalling.
**How to fix:** `try: v = float(s.Value); except Exception: continue`.
**Prevention / hardening:** Wrap each individual sensor read in its own try/except so one bad sensor doesn't kill the whole loop.
**Related:** E.PRF.013, E.PRF.020.

## E.PRF.038 — `c.Open()` is slow (~700ms cold) blocking the first request
**Trigger:** First poll after server start triggers `_init_lhm_direct` → `c.Open()`.
**Where:** perf_monitor.py:298
**What it means (plain English):** Probing all CPU sensors via MSR/SMBus on cold start can take half a second to a second. The first HTTP request blocks for that long.
**Symptoms:** First sample of CPU panel arrives ~1s late; subsequent ones are instant.
**Root cause(s):** Driver init cost.
**How to fix:**
1. Eagerly initialize at app startup (background thread).
2. Cache the initialized `Computer` object (already done — `_LHM_DIRECT_TRIED`).
**Prevention / hardening:** Add a startup hook that calls `_init_lhm_direct()` from a daemon thread.
**Related:** E.PRF.013, E.PRF.032.

## E.PRF.039 — `_CPU_BASELINE_REFRESH_S` too short on busy event loop
**Trigger:** The event loop is starved; `_CPU_PREV_T` is older than 0.5s but the deltas span seconds.
**Where:** perf_monitor.py:35, 177-185
**What it means (plain English):** If the server is overloaded, the baseline is "fresh" (since refresh) but the delta represents many seconds — math still correct, just lossy averaging.
**Symptoms:** CPU% looks smoothed/laggy under heavy load.
**Root cause(s):** Single-threaded Flask + heavy work.
**How to fix:** Move `perf_snapshot` to a separate worker thread/process.
**Prevention / hardening:** Run the Flask app under a real WSGI server (waitress/gunicorn).
**Related:** E.PRF.022, E.PRF.030.

## E.PRF.040 — TTL caches hide that a sensor is permanently broken
**Trigger:** A sensor genuinely died; `_to_float` returns `None`; the cache stores `None` and serves it for 3 seconds repeatedly.
**Where:** perf_monitor.py:397, 400, 334
**What it means (plain English):** TTL cache treats `None` as a valid value. There's no "did the cache contain a positive read recently?" signal.
**Symptoms:** UI shows null indefinitely with no indication it's stuck null.
**Root cause(s):** Cache stores both successes and failures uniformly.
**How to fix:**
1. Track `last_successful_read_at` and surface it.
2. Or use shorter TTL for `None` results (e.g. 0.5s) than for valid values (3s).
**Prevention / hardening:** Add a `last_seen` timestamp per sensor in the snapshot.
**Related:** E.PRF.018, E.PRF.032.

## E.PRF.041 — `creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)` no-op on non-Windows
**Trigger:** Module imported on Linux; the `creationflags=0` is harmless but the subprocess call still tries to spawn `nvidia-smi` / `powershell`.
**Where:** perf_monitor.py:107, 366, 394
**What it means (plain English):** `getattr` correctly returns 0 on non-Windows so no flag mismatch. But the *spawn* still happens — `powershell` doesn't exist on Linux.
**Symptoms:** On Linux, `_probe_lhm_wmi_once` raises `FileNotFoundError`, caught at line 369, `_LHM_WMI_AVAILABLE=False`. Acceptable.
**Root cause(s):** Cross-platform code path.
**How to fix:** The `_read_cpu_temp_wmi` and `_read_cpu_power_wmi` already guard with `sys.platform.startswith("win")` (lines 342, 348), so the probe never runs. Good.
**Prevention / hardening:** Add the same guard to `_probe_lhm_wmi_once` for symmetry.
**Related:** E.PRF.014.

## E.PRF.042 — Inserting DLL dir into `sys.path` permanently
**Trigger:** `sys.path.insert(0, os.path.dirname(dll))` at line 281 prepends the LHM install folder to `sys.path` for the lifetime of the process.
**Where:** perf_monitor.py:281
**What it means (plain English):** Any future `import` of a name that happens to also exist in the LHM install folder will resolve there first.
**Symptoms:** Surprising shadowing if LHM ever ships a `.py` or DLL with a generic name.
**Root cause(s):** Wildcard `sys.path` injection.
**How to fix:**
1. Use `clr.AddReference(<absolute path>)` only — pythonnet doesn't actually need the dir on `sys.path`.
2. If needed, append rather than insert at index 0.
**Prevention / hardening:** Audit `sys.path` post-init in tests.
**Related:** E.PRF.012, E.PRF.033.

## E.PRF.043 — `_LHM_DIRECT_LAST` shared across temp/power sample timing
**Trigger:** Caller wants only `temp_c` but cache TTL has a stale `power_w` from 3s ago.
**Where:** perf_monitor.py:52, 318-321, 334
**What it means (plain English):** Single tuple stores both values; whatever update came last is what's served. Fine for the current 3s TTL but couples the two sensors.
**Symptoms:** Power and temp can drift up to 3s out-of-phase from each other in extreme cases.
**Root cause(s):** Combined cache.
**How to fix:** Acceptable for a 3s window; if needed, split into two cached tuples.
**Prevention / hardening:** Document the contract — both values are sampled together; treat them as a pair.
**Related:** E.PRF.040.

## E.PRF.044 — `_init_lhm_direct` partial init leaves `_LHM_DIRECT_OK=False` but resources held
**Trigger:** `c.Open()` succeeds but `next(iter(c.Hardware), None)` is `None`; code calls `c.Close()` (line 301) and returns False.
**Where:** perf_monitor.py:299-303
**What it means (plain English):** Correctly cleaned up. But if the exception path at line 308 is hit *after* `c.Open()`, `c.Close()` is never called and the .NET handles leak.
**Symptoms:** Stale LHM kernel-driver handles after repeated app restarts; possible "another instance running" error from LHM.
**Root cause(s):** Missing finally on the second try-block.
**How to fix:** Wrap lines 290-307 with `try/except/finally` and call `c.Close()` in the failure path.
**Prevention / hardening:** Add `atexit.register(c.Close)` once `_LHM_DIRECT_COMPUTER` is set.
**Related:** E.PRF.013, E.PRF.038.

## E.PRF.045 — perf_snapshot called from a thread without GIL warm-up causes pythonnet AttributeError
**Trigger:** First-ever call to `_LHM_DIRECT_CPU_HW.Update()` from a thread that hasn't touched .NET yet.
**Where:** perf_monitor.py:323
**What it means (plain English):** pythonnet attaches a CLR thread on first use; rare but documented races have caused `AttributeError: 'NoneType' object has no attribute 'Update'`.
**Symptoms:** Sporadic `_LHM_DIRECT_LAST` stays at zeros; the broad `except Exception` (line 336) hides it.
**Root cause(s):** pythonnet thread-attach race.
**How to fix:**
1. Pre-warm by calling `_init_lhm_direct()` and one `Update()` from the main thread.
2. Catch and re-init on `AttributeError`.
**Prevention / hardening:** Eager init at app startup, not lazy on first request.
**Related:** E.PRF.038, E.PRF.037.
