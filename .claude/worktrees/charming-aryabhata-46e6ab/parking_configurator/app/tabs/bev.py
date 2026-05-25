"""BEV Calibration tab — adjust 4 source points via drag, spinboxes, or raw paste."""
import re

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QGraphicsEllipseItem, QGraphicsLineItem,
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView,
    QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout, QWidget,
)

from app.state import AppState

POINT_COLORS = [
    QColor(0, 255, 0),    # TL — green
    QColor(0, 220, 255),  # TR — cyan
    QColor(255, 80, 80),  # BR — red
    QColor(255, 220, 0),  # BL — yellow
]
POINT_LABELS = ["TL", "TR", "BR", "BL"]
HANDLE_R = 10


# ── Custom view: items draggable, Ctrl+drag or middle-button pans ─────────────

class BevView(QGraphicsView):
    """QGraphicsView where items are always draggable.
    Pan with Ctrl+LMB or Middle Mouse Button.
    Zoom with Ctrl+Wheel.
    """

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        # RubberBandDrag lets click-through reach items; we handle pan manually
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._panning = False
        self._pan_start = QPointF()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier
        ):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setCursor(QCursor(Qt.ArrowCursor))
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ── Draggable point on the scene ──────────────────────────────────────────────

class DraggablePoint(QGraphicsEllipseItem):
    def __init__(self, idx: int, scene: "BevScene", color: QColor) -> None:
        super().__init__(-HANDLE_R, -HANDLE_R, HANDLE_R * 2, HANDLE_R * 2)
        self.idx = idx
        self.scene_ref = scene
        self.suppress = False   # when True, itemChange won't emit
        self.setBrush(color)
        self.setPen(QPen(Qt.white, 2))
        self.setFlags(
            QGraphicsEllipseItem.ItemIsMovable |
            QGraphicsEllipseItem.ItemSendsGeometryChanges
        )
        self.setZValue(10)
        self.setCursor(QCursor(Qt.SizeAllCursor))

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.ItemPositionHasChanged and not self.suppress:
            self.scene_ref.point_moved(self.idx, value)
        return super().itemChange(change, value)


# ── Scene ─────────────────────────────────────────────────────────────────────

class BevScene(QGraphicsScene):
    points_changed = pyqtSignal()
    cursor_moved = pyqtSignal(int, int)  # x, y in image coords

    def __init__(self, points: np.ndarray) -> None:
        super().__init__()
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._poly_lines: list[QGraphicsLineItem] = []          
        self._handles: list[DraggablePoint] = []
        self._points = points.copy()

    def mouseMoveEvent(self, event) -> None:
        pos = event.scenePos()
        self.cursor_moved.emit(int(pos.x()), int(pos.y()))
        super().mouseMoveEvent(event)

    def load_image(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        q_img = QImage(rgb.data.tobytes(), w, h, 3 * w, QImage.Format_RGB888)
        if self._pixmap_item:
            self.removeItem(self._pixmap_item)
        self._pixmap_item = self.addPixmap(QPixmap.fromImage(q_img))
        self._pixmap_item.setZValue(0)
        self.setSceneRect(0, 0, w, h)
        self._rebuild_handles()

    def set_points(self, points: np.ndarray) -> None:
        """Update all 4 points and redraw handles (used by spinboxes and paste)."""
        self._points = points.copy()
        for i, handle in enumerate(self._handles):
            handle.suppress = True
            handle.setPos(float(self._points[i][0]), float(self._points[i][1]))
            handle.suppress = False
        self._update_polygon()
        self.points_changed.emit()

    def get_points(self) -> np.ndarray:
        return self._points.copy()

    def point_moved(self, idx: int, pos: QPointF) -> None:
        """Called when a handle is dragged."""
        self._points[idx] = [pos.x(), pos.y()]
        self._update_polygon()
        self.points_changed.emit()

    def _rebuild_handles(self) -> None:
        for h in self._handles:
            self.removeItem(h)
        self._handles.clear()
        for line in self._poly_lines:
            self.removeItem(line)
        self._poly_lines.clear()

        for i, (pt, color) in enumerate(zip(self._points, POINT_COLORS)):
            handle = DraggablePoint(i, self, color)
            handle.setPos(float(pt[0]), float(pt[1]))
            self.addItem(handle)
            self._handles.append(handle)

        self._update_polygon()

    def _update_polygon(self) -> None:
        for line in self._poly_lines:
            self.removeItem(line)
        self._poly_lines.clear()

        pen = QPen(QColor(255, 255, 255), 2, Qt.DashLine)
        pts = self._points
        for i in range(4):
            p1, p2 = pts[i], pts[(i + 1) % 4]
            item = self.addLine(
                float(p1[0]), float(p1[1]),
                float(p2[0]), float(p2[1]),
                pen,
            )
            item.setZValue(5)
            self._poly_lines.append(item)


# ── BEV Tab ───────────────────────────────────────────────────────────────────

class BevTab(QWidget):
    def __init__(self, state: AppState, status_bar) -> None:
        super().__init__()
        self.state = state
        self.status_bar = status_bar
        self._block_spinbox_signals = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setSpacing(8)

        # ── Left column: scene + controls ────────────────────────────
        left = QVBoxLayout()

        left.addWidget(QLabel(
            "Drag the colored handles to set perspective corners  "
            "(TL · TR · BR · BL)"
        ))

        self.scene = BevScene(self.state.src_points)
        self.scene.points_changed.connect(self._on_scene_points_changed)
        self.scene.cursor_moved.connect(self._on_cursor_moved)
        
        self.orig_view = BevView(self.scene)
        left.addWidget(self.orig_view)
        
        self.cursor_label = QLabel("x: —   y: —")
        self.cursor_label.setStyleSheet("color: #aaa; font-family: monospace; font-size: 11px;")
        left.addWidget(self.cursor_label)

        # ── Spinbox grid: 4 points × X/Y ─────────────────────────────
        spin_group = QGroupBox("Coordinates (keyboard editable)")
        spin_grid = QVBoxLayout(spin_group)

        self._x_spins: list[QSpinBox] = []
        self._y_spins: list[QSpinBox] = []

        for i in range(4):
            row = QHBoxLayout()
            color_label = QLabel(f"● {POINT_LABELS[i]}")
            color_label.setStyleSheet(
                f"color: {POINT_COLORS[i].name()}; font-weight: bold; min-width: 36px;"
            )
            row.addWidget(color_label)

            row.addWidget(QLabel("X:"))
            sx = QSpinBox()
            sx.setRange(-9999, 9999)
            sx.setValue(int(self.state.src_points[i][0]))
            sx.setFixedWidth(80)
            sx.valueChanged.connect(lambda _, idx=i: self._on_spin_changed(idx))
            row.addWidget(sx)
            self._x_spins.append(sx)

            row.addWidget(QLabel("Y:"))
            sy = QSpinBox()
            sy.setRange(-9999, 9999)
            sy.setValue(int(self.state.src_points[i][1]))
            sy.setFixedWidth(80)
            sy.valueChanged.connect(lambda _, idx=i: self._on_spin_changed(idx))
            row.addWidget(sy)
            self._y_spins.append(sy)

            row.addStretch()
            spin_grid.addLayout(row)

        left.addWidget(spin_group)

        # ── BEV output size ───────────────────────────────────────────
        size_group = QGroupBox("BEV Output Size")
        size_row = QHBoxLayout(size_group)
        size_row.addWidget(QLabel("Width:"))
        self.bev_w_spin = QSpinBox()
        self.bev_w_spin.setRange(400, 4000)
        self.bev_w_spin.setValue(self.state.bev_width)
        self.bev_w_spin.setSingleStep(50)
        self.bev_w_spin.valueChanged.connect(self._update_bev)
        size_row.addWidget(self.bev_w_spin)
        size_row.addWidget(QLabel("Height:"))
        self.bev_h_spin = QSpinBox()
        self.bev_h_spin.setRange(400, 4000)
        self.bev_h_spin.setValue(self.state.bev_height)
        self.bev_h_spin.setSingleStep(50)
        self.bev_h_spin.valueChanged.connect(self._update_bev)
        size_row.addWidget(self.bev_h_spin)
        size_row.addStretch()
        left.addWidget(size_group)

        root.addLayout(left, 3)

        # ── Right column: paste + BEV preview ────────────────────────
        right = QVBoxLayout()

        # Paste box
        paste_group = QGroupBox("Paste / Copy coordinates")
        paste_layout = QVBoxLayout(paste_group)
        paste_layout.addWidget(QLabel(
            "Paste np.float32([...]) or [[x,y],[x,y],...] and click Apply:"
        ))
        self.paste_edit = QTextEdit()
        self.paste_edit.setFixedHeight(100)
        self.paste_edit.setPlaceholderText(
            "[[-172, -86],\n [2062, 414],\n [3040, 1079],\n [746, 1258]]"
        )
        self.paste_edit.setStyleSheet("font-family: monospace; font-size: 12px;")
        paste_layout.addWidget(self.paste_edit)

        paste_btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply_paste)
        copy_btn = QPushButton("Copy current")
        copy_btn.clicked.connect(self._copy_current)
        paste_btn_row.addWidget(apply_btn)
        paste_btn_row.addWidget(copy_btn)
        paste_btn_row.addStretch()
        paste_layout.addLayout(paste_btn_row)

        right.addWidget(paste_group)

        # BEV preview
        right.addWidget(QLabel("Bird's Eye View preview"))
        self.bev_label = QLabel("No frame loaded")
        self.bev_label.setAlignment(Qt.AlignCenter)
        self.bev_label.setStyleSheet("background: #1e1e1e; color: #888;")
        self.bev_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right.addWidget(self.bev_label)

        export_btn = QPushButton("Export BEV image…")
        export_btn.clicked.connect(self._export_bev)
        right.addWidget(export_btn)

        root.addLayout(right, 2)

    # ── Activation ────────────────────────────────────────────────────

    def on_activate(self) -> None:
        if self.state.frame is not None and self.scene._pixmap_item is None:
            self.scene.load_image(self.state.frame)
            self.orig_view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self._update_bev()

    # ── Signal handlers ───────────────────────────────────────────────

    def _on_cursor_moved(self, x: int, y: int) -> None:
        self.cursor_label.setText(f"x: {x}   y: {y}")
    
    def _on_scene_points_changed(self) -> None:
        """Handles dragged — sync spinboxes then update BEV."""
        pts = self.scene.get_points()
        self._block_spinbox_signals = True
        for i in range(4):
            self._x_spins[i].setValue(int(pts[i][0]))
            self._y_spins[i].setValue(int(pts[i][1]))
        self._block_spinbox_signals = False
        self._update_bev()

    def _on_spin_changed(self, idx: int) -> None:
        """Spinbox edited — sync scene handles then update BEV."""
        if self._block_spinbox_signals:
            return
        pts = self.scene.get_points()
        pts[idx][0] = self._x_spins[idx].value()
        pts[idx][1] = self._y_spins[idx].value()
        self.scene.set_points(pts)
        self._update_bev()

    # ── Paste / copy ─────────────────────────────────────────────────

    def _apply_paste(self) -> None:
        text = self.paste_edit.toPlainText().strip()
        pts = self._parse_points(text)
        if pts is None:
            QMessageBox.warning(
                self,
                "Parse error",
                "Could not parse coordinates.\n\n"
                "Expected format:\n"
                "[[-172, -86], [2062, 414], [3040, 1079], [746, 1258]]",
            )
            return
        self._apply_points(pts)
        self.status_bar.showMessage("Points applied from paste")

    def _copy_current(self) -> None:
        pts = self.scene.get_points()
        lines = [f"    [{int(x)}, {int(y)}]" for x, y in pts]
        text = "np.float32([\n" + ",\n".join(lines) + "\n])"
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        self.paste_edit.setPlainText(text)
        self.status_bar.showMessage("Copied to clipboard")

    @staticmethod
    def _parse_points(text: str) -> np.ndarray | None:
        """Parse any reasonable coordinate format into a (4, 2) float32 array."""
        # Strip Python wrappers: np.float32(...), array([...]), etc.
        text = re.sub(r"np\.float\d*\s*\(", "", text)
        text = re.sub(r"array\s*\(", "", text)
        text = text.replace(")", "")

        # Extract all numbers (int or float, possibly negative)
        numbers = re.findall(r"-?\d+(?:\.\d+)?", text)
        if len(numbers) != 8:
            return None
        try:
            flat = [float(n) for n in numbers]
            return np.float32(flat).reshape(4, 2)
        except ValueError:
            return None

    def _apply_points(self, pts: np.ndarray) -> None:
        self._block_spinbox_signals = True
        for i in range(4):
            self._x_spins[i].setValue(int(pts[i][0]))
            self._y_spins[i].setValue(int(pts[i][1]))
        self._block_spinbox_signals = False
        self.scene.set_points(pts)
        self._update_bev()

    # ── BEV rendering ─────────────────────────────────────────────────

    def _update_bev(self) -> None:
        if self.state.frame is None:
            return

        pts = self.scene.get_points().astype(np.float32)
        self.state.src_points = pts

        bev_w = self.bev_w_spin.value()
        bev_h = self.bev_h_spin.value()
        self.state.bev_width = bev_w
        self.state.bev_height = bev_h

        dst = np.float32([[0, 0], [bev_w, 0], [bev_w, bev_h], [0, bev_h]])
        M = cv2.getPerspectiveTransform(pts, dst)
        self.state.bev_matrix = M
        bev = cv2.warpPerspective(self.state.frame, M, (bev_w, bev_h))
        self.state.bev_image = bev

        lw = max(1, self.bev_label.width())
        lh = max(1, self.bev_label.height())
        scale = min(lw / bev_w, lh / bev_h, 1.0)
        dw, dh = max(1, int(bev_w * scale)), max(1, int(bev_h * scale))
        rgb = cv2.cvtColor(cv2.resize(bev, (dw, dh)), cv2.COLOR_BGR2RGB)
        q_img = QImage(rgb.data.tobytes(), dw, dh, 3 * dw, QImage.Format_RGB888)
        self.bev_label.setPixmap(QPixmap.fromImage(q_img))

    # ── Export ────────────────────────────────────────────────────────

    def _export_bev(self) -> None:
        if self.state.bev_image is None:
            self.status_bar.showMessage("No BEV to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save BEV Image", "bev.png", "PNG (*.png);;JPEG (*.jpg)"
        )
        if path:
            cv2.imwrite(path, self.state.bev_image)
            self.status_bar.showMessage(f"Saved: {path}")
