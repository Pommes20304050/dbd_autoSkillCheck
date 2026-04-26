# Chapter 5 — System Info & CPU Affinity Errors

`dbd/web/system_info.py` is the hardware-detection layer the Flask UI consults
to show CPU/GPU presets that match the user's actual machine. It pokes at
`kernel32!GetLogicalProcessorInformationEx` through ctypes, parses the
heterogeneous-core layout for hybrid Intel CPUs, computes affinity masks for
P-physical pinning, and tries Windows / Linux per-process affinity APIs.
Because every one of those steps speaks directly to a different OS, the file
is a magnet for portability and edge-case failures.

This chapter enumerates the failure modes — kernel32 ctypes mishaps, AMD
hybrid mis-classification, processor-group overflow, cgroup permission
errors on Linux, macOS no-ops, GPU enumeration regressions, and the long
tail of "fingers-crossed" parsing fallbacks. Entry numbering is `E.SYS.NNN`.

---

## E.SYS.001 — kernel32.dll fails to load via ctypes
**Trigger:** `ctypes.windll.kernel32` raises `OSError` or `AttributeError` at line 126 / line 230.
**Where:** system_info.py:126, system_info.py:230
**What it means (plain English):** Python tried to grab the standard Win32 system DLL and the loader said no. Either the platform check (`sys.platform.startswith("win")`) was wrong, ctypes is broken, or kernel32 isn't on the DLL search path (sandboxed, AppContainer, server core).
**Symptoms:** Detection silently returns `empty` (`p_logical=[]`, `is_hybrid=False`); UI shows non-hybrid presets even on a 14900K. `set_process_affinity` returns `False`.
**Root cause(s):** Wine prefix without working kernel32, AppContainer / MSIX sandboxing the process, broken Python install, antivirus blocking ctypes.
**How to fix:**
1. Run `python -c "import ctypes; print(ctypes.windll.kernel32)"` outside the app to confirm.
2. Reinstall Python from python.org (not from MS Store — that one runs in AppContainer with restricted DLL access).
3. Add an AV exclusion for the install dir.
**Prevention / hardening:** The `try/except Exception: return empty` at line 89 already swallows this; surface a `cpu.detection_error` field in `detect_cpu()` for the UI to display so users notice.
**Related:** E.SYS.002, E.SYS.030.

---

## E.SYS.002 — GetLogicalProcessorInformationEx initial sizing returns wrong error
**Trigger:** Initial sizing call doesn't return `ERROR_INSUFFICIENT_BUFFER` (122).
**Where:** system_info.py:131-134
**What it means (plain English):** The standard "ask the API how big a buffer to allocate" pattern got a different errno. Could be `ERROR_INVALID_PARAMETER` (3) on too-old Windows, `ERROR_NOT_ENOUGH_MEMORY` (8), or success (0) if the structure is empty.
**Symptoms:** `OSError("GetLogicalProcessorInformationEx initial sizing failed")` raised; outer try/except returns `empty` dict.
**Root cause(s):** Windows 7 SP1 without KB hotfix (function exists but stub), 32-bit Python on >64 logical CPUs (struct layout mismatch), running under Wine with stale wineprefix.
**How to fix:**
1. Verify Windows version `>= 10.0.10240`.
2. Check `ctypes.GetLastError()` value in the raised message — log it in the except block.
3. Fall back to the older `GetLogicalProcessorInformation` (no Ex) which uses fixed-size structs.
**Prevention / hardening:** Wrap the raise with the actual GetLastError code so the fallback path can decide whether to retry vs. give up.
**Related:** E.SYS.003, E.SYS.005.

---

## E.SYS.003 — GetLogicalProcessorInformationEx second call fails
**Trigger:** Second `fn(...)` call returns 0 (FALSE).
**Where:** system_info.py:137-138
**What it means (plain English):** The buffer allocation worked, but the actual data fetch failed. Almost always indicates the topology changed between the two calls (CPU hotplug, VM live-migration) so `length` is now too small.
**Symptoms:** `OSError("GetLogicalProcessorInformationEx failed")`; falls back to `empty`.
**Root cause(s):** VM CPU hotplug, container CPU resize, race with Windows power-throttling park/unpark.
**How to fix:**
1. Retry the whole sizing+fetch sequence up to 3× before giving up.
2. Check `GetLastError() == ERROR_INSUFFICIENT_BUFFER` — if so, re-allocate with the new `length` and retry.
**Prevention / hardening:** Implement a sizing/fetch retry loop in `_detect_pe_cores_windows` like the official MSDN example.
**Related:** E.SYS.002, E.SYS.025.

---

## E.SYS.004 — PROCESSOR_RELATIONSHIP struct misalignment
**Trigger:** Parsed `EfficiencyClass` is nonsensical (e.g. 0xCC, 254, garbage), or `info.Size` is 0 / huge.
**Where:** system_info.py:107-114, parsed at 142-152
**What it means (plain English):** The ctypes struct definition doesn't match the binary layout the OS wrote. Likely cause: `BYTE` Reserved padding miscounted, or the union member alignment differs from the actual `SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX`.
**Symptoms:** Infinite loop (Size=0), buffer over-read crash, or `is_hybrid=True` on a non-hybrid CPU because efficiency classes look like `{0, 204}`.
**Root cause(s):** Future Windows SDK extends the struct with new fields, code uses fixed `Reserved BYTE * 20` that's now wrong; or `GroupMask GROUP_AFFINITY * 1` flexible-array-member mismatch when `GroupCount > 1`.
**How to fix:**
1. Validate `info.Size >= sizeof(struct)` before parsing.
2. Bound the offset advance: `if info.Size == 0: break`.
3. Sanity-check `eff` is in 0..15 before trusting it.
**Prevention / hardening:** Add `assert 0 < info.Size <= length.value - offset` and log struct dump on failure.
**Related:** E.SYS.005, E.SYS.011.

---

## E.SYS.005 — OS too old (Windows 7/8) — no GetLogicalProcessorInformationEx
**Trigger:** Function pointer lookup fails or returns garbage on pre-Win7-SP1.
**Where:** system_info.py:127
**What it means (plain English):** `GetLogicalProcessorInformationEx` was added in Windows 7. Older Windows (Vista, XP) have only the non-Ex version with a different struct.
**Symptoms:** `AttributeError: function 'GetLogicalProcessorInformationEx' not found`; outer `except` returns empty.
**Root cause(s):** User running pre-Win7 (rare but happens in industrial / lab environments), or the function exists but always fails (Wine).
**How to fix:**
1. Detect Windows version with `sys.getwindowsversion()` and skip hybrid detection on `< (6, 1)`.
2. For Vista/XP, accept that hybrid CPUs don't exist there anyway and return `is_hybrid=False`.
**Prevention / hardening:** Resolve the function with `getattr(kernel32, "GetLogicalProcessorInformationEx", None)` and explicitly return empty on `None`.
**Related:** E.SYS.002.

---

## E.SYS.006 — WMI fallback for hybrid detection is missing
**Trigger:** Some users expect hybrid detection via WMI when the ctypes path fails; the code never tries WMI.
**Where:** system_info.py:73-90 (no WMI fallback)
**What it means (plain English):** If the ctypes route fails for any reason (E.SYS.001-005), there's no plan B. WMI's `Win32_Processor` exposes `Architecture` and `Description`, and Windows 11 even surfaces hybrid info via `MSFT_Processor`.
**Symptoms:** `is_hybrid=False` on a confirmed Intel 12th-gen+ host whenever ctypes path raises; star-marked presets disappear.
**Root cause(s):** Defensive `except Exception` at line 89 hides the failure without trying alternates.
**How to fix:**
1. Add a WMI fallback using `wmi` package or `subprocess.run(["wmic", "cpu", "get", "Name"])`.
2. Or parse `HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\*` registry entries for `Identifier` to infer P-vs-E.
**Prevention / hardening:** Even rough heuristics ("Intel + gen >= 12" → assume hybrid) beat silently degrading.
**Related:** E.SYS.001, E.SYS.024.

---

## E.SYS.007 — Hybrid detection wrong on AMD Zen 4/5 (no P/E split)
**Trigger:** AMD Ryzen 7000/9000-series CPU evaluated; all cores share `EfficiencyClass=0`.
**Where:** system_info.py:158-159
**What it means (plain English):** AMD Zen 4 and Zen 5 are NOT hybrid in the Intel sense — every core is the same architecture. So `eff_classes == {0}` and `is_hybrid=False` is correct… until you hit Zen 5c (cloud) variants or the 7950X3D where one CCD has 3D V-Cache and the other doesn't.
**Symptoms:** No star-marked presets on Ryzen 9 7950X3D even though pinning to the X3D CCD gives 30%+ FPS uplift in games. False negatives on AMD's "Phoenix2" Zen4+Zen4c hybrids (laptops).
**Root cause(s):** Code assumes `len(eff_classes) >= 2` is the only hybrid signal. AMD reports `EfficiencyClass=0` for all cores even when there's heterogeneity (CCD asymmetry, 3D V-Cache).
**How to fix:**
1. Add CPU-name regex: if `name.contains("7950X3D"|"7900X3D"|"9950X3D")`, parse cache info to detect the X3D CCD.
2. Use `cpuid` instruction (via `cpuid` package) to read leaf `0x8000001E` for compute-unit topology.
**Prevention / hardening:** Add an explicit `is_amd_asymmetric` flag distinct from `is_hybrid`.
**Related:** E.SYS.008, E.SYS.014.

---

## E.SYS.008 — AMD 7950X3D: pinning to wrong CCD halves performance
**Trigger:** User on 7950X3D enables a "Max" preset that spans both CCDs.
**Where:** system_info.py:267-290 (preset builder)
**What it means (plain English):** The 7950X3D has two 8-core CCDs: one with 3D V-Cache (slower clocks, big L3), one without (higher clocks, normal L3). Cross-CCD scheduling adds Infinity Fabric latency. The DBD inference workload is cache-sensitive; pinning to the X3D CCD specifically wins. We don't surface that.
**Symptoms:** Variance run-to-run; FPS swings depending on Windows scheduler whim.
**Root cause(s):** Preset builder treats AMD as homogeneous (`is_hybrid=False`), so no pinned presets generated.
**How to fix:**
1. After detecting an X3D part, generate two presets: "X3D CCD (8 phys)" and "Frequency CCD (8 phys)", letting the user pick.
2. Default to X3D CCD for inference (cache-bound).
**Prevention / hardening:** Document the CCD-pinning UX explicitly; gamers expect this UI on AMD.
**Related:** E.SYS.007.

---

## E.SYS.009 — SetProcessAffinityMask returns 0 (insufficient privileges)
**Trigger:** `kernel32.SetProcessAffinityMask(h, mask)` returns FALSE; `set_process_affinity` returns `False`.
**Where:** system_info.py:235
**What it means (plain English):** The OS rejected the affinity change. On Windows the most common reason is Job-Object restriction — if the parent process applied `JOB_OBJECT_LIMIT_AFFINITY`, child processes can only narrow the mask, never expand it.
**Symptoms:** `default_cpu_threads` returns the full-P count but `bench_pe_cores.py` reports same FPS as no-pinning; star presets show up but provide no benefit.
**Root cause(s):** Running under a Job (Windows Sandbox, Docker for Windows, some CI runners), AppContainer, or with reduced token privilege.
**How to fix:**
1. Check if process is in a Job: `IsProcessInJob(GetCurrentProcess(), NULL, &inJob)`.
2. Query the current job affinity with `QueryInformationJobObject` and AND your mask with it before applying.
3. Surface failure clearly in the UI so users know pinning is inactive.
**Prevention / hardening:** Add a post-pin verify: read back `GetProcessAffinityMask` and compare; warn if they differ.
**Related:** E.SYS.010, E.SYS.027.

---

## E.SYS.010 — SetProcessAffinityMask: mask invalid (bit set for nonexistent CPU)
**Trigger:** Mask has bits set for logical CPUs >= `os.cpu_count()`.
**Where:** system_info.py:235
**What it means (plain English):** SetProcessAffinityMask requires the requested mask be a subset of the system affinity mask. If `_mask_to_list` is fed a stale mask after VM resize, you'll get bits beyond reality and the call silently returns 0.
**Symptoms:** Returns `False`; pinning silently disabled.
**Root cause(s):** VM CPU hotplug, hot-removal of a core, mask cached across power-state transitions.
**How to fix:**
1. Sanity-check `mask & ~system_affinity_mask == 0` before calling.
2. Re-detect topology if `os.cpu_count()` differs from cached value.
**Prevention / hardening:** Compute `system_affinity_mask = (1 << os.cpu_count()) - 1` and AND the requested mask with it before passing to ctypes.
**Related:** E.SYS.009, E.SYS.013.

---

## E.SYS.011 — Processor groups: >64 logical CPUs silently ignored
**Trigger:** Threadripper 7980X / Xeon dual-socket with > 64 logical CPUs.
**Where:** system_info.py:195-196 (`_mask_to_list` hard-coded to range(64))
**What it means (plain English):** Windows splits CPUs > 64 into multiple "processor groups" of 64. `SetProcessAffinityMask` only addresses ONE group at a time. The 64-bit mask plus group index is the actual API. We pretend the world stops at CPU 63.
**Symptoms:** On a 96-thread 7980X only the first group's 64 threads ever appear in masks. Pinning to "all P-physical" misses any P-cores in group 1.
**Root cause(s):** `_mask_to_list(mask)` returns `[i for i in range(64)]`; we ignore `GROUP_AFFINITY.Group` field at line 149.
**How to fix:**
1. Track `Group` per core; build per-group masks.
2. Use `SetThreadGroupAffinity` (per-thread) instead of `SetProcessAffinityMask` (single-group).
3. For most users this is moot — DBD is single-game on consumer HW — but document the limit.
**Prevention / hardening:** Detect `os.cpu_count() > 64` and disable affinity pinning with a warning rather than producing a wrong mask.
**Related:** E.SYS.010, E.SYS.020.

---

## E.SYS.012 — os.sched_setaffinity Linux PermissionError on cgroup-restricted set
**Trigger:** Container's cgroup `cpuset.cpus` excludes some bits in `mask`; `os.sched_setaffinity(0, cpus)` raises `PermissionError` (EPERM) or `ValueError` (EINVAL).
**Where:** system_info.py:245-248
**What it means (plain English):** Inside Docker/Kubernetes the kernel pre-restricts which CPUs you may touch. Trying to expand beyond that set fails with EINVAL, not "silently clamped".
**Symptoms:** `set_process_affinity` returns `False`; on a system that should support pinning. Log noise: `OSError: [Errno 22] Invalid argument`.
**Root cause(s):** Cgroup v2 restrictions, `taskset`-launched parent that already narrowed affinity, systemd `CPUAffinity=` directive.
**How to fix:**
1. Read `os.sched_getaffinity(0)` first; intersect with desired CPU set before applying.
2. Catch `PermissionError` separately from `OSError` for clearer diagnostics.
**Prevention / hardening:** Add the intersection logic so we always request a subset of what's permitted.
**Related:** E.SYS.013, E.SYS.026.

---

## E.SYS.013 — os.sched_setaffinity: empty cpu set ambiguity
**Trigger:** `mask` argument has no bits set for CPUs 0..255 → `cpus = set()`.
**Where:** system_info.py:242-244
**What it means (plain English):** Code correctly treats empty set as failure (`return False`), but the caller may have meant "all CPUs". The function silently drops the request without telling anyone.
**Symptoms:** Pinning silently disabled, no log message, user mystified.
**Root cause(s):** Caller passes a mask intended as "all" (mask=0 means "no restriction" on Windows in some APIs, but means "fail" here).
**How to fix:**
1. At minimum, log a warning when `mask=0` is passed.
2. Define an explicit "no pinning" sentinel (`None`) distinct from `mask=0`.
**Prevention / hardening:** Document mask=0 semantics in the docstring.
**Related:** E.SYS.018.

---

## E.SYS.014 — macOS: no per-process affinity API → silent no-op
**Trigger:** Running on Darwin; `hasattr(os, "sched_setaffinity")` is `False`.
**Where:** system_info.py:240-249
**What it means (plain English):** macOS deliberately doesn't expose process-pinning in user space. The "thread affinity hints" API (`thread_policy_set`) is a hint, not a guarantee. Function returns `False` and pinning never happens.
**Symptoms:** Apple Silicon users get no benefit from P/E presets; benchmark deltas absent.
**Root cause(s):** Apple's stance: scheduler knows best.
**How to fix:**
1. Hide all star-marked presets on macOS in the UI.
2. Use `thread_policy_set` with `THREAD_AFFINITY_POLICY` for best-effort hinting (still not guaranteed).
**Prevention / hardening:** Detect Darwin and suppress hybrid UI affordances entirely; show an info banner.
**Related:** E.SYS.022.

---

## E.SYS.015 — get_logical_processor_count overflow at 64 bits
**Trigger:** `_mask_to_list(mask)` only iterates `range(64)`; fails to enumerate cores 64..127 even on 64-bit Windows.
**Where:** system_info.py:195-196
**What it means (plain English):** Same root issue as E.SYS.011 from another angle. `c_uint64 Mask` field is per-group, so each group's mask CAN'T exceed 64 bits, but the data structure has a `Group` index too — which we discard.
**Symptoms:** P-cores in group 1 missing from `p_logical`.
**Root cause(s):** Hard-coded loop bound 64.
**How to fix:**
1. See E.SYS.011.
**Prevention / hardening:** Replace with `int.bit_length()`-based iteration to be safe up to 64 bits per call.
**Related:** E.SYS.011.

---

## E.SYS.016 — nvidia-smi subprocess.TimeoutExpired
**Trigger:** A GPU detection path shells out to `nvidia-smi` and the call hangs.
**Where:** system_info.py:332-387 (currently uses torch+ort, not nvidia-smi — but a future enhancement may add it; document the failure mode)
**What it means (plain English):** `nvidia-smi` can hang for tens of seconds when the GPU is in `P8` state, when an XID 13 just fired, or when nvidia-persistenced is dead. Subprocess timeout pops.
**Symptoms:** UI hangs on startup; GPU info never returns.
**Root cause(s):** Driver hung, persistence mode off, GPU in low-power state, MIG slicing in flux.
**How to fix:**
1. If you add nvidia-smi calls, use `timeout=5`.
2. Catch `subprocess.TimeoutExpired` and treat as "no GPU info".
3. Prefer `pynvml` over shelling out.
**Prevention / hardening:** Run GPU detection in a background thread so UI stays responsive.
**Related:** E.SYS.017, E.SYS.023.

---

## E.SYS.017 — nvidia-smi parse failure on non-English locale
**Trigger:** German/French Windows with `nvidia-smi` localized output (rare); CSV parser breaks on commas in locale-dependent decimals.
**Where:** system_info.py (potential nvidia-smi addition)
**What it means (plain English):** `nvidia-smi` is mostly locale-agnostic but driver versions and timestamp fields aren't. CSV with `,` decimals corrupts numeric parses.
**Symptoms:** ValueError on float parse; GPU device list partially populated.
**Root cause(s):** German `Win11`'s comma decimal in temperature field; `nvidia-smi --query-gpu=...` mostly safe but DON'T parse human output.
**How to fix:**
1. Use `nvidia-smi --query-gpu=name --format=csv,noheader,nounits`.
2. Force `LANG=C` in subprocess env.
**Prevention / hardening:** Use NVML directly (`pynvml`) — no parsing.
**Related:** E.SYS.016.

---

## E.SYS.018 — Affinity mask=0 ambiguity (all vs none)
**Trigger:** Caller passes `mask=0` to `set_process_affinity` or `p_physical_affinity_mask` returns 0.
**Where:** system_info.py:225-226, 199-218
**What it means (plain English):** `mask=0` means "no CPUs" in Win32 (and the API rejects it: ERROR_INVALID_PARAMETER). Code currently treats 0 as "fail" → returns False. But callers might mean "no pinning preferred" → expecting pinning to be skipped, not failed.
**Symptoms:** Adaptive presets generate `(label, threads, 0)` for non-hybrid CPUs (line 268); a downstream caller invoking `set_process_affinity(0)` always gets False without a warning.
**Root cause(s):** Sentinel collision: 0 means both "unset" and "request zero CPUs".
**How to fix:**
1. Use `mask=None` for "no pinning"; `mask=0` should never be valid.
2. Adjust `adaptive_cpu_presets` to emit `None` instead of 0 for unpinned presets.
**Prevention / hardening:** Type the mask as `Optional[int]` and disallow 0 explicitly.
**Related:** E.SYS.013.

---

## E.SYS.019 — ImportError pythonnet on non-Windows
**Trigger:** Future LibreHardwareMonitor integration imports `clr` (pythonnet); fails on Linux/macOS or 32-bit Python.
**Where:** system_info.py (potential LHM addition for thermal/power)
**What it means (plain English):** pythonnet ships .NET CLR bindings; only works on Windows + .NET Framework or .NET 6+. Linux requires Mono + extra steps.
**Symptoms:** `ImportError: No module named 'clr'`; thermal info absent.
**Root cause(s):** Cross-platform code attempts Windows-only LHM lib.
**How to fix:**
1. Guard the import: `if sys.platform.startswith("win"): import clr`.
2. Catch `ImportError` and fall back to `psutil.sensors_temperatures()`.
**Prevention / hardening:** Only attempt CLR libraries inside platform-checked branches.
**Related:** E.SYS.024.

---

## E.SYS.020 — WMI fallback when LibreHardwareMonitor not running
**Trigger:** Code expects LHM WMI namespace `root\LibreHardwareMonitor`; LHM service not started.
**Where:** system_info.py (potential thermal addition)
**What it means (plain English):** LHM exposes detailed sensor data via WMI ONLY when its UI/service is running. Headless detection without LHM gets empty results.
**Symptoms:** No thermal/power info; UI shows "—" for sensor fields.
**Root cause(s):** LHM not installed / not running.
**How to fix:**
1. Bundle Open/Libre HW Monitor or document install requirement.
2. Fall back to WMI `root\WMI\MSAcpi_ThermalZoneTemperature` (limited but no LHM needed).
**Prevention / hardening:** Detect LHM service via `sc query LibreHardwareMonitor` before WMI query.
**Related:** E.SYS.019, E.SYS.006.

---

## E.SYS.021 — 32-bit Python on 64-bit Windows
**Trigger:** User has 32-bit Python interpreter; `c_size_t` is 4 bytes; mask values >= 2^32 truncate.
**Where:** system_info.py:232 (`SetProcessAffinityMask.argtypes = [..., c_size_t]`)
**What it means (plain English):** `c_size_t` matches the interpreter pointer width, NOT the OS pointer width. A 32-bit Python on 64-bit Windows truncates affinity masks for CPUs 32..63.
**Symptoms:** Pinning silently fails or pins wrong cores on systems with > 32 logical CPUs.
**Root cause(s):** 32-bit ctypes types in a 64-bit OS.
**How to fix:**
1. Detect interpreter bitness with `sys.maxsize > 2**32`; warn on 32-bit + > 32-thread CPU.
2. Force `c_uint64` instead of `c_size_t` for the mask parameter.
**Prevention / hardening:** Refuse to install on 32-bit Python.
**Related:** E.SYS.011.

---

## E.SYS.022 — ARM CPUs (Apple Silicon, Snapdragon X) misclassified
**Trigger:** Apple M1-M4 or Snapdragon X Elite; `platform.machine()` returns `arm64` / `aarch64`.
**Where:** system_info.py:23-24, 73-90
**What it means (plain English):** Apple Silicon has heterogeneous P/E cores (Firestorm/Avalanche P-cores + Icestorm/Blizzard E-cores). Snapdragon X Elite has all-Oryon homogeneous cores. Neither expose info via `GetLogicalProcessorInformationEx`.
**Symptoms:** All ARM systems show `is_hybrid=False`; no pinning presets even though Apple Silicon clearly benefits.
**Root cause(s):** Detection is Win32-only; no `sysctl hw.perflevel0.physicalcpu` (Darwin) or `/sys/devices/system/cpu/cpu*/topology/cluster_id` (Linux ARM) fallbacks.
**How to fix:**
1. On Darwin, parse `sysctl hw.perflevel0.physicalcpu` and `hw.perflevel1.physicalcpu`.
2. On Windows-on-ARM, query `IsProcessorFeaturePresent` and `GetSystemInfo`.
3. Skip pinning UI on ARM until backed by a working API path.
**Prevention / hardening:** Add `arch` field to `detect_cpu()` output; UI should disable hybrid affordances on `arm64`.
**Related:** E.SYS.014.

---

## E.SYS.023 — Power scheme affecting affinity (Windows "Best Performance")
**Trigger:** Windows Modern Standby + connected-standby parks cores; affinity mask referencing parked CPUs returns success but no thread runs there.
**Where:** system_info.py:235 (SetProcessAffinityMask succeeds)
**What it means (plain English):** PowerCfg's CPMINCORES / CPMAXCORES values can park P-cores under the "Balanced" scheme. Pinning to a parked core yields zero throughput — and the API doesn't tell you.
**Symptoms:** `bench_pe_cores.py` reports identical FPS regardless of pin; "Max" beats "P-Physical".
**Root cause(s):** Windows core-parking active under Balanced scheme; "Ultimate Performance" disables it.
**How to fix:**
1. On detection, query `powercfg /getactivescheme`; recommend "High performance" / "Ultimate" for benchmarks.
2. Read `\Kernel\Processor\1\C0%` perfmon counter to detect parked cores.
**Prevention / hardening:** Surface a warning in the UI: "Power scheme = Balanced; pinning may be ineffective."
**Related:** E.SYS.009, E.SYS.027.

---

## E.SYS.024 — CPU short-name parsing collapses on unusual brands
**Trigger:** CPU name like `"AMD Ryzen 9 7950X3D 16-Core Processor"` — `_short_cpu_name` strips "AMD ", "Processor"; result: `"Ryzen 9 7950X3D 16-Core"`. ARM / Apple / unknown vendors look weirder.
**Where:** system_info.py:49-61
**What it means (plain English):** The noise-strip list is Intel-centric. AMD, Qualcomm, Apple, ARM names get partial cleanups, leaving "Apple M3 Max", "Snapdragon(R) X Elite", or "Ampere Altra" with vendor tokens still attached.
**Symptoms:** Topbar chip shows ugly long string; no functional break, just UX.
**Root cause(s):** Regex/string-replace approach uses fixed token list.
**How to fix:**
1. Extend the noise list: `("AMD ", "Ryzen ", "Apple ", "Qualcomm(R) ", "Snapdragon(R) ", "(R)", "(TM)", "16-Core", "8-Core", ...)`.
2. Better: use a regex `r"\b(Processor|CPU|\d+-Core)\b"` plus vendor stripping.
**Prevention / hardening:** Snapshot a corpus of CPU name strings (Intel / AMD / ARM) and run a unit test.
**Related:** E.SYS.030.

---

## E.SYS.025 — Container-restricted CPUs (`os.cpu_count` lies)
**Trigger:** Inside Docker with `--cpus=2`; `os.cpu_count()` still returns host count (16); `os.sched_getaffinity(0)` returns the limited set.
**Where:** system_info.py:11
**What it means (plain English):** `os.cpu_count()` reports physical/logical count, NOT the cgroup-restricted set. So `cores=16` but only 2 are usable. Presets generate "Max=16t", which immediately oversubscribes.
**Symptoms:** Massive performance regression in containers; thread pools 8× over-allocated.
**Root cause(s):** os.cpu_count semantics on Linux predate cgroups.
**How to fix:**
1. Use `len(os.sched_getaffinity(0))` on Linux when available — that's the correct usable count.
2. Or `psutil.Process().cpu_affinity()` (cross-platform helper).
**Prevention / hardening:** Replace `os.cpu_count()` with a wrapper that prefers `sched_getaffinity` on Linux.
**Related:** E.SYS.012.

---

## E.SYS.026 — Process affinity reset by Windows Process Manager
**Trigger:** Windows 11 22H2+ "Efficiency Mode" or Process Manager re-pins the process after we set affinity.
**Where:** system_info.py:235 (post-call drift)
**What it means (plain English):** Windows scheduler can override affinity hints, especially when the process is marked Efficiency Mode (lower priority). After a few seconds the OS re-balances threads back across cores.
**Symptoms:** Initial pinning works; throughput degrades over 10-30s as scheduler intervenes.
**Root cause(s):** Process Power Throttling / EcoQoS overrides pinning hints; foreground/background priority shifts.
**How to fix:**
1. Disable EcoQoS: `SetProcessInformation(h, ProcessPowerThrottling, ...)` with `ControlMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED`.
2. Periodically re-apply affinity (every 5s).
**Prevention / hardening:** Set process priority class to `HIGH_PRIORITY_CLASS` and clear EcoQoS at startup.
**Related:** E.SYS.009, E.SYS.023.

---

## E.SYS.027 — Intel 12th-gen P-Core preset on non-hybrid CPUs
**Trigger:** Code path that *should* skip hybrid logic on (e.g.) 11th-gen Intel triggers it anyway because of buggy `EfficiencyClass` reporting.
**Where:** system_info.py:158-159
**What it means (plain English):** A handful of older platforms report `EfficiencyClass=0` for some cores and `EfficiencyClass=1` for others due to BIOS bugs (some pre-12th-gen), making the code believe it's hybrid and producing nonsense star presets.
**Symptoms:** Star-marked "P-cores" preset on a 10900K; UI shows `8P+0E` or similar nonsense.
**Root cause(s):** Vendor BIOS reports asymmetric EfficiencyClass on homogeneous CPUs.
**How to fix:**
1. Cross-check with CPU-name regex: only trust `is_hybrid=True` if name matches Intel 12th-gen+ family.
2. Verify both classes have non-zero core count (line 184 already does P-class assignment).
**Prevention / hardening:** Add `is_hybrid &= name_suggests_hybrid(name)` guard.
**Related:** E.SYS.007, E.SYS.024.

---

## E.SYS.028 — `winreg.OpenKey` fails on locked-down systems
**Trigger:** `HARDWARE\DESCRIPTION\System\CentralProcessor\0` not readable; PermissionError or FileNotFoundError.
**Where:** system_info.py:34-37
**What it means (plain English):** Group Policy / EDR can lock down HARDWARE registry keys. Code falls back to `platform.processor()`, which on Windows just returns `"Intel64 Family 6 Model 183 Stepping 1, GenuineIntel"` — useless for short-name display.
**Symptoms:** Topbar shows raw CPUID string instead of "i9-14900K".
**Root cause(s):** Strict GPO; running as SYSTEM in some scheduled-task contexts strips access.
**How to fix:**
1. Try alternate sources: `wmic cpu get Name`, NVML for NVIDIA-paired systems, environment vars.
2. Catch `OSError`/`FileNotFoundError` separately.
**Prevention / hardening:** Cache a clean CPU name in user-config so the fallback only runs once.
**Related:** E.SYS.024.

---

## E.SYS.029 — `platform.processor()` returns empty string on Linux
**Trigger:** Linux non-Windows fallback at line 45.
**Where:** system_info.py:45-46
**What it means (plain English):** `platform.processor()` returns `""` on most modern Linux distros (returns the same as `platform.machine()` in the worst case). Code falls back to `"CPU"`.
**Symptoms:** Linux users see "CPU" as the chip name; no model info.
**Root cause(s):** `/proc/version` doesn't expose model name; CPython doesn't read `/proc/cpuinfo`.
**How to fix:**
1. Parse `/proc/cpuinfo` directly: `model name` field.
2. Or use `lscpu -J` and parse JSON.
**Prevention / hardening:** Add a Linux-specific cpu-name probe.
**Related:** E.SYS.028.

---

## E.SYS.030 — `_short_cpu_name` produces empty string after stripping
**Trigger:** CPU name consists ENTIRELY of stripped tokens (artificial test case, but possible with weird firmware).
**Where:** system_info.py:60-61
**What it means (plain English):** If `name.strip(" -@")` returns empty, code returns `name` (the original) — but if name was already empty, result is "". Caller chains might choke.
**Symptoms:** Topbar chip empty; nothing rendered.
**Root cause(s):** Edge case handling: empty after strip falls back to `name` which may also be empty.
**How to fix:**
1. Final fallback: `return cleaned or name or "CPU"`.
**Prevention / hardening:** Always return a non-empty label.
**Related:** E.SYS.024.

---

## E.SYS.031 — `default_cpu_threads` returns 0 on broken hybrid detection
**Trigger:** `is_hybrid=True` but `p_physical=0` (impossible-but-occurred edge case).
**Where:** system_info.py:322-326
**What it means (plain English):** Loop fails to find matching star preset; falls through to `presets[0][1]`. If `presets` is empty (cores <= 0), `IndexError`.
**Symptoms:** `IndexError: list index out of range` from default thread query.
**Root cause(s):** `_baseline_presets` always emits at least 2 entries even for cores=0, so unlikely — but `cores=0` returns `[("Single", 1), ("Max", 0)]`, and if the star loop finds a match with threads=0, default = 0 threads → ORT crashes.
**How to fix:**
1. Clamp `cores = max(1, os.cpu_count() or 4)`.
2. Skip preset entries where `threads == 0`.
**Prevention / hardening:** Defensive minimum at the top of `detect_cpu`.
**Related:** E.SYS.018.

---

## E.SYS.032 — `p_physical_affinity_mask` HT detection fragile on partial-HT CPUs
**Trigger:** CPU like Intel 14900K where P-cores have HT but E-cores don't; `len(p_logical) >= 2 * n_phys` matches for P-cluster, but selecting `p_logical[::2]` assumes interleaved sibling ordering.
**Where:** system_info.py:213-214
**What it means (plain English):** Logical CPU IDs aren't guaranteed to be `[P0a, P0b, P1a, P1b, ...]`. On some Windows topologies they're `[P0a, P1a, ..., P0b, P1b, ...]` (cluster-major). `p_logical[::2]` then picks 2 logical from the SAME physical core — defeating the "no HT siblings" intent.
**Symptoms:** Pinning supposedly-distinct physical cores actually shares one core's two SMT siblings; throughput halved.
**Root cause(s):** Assumed sibling-interleaved enumeration; not universal.
**How to fix:**
1. Use the per-core `mask` from `cores` list (each entry has a 2-bit mask for HT cores) and pick the lowest bit per physical core.
2. Don't infer from `p_logical` order; carry the per-physical-core sibling mask through.
**Prevention / hardening:** Refactor `_detect_pe_cores_windows` to return per-physical-core sibling info, not flat logical lists.
**Related:** E.SYS.007.

---

## E.SYS.033 — `c_byte` array buffer over-read on incorrect length
**Trigger:** `length.value` is wrong (driver bug); `(c_byte * length.value)()` allocates too small; parsing reads past end.
**Where:** system_info.py:136
**What it means (plain English):** ctypes won't enforce buffer bounds inside the `while offset < length.value` loop. If the OS lied about size or struct headers say `Size > remaining`, we segfault.
**Symptoms:** Python interpreter crash with no traceback, or returns wildly wrong eff classes.
**Root cause(s):** Trust in `info.Size` advance without bounds-checking that `offset + info.Size <= length.value`.
**How to fix:**
1. Add `if offset + info.Size > length.value: break`.
2. Validate `0 < info.Size < 4096` (sanity bound).
**Prevention / hardening:** Defense-in-depth bounds check.
**Related:** E.SYS.004.

---

## E.SYS.034 — Detection runs on every Flask request (perf)
**Trigger:** UI re-fetches `/system_info` JSON; `detect_cpu()` runs again, re-allocates kernel32 buffer.
**Where:** system_info.py:10-25 (no caching)
**What it means (plain English):** `_detect_pe_cores_windows` is non-trivial (ctypes alloc, kernel call); not cached. Hammering the endpoint kicks Windows hundreds of times.
**Symptoms:** UI sluggish under repeated polling; minor CPU usage spike when settings tab is open.
**Root cause(s):** No memoization.
**How to fix:**
1. Cache result module-level: `_pe_cache = None; if _pe_cache: return _pe_cache`.
2. Invalidate on suspend/resume events if topology can change (rare).
**Prevention / hardening:** Use `functools.lru_cache(maxsize=1)` on `detect_pe_cores`.
**Related:** —

---

## E.SYS.035 — torch import side-effects (CUDA init blocks UI thread)
**Trigger:** `import torch` at line 355 triggers CUDA context init on first call; can take 1-3 seconds.
**Where:** system_info.py:355
**What it means (plain English):** Torch lazily initializes CUDA on first `cuda.is_available()` call. That triggers `nvcuda.dll` load, driver context create, kernel compile-cache check. Blocks the Flask request thread.
**Symptoms:** First UI load is slow; subsequent calls fast (cache).
**Root cause(s):** torch's import-time side effects.
**How to fix:**
1. Run `detect_gpu()` once at startup in a background thread; serve cached result.
2. Set `CUDA_MODULE_LOADING=LAZY` env to defer kernel loads.
**Prevention / hardening:** Pre-warm at app launch.
**Related:** E.SYS.036.

---

## E.SYS.036 — `torch.cuda.device_count` throws on broken driver
**Trigger:** CUDA driver mismatch with toolkit; `device_count()` raises `RuntimeError("CUDA driver version is insufficient")`.
**Where:** system_info.py:361
**What it means (plain English):** torch built against CUDA 12.4 + driver still on 11.7 → init fails. Inner `try` at line 358 catches, but stores error; `cuda.available=False` despite GPU existing.
**Symptoms:** UI shows "no GPU" on a system with NVIDIA hardware.
**Root cause(s):** Driver/toolkit version mismatch.
**How to fix:**
1. Surface `info["cuda"]["error"]` in the UI as a red banner.
2. Document `nvidia-smi` driver-version expectations.
**Prevention / hardening:** Version-check `torch.version.cuda` vs. driver at startup.
**Related:** E.SYS.016.

---

## E.SYS.037 — DirectML provider listed but no device available
**Trigger:** ORT lists `DmlExecutionProvider`, but when used, returns "no DirectML adapters found".
**Where:** system_info.py:351-352
**What it means (plain English):** `DmlExecutionProvider` being in `ort.get_available_providers()` only means the binary was compiled in — NOT that a usable adapter exists. Headless servers, RDP sessions without GPU acceleration, or stripped Windows builds expose this discrepancy.
**Symptoms:** UI advertises DirectML; selecting it crashes session creation with `Failed to create DML device`.
**Root cause(s):** Provider availability != device availability.
**How to fix:**
1. Actually try to create a 1-op DML session to verify; cache result.
2. Or use `DXGI EnumAdapters1` to count GPU adapters before claiming DML is available.
**Prevention / hardening:** Distinguish "compiled-in" from "usable" in the UI label.
**Related:** —

---

## E.SYS.038 — TensorRT import succeeds but no compatible GPU
**Trigger:** `tensorrt` Python module imports; underlying GPU lacks TensorRT-compatible compute capability (< 7.5).
**Where:** system_info.py:371-373
**What it means (plain English):** TRT 10.x supports SM 7.5+ (Turing onward). Older Pascal (SM 6.x) loads the module but session creation fails. UI shows "+TensorRT" suffix incorrectly.
**Symptoms:** GPU summary lies about TRT support; session creation later errors.
**Root cause(s):** Import success != functional support.
**How to fix:**
1. Check compute capability via `torch.cuda.get_device_capability(0) >= (7, 5)`.
2. Only set `tensorrt.available=True` if both module imports AND device CC supports it.
**Prevention / hardening:** Probe with a minimal TRT engine build at detect time.
**Related:** E.SYS.036.

---

## E.SYS.039 — `gpu_unavailable_reason` never reports cuda runtime errors
**Trigger:** `cuda.error` set but `gpu_summary` is None; reason returned is generic.
**Where:** system_info.py:390-399
**What it means (plain English):** When CUDA path errors out (E.SYS.036), `info["cuda"]["error"]` holds the message but `gpu_unavailable_reason` ignores it.
**Symptoms:** UI says "Install PyTorch with CUDA" even though torch IS installed but driver-broken.
**Root cause(s):** Reason logic checks `torch_available` but not `cuda.error` content.
**How to fix:**
1. Add: `if gpu_info["cuda"].get("error"): return f"CUDA init failed: {gpu_info['cuda']['error']}"`.
**Prevention / hardening:** Surface the most-specific error first.
**Related:** E.SYS.036.

---

## E.SYS.040 — Concurrent affinity changes from multiple threads race
**Trigger:** Two threads call `set_process_affinity(mask)` concurrently with different masks.
**Where:** system_info.py:221-249
**What it means (plain English):** Affinity is process-global, not thread-local. Last write wins. UI thread + benchmark thread fighting over affinity → unpredictable.
**Symptoms:** Benchmark FPS variance; pinning seems to "wear off".
**Root cause(s):** Lack of synchronization around affinity state.
**How to fix:**
1. Wrap calls with a module-level `threading.Lock`.
2. Track current mask; refuse changes that would conflict with active workload.
**Prevention / hardening:** Single source of truth for affinity, set once at startup.
**Related:** E.SYS.026.

---
