import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, abort
from io import BytesIO

import cv2
import numpy as np

from dbd.utils.monitoring_mss import Monitoring_mss
from dbd.web.state import AppState
from dbd.web.inference_worker import InferenceWorker, BETTERCAM_OK, make_monitoring
from dbd.web import fps_advisor, system_info

if BETTERCAM_OK:
    from dbd.utils.monitoring_bettercam import Monitoring_bettercam


MODELS_FOLDER = "models"
DEVICES = ["CPU", "GPU"]


def _list_models():
    if not os.path.isdir(MODELS_FOLDER):
        return []
    return sorted(
        f for f in os.listdir(MODELS_FOLDER)
        if f.endswith(".onnx") or f.endswith(".trt")
    )


def _list_monitors(monitoring_lib):
    if monitoring_lib == "bettercam" and BETTERCAM_OK:
        return [{"label": label, "id": mid} for label, mid in Monitoring_bettercam.get_monitors_info()]
    return [{"label": label, "id": mid} for label, mid in Monitoring_mss.get_monitors_info()]


def _grab_preview_jpeg(monitoring_lib, monitor_id):
    """One-shot preview frame for the monitor selector (larger crop than inference)."""
    crop_size = 520
    if monitoring_lib == "bettercam" and BETTERCAM_OK:
        with Monitoring_bettercam(monitor_id=monitor_id, crop_size=crop_size) as mon:
            frame = mon.get_frame_np()
    else:
        with Monitoring_mss(monitor_id=monitor_id, crop_size=crop_size) as mon:
            frame = mon.get_frame_np()

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

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/init")
    def api_init():
        models = _list_models()
        monitoring_libs = ["mss", "bettercam"] if BETTERCAM_OK else ["mss"]

        cpu = system_info.detect_cpu()
        gpu = system_info.detect_gpu()
        cpu_presets = system_info.adaptive_cpu_presets(cpu["cores"])
        default_threads = system_info.default_cpu_threads(cpu["cores"])

        gpu_available = gpu["gpu_summary"] is not None
        gpu_reason = system_info.gpu_unavailable_reason(gpu)

        return jsonify({
            "models": models,
            "default_model": models[0] if models else None,
            "models_folder": MODELS_FOLDER,
            "devices": DEVICES,
            "default_device": "GPU" if gpu_available else "CPU",
            "monitoring_libs": monitoring_libs,
            "default_monitoring_lib": monitoring_libs[0],
            "cpu_presets": [{"label": l, "threads": t} for l, t in cpu_presets],
            "default_cpu_threads": default_threads,
            "default_hit_ante": 20,
            "monitors": _list_monitors(monitoring_libs[0]),
            "system": {
                "cpu": cpu,
                "gpu": gpu,
                "gpu_available": gpu_available,
                "gpu_unavailable_reason": gpu_reason,
            },
        })

    @app.route("/api/monitors")
    def api_monitors():
        monitoring_lib = request.args.get("monitoring_lib", "mss")
        return jsonify({"monitors": _list_monitors(monitoring_lib)})

    @app.route("/api/preview")
    def api_preview():
        monitoring_lib = request.args.get("monitoring_lib", "mss")
        try:
            monitor_id_raw = request.args.get("monitor_id", "1")
            monitor_id = int(monitor_id_raw)
        except ValueError:
            abort(400, "monitor_id must be int")

        try:
            jpeg = _grab_preview_jpeg(monitoring_lib, monitor_id)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        if jpeg is None:
            abort(500, "encode failed")
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/live-frame")
    def api_live_frame():
        snap_lock = state._lock
        with snap_lock:
            jpeg = state.live_frame_jpeg
        if not jpeg:
            abort(404)
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/last-hit-frame")
    def api_last_hit_frame():
        snap_lock = state._lock
        with snap_lock:
            jpeg = state.last_hit_frame_jpeg
        if not jpeg:
            abort(404)
        return send_file(BytesIO(jpeg), mimetype="image/jpeg")

    @app.route("/api/status")
    def api_status():
        snap = state.snapshot()
        avg = snap["tool_fps_avg"] if snap["status"] == "running" else None
        snap["fps_advice"] = fps_advisor.build_advice(avg)
        return jsonify(snap)

    @app.route("/api/fps-advice")
    def api_fps_advice():
        snap = state.snapshot()
        avg = snap["tool_fps_avg"] if snap["status"] == "running" else None
        return jsonify(fps_advisor.build_advice(avg))

    @app.route("/api/start", methods=["POST"])
    def api_start():
        if state.status in ("starting", "running"):
            return jsonify({"ok": False, "error": "already running"}), 409

        body = request.get_json(silent=True) or {}
        model_name = body.get("model")
        device = body.get("device", "CPU")
        monitoring_lib = body.get("monitoring_lib", "mss")
        monitor_id = body.get("monitor_id")
        hit_ante = int(body.get("hit_ante", 20))
        nb_cpu_threads = int(body.get("nb_cpu_threads", 4))

        if not model_name:
            return jsonify({"ok": False, "error": "model required"}), 400
        model_path = os.path.join(MODELS_FOLDER, model_name)
        if not os.path.exists(model_path):
            return jsonify({"ok": False, "error": f"model not found: {model_path}"}), 400
        if monitor_id is None:
            return jsonify({"ok": False, "error": "monitor_id required"}), 400

        config = {
            "model_path": model_path,
            "device": device,
            "monitoring_lib": monitoring_lib,
            "monitor_id": int(monitor_id),
            "hit_ante": hit_ante,
            "nb_cpu_threads": nb_cpu_threads,
        }

        state.reset_for_run()
        worker = InferenceWorker(state, config)
        worker_holder["worker"] = worker
        worker.start()
        return jsonify({"ok": True})

    @app.route("/api/stop", methods=["POST"])
    def api_stop():
        worker = worker_holder.get("worker")
        if worker is None or not worker.is_alive():
            state.set_status("idle")
            return jsonify({"ok": True, "note": "no worker was running"})

        state.set_status("stopping")
        worker.request_stop()
        worker.join(timeout=5)
        worker_holder["worker"] = None
        return jsonify({"ok": True})

    return app, state, worker_holder
