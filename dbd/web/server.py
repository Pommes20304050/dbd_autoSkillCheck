import logging
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, abort
from io import BytesIO

import cv2
import numpy as np

from dbd.utils.monitoring_mss import Monitoring_mss
from dbd.web.state import AppState
from dbd.web.inference_worker import InferenceWorker, make_monitoring
from dbd.web import fps_advisor, system_info, perf_monitor, env_info, preflight


log = logging.getLogger(__name__)

MODELS_FOLDER = "models"
DEVICES = ["CPU", "GPU"]


def _list_models():
    if not os.path.isdir(MODELS_FOLDER):
        return []
    return sorted(
        f for f in os.listdir(MODELS_FOLDER)
        if f.lower().endswith((".onnx", ".trt"))
    )


def _list_monitors():
    return [{"label": label, "id": mid} for label, mid in Monitoring_mss.get_monitors_info()]


def _resolve_safe_model_path(model_name):
    """Validate that `model_name` is a plain filename within MODELS_FOLDER.
    Returns the absolute path on success, or None if anything looks fishy
    (path separators, parent traversal, absolute path, missing file)."""
    if not model_name or not isinstance(model_name, str):
        return None
    # Reject any path syntax — only bare filenames allowed.
    if model_name in (".", "..") or "/" in model_name or "\\" in model_name:
        return None
    if os.path.isabs(model_name):
        return None
    if model_name not in _list_models():
        return None
    return os.path.join(MODELS_FOLDER, model_name)


def _grab_preview_jpeg(monitor_id):
    """One-shot preview frame for the monitor selector (larger crop than inference)."""
    crop_size = 520
    with Monitoring_mss(monitor_id=monitor_id, crop_size=crop_size) as mon:
        frame = mon.get_frame_np()

    if frame is None:
        return None
    bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None


def create_app():
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    state = AppState()
    worker_holder = {"worker": None}
    # Single lock guards start/stop transitions so two parallel POSTs can't
    # both pass the status gate and spawn two workers (one would be leaked).
    worker_lock = threading.Lock()

    def _safe_jsonify(label, fn, *args, **kwargs):
        """Run `fn` and return its result as JSON. On unexpected exception,
        return a 503 with a minimal shape rather than a 500 with stack trace —
        the frontend polls these endpoints, so a noisy 500 spams the toast."""
        try:
            return jsonify(fn(*args, **kwargs))
        except Exception as e:
            log.exception("%s endpoint failed", label)
            return jsonify({"error": f"{label} probe failed: {e}", "available": False}), 503

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/init")
    def api_init():
        try:
            models = _list_models()

            cpu = system_info.detect_cpu()
            gpu = system_info.detect_gpu()
            pe = system_info.detect_pe_cores()
            cpu_presets = system_info.adaptive_cpu_presets(cpu["cores"], pe)
            default_threads = system_info.default_cpu_threads(cpu["cores"], pe)

            gpu_available = gpu["gpu_summary"] is not None
            gpu_reason = system_info.gpu_unavailable_reason(gpu)

            try:
                monitors = _list_monitors()
            except Exception as e:
                log.exception("Monitor enumeration failed")
                monitors = []
                gpu_reason = gpu_reason or f"Monitor enumeration failed: {e}"

            return jsonify({
                "models": models,
                "default_model": models[0] if models else None,
                "models_folder": MODELS_FOLDER,
                "models_folder_exists": os.path.isdir(MODELS_FOLDER),
                "devices": DEVICES,
                "default_device": "GPU" if gpu_available else "CPU",
                "cpu_presets": [
                    {"label": l, "threads": t, "affinity_mask": m} for l, t, m in cpu_presets
                ],
                "default_cpu_threads": default_threads,
                "default_hit_ante": 10,
                "monitors": monitors,
                "system": {
                    "cpu": cpu,
                    "gpu": gpu,
                    "gpu_available": gpu_available,
                    "gpu_unavailable_reason": gpu_reason,
                },
            })
        except Exception as e:
            log.exception("api_init failed")
            return jsonify({"error": f"init failed: {e}"}), 500

    @app.route("/api/monitors")
    def api_monitors():
        try:
            return jsonify({"monitors": _list_monitors()})
        except Exception as e:
            log.exception("api_monitors failed")
            return jsonify({"error": f"monitor enumeration failed: {e}", "monitors": []}), 503

    @app.route("/api/preview")
    def api_preview():
        try:
            monitor_id = int(request.args.get("monitor_id", "1"))
        except (TypeError, ValueError):
            return jsonify({"error": "monitor_id must be int"}), 400

        try:
            jpeg = _grab_preview_jpeg(monitor_id)
        except (IndexError, KeyError) as e:
            return jsonify({"error": f"invalid monitor_id: {e}"}), 400
        except Exception as e:
            log.exception("preview capture failed")
            return jsonify({"error": str(e)}), 500

        if jpeg is None:
            return jsonify({"error": "encode failed (game window may be minimized)"}), 503
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/live-frame")
    def api_live_frame():
        jpeg = state.get_live_frame()
        if not jpeg:
            abort(404)
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/last-hit-frame")
    def api_last_hit_frame():
        jpeg = state.get_last_hit_frame()
        if not jpeg:
            abort(404)
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/status")
    def api_status():
        snap = state.snapshot()
        try:
            avg = snap["tool_fps_avg"] if snap["status"] == "running" else None
            snap["fps_advice"] = fps_advisor.build_advice(avg)
        except Exception as e:
            log.exception("fps_advisor failed in /api/status")
            snap["fps_advice"] = {
                "tool_fps_avg": None,
                "ini_status": "error",
                "ini_path": None,
                "standard_caps": [],
                "recommended_cap": None,
                "game_fps_cap": None,
                "severity": "info",
                "message": f"FPS advisor unavailable: {e}",
                "recommendation": None,
            }
        return jsonify(snap)

    @app.route("/api/fps-advice")
    def api_fps_advice():
        snap = state.snapshot()
        avg = snap["tool_fps_avg"] if snap["status"] == "running" else None
        return _safe_jsonify("fps_advice", fps_advisor.build_advice, avg)

    @app.route("/api/perf")
    def api_perf():
        return _safe_jsonify("perf", perf_monitor.perf_snapshot)

    @app.route("/api/info")
    def api_info():
        return _safe_jsonify("info", env_info.collect)

    @app.route("/api/preflight")
    def api_preflight():
        device = request.args.get("device") or None
        model = request.args.get("model") or None
        if device not in (None, "CPU", "GPU"):
            device = None
        # Strip path syntax from model arg for safety even though it's only
        # used for a string-equality check inside preflight.
        if model and ("/" in model or "\\" in model or model in (".", "..")):
            model = None
        return _safe_jsonify("preflight", preflight.build_advice,
                             device=device, model=model)

    @app.route("/api/set-fps-cap", methods=["POST"])
    def api_set_fps_cap():
        body = request.get_json(silent=True) or {}
        cap_raw = body.get("cap")
        try:
            new_cap = int(cap_raw)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "cap must be an integer"}), 400
        # Reject obviously-bogus values before fps_advisor's whitelist check
        # produces a more confusing message.
        if new_cap < 0 or new_cap > 1000:
            return jsonify({"ok": False, "error": f"cap out of range: {new_cap}"}), 400
        try:
            ok, msg = fps_advisor.set_game_fps_cap(new_cap)
        except Exception as e:
            log.exception("set_game_fps_cap failed")
            return jsonify({"ok": False, "error": f"set_game_fps_cap raised: {e}"}), 500
        return jsonify({"ok": ok, "message": msg, "cap": new_cap}), (200 if ok else 400)

    @app.route("/api/start", methods=["POST"])
    def api_start():
        body = request.get_json(silent=True) or {}
        model_name = body.get("model")
        device = body.get("device", "CPU")
        monitor_id = body.get("monitor_id")

        # ── Strict validation, all paths return 400 with a helpful reason ──
        if device not in DEVICES:
            return jsonify({"ok": False, "error": f"device must be one of {DEVICES}"}), 400

        model_path = _resolve_safe_model_path(model_name)
        if model_path is None:
            return jsonify({"ok": False, "error": f"model not found or invalid: {model_name!r}"}), 400

        if monitor_id is None:
            return jsonify({"ok": False, "error": "monitor_id required"}), 400

        try:
            monitor_id_i = int(monitor_id)
            hit_ante = int(body.get("hit_ante", 10))
            nb_cpu_threads = int(body.get("nb_cpu_threads", 4))
            cpu_affinity_mask = int(body.get("cpu_affinity_mask", 0))
        except (TypeError, ValueError) as e:
            return jsonify({"ok": False, "error": f"numeric field must be int: {e}"}), 400

        if hit_ante < 0 or hit_ante > 1000:
            return jsonify({"ok": False, "error": "hit_ante out of range"}), 400
        if nb_cpu_threads < 1 or nb_cpu_threads > 256:
            return jsonify({"ok": False, "error": "nb_cpu_threads out of range"}), 400
        if cpu_affinity_mask < 0:
            return jsonify({"ok": False, "error": "cpu_affinity_mask must be >= 0"}), 400

        config = {
            "model_path": model_path,
            "device": device,
            "monitor_id": monitor_id_i,
            "hit_ante": hit_ante,
            "nb_cpu_threads": nb_cpu_threads,
            "cpu_affinity_mask": cpu_affinity_mask,
        }

        # ── Atomic check-and-spawn under the worker lock ──
        with worker_lock:
            if state.status in ("starting", "running"):
                return jsonify({"ok": False, "error": "already running"}), 409
            existing = worker_holder.get("worker")
            if existing is not None and existing.is_alive():
                return jsonify({"ok": False, "error": "previous worker still alive"}), 409

            state.reset_for_run()
            worker = InferenceWorker(state, config)
            worker_holder["worker"] = worker
            worker.start()
        return jsonify({"ok": True})

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        with worker_lock:
            worker = worker_holder.get("worker")
            if worker is None or not worker.is_alive():
                worker_holder["worker"] = None
                state.set_status("idle")
                return jsonify({"ok": True, "note": "no worker was running"})

            state.set_status("stopping")
            worker.request_stop()

        # Join outside the lock so a slow shutdown doesn't deadlock new requests.
        worker.join(timeout=5)
        if worker.is_alive():
            log.error("Worker did not stop within 5s; abandoning.")
            state.set_status("error", error="Worker did not stop within 5s — restart the app.")
            with worker_lock:
                worker_holder["worker"] = None
            return jsonify({"ok": False, "error": "worker join timed out"}), 500

        with worker_lock:
            worker_holder["worker"] = None
        return jsonify({"ok": True})

    @app.route("/api/quit", methods=["POST"])
    def api_quit():
        """Stop the worker (best-effort) and terminate the whole Python process.
        Frontend uses this for the QUIT button so the user doesn't have to
        Ctrl-C the start.bat console window."""
        with worker_lock:
            worker = worker_holder.get("worker")
            if worker is not None and worker.is_alive():
                state.set_status("stopping")
                worker.request_stop()
        # Don't join — we're about to os._exit() anyway, and we want to
        # respond to the HTTP request before the socket dies. Use a tiny
        # delayed exit so Flask can flush the response to the client.
        def _terminate_soon():
            time.sleep(0.3)
            os._exit(0)
        threading.Thread(target=_terminate_soon, daemon=True).start()
        return jsonify({"ok": True})

    return app, state, worker_holder
