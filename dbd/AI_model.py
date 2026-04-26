import glob
import os
import sys

import numpy as np
import onnxruntime as ort

from dbd.utils.monitoring_mss import Monitoring, Monitoring_mss


def _register_cudnn_dll_dirs():
    """Make cuDNN 9 DLLs loadable by onnxruntime-gpu even when their install
    directory isn't on PATH.

    NVIDIA's cuDNN 9 installer drops cudnn64_9.dll under
        C:\\Program Files\\NVIDIA\\CUDNN\\v9.x\\bin\\<cuda-ver>\\x64\\
    and does NOT add that path to the system PATH. Without this, onnxruntime
    silently falls back to CPU at session creation. We probe the standard
    install layouts and register every match via os.add_dll_directory (the
    only reliable mechanism on Python 3.8+ Windows for native DLL discovery).

    Idempotent and Windows-only — no-op elsewhere or if no cuDNN dir exists."""
    if not sys.platform.startswith("win"):
        return
    if not hasattr(os, "add_dll_directory"):
        return

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates = []
    # Layouts under C:\Program Files\NVIDIA\CUDNN\v9.x\bin\
    for cudnn_root in glob.glob(os.path.join(program_files, "NVIDIA", "CUDNN", "v9.*")):
        bin_root = os.path.join(cudnn_root, "bin")
        # Layout A — flat
        if os.path.isfile(os.path.join(bin_root, "cudnn64_9.dll")):
            candidates.append(bin_root)
        # Layouts B/C — bin\<cuda-ver>\[x64\]
        for cuda_sub in glob.glob(os.path.join(bin_root, "*")):
            if os.path.isfile(os.path.join(cuda_sub, "cudnn64_9.dll")):
                candidates.append(cuda_sub)
            x64 = os.path.join(cuda_sub, "x64")
            if os.path.isfile(os.path.join(x64, "cudnn64_9.dll")):
                candidates.append(x64)
    # CUDA toolkit runtime DLLs.
    # Layout differs by CUDA major version:
    #   CUDA 12.x: ...\CUDA\v12.x\bin\cudart64_12.dll
    #   CUDA 13.x: ...\CUDA\v13.x\bin\x64\cudart64_13.dll  (new x64 subfolder!)
    for cuda_root in glob.glob(os.path.join(program_files, "NVIDIA GPU Computing Toolkit", "CUDA", "v1*")):
        for sub in ("bin", os.path.join("bin", "x64")):
            cuda_dir = os.path.join(cuda_root, sub)
            if not os.path.isdir(cuda_dir):
                continue
            if os.path.isfile(os.path.join(cuda_dir, "cudnn64_9.dll")) \
               or os.path.isfile(os.path.join(cuda_dir, "cudart64_12.dll")) \
               or os.path.isfile(os.path.join(cuda_dir, "cudart64_13.dll")):
                candidates.append(cuda_dir)

    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
        # Also prepend to PATH for code that uses default DLL search semantics.
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")

try:
    import torch
    torch_ok = True
    print("Info: torch library found.")
except ImportError:
    torch_ok = False

try:
    import tensorrt as trt
    import pycuda.driver as cuda
    trt_ok = True
    print("Info: tensorRT and pycuda library found.")
except ImportError:
    trt_ok = False


class AI_model:
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    pred_dict = {
        0: {"desc": "None", "hit": False},
        1: {"desc": "repair-heal (great)", "hit": True},
        2: {"desc": "repair-heal (ante-frontier)", "hit": True},
        3: {"desc": "repair-heal (out)", "hit": False},
        4: {"desc": "full white (great)", "hit": True},
        5: {"desc": "full white (out)", "hit": False},
        6: {"desc": "full black (great)", "hit": True},
        7: {"desc": "full black (out)", "hit": False},
        8: {"desc": "wiggle (great)", "hit": True},
        9: {"desc": "wiggle (frontier)", "hit": False},
        10: {"desc": "wiggle (out)", "hit": False}
    }

    def __init__(self, model_path="model.onnx", use_gpu=False, nb_cpu_threads=None, monitoring: Monitoring = None):
        self.model_path = model_path
        self.use_gpu = use_gpu
        self.nb_cpu_threads = nb_cpu_threads

        # Onnx model
        self.ort_session = None
        self.input_name = None

        # TensorRT model
        self.cuda_context = None
        self.engine = None
        self.context = None
        self.stream = None
        self.tensor_shapes = None
        self.bindings = None

        # State guards for cleanup() — make it idempotent so __exit__/explicit
        # cleanup followed by __del__-time GC don't double-free.
        self._cleaned_up = False

        # Load the model FIRST. If load fails, we never started a monitor and
        # therefore can't leak its capture handle. The caller's `except` will
        # see the model error and reset state, while no resources hang.
        if model_path.endswith(".trt"):
            self.load_tensorrt()
        else:
            self.load_onnx()

        # Model loaded successfully — now start the screen monitor.
        self.monitor = monitoring if monitoring else Monitoring_mss(crop_size=224)
        try:
            self.monitor.start()
        except Exception:
            # Roll back the model so the caller doesn't have to know about
            # the partial-init hazard.
            self._cleanup_model_only()
            raise

    def grab_screenshot(self) -> np.ndarray:
        """
        Grab a screenshot from the monitor.
        Returns:
            np.ndarray: The screenshot as a numpy array of shape (224x224x3) in RGB format.
        """

        return self.monitor.get_frame_np()

    def softmax(self, x):
        exp_x = np.exp(x - np.max(x))
        return exp_x / np.sum(exp_x)

    def load_onnx(self):
        sess_options = ort.SessionOptions()

        if not self.use_gpu and self.nb_cpu_threads is not None:
            sess_options.intra_op_num_threads = self.nb_cpu_threads
            sess_options.inter_op_num_threads = self.nb_cpu_threads

        if self.use_gpu:
            # Make cuDNN 9 DLLs discoverable to the CUDAExecutionProvider even
            # when their install dir isn't on PATH (NVIDIA's installer doesn't
            # add it). Must happen before InferenceSession construction.
            _register_cudnn_dll_dirs()

            available_providers = ort.get_available_providers()
            preferred_execution_providers = ['CUDAExecutionProvider', 'DmlExecutionProvider', 'CPUExecutionProvider']
            execution_providers = [p for p in preferred_execution_providers if p in available_providers]
            # Detect the silent CPU fallback (user picked GPU but no GPU EP available).
            # The worker will surface a clearer message via state.error.
            if execution_providers == ["CPUExecutionProvider"]:
                raise RuntimeError(
                    "GPU mode selected but no GPU execution provider is available. "
                    "Install onnxruntime-gpu (CUDA) or onnxruntime-directml (DirectML), "
                    "or switch to CPU mode."
                )
        else:
            execution_providers = ["CPUExecutionProvider"]

        self.ort_session = ort.InferenceSession(
            self.model_path, providers=execution_providers, sess_options=sess_options
        )

        # `available_providers` only tells us a GPU EP is *advertised*. The
        # session may still fall back to CPU at construction time if the EP's
        # native DLLs (CUDA/cuDNN runtime, DirectML) are missing or mismatched.
        # Surface that as an explicit error instead of silently inferring on CPU.
        if self.use_gpu:
            attached = self.ort_session.get_providers()
            if all(p == "CPUExecutionProvider" for p in attached):
                raise RuntimeError(
                    "GPU mode selected, but ONNX Runtime fell back to CPU at session "
                    "creation. The GPU execution provider is advertised but its native "
                    "runtime DLLs are missing or mismatched. Common causes:\n"
                    "  • CUDA 12.x runtime + cuDNN 9.x not installed (CUDAExecutionProvider).\n"
                    "  • DirectML runtime missing (DmlExecutionProvider).\n"
                    "Install the matching runtime, or switch to CPU mode."
                )

        self.input_name = self.ort_session.get_inputs()[0].name

    def load_tensorrt(self):
        # https://github.com/NVIDIA/TensorRT/blob/HEAD/quickstart/IntroNotebooks/2.%20Using%20PyTorch%20through%20ONNX.ipynb
        assert self.use_gpu, "TensorRT engine model requires GPU mode. Aborting."
        assert torch_ok, "TensorRT engine model requires torch lib. Aborting."
        assert trt_ok, "TensorRT engine model requires tensorrt lib. Aborting."

        cuda.init()
        device = cuda.Device(0)
        self.cuda_context = device.make_context()

        logger = trt.Logger(trt.Logger.WARNING)
        runtime = trt.Runtime(logger)

        with open(self.model_path, "rb") as f:
            engine_data = f.read()
            self.engine = runtime.deserialize_cuda_engine(engine_data)
            self.context = self.engine.create_execution_context()

        tensor_names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        assert len(tensor_names) == 2

        self.tensor_shapes = [self.engine.get_tensor_shape(n) for n in tensor_names]
        tensor_in = np.empty(self.tensor_shapes[0], dtype=np.float32)
        tensor_out = np.empty(self.tensor_shapes[1], dtype=np.float32)

        p_input = cuda.mem_alloc(1 * tensor_in.nbytes)
        p_output = cuda.mem_alloc(1 * tensor_out.nbytes)

        self.context.set_tensor_address(tensor_names[0], int(p_input))
        self.context.set_tensor_address(tensor_names[1], int(p_output))

        self.bindings = [p_input, p_output]
        self.stream = cuda.Stream()

    def _preprocess_image_for_inference(self, img_np: np.ndarray):
        img = np.asarray(img_np, dtype=np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # (H,W,C) to (C,H,W) i.e. channel first format
        img = (img - self.MEAN[:, None, None]) / self.STD[:, None, None]
        img = np.expand_dims(img, axis=0)
        img = np.ascontiguousarray(img)
        return img

    def predict(self, img_np: np.ndarray):
        img_np = self._preprocess_image_for_inference(img_np)

        if self.engine:
            output = np.empty(self.tensor_shapes[1], dtype=np.float32)
            cuda.memcpy_htod_async(self.bindings[0], img_np, self.stream)  # transfer input data to device
            self.context.execute_async_v3(self.stream.handle)  # execute model
            cuda.memcpy_dtoh_async(output, self.bindings[1], self.stream)  # transfer predictions back
            self.stream.synchronize()  # synchronize threads

        else:
            ort_inputs = {self.input_name: img_np}
            output = self.ort_session.run(None, ort_inputs)

        logits = np.squeeze(output)
        pred = int(np.argmax(logits))
        probs = self.softmax(logits)
        probs_dict = {self.pred_dict[i]["desc"]: probs[i] for i in range(len(probs))}

        return pred, self.pred_dict[pred]["desc"], probs_dict, self.pred_dict[pred]["hit"]

    def check_provider(self):
        return "TensorRT" if self.engine else self.ort_session.get_providers()[0]

    def _cleanup_model_only(self):
        """Tear down the model side without touching `self.monitor`. Used when
        monitor.start() raises after a successful model load."""
        # Free TRT bindings BEFORE dropping the engine/context, otherwise the
        # CUDA driver can complain about freeing memory tied to a torn-down ctx.
        if self.bindings:
            for binding in self.bindings:
                try:
                    binding.free()
                except Exception:
                    pass
            self.bindings = None

        self.stream = None
        self.context = None
        self.engine = None
        self.ort_session = None
        self.input_name = None

        if self.cuda_context is not None:
            try:
                self.cuda_context.pop()
            except Exception:
                pass
            self.cuda_context = None

    def cleanup(self):
        # Idempotent — safe to call from __exit__, the worker's finally, AND
        # __del__ at GC time without double-freeing CUDA resources.
        if self._cleaned_up:
            return
        self._cleaned_up = True

        # Bindings before engine/context (CUDA cleanup ordering).
        if self.bindings:
            for binding in self.bindings:
                try:
                    binding.free()
                except Exception:
                    pass
            self.bindings = None

        self.stream = None
        self.context = None
        self.engine = None
        self.ort_session = None
        self.input_name = None

        monitor = self.monitor
        self.monitor = None
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:
                pass

        if self.cuda_context is not None:
            try:
                self.cuda_context.pop()
                print("Info: Cuda context released")
            except Exception:
                pass
            self.cuda_context = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
