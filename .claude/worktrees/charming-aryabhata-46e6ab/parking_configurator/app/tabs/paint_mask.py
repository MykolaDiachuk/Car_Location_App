"""Reusable paint tab for binary and color masks.

Used for:
  - Parking Mask (grayscale: white=allowed, black=forbidden)
  - Orientation Zones (color: green=parallel, blue=perpendicular, black=none)
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QPointF, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox, QFileDialog, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from app.state import AppState


# ── Brush colors (BGR for cv2) ────────────────────────────────────────────────

BGR_WHITE = (255, 255, 255)
BGR_BLACK = (0, 0, 0)
BGR_GREEN = (0, 255, 0)
BGR_BLUE = (255, 0, 0)


# ── Mode config ──────────────────────────────────────────────────────────────

@dataclass
class BrushConfig:
    name: str
    color_bgr: tuple[int, int, int]
    display_color: str      # CSS color for button
    text_color: str
    key_hint: str


PARKING_MASK_BRUSHES = [
    BrushConfig("Allow (LMB)", BGR_WHITE, "#00CC00", "black", "LMB"),
    BrushConfig("Forbid (RMB)", BGR_BLACK, "#CC0000", "white", "RMB"),
]

ORIENTATION_BRUSHES = [
    BrushConfig("Parallel (LMB)", BGR_GREEN, "#00CC00", "black", "LMB"),
    BrushConfig("Perpendicular (RMB)", BGR_BLUE, "#0000CC", "white", "RMB"),
    BrushConfig("Clear (C)", BGR_BLACK, "#333333", "white", "C"),
]


MaskType = Literal["parking", "orientation"]


# ── View with pan/zoom ───────────────────────────────────────────────────────

class MaskView(QGraphicsView):
    """Pan: Ctrl+LMB / MMB.  Zoom: Ctrl+Wheel.  Draw: LMB/RMB directly."""

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._panning = False
        self._pan_start = QPointF()

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            f = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(f, f)
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
            d = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
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


# ── Paint scene ──────────────────────────────────────────────────────────────

class PaintScene(QGraphicsScene):
    cursor_moved = pyqtSignal(int, int)

    def __init__(self, w: int, h: int) -> None:
        super().__init__(0, 0, w, h)
        self.canvas_w = w
        self.canvas_h = h
        self._pixmap_item: QGraphicsPixmapItem | None = None

    def set_pixmap(self, pixmap: QPixmap) -> None:
        if self._pixmap_item:
            self.removeItem(self._pixmap_item)
        self._pixmap_item = self.addPixmap(pixmap)
        self._pixmap_item.setZValue(0)

    def mouseMoveEvent(self, event) -> None:
        p = event.scenePos()
        self.cursor_moved.emit(int(p.x()), int(p.y()))
        super().mouseMoveEvent(event)


# ── PaintTab ─────────────────────────────────────────────────────────────────

class PaintTab(QWidget):
    """Brush-paint tab for mask editing with BEV overlay."""

    def __init__(
        self,
        state: AppState,
        status_bar,
        mask_type: MaskType,
    ) -> None:
        super().__init__()
        self.state = state
        self.status_bar = status_bar
        self.mask_type = mask_type

        self._is_parking = mask_type == "parking"
        self._brushes = PARKING_MASK_BRUSHES if self._is_parking else ORIENTATION_BRUSHES
        self._active_color = self._brushes[0].color_bgr

        self._brush_size = 20 if self._is_parking else 30
        self._drawing = False
        self._bev_opacity = 0.45

        # Mask data — initialized empty, loaded later
        self._mask: np.ndarray | None = None
        self._original_mask: np.ndarray | None = None

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Sidebar ───────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(240)
        sidebar.setStyleSheet("background: #252535;")
        sb = QVBoxLayout(sidebar)
        sb.setSpacing(6)
        sb.setContentsMargins(8, 8, 8, 8)

        # Brushes
        bg = QGroupBox("Brush")
        bl = QVBoxLayout(bg)

        for brush in self._brushes:
            btn = QPushButton(f"{brush.name}")
            btn.setStyleSheet(
                f"background-color: {brush.display_color}; "
                f"color: {brush.text_color}; font-weight: bold;"
            )
            btn.clicked.connect(lambda _, b=brush: self._set_brush(b))
            bl.addWidget(btn)

        bl.addSpacing(8)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size:"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(3, 150)
        self.size_slider.setValue(self._brush_size)
        self.size_slider.valueChanged.connect(self._on_size)
        size_row.addWidget(self.size_slider)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(3, 150)
        self.size_spin.setValue(self._brush_size)
        self.size_spin.valueChanged.connect(self._on_size_spin)
        size_row.addWidget(self.size_spin)
        bl.addLayout(size_row)

        sb.addWidget(bg)

        # View
        vg = QGroupBox("View")
        vl = QVBoxLayout(vg)

        self.bev_check = QCheckBox("Show BEV overlay")
        self.bev_check.setChecked(True)
        self.bev_check.toggled.connect(lambda _: self._refresh())
        vl.addWidget(self.bev_check)

        op = QHBoxLayout()
        op.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self._bev_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        op.addWidget(self.opacity_slider)
        vl.addLayout(op)

        sb.addWidget(vg)

        # Actions
        ag = QGroupBox("Actions")
        al = QVBoxLayout(ag)

        import_btn = QPushButton("Import from file…")
        import_btn.clicked.connect(self._import_mask)
        al.addWidget(import_btn)

        reset_btn = QPushButton("Reset to imported")
        reset_btn.clicked.connect(self._reset)
        al.addWidget(reset_btn)

        clear_btn = QPushButton("Clear all")
        clear_btn.setStyleSheet("color: #ff6666;")
        clear_btn.clicked.connect(self._clear)
        al.addWidget(clear_btn)

        sb.addWidget(ag)

        # Info
        self.coord_label = QLabel("x: —  y: —")
        self.coord_label.setStyleSheet("color: #aaa; font-family: monospace; font-size: 11px;")
        sb.addWidget(self.coord_label)

        sb.addStretch()

        # Export
        xg = QGroupBox("Export")
        xl = QVBoxLayout(xg)

        download_btn = QPushButton("Download mask…")
        download_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold; padding: 6px;"
        )
        download_btn.clicked.connect(self._export)
        xl.addWidget(download_btn)

        sb.addWidget(xg)

        # Hint
        hint = "LMB — allow   RMB — forbid" if self._is_parking else \
               "LMB — parallel   RMB — perpendicular   C — clear"
        hint_label = QLabel(hint)
        hint_label.setStyleSheet("color: #888; font-size: 10px;")
        hint_label.setWordWrap(True)
        sb.addWidget(hint_label)

        root.addWidget(sidebar)

        # ── Canvas ────────────────────────────────────────────────────
        bw, bh = self.state.bev_width, self.state.bev_height
        self.scene = PaintScene(bw, bh)
        self.scene.cursor_moved.connect(self._on_cursor)

        self.view = MaskView(self.scene)
        root.addWidget(self.view)

    # ── Activation ────────────────────────────────────────────────────

    def on_activate(self) -> None:
        bw, bh = self.state.bev_width, self.state.bev_height

        # Resize mask if BEV dimensions changed
        if self._mask is not None and (self._mask.shape[1] != bw or self._mask.shape[0] != bh):
            interp = cv2.INTER_NEAREST
            if self._is_parking:
                self._mask = cv2.resize(self._mask, (bw, bh), interpolation=interp)
            else:
                self._mask = cv2.resize(self._mask, (bw, bh), interpolation=interp)
            self._original_mask = self._mask.copy()

        # Init blank mask if never created
        if self._mask is None:
            self._init_blank_mask(bw, bh)

        self.scene.canvas_w = bw
        self.scene.canvas_h = bh
        self.scene.setSceneRect(0, 0, bw, bh)
        self._refresh()

    def _init_blank_mask(self, w: int, h: int) -> None:
        if self._is_parking:
            self._mask = np.zeros((h, w), dtype=np.uint8)
        else:
            self._mask = np.zeros((h, w, 3), dtype=np.uint8)
        self._original_mask = self._mask.copy()

    # ── Brush ─────────────────────────────────────────────────────────

    def _set_brush(self, brush: BrushConfig) -> None:
        self._active_color = brush.color_bgr
        self.status_bar.showMessage(f"Brush: {brush.name}")

    def _on_size(self, val: int) -> None:
        self._brush_size = val
        self.size_spin.blockSignals(True)
        self.size_spin.setValue(val)
        self.size_spin.blockSignals(False)

    def _on_size_spin(self, val: int) -> None:
        self._brush_size = val
        self.size_slider.blockSignals(True)
        self.size_slider.setValue(val)
        self.size_slider.blockSignals(False)

    def _on_opacity(self, val: int) -> None:
        self._bev_opacity = val / 100
        self._refresh()

    def _on_cursor(self, x: int, y: int) -> None:
        self.coord_label.setText(f"x: {x}  y: {y}")

    # ── Drawing ───────────────────────────────────────────────────────

    def _scene_to_mask(self, scene_pos: QPointF) -> tuple[int, int]:
        return int(scene_pos.x()), int(scene_pos.y())

    def _paint_at(self, x: int, y: int) -> None:
        if self._mask is None:
            return
        h, w = self._mask.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            if self._is_parking:
                gray = 255 if self._active_color == BGR_WHITE else 0
                cv2.circle(self._mask, (x, y), self._brush_size, gray, -1)
            else:
                cv2.circle(self._mask, (x, y), self._brush_size, self._active_color, -1)
            self._refresh()

    def _map_event_to_scene(self, event) -> QPointF:
        return self.view.mapToScene(event.pos())

    # Override mouse events on view
    def _install_mouse_handlers(self) -> None:
        """Connect mouse handling on the view (called once after view exists)."""
        self.view.mousePressEvent = self._view_mouse_press
        self.view.mouseMoveEvent = self._view_mouse_move
        self.view.mouseReleaseEvent = self._view_mouse_release

    def _view_mouse_press(self, event) -> None:
        # Pan
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier
        ):
            MaskView.mousePressEvent(self.view, event)
            return
        # Draw
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self._drawing = True
            if event.button() == Qt.RightButton:
                self._active_color = self._brushes[1].color_bgr
            elif not (event.modifiers() & Qt.ControlModifier):
                self._active_color = self._brushes[0].color_bgr
            sp = self.view.mapToScene(event.pos())
            self._paint_at(int(sp.x()), int(sp.y()))
            event.accept()

    def _view_mouse_move(self, event) -> None:
        if self.view._panning:
            MaskView.mouseMoveEvent(self.view, event)
            return
        if self._drawing:
            sp = self.view.mapToScene(event.pos())
            self._paint_at(int(sp.x()), int(sp.y()))
            event.accept()
            return
        # Update cursor coord
        sp = self.view.mapToScene(event.pos())
        self.scene.cursor_moved.emit(int(sp.x()), int(sp.y()))

    def _view_mouse_release(self, event) -> None:
        if self.view._panning:
            MaskView.mouseReleaseEvent(self.view, event)
            return
        self._drawing = False

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_C and not self._is_parking:
            self._active_color = BGR_BLACK
            self.status_bar.showMessage("Brush: Clear")
        else:
            super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._install_mouse_handlers()

    # ── Render composite ──────────────────────────────────────────────

    def _refresh(self) -> None:
        if self._mask is None:
            return
        bw, bh = self.scene.canvas_w, self.scene.canvas_h

        # Build overlay from mask
        if self._is_parking:
            overlay = np.zeros((bh, bw, 3), dtype=np.uint8)
            overlay[self._mask == 255] = (0, 200, 0)    # allowed = green
            overlay[self._mask == 0] = (0, 0, 200)      # forbidden = red
        else:
            overlay = np.zeros((bh, bw, 3), dtype=np.uint8)
            g_mask = (self._mask[:, :, 1] > 200) & (self._mask[:, :, 0] < 50)
            b_mask = (self._mask[:, :, 0] > 200) & (self._mask[:, :, 1] < 50)
            overlay[g_mask] = (0, 200, 0)
            overlay[b_mask] = (200, 0, 0)

        # Composite with BEV
        if self.bev_check.isChecked() and self.state.bev_image is not None:
            bev = cv2.resize(self.state.bev_image, (bw, bh))
            alpha = self._bev_opacity
            composite = cv2.addWeighted(bev, alpha, overlay, 1.0 - alpha, 0)
        else:
            composite = overlay

        rgb = cv2.cvtColor(composite, cv2.COLOR_BGR2RGB)
        q_img = QImage(rgb.data.tobytes(), bw, bh, 3 * bw, QImage.Format_RGB888)
        self.scene.set_pixmap(QPixmap.fromImage(q_img))

    # ── Actions ───────────────────────────────────────────────────────

    def _import_mask(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Mask", "", "Images (*.png *.jpg *.bmp)"
        )
        if not path:
            return
        bw, bh = self.scene.canvas_w, self.scene.canvas_h
        if self._is_parking:
            raw = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if raw is None:
                self.status_bar.showMessage("Failed to read file")
                return
            self._mask = cv2.resize(raw, (bw, bh), interpolation=cv2.INTER_NEAREST)
        else:
            raw = cv2.imread(path, cv2.IMREAD_COLOR)
            if raw is None:
                self.status_bar.showMessage("Failed to read file")
                return
            self._mask = cv2.resize(raw, (bw, bh), interpolation=cv2.INTER_NEAREST)
        self._original_mask = self._mask.copy()
        self._refresh()
        self.status_bar.showMessage(f"Imported: {path}")

    def _reset(self) -> None:
        if self._original_mask is not None:
            self._mask = self._original_mask.copy()
            self._refresh()
            self.status_bar.showMessage("Reset to imported state")

    def _clear(self) -> None:
        bw, bh = self.scene.canvas_w, self.scene.canvas_h
        self._init_blank_mask(bw, bh)
        self._refresh()
        self.status_bar.showMessage("Cleared")

    def _export(self) -> None:
        if self._mask is None:
            self.status_bar.showMessage("Nothing to export")
            return
        default_name = "parking_mask.png" if self._is_parking else "orientation_zones.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Mask", default_name, "PNG (*.png)"
        )
        if path:
            cv2.imwrite(path, self._mask)
            self.status_bar.showMessage(f"Saved: {path}")
