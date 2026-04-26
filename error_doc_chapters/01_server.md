# Chapter 1 — Web Server Errors

This chapter exhaustively catalogs every error path, exception branch, status-code return, race condition, edge case, and silent-degradation route in the Flask web server of `dbd_autoSkillCheck`. Two files are in scope: `dbd/web/server.py` (route handlers, validation, worker lifecycle) and `app_flask.py` (process bootstrap, signal handlers, `atexit`). Each entry documents trigger conditions, exact source location, plain-English meaning, observable symptoms (HTTP code and JSON shape), root cause(s), step-by-step remediation, and hardening guidance. Errors are numbered E.SRV.001 through E.SRV.060 and cross-referenced where they share a root cause.

---

## E.SRV.001 — `models/` directory missing on disk

**Trigger:** The process is started in a working directory that does not contain a `models/` folder, or the folder was deleted/renamed between runs.
**Where:** `server.py:28` (`_list_models`); also surfaces via `server.py:110` (`api_init`) and `server.py:287` (`api_start`).
**What it means (plain English):** The server hard-codes `MODELS_FOLDER = "models"` as a relative path. If `os.path.isdir("models")` is False, `_list_models()` silently returns `[]`. The init endpoint will then report `default_model: None` and an empty model list, leaving the dropdown blank. Any subsequent `/api/start` will fail validation because `_resolve_safe_model_path` cannot match a name against an empty list.
**Symptoms:** UI shows an empty model dropdown; banner reads "no models available"; `/api/init` returns 200 with `models: [], default_model: null, models_folder_exists: false`. A `/api/start` POST returns 400 `{"ok": false, "error": "model not found or invalid: <name>"}`.
**Root cause(s):** Working directory mismatch (server launched from a parent or sibling directory); models folder accidentally renamed; deployment skipped the models artifact; permissions hide directory listing.
**How to fix (step-by-step):**
1. Confirm `cwd` with `os.getcwd()` in a debug print or check the launch script.
2. Place `.onnx`/`.trt` files into `<cwd>/models/`.
3. Restart the server (the listing is read on every request so technically a refresh works, but caching the dropdown means a UI reload helps).
4. Verify `/api/init` now returns `models_folder_exists: true` and a non-empty list.
**Prevention / hardening:** Resolve `MODELS_FOLDER` to an absolute path using `Path(__file__).parent.parent.parent / "models"` so it is independent of cwd. Log a startup warning if the folder is missing.
**Related:** E.SRV.002, E.SRV.020, E.SRV.021.

---

## E.SRV.002 — `_list_models` shadows `OSError` from `os.listdir`

**Trigger:** Models folder exists but is unreadable (Windows ACL denies read, the directory is a junction to a removed network share, or Defender has it locked during scan).
**Where:** `server.py:32` (`_list_models`).
**What it means (plain English):** `os.path.isdir` may succeed while `os.listdir` raises `PermissionError` or `OSError`. The function does not catch this, so the exception bubbles to the caller. In `/api/init` it is swallowed by the outer try/except and rendered as a 500 init failure; in `/api/start` it returns 500 because `_resolve_safe_model_path` invokes `_list_models` without a guard.
**Symptoms:** `/api/init` → 500 `{"error": "init failed: [WinError 5] Access is denied"}`; `/api/start` → unhandled exception, Flask default 500 HTML page (because `_resolve_safe_model_path` is called outside any try block in `api_start`).
**Root cause(s):** ACL mis-configuration; OneDrive/cloud-only files with `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`; transient AV lock; junction target gone.
**How to fix (step-by-step):**
1. Run `icacls models` and grant the running user read+execute.
2. Pin OneDrive files with "Always keep on this device".
3. Whitelist the project folder in Defender.
4. Wrap `_list_models` in `try/except OSError` and return `[]` plus a logged warning.
**Prevention / hardening:** Add a try/except inside `_list_models`. Surface the failure through `/api/init` as a non-fatal `models_folder_error` field rather than a 500.
**Related:** E.SRV.001, E.SRV.020.

---

## E.SRV.003 — Path traversal attempt rejected by `_resolve_safe_model_path`

**Trigger:** A POST to `/api/start` with `model` containing `..`, `/`, `\`, an absolute path, or the literal `.` / `..`.
**Where:** `server.py:47` (`_resolve_safe_model_path`), called at `server.py:287`.
**What it means (plain English):** The function deliberately refuses any path syntax to stop a remote caller from loading arbitrary files (e.g., `..\..\Windows\System32\foo.dll`). The check covers four cases: empty/non-string, dot-relative names, separator characters, and absolute paths. Failure of any check returns `None`, which `api_start` translates into a 400.
**Symptoms:** HTTP 400, body `{"ok": false, "error": "model not found or invalid: '../../etc/passwd'"}`. UI banner: "Model not found or invalid".
**Root cause(s):** Hostile or buggy client; user manually typing into a debug console; legitimate but malformed config (e.g., a Windows path with backslashes pasted into a Linux dev build).
**How to fix (step-by-step):**
1. Send only the bare filename, e.g., `"model_v1.onnx"`, never `"models/model_v1.onnx"`.
2. If the file lives elsewhere, copy/symlink it into `models/`.
3. Verify the dropdown sends only filenames (the front-end builds requests from `/api/init`'s `models` array).
**Prevention / hardening:** Keep this gate. Add an audit log line when the gate trips so repeated probes are visible. Consider returning a generic "invalid" without echoing the offending name to avoid reflecting attacker input.
**Related:** E.SRV.004, E.SRV.005, E.SRV.029.

---

## E.SRV.004 — `_resolve_safe_model_path` rejects non-string model

**Trigger:** Client posts `{"model": 123}` or `{"model": null}` or `{"model": ["a"]}`.
**Where:** `server.py:51`.
**What it means (plain English):** `isinstance(model_name, str)` is False, so the function returns `None`. JSON allows numbers/arrays/objects/null in the same field, and a buggy client could send any of them. The early type guard prevents downstream `os.path.join` from raising `TypeError`.
**Symptoms:** 400 `{"ok": false, "error": "model not found or invalid: 123"}` (the `!r` repr shows the type clearly).
**Root cause(s):** Client serialization bug; form library wrapping value as array; `null` passed because dropdown not yet populated when user clicked Start.
**How to fix (step-by-step):**
1. In the front-end, disable the Start button until `/api/init` resolves and the dropdown has a value.
2. Coerce to string client-side.
3. Inspect DevTools Network tab to confirm payload shape.
**Prevention / hardening:** Add a JSON-schema validation layer (e.g., `pydantic` or `marshmallow`) for `/api/start` so type errors return a structured 422 with field paths.
**Related:** E.SRV.003, E.SRV.029.

---

## E.SRV.005 — Model filename present in request but missing on disk

**Trigger:** Client sends a model name that was valid at app load time but the file has since been deleted or renamed; or a stale browser tab sends an old name.
**Where:** `server.py:58` (`if model_name not in _list_models()`), called from `api_start` at `server.py:287`.
**What it means (plain English):** The whitelist check is recomputed on every call by listing the directory again. If the file vanished, the request is rejected. This is intentional — a stale dropdown should not be allowed to load arbitrary files later.
**Symptoms:** 400 with `{"ok": false, "error": "model not found or invalid: 'old_model.onnx'"}`.
**Root cause(s):** Manual file management; partial deployment; user moved file mid-session.
**How to fix (step-by-step):**
1. Restore the missing file or refresh the UI to re-pull `/api/init`.
2. If model was intentionally retired, instruct user to pick a different one.
**Prevention / hardening:** Push a Server-Sent-Event when the models list changes so open tabs auto-refresh, or include a content hash so the front-end can detect drift.
**Related:** E.SRV.001, E.SRV.003.

---

## E.SRV.006 — Path-traversal in `/api/preflight` model arg

**Trigger:** GET `/api/preflight?model=../foo`.
**Where:** `server.py:249`.
**What it means (plain English):** The preflight endpoint only does a string-equality comparison inside `preflight.build_advice`, so the risk is lower, but the code defensively neutralizes `model` to `None` if path syntax is detected. This collapses the user-visible advice to the device/lib portion only.
**Symptoms:** 200 with preflight payload but the model-specific section is computed as if no model was provided.
**Root cause(s):** Misbehaving client; security-test scanner; URL-encoding of legitimate names that introduces forbidden characters (e.g., `%2F` decoded to `/`).
**How to fix (step-by-step):**
1. Send a clean filename such as `model_v1.onnx`.
2. Avoid embedding folder prefixes.
**Prevention / hardening:** Mirror `_resolve_safe_model_path`'s fuller checks here so behaviour is uniform across endpoints.
**Related:** E.SRV.003, E.SRV.029.

---

## E.SRV.007 — `/api/preflight` device parameter coerced to None

**Trigger:** Query `?device=AMD` or `?device=cuda` (anything not in `{None, "CPU", "GPU"}`).
**Where:** `server.py:243-244`.
**What it means (plain English):** Unknown device strings silently degrade to `None`, suppressing the device-specific section of the advice. No error is returned. This is permissive on purpose: preflight is a hint, not an enforcement layer.
**Symptoms:** 200 with advice computed as device-agnostic; UI may show "Select a device" banner instead of a tailored hint.
**Root cause(s):** Front-end localization quirk; user-typed override; old client referencing a removed device label.
**How to fix (step-by-step):**
1. Pass `CPU` or `GPU` exactly.
2. If the front-end exposes more devices, update server's allowlist accordingly.
**Prevention / hardening:** Log unknown device values at DEBUG level so they are visible during development.
**Related:** E.SRV.008, E.SRV.029.

---

## E.SRV.008 — `/api/preflight` monitoring_lib coerced to None

**Trigger:** Query `?monitoring_lib=dxgi` or any string not in `{"mss", "bettercam"}`.
**Where:** `server.py:245-246`.
**What it means (plain English):** Same idea as E.SRV.007 but for the capture library. Silent downgrade to `None`.
**Symptoms:** 200 with library-agnostic advice.
**Root cause(s):** Outdated front-end constants; typo.
**How to fix (step-by-step):**
1. Pass `mss` or `bettercam`.
2. Confirm `bettercam` is actually installed; otherwise even passing it has limited effect downstream.
**Prevention / hardening:** Convert to a strict 400 if you want explicit feedback during development.
**Related:** E.SRV.007, E.SRV.022.

---

## E.SRV.009 — `/api/preflight` returns 503 via `_safe_jsonify`

**Trigger:** `preflight.build_advice` raises any exception (e.g., NVML died, registry probe threw, file IO error inside the advisor).
**Where:** `server.py:251` → `server.py:99` (`_safe_jsonify` exception path).
**What it means (plain English):** Rather than returning Flask's default 500 HTML page (which would spam toast notifications because the front-end polls), `_safe_jsonify` formats a JSON 503 with `{"error": "<label> probe failed: ...", "available": false}`. The route stays well-behaved during transient failures.
**Symptoms:** 503 with body `{"error": "preflight probe failed: <message>", "available": false}`. UI typically renders a muted "preflight unavailable" panel.
**Root cause(s):** NVML init failure; missing DLL; permissions issue reading registry/INI; race against driver reload.
**How to fix (step-by-step):**
1. Inspect server logs — `_safe_jsonify` calls `log.exception` with the label name, including stack trace.
2. Address the underlying cause (driver, permissions, missing file).
3. Retry — UI will recover automatically once the probe succeeds.
**Prevention / hardening:** Add a circuit-breaker so a flapping probe stops being polled for N seconds.
**Related:** E.SRV.010, E.SRV.011, E.SRV.012, E.SRV.025.

---

## E.SRV.010 — `/api/perf` 503 from perf_monitor failure

**Trigger:** `perf_monitor.perf_snapshot()` raises (e.g., psutil DLL load error, NVML thread access denied, GPU hot-unplug).
**Where:** `server.py:232`.
**What it means (plain English):** Same `_safe_jsonify` wrapper: any exception inside the perf collector returns a 503 JSON. Because this endpoint is polled every second or so by the dashboard, swallowing it is critical.
**Symptoms:** 503 `{"error": "perf probe failed: ...", "available": false}`. Dashboard shows the perf widgets in a degraded state.
**Root cause(s):** psutil version mismatch with kernel; counter not present on this Windows build; pdh.dll absent in container.
**How to fix (step-by-step):**
1. `pip install --upgrade psutil`.
2. Run process as a user with PerfMon access.
3. Restart the host if PDH counters are corrupted (`lodctr /R`).
**Prevention / hardening:** Cache last-good snapshot and serve stale-but-safe data on transient failure.
**Related:** E.SRV.009, E.SRV.011, E.SRV.012.

---

## E.SRV.011 — `/api/info` 503 from env_info failure

**Trigger:** `env_info.collect()` raises (rare; usually only if the OS reports unusual fields).
**Where:** `server.py:236`.
**What it means (plain English):** Environment introspection failure. The 503 body lets the UI hide the "About" panel rather than throw a banner.
**Symptoms:** 503 `{"error": "info probe failed: ...", "available": false}`.
**Root cause(s):** Platform-specific call returning unexpected types; locale/encoding errors when reading kernel strings; UnicodeDecodeError on OEM-coded paths.
**How to fix (step-by-step):**
1. Read the stack trace from logs.
2. Add a try/except around the offending probe inside `env_info.collect`.
**Prevention / hardening:** Each sub-probe should be independently try/excepted with a partial-result return value.
**Related:** E.SRV.009, E.SRV.010, E.SRV.012.

---

## E.SRV.012 — `/api/fps-advice` 503 wrapper

**Trigger:** `fps_advisor.build_advice` raises (e.g., Engine.ini malformed, INI parser exception).
**Where:** `server.py:225-228`.
**What it means (plain English):** Calls the same `_safe_jsonify` helper. Note this is **separate** from the inline try/except inside `/api/status` (E.SRV.013), which is a duplicate-but-different code path.
**Symptoms:** 503 `{"error": "fps_advice probe failed: ...", "available": false}`.
**Root cause(s):** INI file corruption; permissions; advisor logic bug.
**How to fix (step-by-step):**
1. Validate the Engine.ini file by hand.
2. Check log stack trace.
**Prevention / hardening:** Unify with the inline branch in `/api/status` so the failure shape matches.
**Related:** E.SRV.013.

---

## E.SRV.013 — fps_advisor failure inside `/api/status`

**Trigger:** `fps_advisor.build_advice(avg)` raises during a status poll.
**Where:** `server.py:209-221`.
**What it means (plain English):** Unlike the dedicated `/api/fps-advice` route which uses `_safe_jsonify`, the status route catches the exception inline and substitutes a synthetic advice dict containing `"ini_status": "error"` plus a human-readable message. The endpoint still returns 200 because clients depend on `/api/status` for state machine transitions and a 503 here would freeze the UI.
**Symptoms:** 200 with `fps_advice.message = "FPS advisor unavailable: <e>"` and `severity = "info"`. Other status fields remain valid.
**Root cause(s):** Same as E.SRV.012 (INI parsing, file IO).
**How to fix (step-by-step):**
1. Same as E.SRV.012.
**Prevention / hardening:** Two divergent failure shapes (here vs. `_safe_jsonify`) is a code smell; refactor into one helper.
**Related:** E.SRV.012, E.SRV.038.

---

## E.SRV.014 — `/api/monitors` rejects unknown monitoring_lib

**Trigger:** GET `/api/monitors?monitoring_lib=foo`.
**Where:** `server.py:158-159`.
**What it means (plain English):** Unlike `/api/preflight`, this route validates strictly and returns 400. The intent is that this list directly populates a UI control, so silently coercing would mislead.
**Symptoms:** 400 `{"error": "unknown monitoring_lib: foo"}`.
**Root cause(s):** Stale UI; misspelling.
**How to fix (step-by-step):**
1. Pass `mss` or `bettercam`.
2. If `bettercam` is rejected with this message, the lib is allowed; the actual problem is likely an enumeration error (E.SRV.015).
**Prevention / hardening:** Echo the allowed list in the error message so clients self-correct.
**Related:** E.SRV.015, E.SRV.022.

---

## E.SRV.015 — `/api/monitors` enumeration failure (503)

**Trigger:** Library is allowed but enumeration raises (e.g., bettercam fails to spin up DXGI duplication; mss fails on a virtual session without GUI).
**Where:** `server.py:160-164`.
**What it means (plain English):** Returns a 503 with `monitors: []` plus a descriptive error. The empty array gives the front-end a sensible fallback even if the user ignores the error.
**Symptoms:** 503 `{"error": "monitor enumeration failed: ...", "monitors": []}`.
**Root cause(s):** RDP session without console attach; missing graphics driver; no displays attached; bettercam DLL not loaded; user is a Windows service without an interactive desktop.
**How to fix (step-by-step):**
1. Run on a logged-in interactive session, not a service.
2. Install/update graphics driver.
3. Reconnect at least one monitor.
4. Switch monitoring_lib to mss for testing.
**Prevention / hardening:** Cache last-known monitor list across runs to ease config persistence.
**Related:** E.SRV.014, E.SRV.022, E.SRV.023.

---

## E.SRV.016 — `/api/init` monitor enumeration failure (degraded)

**Trigger:** During init, `_list_monitors(monitoring_libs[0])` raises.
**Where:** `server.py:122-127`.
**What it means (plain English):** Init is too important to fail outright, so the catch sets `monitors = []` and appends the error to `gpu_unavailable_reason` (a slightly questionable choice — see E.SRV.017). The route still returns 200.
**Symptoms:** 200 with `monitors: []` and a verbose `gpu_unavailable_reason` containing "Monitor enumeration failed: ...".
**Root cause(s):** Same as E.SRV.015.
**How to fix (step-by-step):**
1. Same as E.SRV.015.
**Prevention / hardening:** Add a dedicated `monitors_error` field so the GPU reason isn't conflated with display capture failures.
**Related:** E.SRV.015, E.SRV.017.

---

## E.SRV.017 — Misleading `gpu_unavailable_reason` includes monitor failure

**Trigger:** Monitor enumeration fails during init while the GPU was actually fine.
**Where:** `server.py:127`.
**What it means (plain English):** Subtle UX bug. The reason field is repurposed to carry the enumeration error, so the UI displays "GPU unavailable: Monitor enumeration failed: ..." which is technically true (gpu_reason was None before) but confusing because the GPU itself is healthy.
**Symptoms:** UI banner blames the GPU for a display capture issue.
**Root cause(s):** Field overload.
**How to fix (step-by-step):**
1. Treat as a known cosmetic issue, no runtime impact.
2. Refactor to introduce `monitors_error` field (see E.SRV.016 hardening).
**Prevention / hardening:** Avoid concatenating unrelated diagnostics into a single field.
**Related:** E.SRV.016.

---

## E.SRV.018 — `/api/init` 500 wrapper

**Trigger:** Any uncaught exception in init body (e.g., `system_info.detect_cpu` blows up).
**Where:** `server.py:151-153`.
**What it means (plain English):** This is the only init failure that returns 500; the inner monitor catch is the sole exception. Anything else (CPU detection, GPU detection, preset construction) is fatal for init.
**Symptoms:** 500 `{"error": "init failed: ..."}`. UI cannot proceed past the splash screen.
**Root cause(s):** WMI down on Windows; psutil crash; broken preset math.
**How to fix (step-by-step):**
1. Read log stack trace.
2. Restart WMI service: `net stop winmgmt && net start winmgmt`.
3. Reinstall psutil.
**Prevention / hardening:** Make every sub-probe partially-failable so init can degrade rather than refuse to start.
**Related:** E.SRV.011, E.SRV.016.

---

## E.SRV.019 — `/api/preview` rejects unknown monitoring_lib

**Trigger:** GET `/api/preview?monitoring_lib=foo`.
**Where:** `server.py:169-170`.
**What it means (plain English):** Same allowlist as `/api/monitors`; deviation is also 400 here.
**Symptoms:** 400 `{"error": "unknown monitoring_lib: foo"}`.
**Root cause(s):** Stale UI; user override.
**How to fix (step-by-step):**
1. Use `mss` or `bettercam`.
**Prevention / hardening:** Centralize allowlist in a single function (`_allowed_monitoring_libs` already exists but is duplicated in /api/preflight as a literal — drift risk).
**Related:** E.SRV.014, E.SRV.022.

---

## E.SRV.020 — `/api/preview` rejects non-int monitor_id

**Trigger:** GET `/api/preview?monitor_id=abc` or omitted with garbage default.
**Where:** `server.py:172-175`.
**What it means (plain English):** Tries `int(request.args.get("monitor_id", "1"))`. `TypeError` and `ValueError` are caught and translated to 400. The default `"1"` is the typical primary monitor ID.
**Symptoms:** 400 `{"error": "monitor_id must be int"}`.
**Root cause(s):** UI bug serializing the value; user editing URL by hand.
**How to fix (step-by-step):**
1. Pass an integer, e.g., `?monitor_id=1`.
**Prevention / hardening:** Use Flask's typed converters (`<int:monitor_id>`) when refactoring to path-style endpoints.
**Related:** E.SRV.029.

---

## E.SRV.021 — `/api/preview` invalid monitor_id (400)

**Trigger:** Monitor index is integer but out of range or unknown to mss/bettercam (e.g., user sends `id=99` on a single-monitor setup).
**Where:** `server.py:179-180`.
**What it means (plain English):** `Monitoring_*` raises `IndexError` or `KeyError` when the ID is unknown; the endpoint catches both and reports 400.
**Symptoms:** 400 `{"error": "invalid monitor_id: <message>"}`.
**Root cause(s):** Hot-unplug between enumeration and preview; user typed a bad index; monitor list cached client-side outlived a topology change.
**How to fix (step-by-step):**
1. Re-fetch `/api/monitors` to refresh.
2. Pick a valid ID.
**Prevention / hardening:** Have the preview endpoint validate against a fresh `_list_monitors` and return a structured "valid_ids" list when rejecting.
**Related:** E.SRV.022.

---

## E.SRV.022 — `/api/preview` capture failure (500)

**Trigger:** Monitor index is valid but capture itself fails (DXGI desktop access denied, secure desktop active, UAC prompt, lock screen).
**Where:** `server.py:181-183`.
**What it means (plain English):** Any non-IndexError/KeyError exception during capture is treated as a server error (500). The exception message is echoed to the client.
**Symptoms:** 500 `{"error": "<exception message>"}`.
**Root cause(s):** Secure desktop active (UAC); session locked; desktop is on the secure session (Ctrl-Alt-Del); GPU TDR'd; bettercam DLL crash.
**How to fix (step-by-step):**
1. Dismiss any UAC/lock prompts.
2. Ensure the user has an interactive session.
3. Switch to mss as a fallback (DXGI is more sensitive than mss).
**Prevention / hardening:** Differentiate "transient capture failure" (503) from "code bug" (500). DXGI access denial is environmental, not a server bug.
**Related:** E.SRV.015, E.SRV.023.

---

## E.SRV.023 — `/api/preview` JPEG encode failure (503)

**Trigger:** Frame captured is `None` or `cv2.imencode` returns False.
**Where:** `server.py:185-186`.
**What it means (plain English):** Capture worked at the API level but produced an empty frame (the typical case is a minimized or destroyed game window) or OpenCV refused to encode it. The 503 lets the front-end show "preview unavailable" without spamming toasts.
**Symptoms:** 503 `{"error": "encode failed (game window may be minimized)"}`.
**Root cause(s):** Game minimized; black frame; OpenCV linked against a JPEG codec that refused odd-size input.
**How to fix (step-by-step):**
1. Bring the game window to the foreground.
2. Resize so the capture region is visible.
**Prevention / hardening:** Encode a placeholder image with the diagnostic instead of a JSON error; the UI can `<img>`-tag it directly.
**Related:** E.SRV.022.

---

## E.SRV.024 — `/api/live-frame` returns 404 when no live frame

**Trigger:** GET `/api/live-frame` while the worker is idle, just started, or has not yet pushed a frame.
**Where:** `server.py:189-194`.
**What it means (plain English):** `state.get_live_frame()` returns `None` until inference produces at least one frame. The endpoint uses Flask `abort(404)` rather than a JSON body because the front-end binds it to an `<img>` element which only handles HTTP semantics.
**Symptoms:** 404 (no body). UI shows broken image or fallback placeholder.
**Root cause(s):** Worker not yet running; worker stopped; race during startup.
**How to fix (step-by-step):**
1. Wait for `/api/status.status == "running"` before requesting frames.
2. Front-end should retry with backoff.
**Prevention / hardening:** Return a 1x1 transparent PNG instead of 404 to avoid console errors in the browser.
**Related:** E.SRV.025.

---

## E.SRV.025 — `/api/last-hit-frame` returns 404 before any hit

**Trigger:** GET `/api/last-hit-frame` before the worker has logged a hit.
**Where:** `server.py:196-201`.
**What it means (plain English):** Same pattern as E.SRV.024. The "last hit" frame is only populated after a positive detection.
**Symptoms:** 404, broken image.
**Root cause(s):** No hit recorded yet.
**How to fix (step-by-step):**
1. Trigger a skill check in the game.
2. Refresh.
**Prevention / hardening:** As above, serve a placeholder image.
**Related:** E.SRV.024.

---

## E.SRV.026 — `/api/set-fps-cap` malformed JSON

**Trigger:** POST with invalid JSON (e.g., trailing comma, wrong content-type without body, empty body).
**Where:** `server.py:256` (`request.get_json(silent=True) or {}`).
**What it means (plain English):** `silent=True` means malformed JSON returns `None` instead of raising; the `or {}` ensures `body` is always a dict. Then `body.get("cap")` is `None`, which falls through to the int cast (E.SRV.027).
**Symptoms:** 400 `{"ok": false, "error": "cap must be an integer"}` (because int(None) raises TypeError).
**Root cause(s):** Wrong Content-Type header (must be `application/json`); empty body; client built a query string instead of a JSON body.
**How to fix (step-by-step):**
1. Send `Content-Type: application/json` and a JSON body `{"cap": 60}`.
2. Avoid trailing commas.
**Prevention / hardening:** Use `silent=False` and a custom 400 mapper to differentiate "not JSON" from "JSON but missing field".
**Related:** E.SRV.027, E.SRV.030.

---

## E.SRV.027 — `/api/set-fps-cap` non-integer cap

**Trigger:** Body `{"cap": "fast"}` or `{"cap": 60.5}`.
**Where:** `server.py:258-261`.
**What it means (plain English):** `int("fast")` raises ValueError; `int(60.5)` succeeds — interesting nuance: floats truncate silently to 60 here, which may surprise. Only TypeError/ValueError are caught.
**Symptoms:** 400 `{"ok": false, "error": "cap must be an integer"}`.
**Root cause(s):** UI form binding; locale formatting (comma vs. dot).
**How to fix (step-by-step):**
1. Send a JSON integer.
**Prevention / hardening:** Use `isinstance(cap_raw, int) and not isinstance(cap_raw, bool)` to reject booleans (which silently pass `int()`).
**Related:** E.SRV.026, E.SRV.028, E.SRV.029.

---

## E.SRV.028 — `/api/set-fps-cap` out-of-range cap

**Trigger:** Body `{"cap": -1}` or `{"cap": 99999}`.
**Where:** `server.py:264-265`.
**What it means (plain English):** Pre-filter before the advisor whitelist. Anything below 0 or above 1000 is rejected with a clear message; the advisor would otherwise issue a less obvious one.
**Symptoms:** 400 `{"ok": false, "error": "cap out of range: -1"}`.
**Root cause(s):** Bad slider; user-provided value out of policy.
**How to fix (step-by-step):**
1. Send a value in [0, 1000].
**Prevention / hardening:** Document the legal range in the API docs and front-end tooltip.
**Related:** E.SRV.027, E.SRV.030.

---

## E.SRV.029 — `/api/set-fps-cap` advisor rejection (200/400 split)

**Trigger:** Cap is integer and in range, but `fps_advisor.set_game_fps_cap` returns `(False, message)` (e.g., the value is not in the standard cap whitelist).
**Where:** `server.py:267-271`.
**What it means (plain English):** Returns 200 if `ok=True`, else 400 — sharing the same JSON shape `{"ok", "message", "cap"}`. Clients should look at `ok` to differentiate, not the status code alone.
**Symptoms:** 400 with `{"ok": false, "message": "<advisor reason>", "cap": <value>}`.
**Root cause(s):** Cap not on the supported whitelist; INI write blocked; advisor policy.
**How to fix (step-by-step):**
1. Pick a supported cap from `/api/fps-advice.standard_caps`.
**Prevention / hardening:** Surface the whitelist in the same endpoint response.
**Related:** E.SRV.030.

---

## E.SRV.030 — `/api/set-fps-cap` advisor exception (500)

**Trigger:** `set_game_fps_cap` raises (e.g., file-permission denied writing Engine.ini, disk full, file locked by game).
**Where:** `server.py:268-270`.
**What it means (plain English):** Unlike the polling endpoints, this is a write operation, so a real failure deserves a 500 with the exception message.
**Symptoms:** 500 `{"ok": false, "error": "set_game_fps_cap raised: <e>"}`.
**Root cause(s):** INI is read-only; game is currently writing the file; Defender quarantine.
**How to fix (step-by-step):**
1. Close the game.
2. Remove read-only flag.
3. Run as user with write access.
**Prevention / hardening:** Atomic-write to a temp file then rename to avoid partial INI corruption.
**Related:** E.SRV.029.

---

## E.SRV.031 — `/api/start` invalid device

**Trigger:** Body `{"device": "TPU"}` or any value not in `["CPU", "GPU"]`.
**Where:** `server.py:282-283`.
**What it means (plain English):** Strict allowlist; failure is a 400 with the legal list echoed back to aid debugging.
**Symptoms:** 400 `{"ok": false, "error": "device must be one of ['CPU', 'GPU']"}`.
**Root cause(s):** Stale UI; user override; future device label not yet wired.
**How to fix (step-by-step):**
1. Send `CPU` or `GPU`.
**Prevention / hardening:** When introducing a new device, update DEVICES, the UI, and `/api/preflight`'s allowlist together.
**Related:** E.SRV.007, E.SRV.032.

---

## E.SRV.032 — `/api/start` invalid monitoring_lib

**Trigger:** Body `{"monitoring_lib": "dxgi"}` (or `"bettercam"` when bettercam is not installed).
**Where:** `server.py:284-285`.
**What it means (plain English):** Same as E.SRV.014/E.SRV.019 but in the start path. Importantly, `_allowed_monitoring_libs()` returns only `["mss"]` if `BETTERCAM_OK` is False — passing `"bettercam"` on such a build is rejected here, not at `_grab_preview_jpeg`.
**Symptoms:** 400 with the legal list.
**Root cause(s):** bettercam not importable on this Python; user override.
**How to fix (step-by-step):**
1. `pip install bettercam` if you need it.
2. Otherwise, send `mss`.
**Prevention / hardening:** UI should only show available libs (it does, via `/api/init`).
**Related:** E.SRV.014, E.SRV.019.

---

## E.SRV.033 — `/api/start` missing model field

**Trigger:** Body without `model` or with `model: null`.
**Where:** `server.py:287-289`.
**What it means (plain English):** `_resolve_safe_model_path(None)` returns `None`; the route emits 400.
**Symptoms:** 400 `{"ok": false, "error": "model not found or invalid: None"}`.
**Root cause(s):** Form binding bug; race when dropdown not populated.
**How to fix (step-by-step):**
1. Disable Start until `default_model` is set.
2. Send `model` as a string.
**Prevention / hardening:** See E.SRV.004 (schema validation).
**Related:** E.SRV.003-E.SRV.005.

---

## E.SRV.034 — `/api/start` missing monitor_id

**Trigger:** Body without `monitor_id`.
**Where:** `server.py:291-292`.
**What it means (plain English):** Explicit `None` check before the int cast block, so the 400 message is clearer than "numeric field must be int".
**Symptoms:** 400 `{"ok": false, "error": "monitor_id required"}`.
**Root cause(s):** UI bug; user clicked Start before selecting a monitor.
**How to fix (step-by-step):**
1. Choose a monitor first.
**Prevention / hardening:** Disable Start while `monitor_id` is unset.
**Related:** E.SRV.035.

---

## E.SRV.035 — `/api/start` non-integer numeric field

**Trigger:** Any of `monitor_id`, `hit_ante`, `nb_cpu_threads`, `cpu_affinity_mask` is non-castable to int.
**Where:** `server.py:294-300`.
**What it means (plain English):** Wrapped in a single try/except; a single failure causes a single 400 referencing the offending error message. The exception attribute is included so the field with the problem can be inferred.
**Symptoms:** 400 `{"ok": false, "error": "numeric field must be int: <ValueError>"}`.
**Root cause(s):** UI sending strings; user-edited config.
**How to fix (step-by-step):**
1. Coerce values to int client-side.
**Prevention / hardening:** Catch each cast separately to identify which field failed.
**Related:** E.SRV.004, E.SRV.027.

---

## E.SRV.036 — `/api/start` `hit_ante` out of range

**Trigger:** `hit_ante < 0 or > 1000`.
**Where:** `server.py:302-303`.
**What it means (plain English):** Domain check on the antenna count.
**Symptoms:** 400 `{"ok": false, "error": "hit_ante out of range"}`.
**Root cause(s):** Slider miswired; user override.
**How to fix (step-by-step):**
1. Use a value in [0, 1000].
**Prevention / hardening:** Clamp on the client too.
**Related:** E.SRV.037.

---

## E.SRV.037 — `/api/start` `nb_cpu_threads` out of range

**Trigger:** Value < 1 or > 256.
**Where:** `server.py:304-305`.
**What it means (plain English):** Defends against zero (which would deadlock ONNX runtime) and against absurdly large values that could OOM.
**Symptoms:** 400 `{"ok": false, "error": "nb_cpu_threads out of range"}`.
**Root cause(s):** UI bug; user override.
**How to fix (step-by-step):**
1. Use a value in [1, 256], typically the CPU core count or one of the presets.
**Prevention / hardening:** Cap at `os.cpu_count()` server-side too.
**Related:** E.SRV.036, E.SRV.038.

---

## E.SRV.038 — `/api/start` negative `cpu_affinity_mask`

**Trigger:** Value < 0.
**Where:** `server.py:306-307`.
**What it means (plain English):** Affinity masks are bitfields; negatives are nonsensical. `0` is the documented sentinel for "no override".
**Symptoms:** 400 `{"ok": false, "error": "cpu_affinity_mask must be >= 0"}`.
**Root cause(s):** Off-by-one; signed/unsigned mistake.
**How to fix (step-by-step):**
1. Use a non-negative bitmask, or 0 for default.
**Prevention / hardening:** Validate the mask fits in the host's CPU count (`mask < (1 << os.cpu_count())`).
**Related:** E.SRV.037.

---

## E.SRV.039 — `/api/start` race: already running (409)

**Trigger:** Two clients (or two clicks) POST `/api/start` while the worker is starting/running.
**Where:** `server.py:320-322`.
**What it means (plain English):** The `worker_lock` guarantees only one POST can pass the status check. The second POST sees `state.status in ("starting", "running")` and is rejected with 409 Conflict — the canonical "request can't apply because of state".
**Symptoms:** 409 `{"ok": false, "error": "already running"}`.
**Root cause(s):** Double-click; two browser tabs; programmatic retry.
**How to fix (step-by-step):**
1. UI should disable Start while `status != "idle"`.
2. Retry only after status returns to idle.
**Prevention / hardening:** Add an idempotency token so retries are safely no-ops.
**Related:** E.SRV.040, E.SRV.045.

---

## E.SRV.040 — `/api/start` race: previous worker still alive (409)

**Trigger:** State already transitioned out of running but the thread has not exited yet (slow GPU release, tear-down hang).
**Where:** `server.py:323-325`.
**What it means (plain English):** Defensive secondary check — `state.status` could be "idle" while the OS thread still runs after a botched shutdown. Without this guard, two threads could share `state` and `worker_holder`.
**Symptoms:** 409 `{"ok": false, "error": "previous worker still alive"}`.
**Root cause(s):** Worker stuck on `cv2.dnn` or driver call; GPU TDR.
**How to fix (step-by-step):**
1. Wait a few seconds and retry.
2. If persistent, restart the server (E.SRV.046 covers worker abandonment).
**Prevention / hardening:** Promote `state.status` and `worker_holder` consistency by setting status only after the join, not before.
**Related:** E.SRV.039, E.SRV.046.

---

## E.SRV.041 — Two workers spawned without `worker_lock` (historical)

**Trigger:** Hypothetical: if `worker_lock` were removed.
**Where:** `server.py:91`, `server.py:320`.
**What it means (plain English):** The comment in the source explicitly calls out this scenario: without the lock, two parallel POSTs could both pass the status gate before either spawned a worker, leading to a leaked worker that never gets stopped because `worker_holder["worker"]` only stores the last one.
**Symptoms:** N/A in current code; would manifest as duplicate inference, thrashing GPU, leaked threads.
**Root cause(s):** Missing critical-section.
**How to fix (step-by-step):**
1. Keep the lock.
**Prevention / hardening:** Document the invariant: every read-modify-write of `worker_holder` and `state.status` must hold `worker_lock`.
**Related:** E.SRV.039, E.SRV.040, E.SRV.045.

---

## E.SRV.042 — `state.reset_for_run()` called inside the lock

**Trigger:** Normal start path.
**Where:** `server.py:327`.
**What it means (plain English):** Done under the lock so the new worker observes a clean state. If reset were outside the lock, a subsequent reader might see partial state.
**Symptoms:** No user-facing error; this is a correctness invariant.
**Root cause(s):** N/A.
**How to fix (step-by-step):**
1. Don't move it outside the lock during refactors.
**Prevention / hardening:** Add a comment.
**Related:** E.SRV.041.

---

## E.SRV.043 — `InferenceWorker.start()` failure inside lock

**Trigger:** Worker constructor or `start()` raises (e.g., model file became unreadable between validation and load).
**Where:** `server.py:328-330`.
**What it means (plain English):** This is an **uncaught** exception. If `InferenceWorker(state, config)` or `worker.start()` raises while the lock is held, the exception bubbles to Flask, returning 500 with no JSON body. The lock is released by `with`. `worker_holder["worker"]` may be set to a non-started worker, and `state` may be in `running` state from `reset_for_run` (depending on its semantics).
**Symptoms:** 500 (Flask default HTML page). Subsequent `/api/start` may return 409 because `worker_holder` still contains a half-spawned worker.
**Root cause(s):** Race deletion of model file; thread limit exceeded; OS thread spawn failure.
**How to fix (step-by-step):**
1. Restart the server.
2. Investigate stack trace.
**Prevention / hardening:** Wrap construct+start in try/except, clear `worker_holder` and reset state on failure, return JSON 500.
**Related:** E.SRV.044, E.SRV.046.

---

## E.SRV.044 — `state.reset_for_run` exception leaves stale state

**Trigger:** `reset_for_run` raises (defensive — currently unlikely).
**Where:** `server.py:327`.
**What it means (plain English):** Same risk as E.SRV.043 but earlier; the worker is never created, but the lock is released and any partial state may persist.
**Symptoms:** 500. `state.status` indeterminate.
**Root cause(s):** Bug in AppState.
**How to fix (step-by-step):**
1. Restart server.
**Prevention / hardening:** Wrap the entire critical section in try/except with a clear rollback.
**Related:** E.SRV.043.

---

## E.SRV.045 — `/api/stop` with no worker

**Trigger:** POST `/api/stop` while idle.
**Where:** `server.py:336-340`.
**What it means (plain English):** Fast path: if `worker_holder["worker"]` is None or the worker is not alive, nothing to do — clears the slot, sets status to idle, and returns 200 with a friendly note. This is intentional so the UI's Stop button is always safe to click.
**Symptoms:** 200 `{"ok": true, "note": "no worker was running"}`.
**Root cause(s):** Idempotent stop.
**How to fix (step-by-step):**
1. None needed.
**Prevention / hardening:** This is the model.
**Related:** E.SRV.046.

---

## E.SRV.046 — `/api/stop` join timeout (500)

**Trigger:** Worker fails to terminate within 5 seconds of `request_stop()`.
**Where:** `server.py:346-352`.
**What it means (plain English):** The join is performed **outside** the lock so a hung shutdown doesn't deadlock new requests. After 5 seconds, the server gives up, sets state to error with a fixed message, clears `worker_holder` (so further start attempts can succeed in principle), and returns 500.
**Symptoms:** 500 `{"ok": false, "error": "worker join timed out"}`. Status becomes `error` with message "Worker did not stop within 5s — restart the app."
**Root cause(s):** Worker stuck in C/C++ extension that ignores Python-level cooperation; GPU command queue stuck; deadlock between worker and lock; bettercam DXGI release blocking.
**How to fix (step-by-step):**
1. Note: the worker is **not killed**, just abandoned. It still consumes the GPU until process exit.
2. Restart the server process.
3. Investigate logs for which subsystem hung.
**Prevention / hardening:** Increase the timeout configurably; add a hard daemon flag so the OS reaps the thread on process exit; add per-stage timeouts inside the worker.
**Related:** E.SRV.040, E.SRV.043, E.SRV.058.

---

## E.SRV.047 — Lock held across `request_stop()` (intentional)

**Trigger:** Normal stop.
**Where:** `server.py:335-343`.
**What it means (plain English):** `request_stop` is called inside the lock so concurrent starts cannot observe a half-stopped state. This is correct, but if `request_stop` itself blocks (it shouldn't — it should just flip a flag), it would block other requests. As written it's safe.
**Symptoms:** None under normal conditions.
**Root cause(s):** N/A.
**How to fix (step-by-step):**
1. Ensure `request_stop` remains O(1).
**Prevention / hardening:** Audit `request_stop` for IO.
**Related:** E.SRV.046.

---

## E.SRV.048 — Atexit `_stop_worker` race during interpreter shutdown

**Trigger:** Process exit while a worker is alive.
**Where:** `app_flask.py:15-21` (`_stop_worker`), `app_flask.py:38` (`atexit.register`).
**What it means (plain English):** Python's atexit runs after most threads have been joined or marked daemon. If the worker thread is non-daemon, the interpreter waits for it to finish before atexit fires — meaning `_stop_worker` may be called too late to help. If it is daemon, the thread can be killed mid-step, potentially leaving GPU resources in an undefined state.
**Symptoms:** Console message "Warning: worker did not stop within 5s — process exit may hang."
**Root cause(s):** Worker not honoring stop flag fast enough; GPU work in flight.
**How to fix (step-by-step):**
1. Wait or `taskkill /F`.
**Prevention / hardening:** Use a context manager for the worker; explicitly stop and join before `app.run()` returns.
**Related:** E.SRV.046, E.SRV.049.

---

## E.SRV.049 — Signal handler triggers `sys.exit(0)` mid-request

**Trigger:** SIGINT (Ctrl-C) or SIGTERM during a request.
**Where:** `app_flask.py:40-46`.
**What it means (plain English):** The handler stops the worker then calls `sys.exit(0)`, which raises SystemExit on the main thread. Because Flask's dev server is `threaded=True`, in-flight worker request threads may not be cleanly torn down. Responses to those requests can be truncated.
**Symptoms:** Open requests hang or fail with connection reset; UI may show network errors.
**Root cause(s):** Cooperative shutdown semantics in Flask dev server.
**How to fix (step-by-step):**
1. Refresh the page after restart.
**Prevention / hardening:** Migrate to a production server (waitress, gunicorn) with proper graceful shutdown.
**Related:** E.SRV.048, E.SRV.054.

---

## E.SRV.050 — SIGTERM registration suppressed on Windows services

**Trigger:** Running under a Windows service host that disallows custom SIGTERM handlers.
**Where:** `app_flask.py:47-52`.
**What it means (plain English):** `signal.signal(SIGTERM, ...)` raises `ValueError` or `OSError` in some restricted contexts. The code swallows both. As a consequence, when the service manager terminates the process, the worker is not gracefully stopped — only atexit might run, and only sometimes.
**Symptoms:** Silent. Worker abandoned at shutdown.
**Root cause(s):** Windows signal model; service-host policy.
**How to fix (step-by-step):**
1. If running as a service, register a `SERVICE_CONTROL_STOP` callback through pywin32 instead.
**Prevention / hardening:** Log a debug message when SIGTERM registration fails so operators know shutdown is degraded.
**Related:** E.SRV.048, E.SRV.049.

---

## E.SRV.051 — Atexit not called on hard kill

**Trigger:** `taskkill /F`, kernel OOM kill, BSOD.
**Where:** `app_flask.py:38`.
**What it means (plain English):** `atexit` only fires for normal Python exits; SIGKILL-equivalent kills bypass it. The worker is hard-terminated; GPU contexts may leak until driver garbage collection.
**Symptoms:** Worker disappears with no log; may need driver reset.
**Root cause(s):** Force kill.
**How to fix (step-by-step):**
1. Avoid /F; use Ctrl-C or normal stop.
**Prevention / hardening:** Use a watchdog to clean up GPU state at next start.
**Related:** E.SRV.048, E.SRV.050.

---

## E.SRV.052 — `--port` already in use

**Trigger:** Another process holds port 7860.
**Where:** `app_flask.py:55` (`app.run`).
**What it means (plain English):** Flask raises `OSError: [Errno 48] Address already in use` (or WSAEADDRINUSE on Windows). The exception propagates and the process dies before `atexit` would do anything useful.
**Symptoms:** Stack trace at startup.
**Root cause(s):** Stale instance; conflicting service.
**How to fix (step-by-step):**
1. `netstat -ano | findstr :7860` to find the holder.
2. `taskkill /PID <pid>` or pass `--port` with a different value.
**Prevention / hardening:** Probe the port first and exit with a friendly message.
**Related:** E.SRV.053.

---

## E.SRV.053 — `--host` invalid value

**Trigger:** `--host 999.999.999.999` or non-routable address.
**Where:** `app_flask.py:26`, `app_flask.py:55`.
**What it means (plain English):** argparse accepts any string. Flask/Werkzeug raises during bind.
**Symptoms:** Startup stack trace.
**Root cause(s):** Typo.
**How to fix (step-by-step):**
1. Use `127.0.0.1` or `0.0.0.0`.
**Prevention / hardening:** Validate with `ipaddress.ip_address` before passing to Flask.
**Related:** E.SRV.052.

---

## E.SRV.054 — `threaded=True` reentrancy on shared state

**Trigger:** Concurrent requests from multiple browser tabs.
**Where:** `app_flask.py:55`.
**What it means (plain English):** Flask's dev server with `threaded=True` runs each request in its own thread. The server code uses `worker_lock` for start/stop and otherwise relies on `AppState` being internally thread-safe. Any unprotected mutation of shared state outside `AppState` (e.g., the `worker_holder` dict outside the lock) is a latent race.
**Symptoms:** None observable unless `AppState` has a bug.
**Root cause(s):** Concurrency.
**How to fix (step-by-step):**
1. Audit `AppState.snapshot/get_live_frame/get_last_hit_frame` for thread safety.
**Prevention / hardening:** Add a unit test that hammers `/api/start` and `/api/stop` from many threads.
**Related:** E.SRV.041, E.SRV.055.

---

## E.SRV.055 — `worker_holder` dict accessed without lock in some paths

**Trigger:** N/A — by inspection. `/api/stop` reads `worker_holder.get("worker")` inside the lock and writes to it inside the lock; `/api/start` likewise. The atexit/signal handler accesses it from the main thread without the lock.
**Where:** `app_flask.py:16`, `server.py:336`, `server.py:323`.
**What it means (plain English):** During shutdown, `_stop_worker` reads `worker_holder["worker"]` without acquiring `worker_lock`. In practice this is safe because only the main thread runs at that point, but a future refactor that runs the handler from a worker thread would introduce a race.
**Symptoms:** None today.
**Root cause(s):** Lock-discipline drift risk.
**How to fix (step-by-step):**
1. None.
**Prevention / hardening:** Add a comment.
**Related:** E.SRV.054.

---

## E.SRV.056 — `request.get_json(silent=True)` masks Content-Type quirks

**Trigger:** POST without `Content-Type: application/json` even if body is JSON.
**Where:** `server.py:256` (`/api/set-fps-cap`), `server.py:275` (`/api/start`).
**What it means (plain English):** With `silent=True`, Flask returns `None` rather than raising for both "wrong content type" and "malformed JSON". The downstream `or {}` makes them indistinguishable from "empty body". The user sees a generic field-missing error.
**Symptoms:** 400 with a misleading error like "model not found or invalid: None" when the actual problem was the missing header.
**Root cause(s):** curl users forgetting `-H 'Content-Type: application/json'`.
**How to fix (step-by-step):**
1. Add the header explicitly.
**Prevention / hardening:** Require the header explicitly and return 415 Unsupported Media Type when missing.
**Related:** E.SRV.026, E.SRV.057.

---

## E.SRV.057 — Empty JSON body treated as empty dict

**Trigger:** POST with `Content-Type: application/json` but empty body, or `null`, or `[]`.
**Where:** `server.py:275`.
**What it means (plain English):** `request.get_json(silent=True) or {}` collapses null and any falsy result into `{}`. A literal JSON `[]` (truthy by Python's standards if non-empty, but falsy if empty) is also coerced. This means downstream `body.get("model")` returns `None`, going through the missing-field code path.
**Symptoms:** Whichever required-field error fires first (typically model invalid).
**Root cause(s):** Bad client.
**How to fix (step-by-step):**
1. Send a JSON object.
**Prevention / hardening:** Validate `isinstance(body, dict)` and return 400 if not.
**Related:** E.SRV.056.

---

## E.SRV.058 — State desync after worker self-exit

**Trigger:** Worker thread exits on its own (success or unhandled exception) without a `/api/stop` POST.
**Where:** `server.py:323-325` (recovery path).
**What it means (plain English):** If the worker exits without stop, `worker_holder["worker"]` still references the dead thread. The next `/api/start` checks `existing.is_alive()` — it's False — so the start proceeds normally, replacing the holder. State must have been updated by the worker before exit (an AppState concern); otherwise UI may show "running" while the thread is dead.
**Symptoms:** UI stuck on "running". `/api/start` may succeed cleanly after a refresh.
**Root cause(s):** Worker raised an unhandled exception; AppState not updated to error/idle on exit.
**How to fix (step-by-step):**
1. POST `/api/stop` to clear; then start again.
**Prevention / hardening:** Worker must use a try/finally to set status to "error" or "idle" on exit, no matter the cause.
**Related:** E.SRV.046, E.SRV.040.

---

## E.SRV.059 — Logging side-effects from `log.exception`

**Trigger:** Any exception path that calls `log.exception`.
**Where:** Multiple — `server.py:100, 125, 152, 163, 182, 210, 269`.
**What it means (plain English):** `log.exception` writes a stack trace to stderr at ERROR level. If the logger is misconfigured (e.g., file handler refusing writes) or the trace is huge, the call itself can raise. Python normally swallows logging exceptions but rare configurations propagate them, masking the original error.
**Symptoms:** Possible secondary 500 with no JSON body.
**Root cause(s):** Logging config edge case.
**How to fix (step-by-step):**
1. Verify `logging.basicConfig` succeeded.
2. Avoid custom handlers that raise.
**Prevention / hardening:** Use `logging.raiseExceptions = False` in production.
**Related:** all 503/500 paths.

---

## E.SRV.060 — `use_reloader=False` masks code reload failures

**Trigger:** Editing source while the server is running.
**Where:** `app_flask.py:55`.
**What it means (plain English):** The reloader is explicitly disabled. This is correct (the reloader spawns a child process that would create two workers and double-poll the GPU), but it means developers must restart manually. Forgetting to restart leads to confusing "this should be fixed" reports because old code is still running.
**Symptoms:** Behavior doesn't match source on disk.
**Root cause(s):** Stale process.
**How to fix (step-by-step):**
1. Stop and restart.
**Prevention / hardening:** Print a startup banner including the git hash so devs can verify the running code.
**Related:** all routes.
