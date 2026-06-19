"""Orientation zones editor — paint parallel/perpendicular parking zones on BEV.

Reads BEV background from tools/output/bev_*.png (latest).
Saves zone mask to assets/orientation_zones.png (used by the main pipeline).

Usage:
    python tools/edit_orientation_zones.py

Controls:
    LMB   — green (parallel spots)
    RMB   — blue (perpendicular spots)
    C     — clear (black / no zone)
    Brush size slider
    Reset — revert to last saved mask
    Save  — write to assets/orientation_zones.png
    ESC   — close without saving
"""
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
ZONES_PATH = ASSETS_DIR / "orientation_zones.png"
OUTPUT_DIR = TOOLS_DIR / "output"

COLOR_PARALLEL = (0, 255, 0)       # BGR green
COLOR_PERPENDICULAR = (255, 0, 0)  # BGR blue
COLOR_CLEAR = (0, 0, 0)            # BGR black


def _find_bev_background() -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob("bev_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


class ZoneEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = ParkingConfig()
        self.w = self.config.BEV_WIDTH
        self.h = self.config.BEV_HEIGHT

        self.mask = self._load_mask()
        self.original_mask = self.mask.copy()
        self.background = self._load_background()

        self.brush_size = 30
        self.draw_color = COLOR_PARALLEL
        self.is_drawing = False

        self._build_ui()

    def _load_mask(self) -> np.ndarray:
        if ZONES_PATH.exists():
            img = cv2.imread(str(ZONES_PATH))
            if img is not None:
                return cv2.resize(img, (self.w, self.h), interpolation=cv2.INTER_NEAREST)
        return np.zeros((self.h, self.w, 3), dtype=np.uint8)

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
        self.setWindowTitle("Orientation Zones Editor")
        self.setGeometry(100, 100, 1200, 900)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Brush size:"))

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(5, 150)
        self.slider.setValue(self.brush_size)
        self.slider.valueChanged.connect(self._on_slider)
        toolbar.addWidget(self.slider)

        self.spinbox = QSpinBox()
        self.spinbox.setRange(5, 150)
        self.spinbox.setValue(self.brush_size)
        self.spinbox.valueChanged.connect(self._on_spinbox)
        toolbar.addWidget(self.spinbox)

        toolbar.addSpacing(20)

        self.btn_parallel = QPushButton("Parallel (LMB)")
        self.btn_parallel.setStyleSheet("background-color: #00CC00; color: black; font-weight: bold;")
        self.btn_parallel.clicked.connect(lambda: self._set_color(COLOR_PARALLEL))
        toolbar.addWidget(self.btn_parallel)

        self.btn_perp = QPushButton("Perpendicular (RMB)")
        self.btn_perp.setStyleSheet("background-color: #0000CC; color: white; font-weight: bold;")
        self.btn_perp.clicked.connect(lambda: self._set_color(COLOR_PERPENDICULAR))
        toolbar.addWidget(self.btn_perp)

        self.btn_clear = QPushButton("Clear (C)")
        self.btn_clear.setStyleSheet("background-color: #333333; color: white; font-weight: bold;")
        self.btn_clear.clicked.connect(lambda: self._set_color(COLOR_CLEAR))
        toolbar.addWidget(self.btn_clear)

        toolbar.addSpacing(20)

        reset_btn = QPushButton("Reset")
        reset_btn.clicked.connect(self._reset)
        toolbar.addWidget(reset_btn)

        save_btn = QPushButton("Save → assets/orientation_zones.png")
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

        layout.addWidget(QLabel(
            "LMB — parallel (green)   |   RMB — perpendicular (blue)   "
            "|   C — clear   |   ESC — close"
        ))

        self._refresh()

    def _on_slider(self, value: int) -> None:
        self.brush_size = value
        self.spinbox.setValue(value)

    def _on_spinbox(self, value: int) -> None:
        self.brush_size = value
        self.slider.setValue(value)

    def _set_color(self, color: tuple[int, int, int]) -> None:
        self.draw_color = color

    def _reset(self) -> None:
        self.mask = self.original_mask.copy()
        self._refresh()

    def _save(self) -> None:
        ASSETS_DIR.mkdir(exist_ok=True)
        cv2.imwrite(str(ZONES_PATH), self.mask)
        print(f"Saved: {ZONES_PATH}")

    def _refresh(self) -> None:
        if self.background is not None:
            display = self.background.copy()
            overlay = np.zeros_like(display)

            parallel = (self.mask[:, :, 1] == 255) & (self.mask[:, :, 0] == 0)
            perp = (self.mask[:, :, 0] == 255) & (self.mask[:, :, 1] == 0)
            overlay[parallel] = COLOR_PARALLEL
            overlay[perp] = COLOR_PERPENDICULAR

            display = cv2.addWeighted(display, 0.6, overlay, 0.4, 0)
        else:
            display = self.mask.copy()

        h, w = display.shape[:2]
        q_img = QImage(display.data, w, h, 3 * w, QImage.Format_RGB888).rgbSwapped()
        scaled = QPixmap.fromImage(q_img).scaled(
            self.canvas.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.canvas.setPixmap(scaled)

    def _to_mask_coords(self, pos) -> tuple[int, int]:
        pixmap = self.canvas.pixmap()
        pw, ph = pixmap.width(), pixmap.height()
        offset_x = (self.canvas.width() - pw) / 2
        offset_y = (self.canvas.height() - ph) / 2
        x = int((pos.x() - offset_x) * self.w / pw)
        y = int((pos.y() - offset_y) * self.h / ph)
        return x, y

    def _draw_at(self, pos) -> None:
        x, y = self._to_mask_coords(pos)
        if 0 <= x < self.w and 0 <= y < self.h:
            cv2.circle(self.mask, (x, y), self.brush_size, self.draw_color, -1)
            self._refresh()

    def _mouse_press(self, event) -> None:
        self.is_drawing = True
        if event.button() == Qt.LeftButton:
            self.draw_color = COLOR_PARALLEL
        elif event.button() == Qt.RightButton:
            self.draw_color = COLOR_PERPENDICULAR
        self._draw_at(event.pos())

    def _mouse_move(self, event) -> None:
        if self.is_drawing:
            self._draw_at(event.pos())

    def _mouse_release(self, event) -> None:
        self.is_drawing = False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()
        elif event.key() == Qt.Key_C:
            self._set_color(COLOR_CLEAR)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()


def main() -> None:
    app = QApplication(sys.argv)
    editor = ZoneEditor()
    editor.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
