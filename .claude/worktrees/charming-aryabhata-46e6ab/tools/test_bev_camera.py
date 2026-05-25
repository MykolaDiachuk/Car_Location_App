"""Live BEV preview from camera — used to verify SRC_POINTS calibration.

Usage:
    python tools/test_bev_camera.py

Controls:
    q     — quit
    s     — save current frame pair to tools/output/
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
from parking.transformer import PerspectiveTransformer

OUTPUT_DIR = TOOLS_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

GRID_STEP = 50


def draw_src_points(frame: np.ndarray, config: ParkingConfig) -> np.ndarray:
    """Draw the perspective source points on the frame."""
    result = frame.copy()
    colors = [(0, 255, 0), (0, 255, 255), (255, 0, 0), (255, 255, 0)]
    labels = ["1: TL", "2: TR", "3: BR", "4: BL"]

    pts = config.SRC_POINTS.astype(np.int32)
    cv2.polylines(result, [pts.reshape(-1, 1, 2)], True, (0, 255, 0), 2)

    for pt, color, label in zip(pts, colors, labels):
        x, y = int(pt[0]), int(pt[1])
        cv2.circle(result, (x, y), 8, color, -1)
        cv2.circle(result, (x, y), 10, (255, 255, 255), 2)
        cv2.putText(result, label, (x + 14, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

    return result


def draw_grid(img: np.ndarray, step: int = GRID_STEP) -> np.ndarray:
    """Overlay a pixel grid on the image."""
    result = img.copy()
    h, w = result.shape[:2]
    color = (100, 100, 100)

    for x in range(0, w, step):
        cv2.line(result, (x, 0), (x, h), color, 1)
        if x > 0:
            cv2.putText(result, str(x), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)

    for y in range(0, h, step):
        cv2.line(result, (0, y), (w, y), color, 1)
        if y > 0:
            cv2.putText(result, str(y), (2, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)

    cv2.putText(result, f"BEV {w}x{h}", (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    return result


def main() -> None:
    config = ParkingConfig()
    transformer = PerspectiveTransformer(config)

    print(f"Connecting to: {config.CAMERA_URL}")
    cap = cv2.VideoCapture(config.CAMERA_URL)

    if not cap.isOpened():
        print("ERROR: Could not connect to camera")
        return

    print("Connected. Controls: q=quit  s=save  SPACE=freeze")

    frozen = False
    display_orig: np.ndarray | None = None
    display_bev: np.ndarray | None = None

    while True:
        if not frozen:
            ret, frame = cap.read()
            if not ret:
                print("ERROR: Lost connection")
                break

            display_orig = draw_src_points(frame, config)
            display_bev = draw_grid(transformer.transform(frame))

        if display_orig is not None:
            cv2.imshow("Original + SRC_POINTS", display_orig)
            cv2.imshow("BEV Transformation", display_bev)

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):
            break
        elif key == ord(" "):
            frozen = not frozen
            print("FROZEN" if frozen else "LIVE")
        elif key == ord("s") and display_orig is not None:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            cv2.imwrite(str(OUTPUT_DIR / f"bev_test_orig_{ts}.jpg"), display_orig)
            cv2.imwrite(str(OUTPUT_DIR / f"bev_test_bev_{ts}.jpg"), display_bev)
            print(f"Saved to tools/output/bev_test_*_{ts}.jpg")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
