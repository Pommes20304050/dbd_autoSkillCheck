# Chapter 2 — Inference Worker Errors

The inference worker is the heart of dbd_autoSkillCheck: a daemon `threading.Thread` that grabs screenshots, runs ONNX/TensorRT inference, fires synthetic SPACE keypresses on positive predictions, and pumps live preview frames + FPS into `AppState`. Because it runs off the Flask request thread and writes shared state under a single `threading.Lock`, every fault path here is two-faced — there is a *thing that broke* (capture, model, key sender) and a *state transition that has to remain atomic* so the UI never gets stuck on a half-truth. This chapter enumerates every observable failure path through `inference_worker.py`, `state.py`, and `directkeys.py`, including races between `set_status`, `set_idle_unless_error`, the `_stop_evt`, and platform-specific key-sender backends.

## E.WRK.001 — `frame_np is None` returned by capture

**Trigger:** `self.ai_model.grab_screenshot()` returns `None` (BetterCam does this before its first frame; mss can do it on a minimized window).
**Where:** `inference_worker.py:164` (the `if frame_np is None:` branch).
**What it means (plain English):** The screen capture call succeeded (didn't raise) but produced no pixels. The frame buffer simply wasn't ready yet, or there is nothing to capture (window minimized, monitor off, virtual desktop swap).
**Symptoms:** Status stays `running`, FPS counter stuck at 0, live preview frozen on the last good frame; after 30 consecutive Nones (~0.6 s) status flips to `error` with message *"Screen capture is returning empty frames — game window may be minimized."*
**Root cause(s):** BetterCam cold-start latency; minimized DBD window; monitor index pointing at a disconnected display; HDR/protected-content blanking.
**How to fix:**
1. Restore the DBD window so it isn't minimized.
2. Verify the configured `monitor_id` matches the physical screen DBD is on.
3. Switch `monitoring_lib` from `bettercam` to `mss` if cold-start keeps tripping.
4. Disable HDR on the target display if frames go black after a mode switch.
**Prevention / hardening:** Increase `MAX_CONSECUTIVE_FRAME_ERRORS` only after the underlying cause is identified — masking it just delays the error.
**Related:** E.WRK.002, E.WRK.003.

## E.WRK.002 — `MAX_CONSECUTIVE_FRAME_ERRORS` exceeded

**Trigger:** 30 consecutive iterations of either an exception in `grab_screenshot()` or `frame_np is None`.
**Where:** `inference_worker.py:152` and `inference_worker.py:167`.
**What it means (plain English):** The capture pipeline has been broken for long enough that the worker stops trying and tells the user.
**Symptoms:** Status flips `running → error`; topbar turns red; toast surfaces the error string; Start button re-enables, Stop disables.
**Root cause(s):** Persistent capture failure (driver hung, monitor unplugged, exclusive-fullscreen game stealing the surface, GPU reset).
**How to fix:**
1. Stop the worker, alt-tab to the game, confirm the window is visible.
2. Try the other capture backend.
3. Reboot the GPU driver (Win + Ctrl + Shift + B) if the failure followed a TDR.
**Prevention / hardening:** Lower the threshold for faster feedback when debugging; keep at 30 in production to ride out a one-off DXGI hiccup.
**Related:** E.WRK.001, E.WRK.012.

## E.WRK.003 — `grab_screenshot()` raises an exception

**Trigger:** Any exception bubbling out of `self.ai_model.grab_screenshot()`.
**Where:** `inference_worker.py:148-162` (the outer `try`/`except Exception`).
**What it means (plain English):** The capture library threw — DXGI device removed, mss locked out by Windows session change, etc.
**Symptoms:** Worker pauses 50 ms (`_stop_evt.wait(0.05)`) per failure, the exception message is preserved for the eventual error toast.
**Root cause(s):** DXGI device removed, secure-desktop transition (UAC prompt, Ctrl-Alt-Del), winlogon screen.
**How to fix:**
1. Dismiss any UAC/secure-desktop prompts.
2. Restart the worker after the system returns to the user desktop.
3. If recurrent, switch capture backend.
**Prevention / hardening:** Consider distinguishing "expected transient" exceptions (DXGI device removed) from terminal ones — currently both paths share the same counter.
**Related:** E.WRK.001, E.WRK.002.

## E.WRK.004 — `model.predict` raises an exception

**Trigger:** Inference call throws (shape mismatch, ORT session invalidated, CUDA OOM mid-run, TensorRT engine corruption).
**Where:** `inference_worker.py:186-196`.
**What it means (plain English):** A single inference call failed; the worker logs it, drops the frame, sleeps 20 ms, and tries again.
**Symptoms:** Log shows `Predict step failed` traceback; FPS drops; if every iteration fails the FPS reading stays at 0 but status remains `running`.
**Root cause(s):** ORT provider crash, GPU memory exhausted, model file truncated mid-run, driver TDR.
**How to fix:**
1. Watch the log — one entry is fine, a flood means restart.
2. Stop and restart the worker so a fresh `AI_model` session loads.
3. If GPU OOM, lower other GPU loads.
**Prevention / hardening:** Could escalate to error after N consecutive predict failures, mirroring the capture path.
**Related:** E.WRK.002, E.WRK.013.

## E.WRK.005 — Monitor backend constructor fails

**Trigger:** `make_monitoring()` raises (bettercam DLL missing, invalid monitor id, mss fails to enumerate displays).
**Where:** `inference_worker.py:73-77`.
**What it means (plain English):** We couldn't even build the capture object — there will be no frames, period.
**Symptoms:** Status goes straight `starting → error` with *"Monitor init failed: ... Pick a different monitor or screen library (mss is always available)."* Worker thread exits before AI_model is constructed.
**Root cause(s):** Bad monitor index, bettercam dependency missing despite `BETTERCAM_OK`, transient COM init failure.
**How to fix:**
1. Pick a different monitor in the UI.
2. Switch to `mss`.
3. Reinstall bettercam if hard-required.
**Prevention / hardening:** Validate `monitor_id` against `system_info.list_monitors()` before launching the worker.
**Related:** E.WRK.029, E.WRK.030.

## E.WRK.006 — `KEY_SENDER_AVAILABLE` is False

**Trigger:** Module-level import of `directkeys` left `KEY_SENDER_AVAILABLE = False` (pynput missing on Linux/macOS).
**Where:** `directkeys.py:22`, surfaced at `inference_worker.py:106-113`.
**What it means (plain English):** The worker can run, see frames, even classify hits — but every `PressKey`/`ReleaseKey` is a silent no-op.
**Symptoms:** Status stays `running`, but `state.error` is set to *"Key sender unavailable on this platform — hits will not be triggered. Install pynput on Linux/macOS."* The UI shows running + warning.
**Root cause(s):** Linux/macOS without pynput; pynput installed but no X/Wayland display; permissions denied on macOS Accessibility.
**How to fix:**
1. `pip install pynput` on Linux/macOS.
2. Run inside a graphical session, not a headless SSH shell.
3. On macOS grant Accessibility access to the Python interpreter.
**Prevention / hardening:** Preflight should show this as a blocking warning before Start, not just at run-time.
**Related:** E.WRK.007, E.WRK.008, E.WRK.024.

## E.WRK.007 — `KEY_SENDER_BACKEND == "noop"`

**Trigger:** Same as E.WRK.006; the no-op `PressKey`/`ReleaseKey` stubs at `directkeys.py:117-121` are wired in.
**Where:** `directkeys.py:23` default value, `directkeys.py:117-121` stubs.
**What it means (plain English):** Worker thinks it's hitting; nothing reaches the OS.
**Symptoms:** `record_hit` still fires, hit counter increments, `last_hit_*` populated — but the in-game skill check fails because no SPACE was actually sent.
**Root cause(s):** pynput import failed silently in the broad `except Exception` at `directkeys.py:102`.
**How to fix:**
1. Run `python -m dbd.utils.directkeys` to print the resolved backend.
2. Install pynput.
3. Check `pip list | grep pynput` matches Python interpreter the app uses.
**Prevention / hardening:** Log the import failure rather than swallow it.
**Related:** E.WRK.006, E.WRK.024.

## E.WRK.008 — `KEY_SENDER_BACKEND == "win32-sendinput"` but SendInput returns 0

**Trigger:** `user32.SendInput` returns 0 events, triggering the `_check_count` errcheck.
**Where:** `directkeys.py:67-72`.
**What it means (plain English):** Windows refused our synthetic input — usually UIPI (a more privileged window has focus, e.g. the secure desktop or an elevated game).
**Symptoms:** Caught by the broad `except Exception` at `inference_worker.py:212`; logs *"Hit handling failed"*; status stays running; cooldown still ticks.
**Root cause(s):** DBD running as Administrator while the tool runs as standard user; secure-desktop visible; anti-cheat blocking SendInput.
**How to fix:**
1. Run the tool with the same elevation level as the game (preferably both non-elevated).
2. Ensure DBD has focus when a hit fires.
3. Anti-cheat: this tool isn't compatible with kernel anti-cheat input filtering.
**Prevention / hardening:** Surface a one-shot toast when SendInput first fails — currently it only hits the log.
**Related:** E.WRK.007, E.WRK.024.

## E.WRK.009 — `KEY_SENDER_BACKEND == "pynput"` mapping miss

**Trigger:** A future caller passes a key code not in `_vk_to_pynput` (`directkeys.py:94-99`).
**Where:** `directkeys.py:108-115`.
**What it means (plain English):** The pynput backend silently no-ops on unknown VK codes (the `if k is not None:` guard).
**Symptoms:** No exception, no log, no key press. From the outside indistinguishable from a working hit.
**Root cause(s):** Adding a new key constant in `directkeys.py` without extending the `_vk_to_pynput` dict.
**How to fix:**
1. Add the missing entry to `_vk_to_pynput`.
**Prevention / hardening:** Log a warning when `k is None` so the silent no-op is at least visible.
**Related:** E.WRK.007.

## E.WRK.010 — `_stop_evt` set during model load

**Trigger:** User clicks Stop while `AI_model(...)` is still constructing (can take seconds for TensorRT).
**Where:** `inference_worker.py:81-86` — there is no stop check inside the constructor.
**What it means (plain English):** Stop request is honored only *after* the heavy model load completes; the user sees "stopping" hang for a few seconds.
**Symptoms:** UI shows status `starting`, then briefly flips to `running`, then immediately to `idle` once `_run_loop` checks `_stop_evt`.
**Root cause(s):** Long synchronous constructor with no cancel hook.
**How to fix:**
1. Wait it out; the worker will exit cleanly.
**Prevention / hardening:** Make `AI_model` accept a stop event for cooperative cancellation during long initializations.
**Related:** E.WRK.014, E.WRK.020.

## E.WRK.011 — `_stop_evt` set during ante delay

**Trigger:** `pred == 2 and hit_ante > 0` schedules an interruptible sleep at `inference_worker.py:203`; user clicks Stop during it.
**Where:** `inference_worker.py:203-204`.
**What it means (plain English):** The worker returns immediately from the ante wait without firing SPACE.
**Symptoms:** No hit recorded for that frame; status transitions cleanly to idle.
**Root cause(s):** This is by design — `_stop_evt.wait()` is the cooperative cancel.
**How to fix:** N/A — this is the expected behavior.
**Prevention / hardening:** Verify `record_hit` is *not* called on this path, otherwise the hit counter would lie.
**Related:** E.WRK.010, E.WRK.020.

## E.WRK.012 — `_stop_evt` set during 50 ms capture backoff

**Trigger:** Capture is failing; worker is in `_stop_evt.wait(0.05)` at `inference_worker.py:160`.
**Where:** `inference_worker.py:160-161` and `inference_worker.py:173-174`.
**What it means (plain English):** Stop interrupts the backoff sleep early so the worker exits in <50 ms instead of riding out the wait.
**Symptoms:** Status transitions `running → idle` within one frame.
**Root cause(s):** Working as designed.
**How to fix:** N/A.
**Prevention / hardening:** Audit that no other `time.sleep` calls (only `sleep(0.005)` between Press/Release at `inference_worker.py:207`) block stop.
**Related:** E.WRK.011, E.WRK.018.

## E.WRK.013 — `_stop_evt` set during 500 ms hit cooldown

**Trigger:** Hit just fired; worker is in `_stop_evt.wait(0.5)` at `inference_worker.py:218`.
**Where:** `inference_worker.py:218-219`.
**What it means (plain English):** Stop interrupts the post-hit cooldown so the user doesn't wait the full half-second.
**Symptoms:** Worker exits within ~50 ms of click.
**Root cause(s):** Designed.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.012.

## E.WRK.014 — `set_status("starting")` race with web reset

**Trigger:** `run()` calls `state.set_status("starting")` at `inference_worker.py:61` while a Flask handler is concurrently calling `state.reset_for_run()`.
**Where:** `state.py:61` (worker) vs `state.py:94` (route).
**What it means (plain English):** Both paths take `self._lock`, so the writes are serialized — but the *order* is non-deterministic. If reset wins, status ends up `idle` even though the worker is starting.
**Symptoms:** UI flickers `starting → idle → running`; user might see a brief idle blip on Start.
**Root cause(s):** Flask route doing a reset after spawning the worker.
**How to fix:**
1. Always reset *before* `worker.start()`.
**Prevention / hardening:** Add a state-machine guard: `set_status("starting")` only allowed from `idle`.
**Related:** E.WRK.015.

## E.WRK.015 — `set_status("running", provider=...)` overwrites pre-existing error

**Trigger:** A previous run left `state.error` populated; new run calls `set_status("running", provider=...)` at `inference_worker.py:104`.
**Where:** `state.py:69-75`.
**What it means (plain English):** `set_status` only clears `error` when the new status is `idle` (`state.py:76-79`). A stale error survives into the new running session.
**Symptoms:** UI shows green `running` topbar but a red error toast from last run still visible.
**Root cause(s):** Caller forgot to call `reset_for_run()` between runs.
**How to fix:**
1. Always call `reset_for_run()` from the route before starting the worker.
**Prevention / hardening:** `set_status("running", ...)` could clear `error` unless explicitly passed; the current contract is footgun-prone.
**Related:** E.WRK.014, E.WRK.016.

## E.WRK.016 — `set_status("running", error=...)` non-fatal warning path

**Trigger:** Key sender unavailable; worker calls `set_status("running", error="Key sender unavailable...")` at `inference_worker.py:109`.
**Where:** `state.py:69-75` — both `status` and `error` are written.
**What it means (plain English):** State machine encodes a "running with warning" mode by piggybacking on `error`. Anyone reading `state.error` thinking "we're in an error state" is wrong.
**Symptoms:** UI must distinguish by checking `status` *and* `error` together.
**Root cause(s):** Overloaded semantic of `error` field — fatal vs warning sharing one slot.
**How to fix:**
1. Treat `error` as informational unless `status == "error"`.
**Prevention / hardening:** Split into `state.error` (fatal) and `state.warning` (non-fatal).
**Related:** E.WRK.006, E.WRK.015.

## E.WRK.017 — `set_idle_unless_error` race with concurrent `set_status("error", ...)`

**Trigger:** `_run_loop` returns after setting `error`; `finally` calls `set_idle_unless_error` at `inference_worker.py:138`.
**Where:** `state.py:81-92`.
**What it means (plain English):** Both updates take the same lock. If the error was written first (it is — `return` happens before `finally`), `set_idle_unless_error` sees `status == "error"` and bails, preserving the message. Safe by construction *only* because `set_status("error", ...)` happens-before the return.
**Symptoms:** Correct case: error survives. Incorrect case (if a future refactor inverts order): error gets clobbered to idle.
**Root cause(s):** Implicit ordering contract.
**How to fix:**
1. Don't call `set_status("idle", ...)` from anywhere other than `set_idle_unless_error` and the worker's *finally*.
**Prevention / hardening:** Add a unit test that asserts `set_idle_unless_error` after `set_status("error")` keeps the error.
**Related:** E.WRK.015, E.WRK.022.

## E.WRK.018 — Worker thread join timeout

**Trigger:** Flask shutdown calls `worker.request_stop()` then `worker.join(timeout=...)`; join returns before worker exits because cleanup is slow (e.g. TensorRT context teardown).
**Where:** `inference_worker.py:122-128` (cleanup block).
**What it means (plain English):** Daemon thread is still tearing down ONNX/CUDA after the join timed out; if the process exits, daemon threads die abruptly.
**Symptoms:** Possible CUDA driver warning at process exit; rare GPU memory leak surfaced on next launch.
**Root cause(s):** Cleanup taking longer than the join timeout.
**How to fix:**
1. Increase the join timeout in the route that calls it.
**Prevention / hardening:** Make cleanup itself bounded; log how long `ai_model.cleanup()` takes.
**Related:** E.WRK.019, E.WRK.020.

## E.WRK.019 — `ai_model.cleanup()` raises

**Trigger:** Cleanup throws (e.g. ORT session already closed by GC).
**Where:** `inference_worker.py:123-127`.
**What it means (plain English):** Caught and logged; we proceed to set `ai_model = None` and restore affinity.
**Symptoms:** Log entry *"Cleanup failed"*; user-visible state still flips to idle.
**Root cause(s):** Double-free of ORT session, GPU context already destroyed.
**How to fix:**
1. Inspect the traceback; usually benign.
**Prevention / hardening:** Make `cleanup` idempotent.
**Related:** E.WRK.018, E.WRK.020.

## E.WRK.020 — `AI_model` cleanup ordering vs affinity restore

**Trigger:** `finally` block runs cleanup *before* affinity restore (`inference_worker.py:122-135`).
**Where:** `inference_worker.py:122-135`.
**What it means (plain English):** Affinity is restored last, so any thread spawned by ORT/TensorRT teardown still inherits the pinned mask. Usually fine because cleanup is short-lived.
**Symptoms:** None observable.
**Root cause(s):** N/A — design decision.
**How to fix:** N/A.
**Prevention / hardening:** If cleanup ever spawns long-lived threads, restore affinity first.
**Related:** E.WRK.019, E.WRK.021.

## E.WRK.021 — `set_process_affinity` restore fails

**Trigger:** `system_info.set_process_affinity((1 << cpu_count) - 1)` raises in `finally`.
**Where:** `inference_worker.py:131-135`.
**What it means (plain English):** Caught silently — process is left pinned to whatever `cpu_affinity_mask` was. Subsequent runs (or background tasks) underperform.
**Symptoms:** Whole Python process is throttled to a subset of cores until restart.
**Root cause(s):** Win32 API call rejected (rare).
**How to fix:**
1. Restart the application.
**Prevention / hardening:** Log the failure rather than `pass`.
**Related:** E.WRK.020.

## E.WRK.022 — `set_idle_unless_error` zeroes `tool_fps` mid-snapshot

**Trigger:** `_run_loop` exits; `set_idle_unless_error` writes `tool_fps = 0.0` while a Flask `/api/snapshot` thread is reading.
**Where:** `state.py:87-92`.
**What it means (plain English):** Both paths take `self._lock`, so the snapshot is internally consistent. A snapshot taken just *after* the worker stopped will show 0 FPS — correct behavior.
**Symptoms:** UI's FPS chart drops to 0 the moment Stop is clicked.
**Root cause(s):** Deliberate.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.017.

## E.WRK.023 — State lock contention starves snapshot endpoint

**Trigger:** Worker calls `update_live_frame` and `update_fps` every iteration; snapshot endpoint takes the same `_lock`.
**Where:** `state.py:10` (single `Lock`).
**What it means (plain English):** Under high FPS (~1000), the lock is taken thousands of times/sec. Snapshot latency grows but stays sub-ms.
**Symptoms:** None observable.
**Root cause(s):** Single coarse-grained lock.
**How to fix:** N/A unless profiling proves contention.
**Prevention / hardening:** Could split into per-field locks or use atomics for hot counters.
**Related:** E.WRK.025.

## E.WRK.024 — Missing `SendInput` on Linux

**Trigger:** `sys.platform.startswith("win")` is False on Linux/macOS; `directkeys.py:26-85` block is skipped entirely.
**Where:** `directkeys.py:26`.
**What it means (plain English):** No `user32.SendInput` exists; the pynput branch (or no-op) is the only option.
**Symptoms:** Backend reports as `pynput` or `noop`; never `win32-sendinput`.
**Root cause(s):** Platform.
**How to fix:**
1. On Linux/macOS install pynput.
**Prevention / hardening:** N/A.
**Related:** E.WRK.006, E.WRK.007.

## E.WRK.025 — `record_hit` race with `snapshot`

**Trigger:** Worker fires `state.record_hit(...)` at `inference_worker.py:211` while Flask reads `snapshot()`.
**Where:** `state.py:120-129`.
**What it means (plain English):** Both lock-protected. `last_hit_probs = dict(self.last_hit_probs)` copies under the lock so the snapshot is consistent.
**Symptoms:** None.
**Root cause(s):** Designed correctly.
**How to fix:** N/A.
**Prevention / hardening:** Don't add new fields to `record_hit` without including them in the `snapshot` lock.
**Related:** E.WRK.023.

## E.WRK.026 — Hit cooldown precision

**Trigger:** `_stop_evt.wait(0.5)` at `inference_worker.py:218` — Python's `Event.wait` resolution is OS-scheduler dependent.
**Where:** `inference_worker.py:218`.
**What it means (plain English):** On Windows the timer-tick can stretch this to 515 ms; on Linux it's tighter. Net effect: post-hit cooldown is "around 500 ms".
**Symptoms:** Some skill checks immediately after a hit are missed because the next inference iteration is delayed.
**Root cause(s):** OS scheduler granularity.
**How to fix:**
1. Lower hit_ante if used.
2. On Windows, bump timer resolution via `winmm.timeBeginPeriod(1)` (not currently done).
**Prevention / hardening:** Document the post-hit dead window.
**Related:** E.WRK.027.

## E.WRK.027 — Ante delay race with stop

**Trigger:** `pred == 2 and hit_ante > 0`; `_stop_evt.wait(hit_ante * 0.001)` at `inference_worker.py:203`.
**Where:** `inference_worker.py:200-204`.
**What it means (plain English):** Stop wins → return without firing; timeout wins → SPACE press. There's no third state.
**Symptoms:** Clean.
**Root cause(s):** Designed.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.011, E.WRK.026.

## E.WRK.028 — `record_hit` called with empty `jpeg_bytes`

**Trigger:** `encode_jpeg(frame_np)` returned `None` (cv2 error or `frame_np is None`).
**Where:** `state.py:120-129` (the `if jpeg_bytes:` guard at line 127).
**What it means (plain English):** Hit metadata still updates (count, desc, probs, timestamp), but `last_hit_frame_jpeg` retains the *previous* hit's image.
**Symptoms:** Hit log shows new entry; the thumbnail in the UI is the previous hit's frame.
**Root cause(s):** OpenCV `cv2.error` swallowed inside `encode_jpeg`.
**How to fix:**
1. Tolerate occasional misses; fix the underlying encode failure (corrupt frame).
**Prevention / hardening:** Log when `encode_jpeg` returns None more than once in a row.
**Related:** E.WRK.029.

## E.WRK.029 — `cv2.cvtColor` raises in `encode_jpeg`

**Trigger:** Frame array has unexpected shape/dtype; OpenCV throws `cv2.error`.
**Where:** `inference_worker.py:30-34`.
**What it means (plain English):** Caught and returned `None`; live preview update is skipped (`update_live_frame` rejects empty bytes via the `if not jpeg_bytes:` guard at `state.py:115-116`).
**Symptoms:** Live preview pane freezes on the last good frame; status stays running.
**Root cause(s):** Capture backend returning a different format than expected (BGRA vs RGB, etc.).
**How to fix:**
1. Switch capture backend.
2. Update the encode path to handle alpha channels.
**Prevention / hardening:** Assert frame shape on first iteration and surface an early error.
**Related:** E.WRK.005, E.WRK.028.

## E.WRK.030 — Bettercam construction succeeds but `BETTERCAM_OK` is False

**Trigger:** `Monitoring_bettercam` import failed at module load; `BETTERCAM_OK = False`; user still requests `monitoring_lib == "bettercam"`.
**Where:** `inference_worker.py:14-20`, `inference_worker.py:38-40`.
**What it means (plain English):** `make_monitoring` silently falls back to `Monitoring_mss` even though the user asked for bettercam.
**Symptoms:** Lower FPS than expected; no error message; user thinks they're on bettercam.
**Root cause(s):** Bettercam dependency not installed / DXGI helpers missing.
**How to fix:**
1. Reinstall bettercam.
2. Verify `pywin32` is healthy.
**Prevention / hardening:** Surface "requested bettercam, fell back to mss" as a state warning.
**Related:** E.WRK.005.

## E.WRK.031 — `set_status` raised inside `run()`

**Trigger:** Hypothetical: `set_status` itself raises (e.g. lock deadlock).
**Where:** `inference_worker.py:117-121` (outer safety net).
**What it means (plain English):** The outermost `except Exception` calls `set_status("error", ...)`, which would also fail. The exception then unwinds out of `run()`; daemon thread dies; finally block still runs.
**Symptoms:** UI sees no state change; status frozen on whatever it was.
**Root cause(s):** Lock corruption (essentially impossible with `threading.Lock`).
**How to fix:** N/A — would indicate a deeper Python-runtime bug.
**Prevention / hardening:** Defensive double-try around `set_status` in the safety net.
**Related:** E.WRK.017.

## E.WRK.032 — Affinity applied but device not actually CPU

**Trigger:** Config has `cpu_affinity_mask != 0` but `device != "CPU"` — guard at `inference_worker.py:68` skips affinity.
**Where:** `inference_worker.py:66-69`.
**What it means (plain English):** Affinity is *only* applied for CPU mode. GPU users with a stale CPU-affinity setting won't have the mask applied.
**Symptoms:** None problematic.
**Root cause(s):** Designed.
**How to fix:** N/A.
**Prevention / hardening:** UI could grey out affinity field when GPU selected.
**Related:** E.WRK.021.

## E.WRK.033 — `os.cpu_count()` returns `None` in finally

**Trigger:** `os.cpu_count()` returns `None` on exotic systems; expression `(1 << (os.cpu_count() or 32)) - 1` falls back to 32 cores.
**Where:** `inference_worker.py:133`.
**What it means (plain English):** A 64-core system would only have its first 32 cores re-enabled. In practice `cpu_count` always returns a number on Win/Linux/macOS.
**Symptoms:** Half the cores stay pinned post-stop on >32-core boxes when `cpu_count` lies.
**Root cause(s):** Defensive `or 32` fallback.
**How to fix:** N/A.
**Prevention / hardening:** Bump fallback to 256 or use `psutil.cpu_count(logical=True)`.
**Related:** E.WRK.021.

## E.WRK.034 — `AssertionError` from `AI_model` (GPU unavailable)

**Trigger:** `AI_model` asserts CUDA availability and fails.
**Where:** `inference_worker.py:87-90`.
**What it means (plain English):** PyTorch sees no CUDA; we record a friendly error and bail.
**Symptoms:** Status `error`, message *"GPU unavailable: ... Install PyTorch with CUDA (or switch to CPU mode)."*
**Root cause(s):** CPU-only torch installed; CUDA driver missing; GPU disabled.
**How to fix:**
1. `pip install torch --index-url https://download.pytorch.org/whl/cu121` (or matching CUDA).
2. Switch device to CPU.
**Prevention / hardening:** Preflight checks GPU availability before user clicks Start.
**Related:** E.WRK.035, E.WRK.036.

## E.WRK.035 — `FileNotFoundError` loading model

**Trigger:** `AI_model` constructor can't find the configured model path.
**Where:** `inference_worker.py:91-93`.
**What it means (plain English):** Wrong path or model not downloaded.
**Symptoms:** Status `error`, message *"Model file not found: ..."*
**Root cause(s):** Stale config pointing to a moved/renamed model.
**How to fix:**
1. Re-pick the model in the UI.
2. Re-run the model download script.
**Prevention / hardening:** Validate file existence before kicking off the worker.
**Related:** E.WRK.034, E.WRK.036.

## E.WRK.036 — `RuntimeError` from `AI_model` (no GPU EP)

**Trigger:** `AI_model` raises a runtime error (typically *"no GPU EP available"* — DirectML/CUDA EP missing in onnxruntime).
**Where:** `inference_worker.py:94-97`.
**What it means (plain English):** ONNX Runtime is installed without a GPU execution provider.
**Symptoms:** Status `error`, raw runtime message surfaced.
**Root cause(s):** Wrong `onnxruntime` flavor (cpu instead of gpu/directml).
**How to fix:**
1. `pip install onnxruntime-gpu` or `onnxruntime-directml`.
2. Switch device to CPU.
**Prevention / hardening:** Preflight enumerates available providers.
**Related:** E.WRK.034.

## E.WRK.037 — Generic exception during model load

**Trigger:** Anything else raised by `AI_model` constructor.
**Where:** `inference_worker.py:98-102`.
**What it means (plain English):** Catch-all that logs full traceback and surfaces a generic error with hint to verify the model file format.
**Symptoms:** Status `error`, message *"Model load failed: ... Check that the model file is a valid ONNX/TensorRT engine and matches your runtime."*
**Root cause(s):** Corrupt ONNX, mismatched TensorRT engine, opset version unsupported.
**How to fix:**
1. Re-download the model.
2. Confirm runtime version matches engine version.
**Prevention / hardening:** Hash-check the model file.
**Related:** E.WRK.034, E.WRK.035, E.WRK.036.

## E.WRK.038 — `update_fps` called with non-numeric value

**Trigger:** Hypothetical caller passing a non-float; `nb_frames / t_diff` is always numeric, so unreachable today.
**Where:** `state.py:109-112`.
**What it means (plain English):** `deque.append` would still succeed; later `sum(sample) / len(sample)` would raise.
**Symptoms:** `_avg_locked` raises `TypeError`; snapshot endpoint 500s.
**Root cause(s):** Future caller bug.
**How to fix:**
1. Pin `update_fps` to `float`.
**Prevention / hardening:** Cast in `update_fps`.
**Related:** E.WRK.022.

## E.WRK.039 — `fps_history` deque saturation

**Trigger:** Worker has been running >60 s; deque reaches `maxlen=60`.
**Where:** `state.py:17`.
**What it means (plain English):** Old samples drop off the left; chart becomes a rolling 60-second window.
**Symptoms:** Designed.
**Root cause(s):** N/A.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.038.

## E.WRK.040 — `hit_log` deque saturation under spam

**Trigger:** >120 hits within 60 s; oldest timestamps drop, undercounting `hits_per_minute`.
**Where:** `state.py:20`.
**What it means (plain English):** With deque cap of 120, true rate >120/min is clipped.
**Symptoms:** UI hits/min plateaus at 120.
**Root cause(s):** Bounded deque.
**How to fix:**
1. Raise `maxlen` if higher rates are expected.
**Prevention / hardening:** Use a rolling counter instead of timestamp deque.
**Related:** E.WRK.025.

## E.WRK.041 — Status transition `starting → running` skipped

**Trigger:** Model load is so fast (or worker so slow to set status) that UI polls and never observes `starting`.
**Where:** `inference_worker.py:61` then `inference_worker.py:104`.
**What it means (plain English):** UI may go directly `idle → running` from the user's perspective.
**Symptoms:** No starting spinner.
**Root cause(s):** Polling cadence.
**How to fix:** N/A — cosmetic.
**Prevention / hardening:** Force a minimum `starting` dwell time, or have UI show "starting" optimistically until first running snapshot.
**Related:** E.WRK.014.

## E.WRK.042 — `_stop_evt.wait(0.005)` not used between Press and Release

**Trigger:** Hit fires; `sleep(0.005)` (uninterruptible) at `inference_worker.py:207` between Press and Release.
**Where:** `inference_worker.py:206-208`.
**What it means (plain English):** A stop request landing in this 5 ms window has to wait for it. Negligible but technically uncancellable.
**Symptoms:** None observable.
**Root cause(s):** Deliberate — short blocking sleep keeps the keypress timing tight.
**How to fix:** N/A.
**Prevention / hardening:** Could swap for `_stop_evt.wait(0.005)` — but on stop we'd return *before* `ReleaseKey`, leaving SPACE held down in the OS.
**Related:** E.WRK.043.

## E.WRK.043 — SPACE held down if exception between Press and Release

**Trigger:** `PressKey(SPACE)` succeeds; `sleep(0.005)` runs; `ReleaseKey(SPACE)` raises (extremely rare).
**Where:** `inference_worker.py:206-208`.
**What it means (plain English):** OS still thinks SPACE is held; in-game character keeps performing the SPACE action.
**Symptoms:** Stuck SPACE input until user presses SPACE manually.
**Root cause(s):** SendInput failure on the release call.
**How to fix:**
1. Press SPACE manually to clear.
**Prevention / hardening:** Wrap in `try/finally` ensuring `ReleaseKey` always runs.
**Related:** E.WRK.008, E.WRK.042.

## E.WRK.044 — `live_frame_jpeg` retains a stale frame after stop

**Trigger:** Worker stops; nothing clears `state.live_frame_jpeg`.
**Where:** `state.py:114-118` and the absence of a clear in `set_idle_unless_error` (`state.py:81-92`).
**What it means (plain English):** UI live preview shows the last frame indefinitely after stop. `reset_for_run` (`state.py:107`) clears it on the next start.
**Symptoms:** Preview "freezes" instead of going dark.
**Root cause(s):** Designed — preserves last context.
**How to fix:** N/A.
**Prevention / hardening:** Could add `self.live_frame_jpeg = None` to `set_idle_unless_error` if a dark preview is preferred.
**Related:** E.WRK.022.

## E.WRK.045 — Hot-loop sleep interruption via stop event

**Trigger:** All three `_stop_evt.wait(...)` calls (50 ms backoff, 20 ms post-error, 500 ms cooldown, ante delay).
**Where:** `inference_worker.py:160, 173, 194, 203, 218`.
**What it means (plain English):** All sleeps are interruptible — there is no place where a stop request waits longer than the model load (E.WRK.010), the 5 ms Press/Release gap (E.WRK.042), or the predict call itself.
**Symptoms:** Stop responsiveness ~50 ms in steady state.
**Root cause(s):** Designed.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.010, E.WRK.011, E.WRK.012, E.WRK.013, E.WRK.042.

## E.WRK.046 — `frame_idx` overflow on long sessions

**Trigger:** `frame_idx += 1` per iteration; at 1000 fps, overflow into Python big-int territory after billions of frames (memory cost grows slowly).
**Where:** `inference_worker.py:180`.
**What it means (plain English):** Python ints are arbitrary precision; no overflow, but memory creep is theoretically possible after weeks.
**Symptoms:** None practical.
**Root cause(s):** N/A.
**How to fix:** N/A.
**Prevention / hardening:** Modulo `frame_idx` by `LIVE_FRAME_EVERY_N` and reset.
**Related:** E.WRK.039.

## E.WRK.047 — `t0 = time()` clock skew

**Trigger:** System wall clock jumps (NTP correction) during the FPS interval.
**Where:** `inference_worker.py:142, 220, 228` (uses `time.time` semantics via `from time import time`).
**What it means (plain English):** A backwards jump → negative `t_diff` → never enters the `if t_diff > 1.0` branch → FPS counter freezes; forward jump → spike.
**Symptoms:** Brief FPS anomaly after NTP sync.
**Root cause(s):** Wall clock used instead of monotonic.
**How to fix:** N/A.
**Prevention / hardening:** Switch to `time.monotonic()` for FPS measurement (state.py already uses it).
**Related:** E.WRK.038.

## E.WRK.048 — `set_status("running", ...)` not setting provider on warning path

**Trigger:** Key sender unavailable warning at `inference_worker.py:109-113` calls `set_status("running", error=...)` *without* `provider=`.
**Where:** `state.py:69-75` — the `if provider is not None:` guard means the previously-set provider sticks. Safe.
**Symptoms:** None.
**Root cause(s):** Correct by design.
**How to fix:** N/A.
**Prevention / hardening:** N/A.
**Related:** E.WRK.016.

## E.WRK.049 — `reset_for_run` clears state mid-run

**Trigger:** Flask handler calls `state.reset_for_run()` while the worker is already in `_run_loop`.
**Where:** `state.py:94-107`.
**What it means (plain English):** Worker keeps running but FPS history, hit log, hit_count, last_hit_*, live_frame all wiped under the lock. Next `update_fps` re-populates.
**Symptoms:** UI counters reset to 0 mid-run; hit thumbnails clear.
**Root cause(s):** Reset called outside its intended pre-start window.
**How to fix:**
1. Only call `reset_for_run` from the Start route, before spawning the worker.
**Prevention / hardening:** Guard reset against non-idle status.
**Related:** E.WRK.014.

## E.WRK.050 — Atomic snapshot vs in-flight `record_hit`

**Trigger:** Snapshot reader and `record_hit` collide.
**Where:** `state.py:29-47` vs `state.py:120-129`.
**What it means (plain English):** Both lock-protected; snapshot copies `last_hit_probs` via `dict(...)` so iteration is safe even if record_hit replaces the dict reference next.
**Symptoms:** None.
**Root cause(s):** Correct.
**How to fix:** N/A.
**Prevention / hardening:** Don't mutate `last_hit_probs` in-place after assigning.
**Related:** E.WRK.025.
