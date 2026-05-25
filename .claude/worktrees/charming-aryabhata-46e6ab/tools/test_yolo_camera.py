"""Live camera feed with YOLO detection overlay.

Shows the camera stream with bounding boxes around detected vehicles
(car, motorcycle, bus, truck). Useful for verifying model quality,
camera angle, and detection thresholds.

Usage:
    python tools/test_yolo_camera.py

Controls:
    q     — quit
    s     — save current frame to tools/output/
    SPACE — freeze / unfreeze
"""
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from config import ParkingConfig
from parking.detector import VehicleDetector

OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

CLASS_NAMES: dict[int, str] = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

DISPLAY_WIDTH = 1280

BOX_COLOR = (0, 255, 0)
TEXT_COLOR = (0, 255, 0)
TEXT_BG_COLOR = (0, 0, 0)
BOX_THICKNESS = 2
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.55
FONT_THICKNESS = 1


def draw_detections(frame: np.ndarray, detections: list[np.ndarray]) -> np.ndarray:
    """Draw bounding boxes and labels on the frame."""
    result = frame.copy()

    for det in detections:
        x1, y1, x2, y2, conf = det
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cv2.rectangle(result, (x1, y1), (x2, y2), BOX_COLOR, BOX_THICKNESS)

        label = f"{conf:.0%}"
        (tw, th), baseline = cv2.getTextSize(label, FONT, FONT_SCALE, FONT_THICKNESS)
        cv2.rectangle(result, (x1, y1 - th - baseline - 4), (x1 + tw + 4, y1), TEXT_BG_COLOR, -1)
        cv2.putText(result, label, (x1 + 2, y1 - baseline - 2), FONT, FONT_SCALE, TEXT_COLOR, FONT_THICKNESS)

    return result


def draw_hud(frame: np.ndarray, count: int, frozen: bool) -> np.ndarray:
    """Draw detection count and status overlay."""
    result = frame.copy()
    h, w = result.shape[:2]

    status = f"Vehicles: {count}"
    if frozen:
        status += "  [FROZEN]"

    cv2.putText(result, status, (10, h - 14), FONT, 0.7, (255, 255, 255), 2)
    return result


def main() -> None:
    config = ParkingConfig()
    detector = VehicleDetector(config)

    print(f"Connecting to: {config.CAMERA_URL}")
    cap = cv2.VideoCapture(config.CAMERA_URL)

    if not cap.isOpened():
        print("ERROR: Could not connect to camera")
        return

    print("Connected. Controls: q=quit  s=save  SPACE=freeze")

    frozen = False
    display: np.ndarray | None = None
    det_count = 0

    while True:
        if not frozen:
            ret, frame = cap.read()
            if not ret:
                print("ERROR: Lost connection")
                break

            detections = detector.detect(frame)
            det_count = len(detections)
            display = draw_detections(frame, detections)

        if display is not None:
            shown = draw_hud(display, det_count, frozen)
            h, w = shown.shape[:2]
            scale = DISPLAY_WIDTH / w
            shown = cv2.resize(shown, (DISPLAY_WIDTH, int(h * scale)))
            cv2.imshow("YOLO Camera — press 'q' to quit", shown)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            frozen = not frozen
            print("FROZEN" if frozen else "LIVE")
        elif key == ord("s") and display is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = OUTPUT_DIR / f"yolo_frame_{ts}.jpg"
            cv2.imwrite(str(path), display)
            print(f"Saved: {path}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
