import threading
from time import time, sleep

import cv2

from dbd.AI_model import AI_model
from dbd.utils.directkeys import PressKey, ReleaseKey, SPACE
from dbd.utils.monitoring_mss import Monitoring_mss

try:
    from dbd.utils.monitoring_bettercam import Monitoring_bettercam
    BETTERCAM_OK = True
except ImportError:
    BETTERCAM_OK = False


def encode_jpeg(frame_rgb, quality=80):
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else None


def make_monitoring(monitoring_lib, monitor_id):
    if monitoring_lib == "bettercam" and BETTERCAM_OK:
        return Monitoring_bettercam(monitor_id=monitor_id, crop_size=224, target_fps=240)
    return Monitoring_mss(monitor_id=monitor_id, crop_size=224)


class InferenceWorker(threading.Thread):
    """Background thread running the same loop as the original Gradio app,
    but writing into AppState instead of yielding."""

    LIVE_FRAME_EVERY_N = 8  # encode + publish a live preview every Nth frame to save CPU

    def __init__(self, state, config):
        super().__init__(daemon=True)
        self.state = state
        self.config = config
        self._stop_evt = threading.Event()
        self.ai_model = None

    def request_stop(self):
        self._stop_evt.set()

    def run(self):
        self.state.set_status("starting")

        try:
            monitoring = make_monitoring(self.config["monitoring_lib"], self.config["monitor_id"])
        except Exception as e:
            hint = "Pick a different monitor or screen library (mss is always available)."
            self.state.set_status("error", error=f"Monitor init failed: {e}. {hint}")
            return

        use_gpu = (self.config["device"] == "GPU")
        try:
            self.ai_model = AI_model(
                model_path=self.config["model_path"],
                use_gpu=use_gpu,
                nb_cpu_threads=self.config["nb_cpu_threads"],
                monitoring=monitoring,
            )
        except AssertionError as e:
            hint = "Install PyTorch with CUDA (or switch to CPU mode)."
            self.state.set_status("error", error=f"GPU unavailable: {e}. {hint}")
            return
        except FileNotFoundError as e:
            self.state.set_status("error", error=f"Model file not found: {e}.")
            return
        except Exception as e:
            hint = "Check that the model file is a valid ONNX/TensorRT engine and matches your runtime."
            self.state.set_status("error", error=f"Model load failed: {e}. {hint}")
            return

        self.state.set_status("running", provider=self.ai_model.check_provider())

        hit_ante = self.config["hit_ante"]
        t0 = time()
        nb_frames = 0
        frame_idx = 0

        try:
            while not self._stop_evt.is_set():
                frame_np = self.ai_model.grab_screenshot()
                nb_frames += 1
                frame_idx += 1

                if frame_idx % self.LIVE_FRAME_EVERY_N == 0:
                    jpeg = encode_jpeg(frame_np)
                    if jpeg is not None:
                        self.state.update_live_frame(jpeg)

                pred, desc, probs, should_hit = self.ai_model.predict(frame_np)

                if should_hit:
                    if pred == 2 and hit_ante > 0:
                        sleep(hit_ante * 0.001)

                    PressKey(SPACE)
                    sleep(0.005)
                    ReleaseKey(SPACE)

                    jpeg = encode_jpeg(frame_np)
                    probs_serializable = {k: float(v) for k, v in probs.items()}
                    self.state.record_hit(jpeg, desc, probs_serializable)

                    sleep(0.5)
                    t0 = time()
                    nb_frames = 0
                    continue

                t_diff = time() - t0
                if t_diff > 1.0:
                    fps = round(nb_frames / t_diff, 1)
                    self.state.update_fps(fps)
                    t0 = time()
                    nb_frames = 0

        except Exception as e:
            self.state.set_status("error", error=f"Runtime error: {e}")
        finally:
            try:
                if self.ai_model is not None:
                    self.ai_model.cleanup()
            except Exception:
                pass
            self.ai_model = None
            self.state.set_status("idle")
