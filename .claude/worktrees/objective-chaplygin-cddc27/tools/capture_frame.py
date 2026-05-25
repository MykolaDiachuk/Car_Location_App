"""Capture a single frame from RTSP camera for BEV calibration.

Usage:
    python tools/capture_frame.py

Output:
    tools/input/frame_YYYYMMDD_HHMMSS.jpg
"""
import sys
from datetime import datetime
from pathlib import Path

import cv2

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from config import ParkingConfig

INPUT_DIR = TOOLS_DIR / "input"
INPUT_DIR.mkdir(exist_ok=True)

WARMUP_FRAMES = 5


def capture_frame(camera_url: str) -> Path:
    """Capture one frame from camera and save to tools/output/.

    Skips the first few frames to avoid camera warmup artifacts.

    Returns:
        Path to saved file.

    Raises:
        RuntimeError: If camera connection or frame read fails.
    """
    print(f"Connecting to camera: {camera_url}")
    cap = cv2.VideoCapture(camera_url)

    if not cap.isOpened():
        raise RuntimeError("Could not connect to camera")

    for _ in range(WARMUP_FRAMES):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Failed to read frame")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = INPUT_DIR / f"frame_{timestamp}.jpg"
    cv2.imwrite(str(output_path), frame)
    
    print(f"Saved: {output_path}  ({frame.shape[1]}x{frame.shape[0]})")
    print(f"Next step: python tools/find_bev_points.py")

    cv2.imshow("Captured Frame — press any key to close", frame)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return output_path


def main() -> int:
    config = ParkingConfig()
    try:
        capture_frame(config.CAMERA_URL)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
