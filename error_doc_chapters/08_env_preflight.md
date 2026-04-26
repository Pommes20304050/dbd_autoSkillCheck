# Chapter 8 — Environment & Preflight Errors

The Info page (`/api/info`, served by `dbd/web/env_info.py`) and the Preflight Advisor banner (`/api/preflight`, served by `dbd/web/preflight.py`) are the two layers of "what's wrong with your setup" telemetry in the Flask UI.

- **`env_info.py`** is descriptive: it reports Python version, OS, CUDA driver/toolkit, and the install state of every package the project might use, redacted for privacy and cached for 60 seconds. It only *reports* — it never raises a banner.
- **`preflight.py`** is prescriptive: it converts the same probes (plus models-folder scanning and provider introspection) into actionable banner messages with a stable i18n code, severity tier, and format placeholders. Cached for 30 seconds. The frontend localizes the codes and renders them as a stack of dismissible banners.

Both modules are intentionally side-effect-light: they use `importlib.metadata.version()` rather than `import` so probing TensorRT or PyTorch on the Info page doesn't load CUDA runtimes or spend 800 ms initializing a tensor library that the user may not actually be running.

This chapter walks every failure mode of `env_info.collect()`, every issue code emitted by `preflight.collect_issues()`, and the surrounding cache/severity infrastructure. Each entry is numbered E.ENV.NNN.

---

## A. Environment-Info Probe Failures (`env_info.py`)

### E.ENV.001 — `importlib.metadata` raises for namespace packages
**Trigger:** A "package" listed in `REQUIRED_PACKAGES` is actually a PEP 420 namespace package (no installer-recorded distribution metadata) or was vendored without an `*.dist-info` directory.
**Where:** `env_info.py:_pkg_version` (line ~56), called from `collect()` (line ~176).
**What it means (plain English):** Python's "what's installed?" lookup table doesn't list the package — even though `import <pkg>` may succeed — so the Info page reports "not installed" even when the user can use it.
**Symptoms:** Red dot next to a package on the Info page despite the user swearing they have it. The corresponding Preflight banner (`preflight.missing.*`) also lights up incorrectly.
**Root cause(s):**
- Source-tree install with no metadata (`PYTHONPATH` hack, `pip install --no-build-isolation` gone wrong, plain `git clone` into `site-packages`).
- Namespace package split across multiple distributions where only the sub-distribution carries metadata.
- Distribution renamed (e.g. `Pillow` vs `pillow` vs `PIL` import name); we look up the *distribution* name, not the import name.
**How to fix:**
1. Reinstall the package via pip: `pip install --force-reinstall --no-deps <dist>`.
2. Confirm `pip show <dist>` returns a record — that's exactly what `md.version()` reads.
3. If the user vendored sources, copy the matching `*.dist-info/` directory next to the package.
**Prevention / hardening:** `_pkg_version` already wraps both `PackageNotFoundError` and bare `Exception` to return `None` cleanly — so the failure surfaces as "not installed" rather than crashing the page.
**Related:** E.ENV.002 (opencv variant), every `preflight.missing.*` entry in section B.

---

### E.ENV.002 — Spurious package detection: `opencv-python` vs `opencv-contrib-python`
**Trigger:** User has `opencv-contrib-python` installed but no `opencv-python` distribution; both ship the `cv2` import, but only one is queried.
**Where:** `env_info.py:REQUIRED_PACKAGES` row 3 (`"opencv-python"`); `preflight.py:_collect_base()` line ~52.
**What it means (plain English):** OpenCV is functionally available (`import cv2` works) but our detector is asking for the wrong distribution name, so we report "missing" and emit `preflight.missing.opencv` — a false danger.
**Symptoms:** Red banner "OpenCV missing" but the app actually runs fine; or the user installed `opencv-contrib-python-headless` for server use and gets two false positives at once.
**Root cause(s):** There are four mutually-exclusive PyPI distributions that all provide `cv2`: `opencv-python`, `opencv-python-headless`, `opencv-contrib-python`, `opencv-contrib-python-headless`. We only check the first.
**How to fix:**
1. Install plain `opencv-python` alongside (they conflict — pick one).
2. Or extend `_pkg_installed("opencv-python")` to fall through to the other three names before declaring it missing.
**Prevention / hardening:** Replace the single-name lookup with a tuple fallback: `for name in ("opencv-python", "opencv-contrib-python", "opencv-python-headless", "opencv-contrib-python-headless"): if (v := _pkg_installed(name)): break`.
**Related:** E.ENV.001, E.ENV.B03 (`preflight.missing.opencv`).

---

### E.ENV.003 — `nvcc` not on PATH
**Trigger:** CUDA toolkit installed but `nvcc.exe` directory not added to PATH.
**Where:** `env_info.py:_cuda_toolkit` (line ~127): `nvcc = shutil.which("nvcc")`.
**What it means (plain English):** We can't find the CUDA compiler binary, so the Info page shows "CUDA toolkit version: unknown" even when the toolkit is installed.
**Symptoms:** Info page shows `cuda_toolkit.version = null`; users see a blank "CUDA Toolkit" row even though `nvidia-smi` reports a CUDA *driver* version.
**Root cause(s):**
- Toolkit installed via the runfile installer without selecting "Add to PATH".
- User installed a `cuda-runtime` Conda package (no `nvcc`, that's a separate `cuda-nvcc` package).
- Multiple CUDA toolkits installed; the new one didn't replace `CUDA_PATH`.
**How to fix:**
1. Add `%CUDA_PATH%\bin` to PATH (Windows) or `$CUDA_HOME/bin` (Linux).
2. Open a new shell — PATH changes don't apply to running processes.
3. Verify with `nvcc --version` from a fresh terminal.
**Prevention / hardening:** `_cuda_toolkit` falls back to reading `CUDA_PATH` / `CUDA_HOME` env vars even when `nvcc` is absent — at least the install root surfaces.
**Related:** E.ENV.004 (env vars wrong), E.ENV.010 (nvidia-smi missing).

---

### E.ENV.004 — `CUDA_PATH` / `CUDA_HOME` points to wrong toolkit
**Trigger:** Env var inherited from a previous toolkit version that was uninstalled, or a manually-set value that doesn't match the active install.
**Where:** `env_info.py:_cuda_toolkit` line ~126: `home = os.environ.get("CUDA_PATH") or os.environ.get("CUDA_HOME")`.
**What it means (plain English):** The Info page reports a CUDA toolkit *home* directory that no longer exists or contains a different version than `nvcc --version` says — confusing users when they try to compile against it.
**Symptoms:** `cuda_toolkit.home` shows `~/CUDA/v11.8` but `cuda_toolkit.version = "12.5"`. PyTorch / TensorRT may pick up the stale path and fail to load DLLs.
**Root cause(s):**
- Side-by-side CUDA installs where the uninstaller didn't repoint `CUDA_PATH`.
- Manual `set CUDA_PATH=...` in a `.bat` file that's stale.
- WSL bind mount inheriting Windows env vars.
**How to fix:**
1. Set `CUDA_PATH` to the correct toolkit root (`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.5`).
2. Reboot — Windows services and explorer.exe cache the env block.
3. If using `pythonnet` / TensorRT, also clear `CUDA_PATH_V11_8` etc. for unused versions.
**Prevention / hardening:** `_cuda_toolkit` reports both `home` and `nvcc_path` separately so the inconsistency is *visible* rather than silently wrong.
**Related:** E.ENV.003, E.ENV.011 (torch CUDA build).

---

### E.ENV.005 — Python <3.10 rejected (formally <3.9 by spec, enforced as <3.10 by preflight)
**Trigger:** User running Python 3.8 / 3.9 / pre-3.10. (The chapter brief says <3.9, but the actual preflight rule is `py_minor < 10`.)
**Where:** `preflight.py:collect_issues` line ~189: `if py_major != 3 or py_minor < 10 or py_minor > 12:`.
**What it means (plain English):** The codebase uses syntax/stdlib features (`match` statements, `int | None` unions, `importlib.metadata` 3.10+ API) that won't run or weren't validated on older interpreters.
**Symptoms:** `preflight.python.versionUntested` info-banner; possibly `SyntaxError` at import time on 3.9; `ImportError` for `importlib.metadata.PackageNotFoundError` on 3.7.
**Root cause(s):** System Python on stale Linux distros, Conda env created with an old default, Windows Store Python 3.9.
**How to fix:**
1. Install Python 3.11 or 3.12 from python.org.
2. Recreate the venv: `py -3.11 -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`.
3. Don't use 3.13+ until ONNX Runtime / PyTorch publish wheels for it.
**Prevention / hardening:** Banner is `info` severity, not `danger` — so the user can dismiss it on 3.13 if everything happens to work.
**Related:** E.ENV.006 (3.13+ untested), E.ENV.B21 (`preflight.python.versionUntested`).

---

### E.ENV.006 — Python 3.13+ untested
**Trigger:** User on Python 3.13 / 3.14.
**Where:** Same line as E.ENV.005 — `py_minor > 12` triggers the same code.
**What it means (plain English):** ONNX Runtime, PyTorch, TensorRT, and `pythonnet` typically lag CPython releases by 3-9 months. Even if our code is forward-compatible, the inference stack may not have wheels.
**Symptoms:** `pip install onnxruntime-gpu` fails with "no matching distribution"; `pip install torch` only installs the latest CPU wheel; `tensorrt` build fails.
**Root cause(s):** Cutting-edge CPython release; Anaconda / pyenv defaulting to "latest".
**How to fix:** Pin to 3.11 or 3.12 — the matrix where every dependency has Windows wheels.
**Prevention / hardening:** The version check displays the actual version in the banner via the `version` fmt placeholder, so the user immediately sees they're outside the tested range.
**Related:** E.ENV.005.

---

### E.ENV.007 — 32-bit Python rejected
**Trigger:** User accidentally installed 32-bit CPython.
**Where:** `env_info.py:_python_info` line ~70: `"bits": "64-bit" if sys.maxsize > 2**32 else "32-bit"`.
**What it means (plain English):** ONNX Runtime, PyTorch, TensorRT publish only 64-bit wheels. A 32-bit interpreter will get nothing but pure-Python deps and the inference stack will fail to install.
**Symptoms:** Info page bits row reads "32-bit"; every optional inference package is missing; `pip install torch` says "no matching distribution".
**Root cause(s):** Windows Store Python 3.x (32-bit was the default for years), legacy `python-3.x.x.exe` installer with x86 selected.
**How to fix:**
1. Uninstall the 32-bit interpreter.
2. Install python.org **Windows installer (64-bit)** — explicitly check the bitness on the download page.
3. Recreate the venv using the new interpreter.
**Prevention / hardening:** The Info page displays the bit-width prominently so users notice the issue before chasing a missing wheel.
**Related:** None (no preflight code yet — could be added as `preflight.python.is32Bit`).

---

### E.ENV.008 — HOME path leakage (privacy regression)
**Trigger:** A redaction path in `_redact()` fails to match because `os.path.expanduser("~")` returns a different casing or trailing-separator variant than what's embedded in the leaked path.
**Where:** `env_info.py:_redact` (line ~25-36).
**What it means (plain English):** The Info page is shown in the browser; if `_redact` doesn't strip the user's home directory from `sys.executable`, `nvcc_path`, or `CUDA_PATH`, the OS username shows up in the rendered HTML — a real privacy issue when users screenshot the page for support.
**Symptoms:** Info page shows `C:\Users\louisgottschlich11\...` instead of `~\...`. Visible when the user shares a screenshot.
**Root cause(s):**
- Casing mismatch on Windows: `expanduser` may return `C:\Users\Louis` while `sys.executable` has `c:\users\louis`.
- UNC paths starting with `\\?\C:\Users\...`.
- Symlinked home (`/home/louis -> /mnt/data/louis`).
**How to fix:**
1. Normalize both paths via `os.path.normcase(os.path.normpath(...))` before substring match.
2. Add `USERPROFILE` (Windows) and `HOME` (POSIX) env-var fallbacks to the home candidate set.
**Prevention / hardening:** `_redact` already wraps in `try/except` and falls through to the original path — at worst, redaction silently fails open. Consider also redacting `LOGNAME` / `USERNAME` env-var values literally.
**Related:** Every `_redact()`-wrapped output: `python.executable`, `cuda_toolkit.home`, `cuda_toolkit.nvcc_path`.

---

### E.ENV.009 — 60-second TTL cache returns stale data
**Trigger:** User installs/uninstalls a package while the Info page is open; the next reload shows the *previous* state for up to 60 s.
**Where:** `env_info.py` lines 21-22 (`_CACHE`, `_CACHE_TTL_S = 60.0`) and `collect()` line ~170.
**What it means (plain English):** The Info page is cached for 60 seconds to avoid re-spawning `nvidia-smi` and re-importing torch on every refresh — but that means newly-installed packages won't show up immediately.
**Symptoms:** User runs `pip install onnxruntime-gpu`, refreshes Info page, still sees "not installed". Refreshes again 60s later — now installed.
**Root cause(s):** Module-level cache with no invalidation hook on the Info path. (`preflight.py` has `invalidate_cache()` but `env_info.py` does not.)
**How to fix:**
1. Wait 60 s and refresh.
2. Restart the Flask server to force a cold cache.
3. Patch: add an `invalidate_cache()` symmetric to `preflight.invalidate_cache()` and call it from a "refresh" button.
**Prevention / hardening:** The TTL is short enough to be self-healing; the alternative (no cache) made the page take 1.5 s due to nvidia-smi spawn cost.
**Related:** E.ENV.C01 (preflight cache invalidation).

---

### E.ENV.010 — `_safe()` sub-probe wrapping (graceful single-probe failure)
**Trigger:** Any of `_python_info`, `_os_info`, `_nvidia_info`, `_cuda_toolkit`, `_torch_cuda` raises an unexpected exception.
**Where:** `env_info.py:collect()` lines 189-200, the inline `_safe(fn, fallback)` helper.
**What it means (plain English):** Each sub-probe is independently wrapped, so a single broken probe (e.g. nvidia-smi crashes mid-pipe) returns the fallback dict with an `error` field rather than blanking the entire Info page.
**Symptoms:** One Info-page card shows an error string; the others render normally. Without `_safe`, the entire page would render an HTTP 500.
**Root cause(s):** This is the *defense*, not a bug. Listed here for completeness — when reading the chapter, if a sub-probe consistently shows `error: ...`, dig into the relevant section.
**How to fix:** Inspect the `error` field on the failing card and treat as the corresponding probe's failure mode (E.ENV.003/004/011/012).
**Prevention / hardening:** `_safe` is the canonical pattern — replicate for any new sub-probe added to `collect()`.
**Related:** All env_info entries.

---

### E.ENV.011 — `nvidia-smi` CSV parse failure
**Trigger:** `nvidia-smi` runs but emits unexpected text (locale-translated, container without GPUs visible, driver-side error message instead of CSV).
**Where:** `env_info.py:_nvidia_info` lines 89-99 (CSV split) and lines 102-114 (CUDA-Version line scan).
**What it means (plain English):** We invoke `nvidia-smi --query-gpu=driver_version,name --format=csv,noheader`, then split on commas. If the output is empty, contains warning text on stderr (we suppress stderr but output may still be polluted), or is in a non-en_US locale, the parse silently produces `None` values.
**Symptoms:** Info page nvidia card shows "available: true" but `driver: null`, `gpu_name: null`. Or `cuda_runtime` is `None` because the second `nvidia-smi` call's "CUDA Version:" line is translated.
**Root cause(s):**
- Docker container with `--gpus none` — smi exists but reports "No devices were found".
- WSL2 without nvidia-cuda-toolkit-wsl integration.
- Non-English Windows locale changing the human-readable header line text.
- nvidia-smi version mismatch with driver (rare, after partial driver update).
**How to fix:**
1. Run `nvidia-smi` manually — confirm output looks like the parser expects.
2. Update GPU driver to a clean state.
3. For containers, add `--gpus all` to docker run.
4. Patch: switch the second probe from string-scanning to `--query-gpu=cuda_version` (a real CSV field) instead of grepping the human-readable banner.
**Prevention / hardening:** `creationflags=CREATE_NO_WINDOW` prevents a console flash on Windows; `timeout=2` prevents indefinite hangs; both calls catch `TimeoutExpired`, `CalledProcessError`, `OSError` cleanly.
**Related:** E.ENV.B20 (`preflight.nvidiaSmi.missing`).

---

### E.ENV.012 — `torch` import side-effects (CUDA init cost)
**Trigger:** `_torch_cuda()` imports torch when `_pkg_version("torch")` succeeds, which initializes CUDA on first call (~700 ms cold).
**Where:** `env_info.py:_torch_cuda` lines 152-165.
**What it means (plain English):** Unlike every other probe that uses `importlib.metadata` to *avoid* importing the package, the torch probe must actually `import torch` to call `torch.cuda.is_available()`. That triggers CUDA driver loading, runtime version negotiation, and possibly DLL loads — the first call to `/api/info` after server start is slow.
**Symptoms:** First Info page load takes 1-3 seconds; subsequent loads (within 60 s cache) are instant.
**Root cause(s):** `torch.cuda.is_available()` is genuinely expensive — it tries to load `nvcuda.dll`, query device count, and initialize a context. There's no "cheap" version.
**How to fix:**
1. Accept the one-time cost — the cache amortizes it.
2. If torch is installed but the user only uses ORT, the import is wasted; consider gating on a "show torch info" checkbox.
**Prevention / hardening:** Wrapped in `try/except Exception` so a broken torch install (DLL missing) returns `{"installed": True, "error": str(e)}` rather than 500ing the page.
**Related:** Same import happens in `preflight.py:_collect_base()` line 76 — both share the cost on a cold cache.

---

## B. Preflight Issue Codes (`preflight.py`)

Each subsection corresponds to one stable i18n code emitted by `collect_issues()`. The frontend looks up the code in its translation table and splices `fmt` placeholders into the localized string.

---

### E.ENV.B01 — `preflight.missing.flask`
**Trigger:** `md.version("flask")` returns `None`.
**Where:** `preflight.py:collect_issues` lines 117-127.
**What it means (plain English):** The web server itself can't run without Flask. This message would technically be unreachable in `/api/preflight` because the request handler can't fire without Flask… *unless* the user has a CLI/script path that imports `preflight` directly without Flask installed.
**Symptoms:** `danger` banner "Flask missing"; or, more likely, the entire web server fails to import with `ModuleNotFoundError: flask`.
**Root cause(s):**
- Fresh venv where `pip install -r requirements.txt` was skipped.
- Distribution where `flask` is named differently (extremely unlikely).
**How to fix:**
1. `pip install flask>=3.0`.
2. Re-run from the project root.
**Prevention / hardening:** `requirements.txt` line 9 pins `flask>=3.0`; this banner exists as a defensive fallback in case `preflight` is imported standalone.
**Related:** E.ENV.001.

---

### E.ENV.B02 — `preflight.missing.numpy`
**Trigger:** `md.version("numpy")` returns `None`.
**Where:** `preflight.py:collect_issues` lines 117-127.
**What it means (plain English):** NumPy is the foundational tensor/array library — every screenshot, every preprocessed frame, every model input flows through `np.ndarray`. Missing NumPy means no inference at all.
**Symptoms:** `danger` banner "NumPy missing"; downstream `ImportError: numpy` from the inference loop.
**Root cause(s):** Cleanup-pip uninstall, namespace package collision, broken NumPy 2.0 ABI mismatch with OpenCV.
**How to fix:**
1. `pip install --upgrade numpy`.
2. If OpenCV/torch complain about ABI, pin `numpy<2` until those packages catch up.
**Prevention / hardening:** Hard-pinned in `requirements.txt:13`.
**Related:** E.ENV.B03 (OpenCV often pulls in NumPy).

---

### E.ENV.B03 — `preflight.missing.opencv`
**Trigger:** `md.version("opencv-python")` returns `None`.
**Where:** `preflight.py:collect_issues` line ~126: distinct `pkg = "opencv-python"` substitution.
**What it means (plain English):** OpenCV powers the resize/normalize/format-conversion pipeline between mss/bettercam and the model input tensor. Without it, no preprocessed frames reach the model.
**Symptoms:** `danger` banner "OpenCV missing"; runtime `ImportError: cv2`.
**Root cause(s):** See E.ENV.002 — could be a false positive if user has `opencv-contrib-python`.
**How to fix:**
1. `pip install opencv-python` (note: not `cv2` — the import name and the distribution name differ).
2. If user wants extra cv modules, install `opencv-contrib-python` *instead*.
**Prevention / hardening:** Frontend banner displays the canonical pip-install name as the `pkg` placeholder.
**Related:** E.ENV.002.

---

### E.ENV.B04 — `preflight.missing.mss`
**Trigger:** `md.version("mss")` returns `None`.
**Where:** Same loop, lines 117-127.
**What it means (plain English):** MSS is the cross-platform screen-capture fallback. Even when `bettercam` is selected (Windows fast path), MSS is the safety net. Missing MSS means no screen capture at all on non-Windows or when bettercam fails.
**Symptoms:** `danger` banner "MSS missing"; capture loop fails to start.
**Root cause(s):** Trimmed-down install, custom requirements file.
**How to fix:** `pip install mss`.
**Prevention / hardening:** Pinned in `requirements.txt:15`.
**Related:** E.ENV.B18 (bettercam missing).

---

### E.ENV.B05 — `preflight.missing.pillow`
**Trigger:** `md.version("pillow")` returns `None`.
**Where:** Same loop.
**What it means (plain English):** Pillow encodes captured frames to PNG/JPEG for the live-preview WebSocket and the debug overlay. Without it, the live preview is blank but the model can still run.
**Symptoms:** `danger` banner "Pillow missing"; preview tile shows broken-image icon; some scripts that save debug captures crash.
**Root cause(s):** Distribution name collision with the legacy `PIL` package; Conda channel ordering.
**How to fix:** `pip install pillow`.
**Prevention / hardening:** Pinned in `requirements.txt:16`.
**Related:** E.ENV.B02.

---

### E.ENV.B06 — `preflight.missing.psutil`
**Trigger:** `md.version("psutil")` returns `None`.
**Where:** Same loop.
**What it means (plain English):** psutil drives the per-core CPU bars and total utilization graph on the Performance page. Missing psutil means the Performance page CPU section is blank but inference still runs.
**Symptoms:** `danger` banner "psutil missing"; Performance page CPU card empty.
**Root cause(s):** Build failure on uncommon platforms (psutil ships C extensions per OS).
**How to fix:** `pip install psutil>=5.9`. On exotic platforms, install the system C compiler first.
**Prevention / hardening:** Pinned `psutil>=5.9` in `requirements.txt:20` — older versions lack per-core temp/freq APIs.
**Related:** Performance page errors (separate chapter).

---

### E.ENV.B07 — `preflight.missing.onnxruntime`
**Trigger:** Both `onnxruntime` and `onnxruntime-gpu` are absent.
**Where:** `preflight.py:collect_issues` lines 130-132: `has_ort = base["onnxruntime"] is not None or base["onnxruntime_gpu"] is not None`.
**What it means (plain English):** No ONNX Runtime build is installed at all — neither CPU nor GPU. Inference will fail at the first model load.
**Symptoms:** `danger` banner "ONNX Runtime missing"; `ImportError: onnxruntime` at startup.
**Root cause(s):** `requirements.txt` deliberately doesn't pin ORT (line 33-34: "Listing neither here so an existing GPU install isn't clobbered by a CPU one"), so a fresh install requires a manual choice.
**How to fix:**
1. CPU baseline: `pip install onnxruntime`.
2. NVIDIA: `pip install onnxruntime-gpu` matching CUDA version (see ORT docs).
3. **Never install both** — DLL conflicts.
**Prevention / hardening:** The check accepts either distribution; only emits danger when both are missing.
**Related:** E.ENV.B16 (`gpu.needsOrtGpu`).

---

### E.ENV.B08 — `preflight.models.folderMissing`
**Trigger:** `os.path.isdir("models")` returns `False`.
**Where:** `preflight.py:_collect_base` line 59 and `collect_issues` line 135.
**What it means (plain English):** The relative `./models` directory doesn't exist. Either the user is launching from the wrong CWD, or they haven't downloaded the model artifacts.
**Symptoms:** `danger` banner "models folder missing"; model dropdown empty.
**Root cause(s):**
- Launching `python -m dbd.web.server` from outside the repo root (CWD-relative path).
- Cloning a fork that excluded the `models/` directory via `.gitignore`.
- Models stored on a different drive and never symlinked.
**How to fix:**
1. Launch from the repo root (where `models/` lives).
2. Download model files (link in repo README) and place them in `models/`.
3. Or symlink: `mklink /D models D:\models` (Windows).
**Prevention / hardening:** Could absolutize via `os.path.join(os.path.dirname(__file__), "..", "..", "models")`. Currently CWD-relative for simplicity.
**Related:** E.ENV.B09, E.ENV.B10.

---

### E.ENV.B09 — `preflight.models.empty`
**Trigger:** `models/` exists but contains no `.onnx` or `.trt` files.
**Where:** `preflight.py:_collect_base` lines 63-70 and `collect_issues` line 137-138.
**What it means (plain English):** The folder is there but empty (or only contains README/sidecar files). No model can be selected.
**Symptoms:** `danger` banner "models folder empty"; dropdown empty.
**Root cause(s):** Clone without LFS pull; download script aborted; user manually deleted models thinking they were stale.
**How to fix:**
1. `git lfs pull` if models are LFS-tracked.
2. Re-run download script from README.
3. Manually drop `*.onnx` files into `models/`.
**Prevention / hardening:** Filtering by extension (`.onnx`, `.trt`) is intentional — random `.txt` / `.md` files don't accidentally satisfy the check.
**Related:** E.ENV.B08.

---

### E.ENV.B10 — `preflight.models.notFound`
**Trigger:** Selected `model` filename isn't in `base["models_folder_files"]`.
**Where:** `preflight.py:collect_issues` line 142-143.
**What it means (plain English):** The user selected (or had previously selected) a model file that no longer exists in the folder — renamed, deleted, or different casing.
**Symptoms:** `danger` banner "model {name} not found"; the `model=` fmt placeholder shows the missing filename.
**Root cause(s):**
- User deleted/renamed a model.
- Settings persisted from a previous version that shipped a different model.
- Casing mismatch on case-insensitive filesystems re-exported from case-sensitive ones.
**How to fix:**
1. Pick a different model from the dropdown (the UI should auto-suggest).
2. Restore the missing file.
3. Server-side: `preflight.invalidate_cache()` after the user re-selects.
**Prevention / hardening:** The frontend is expected to clear the persisted selection when this code fires.
**Related:** E.ENV.B08, E.ENV.B09; also E.ENV.SVR (server arg sanitization line 249 — model path traversal scrubbed).

---

### E.ENV.B11 — `preflight.trt.needsTorch`
**Trigger:** Selected model ends in `.trt` AND `torch` is not installed.
**Where:** `preflight.py:collect_issues` line 146-147.
**What it means (plain English):** The TensorRT inference path in this codebase reuses PyTorch tensor allocators / streams. Even though TensorRT itself doesn't require torch, our wrapper does.
**Symptoms:** `danger` banner "TensorRT model needs PyTorch"; runtime `ImportError: torch` from the TRT loader.
**Root cause(s):** User installed `tensorrt` but not `torch` — assumed they were independent.
**How to fix:**
1. Install the CUDA build of PyTorch from pytorch.org (see `requirements.txt:36-38` warning — don't `pip install torch` blindly, you'll get the CPU wheel which then fails E.ENV.B14).
2. Or switch to the `.onnx` version of the model.
**Prevention / hardening:** All three TRT requirements (B11/B12/B13) fire together so the user sees the full picture.
**Related:** E.ENV.B12, E.ENV.B13, E.ENV.B14.

---

### E.ENV.B12 — `preflight.trt.needsTensorrt`
**Trigger:** Selected model ends in `.trt` AND `tensorrt` is not installed.
**Where:** `preflight.py:collect_issues` line 148-149.
**What it means (plain English):** Can't run a TensorRT engine without the TensorRT Python bindings.
**Symptoms:** `danger` banner "TensorRT missing"; engine load fails.
**Root cause(s):**
- TensorRT is hard to install: requires NVIDIA developer account, version-matched to CUDA toolkit.
- `requirements.txt:41` deliberately leaves `tensorrt` commented out.
**How to fix:**
1. Download TensorRT matching your CUDA toolkit from NVIDIA.
2. `pip install tensorrt-<ver>-cp<py>-none-win_amd64.whl`.
3. Make sure DLLs are on PATH.
**Prevention / hardening:** None — this stack is genuinely hard to package; the banner is the best we can do.
**Related:** E.ENV.B11, E.ENV.B13.

---

### E.ENV.B13 — `preflight.trt.needsPycuda`
**Trigger:** Selected model ends in `.trt` AND `pycuda` is not installed.
**Where:** `preflight.py:collect_issues` line 150-151.
**What it means (plain English):** Our TRT loader uses `pycuda.driver` for memory allocation and stream management.
**Symptoms:** `danger` banner "pycuda missing"; runtime `ImportError: pycuda.driver`.
**Root cause(s):** pycuda has C++ build steps; on Windows requires Visual C++ build tools. Many users skip it because it's not in `requirements.txt`.
**How to fix:**
1. Install Visual C++ Build Tools (Windows) or `nvidia-cuda-toolkit` (Linux).
2. `pip install pycuda` — verify it picks up CUDA via `CUDA_PATH`.
**Prevention / hardening:** Could be replaced with `cuda-python` (NVIDIA's first-party binding) for easier installs.
**Related:** E.ENV.B11, E.ENV.B12, E.ENV.004.

---

### E.ENV.B14 — `preflight.gpu.needsTorch`
**Trigger:** Device set to "GPU" AND `torch` is not installed.
**Where:** `preflight.py:collect_issues` line 159-160.
**What it means (plain English):** Even when running ONNX Runtime on GPU, the codebase uses `torch.cuda` calls for stream synchronization / debug display. Without torch the GPU device path errors.
**Symptoms:** `warn` banner "PyTorch needed for GPU"; some GPU paths degrade to CPU.
**Root cause(s):** User installed `onnxruntime-gpu` and assumed torch wasn't needed.
**How to fix:** Install CUDA-built torch from pytorch.org.
**Prevention / hardening:** `warn` rather than `danger` — inference may still run, but with reduced functionality.
**Related:** E.ENV.B15, E.ENV.B11.

---

### E.ENV.B15 — `preflight.gpu.torchNoCuda`
**Trigger:** Device "GPU" AND torch installed AND `torch.cuda.is_available()` returns `False`.
**Where:** `preflight.py:collect_issues` line 161-163; populated by `_collect_base()` line 76-79.
**What it means (plain English):** User has the **CPU-only** PyTorch wheel — the one `pip install torch` defaults to. CUDA isn't compiled in. GPU acceleration via torch is impossible until they reinstall the CUDA wheel.
**Symptoms:** `warn` banner "PyTorch built without CUDA"; Info page shows `torch.cuda_built: false`.
**Root cause(s):** The PyTorch index URL was not specified during install; `pip install torch` from PyPI gives the CPU-only build.
**How to fix:**
1. Uninstall: `pip uninstall torch torchvision torchaudio`.
2. Install with CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu121` (match your CUDA toolkit).
3. Verify: `python -c "import torch; print(torch.version.cuda)"` should print "12.1" not None.
**Prevention / hardening:** `requirements.txt:36-38` warns explicitly. The check distinguishes "torch missing" (B14) from "torch installed but wrong build" (B15) so the message is actionable.
**Related:** E.ENV.B14, E.ENV.011.

---

### E.ENV.B16 — `preflight.gpu.needsOrtGpu`
**Trigger:** Device "GPU" AND `onnxruntime` (CPU build) is installed AND `onnxruntime-gpu` is not.
**Where:** `preflight.py:collect_issues` line 165-168.
**What it means (plain English):** User picked GPU but the installed ONNX Runtime is the CPU-only build. The GPU execution providers (CUDA/DirectML/TensorRT) aren't available.
**Symptoms:** `warn` banner "Need onnxruntime-gpu"; ORT silently falls back to CPU; inference is slow.
**Root cause(s):** Followed the "CPU baseline" path in `requirements.txt:30` instead of the GPU path on line 31.
**How to fix:**
1. `pip uninstall onnxruntime`.
2. `pip install onnxruntime-gpu`.
3. Restart server.
**Prevention / hardening:** The check looks at distribution metadata, not provider list, so it works even if the GPU install is broken at the DLL level.
**Related:** E.ENV.B07, E.ENV.B17.

---

### E.ENV.B17 — `preflight.gpu.noProvider`
**Trigger:** Device "GPU" AND `ort.get_available_providers()` does not include any of `CUDAExecutionProvider`, `DmlExecutionProvider`, `TensorrtExecutionProvider` AND ORT is importable AND it's not the "CPU-only build" case (B16).
**Where:** `preflight.py:collect_issues` line 165-173, the `else: issues.append(_issue("preflight.gpu.noProvider", ...))` branch.
**What it means (plain English):** ORT-GPU is installed but at runtime no GPU provider is registered — typically a CUDA DLL load failure (cuDNN missing, version mismatch, no GPU visible).
**Symptoms:** `warn` banner "No GPU provider"; ORT falls back to CPU; `ort.get_available_providers()` returns only `["CPUExecutionProvider"]` despite the GPU build being installed.
**Root cause(s):**
- cuDNN not on PATH.
- CUDA toolkit version doesn't match the ORT-GPU build (e.g. ORT built for CUDA 12, system has CUDA 11).
- GPU disabled in BIOS / driver crashed.
- Running over RDP without `-multimon` may hide the GPU on some Windows setups.
**How to fix:**
1. Run `python -c "import onnxruntime; print(onnxruntime.get_available_providers())"` and check what's *actually* registered.
2. Install matching cuDNN.
3. Verify CUDA toolkit version against ORT requirements page.
**Prevention / hardening:** `_ort_providers()` returns `None` on import failure so we can distinguish "ORT broken" from "ORT loaded but no GPU EP" cleanly.
**Related:** E.ENV.B07, E.ENV.B16, E.ENV.011.

---

### E.ENV.B18 — `preflight.bettercam.missing`
**Trigger:** monitoring_lib set to "bettercam" AND `bettercam` is not installed.
**Where:** `preflight.py:collect_issues` line 176-178.
**What it means (plain English):** User selected the fast-path Windows screen-capture library but it isn't installed. Capture would fall back to MSS (slower).
**Symptoms:** `warn` banner "BetterCam missing"; capture FPS noticeably lower than expected.
**Root cause(s):** `requirements.txt:45` marks bettercam Windows-only via env-marker, but install may have failed (DXGI dependencies on older Windows builds).
**How to fix:**
1. `pip install bettercam`.
2. On Windows 10 <1903, may not work — fall back to MSS.
**Prevention / hardening:** `warn` not `danger` — MSS still works.
**Related:** E.ENV.B19, E.ENV.B04.

---

### E.ENV.B19 — `preflight.bettercam.notWindows`
**Trigger:** monitoring_lib set to "bettercam" AND `bettercam` IS installed AND `sys.platform` is not Windows.
**Where:** `preflight.py:collect_issues` line 179-180.
**What it means (plain English):** BetterCam is fundamentally Windows-only (uses DXGI). If the user manually pip-installed it on Linux/macOS, it'll fail at runtime with platform errors.
**Symptoms:** `info` banner "BetterCam is Windows-only"; capture init fails.
**Root cause(s):** Cross-platform user reading docs that recommend bettercam without noticing the platform marker.
**How to fix:** Switch monitoring_lib to "mss".
**Prevention / hardening:** Severity intentionally `info` — non-blocking, and the user can switch to MSS easily.
**Related:** E.ENV.B18.

---

### E.ENV.B20 — `preflight.nvidiaSmi.missing`
**Trigger:** `nvidia-smi` not on PATH AND (ORT-GPU is installed OR torch.cuda is available).
**Where:** `preflight.py:collect_issues` lines 183-186.
**What it means (plain English):** User has an NVIDIA GPU stack (ORT-GPU or CUDA torch) but `nvidia-smi` isn't reachable. The Performance page GPU monitor will show blank values because we can't query utilization.
**Symptoms:** `info` banner "nvidia-smi missing"; Performance page GPU card empty.
**Root cause(s):**
- Driver-only install (no CUDA toolkit) on a host where the driver `nvidia-smi.exe` isn't in `C:\Windows\System32`.
- `PATH` was modified and the System32 entry was lost.
- Linux: missing `nvidia-utils` package.
**How to fix:**
1. Reinstall NVIDIA driver — `nvidia-smi` ships with it.
2. Add `C:\Program Files\NVIDIA Corporation\NVSMI\` to PATH (older driver layouts).
**Prevention / hardening:** Severity `info` — inference works, only the perf widget is degraded.
**Related:** E.ENV.011, E.ENV.003.

---

### E.ENV.B21 — `preflight.python.versionUntested`
**Trigger:** Python is not 3.10 / 3.11 / 3.12.
**Where:** `preflight.py:collect_issues` line 188-191.
**What it means (plain English):** The dependency matrix is verified on 3.10-3.12. Anything outside that range may have wheel availability issues or unexpected behavior.
**Symptoms:** `info` banner "Python {version} untested"; placeholder `version` is filled by the frontend.
**Root cause(s):** See E.ENV.005 / E.ENV.006.
**How to fix:** Use Python 3.11 (current sweet spot for ORT-GPU + torch + tensorrt wheels).
**Prevention / hardening:** Single check covers both "too old" and "too new" with the same code, distinguishing via the rendered version.
**Related:** E.ENV.005, E.ENV.006.

---

## C. Preflight Infrastructure

### E.ENV.C01 — Cache invalidation between probes
**Trigger:** State changes externally (user installs a package, drops a model file) but `preflight.collect_issues()` returns cached results for up to 30 s.
**Where:** `preflight.py:_get_base()` lines 84-89; `_CACHE_TTL = 30.0`. Manual invalidation via `invalidate_cache()` line 92-94.
**What it means (plain English):** The 30-second cache amortizes ~12 metadata lookups + provider probe + nvidia-smi lookup + models folder scan + torch CUDA init across many `/api/preflight` polls. But it makes the banner "lag" external changes.
**Symptoms:** Banner persists 30s after the user fixed the underlying issue. Or vice versa: banner doesn't appear immediately when something breaks.
**Root cause(s):** Intentional cache by design. The frontend polls `/api/preflight` on every page change, on device-selection change, on model-selection change — without caching, each click would spawn a torch import.
**How to fix / mitigate:**
1. Call `preflight.invalidate_cache()` from any code path that mutates the environment (e.g. an admin endpoint that triggers `pip install`).
2. Wait 30 s.
3. Restart server.
**Prevention / hardening:** Public `invalidate_cache()` exists explicitly so callers (test suite, future "refresh" button) can punch through.
**Related:** E.ENV.009.

---

### E.ENV.C02 — Severity climb (info → warn → danger)
**Trigger:** Multiple issues accumulate; the summary severity is the highest tier present.
**Where:** `preflight.py:build_advice` lines 199-212; sort order via `SEV_ORDER` line 194-195.
**What it means (plain English):** `build_advice()` returns a single `summary` field that the UI uses to color the banner badge. If any issue is `danger`, summary is `danger`; else if any is `warn`, summary is `warn`; else `info`; else `ok`. The issues list itself is also sorted danger→warn→info so the user sees the worst problem at the top.
**Symptoms:** A single `danger` issue (e.g. missing NumPy) overrides ten `info` ones — correct behavior.
**Root cause(s):** N/A — this is the spec.
**How to fix:** N/A.
**Prevention / hardening:** Within a tier, original input order is preserved (Python's sort is stable) so the most-severe-then-most-fundamental ordering is deterministic.
**Related:** E.ENV.C03.

---

### E.ENV.C03 — Banner dismiss state vs new severity climb
**Trigger:** User dismisses a `warn` banner; later, a new `danger`-severity issue arises (e.g. they uninstalled NumPy mid-session).
**Where:** Frontend banner-state machine (not in `preflight.py`); but the *server* contract is in `build_advice()`'s `summary` climb.
**What it means (plain English):** The frontend should re-show the banner whenever the summary severity climbs above the dismissed one. If it just hides "any banner with the same code" forever, a fresh danger gets swallowed by a stale dismiss.
**Symptoms:** User dismissed "BetterCam not Windows" (info), then a danger-tier issue appears, but the banner stays hidden.
**Root cause(s):** Frontend state-machine bug — server is correct.
**How to fix (frontend contract):**
1. Track dismissed-severity per code, not just dismissed.
2. Re-show whenever incoming severity > dismissed severity.
3. Or simpler: re-show whenever the issue *list hash* changes (any add/remove).
**Prevention / hardening:** `summary` field gives the frontend a cheap way to detect climbs without diffing the full list.
**Related:** E.ENV.C02.

---

### E.ENV.C04 — `preflight.collect_issues(None, None, None)` initial probe
**Trigger:** First page load before the user picks device / monitoring_lib / model.
**Where:** `preflight.py:collect_issues` defaults — all three args are `None`.
**What it means (plain English):** With all three None, only environment-wide checks fire: missing core packages, ORT presence, models-folder presence/empty, nvidia-smi presence (when GPU stack is installed), Python version. Device-conditional (B14-B17), model-conditional (B10-B13), and monitoring-lib-conditional (B18-B19) checks are skipped. This is intentional — they'd be noise before the user has chosen anything.
**Symptoms:** First load shows fewer banners than after selecting GPU + a `.trt` model. That's correct behavior, not a bug.
**Root cause(s):** N/A — by design.
**How to fix:** N/A.
**Prevention / hardening:** The handler in `server.py:api_preflight` (lines 238-252) reads `device` / `monitoring_lib` / `model` from query string and passes them through; whitelist-validates `device` to `(None, "CPU", "GPU")` and `monitoring_lib` to `(None, "mss", "bettercam")`; sanitizes `model` against path traversal.
**Related:** All B-section entries that depend on a non-None selection.

---

### E.ENV.C05 — Server-side argument sanitization (`/api/preflight`)
**Trigger:** Frontend (or a malicious client) sends `device=foo`, `monitoring_lib=bar`, or `model=../../etc/passwd`.
**Where:** `server.py:api_preflight` lines 238-252.
**What it means (plain English):** The handler whitelists `device` and `monitoring_lib` to known values (defaulting to None), and strips path-traversal characters from `model`. Even though `model` is only used for a string-equality check inside `preflight`, the defense-in-depth is cheap.
**Symptoms:** Garbage args silently downgrade to None; preflight runs in initial-probe mode.
**Root cause(s):** N/A — defensive coding.
**How to fix:** N/A.
**Prevention / hardening:** The `model` sanitizer at line 249 (`if model and ("\\" in model or "/" in model or model in (".", ".."))`) is conservative; could be tightened to a regex `^[A-Za-z0-9._-]+\.(onnx|trt)$`.
**Related:** E.ENV.B10.

---

### E.ENV.C06 — `_safe_jsonify` exception envelope (server)
**Trigger:** `env_info.collect()` or `preflight.build_advice()` raises despite all internal `_safe` wrapping.
**Where:** `server.py:api_info` and `api_preflight` use `_safe_jsonify(name, fn, ...)`.
**What it means (plain English):** Even if every sub-probe wrapper fails simultaneously, `_safe_jsonify` ensures the HTTP response is a structured JSON error rather than a 500-page-of-HTML. The frontend can render "Info unavailable: <error>" without crashing.
**Symptoms:** `/api/info` returns `{"error": "..."}` with HTTP 200 (or 500 — depends on `_safe_jsonify` impl).
**Root cause(s):** Triple defense (sub-probe `_safe`, `collect()` falls through, `_safe_jsonify` envelopes). Should be unreachable.
**How to fix:** Treat as a bug report — file an issue with the error string.
**Prevention / hardening:** Multi-layer. Each layer logs to stderr so the underlying cause is recoverable from server logs.
**Related:** E.ENV.010.

---

## D. Cross-Cutting Notes

### E.ENV.D01 — Why `importlib.metadata` over `import` in probes
Both `env_info.py` and `preflight.py` use `md.version(dist)` rather than `import dist; check_attr`. That's deliberate:
- Importing `tensorrt` allocates a 50+ MB CUDA context.
- Importing `torch` initializes CUDA on first call (~700 ms cold).
- Importing `bettercam` opens a DXGI duplication interface.

Using metadata avoids all of these — at the cost of false positives for namespace packages and rename mismatches (E.ENV.001, E.ENV.002). The torch/CUDA-availability check is the **only** place where we deliberately import (`env_info.py:_torch_cuda` line 156, `preflight.py:_collect_base` line 76) because `torch.cuda.is_available()` has no metadata equivalent.

### E.ENV.D02 — `creationflags=CREATE_NO_WINDOW`
All `subprocess.check_output` calls in `env_info.py` pass `creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)`. On Windows this prevents a console window from flashing every time the Info page is loaded. The `getattr(... 0)` keeps the code portable to non-Windows where `CREATE_NO_WINDOW` doesn't exist.

### E.ENV.D03 — 2-second subprocess timeouts
Both `nvidia-smi` calls and the `nvcc --version` call have `timeout=2`. `TimeoutExpired` is caught explicitly. This protects against:
- Driver-side hangs (nvidia-smi waiting for a stuck GPU).
- WSL VM startup latency on first call.
- Container-side ipc deadlocks.

The cache TTLs (60 s for env_info, 30 s for preflight) ensure these costs are paid at most once per minute.

---

**End of Chapter 8.**
