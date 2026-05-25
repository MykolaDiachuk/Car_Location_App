"""Interactive BEV point finder — adjust SRC_POINTS visually.

Place a frame image in tools/input/ (e.g. captured with tools/capture_frame.py),
then run this tool to tune the 4 perspective source points with sliders.
Press "Export" to copy the result to clipboard and paste into config.py.

Usage:
    python tools/find_bev_points.py
    python tools/find_bev_points.py --input tools/input/frame.jpg
"""
import sys
from pathlib import Path

import argparse
import cv2
import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QGridLayout, QLabel, QPushButton, QSlider, QWidget,
)

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import ParkingConfig

INPUT_DIR = TOOLS_DIR / "input"
DISPLAY_SIZE = 450
EXTRA = 500  # Allow points outside image bounds by this many pixels


def _find_input_image() -> Path:
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        matches = sorted(INPUT_DIR.glob(ext))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"No images found in {INPUT_DIR}. "
        "Run tools/capture_frame.py first or place a frame in tools/input/."
    )


class BEVEditor(QWidget):
    def __init__(self, image_path: Path) -> None:
        super().__init__()
        self.img = cv2.imread(str(image_path))
        if self.img is None:
            raise FileNotFoundError(f"Could not read image: {image_path}")

        self.h, self.w = self.img.shape[:2]
        cfg = ParkingConfig()
        self.points = [list(map(int, pt)) for pt in cfg.SRC_POINTS]
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("BEV Point Finder")
        grid = QGridLayout(self)

        self.img_label = QLabel()
        self.img_label.setFixedSize(DISPLAY_SIZE, DISPLAY_SIZE)
        self.img_label.setAlignment(Qt.AlignCenter)
        grid.addWidget(QLabel("Original + points"), 0, 0, Qt.AlignCenter)
        grid.addWidget(self.img_label, 1, 0)

        self.bev_label = QLabel()
        self.bev_label.setFixedSize(DISPLAY_SIZE, DISPLAY_SIZE)
        self.bev_label.setAlignment(Qt.AlignCenter)
        grid.addWidget(QLabel("BEV preview"), 0, 1, Qt.AlignCenter)
        grid.addWidget(self.bev_label, 1, 1)

        controls = QGridLayout()
        labels = ["TL", "TR", "BR", "BL"]
        self.sliders: list[tuple[QSlider, QSlider]] = []
        self.coord_labels: list[tuple[QLabel, QLabel]] = []

        for i in range(4):
            lx = QLabel(f"{labels[i]} X: {self.points[i][0]}")
            ly = QLabel(f"{labels[i]} Y: {self.points[i][1]}")
            controls.addWidget(lx, 0, i)
            controls.addWidget(ly, 2, i)

            sx = QSlider(Qt.Horizontal)
            sx.setRange(-EXTRA, self.w + EXTRA)
            sx.setValue(self.points[i][0])
            sx.valueChanged.connect(lambda v, idx=i: self._update(idx, 0, v))
            controls.addWidget(sx, 1, i)

            sy = QSlider(Qt.Horizontal)
            sy.setRange(-EXTRA, self.h + EXTRA)
            sy.setValue(self.points[i][1])
            sy.valueChanged.connect(lambda v, idx=i: self._update(idx, 1, v))
            controls.addWidget(sy, 3, i)

            self.sliders.append((sx, sy))
            self.coord_labels.append((lx, ly))

        gen_btn = QPushButton("Generate BEV")
        gen_btn.clicked.connect(self._generate_bev)
        controls.addWidget(gen_btn, 4, 0, 1, 2)

        export_btn = QPushButton("Export → clipboard")
        export_btn.clicked.connect(self._export)
        controls.addWidget(export_btn, 4, 2, 1, 2)

        grid.addLayout(controls, 2, 0, 1, 2)
        self._render_original()

    def _update(self, idx: int, xy: int, value: int) -> None:
        self.points[idx][xy] = value
        axis = "X" if xy == 0 else "Y"
        label_idx = ["TL", "TR", "BR", "BL"][idx]
        self.coord_labels[idx][xy].setText(f"{label_idx} {axis}: {value}")
        self._render_original()

    def _render_original(self) -> None:
        img = self.img.copy()
        colors = [(0, 255, 0), (0, 255, 255), (255, 0, 0), (255, 255, 0)]
        for i, (pt, color) in enumerate(zip(self.points, colors)):
            x, y = int(pt[0]), int(pt[1])
            if 0 <= x < self.w and 0 <= y < self.h:
                cv2.circle(img, (x, y), 10, color, -1)
                cv2.putText(img, str(i + 1), (x + 14, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        self._set_pixmap(self.img_label, img)

    def _generate_bev(self) -> None:
        src = np.float32(self.points)
        dst = np.float32([[0, 0], [self.w - 1, 0], [self.w - 1, self.h - 1], [0, self.h - 1]])
        matrix = cv2.getPerspectiveTransform(src, dst)
        bev = cv2.warpPerspective(self.img, matrix, (self.w, self.h))
        self._set_pixmap(self.bev_label, bev)

    def _set_pixmap(self, label: QLabel, img: np.ndarray) -> None:
        resized = cv2.resize(img, (DISPLAY_SIZE, DISPLAY_SIZE))
        q_img = QImage(resized.data, DISPLAY_SIZE, DISPLAY_SIZE, resized.strides[0], QImage.Format_BGR888)
        label.setPixmap(QPixmap.fromImage(q_img))

    def _export(self) -> None:
        coords = [f"    [{x}, {y}]" for x, y in self.points]
        text = "SRC_POINTS = np.float32([\n" + ",\n".join(coords) + "\n])"
        QApplication.clipboard().setText(text)
        print("\nExported to clipboard:\n" + text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Adjust BEV source points interactively")
    parser.add_argument("--input", "-i", default=None, help="Input frame image path")
    args = parser.parse_args()

    image_path = Path(args.input) if args.input else _find_input_image()

    app = QApplication(sys.argv)
    editor = BEVEditor(image_path)
    editor.resize(1100, 850)
    editor.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
