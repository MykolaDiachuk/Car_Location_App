"""Test camera connection — shows live feed.

Usage:
    python tools/test_connection.py

Controls:
    q — quit
"""
import sys
from pathlib import Path

import cv2

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from config import ParkingConfig


def main() -> None:
    config = ParkingConfig()
    print(f"Connecting to: {config.CAMERA_URL}")

    cap = cv2.VideoCapture(config.CAMERA_URL)
    if not cap.isOpened():
        print("ERROR: Could not connect to camera")
        return

    print("Connected. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("ERROR: Lost connection")
            break
        cv2.imshow("Camera Feed — press 'q' to quit", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
