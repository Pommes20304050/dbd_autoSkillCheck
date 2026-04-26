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
            now = time.monotonic()
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
                "last_hit_probs": dict(self.last_hit_probs) if self.last_hit_probs else None,
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

    def get_live_frame(self):
        with self._lock:
            return self.live_frame_jpeg

    def get_last_hit_frame(self):
        with self._lock:
            return self.last_hit_frame_jpeg

    def set_status(self, status, error=None, provider=None):
        with self._lock:
            self.status = status
            if error is not None:
                self.error = error
            if provider is not None:
                self.provider = provider
            if status == "idle":
                # Clear error only on explicit idle. Worker-end paths use
                # set_idle_unless_error() to preserve a final error message.
                self.error = None

    def set_idle_unless_error(self):
        """Used by the worker's finally — if a runtime exception already
        flipped us to "error", keep that state (and the message) so the UI
        can show what went wrong. Otherwise return cleanly to idle.
        Also resets the live-FPS reading AND the rolling FPS history so a
        stopped run doesn't leave a stale FPS number on the sidebar / mini-
        stats (Avg FPS reads from fps_history)."""
        with self._lock:
            self.tool_fps = 0.0
            self.fps_history.clear()
            if self.status == "error":
                return
            self.status = "idle"
            self.error = None

    def reset_for_run(self):
        with self._lock:
            self.status = "idle"
            self.provider = None
            self.error = None
            self.tool_fps = 0.0
            self.fps_history.clear()
            self.hit_count = 0
            self.hit_log.clear()
            self.last_hit_desc = None
            self.last_hit_probs = None
            self.last_hit_frame_jpeg = None
            self.last_hit_at = None
            self.live_frame_jpeg = None

    def update_fps(self, fps):
        with self._lock:
            self.tool_fps = fps
            self.fps_history.append(fps)

    def update_live_frame(self, jpeg_bytes):
        if not jpeg_bytes:
            return
        with self._lock:
            self.live_frame_jpeg = jpeg_bytes

    def record_hit(self, jpeg_bytes, desc, probs):
        now = time.monotonic()
        with self._lock:
            self.hit_count += 1
            self.hit_log.append(now)
            self.last_hit_desc = desc
            self.last_hit_probs = probs
            if jpeg_bytes:
                self.last_hit_frame_jpeg = jpeg_bytes
            self.last_hit_at = time.time()  # wall-clock for UI display only
