# Chapter 3 — AI Model Loading & Inference Errors

This chapter catalogs every failure mode encountered when loading the skill-check classifier and running inference against it. The model lives in `dbd/AI_model.py` and supports three backends in priority order: **TensorRT** (`.trt` engines, NVIDIA-only, fastest), **ONNX Runtime CUDA / DirectML** (`.onnx` files on GPU), and **ONNX Runtime CPU** (`.onnx` fallback). Because each backend pulls in its own native DLL stack (CUDA, cuDNN, TensorRT, DirectML, MSVC runtimes) and because the constructor partially initializes a CUDA context **and** a screen-monitor before returning, the failure surface is wide. Errors below are grouped by the order they typically appear: import-time, file-load-time, provider-resolution, session/engine creation, inference, and teardown.

---

## E.MDL.001 — ONNX file not found

**Trigger:** `model_path` passed to `AI_model(...)` points to a non-existent `.onnx` file.
**Where:** `AI_model.py:115` (`load_onnx`, inside `ort.InferenceSession(...)`).
**What it means (plain English):** The runtime tried to open the model file from disk and the OS returned ENOENT.
**Symptoms:** `onnxruntime.capi.onnxruntime_pybind11_state.NoSuchFile: [ONNXRuntimeError] : 3 : NO_SUCHFILE : Load model from model.onnx failed: Load model model.onnx failed. File doesn't exist`.
**Root cause(s):** Wrong relative path (cwd differs from project root); user deleted/renamed the model; bundle missing from PyInstaller dist; user typed the path in the UI.
**How to fix:**
1. Confirm the file is actually on disk at the resolved absolute path.
2. Use `os.path.abspath(model_path)` in logs to show what the runtime really tried.
3. Re-download `model.onnx` from the repo release.
**Prevention / hardening:** Pre-validate `os.path.isfile(model_path)` before constructing the session and raise a typed `FileNotFoundError` with the absolute path embedded.
**Related:** E.MDL.002, E.MDL.003.

---

## E.MDL.002 — ONNX file is corrupt or truncated

**Trigger:** Partial download, interrupted git-lfs pull, or disk corruption.
**Where:** `AI_model.py:115` (`load_onnx`).
**What it means (plain English):** The bytes on disk aren't a valid protobuf, so ORT can't parse the graph.
**Symptoms:** `Protobuf parsing failed.` / `ModelProto could not be parsed.` / `Invalid model: failed to load.`
**Root cause(s):** File size != released size; disk write was cut; antivirus quarantined a chunk; user replaced it with an HTML 404 page.
**How to fix:**
1. Check the SHA-256 against the release notes.
2. Re-download in a fresh shell with `curl -L -o model.onnx`.
3. Disable A/V scan on the model directory.
**Prevention / hardening:** Validate file size + hash on first load, cache a `model.onnx.sha256` sidecar.
**Related:** E.MDL.001, E.MDL.003.

---

## E.MDL.003 — ONNX opset newer than installed onnxruntime supports

**Trigger:** Re-exported `model.onnx` with a torch version using opset 18+, paired with onnxruntime <1.16.
**Where:** `AI_model.py:115` (`load_onnx`).
**What it means (plain English):** The graph uses operators the local ORT doesn't know.
**Symptoms:** `[ONNXRuntimeError] : 9 : NOT_IMPLEMENTED : Could not find an implementation for the node ... opset version 18.`
**Root cause(s):** `model_to_onnx.py` (line 19) calls `model.to_onnx(...)` with no `opset_version=` override and inherits torch's default; user's onnxruntime is older than the export target.
**How to fix:**
1. `pip install -U onnxruntime` (or `onnxruntime-gpu`) to the latest stable.
2. Or re-export pinning `opset_version=15` in `model_to_onnx.py`.
**Prevention / hardening:** Pin `opset_version` explicitly during export and document the minimum ORT version in the README.
**Related:** E.MDL.025.

---

## E.MDL.004 — onnxruntime not installed

**Trigger:** Fresh venv, user skipped `pip install -r requirements.txt`.
**Where:** `AI_model.py:2` (`import onnxruntime as ort`).
**What it means (plain English):** Module import fails before the class is even defined.
**Symptoms:** `ModuleNotFoundError: No module named 'onnxruntime'`.
**Root cause(s):** Missing install; activated wrong venv; pip install hit a proxy and silently skipped.
**How to fix:**
1. `pip install onnxruntime` (CPU) or `pip install onnxruntime-gpu` (CUDA).
2. Verify with `python -c "import onnxruntime; print(onnxruntime.__version__)"`.
**Prevention / hardening:** Ship a startup self-check that imports onnxruntime and prints the env_info diagnostic before the worker starts.
**Related:** E.MDL.005.

---

## E.MDL.005 — onnxruntime AND onnxruntime-gpu both installed (DLL conflict)

**Trigger:** User ran `pip install onnxruntime` then later `pip install onnxruntime-gpu` (or vice versa). Both packages ship the same `onnxruntime_pybind11_state.pyd` and the second install only partially overwrites the first.
**Where:** `AI_model.py:2` import OR `AI_model.py:115` session creation.
**What it means (plain English):** Two copies of the runtime fight for DLL load order; whichever wins decides whether CUDA EP exists, and the loser leaves stale .pyd bytes on disk.
**Symptoms:** `ImportError: DLL load failed while importing onnxruntime_pybind11_state`; or `CUDAExecutionProvider` advertised in `get_available_providers()` but session creation crashes with `cudnn64_*.dll not found`; or random `0xC0000005` access violations.
**Root cause(s):** The two wheels conflict. requirements.txt explicitly notes "pick ONE of the two — they share DLLs and conflict" (line 29).
**How to fix:**
1. `pip uninstall -y onnxruntime onnxruntime-gpu onnxruntime-directml`.
2. Reinstall exactly one variant.
3. `pip show onnxruntime` should return one record only.
**Prevention / hardening:** Add a startup guard that scans `pip list` and refuses to start if more than one ORT variant is present.
**Related:** E.MDL.004, E.MDL.006, E.MDL.007.

---

## E.MDL.006 — CUDAExecutionProvider not registered

**Trigger:** `use_gpu=True`, model is `.onnx`, but `ort.get_available_providers()` doesn't list `CUDAExecutionProvider`.
**Where:** `AI_model.py:101–111` (`load_onnx`, provider filter + RuntimeError raise).
**What it means (plain English):** ORT was built without CUDA support, or CUDA libs can't be found at runtime.
**Symptoms:** `RuntimeError: GPU mode selected but no GPU execution provider is available. Install onnxruntime-gpu (CUDA) or onnxruntime-directml (DirectML), or switch to CPU mode.`
**Root cause(s):** Plain `onnxruntime` (CPU wheel) installed instead of `onnxruntime-gpu`; CUDA toolkit/cuDNN missing from PATH; ORT version's CUDA requirement doesn't match installed CUDA.
**How to fix:**
1. `pip install onnxruntime-gpu` (uninstall CPU first).
2. Install matching CUDA Toolkit (see https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#requirements).
3. Add CUDA `bin/` to PATH.
**Prevention / hardening:** This RuntimeError already prevents the silent CPU fallback — keep it.
**Related:** E.MDL.005, E.MDL.011, E.MDL.014.

---

## E.MDL.007 — DmlExecutionProvider not registered

**Trigger:** AMD/Intel GPU user expected DirectML; `onnxruntime-directml` not installed or shadowed by another ORT.
**Where:** `AI_model.py:102–103` (preferred provider list).
**What it means (plain English):** DirectML EP isn't in the available list, so the filter falls back to CPU and the RuntimeError fires.
**Symptoms:** Same RuntimeError as E.MDL.006.
**Root cause(s):** Wrong wheel (CPU or CUDA installed instead of DirectML); Windows version too old for DirectML feature level.
**How to fix:**
1. `pip uninstall onnxruntime onnxruntime-gpu`.
2. `pip install onnxruntime-directml`.
3. Update Windows to a build that ships DirectX 12 + DML.
**Prevention / hardening:** In env_info, surface which ORT variant is installed and which providers it advertises.
**Related:** E.MDL.006.

---

## E.MDL.008 — TensorRT engine load attempted with torch missing

**Trigger:** `model_path.endswith(".trt")` but `torch` import failed at module load.
**Where:** `AI_model.py:124` (`load_tensorrt`, `assert torch_ok`).
**What it means (plain English):** TRT path needs torch for tensor utilities; without it the assert fires.
**Symptoms:** `AssertionError: TensorRT engine model requires torch lib. Aborting.`
**Root cause(s):** `torch` not installed (intentional — requirements.txt comments it out).
**How to fix:**
1. Install the matching CUDA-enabled torch wheel from pytorch.org.
2. Or use the `.onnx` model instead.
**Prevention / hardening:** Document that `.trt` requires torch + tensorrt + pycuda all together.
**Related:** E.MDL.009, E.MDL.010.

---

## E.MDL.009 — TensorRT engine load attempted with tensorrt/pycuda missing

**Trigger:** `model_path.endswith(".trt")` but the `tensorrt`/`pycuda` import block at line 13–19 failed.
**Where:** `AI_model.py:125` (`load_tensorrt`, `assert trt_ok`).
**What it means (plain English):** TRT bindings or pycuda aren't installed.
**Symptoms:** `AssertionError: TensorRT engine model requires tensorrt lib. Aborting.`
**Root cause(s):** User picked a `.trt` file but never `pip install tensorrt pycuda` (these are commented out in requirements).
**How to fix:**
1. Install matching TensorRT wheel (NVIDIA NGC) for your CUDA.
2. `pip install pycuda`.
3. Restart so `trt_ok` re-evaluates.
**Prevention / hardening:** When the file extension is `.trt`, fail early with a checklist message of all three deps.
**Related:** E.MDL.008, E.MDL.012.

---

## E.MDL.010 — TensorRT requested without GPU mode

**Trigger:** User loaded a `.trt` engine but left `use_gpu=False`.
**Where:** `AI_model.py:123` (`load_tensorrt`, `assert self.use_gpu`).
**What it means (plain English):** TRT only runs on the GPU; CPU mode is meaningless here.
**Symptoms:** `AssertionError: TensorRT engine model requires GPU mode. Aborting.`
**Root cause(s):** UI checkbox not flipped; misconfigured launcher script.
**How to fix:**
1. Toggle "Use GPU" in the UI.
2. Or load the `.onnx` model instead.
**Prevention / hardening:** Auto-set `use_gpu=True` when the path ends in `.trt`, then warn.
**Related:** E.MDL.008, E.MDL.009.

---

## E.MDL.011 — torch.cuda.is_available() returns False after install

**Trigger:** User pip-installed plain `torch` (CPU wheel) instead of the CUDA build.
**Where:** Affects `load_onnx` (GPU branch) and `load_tensorrt` indirectly.
**What it means (plain English):** Torch was installed but without CUDA support; `torch_ok=True` (import worked) but actual CUDA calls won't function.
**Symptoms:** ORT-CUDA may still work, but TRT path fails late with cryptic CUDA driver errors; env_info shows "CUDA: not available".
**Root cause(s):** `pip install torch` defaults to CPU wheel on Windows. requirements.txt notes this on line 36–37.
**How to fix:**
1. `pip uninstall torch`.
2. Use the selector at https://pytorch.org/get-started/locally/ to get the CUDA-matched index URL.
3. Re-test with `python -c "import torch; print(torch.cuda.is_available())"`.
**Prevention / hardening:** Surface `torch.cuda.is_available()` in env_info; refuse GPU mode if it's False.
**Related:** E.MDL.014, E.MDL.015.

---

## E.MDL.012 — TensorRT engine version mismatch

**Trigger:** `.trt` file was built with TensorRT 8.x; user's installed TRT is 10.x (or vice versa).
**Where:** `AI_model.py:136` (`runtime.deserialize_cuda_engine`).
**What it means (plain English):** TRT engines are not portable across major versions.
**Symptoms:** `[TRT] [E] 6: The engine plan file is not compatible with this version of TensorRT, expecting library version X.Y.Z got A.B.C, please rebuild.` followed by `deserialize_cuda_engine` returning None and the next line crashing on `create_execution_context()`.
**Root cause(s):** Engine baked on different machine; TensorRT updated since the engine was generated.
**How to fix:**
1. Re-run the ONNX→TRT conversion with the currently installed TRT.
2. Or downgrade TRT to the version that built the engine.
**Prevention / hardening:** Stamp the build TRT version into the engine filename (e.g., `model_trt10.5.trt`).
**Related:** E.MDL.013.

---

## E.MDL.013 — TensorRT engine compute-capability mismatch

**Trigger:** Engine built for sm_80 (Ampere) executed on sm_75 (Turing) GPU, or vice versa.
**Where:** `AI_model.py:137` (`create_execution_context`).
**What it means (plain English):** TRT engines bake in target SM; running on a different architecture fails or silently underperforms.
**Symptoms:** `[TRT] [E] 1: [executionContext.cpp::nvinfer1::rt::ExecutionContext::enqueueV3::...] kernel was not compiled for the current device capability`.
**Root cause(s):** Engine was generated on a different GPU; user upgraded GPU since conversion.
**How to fix:**
1. Re-convert the ONNX on the actual deployment machine.
2. Use a multi-profile TRT build covering all target SMs.
**Prevention / hardening:** Print `cuda.Device(0).compute_capability()` next to the engine SM at load time.
**Related:** E.MDL.012.

---

## E.MDL.014 — Wrong CUDA toolkit vs PyTorch CUDA build

**Trigger:** Torch wheel built for CUDA 12.1, system has CUDA 11.8, or any cross-major mix.
**Where:** Affects all GPU paths; may surface as `load_tensorrt` (line 127, `cuda.init`) or ORT session creation.
**What it means (plain English):** Native CUDA libs torch loads disagree with what NVIDIA driver/runtime exposes.
**Symptoms:** `OSError: [WinError 126] The specified module could not be found. Error loading "...\torch\lib\cudart64_12.dll"`; or `cuda.init()` returning `cudaErrorInsufficientDriver`.
**Root cause(s):** Torch CUDA version > driver-supported CUDA; mismatched CUDA toolkit vs torch wheel.
**How to fix:**
1. Update NVIDIA driver to one supporting torch's CUDA version.
2. Or reinstall torch matching your driver's CUDA cap (`nvidia-smi` shows max).
**Prevention / hardening:** env_info should report `nvidia-smi` driver CUDA + `torch.version.cuda` side by side.
**Related:** E.MDL.011, E.MDL.030.

---

## E.MDL.015 — Silent CPU fallback when GPU was requested

**Trigger:** User checks "Use GPU" but only `CPUExecutionProvider` is actually available.
**Where:** `AI_model.py:106–111` (the explicit RuntimeError raise prevents this).
**What it means (plain English):** Without the guard, ORT would happily filter the provider list down to CPU and run silently — appearing fine but losing 10× perf.
**Symptoms:** Without the guard: low FPS, no error. With the guard (current behavior): `RuntimeError: GPU mode selected but no GPU execution provider is available...`.
**Root cause(s):** Missing GPU EP wheel; missing CUDA libs.
**How to fix:** See E.MDL.006/E.MDL.007.
**Prevention / hardening:** The current code already raises — do not "soften" this to a warning, the perf cliff is too steep.
**Related:** E.MDL.006, E.MDL.007.

---

## E.MDL.016 — CUDA out-of-memory on engine load

**Trigger:** Another process (game, browser GPU accel, second AI app) is holding most of VRAM.
**Where:** `AI_model.py:146–147` (`cuda.mem_alloc` for input/output bindings) or `AI_model.py:137` (engine context creation).
**What it means (plain English):** Driver refuses the allocation request.
**Symptoms:** `pycuda._driver.MemoryError: cuMemAlloc failed: out of memory`; or `[TRT] [E] 1: [defaultAllocator.cpp::allocateAsync::...] cudaMalloc failed`.
**Root cause(s):** DBD itself is using ~2GB VRAM; GPU is already loaded for streaming/encoding.
**How to fix:**
1. Close other GPU-heavy apps before launch.
2. Lower DBD's resolution / texture pool.
3. Switch to ONNX Runtime CPU mode if VRAM-starved.
**Prevention / hardening:** Catch the MemoryError at line 146 and translate to a friendly "VRAM full" message.
**Related:** E.MDL.024.

---

## E.MDL.017 — CUDA OOM during inference

**Trigger:** Long-running session and a memory leak in another GPU app eats VRAM until the next `memcpy_htod_async` fails.
**Where:** `AI_model.py:168–171` (`predict`, async H2D / D2H copies).
**What it means (plain English):** Allocations were fine at startup but a later op runs out of VRAM.
**Symptoms:** `pycuda._driver.LaunchError: cuStreamSynchronize failed: an illegal memory access was encountered`.
**Root cause(s):** Concurrent GPU pressure; driver TDR; faulty VRAM.
**How to fix:**
1. Restart the bot.
2. Check `nvidia-smi` for runaway allocations.
**Prevention / hardening:** Wrap predict() in a try/except CUDA error and force a clean rebuild of the engine on relaunch.
**Related:** E.MDL.016, E.MDL.024.

---

## E.MDL.018 — Model input shape mismatch (ONNX)

**Trigger:** Model expects `(1,3,224,224)` but the screenshot pipeline produces a different shape.
**Where:** `AI_model.py:175` (`ort_session.run`) after `_preprocess_image_for_inference`.
**What it means (plain English):** Tensor shape sent to ORT doesn't match what the graph declared.
**Symptoms:** `[ONNXRuntimeError] : 2 : INVALID_ARGUMENT : Got invalid dimensions for input: input for the following indices: index: 2 Got: 256 Expected: 224`.
**Root cause(s):** `Monitoring_mss(crop_size=224)` (line 70) was overridden to a different size by an injected monitor; user re-exported the model with a different `input_sample` (line 18 of `model_to_onnx.py`).
**How to fix:**
1. Confirm `monitor.crop_size` is 224.
2. Re-export with the correct `input_sample = torch.zeros((1,3,224,224), dtype=torch.float32)`.
**Prevention / hardening:** Read `ort_session.get_inputs()[0].shape` at load time, store it, validate on each predict.
**Related:** E.MDL.019.

---

## E.MDL.019 — TensorRT input/output binding count != 2

**Trigger:** A re-exported engine has more than one input or extra debug outputs.
**Where:** `AI_model.py:140` (`assert len(tensor_names) == 2`).
**What it means (plain English):** Code hardcodes a single-input single-output graph.
**Symptoms:** `AssertionError` with no message at line 140.
**Root cause(s):** ONNX graph mutation added auxiliary outputs; multi-input variant.
**How to fix:**
1. Re-export the model graph with exactly one input and one output.
2. Or generalize the binding code to iterate.
**Prevention / hardening:** Replace bare assert with informative message: `f"expected 2 IO tensors, got {len(tensor_names)}: {tensor_names}"`.
**Related:** E.MDL.018.

---

## E.MDL.020 — Monitor capture handle leak on model-load failure

**Trigger:** Earlier code ordering (now fixed): if `monitor.start()` ran before `load_onnx`/`load_tensorrt` and the model load then failed, the screen capture handle stayed leaked.
**Where:** `AI_model.py:64–77` (constructor — current ordering loads the model **first**, monitor second).
**What it means (plain English):** Resource leak that exhausts mss/bettercam handles after repeated retries.
**Symptoms:** Eventually: `OSError: [WinError 8] Not enough memory resources are available to process this command`.
**Root cause(s):** The fix is encoded in the comment at lines 62–63: "Load the model FIRST. If load fails, we never started a monitor and therefore can't leak its capture handle."
**How to fix:** Don't reorder — keep model load before monitor.start().
**Prevention / hardening:** Constructor comment must stay; consider a unit test that mocks a load failure and asserts no monitor was ever started.
**Related:** E.MDL.021, E.MDL.022.

---

## E.MDL.021 — _cleanup_model_only rollback path

**Trigger:** Model loaded successfully, then `monitor.start()` raised (e.g., bettercam failed to enumerate adapters).
**Where:** `AI_model.py:71–77` (try/except around `monitor.start`).
**What it means (plain English):** Partial init: model + CUDA context exist, monitor doesn't. Without rollback, the caller would have a half-built object whose `__del__` later trips on missing `self.monitor`.
**Symptoms:** Without the rollback: dangling CUDA context, `AttributeError` in `__del__`. With current code: clean rollback, exception propagates to caller.
**Root cause(s):** Anything monitor.start() can raise — display unplugged, permission denied, mss bug, bettercam DXGI failure.
**How to fix:** N/A — the rollback (`self._cleanup_model_only()` + `raise`) is the fix.
**Prevention / hardening:** Keep the try/except narrow; never swallow the original exception.
**Related:** E.MDL.022, E.MDL.026.

---

## E.MDL.022 — TRT bindings cleanup ordering

**Trigger:** Calling `cleanup()` after a TRT load.
**Where:** `AI_model.py:192–211` and `221–249`.
**What it means (plain English):** CUDA driver requires you to free device memory **before** the engine/context that allocated it; freeing in the wrong order can warn or crash.
**Symptoms:** `[TRT] [E] 1: [defaultAllocator.cpp::deallocate::...] memory still in use`; or pycuda's `LogicError: cuMemFree failed: invalid context`.
**Root cause(s):** Bindings (device pointers) were allocated against a CUDA context; freeing the context first orphans them.
**How to fix:** Already correct — both cleanup paths free `self.bindings` first, then null engine/context, then `cuda_context.pop()`.
**Prevention / hardening:** Comments on lines 191 and 220 document this — preserve them on refactor.
**Related:** E.MDL.023, E.MDL.027.

---

## E.MDL.023 — pycuda autoinit / explicit context conflict

**Trigger:** Some other code path imports `pycuda.autoinit` while `AI_model.load_tensorrt` is also doing `cuda.init()` + `make_context()`.
**Where:** `AI_model.py:127–129`.
**What it means (plain English):** Two contexts pushed onto the same thread stack confuse subsequent `cuda.mem_alloc` calls.
**Symptoms:** `LogicError: cuMemcpyHtoDAsync failed: invalid resource handle`; or "context is not current" errors.
**Root cause(s):** `import pycuda.autoinit` accidentally added by a sibling module (e.g., utility script).
**How to fix:**
1. Remove any `pycuda.autoinit` imports from the runtime path.
2. Centralize CUDA context creation in `load_tensorrt`.
**Prevention / hardening:** Grep the codebase for `autoinit` and forbid in CI.
**Related:** E.MDL.022.

---

## E.MDL.024 — OrtAllocator / arena failures

**Trigger:** Insufficient system RAM or VRAM at session-creation time.
**Where:** `AI_model.py:115` (`InferenceSession`).
**What it means (plain English):** ORT couldn't reserve the arena needed for activation buffers.
**Symptoms:** `[ONNXRuntimeError] : 1 : FAIL : ... CUDNN failure 4 : CUDNN_STATUS_INTERNAL_ERROR` (often masks an OOM); `cudaErrorMemoryAllocation`.
**Root cause(s):** Other GPU apps; arena_extend_strategy default too eager.
**How to fix:**
1. Set `sess_options.add_session_config_entry("session.use_env_allocators", "1")`.
2. Configure arena_extend_strategy=kSameAsRequested.
**Prevention / hardening:** Constrain memory via SessionOptions when running alongside the game.
**Related:** E.MDL.016, E.MDL.017.

---

## E.MDL.025 — cuDNN missing or version-incompatible

**Trigger:** `onnxruntime-gpu` requires a specific cuDNN version; user installed CUDA toolkit but skipped cuDNN, or installed a mismatched cuDNN.
**Where:** `AI_model.py:115` (session creation when CUDA EP is selected).
**What it means (plain English):** ORT-CUDA dynamically loads cuDNN at first kernel launch.
**Symptoms:** `Failed to load library libcudnn_cnn_infer.so.8` (Linux) / `cudnn64_8.dll not found` (Windows); session creation succeeds but predict crashes.
**Root cause(s):** cuDNN not on PATH; wrong cuDNN major version.
**How to fix:**
1. Download cuDNN from NVIDIA matching your CUDA + ORT.
2. Copy DLLs into CUDA `bin/` or add a directory to PATH.
**Prevention / hardening:** Document the cuDNN requirement in README near the GPU install instructions.
**Related:** E.MDL.006, E.MDL.014.

---

## E.MDL.026 — `__del__` AttributeError when constructor failed early

**Trigger:** Constructor raises before `self.monitor` is assigned (e.g., `load_onnx` fails on line 115).
**Where:** Implicit `__del__` -> `cleanup()` -> `AI_model.py:235` (`self.monitor`).
**What it means (plain English):** GC calls `__del__` on a half-built object; attributes not yet set raise `AttributeError`.
**Symptoms:** `Exception ignored in: <function AI_model.__del__ at ...>` followed by `AttributeError: 'AI_model' object has no attribute 'monitor'`.
**Root cause(s):** Python GC always calls `__del__` even on partial init.
**How to fix:** All instance attributes touched by `cleanup()` are pre-set to `None` in `__init__` (lines 46–59) **before** `load_onnx`/`load_tensorrt`. Keep that ordering.
**Prevention / hardening:** Use `getattr(self, "monitor", None)` defensively, or guard with `_cleaned_up`.
**Related:** E.MDL.027, E.MDL.028.

---

## E.MDL.027 — `_cleaned_up` idempotency guard

**Trigger:** `cleanup()` called twice — once explicitly, once at GC.
**Where:** `AI_model.py:216–218`.
**What it means (plain English):** Without the guard, double `binding.free()` and double `cuda_context.pop()` would crash.
**Symptoms:** Without guard: `LogicError: cuMemFree failed: invalid value`; or `cuda.LogicError: pop_context failed: invalid context`.
**Root cause(s):** Multiple cleanup paths: `__exit__`, worker `finally`, `__del__`.
**How to fix:** Keep the `if self._cleaned_up: return` early-out at line 216.
**Prevention / hardening:** Cover with a unit test that calls `cleanup()` three times.
**Related:** E.MDL.022, E.MDL.026.

---

## E.MDL.028 — Bare `except Exception: pass` swallows real bugs

**Trigger:** Lines 196, 209, 224, 240, 247 silently swallow exceptions during teardown.
**Where:** `AI_model.py:_cleanup_model_only` and `cleanup`.
**What it means (plain English):** Defensive — but obscures legit logic errors during cleanup.
**Symptoms:** A binding free that should have worked but didn't simply vanishes; later runs see stale state.
**Root cause(s):** Cleanup must not raise (especially during `__del__`).
**How to fix:** Log at debug level inside the except blocks rather than `pass`.
**Prevention / hardening:** `except Exception as e: logger.debug("cleanup non-fatal: %s", e)`.
**Related:** E.MDL.022, E.MDL.027.

---

## E.MDL.029 — ORT session intra/inter op thread count > cpu_count

**Trigger:** User passes `nb_cpu_threads=64` on a 12-core machine.
**Where:** `AI_model.py:96–97` (intra/inter op num_threads setters).
**What it means (plain English):** ORT will spawn that many threads regardless; oversubscription thrashes the OS scheduler.
**Symptoms:** Lower FPS than with default; high context-switch rate; UI lag.
**Root cause(s):** No clamp on user input.
**How to fix:**
1. Clamp at the worker level: `nb_cpu_threads = min(nb_cpu_threads, os.cpu_count())`.
**Prevention / hardening:** UI slider should max out at `os.cpu_count()`.
**Related:** E.MDL.030.

---

## E.MDL.030 — intra_op vs inter_op thread settings conflict

**Trigger:** Setting both equal to `nb_cpu_threads` (current code) overcommits when graph has parallel branches.
**Where:** `AI_model.py:96–97`.
**What it means (plain English):** intra_op = within a single op (matmul parallelism); inter_op = across ops in graph; setting both to N can spawn ~N² threads.
**Symptoms:** CPU pegged at 100%, but ORT throughput plateaus or regresses.
**Root cause(s):** intra/inter both set to user-supplied count.
**How to fix:**
1. Set `inter_op_num_threads=1` (most CNNs are sequential anyway) and only intra_op = N.
2. Or split: intra=N, inter=max(1, N//4).
**Prevention / hardening:** Document the recommended split in env_info.
**Related:** E.MDL.029.

---

## E.MDL.031 — TF32 precision regression

**Trigger:** ORT-CUDA / TRT default to TF32 on Ampere+; subtle accuracy loss vs FP32 reference.
**Where:** Implicit in `AI_model.py:115` (CUDA EP) / `136` (TRT engine).
**What it means (plain English):** TF32 trades 10 bits of mantissa for speed; classifier scores may drift slightly from the FP32 reference.
**Symptoms:** Same input on CPU vs GPU yields different `pred` argmax in borderline cases (great vs ante-frontier).
**Root cause(s):** Tensor Core path on Ampere/Hopper.
**How to fix:** Set CUDA EP option `cudnn_conv_use_max_workspace=1` and disable TF32 via `provider_options`.
**Prevention / hardening:** Validate end-to-end accuracy on GPU after every torch/ORT/TRT upgrade.
**Related:** E.MDL.032.

---

## E.MDL.032 — FP16/INT8 quantized engine accuracy collapse

**Trigger:** TRT engine built with `--fp16` or `--int8` calibration on insufficient calibration data.
**Where:** External to AI_model.py (engine baking) but surfaces in `predict()`.
**What it means (plain English):** Quantization without enough calibration images destroys minority-class accuracy.
**Symptoms:** Wiggle/great categories (rare) misclassified; great-only mode fires on out-of-zone hits.
**Root cause(s):** Aggressive quant without per-channel calibration.
**How to fix:**
1. Rebuild engine FP32 first to confirm it's a quant issue.
2. Re-calibrate with a balanced dataset.
**Prevention / hardening:** Hash-check the calibration set into the engine filename.
**Related:** E.MDL.031.

---

## E.MDL.033 — `softmax` numerical NaN

**Trigger:** Logits contain `+inf` or NaN due to upstream FP issues.
**Where:** `AI_model.py:88–90` (`softmax`).
**What it means (plain English):** `np.exp(inf)` = inf, division produces NaN.
**Symptoms:** `probs_dict` contains NaN values; `argmax` returns 0 or undefined.
**Root cause(s):** Uninitialized output buffer, broken engine, NaN in input image (rare).
**How to fix:**
1. Validate logits with `np.isfinite(logits).all()` before softmax.
2. Replace NaN logits with -inf so softmax returns 0 for that class.
**Prevention / hardening:** Add an assertion in predict() during dev builds.
**Related:** E.MDL.034.

---

## E.MDL.034 — Output buffer not zero'd before TRT inference

**Trigger:** `np.empty(self.tensor_shapes[1])` at line 167 returns uninitialized memory; if `cuda.memcpy_dtoh_async` errors silently, the user sees junk values.
**Where:** `AI_model.py:167`.
**What it means (plain English):** `np.empty` doesn't zero-initialize. If the D2H copy fails without raising, residual heap data becomes "logits".
**Symptoms:** Wildly random predictions on first frames.
**Root cause(s):** Stream sync error swallowed; allocation happened but copy didn't complete.
**How to fix:** Use `np.zeros` and check `cuda.memcpy_dtoh_async` return code.
**Prevention / hardening:** Pre-allocate output buffer once in `load_tensorrt`, reuse + zero each call.
**Related:** E.MDL.017, E.MDL.033.

---

## E.MDL.035 — Stream not synchronized before reading output

**Trigger:** Race condition if `np.argmax(logits)` is called before `stream.synchronize()` returns.
**Where:** `AI_model.py:171–177` (predict).
**What it means (plain English):** Async D2H copy must complete before the CPU reads `output`.
**Symptoms:** Same pattern as E.MDL.034 — junk values on the host buffer.
**Root cause(s):** Forgetting `stream.synchronize()` (current code does call it on line 171 — good).
**How to fix:** Don't remove the `synchronize()` call.
**Prevention / hardening:** Add a comment explaining why sync is required at line 171.
**Related:** E.MDL.034.

---

## E.MDL.036 — `engine` truthiness check ambiguous

**Trigger:** `if self.engine:` (line 166) and `check_provider` at 185 rely on engine being None/truthy.
**Where:** `AI_model.py:166, 185`.
**What it means (plain English):** Some TRT engine objects may have `__bool__` defined unusually; defensive code should compare to None.
**Symptoms:** Edge case: a "deserialization succeeded but returned a stub" engine could evaluate falsy and silently route to ORT path even with a `.trt` file.
**Root cause(s):** Implicit truthiness of TRT bindings.
**How to fix:** Use `if self.engine is not None:` everywhere.
**Prevention / hardening:** Lint rule against truthy checks on third-party C-extension objects.
**Related:** E.MDL.012, E.MDL.013.

---

## E.MDL.037 — Provider order — DirectML preferred over CUDA accidentally

**Trigger:** On a hybrid system with both onnxruntime-gpu and onnxruntime-directml installed (rare but possible), the order in line 102 matters.
**Where:** `AI_model.py:102`.
**What it means (plain English):** First in `preferred_execution_providers` wins. CUDA is currently first (correct on NVIDIA), but on AMD systems CUDA never registers and DirectML is picked — fine.
**Symptoms:** Unexpected EP selected; perf differs from expectations.
**Root cause(s):** Hardcoded preference.
**How to fix:** Detect GPU vendor (via WMI or torch) and reorder dynamically.
**Prevention / hardening:** Log the chosen provider after session creation (already exposed via `check_provider`).
**Related:** E.MDL.006, E.MDL.007.

---

## E.MDL.038 — `monitor.start()` raises with model already loaded — leak path

**Trigger:** Successful TRT load (CUDA context pushed), then bettercam fails.
**Where:** `AI_model.py:71–77`.
**What it means (plain English):** Without `_cleanup_model_only`, the CUDA context stays pushed on the calling thread; subsequent retries see "context already current".
**Symptoms:** Second instantiation crashes immediately with `LogicError: cuCtxPushCurrent failed: invalid resource handle`.
**Root cause(s):** Missed rollback (now fixed by line 76's `_cleanup_model_only`).
**How to fix:** Don't bypass `_cleanup_model_only`.
**Prevention / hardening:** Cover with integration test that fakes a monitor failure.
**Related:** E.MDL.020, E.MDL.021.

---

## E.MDL.039 — `_preprocess_image_for_inference` divides by zero STD

**Trigger:** STD constants are normal — but if someone substitutes a custom mean/std with a 0.0, division explodes.
**Where:** `AI_model.py:158`.
**What it means (plain English):** Defensive concern around the broadcasted divide.
**Symptoms:** `RuntimeWarning: invalid value encountered in divide`; NaN propagates to logits → softmax → output.
**Root cause(s):** User-mutated MEAN/STD arrays.
**How to fix:** Treat MEAN/STD as immutable tuples.
**Prevention / hardening:** Use `np.divide(..., where=STD!=0)` defensively.
**Related:** E.MDL.033.

---

## E.MDL.040 — `np.transpose(img, (2,0,1))` fails on grayscale frames

**Trigger:** Monitor returns `(H,W)` instead of `(H,W,3)` (rare — bettercam returning a single-channel buffer).
**Where:** `AI_model.py:157`.
**What it means (plain English):** Transpose expects 3 axes, gets 2.
**Symptoms:** `ValueError: axes don't match array`.
**Root cause(s):** Capture API returning grayscale or RGBA.
**How to fix:** Validate `img_np.ndim == 3 and img_np.shape[2] == 3` at the top of `_preprocess_image_for_inference`.
**Prevention / hardening:** Strict shape contract on `Monitoring.get_frame_np`.
**Related:** E.MDL.018.

---

## E.MDL.041 — Model export script fails because checkpoint glob is empty

**Trigger:** `model_to_onnx.py` line 12: `glob.glob(...)[0]` raises `IndexError` when no `.ckpt` exists.
**Where:** `model_to_onnx.py:12`.
**What it means (plain English):** Re-export pipeline broken if checkpoints dir is empty.
**Symptoms:** `IndexError: list index out of range`.
**Root cause(s):** Wrong `version_NN` directory; training never produced a checkpoint.
**How to fix:** Check the glob list before indexing; print the search dir.
**Prevention / hardening:** Wrap in `if not files: raise FileNotFoundError(...)`.
**Related:** E.MDL.042.

---

## E.MDL.042 — Model export checkpoint loaded with strict=True misses keys

**Trigger:** Checkpoint trained against an older `Model` class definition.
**Where:** `model_to_onnx.py:14` (`load_from_checkpoint(... strict=True)`).
**What it means (plain English):** Class architecture changed since the checkpoint was saved.
**Symptoms:** `RuntimeError: Error(s) in loading state_dict for Model: Missing key(s) ... Unexpected key(s) ...`.
**Root cause(s):** Network refactor; renamed layers.
**How to fix:**
1. Retrain.
2. Or load with `strict=False` and verify accuracy.
**Prevention / hardening:** Version-stamp the architecture in checkpoint metadata.
**Related:** E.MDL.041.

---

## E.MDL.043 — `model.to_onnx` exports without dynamic batch dim

**Trigger:** `input_sample = torch.zeros((1,3,224,224))` at line 18 of `model_to_onnx.py` bakes batch=1 into the graph.
**Where:** `model_to_onnx.py:18–19`.
**What it means (plain English):** Engine can't batch multiple frames at once.
**Symptoms:** Trying to feed batch=4 fails: `Got: 4 Expected: 1`.
**Root cause(s):** Missing `dynamic_axes={'input': {0: 'batch'}}` on export.
**How to fix:** Pass dynamic axes if batched inference is desired.
**Prevention / hardening:** Document expected batch size.
**Related:** E.MDL.018.

---

## E.MDL.044 — InferenceSession created but input name not the expected key

**Trigger:** Some exports name the input `input.1` or `onnx::Reshape_0` instead of `input`.
**Where:** `AI_model.py:119` (`get_inputs()[0].name`) — the code reads it dynamically, so this is robust. But hardcoded callers would break.
**What it means (plain English):** `predict()` uses the captured name, so this is mostly fine — covered to flag if anyone refactors.
**Symptoms:** If hardcoded: `[ONNXRuntimeError] : INVALID_ARGUMENT : Invalid input name`.
**Root cause(s):** Export tool naming choice.
**How to fix:** Keep the dynamic `get_inputs()[0].name` capture.
**Prevention / hardening:** Don't hardcode the input name anywhere.
**Related:** E.MDL.018.

---

## E.MDL.045 — onnxruntime-gpu DLL not found at runtime under PyInstaller

**Trigger:** Packaging the app with PyInstaller skips ORT's `_pybind_state` DLLs because they're loaded dynamically.
**Where:** `AI_model.py:2` (import) and `:115` (session).
**What it means (plain English):** PyInstaller's static analysis misses runtime-loaded plugins.
**Symptoms:** `ImportError: DLL load failed` only in the frozen exe; works fine from source.
**Root cause(s):** Missing `--collect-all onnxruntime` during packaging.
**How to fix:** `pyinstaller --collect-all onnxruntime --collect-all onnxruntime-gpu ...`.
**Prevention / hardening:** Lock the build flags into a spec file.
**Related:** E.MDL.004, E.MDL.005.

---

## E.MDL.046 — pycuda DLL conflict with NVIDIA driver TDR

**Trigger:** Long inference run + Windows TDR (Timeout Detection & Recovery) kicks in if a kernel exceeds 2s.
**Where:** `AI_model.py:169` (`execute_async_v3`).
**What it means (plain English):** Windows resets the GPU; CUDA context becomes invalid.
**Symptoms:** `LogicError: cuStreamSynchronize failed: launch timed out`; black flicker; entire bot needs relaunch.
**Root cause(s):** GPU under heavy game load + skill-check inference.
**How to fix:**
1. Increase TDR delay via registry: `HKLM\System\CurrentControlSet\Control\GraphicsDrivers\TdrDelay = 10`.
2. Lower DBD GPU load.
**Prevention / hardening:** Document TDR tuning in the troubleshooting guide.
**Related:** E.MDL.013, E.MDL.017.

---

## E.MDL.047 — `assert torch_ok` failure surfaces as bare AssertionError

**Trigger:** `use_gpu=True`, `.onnx` model, no torch installed.
**Where:** `AI_model.py:100`.
**What it means (plain English):** Without torch, ORT-CUDA EP usually still works — but the code requires torch as a hard prereq for GPU mode.
**Symptoms:** `AssertionError: GPU mode requires torch lib`.
**Root cause(s):** Pure-ORT GPU users hit this even if they don't actually need torch.
**How to fix:**
1. Install torch (CUDA build).
2. Or relax the assert if ORT-CUDA-only operation is desired.
**Prevention / hardening:** Reconsider whether torch is truly required for ORT-CUDA path.
**Related:** E.MDL.008, E.MDL.011.

---

## E.MDL.048 — Multiple `AI_model` instances on different GPUs

**Trigger:** Two workers both call `cuda.Device(0).make_context()`.
**Where:** `AI_model.py:128–129`.
**What it means (plain English):** Hardcoded GPU index 0 means multi-GPU rigs always pin to first device.
**Symptoms:** Second instance fails with VRAM pressure even if GPU 1 is idle.
**Root cause(s):** Hardcoded `cuda.Device(0)`.
**How to fix:** Accept a `device_index` parameter in `AI_model.__init__`.
**Prevention / hardening:** Surface available GPUs in the UI device picker.
**Related:** E.MDL.016.

---

## E.MDL.049 — TRT logger only at WARNING level — silent ERRORS

**Trigger:** `trt.Logger(trt.Logger.WARNING)` (line 131) suppresses INFO; ERRORs still print but go to stdout, not the app log.
**Where:** `AI_model.py:131`.
**What it means (plain English):** TRT diagnostic info is invisible during user troubleshooting.
**Symptoms:** Cryptic load failures with no context.
**Root cause(s):** Logger writes to stdout/stderr only.
**How to fix:**
1. Subclass `trt.ILogger` and route messages into the app's logger.
2. Bump to `trt.Logger.INFO` during diagnostics.
**Prevention / hardening:** Capture TRT logs in the FPS advisor / env_info diagnostics page.
**Related:** E.MDL.012, E.MDL.013.

---

## E.MDL.050 — Re-entrant `cleanup()` race during `__exit__` + worker thread

**Trigger:** Main thread `with AI_model(...) as m: ...` exits while a worker thread is mid-`predict`.
**Where:** `AI_model.py:254–255` (`__exit__`).
**What it means (plain English):** `cleanup()` could null out `self.engine`/`self.context` while another thread is reading them on line 166.
**Symptoms:** `AttributeError: 'NoneType' object has no attribute 'execute_async_v3'`.
**Root cause(s):** No lock around model resources during teardown.
**How to fix:**
1. Add a `threading.RLock` around `predict` and `cleanup`.
2. Or signal the worker to drain before `__exit__` returns.
**Prevention / hardening:** Document `predict` as not thread-safe with concurrent cleanup.
**Related:** E.MDL.027.

---

## E.MDL.051 — `nb_cpu_threads=0` accidentally disables threading

**Trigger:** UI default of 0 passed straight through.
**Where:** `AI_model.py:95–97`.
**What it means (plain English):** ORT interprets 0 as "use all available"; setting it intentionally is fine. But user-visible "0" is confusing.
**Symptoms:** No error, but UI text saying "0 threads" is misleading.
**Root cause(s):** Sentinel value confusion.
**How to fix:** Treat `0` as `None` in the UI layer; show "auto" instead.
**Prevention / hardening:** Validate `nb_cpu_threads >= 1` or pass None.
**Related:** E.MDL.029.

---

## E.MDL.052 — `assert len(tensor_names) == 2` discards multi-output debug builds

**Trigger:** Debug TRT engine emits both class logits and an intermediate feature map.
**Where:** `AI_model.py:140`.
**What it means (plain English):** Hardcoded 2-IO contract.
**Symptoms:** AssertionError without message.
**Root cause(s):** Engineering choice.
**How to fix:** Allow `>=2` and pick the output by name suffix.
**Prevention / hardening:** Promote bare assert to a real exception with message.
**Related:** E.MDL.019.

---

## E.MDL.053 — DirectML provider succeeds but wrong adapter selected

**Trigger:** Multi-GPU machine, DirectML picks the iGPU instead of the discrete card.
**Where:** `AI_model.py:115` (DirectML EP, no provider_options).
**What it means (plain English):** DML adapter index defaults to 0 (iGPU on most laptops).
**Symptoms:** Inference works but at iGPU speed; FPS advisor flags it.
**Root cause(s):** No `provider_options=[{'device_id': N}]` passed.
**How to fix:** Enumerate adapters and pick the discrete one explicitly.
**Prevention / hardening:** UI device selector that maps to DML adapter index.
**Related:** E.MDL.007, E.MDL.037.

---

## E.MDL.054 — Engine load happens on import but predict runs on a different thread (CUDA context not pushed)

**Trigger:** `AI_model` instantiated on thread A, `predict` called from thread B.
**Where:** `AI_model.py:163` (predict) — CUDA contexts are thread-local.
**What it means (plain English):** Pycuda contexts must be `push`'d on the calling thread before any cuda call.
**Symptoms:** `LogicError: explicit_context_dependent failed: invalid device context - no currently active context?`.
**Root cause(s):** Worker pool design moves predict to a different thread.
**How to fix:**
1. Use `cuda_context.push()` at predict entry, `pop()` at exit.
2. Or pin all model ops to the same thread.
**Prevention / hardening:** Document thread affinity loudly.
**Related:** E.MDL.022, E.MDL.050.

---

## E.MDL.055 — Engine deserialize returns None silently

**Trigger:** `runtime.deserialize_cuda_engine(engine_data)` (line 136) returns None on failure rather than raising.
**Where:** `AI_model.py:136–137`.
**What it means (plain English):** TRT API quirk: silent failure.
**Symptoms:** Next line `self.engine.create_execution_context()` -> `AttributeError: 'NoneType' object has no attribute 'create_execution_context'`.
**Root cause(s):** Any deserialization failure (version mismatch, corrupt file, SM mismatch).
**How to fix:** Add `assert self.engine is not None, "TRT engine deserialize returned None — check version/SM/corruption"`.
**Prevention / hardening:** Inspect the TRT logger for the actual reason.
**Related:** E.MDL.012, E.MDL.013, E.MDL.049.
