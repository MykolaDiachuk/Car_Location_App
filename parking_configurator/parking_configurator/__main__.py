from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser


def _setup_env() -> None:
    os.environ.setdefault(
        "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        "rtsp_transport;tcp|stimeout;10000000",
    )


def _open_browser_when_ready(url: str, delay: float = 1.2) -> None:
    def _opener() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url, new=1, autoraise=True)
        except Exception:
            pass

    t = threading.Thread(target=_opener, daemon=True)
    t.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m parking_configurator",
        description="Local pre-deploy setup tool for the parking monitoring system",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="bind port (default: 8765)"
    )
    parser.add_argument(
        "--fresh", action="store_true", help="discard any previous saved session"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the browser automatically",
    )
    args = parser.parse_args(argv)

    _setup_env()
    if args.fresh:
        os.environ["PARKING_CONFIGURATOR_FRESH"] = "1"

    url = f"http://{args.host}:{args.port}/"
    print(f"Parking Configurator listening at {url}")
    if not args.no_browser:
        _open_browser_when_ready(url)

    import uvicorn

    uvicorn.run(
        "parking_configurator.server:app",
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
