"""Parking mask editor — draw allowed/forbidden zones on the BEV image.

Reads BEV background from tools/output/bev_*.png (latest).
Saves mask to assets/parking_mask.png (used by the main pipeline).

Usage:
    python tools/edit_parking_mask.py

Controls:
    LMB   — white (allowed zone)
    RMB   — black (forbidden zone)
    Brush size slider
    Reset — revert to last saved mask
    Save  — write to assets/parking_mask.png
    ESC   — close without saving
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import ParkingConfig

ASSETS_DIR = PROJECT_ROOT / "assets"
MASK_PATH = ASSETS_DIR / "parking_mask.png"
OUTPUT_DIR = TOOLS_DIR / "output"


def _find_bev_background() -> Path | None:
    """Return the most recent BEV image from tools/output/."""
    candidates = sorted(OUTPUT_DIR.glob("bev_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


class MaskEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = ParkingConfig()
        self.w = self.config.BEV_WIDTH
        self.h = self.config.BEV_HEIGHT

        self.mask = self._load_mask()
        self.original_mask = self.mask.copy()
        self.background = self._load_background()

        self.brush_size = 20
        self.draw_color = 255
        self.is_drawing = False

        self._build_ui()

    def _load_mask(self) -> np.ndarray:
        if MASK_PATH.exists():
            mask = cv2.imread(str(MASK_PATH), cv2.IMREAD_GRAYSCALE)
            if mask is not None:
                return cv2.resize(mask, (self.w, self.h))
        return np.full((self.h, self.w), 255, dtype=np.uint8)

    def _load_background(self) -> np.ndarray | None:
        bev_path = _find_bev_background()
        if bev_path:
            img = cv2.imread(str(bev_path))
            if img is not None:
                print(f"BEV background: {bev_path.name}")
                return cv2.resize(img, (self.w, self.h))
        print("No BEV background found. Run tools/generate_bev.py first.")
        return None

    def _build_ui(self) -> None:
        self.setWindowTitle("Parking Mask Editor")
        self.setGeometry(100, 100, 1000, 800)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Brush size:"))

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(5, 100)
        self.slider.setValue(self.brush_size)
        self.slider.valueChanged.connect(self._on_slider)
        toolbar.addWidget(self.slider)

        self.spinbox = QSpinBox()
        self.spinbox.setRange(5, 100)
        self.spinbox.setValue(self.brush_size)
        self.spinbox.valueChanged.connect(self._on_spinbox)
        toolbar.addWidget(self.spinbox)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        toolbar.addWidget(reset_btn)

        save_btn = QPushButton("Save → assets/parking_mask.png")
        save_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        layout.addLayout(toolbar)

        self.canvas = QLabel()
        self.canvas.setAlignment(Qt.AlignCenter)
        self.canvas.setMouseTracking(True)
        self.canvas.mousePressEvent = self._mouse_press
        self.canvas.mouseMoveEvent = self._mouse_move
        self.canvas.mouseReleaseEvent = self._mouse_release
        layout.addWidget(self.canvas)

        layout.addWidget(QLabel("LMB — allow (white)   |   RMB — forbid (black)   |   ESC — close"))

        self._refresh()

    def _on_slider(self, value: int) -> None:
        self.brush_size = value
        self.spinbox.setValue(value)

    def _on_spinbox(self, value: int) -> None:
        self.brush_size = value
        self.slider.setValue(value)

    def _reset(self) -> None:
        self.mask = self.original_mask.copy()
        self._refresh()

    def _save(self) -> None:
        ASSETS_DIR.mkdir(exist_ok=True)
        cv2.imwrite(str(MASK_PATH), self.mask)
        print(f"Saved: {MASK_PATH}")

    def _refresh(self) -> None:
        if self.background is not None:
            display = self.background.copy()
            overlay = np.zeros_like(display)
            overlay[self.mask == 0] = (0, 0, 255)
            overlay[self.mask == 255] = (0, 255, 0)
            display = cv2.addWeighted(display, 0.6, overlay, 0.4, 0)
        else:
            display = cv2.cvtColor(self.mask, cv2.COLOR_GRAY2BGR)

        h, w = display.shape[:2]
        q_img = QImage(display.data, w, h, 3 * w, QImage.Format_RGB888).rgbSwapped()
        self.canvas.setPixmap(QPixmap.fromImage(q_img))

    def _to_mask_coords(self, pos) -> tuple[int, int]:
        pixmap = self.canvas.pixmap()
        lw, lh = self.canvas.width(), self.canvas.height()
        pw, ph = pixmap.width(), pixmap.height()
        x = int(pos.x() * pw / lw)
        y = int(pos.y() * ph / lh)
        return x, y

    def _draw_at(self, pos) -> None:
        x, y = self._to_mask_coords(pos)
        cv2.circle(self.mask, (x, y), self.brush_size, self.draw_color, -1)
        self._refresh()

    def _mouse_press(self, event) -> None:
        self.is_drawing = True
        self.draw_color = 255 if event.button() == Qt.LeftButton else 0
        self._draw_at(event.pos())

    def _mouse_move(self, event) -> None:
        if self.is_drawing:
            self._draw_at(event.pos())

    def _mouse_release(self, event) -> None:
        self.is_drawing = False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()


def main() -> None:
    app = QApplication(sys.argv)
    editor = MaskEditor()
    editor.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
