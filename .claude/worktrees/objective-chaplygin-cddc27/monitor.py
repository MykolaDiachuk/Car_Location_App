"""Realtime parking monitor — main entry point.

Run:
    python monitor.py

Controls:
    q — quit
    s — save screenshot to output/
"""
import logging
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from config import ParkingConfig
from parking.pipeline import ParkingPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ANALYSIS_INTERVAL = 1.0   # seconds between full pipeline runs
RECONNECT_ATTEMPTS = 5


def connect(url: str) -> cv2.VideoCapture | None:
    """Try to open camera, return capture object or None."""
    for attempt in range(1, RECONNECT_ATTEMPTS + 1):
        logger.info(f"Connecting ({attempt}/{RECONNECT_ATTEMPTS})...")
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                logger.info("Connected")
                return cap
            cap.release()
        if attempt < RECONNECT_ATTEMPTS:
            time.sleep(2)
    logger.error("Could not connect to camera")
    return None


def overlay_stats(img: np.ndarray, cars: int, free: int) -> np.ndarray:
    """Draw a small stats panel on the image."""
    out = img.copy()
    h, w = out.shape[:2]
    cv2.rectangle(out, (10, 10), (w - 10, 90), (0, 0, 0), -1)
    cv2.addWeighted(out, 0.65, img, 0.35, 0, out)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(out, "PARKING MONITOR", (20, 38), font, 0.75, (255, 255, 255), 2)
    cv2.putText(out, f"CARS: {cars}", (20, 72), font, 0.6, (0, 0, 255), 2)
    cv2.putText(out, f"FREE: {free}", (180, 72), font, 0.6, (0, 255, 0), 2)
    cv2.putText(
        out,
        datetime.now().strftime("%H:%M:%S"),
        (w - 110, 72),
        font, 0.5, (180, 180, 180), 1,
    )
    return out


def load_mask(config: ParkingConfig) -> np.ndarray:
    """Load parking mask resized to BEV dimensions."""
    mask = cv2.imread("assets/parking_mask.png", cv2.IMREAD_GRAYSCALE)
    if mask is None:
        logger.warning("parking_mask.png not found — mask overlay disabled")
        return np.zeros((config.BEV_HEIGHT, config.BEV_WIDTH), dtype=np.uint8)
    return cv2.resize(mask, (config.BEV_WIDTH, config.BEV_HEIGHT), interpolation=cv2.INTER_NEAREST)


def overlay_parking_zones(bev_img: np.ndarray, mask_bev: np.ndarray) -> np.ndarray:
    """Blend parking mask zones semi-transparently onto BEV image."""
    color_mask = np.zeros_like(bev_img)
    color_mask[mask_bev > 128] = (200, 200, 0)  # cyan-yellow tint for allowed zones
    return cv2.addWeighted(bev_img, 0.75, color_mask, 0.25, 0)


def run() -> None:
    config = ParkingConfig()
    pipeline = ParkingPipeline(config)

    mask_bev = load_mask(config)

    cap = connect(config.CAMERA_URL)
    if cap is None:
        return

    last_analysis = 0.0
    display: np.ndarray | None = None

    logger.info("Monitor running — press 'q' to quit, 's' to screenshot")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Frame read failed, reconnecting...")
                cap.release()
                cap = connect(config.CAMERA_URL)
                if cap is None:
                    break
                continue

            if time.time() - last_analysis >= ANALYSIS_INTERVAL:
                last_analysis = time.time()
                result = pipeline.process_frame(frame)
                annotated = overlay_parking_zones(result.analysis_view, mask_bev)
                display = overlay_stats(annotated, result.state.occupied, result.state.free)
                logger.info(f"Cars: {result.state.occupied}  Free: {result.state.free}")

            if display is not None:
                cv2.imshow("Parking Monitor", display)

            key = cv2.waitKey(10) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s") and display is not None:
                Path("output").mkdir(exist_ok=True)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                cv2.imwrite(f"output/snapshot_{ts}.jpg", display)
                logger.info(f"Saved output/snapshot_{ts}.jpg")

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    run()
