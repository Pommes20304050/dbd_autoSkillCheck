import threading
import time
from collections import deque


class AppState:
    """Thread-safe shared state between the inference worker and Flask routes."""

    def __init__(self):
        self._lock = threading.Lock()

        self.status = "idle"  # idle | starting | running | error | stopping
        self.error = None
        self.provider = None  # CUDA / DirectML / TensorRT / CPU

        self.tool_fps = 0.0
        self.fps_history = deque(maxlen=60)  # last 60 samples for the chart

        self.hit_count = 0
        self.hit_log = deque(maxlen=120)  # timestamps for hits/min calc

        self.last_hit_desc = None
        self.last_hit_probs = None  # dict[label] -> prob
        self.last_hit_frame_jpeg = None  # bytes
        self.last_hit_at = None

        self.live_frame_jpeg = None  # bytes — preview of what the model sees right now

    def snapshot(self):
        with self._lock:
            now = time.time()
            recent_hits = [t for t in self.hit_log if now - t <= 60]
            history = list(self.fps_history)
            return {
                "status": self.status,
                "error": self.error,
                "provider": self.provider,
                "tool_fps": self.tool_fps,
                "tool_fps_avg": self._avg_locked(history),
                "tool_fps_samples": len(history),
                "fps_history": history,
                "hit_count": self.hit_count,
                "hits_per_minute": len(recent_hits),
                "last_hit_desc": self.last_hit_desc,
                "last_hit_probs": self.last_hit_probs,
                "last_hit_at": self.last_hit_at,
            }

    @staticmethod
    def _avg_locked(history, window=10, min_samples=5):
        if len(history) < min_samples:
            return None
        sample = history[-window:]
        return round(sum(sample) / len(sample), 1)

    def get_fps_average(self, window=10, min_samples=5):
        with self._lock:
            history = list(self.fps_history)
        return self._avg_locked(history, window=window, min_samples=min_samples)

    def set_status(self, status, error=None, provider=None):
        with self._lock:
            self.status = status
            if error is not None:
                self.error = error
            if provider is not None:
                self.provider = provider
            if status == "idle":
                self.error = None

    def reset_for_run(self):
        with self._lock:
            self.tool_fps = 0.0
            self.fps_history.clear()
            self.hit_count = 0
            self.hit_log.clear()
            self.last_hit_desc = None
            self.last_hit_probs = None
            self.last_hit_frame_jpeg = None
            self.last_hit_at = None
            self.live_frame_jpeg = None
            self.error = None

    def update_fps(self, fps):
        with self._lock:
            self.tool_fps = fps
            self.fps_history.append(fps)

    def update_live_frame(self, jpeg_bytes):
        with self._lock:
            self.live_frame_jpeg = jpeg_bytes

    def record_hit(self, jpeg_bytes, desc, probs):
        with self._lock:
            self.hit_count += 1
            self.hit_log.append(time.time())
            self.last_hit_desc = desc
            self.last_hit_probs = probs
            self.last_hit_frame_jpeg = jpeg_bytes
            self.last_hit_at = time.time()
