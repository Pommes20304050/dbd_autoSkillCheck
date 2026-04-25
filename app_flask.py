"""Flask entry point — alternative UI to the default Gradio app.py.

Run with:  python app_flask.py
Then open: http://127.0.0.1:7860
"""
import argparse
import atexit

from dbd.web.server import create_app


def main():
    parser = argparse.ArgumentParser(description="DBD Auto Skill Check — Flask UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    app, state, worker_holder = create_app()

    @atexit.register
    def _shutdown():
        worker = worker_holder.get("worker")
        if worker is not None and worker.is_alive():
            worker.request_stop()
            worker.join(timeout=5)

    print(f"DBD Auto Skill Check — Flask UI on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
