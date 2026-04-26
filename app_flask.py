"""Flask entry point — alternative UI to the default Gradio app.py.

Run with:  python app_flask.py
Then open: http://127.0.0.1:7860
"""
import argparse
import atexit
import logging
import signal
import sys

from dbd.web.server import create_app


def _stop_worker(worker_holder):
    worker = worker_holder.get("worker")
    if worker is not None and worker.is_alive():
        worker.request_stop()
        worker.join(timeout=5)
        if worker.is_alive():
            print("Warning: worker did not stop within 5s — process exit may hang.")


def main():
    parser = argparse.ArgumentParser(description="DBD Auto Skill Check — Flask UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app, state, worker_holder = create_app()

    atexit.register(_stop_worker, worker_holder)

    def _on_signal(signum, frame):
        _stop_worker(worker_holder)
        sys.exit(0)

    # Catch Ctrl-C (SIGINT) and SIGTERM so the worker shuts down cleanly even
    # when atexit doesn't run (e.g. service manager kills the process).
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _on_signal)
        except (ValueError, OSError):
            # Some environments (Windows service contexts) reject SIGTERM.
            pass

    print(f"DBD Auto Skill Check — Flask UI on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
