import logging
import threading
from time import time, sleep

import cv2

from dbd.AI_model import AI_model
from dbd.utils import directkeys
from dbd.utils.directkeys import PressKey, ReleaseKey, SPACE
from dbd.utils.monitoring_mss import Monitoring_mss
from dbd.web import system_info


log = logging.getLogger(__name__)


def encode_jpeg(frame_rgb, quality=80):
    if frame_rgb is None:
        return None
    try:
        bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None
    except cv2.error:
        return None


def make_monitoring(monitor_id):
    return Monitoring_mss(monitor_id=monitor_id, crop_size=224)


class InferenceWorker(threading.Thread):
    """Background thread running the same loop as the original Gradio app,
    but writing into AppState instead of yielding."""

    LIVE_FRAME_EVERY_N = 8  # encode + publish a live preview every Nth frame to save CPU
    MAX_CONSECUTIVE_FRAME_ERRORS = 30  # bail out if every iteration is failing

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

        # Pin process to selected affinity mask BEFORE loading the ONNX session,
        # so all worker threads inherit the affinity and stay off E-cores.
        # On 14900K this is the difference between 980 fps (P-only) and 525 fps (all cores).
        affinity_mask = self.config.get("cpu_affinity_mask", 0)
        affinity_applied = False
        if affinity_mask and self.config.get("device") == "CPU":
            affinity_applied = system_info.set_process_affinity(affinity_mask)

        try:
            try:
                monitoring = make_monitoring(self.config["monitor_id"])
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
            except RuntimeError as e:
                # Includes our explicit "no GPU EP" runtime error from AI_model.
                self.state.set_status("error", error=str(e))
                return
            except Exception as e:
                log.exception("Model load failed")
                hint = "Check that the model file is a valid ONNX/TensorRT engine and matches your runtime."
                self.state.set_status("error", error=f"Model load failed: {e}. {hint}")
                return

            self.state.set_status("running", provider=self.ai_model.check_provider())

            if not directkeys.KEY_SENDER_AVAILABLE:
                # Surface the no-op fallback as a non-fatal hint via state.error,
                # but keep status=running so the UI still shows live frames.
                self.state.set_status(
                    "running",
                    error="Key sender unavailable on this platform — hits will not be triggered. "
                          "Install pynput on Linux/macOS.",
                )

            self._run_loop()

        except Exception as e:
            # Outer safety net — only reachable if the inner blocks themselves
            # raised (e.g. set_status raised). Log + record so the UI shows it.
            log.exception("Unhandled worker error")
            self.state.set_status("error", error=f"Unhandled worker error: {e}")
        finally:
            try:
                if self.ai_model is not None:
                    self.ai_model.cleanup()
            except Exception:
                log.exception("Cleanup failed")
            self.ai_model = None

            # Restore affinity to all logical CPUs only if we actually applied it.
            if affinity_applied:
                try:
                    system_info.set_process_affinity((1 << (os.cpu_count() or 32)) - 1)
                except Exception:
                    pass

            # Preserve state.error if a runtime crash already set it; otherwise idle.
            self.state.set_idle_unless_error()

    def _run_loop(self):
        hit_ante = self.config["hit_ante"]
        t0 = time()
        nb_frames = 0
        frame_idx = 0
        consecutive_frame_errors = 0

        while not self._stop_evt.is_set():
            try:
                frame_np = self.ai_model.grab_screenshot()
            except Exception as e:
                consecutive_frame_errors += 1
                if consecutive_frame_errors >= self.MAX_CONSECUTIVE_FRAME_ERRORS:
                    self.state.set_status(
                        "error",
                        error=f"Screen capture failed repeatedly: {e}. "
                              f"Try a different monitor or screen library."
                    )
                    return
                # Brief backoff so we don't spin on a broken capture.
                if self._stop_evt.wait(0.05):
                    return
                continue

            if frame_np is None:
                # MSS may return None on transient capture failure (e.g. minimized window).
                consecutive_frame_errors += 1
                if consecutive_frame_errors >= self.MAX_CONSECUTIVE_FRAME_ERRORS:
                    self.state.set_status(
                        "error",
                        error="Screen capture is returning empty frames — game window may be minimized."
                    )
                    return
                if self._stop_evt.wait(0.02):
                    return
                continue

            # Successful capture → reset the error streak.
            consecutive_frame_errors = 0
            nb_frames += 1
            frame_idx += 1

            try:
                if frame_idx % self.LIVE_FRAME_EVERY_N == 0:
                    self.state.update_live_frame(encode_jpeg(frame_np))

                pred, desc, probs, should_hit = self.ai_model.predict(frame_np)
            except Exception as e:
                # One bad inference call shouldn't kill the worker — log it,
                # drop this frame, continue. If predict() is permanently broken
                # the next iterations will keep failing and the user will notice
                # the FPS counter stuck at 0.
                log.exception("Predict step failed")
                _ = e
                if self._stop_evt.wait(0.02):
                    return
                continue

            if should_hit:
                try:
                    if pred == 2 and hit_ante > 0:
                        # Use the stop-event as an interruptible sleep so a stop
                        # request during the ante delay doesn't have to wait it out.
                        if self._stop_evt.wait(hit_ante * 0.001):
                            return

                    PressKey(SPACE)
                    sleep(0.005)
                    ReleaseKey(SPACE)

                    probs_serializable = {k: float(v) for k, v in probs.items()}
                    self.state.record_hit(encode_jpeg(frame_np), desc, probs_serializable)
                except Exception:
                    log.exception("Hit handling failed")
                    # Fall through — don't kill the worker over a SendInput hiccup.

                # Interruptible cooldown so stop responds within ~50ms instead
                # of the full half-second.
                if self._stop_evt.wait(0.5):
                    return
                t0 = time()
                nb_frames = 0
                continue

            t_diff = time() - t0
            if t_diff > 1.0:
                fps = round(nb_frames / t_diff, 1)
                self.state.update_fps(fps)
                t0 = time()
                nb_frames = 0
