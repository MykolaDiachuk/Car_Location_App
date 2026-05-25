"""Live BEV camera feed with YOLO detection overlay.

Takes camera frames, transforms them to Bird's Eye View, then runs
YOLO detection on the BEV image. Shows both the original YOLO result
and the BEV YOLO result side-by-side for comparison.

Usage:
    python tools/test_yolo_bev_camera.py

Controls:
    q     — quit
    s     — save current frames to tools/output/
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
from parking.transformer import PerspectiveTransformer

OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DISPLAY_WIDTH = 640

BOX_COLOR = (0, 255, 0)
TEXT_BG_COLOR = (0, 0, 0)
BOX_THICKNESS = 2
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.5
FONT_THICKNESS = 1


def draw_detections(frame: np.ndarray, detections: list[np.ndarray]) -> np.ndarray:
    result = frame.copy()
    for det in detections:
        x1, y1, x2, y2, conf = det
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

        cv2.rectangle(result, (x1, y1), (x2, y2), BOX_COLOR, BOX_THICKNESS)

        label = f"{conf:.0%}"
        (tw, th), baseline = cv2.getTextSize(label, FONT, FONT_SCALE, FONT_THICKNESS)
        cv2.rectangle(result, (x1, y1 - th - baseline - 4), (x1 + tw + 4, y1), TEXT_BG_COLOR, -1)
        cv2.putText(result, label, (x1 + 2, y1 - baseline - 2), FONT, FONT_SCALE, BOX_COLOR, FONT_THICKNESS)

    return result


def draw_label(frame: np.ndarray, text: str, count: int, frozen: bool) -> np.ndarray:
    result = frame.copy()
    h = result.shape[0]
    status = f"{text}: {count}"
    if frozen:
        status += "  [FROZEN]"
    cv2.putText(result, status, (8, h - 10), FONT, 0.6, (255, 255, 255), 2)
    return result


def resize_to_width(frame: np.ndarray, width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = width / w
    return cv2.resize(frame, (width, int(h * scale)))


def main() -> None:
    config = ParkingConfig()
    detector = VehicleDetector(config)
    transformer = PerspectiveTransformer(config)

    print(f"Connecting to: {config.CAMERA_URL}")
    cap = cv2.VideoCapture(config.CAMERA_URL)

    if not cap.isOpened():
        print("ERROR: Could not connect to camera")
        return

    print("Connected. Controls: q=quit  s=save  SPACE=freeze")

    frozen = False
    orig_display: np.ndarray | None = None
    bev_display: np.ndarray | None = None
    orig_count = 0
    bev_count = 0

    while True:
        if not frozen:
            ret, frame = cap.read()
            if not ret:
                print("ERROR: Lost connection")
                break

            bev = transformer.transform(frame)

            orig_dets = detector.detect(frame)
            bev_dets = detector.detect(bev)

            orig_count = len(orig_dets)
            bev_count = len(bev_dets)

            orig_display = draw_detections(frame, orig_dets)
            bev_display = draw_detections(bev, bev_dets)

        if orig_display is not None and bev_display is not None:
            orig_shown = draw_label(orig_display, "Original", orig_count, frozen)
            bev_shown = draw_label(bev_display, "BEV", bev_count, frozen)

            orig_shown = resize_to_width(orig_shown, DISPLAY_WIDTH)
            bev_shown = resize_to_width(bev_shown, DISPLAY_WIDTH)

            cv2.imshow("Original + YOLO", orig_shown)
            cv2.imshow("BEV + YOLO", bev_shown)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            frozen = not frozen
            print("FROZEN" if frozen else "LIVE")
        elif key == ord("s") and orig_display is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(str(OUTPUT_DIR / f"yolo_orig_{ts}.jpg"), orig_display)
            cv2.imwrite(str(OUTPUT_DIR / f"yolo_bev_{ts}.jpg"), bev_display)
            print(f"Saved to tools/output/yolo_*_{ts}.jpg")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
