"""Generate Bird's Eye View image from a frame for mask editing.

Reads input from tools/input/, writes output to tools/output/.

Usage:
    python tools/generate_bev.py

    # Custom input/output:
    python tools/generate_bev.py --input tools/input/frame.jpg --output tools/output/bev.png

    # Without grid:
    python tools/generate_bev.py --no-grid
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR.parent))

from config import ParkingConfig

INPUT_DIR = TOOLS_DIR / "input"
OUTPUT_DIR = TOOLS_DIR / "output"


def _draw_grid(img: np.ndarray, step: int = 50) -> np.ndarray:
    h, w = img.shape[:2]
    out = img.copy()
    color = (100, 100, 100)
    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h - 1), color, 1)
        cv2.putText(out, str(x), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
    for y in range(0, h, step):
        cv2.line(out, (0, y), (w - 1, y), color, 1)
        cv2.putText(out, str(y), (2, y + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
    return out


def generate_bev(image_path: Path, output_path: Path, *, draw_grid: bool = True, grid_step: int = 50) -> None:
    img = cv2.imread(str(image_path))
    if img is None:
        raise FileNotFoundError(f"Could not read: {image_path}")

    cfg = ParkingConfig
    matrix = cv2.getPerspectiveTransform(
        np.asarray(cfg.SRC_POINTS, dtype=np.float32),
        cfg.get_dst_points(),
    )
    bev = cv2.warpPerspective(img, matrix, (cfg.BEV_WIDTH, cfg.BEV_HEIGHT))

    if draw_grid:
        bev = _draw_grid(bev, step=grid_step)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), bev):
        raise RuntimeError(f"Failed to write: {output_path}")

    print(f"Saved: {output_path}  ({cfg.BEV_WIDTH}x{cfg.BEV_HEIGHT})")
    print("Next steps:")
    print("  python tools/edit_parking_mask.py")
    print("  python tools/edit_orientation_zones.py")


def _default_input() -> Path:
    """Return the first image found in tools/input/, or raise."""
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        matches = sorted(INPUT_DIR.glob(ext))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"No images found in {INPUT_DIR}. "
        "Run tools/capture_frame.py first or place a frame in tools/input/."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate BEV from a camera frame")
    parser.add_argument("--input", "-i", default=None, help="Input image path")
    parser.add_argument("--output", "-o", default=None, help="Output BEV image path")
    parser.add_argument("--no-grid", action="store_true", help="Disable grid overlay")
    parser.add_argument("--grid-step", type=int, default=50, help="Grid step in pixels")
    args = parser.parse_args()

    try:
        input_path = Path(args.input) if args.input else _default_input()
        output_path = Path(args.output) if args.output else OUTPUT_DIR / f"bev_{input_path.stem}.png"
        generate_bev(input_path, output_path, draw_grid=not args.no_grid, grid_step=args.grid_step)
    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
