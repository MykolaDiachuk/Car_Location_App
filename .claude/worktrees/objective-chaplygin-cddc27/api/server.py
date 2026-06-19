"""FastAPI server — exposes ParkingState over HTTP and serves the web frontend.

Run from project root:
    uvicorn api.server:app --reload --host 0.0.0.0 --port 8000

Set MOCK_MODE = True to run without a camera or YOLO model.
"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from parking.models import ParkingState

# ── Configuration ─────────────────────────────────────────────────────────────

MOCK_MODE = False  # set True to skip camera/YOLO during UI testing
ANALYSIS_INTERVAL = 1.0    # seconds between pipeline runs
RECONNECT_DELAY = 2.0
MAX_RECONNECT = 10
SVG_PATH = Path("assets/parking_map.svg")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Shared state (thread-safe) ────────────────────────────────────────────────

_state_lock = threading.Lock()
_latest_state: Optional[ParkingState] = None


def _set_state(state: ParkingState) -> None:
    global _latest_state
    with _state_lock:
        _latest_state = state


def _get_state() -> Optional[ParkingState]:
    with _state_lock:
        return _latest_state


# ── Background thread: real pipeline ─────────────────────────────────────────

def _pipeline_worker() -> None:
    from config import ParkingConfig
    from parking.pipeline import ParkingPipeline

    config = ParkingConfig()
    pipeline = ParkingPipeline(config)
    cap = None
    reconnect_count = 0

    while True:
        if cap is None or not cap.isOpened():
            logger.info(f"Connecting to camera (attempt {reconnect_count + 1}/{MAX_RECONNECT})...")
            cap = cv2.VideoCapture(config.CAMERA_URL)
            if not cap.isOpened():
                reconnect_count += 1
                if reconnect_count >= MAX_RECONNECT:
                    logger.error("Camera permanently unavailable — pipeline thread stopping")
                    return
                time.sleep(RECONNECT_DELAY)
                continue
            reconnect_count = 0
            logger.info("Camera connected")

        ret, frame = cap.read()
        if not ret:
            logger.warning("Frame read failed, reconnecting...")
            cap.release()
            cap = None
            continue

        try:
            result = pipeline.process_frame(frame)
            _set_state(result.state)
            logger.info(f"Cars: {result.state.occupied}  Free: {result.state.free}")
        except Exception:
            logger.exception("Pipeline error")

        time.sleep(ANALYSIS_INTERVAL)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    if MOCK_MODE:
        from api.mock_state import start_mock_worker
        logger.info("Starting in MOCK MODE — no camera required")
        t = threading.Thread(target=start_mock_worker, args=(_set_state,), daemon=True)
    else:
        t = threading.Thread(target=_pipeline_worker, daemon=True)

    t.start()
    logger.info("Background thread started")
    yield
    logger.info("Server shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Parking Monitor API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Endpoints (must come before static mount) ─────────────────────────────────

@app.get("/api/state")
def get_state():
    state = _get_state()
    if state is None:
        raise HTTPException(status_code=503, detail="No data yet — pipeline still initializing")
    return JSONResponse(content=state.model_dump(mode="json"))


@app.get("/parking_map.svg")
def get_svg():
    if not SVG_PATH.is_file():
        raise HTTPException(status_code=404, detail="SVG map not available yet")
    return FileResponse(SVG_PATH, media_type="image/svg+xml")


# ── Static frontend (catch-all — must be last) ────────────────────────────────

app.mount("/", StaticFiles(directory="web", html=True), name="web")
