# Chapter 4 — Screen Capture Errors

This chapter catalogs every error class that can occur in the screen-capture
layer of `dbd_autoSkillCheck`. The capture stack has two backends: **MSS**
(`dbd/utils/monitoring_mss.py`, cross-platform default) and **BetterCam**
(`dbd/utils/monitoring_bettercam.py`, optional Windows-only DXGI duplication).
Both are exposed to the Flask server in `dbd/web/server.py` through the
`/api/monitors`, `/api/preview`, and `/api/live-frame` endpoints, plus
the worker pipeline. Many failure modes are platform-specific (DXGI vs
Wayland vs TCC), some are timing-related (race between preview and worker),
and some are silent (`get_latest_frame()` returning `None`). Every entry below
maps a concrete trigger to its user-visible symptom and a tested fix.

---

## E.CAP.001 — `ImportError: No module named 'bettercam'`
**Trigger:** `from dbd.utils.monitoring_bettercam import Monitoring_bettercam` is executed before the `BETTERCAM_OK` gate in the caller, or the package is uninstalled.
**Where:** `dbd/utils/monitoring_bettercam.py` line 10 (`import bettercam`); `dbd/web/server.py` line 18 (gated import).
**What it means (plain English):** Python cannot find the `bettercam` package because it isn't installed in the active environment. BetterCam is an optional Windows-only dependency.
**Symptoms:** App crashes at startup with an `ImportError` traceback, or the BetterCam radio button never appears in the UI even on Windows.
**Root cause(s):** Optional extras not installed (`pip install bettercam`); wrong virtualenv active; bettercam wheel build failed silently on install.
**How to fix:**
1. Verify the env: `python -c "import bettercam; print(bettercam.__version__)"`.
2. Install: `pip install bettercam` (Windows only).
3. If the wheel fails to build, install the prebuilt wheel matching your Python ABI from the bettercam releases page.
4. Restart the app so `BETTERCAM_OK` re-evaluates.
**Prevention / hardening:** Keep the `if BETTERCAM_OK:` import gate in `server.py` — never import `monitoring_bettercam` unconditionally.
**Related:** E.CAP.002, E.CAP.003.

## E.CAP.002 — `ModuleNotFoundError` on non-Windows platforms
**Trigger:** A user on Linux or macOS tries to enable BetterCam, or a config file from a Windows machine is reused on Linux.
**Where:** `monitoring_bettercam.py` import statement.
**What it means (plain English):** BetterCam wraps Windows-only DXGI APIs; the wheel is not published for Linux/macOS.
**Symptoms:** `ModuleNotFoundError: No module named 'bettercam'` even after `pip install` succeeds in unusual environments; or `pip` refuses to find a matching wheel.
**Root cause(s):** Cross-platform configs not gated; user assumes optional deps install everywhere.
**How to fix:**
1. Force MSS in the UI on non-Windows.
2. In `_allowed_monitoring_libs()` rely on `BETTERCAM_OK`, which is `False` on Linux/macOS by design.
3. Educate users: BetterCam is Windows-only.
**Prevention / hardening:** Have `inference_worker.BETTERCAM_OK` set to `False` whenever `sys.platform != "win32"`, even if a stray `bettercam` wheel got installed.
**Related:** E.CAP.001, E.CAP.010.

## E.CAP.003 — Stale `bettercam` version missing `_bettercam__factory`
**Trigger:** Older bettercam release where the private factory has a different name, or the lazy initializer never populated it.
**Where:** `_factory()` in `monitoring_bettercam.py` lines 16–35.
**What it means (plain English):** The code reaches into bettercam's private internals for the output factory. If neither `__factory` nor name-mangled `_bettercam__factory` exists, monitor enumeration fails outright.
**Symptoms:** `RuntimeError: bettercam factory unavailable — incompatible bettercam version` raised from `_factory()`. `/api/monitors?monitoring_lib=bettercam` returns 503.
**Root cause(s):** Bettercam refactor renamed/removed the private attribute; the warm-up `bettercam.create()` also failed silently and didn't populate the factory.
**How to fix:**
1. Upgrade bettercam: `pip install -U bettercam`.
2. Pin a known-good version in `requirements.txt`.
3. If pinning is undesired, fall back to MSS until support is added.
**Prevention / hardening:** Add a smoke-test on import that resolves `_factory()` once and logs the bettercam version; gate `BETTERCAM_OK` on success.
**Related:** E.CAP.004, E.CAP.020.

## E.CAP.004 — Lazy `_factory()` warm-up `create()` raises and is swallowed
**Trigger:** Inside `_factory()` the recovery branch calls `bettercam.create()` to force initialization; that call fails (no DXGI device, locked desktop, etc.).
**Where:** `monitoring_bettercam.py` lines 27–31.
**What it means (plain English):** The fallback that tries to *make* the factory exist by creating a throwaway camera also fails, but we eat the exception and continue. The next attribute lookup fails too, leaving a misleading "factory unavailable" error.
**Symptoms:** `RuntimeError: bettercam factory unavailable` even though the real cause was a `RuntimeError: GetOutputDuplication failed`.
**Root cause(s):** Locked/RDP desktop, no GPU adapter, exclusive fullscreen DRM app, or D3D11 device creation refused.
**How to fix:**
1. Log the swallowed exception: replace `except Exception: pass` with `except Exception as e: log.warning("bettercam warm-up failed: %s", e)`.
2. Reproduce on an unlocked desktop with no exclusive-fullscreen apps.
3. Update GPU driver.
**Prevention / hardening:** Re-raise warm-up failures wrapped with the original exception via `raise RuntimeError(...) from e` so the cause chain reaches the user.
**Related:** E.CAP.005, E.CAP.014.

## E.CAP.005 — `bettercam.create()` returns `None` on locked desktop / RDP
**Trigger:** The user starts the app over RDP, in a locked Windows session, or after switching desktops while bettercam is initializing.
**Where:** `Monitoring_bettercam.start()` line 55; warm-up in `_factory()` line 28.
**What it means (plain English):** DXGI desktop duplication needs an active session; on a locked screen the OS denies the duplication and bettercam returns `None`.
**Symptoms:** `AttributeError: 'NoneType' object has no attribute 'start'` shortly after start; or hangs at first `get_latest_frame()`.
**Root cause(s):** Session 0 isolation; LockApp.exe owning the desktop; RDP rerouting display to the dummy DXGI adapter.
**How to fix:**
1. Unlock the console session before starting.
2. Use MSS over RDP (works through GDI).
3. Add a `None` check after `bettercam.create()` and raise a clear error.
**Prevention / hardening:** Detect RDP via `GetSystemMetrics(SM_REMOTESESSION)` and force MSS. Add a `None`-guard:
```python
cam = bettercam.create(...)
if cam is None:
    raise RuntimeError("bettercam.create() returned None — desktop locked or RDP?")
```
**Related:** E.CAP.004, E.CAP.013.

## E.CAP.006 — `bettercam.release_camera()` raises during stop
**Trigger:** `Monitoring_bettercam.stop()` calls `bettercam.release_camera(monitor_id)` to free the device handle for re-creation.
**Where:** Lines 71–76.
**What it means (plain English):** Releasing the camera can throw if bettercam's internal state is already torn down (double-stop, GC race, or version where `release_camera` doesn't exist).
**Symptoms:** Worker shutdown logs show "release_camera failed"; subsequent `bettercam.create()` on the same `output_idx` fails with "duplicate device handle".
**Root cause(s):** Older bettercam versions lacked `release_camera`; double-stop from both `__exit__` and an explicit `stop()`; GC of `cam` already triggered the C++ destructor.
**How to fix:**
1. The current code already wraps the call in `try/except Exception: pass` — verify this is preserved.
2. After upgrading bettercam, retest re-creation on the same monitor index.
3. Restart the app to clear stuck handles.
**Prevention / hardening:** Make `stop()` idempotent (already is via the `cam is None` early return); log swallowed errors at debug level.
**Related:** E.CAP.005, E.CAP.025.

## E.CAP.007 — Monitor index out of range (BetterCam `IndexError`)
**Trigger:** UI passes `monitor_id=2` but only one monitor is detected; or a monitor was unplugged after `/api/init` enumerated monitors.
**Where:** `_get_monitor_region()` in `monitoring_bettercam.py` lines 86–89; surfaced through `/api/preview` and `/api/start`.
**What it means (plain English):** The user-supplied monitor index is past the last available output.
**Symptoms:** `IndexError: Monitor index 2 out of range (have 1 monitor(s))`. `/api/preview` returns 400 with "invalid monitor_id"; `/api/start` returns 400.
**Root cause(s):** Hot-unplugged display; saved config from a multi-monitor machine reused on a single-monitor laptop; UI cached an old monitor list.
**How to fix:**
1. Reload `/api/init` or re-enumerate via `/api/monitors`.
2. Pick a valid monitor in the UI.
3. Don't persist monitor IDs across hardware changes.
**Prevention / hardening:** On startup, validate `monitor_id` against current `_factory().outputs[0]` length and fall back to 0 with a warning.
**Related:** E.CAP.008, E.CAP.018.

## E.CAP.008 — `KeyError` from MSS `sct.monitors[monitor_id]`
**Trigger:** Monitor index is out of bounds for the MSS backend (e.g. `monitor_id=99`).
**Where:** `Monitoring_mss._get_monitor_region` line 60; `get_monitors_info` line 53.
**What it means (plain English):** MSS exposes monitors as a list and accepts integer indices; `sct.monitors[99]` raises `IndexError` (or `KeyError` on some platforms where MSS internally uses dicts).
**Symptoms:** `/api/preview` returns 400 "invalid monitor_id"; `/api/start` returns 400. Log shows `IndexError` or `KeyError`.
**Root cause(s):** Stale UI selection; off-by-one (MSS uses 1-based; index 0 is the virtual aggregate desktop).
**How to fix:**
1. The MSS UI uses 1-based IDs. Verify the dropdown values start at 1, not 0.
2. Re-enumerate monitors after a display change.
3. The `/api/preview` handler already catches `IndexError` and `KeyError` — keep both in the exception tuple.
**Prevention / hardening:** Validate `monitor_id < len(sct.monitors)` before indexing.
**Related:** E.CAP.007, E.CAP.018.

## E.CAP.009 — `mss.exception.ScreenShotError` from `sct.grab()`
**Trigger:** MSS fails to capture (Win32 GetWindowDC returned NULL, X11 BadMatch, GDI handle leak after thousands of grabs).
**Where:** `Monitoring_mss.get_raw_frame` line 77.
**What it means (plain English):** The OS refused the screen-grab request. MSS surfaces this as `ScreenShotError`.
**Symptoms:** Worker dies; `/api/preview` returns 500 with "ScreenShotError: ...".
**Root cause(s):** GDI object leak; secure desktop active (UAC prompt, Ctrl+Alt+Del); display device removed; X server connection lost.
**How to fix:**
1. Restart the worker.
2. On Windows, dismiss the UAC/secure-desktop prompt before retrying.
3. Reduce capture rate to limit GDI handle pressure.
**Prevention / hardening:** Wrap `get_raw_frame()` with a single retry on `ScreenShotError`; recreate the `mss()` instance on persistent failure.
**Related:** E.CAP.024, E.CAP.029.

## E.CAP.010 — MSS on Wayland (X11-only on Linux)
**Trigger:** Linux user on a Wayland session (GNOME 41+, KDE 5.24+, Sway).
**Where:** `Monitoring_mss.start()` calls `mss()`, which probes XGetImage.
**What it means (plain English):** MSS only supports X11 on Linux. On Wayland the X server is missing or sandboxed (Xwayland exists but doesn't expose other windows for capture).
**Symptoms:** Black/empty frames; `XGetImage failed`; or only the Xwayland surface is captured (a black rectangle).
**Root cause(s):** Wayland forbids unrestricted screen capture for security; MSS hasn't implemented the PipeWire/portal path.
**How to fix:**
1. Log out and pick "GNOME on Xorg" / "Plasma X11" at the login screen.
2. Or use a portal-based capture lib (`pyscreenshot` with `dbus` backend) — not currently wired in.
3. Document Wayland as unsupported.
**Prevention / hardening:** Detect `XDG_SESSION_TYPE=wayland` at startup and surface a clear error in `/api/init`.
**Related:** E.CAP.022, E.CAP.026.

## E.CAP.011 — macOS Screen Recording TCC permission denied
**Trigger:** First run on macOS 10.15+; user has not granted Screen Recording permission to the Python interpreter / Terminal.
**Where:** `Monitoring_mss.start()`; the system silently returns black frames.
**What it means (plain English):** macOS requires explicit user consent for screen capture, recorded in TCC.db. Without it, captures succeed structurally but pixels are all black.
**Symptoms:** Preview is solid black; inference always returns "no skill check"; no exception is raised.
**Root cause(s):** Missing entry in `System Settings → Privacy & Security → Screen Recording`.
**How to fix:**
1. Add the host app (Terminal, iTerm, VS Code, or the bundled Python) to Screen Recording.
2. Quit and relaunch the host app — TCC consent is process-lifetime cached.
3. On Apple Silicon, also add Rosetta if running x86_64 Python under translation.
**Prevention / hardening:** At startup, capture a 4×4 region and check whether all pixels are zero — if so, surface "macOS Screen Recording permission missing".
**Related:** E.CAP.022, E.CAP.026.

## E.CAP.012 — HiDPI / fractional scaling clip
**Trigger:** Windows display scaling set to 125%, 150%, 175%; or macOS Retina; or Linux fractional scaling.
**Where:** `_get_monitor_region` in both backends — uses `monitor["height"]` / `monitor.resolution` directly.
**What it means (plain English):** The capture region is computed in *physical* pixels, but the user reasons about *logical* pixels. With non-integer scaling the centered crop is offset and may clip.
**Symptoms:** Preview is shifted up-left or down-right; skill check arc partly cropped; detection accuracy drops at non-100% scaling.
**Root cause(s):** No DPI awareness manifest; mss returns raw pixels but the OS reports virtual coords.
**How to fix:**
1. Set Windows DPI to 100% on the gaming monitor (recommended).
2. Or call `ctypes.windll.shcore.SetProcessDpiAwareness(2)` early in main.
3. Verify with the preview that the crop is centered.
**Prevention / hardening:** Make the app per-monitor DPI aware via a manifest; document supported scalings.
**Related:** E.CAP.022, E.CAP.030.

## E.CAP.013 — Multi-monitor refresh-rate mismatch
**Trigger:** Primary monitor is 144 Hz, secondary is 60 Hz; bettercam targets `target_fps=240` on the slower monitor.
**Where:** `Monitoring_bettercam.start()` line 58 (`target_fps=self.target_fps`).
**What it means (plain English):** DXGI duplication caps at the monitor's refresh rate. Asking for 240 fps on a 60 Hz panel just produces duplicate frames; some bettercam builds fail outright.
**Symptoms:** Tool FPS plateaus at the panel's refresh rate; warning logs about target_fps not met; occasional "GetFrameLatencyWaitableObject timed out".
**Root cause(s):** Hard-coded `target_fps=240`; user attached game to the wrong output.
**How to fix:**
1. Verify the game runs on the monitor whose `monitor_id` you selected.
2. Set `target_fps` to ≤ panel refresh rate.
3. Or accept the cap — duplicates aren't fatal.
**Prevention / hardening:** Query the monitor's refresh rate and pass `target_fps=min(240, rate)`.
**Related:** E.CAP.005, E.CAP.014.

## E.CAP.014 — Cursor visible in MSS but not in BetterCam (or vice versa)
**Trigger:** User compares preview JPEGs between the two backends and sees cursor artifacts in only one.
**Where:** Both backends.
**What it means (plain English):** MSS uses GDI `BitBlt` which by default *includes* the hardware cursor. BetterCam uses DXGI desktop duplication, which delivers cursor info as a separate sprite — bettercam's default does not composite it.
**Symptoms:** Cursor sometimes occludes the skill-check arc on MSS but never on BetterCam (or vice versa); inference jitter when cursor crosses the crop region.
**Root cause(s):** Different OS APIs, different cursor compositing behavior.
**How to fix:**
1. In-game, hide the cursor (most games do this anyway during skill checks).
2. Move the cursor off the center of the screen during gameplay.
3. Switch backends if the cursor consistently sits in your crop region.
**Prevention / hardening:** Document the difference in the README.
**Related:** E.CAP.012, E.CAP.018.

## E.CAP.015 — `get_frame_np()` returns `None`
**Trigger:** BetterCam called before its first frame has been captured (race during start), or no display change since the last call.
**Where:** `Monitoring_bettercam.get_frame_np` lines 104–108; downstream consumers in `inference_worker` and `_grab_preview_jpeg`.
**What it means (plain English):** DXGI desktop duplication only delivers frames *on change*. On a static screen, the buffer can be empty. BetterCam returns `None`; consumers must handle it.
**Symptoms:** `_grab_preview_jpeg` returns `None` → `/api/preview` 503 "encode failed (game window may be minimized)"; worker logs "frame is None — dropping".
**Root cause(s):** Static desktop; `max_buffer_len=1` evicted the only available frame; race during `start()`.
**How to fix:**
1. Move the mouse or cause any pixel change before requesting preview.
2. Increase `max_buffer_len` to 2.
3. After `start()`, busy-wait up to 100 ms for the first non-None frame.
**Prevention / hardening:** Add a warm-up loop in `start()` that polls `get_latest_frame()` until non-None or timeout, before declaring the camera ready.
**Related:** E.CAP.017, E.CAP.027.

## E.CAP.016 — Race between `/api/preview` and the running worker (BetterCam)
**Trigger:** User opens the monitor selector while the worker is already running; both attempt to acquire the same DXGI output.
**Where:** `_grab_preview_jpeg` line 67 creates a new `Monitoring_bettercam`; the worker already has one.
**What it means (plain English):** BetterCam serializes per output index. A second `bettercam.create(output_idx=1)` while the worker holds 1 fails with "duplicate device handle" or starves one of the two consumers.
**Symptoms:** `/api/preview` returns 500 with bettercam error; worker frame rate drops; or both produce black frames briefly.
**Root cause(s):** No coordination between preview and worker for the same monitor.
**How to fix:**
1. While the worker is running, route `/api/preview` to `/api/live-frame` instead (which reads cached worker frames).
2. Or stop the worker before opening the monitor picker.
**Prevention / hardening:** In `api_preview`, if `state.status == "running"` and the requested monitor matches the worker's monitor, return the live frame instead of grabbing a new one.
**Related:** E.CAP.027, E.CAP.034.

## E.CAP.017 — Race between `/api/preview` and worker (MSS)
**Trigger:** Same as E.CAP.016 but with MSS. Less destructive — MSS can be re-instanced — but still allocates redundant GDI resources.
**Where:** `_grab_preview_jpeg` line 70.
**What it means (plain English):** Two `mss()` instances coexisting on the same thread is fine, but cross-thread MSS use can crash on Windows because the underlying GDI HDC is thread-affine.
**Symptoms:** Sporadic `ScreenShotError` from preview while worker is running; GDI handle leak warnings.
**Root cause(s):** MSS's `mss()` instance is created and destroyed per request, which is OK; problems arise if a single instance is shared across threads.
**How to fix:**
1. Keep `_grab_preview_jpeg` instantiating a fresh `Monitoring_mss` (already does).
2. Never share a single `mss()` between threads.
**Prevention / hardening:** Add a thread-local check in `Monitoring_mss.start()` that asserts the current thread.
**Related:** E.CAP.016, E.CAP.029, E.CAP.034.

## E.CAP.018 — `/api/monitors` with bad `monitoring_lib` parameter
**Trigger:** User crafts a URL like `/api/monitors?monitoring_lib=foo`.
**Where:** `server.py` lines 156–164.
**What it means (plain English):** The server validates the lib against `_allowed_monitoring_libs()` and returns 400.
**Symptoms:** HTTP 400 `{"error": "unknown monitoring_lib: foo"}`.
**Root cause(s):** UI bug, stale frontend cache, or a typo by an integrator.
**How to fix:**
1. Use `mss` or `bettercam` (and only `mss` if `BETTERCAM_OK=False`).
2. Reload `/api/init` to discover allowed libs.
**Prevention / hardening:** The frontend should derive the dropdown options from `/api/init`'s `monitoring_libs` array, never hard-code them.
**Related:** E.CAP.019, E.CAP.001.

## E.CAP.019 — `/api/preview` with non-integer `monitor_id`
**Trigger:** Query string `?monitor_id=abc`.
**Where:** `server.py` lines 173–175.
**What it means (plain English):** The handler does `int(request.args.get(...))`, catches `(TypeError, ValueError)`, and returns 400 "monitor_id must be int".
**Symptoms:** HTTP 400.
**Root cause(s):** UI bug; missing or empty parameter.
**How to fix:**
1. Send a valid integer matching one returned by `/api/monitors`.
**Prevention / hardening:** UI should always pass a numeric value; treat `null`/empty as "default 1" client-side.
**Related:** E.CAP.018, E.CAP.020.

## E.CAP.020 — `/api/preview` with valid type but invalid monitor index
**Trigger:** `?monitor_id=99` on a single-monitor system.
**Where:** `server.py` lines 178–180; raises `IndexError` or `KeyError` from the underlying capture.
**What it means (plain English):** The integer parsed fine but no such monitor exists. Caught and returned as 400 "invalid monitor_id".
**Symptoms:** HTTP 400 `{"error": "invalid monitor_id: ..."}`.
**Root cause(s):** Stale UI; hot-unplugged display.
**How to fix:**
1. Re-enumerate via `/api/monitors`.
2. Pick a valid index.
**Prevention / hardening:** UI invalidates cached monitor list on `/api/preview` 400.
**Related:** E.CAP.007, E.CAP.008.

## E.CAP.021 — JPEG encode failure in `_grab_preview_jpeg`
**Trigger:** `cv2.imencode(".jpg", bgr, ...)` returns `ok=False`.
**Where:** `server.py` lines 76–77.
**What it means (plain English):** OpenCV failed to encode the array as JPEG. Rare but can happen if `bgr` has unexpected dtype, zero dimensions, or 4 channels.
**Symptoms:** `/api/preview` returns 503 "encode failed (game window may be minimized)".
**Root cause(s):** Frame became `None` between capture and encode (impossible in current code but defensive); or a non-`uint8` dtype slipped through; or the frame is 0×0.
**How to fix:**
1. Verify `frame.dtype == np.uint8` before encoding.
2. Verify `frame.shape == (crop_size, crop_size, 3)`.
3. If consistent, install a known-good OpenCV build (`pip install -U opencv-python`).
**Prevention / hardening:** Log the array shape/dtype when `ok=False`.
**Related:** E.CAP.015, E.CAP.030.

## E.CAP.022 — Live-frame caching stale when worker idle
**Trigger:** User reads `/api/live-frame` after stopping the worker; cached frame is from the previous run.
**Where:** `server.py` lines 189–194; `state.get_live_frame()` returns whatever is stored.
**What it means (plain English):** The live frame is updated only when the worker is running. After stop, `state.get_live_frame()` either returns the last frame from the previous session or `None` (causing 404).
**Symptoms:** `/api/live-frame` returns a frame from 5 minutes ago, or 404; users confused why the preview "froze".
**Root cause(s):** No automatic invalidation on stop.
**How to fix:**
1. Always pair `/api/live-frame` polling with `/api/status` — only show it when status is `running`.
2. Or call `state.reset_for_run()` to clear cached frames.
**Prevention / hardening:** Have `state.set_status("idle")` clear the cached live frame so 404 is returned consistently.
**Related:** E.CAP.016, E.CAP.027.

## E.CAP.023 — Monitor enumeration returns empty list
**Trigger:** GPU adapter not found, no displays attached (headless server), or bettercam outputs collection is empty.
**Where:** `Monitoring_bettercam.get_monitors_info` line 80; `Monitoring_mss.get_monitors_info` lines 51–55.
**What it means (plain English):** `_factory().outputs[0]` is empty, or `sct.monitors[1:]` is empty.
**Symptoms:** UI dropdown is empty; `/api/init` returns `monitors: []`; `/api/start` rejects with "monitor_id required" because no value was selected.
**Root cause(s):** Headless box; all monitors disabled in Windows Display settings; bettercam initialized before any output existed.
**How to fix:**
1. Plug in (or virtually attach) a display.
2. Switch to MSS, which reports the virtual desktop in `monitors[0]`.
3. Restart the app after enabling displays.
**Prevention / hardening:** When the list is empty, return a clear "no displays detected" error from `/api/init`.
**Related:** E.CAP.005, E.CAP.026.

## E.CAP.024 — Frame shape mismatch after capture
**Trigger:** A monitor returns a region smaller than `crop_size×crop_size` because it sits at the edge of a virtual desktop with negative coords, or DXGI returned a partial frame.
**Where:** Both backends — the resize fallback in `get_frame_np` (lines 93–94 MSS, lines 109–110 BetterCam).
**What it means (plain English):** The captured frame doesn't match the requested size; both backends fall back to `cv2.resize` to fix it. If the frame has zero rows/cols, resize fails.
**Symptoms:** `cv2.error: OpenCV(...) resize.cpp:... !ssize.empty()`; preview returns 500.
**Root cause(s):** Empty frame (0×0); virtual-desktop coordinate underflow; bettercam clipping at edge of output.
**How to fix:**
1. Validate frame is non-empty before resize: `if frame.size == 0: return None`.
2. Ensure the requested region is fully inside the monitor bounds.
**Prevention / hardening:** Clamp `_get_monitor_region` outputs to monitor size; assert `width > 0 and height > 0`.
**Related:** E.CAP.012, E.CAP.030.

## E.CAP.025 — BGRA-vs-RGB channel-order mismatch
**Trigger:** Caller assumes RGB but reads `frame.bgra` directly; or vice versa.
**Where:** `Monitoring_mss.get_frame_pil` line 81 (`Image.frombytes("RGB", ..., "BGRX")`); `get_frame_np` line 91 (`np.flip(frame[:, :, :3], 2)`).
**What it means (plain English):** MSS captures BGRA; PIL is told to interpret as BGRX→RGB; numpy is flipped on the channel axis. Any downstream code that bypasses these helpers will see wrong colors.
**Symptoms:** Skill-check colors look swapped (red where blue should be); inference accuracy drops.
**Root cause(s):** Custom code that calls `np.array(frame)` without the channel flip.
**How to fix:**
1. Always go through `get_frame_np()` / `get_frame_pil()`.
2. If hand-rolling, use `cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)`.
**Prevention / hardening:** Document the channel-order contract: `get_frame_np()` always returns RGB uint8.
**Related:** E.CAP.021, E.CAP.030.

## E.CAP.026 — HiDPI on Linux returns scaled coords
**Trigger:** Linux with `gdk-scale=2` or X11 random DPI; MSS reports logical sizes but pixels are physical.
**Where:** `Monitoring_mss._get_monitor_region`.
**What it means (plain English):** On scaled X11 sessions, `monitor['width']`/`['height']` may be in logical units while pixel buffers are physical, so the centered crop is wrong.
**Symptoms:** Off-center crop on Linux laptops with hi-dpi panels.
**Root cause(s):** `XRandR` reports inconsistent units depending on whether `Xft.dpi` or `gdk-scale` is set.
**How to fix:**
1. Unset `GDK_SCALE` and `QT_SCALE_FACTOR` in the launching shell.
2. Use a single DPI globally (96 or 192) rather than fractional.
**Prevention / hardening:** Document Linux DPI requirements; recommend running under X11 at 100% scale.
**Related:** E.CAP.010, E.CAP.012.

## E.CAP.027 — OneDrive / antivirus locking captures
**Trigger:** Some antivirus / OneDrive Files-On-Demand setups hook GDI and intermittently delay or reject captures.
**Where:** Any MSS grab on Windows.
**What it means (plain English):** Security software inserts itself in the GDI / D3D pipeline, occasionally yielding `ScreenShotError` or partial frames.
**Symptoms:** Random preview failures; high jitter in worker FPS; bettercam timeouts.
**Root cause(s):** Filter drivers; hooked `BitBlt`.
**How to fix:**
1. Add the project folder and the Python interpreter to the AV exclusion list.
2. Pause OneDrive sync while running.
3. Disable "controlled folder access".
**Prevention / hardening:** Document AV exclusions in install steps.
**Related:** E.CAP.009, E.CAP.029.

## E.CAP.028 — Vulkan / D3D12 fullscreen apps blocking DXGI duplication
**Trigger:** A Vulkan or D3D12 game runs in exclusive fullscreen with `ALLOW_TEARING`; bettercam can't duplicate.
**Where:** `bettercam.create()`; subsequent `get_latest_frame()` returns `None`.
**What it means (plain English):** Modern presentation modes (independent flip, exclusive fullscreen) sometimes bypass the desktop window manager. DXGI desktop duplication then sees a black or stale buffer.
**Symptoms:** Black preview; worker reports "frame is None" indefinitely; works fine in windowed mode.
**Root cause(s):** Independent-flip presentation; DRM-protected content.
**How to fix:**
1. Switch the game to borderless windowed mode.
2. Or use MSS, which uses GDI and is unaffected for non-DRM content.
3. Disable Game Mode.
**Prevention / hardening:** Document "Borderless Windowed required for BetterCam" in README.
**Related:** E.CAP.005, E.CAP.013.

## E.CAP.029 — `mss.sct_init` truthiness check
**Trigger:** Code does `if self.sct:` instead of `if self.sct is not None:`. After `mss()` is closed, the object may be falsy.
**Where:** `Monitoring_mss.stop` line 46 — uses the safe `is not None` form. A regression to `if self.sct:` would break.
**What it means (plain English):** Some MSS wrappers override `__bool__` based on whether the underlying handle is open. A closed `mss()` evaluates as False, so `if self.sct: self.sct.close()` skips cleanup, leaking GDI handles.
**Symptoms:** GDI handle count rises over time (visible in Process Explorer); eventually `ScreenShotError`.
**Root cause(s):** Implicit truthiness on a non-bool object.
**How to fix:**
1. Always compare with `is None` / `is not None`.
2. Audit all references to `self.sct`.
**Prevention / hardening:** Lint rule (`flake8-comparable-truthy` or custom) for MSS instances.
**Related:** E.CAP.009, E.CAP.024.

## E.CAP.030 — Multiple `mss()` instances per thread
**Trigger:** Caller instantiates `mss()` repeatedly without closing — e.g. inside a tight loop.
**Where:** `Monitoring_mss.get_monitors_info` line 52 (`with mss() as sct:` — correctly using context manager); `_get_monitor_region` line 59 (also correct). Risk lives in user code that bypasses `Monitoring_mss`.
**What it means (plain English):** Each `mss()` allocates platform-specific state (HDC on Windows, X connection on Linux). Without `close()` they leak.
**Symptoms:** "GDI objects" counter climbs to 10000 then `ScreenShotError`; or X server refuses new connections.
**Root cause(s):** Missing `with` block; explicit `mss()` calls without `.close()`.
**How to fix:**
1. Always use `with mss() as sct:` (or call `.close()` in `finally`).
2. Reuse a single instance across calls in a thread.
**Prevention / hardening:** Provide and document `Monitoring_mss` as the only public API; mark direct `mss()` use as discouraged.
**Related:** E.CAP.009, E.CAP.029.

## E.CAP.031 — Worker stop didn't release bettercam → next start fails
**Trigger:** Worker is killed mid-flight (process crash, force-quit) so `Monitoring_bettercam.stop()` never ran; the next `bettercam.create()` on the same `output_idx` fails.
**Where:** `monitoring_bettercam.py` lines 60–76.
**What it means (plain English):** BetterCam keeps a per-output device handle. If `release_camera` isn't called, the OS thinks the handle is still owned by the previous process and refuses re-creation.
**Symptoms:** "duplicate device handle" / `RuntimeError` from `bettercam.create()` after restart.
**Root cause(s):** Crash bypassed `stop()`; second start before OS reclaimed the handle.
**How to fix:**
1. Wait 5–10 seconds and retry.
2. Restart the app; failing that, restart the OS.
3. Stop forcing-kill the process — let `/api/stop` run cleanly.
**Prevention / hardening:** Register an `atexit` handler that calls `release_camera` for any active monitor.
**Related:** E.CAP.005, E.CAP.006.

## E.CAP.032 — `with mss()` re-entry on a single instance
**Trigger:** Calling `Monitoring_mss.start()` twice without `stop()` overwrites `self.sct`, leaking the previous instance.
**Where:** `Monitoring_mss.start` line 43.
**What it means (plain English):** Idempotency violation. Worker restart paths must call `stop()` first.
**Symptoms:** GDI handle leak; doubled MSS resources per worker restart.
**Root cause(s):** Missing guard in `start()` — should early-return when `self.sct is not None`.
**How to fix:**
1. Wrap `start()` with `if self.sct is not None: return`.
2. Ensure `stop()` is always called before re-`start()`.
**Prevention / hardening:** Match BetterCam's pattern (lines 53–54) which does early-return on `is not None`.
**Related:** E.CAP.029, E.CAP.030.

## E.CAP.033 — Crop region negative coords on multi-monitor
**Trigger:** Secondary monitor positioned to the left of primary; `monitor['left']` is negative; arithmetic gives correct numbers but downstream Win32 calls reject negatives.
**Where:** `Monitoring_mss._get_monitor_region` lines 64–69.
**What it means (plain English):** Virtual-desktop coordinates can be negative (origin at primary monitor). MSS handles this fine, but custom callers using Win32 APIs may not.
**Symptoms:** Wrong region captured on a secondary monitor placed left/above the primary; preview is blank.
**Root cause(s):** Mismatched coordinate spaces.
**How to fix:**
1. Trust MSS's `monitor['top']`/`['left']` — they already include the offset.
2. Don't compose with screen-relative coords from elsewhere.
**Prevention / hardening:** Add an integration test for left-positioned secondary monitors.
**Related:** E.CAP.012, E.CAP.024.

## E.CAP.034 — Preview JPEG encode wins race vs worker capture
**Trigger:** Heavy `/api/preview` polling from the UI while the worker captures; both contend for GPU/GDI.
**Where:** `_grab_preview_jpeg` opens a fresh `Monitoring_*` instance per request.
**What it means (plain English):** Each preview call allocates and tears down a capture pipeline. Under high frequency this starves the worker.
**Symptoms:** Worker FPS drops while monitor selector is open; preview itself looks fine.
**Root cause(s):** No throttling on `/api/preview`; worker and preview share the same GPU output for bettercam.
**How to fix:**
1. Throttle the UI to ≤ 2 preview requests per second.
2. While worker runs, redirect preview to `/api/live-frame`.
**Prevention / hardening:** Add a per-IP rate limit to `/api/preview`.
**Related:** E.CAP.016, E.CAP.022.

## E.CAP.035 — Crop size larger than monitor height
**Trigger:** Tiny external display (e.g. 480p capture card preview) where `crop_size=520` exceeds `height`.
**Where:** `_get_monitor_region` in both backends.
**What it means (plain English):** The computed `object_size` exceeds the monitor; resulting region extends below the screen, and capture returns zero-size or an out-of-bounds error.
**Symptoms:** `IndexError`/`ScreenShotError`; `cv2.error: !ssize.empty()`.
**Root cause(s):** Hardcoded `crop_size=520` for preview, no clamp to monitor height.
**How to fix:**
1. Clamp `object_size` to `min(object_size, monitor_height, monitor_width)`.
2. Don't use sub-VGA monitors for skill-check capture.
**Prevention / hardening:** Add a `_clamp_region(region, monitor)` helper used by both backends.
**Related:** E.CAP.024, E.CAP.033.

## E.CAP.036 — `bettercam.create()` deadlock on driver bug
**Trigger:** Older NVIDIA / AMD drivers occasionally hang in `IDXGIOutputDuplication::Create`. BetterCam blocks indefinitely.
**Where:** `Monitoring_bettercam.start()` line 55.
**What it means (plain English):** A driver bug causes the DXGI duplication factory to never return; BetterCam has no internal timeout.
**Symptoms:** `/api/start` hangs; worker thread stuck in `start()`; UI shows "starting" forever.
**Root cause(s):** Outdated GPU driver; conflicting DXGI consumer (OBS, Discord overlay, NVIDIA ShadowPlay).
**How to fix:**
1. Update GPU drivers.
2. Close other DXGI consumers (OBS Game Capture, Discord overlay, GeForce Experience Highlights).
3. Restart the app and retry.
**Prevention / hardening:** Run `bettercam.create()` in a watchdog thread with a 5 s timeout; on timeout, raise and fall back to MSS.
**Related:** E.CAP.005, E.CAP.013, E.CAP.028.

## E.CAP.037 — `/api/preview` succeeds but UI shows broken image
**Trigger:** Browser receives the JPEG with wrong `Content-Type` or zero-byte body due to upstream proxy buffering.
**Where:** `server.py` line 187 (`send_file(BytesIO(jpeg), mimetype="image/jpeg")`).
**What it means (plain English):** Server-side everything works, but a reverse proxy (nginx, Caddy) strips or rewrites the Content-Type, or buffers the response.
**Symptoms:** Browser shows broken-image icon; HTTP 200 with image/jpeg in dev tools but body empty.
**Root cause(s):** Proxy mis-configuration; CSP blocking inline JPEG; antivirus scanning the response.
**How to fix:**
1. Bypass the proxy and hit Flask directly to confirm.
2. Set `proxy_buffering off;` in nginx for this route.
3. Whitelist the path in the AV's web filter.
**Prevention / hardening:** Document required proxy settings.
**Related:** E.CAP.021, E.CAP.022.

## E.CAP.038 — `make_monitoring` misroutes to wrong backend
**Trigger:** `inference_worker.make_monitoring` called with `monitoring_lib="bettercam"` but `BETTERCAM_OK=False`.
**Where:** `dbd/web/inference_worker.py` (factory imported into `server.py` line 14).
**What it means (plain English):** The worker's factory must respect `BETTERCAM_OK`; if it constructs a BetterCam instance anyway, import succeeds but use fails.
**Symptoms:** Worker dies during start with `NameError: name 'Monitoring_bettercam' is not defined` or `ImportError`.
**Root cause(s):** Server validates `monitoring_lib` against `_allowed_monitoring_libs()`, but a stale config or direct API call bypasses that.
**How to fix:**
1. Always go through `_allowed_monitoring_libs()` in the server.
2. In `make_monitoring`, raise if `BETTERCAM_OK=False` and `lib=="bettercam"`.
**Prevention / hardening:** Centralize the `BETTERCAM_OK` check; fail fast at config-validation time, not in the worker.
**Related:** E.CAP.001, E.CAP.018.

## E.CAP.039 — Worker leak on context-manager exit failure
**Trigger:** `_grab_preview_jpeg` uses `with Monitoring_bettercam(...) as mon:`; if `__exit__` swallows an exception from `stop()`, resources may leak.
**Where:** `server.py` lines 67–71; `Monitoring_bettercam.stop` lines 60–76 (already swallows internally).
**What it means (plain English):** Context-manager `__exit__` runs `stop()`, which catches all exceptions. That's by design but means a failing release is invisible.
**Symptoms:** Subsequent preview calls fail with "duplicate device handle" until the OS cleans up.
**Root cause(s):** Silent error eating in `stop()`.
**How to fix:**
1. Log swallowed exceptions at WARNING.
2. Wait briefly before re-trying preview after a failure.
**Prevention / hardening:** Surface release failures in metrics so they don't go unnoticed.
**Related:** E.CAP.006, E.CAP.031.

## E.CAP.040 — Frame returned as `None` from preview path
**Trigger:** `_grab_preview_jpeg` receives `None` from `mon.get_frame_np()` (BetterCam pre-first-frame).
**Where:** `server.py` lines 73–74.
**What it means (plain English):** Returns `None`; the route then returns 503 "encode failed (game window may be minimized)". The error message blames a minimized window but the real cause is BetterCam's pre-first-frame return value.
**Symptoms:** Preview shows "encode failed" message even with the game visible.
**Root cause(s):** BetterCam returns `None` until the first GPU-side frame change.
**How to fix:**
1. Move the cursor or alt-tab to force a frame.
2. Switch to MSS (always returns a frame).
3. Improve the error message to distinguish "frame None" from "encode failed".
**Prevention / hardening:** In the BetterCam constructor, warm-up loop until the first non-None frame (≤ 200 ms).
**Related:** E.CAP.015, E.CAP.021.

## E.CAP.041 — `Image.frombytes` raises `ValueError` on size mismatch (MSS)
**Trigger:** `frame.size` and `frame.bgra` length don't agree (corrupted MSS buffer, very rare).
**Where:** `Monitoring_mss.get_frame_pil` line 81.
**What it means (plain English):** PIL validates that `len(bgra) == width*height*4`. If the MSS buffer was truncated, PIL raises.
**Symptoms:** `ValueError: not enough image data`; `/api/preview` 500.
**Root cause(s):** MSS internal corruption (driver race); insufficient memory.
**How to fix:**
1. Retry once.
2. Restart the app.
3. Check system memory.
**Prevention / hardening:** Catch `ValueError` in `get_frame_pil` and retry once.
**Related:** E.CAP.009, E.CAP.024.
