"""Map Builder tab — draw parking spots and borders, export SVG + JSON."""
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import (
    QBrush, QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap,
    QImage, QPolygonF, QTransform,
)
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem,
    QGraphicsPolygonItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsTextItem, QGraphicsView, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QShortcut, QSizePolicy, QSlider, QSpinBox,
    QVBoxLayout, QWidget,
)
from PyQt5.QtGui import QKeySequence

from app.state import AppState

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_SPOT_W = 60
DEFAULT_SPOT_H = 110
RESIZE_HANDLE_SIZE = 8
BORDER_PEN_WIDTH = 4
GRID_STEP = 40

COLOR_FREE = QColor(80, 200, 80, 160)
COLOR_SPOT_BORDER = QColor(255, 255, 255)
COLOR_RESIZE_HANDLE = QColor(255, 180, 0)
COLOR_BORDER_SELECTED = QColor(255, 100, 100, 220)
COLOR_BORDER_SHAPE = QColor(60, 60, 220, 180)
COLOR_GRID = QColor(80, 80, 80, 80)
COLOR_BG = QColor(30, 30, 30)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class SpotData:
    id: str
    label: str
    orientation: Literal["parallel", "perpendicular"]
    x: float
    y: float
    w: float
    h: float
    angle: float


@dataclass
class BorderPoint:
    x: float
    y: float


@dataclass
class BorderShape:
    id: str
    points: list[BorderPoint] = field(default_factory=list)
    closed: bool = False


# ── Resize handle ─────────────────────────────────────────────────────────────

class ResizeHandle(QGraphicsRectItem):
    """Corner handle for resizing a SpotItem."""

    S = RESIZE_HANDLE_SIZE

    def __init__(self, corner: str, parent: "SpotItem") -> None:
        super().__init__(-self.S / 2, -self.S / 2, self.S, self.S, parent)
        self.corner = corner
        self.spot = parent
        self.setBrush(QBrush(COLOR_RESIZE_HANDLE))
        self.setPen(QPen(Qt.black, 1))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setCursor(QCursor(Qt.SizeFDiagCursor if corner in ("tl", "br") else Qt.SizeBDiagCursor))
        self.setZValue(20)
        self._dragging = False

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return super().mouseMoveEvent(event)

        pos = event.pos() + self.pos()
        d = self.spot.data
        hw, hh = d.w / 2, d.h / 2

        MIN_SIZE = 16

        if self.corner == "br":
            new_w = max(MIN_SIZE, pos.x() * 2)
            new_h = max(MIN_SIZE, pos.y() * 2)
        elif self.corner == "bl":
            new_w = max(MIN_SIZE, -pos.x() * 2)
            new_h = max(MIN_SIZE, pos.y() * 2)
        elif self.corner == "tr":
            new_w = max(MIN_SIZE, pos.x() * 2)
            new_h = max(MIN_SIZE, -pos.y() * 2)
        else:  # tl
            new_w = max(MIN_SIZE, -pos.x() * 2)
            new_h = max(MIN_SIZE, -pos.y() * 2)

        self.spot.apply_size(new_w, new_h)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        self.spot.scene_ref.selection_changed_detail.emit(self.spot)
        super().mouseReleaseEvent(event)


# ── SpotItem ──────────────────────────────────────────────────────────────────

class SpotItem(QGraphicsRectItem):
    """Parking spot — movable, resizable, rotatable."""

    def __init__(self, data: SpotData, scene: "MapScene") -> None:
        super().__init__(-data.w / 2, -data.h / 2, data.w, data.h)
        self.data = data
        self.scene_ref = scene

        self.setPos(data.x, data.y)
        self.setRotation(data.angle)
        self.setBrush(QBrush(COLOR_FREE))
        self.setPen(QPen(COLOR_SPOT_BORDER, 2))
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(2)
        self.setCursor(QCursor(Qt.SizeAllCursor))

        self._label = QGraphicsTextItem(data.label, self)
        self._label.setDefaultTextColor(Qt.white)
        self._update_font()
        self._center_label()

        self._handles = self._create_handles()
        self._set_handles_visible(False)

    def _create_handles(self) -> list[ResizeHandle]:
        handles = []
        for c in ("tl", "tr", "bl", "br"):
            handles.append(ResizeHandle(c, self))
        self._handles = handles
        self._position_handles()
        return handles

    def _position_handles(self) -> None:
        w2, h2 = self.data.w / 2, self.data.h / 2
        positions = {"tl": (-w2, -h2), "tr": (w2, -h2), "bl": (-w2, h2), "br": (w2, h2)}
        for h in self._handles:
            px, py = positions[h.corner]
            h.setPos(px, py)

    def _set_handles_visible(self, visible: bool) -> None:
        for h in self._handles:
            h.setVisible(visible)

    def _update_font(self) -> None:
        font = QFont("Arial", max(8, int(min(self.data.w, self.data.h) / 5)))
        font.setBold(True)
        self._label.setFont(font)

    def _center_label(self) -> None:
        br = self._label.boundingRect()
        self._label.setPos(-br.width() / 2, -br.height() / 2)

    def update_label(self, text: str) -> None:
        self.data.label = text
        self._label.setPlainText(text)
        self._center_label()

    def apply_size(self, w: float, h: float) -> None:
        self.data.w, self.data.h = w, h
        self.setRect(-w / 2, -h / 2, w, h)
        self._position_handles()
        self._update_font()
        self._center_label()

    def update_geometry(self, w: float, h: float, angle: float) -> None:
        self.data.angle = angle
        self.setRotation(angle)
        self.apply_size(w, h)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.data.x = value.x()
            self.data.y = value.y()
            self.scene_ref.item_changed()
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self._set_handles_visible(bool(value))
        return super().itemChange(change, value)


# ── Border items ──────────────────────────────────────────────────────────────

class BorderVertex(QGraphicsEllipseItem):
    R = 7

    def __init__(self, idx: int, shape_item: "BorderShapeItem") -> None:
        super().__init__(-self.R, -self.R, self.R * 2, self.R * 2)
        self.idx = idx
        self.shape_item = shape_item
        self.setBrush(QBrush(COLOR_BORDER_SHAPE))
        self.setPen(QPen(Qt.white, 1))
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setCursor(QCursor(Qt.SizeAllCursor))
        self.setZValue(5)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.shape_item.vertex_moved(self.idx, value)
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            # When a vertex is selected, select the whole shape
            if value:
                self.shape_item.set_selected(True)
        return super().itemChange(change, value)


class BorderShapeItem:
    def __init__(self, data: BorderShape, scene: "MapScene") -> None:
        self.data = data
        self.scene_ref = scene
        self._poly: QGraphicsPolygonItem | QGraphicsPathItem | None = None
        self._vertices: list[BorderVertex] = []
        self._selected = False
        self._rebuild()

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, value: bool) -> None:
        self._selected = value
        self._apply_selection_style()
        # Sync all vertices
        for v in self._vertices:
            v.setSelected(value)
        # Notify scene so sidebar can react
        self.scene_ref.border_selection_changed.emit(self if value else None)

    def _apply_selection_style(self) -> None:
        if self._poly is None:
            return
        pen = QPen(
            COLOR_BORDER_SELECTED if self._selected else COLOR_BORDER_SHAPE,
            BORDER_PEN_WIDTH + (2 if self._selected else 0),
        )
        pen.setStyle(Qt.SolidLine if self.data.closed else Qt.DashLine)
        self._poly.setPen(pen)

    def _rebuild(self) -> None:
        self._remove_from_scene()
        pen = QPen(
            COLOR_BORDER_SELECTED if self._selected else COLOR_BORDER_SHAPE,
            BORDER_PEN_WIDTH + (2 if self._selected else 0),
        )
        pen.setStyle(Qt.SolidLine if self.data.closed else Qt.DashLine)
    
        if self.data.closed:
            poly = QPolygonF([QPointF(p.x, p.y) for p in self.data.points])
            self._poly = self.scene_ref.addPolygon(poly, pen, QBrush(QColor(60, 60, 220, 40)))
        else:
            path = QPainterPath()
            pts = self.data.points
            if pts:
                path.moveTo(pts[0].x, pts[0].y)
                for p in pts[1:]:
                    path.lineTo(p.x, p.y)
            self._poly = self.scene_ref.addPath(path, pen)
    
        if self._poly:
            self._poly.setZValue(1)
            # Make polygon itself clickable to select the shape
            self._poly.setFlags(
                QGraphicsItem.ItemIsSelectable
            )
            self._poly.setData(0, id(self))  # store identity for hit-test
    
        for i, pt in enumerate(self.data.points):
            v = BorderVertex(i, self)
            v.setPos(pt.x, pt.y)
            self.scene_ref.addItem(v)
            self._vertices.append(v)

    def _remove_from_scene(self) -> None:
        if self._poly and self._poly.scene():
            self.scene_ref.removeItem(self._poly)
        self._poly = None
        for v in self._vertices:
            if v.scene():
                self.scene_ref.removeItem(v)
        self._vertices.clear()

    def add_point(self, x: float, y: float) -> None:
        self.data.points.append(BorderPoint(x, y))
        self._rebuild()

    def close_shape(self) -> None:
        self.data.closed = True
        self._rebuild()

    def vertex_moved(self, idx: int, pos: QPointF) -> None:
        self.data.points[idx].x = pos.x()
        self.data.points[idx].y = pos.y()
        self._update_shape()

    def _update_shape(self) -> None:
        if self._poly is None:
            return
        if self.data.closed and isinstance(self._poly, QGraphicsPolygonItem):
            self._poly.setPolygon(QPolygonF([QPointF(p.x, p.y) for p in self.data.points]))
        elif not self.data.closed and isinstance(self._poly, QGraphicsPathItem):
            path = QPainterPath()
            pts = self.data.points
            if pts:
                path.moveTo(pts[0].x, pts[0].y)
                for p in pts[1:]:
                    path.lineTo(p.x, p.y)
                self._poly.setPath(path)

    def remove(self) -> None:
        self._remove_from_scene()

    def undo_last_point(self) -> None:
        if self.data.points:
            self.data.points.pop()
            self._rebuild()


# ── Custom View ───────────────────────────────────────────────────────────────

class MapView(QGraphicsView):
    """Pan: Ctrl+LMB or MMB.  Zoom: Ctrl+Wheel.  Otherwise clicks go to items/scene."""

    def __init__(self, scene: QGraphicsScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setStyleSheet("border: none;")
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


# ── Scene ─────────────────────────────────────────────────────────────────────

class MapScene(QGraphicsScene):
    selection_changed_detail = pyqtSignal(object)  # SpotItem | None
    border_selection_changed = pyqtSignal(object)  # BorderShapeItem | None
    cursor_pos = pyqtSignal(int, int)

    clipboard_changed = pyqtSignal(bool)  # has_clipboard

    MODE_SELECT = "select"
    MODE_ADD_SPOT = "add_spot"
    MODE_DRAW_BORDER = "draw_border"

    def __init__(self, w: int, h: int) -> None:
        super().__init__(0, 0, w, h)
        self.canvas_w = w
        self.canvas_h = h
        self.mode = self.MODE_SELECT
        self.spot_defaults: dict = {
            "w": DEFAULT_SPOT_W, "h": DEFAULT_SPOT_H,
            "orientation": "perpendicular", "angle": 0.0,
        }

        self._spots: list[SpotItem] = []
        self._spot_clipboard: SpotData | None = None
        self._borders: list[BorderShapeItem] = []
        self._active_border: BorderShapeItem | None = None
        self._bev_item: QGraphicsPixmapItem | None = None
        self._grid_items: list = []
        self._show_grid = True
        self._spot_counter = 1

        self.setBackgroundBrush(QBrush(COLOR_BG))
        self._draw_grid()
        self.selectionChanged.connect(self._on_selection)

    # ── Grid ──────────────────────────────────────────────────────────

    def _draw_grid(self) -> None:
        for item in self._grid_items:
            if item.scene():
                self.removeItem(item)
        self._grid_items.clear()
        if not self._show_grid:
            return
        pen = QPen(COLOR_GRID, 1)
        for x in range(0, int(self.canvas_w) + 1, GRID_STEP):
            self._grid_items.append(self.addLine(x, 0, x, self.canvas_h, pen))
        for y in range(0, int(self.canvas_h) + 1, GRID_STEP):
            self._grid_items.append(self.addLine(0, y, self.canvas_w, y, pen))
        for item in self._grid_items:
            item.setZValue(-1)

    def toggle_grid(self, visible: bool) -> None:
        self._show_grid = visible
        self._draw_grid()

    # ── BEV overlay ───────────────────────────────────────────────────

    def set_bev(self, bev: np.ndarray, opacity: float) -> None:
        if self._bev_item and self._bev_item.scene():
            self.removeItem(self._bev_item)
            self._bev_item = None
        rgb = cv2.cvtColor(bev, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        q_img = QImage(rgb.data.tobytes(), w, h, 3 * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(q_img).scaled(
            int(self.canvas_w), int(self.canvas_h), Qt.IgnoreAspectRatio, Qt.SmoothTransformation
        )
        self._bev_item = self.addPixmap(pix)
        self._bev_item.setOpacity(opacity)
        self._bev_item.setZValue(0)
        self._bev_item.setFlag(QGraphicsItem.ItemIsMovable, False)

    def toggle_bev(self, visible: bool) -> None:
        if self._bev_item:
            self._bev_item.setVisible(visible)

    def set_bev_opacity(self, opacity: float) -> None:
        if self._bev_item:
            self._bev_item.setOpacity(opacity)

    # ── Resize canvas ─────────────────────────────────────────────────

    def resize_canvas(self, w: int, h: int) -> None:
        self.canvas_w = w
        self.canvas_h = h
        self.setSceneRect(0, 0, w, h)
        self._draw_grid()

    # ── Modes ─────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode != self.MODE_DRAW_BORDER:
            self._active_border = None

    def start_border(self) -> None:
        data = BorderShape(id=str(uuid.uuid4()))
        shape = BorderShapeItem(data, self)
        self._borders.append(shape)
        self._active_border = shape
        self.mode = self.MODE_DRAW_BORDER

    def close_active_border(self) -> None:
        if self._active_border:
            self._active_border.close_shape()
            self._active_border = None
            self.mode = self.MODE_SELECT

    def undo_border_point(self) -> None:
        if self._active_border:
            self._active_border.undo_last_point()

    # ── Spots ─────────────────────────────────────────────────────────

    def next_label(self) -> str:
        label = str(self._spot_counter)
        self._spot_counter += 1
        return label
    
    def add_spot_at(self, x: float, y: float) -> SpotItem:
        d = self.spot_defaults
        data = SpotData(
            id=str(uuid.uuid4()),
            label=self.next_label(),
            orientation=d["orientation"],
            x=x, y=y,
            w=d["w"], h=d["h"],
            angle=d["angle"],
        )
        item = SpotItem(data, self)
        self.addItem(item)
        self._spots.append(item)
        return item
    
    def copy_selected_spot(self) -> None:
        spot = next((i for i in self.selectedItems() if isinstance(i, SpotItem)), None)
        if spot is None:
            return
        d = spot.data
        self._spot_clipboard = SpotData(
            id="",
            label="",
            orientation=d.orientation,
            x=0,
            y=0,
            w=d.w,
            h=d.h,
            angle=d.angle,
        )
        self.clipboard_changed.emit(True)
    
    def paste_spot(self, x: float, y: float) -> SpotItem | None:
        if self._spot_clipboard is None:
            return None
        c = self._spot_clipboard
        data = SpotData(
            id=str(uuid.uuid4()),
            label=self.next_label(),
            orientation=c.orientation,
            x=x,
            y=y,
            w=c.w,
            h=c.h,
            angle=c.angle,
        )
        item = SpotItem(data, self)
        self.addItem(item)
        self._spots.append(item)
        self.clearSelection()
        item.setSelected(True)
        return item
    
    def has_spot_clipboard(self) -> bool:
        return self._spot_clipboard is not None

    def delete_selected(self) -> None:
        """Delete selected spots and/or selected border shapes."""
        for item in list(self.selectedItems()):
            if isinstance(item, SpotItem):
                self._spots.remove(item)
                self.removeItem(item)
            else:
                # Check if it's a polygon/path that belongs to a border shape
                border = self._border_for_poly(item)
                if border is not None:
                    border.remove()
                    self._borders.remove(border)
                    self.border_selection_changed.emit(None)
        self.selection_changed_detail.emit(None)
    
    def _border_for_poly(self, item: QGraphicsItem) -> "BorderShapeItem | None":
        """Return the BorderShapeItem whose polygon/path graphic is this item."""
        # Some Qt items may not support .data() (or may have an attribute named `data`).
        try:
            item_id = item.data(0)  # type: ignore[call-arg]
        except TypeError:
            return None
        if item_id is None:
            return None
        for b in self._borders:
            if b._poly is item:
                return b
        return None
    
    def deselect_all_borders(self) -> None:
        for b in self._borders:
            if b.selected:
                b.set_selected(False)

    def item_changed(self) -> None:
        sel = [i for i in self.selectedItems() if isinstance(i, SpotItem)]
        if len(sel) == 1:
            self.selection_changed_detail.emit(sel[0])

    # ── Mouse ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = event.scenePos()
        if self.mode == self.MODE_ADD_SPOT and event.button() == Qt.LeftButton:
            spot = self.add_spot_at(pos.x(), pos.y())
            self.clearSelection()
            spot.setSelected(True)
            self.deselect_all_borders()
            return
        if self.mode == self.MODE_DRAW_BORDER and event.button() == Qt.LeftButton:
            if not self._active_border:
                self.start_border()
            self._active_border.add_point(pos.x(), pos.y())
            return
        if self.mode == self.MODE_DRAW_BORDER and event.button() == Qt.RightButton:
            self.close_active_border()
            return
    
        # In SELECT mode: check if click hit a border polygon
        if self.mode == self.MODE_SELECT and event.button() == Qt.LeftButton:
            hit = self.itemAt(pos, QTransform())
            border = None
            if hit is not None:
                # If a spot was clicked — let Qt handle it
                if isinstance(hit, SpotItem) or isinstance(getattr(hit, "parentItem", lambda: None)(), SpotItem):
                    border = None
                else:
                    border = self._border_for_poly(hit)
            if border is not None:
                self.deselect_all_borders()
                self.clearSelection()
                border.set_selected(True)
                event.accept()
                return
            else:
                self.deselect_all_borders()
    
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        p = event.scenePos()
        self.cursor_pos.emit(int(p.x()), int(p.y()))
        super().mouseMoveEvent(event)

    def _on_selection(self) -> None:
        sel = [i for i in self.selectedItems() if isinstance(i, SpotItem)]
        self.selection_changed_detail.emit(sel[0] if len(sel) == 1 else None)

    # ── Export ────────────────────────────────────────────────────────

    def to_svg(self) -> str:
        cw, ch = int(self.canvas_w), int(self.canvas_h)
        lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {cw} {ch}" width="{cw}" height="{ch}">',
            f'<rect width="{cw}" height="{ch}" fill="#1a1a2e"/>',
        ]

        for b in self._borders:
            pts = b.data.points
            if not pts:
                continue
            ps = " ".join(f"{p.x:.1f},{p.y:.1f}" for p in pts)
            if b.data.closed:
                lines.append(
                    f'<polygon points="{ps}" fill="rgba(60,60,220,0.15)" '
                    f'stroke="#3c3cdc" stroke-width="{BORDER_PEN_WIDTH}"/>'
                )
            else:
                lines.append(
                    f'<polyline points="{ps}" fill="none" '
                    f'stroke="#3c3cdc" stroke-width="{BORDER_PEN_WIDTH}" '
                    f'stroke-dasharray="8,4"/>'
                )

        for s in self._spots:
            d = s.data
            w2, h2 = d.w / 2, d.h / 2
            fs = max(10, int(min(d.w, d.h) / 4))
            lines.append(
                f'<g id="{d.id}" data-label="{d.label}" data-status="free" '
                f'transform="translate({d.x:.1f},{d.y:.1f}) rotate({d.angle:.1f})">'
                f'<rect x="{-w2:.1f}" y="{-h2:.1f}" width="{d.w:.1f}" height="{d.h:.1f}" '
                f'rx="4" fill="rgba(80,200,80,0.7)" stroke="white" stroke-width="2" '
                f'class="parking-spot"/>'
                f'<text x="0" y="5" text-anchor="middle" font-family="Arial" '
                f'font-size="{fs}" font-weight="bold" fill="white">{d.label}</text>'
                f'</g>'
            )

        lines.append("</svg>")
        return "\n".join(lines)

    def to_json(self, bev_w: int, bev_h: int) -> dict:
        cw, ch = self.canvas_w, self.canvas_h
        spots = []
        for s in self._spots:
            d = s.data
            spots.append({
                "id": d.id,
                "label": d.label,
                "orientation": d.orientation,
                "bev_center": {
                    "x": round(d.x / cw, 4),
                    "y": round(d.y / ch, 4),
                },
                "map_rect": {
                    "x": round(d.x, 1), "y": round(d.y, 1),
                    "w": round(d.w, 1), "h": round(d.h, 1),
                    "angle": round(d.angle, 1),
                },
            })
        borders = []
        for b in self._borders:
            borders.append({
                "id": b.data.id,
                "closed": b.data.closed,
                "points": [{"x": round(p.x, 1), "y": round(p.y, 1)} for p in b.data.points],
            })
        return {
            "canvas": {"width": int(cw), "height": int(ch)},
            "bev": {"width": bev_w, "height": bev_h},
            "spots": spots,
            "borders": borders,
        }


# ── Map Builder Tab ───────────────────────────────────────────────────────────

class MapBuilderTab(QWidget):
    def __init__(self, state: AppState, status_bar) -> None:
        super().__init__()
        self.state = state
        self.status_bar = status_bar
        self._selected_spot: SpotItem | None = None
        self._syncing = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Sidebar ───────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet("background: #252535;")
        sb = QVBoxLayout(sidebar)
        sb.setSpacing(6)
        sb.setContentsMargins(8, 8, 8, 8)

        # --- Tools ---
        tools = QGroupBox("Tools")
        tl = QVBoxLayout(tools)

        self.select_btn = QPushButton("↖  Select / Move")
        self.select_btn.setCheckable(True)
        self.select_btn.setChecked(True)
        self.select_btn.clicked.connect(lambda: self._set_mode("select"))
        tl.addWidget(self.select_btn)

        self.add_spot_btn = QPushButton("＋  Add Spot (click canvas)")
        self.add_spot_btn.setCheckable(True)
        self.add_spot_btn.clicked.connect(lambda: self._set_mode("add_spot"))
        tl.addWidget(self.add_spot_btn)

        self.copy_btn = QPushButton("⧉ Copy Spot")
        self.copy_btn.clicked.connect(self._copy_spot)
        tl.addWidget(self.copy_btn)
        
        self.paste_btn = QPushButton("⎘ Paste Spot")
        self.paste_btn.setEnabled(False)
        self.paste_btn.clicked.connect(self._paste_spot)
        tl.addWidget(self.paste_btn)
        
        self.border_btn = QPushButton("✏  Draw Border")
        self.border_btn.setCheckable(True)
        self.border_btn.clicked.connect(lambda: self._set_mode("draw_border"))
        tl.addWidget(self.border_btn)

        btn_row = QHBoxLayout()
        close_btn = QPushButton("⬡ Close")
        close_btn.setToolTip("Close the current border shape")
        close_btn.clicked.connect(self._close_border)
        btn_row.addWidget(close_btn)
        undo_btn = QPushButton("↩ Undo Pt")
        undo_btn.setToolTip("Undo last border point")
        undo_btn.clicked.connect(lambda: self.scene.undo_border_point())
        btn_row.addWidget(undo_btn)
        tl.addLayout(btn_row)

        del_btn = QPushButton("🗑  Delete Selected")
        del_btn.setStyleSheet("color: #ff6666;")
        del_btn.clicked.connect(self._delete_selected)
        tl.addWidget(del_btn)
        
        self.del_border_btn = QPushButton("🗑  Delete Border")
        self.del_border_btn.setStyleSheet("color: #ff9944; font-weight: bold;")
        self.del_border_btn.setEnabled(False)
        self.del_border_btn.clicked.connect(self._delete_selected_border)
        tl.addWidget(self.del_border_btn)

        sb.addWidget(tools)

        # --- New Spot Defaults ---
        dg = QGroupBox("New Spot Defaults")
        dl = QVBoxLayout(dg)

        dl.addWidget(QLabel("Orientation:"))
        self.orient_combo = QComboBox()
        self.orient_combo.addItems(["perpendicular", "parallel"])
        self.orient_combo.currentTextChanged.connect(self._sync_defaults)
        dl.addWidget(self.orient_combo)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("W:"))
        self.def_w = QSpinBox()
        self.def_w.setRange(10, 500)
        self.def_w.setValue(DEFAULT_SPOT_W)
        self.def_w.valueChanged.connect(self._sync_defaults)
        size_row.addWidget(self.def_w)
        size_row.addWidget(QLabel("H:"))
        self.def_h = QSpinBox()
        self.def_h.setRange(10, 500)
        self.def_h.setValue(DEFAULT_SPOT_H)
        self.def_h.valueChanged.connect(self._sync_defaults)
        size_row.addWidget(self.def_h)
        dl.addLayout(size_row)

        ar = QHBoxLayout()
        ar.addWidget(QLabel("Angle:"))
        self.def_angle = QDoubleSpinBox()
        self.def_angle.setRange(-180, 180)
        self.def_angle.setValue(0)
        self.def_angle.setSuffix("°")
        self.def_angle.valueChanged.connect(self._sync_defaults)
        ar.addWidget(self.def_angle)
        dl.addLayout(ar)

        sb.addWidget(dg)

        # --- Selected Spot ---
        eg = QGroupBox("Selected Spot")
        eg.setEnabled(False)
        self.edit_group = eg
        el = QVBoxLayout(eg)

        lr = QHBoxLayout()
        lr.addWidget(QLabel("Label:"))
        self.edit_label = QLineEdit()
        self.edit_label.textChanged.connect(self._on_label_edit)
        lr.addWidget(self.edit_label)
        el.addLayout(lr)

        or_row = QHBoxLayout()
        or_row.addWidget(QLabel("Orient:"))
        self.edit_orient = QComboBox()
        self.edit_orient.addItems(["perpendicular", "parallel"])
        self.edit_orient.currentTextChanged.connect(self._on_orient_edit)
        or_row.addWidget(self.edit_orient)
        el.addLayout(or_row)

        sr = QHBoxLayout()
        sr.addWidget(QLabel("W:"))
        self.edit_w = QSpinBox()
        self.edit_w.setRange(10, 500)
        self.edit_w.valueChanged.connect(self._on_geom_edit)
        sr.addWidget(self.edit_w)
        sr.addWidget(QLabel("H:"))
        self.edit_h = QSpinBox()
        self.edit_h.setRange(10, 500)
        self.edit_h.valueChanged.connect(self._on_geom_edit)
        sr.addWidget(self.edit_h)
        el.addLayout(sr)

        ea = QHBoxLayout()
        ea.addWidget(QLabel("Angle:"))
        self.edit_angle = QDoubleSpinBox()
        self.edit_angle.setRange(-180, 180)
        self.edit_angle.setSuffix("°")
        self.edit_angle.setSingleStep(5)
        self.edit_angle.valueChanged.connect(self._on_geom_edit)
        ea.addWidget(self.edit_angle)
        el.addLayout(ea)

        pos_row = QHBoxLayout()
        pos_row.addWidget(QLabel("X:"))
        self.edit_x = QSpinBox()
        self.edit_x.setRange(0, 9999)
        self.edit_x.valueChanged.connect(self._on_pos_edit)
        pos_row.addWidget(self.edit_x)
        pos_row.addWidget(QLabel("Y:"))
        self.edit_y = QSpinBox()
        self.edit_y.setRange(0, 9999)
        self.edit_y.valueChanged.connect(self._on_pos_edit)
        pos_row.addWidget(self.edit_y)
        el.addLayout(pos_row)

        sb.addWidget(eg)

        # --- View ---
        vg = QGroupBox("View")
        vl = QVBoxLayout(vg)

        self.bev_check = QCheckBox("Show BEV overlay")
        self.bev_check.setChecked(True)
        self.bev_check.toggled.connect(lambda v: self.scene.toggle_bev(v))
        vl.addWidget(self.bev_check)

        op = QHBoxLayout()
        op.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(35)
        self.opacity_slider.valueChanged.connect(lambda v: self.scene.set_bev_opacity(v / 100))
        op.addWidget(self.opacity_slider)
        vl.addLayout(op)

        self.grid_check = QCheckBox("Show grid")
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(lambda v: self.scene.toggle_grid(v))
        vl.addWidget(self.grid_check)

        sb.addWidget(vg)

        # --- Info ---
        self.info_label = QLabel("Canvas: —")
        self.info_label.setStyleSheet("color: #aaa; font-size: 11px;")
        sb.addWidget(self.info_label)

        self.coord_label = QLabel("x: —  y: —")
        self.coord_label.setStyleSheet("color: #aaa; font-family: monospace; font-size: 11px;")
        sb.addWidget(self.coord_label)

        sb.addStretch()

        # --- Export ---
        xg = QGroupBox("Export")
        xl = QVBoxLayout(xg)
        for label, color, slot in [
            ("Download SVG", "#4CAF50", self._export_svg),
            ("Download spots.json", "#2196F3", self._export_json),
            ("Export Both", "#9C27B0", self._export_both),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                f"background-color: {color}; color: white; font-weight: bold; padding: 6px;"
            )
            btn.clicked.connect(slot)
            xl.addWidget(btn)
        sb.addWidget(xg)

        root.addWidget(sidebar)

        # ── Canvas ────────────────────────────────────────────────────
        bw, bh = self.state.bev_width, self.state.bev_height
        self.scene = MapScene(bw, bh)
        self.scene.selection_changed_detail.connect(self._on_spot_selected)
        self.scene.border_selection_changed.connect(self._on_border_selected)
        self.scene.cursor_pos.connect(self._on_cursor)
        self.scene.clipboard_changed.connect(self._on_clipboard_changed)

        self.view = MapView(self.scene)
        root.addWidget(self.view)

        QShortcut(QKeySequence(Qt.Key_Delete), self).activated.connect(self._delete_selected)
        QShortcut(QKeySequence.Copy, self).activated.connect(self._copy_spot)
        QShortcut(QKeySequence.Paste, self).activated.connect(self._paste_spot)

    # ── Activation ────────────────────────────────────────────────────

    def on_activate(self) -> None:
        bw, bh = self.state.bev_width, self.state.bev_height
        if self.scene.canvas_w != bw or self.scene.canvas_h != bh:
            self.scene.resize_canvas(bw, bh)
        if self.state.bev_image is not None:
            self.scene.set_bev(self.state.bev_image, self.opacity_slider.value() / 100)
        self.info_label.setText(
            f"Canvas: {int(self.scene.canvas_w)}×{int(self.scene.canvas_h)}  "
            f"(= BEV size)"
        )

    # ── Modes ─────────────────────────────────────────────────────────

    def _set_mode(self, mode: str) -> None:
        self.scene.set_mode(mode)
        for btn, m in [
            (self.select_btn, "select"),
            (self.add_spot_btn, "add_spot"),
            (self.border_btn, "draw_border"),
        ]:
            btn.setChecked(mode == m)
        tips = {
            "select": "Click to select · drag to move · drag corners to resize",
            "add_spot": "Click canvas to place a spot",
            "draw_border": "LMB = add point · RMB or ⬡ = close shape",
        }
        self.status_bar.showMessage(tips.get(mode, ""))

    def _close_border(self) -> None:
        self.scene.close_active_border()
        self._set_mode("select")

    def _on_border_selected(self, border: "BorderShapeItem | None") -> None:
        self._selected_border = border
        self.del_border_btn.setEnabled(border is not None)
        if border is not None:
            # Deselect spots when a border is selected
            self._on_spot_selected(None)
    
    def _delete_selected_border(self) -> None:
        border = getattr(self, "_selected_border", None)
        if border is None:
            return
        border.remove()
        if border in self.scene._borders:
            self.scene._borders.remove(border)
        self._selected_border = None
        self.del_border_btn.setEnabled(False)
        self.scene.border_selection_changed.emit(None)
    
    def _on_clipboard_changed(self, has_clipboard: bool) -> None:
        self.paste_btn.setEnabled(has_clipboard)
    
    def _copy_spot(self) -> None:
        self.scene.copy_selected_spot()
        self.status_bar.showMessage("Spot copied (Ctrl+C)")
    
    def _paste_spot(self) -> None:
        if not self.scene.has_spot_clipboard():
            return
        pos = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.paste_spot(pos.x(), pos.y())
        self.status_bar.showMessage("Spot pasted (Ctrl+V)")
    
    def _delete_selected(self) -> None:
        self.scene.delete_selected()

    # ── Defaults ──────────────────────────────────────────────────────

    def _sync_defaults(self) -> None:
        self.scene.spot_defaults = {
            "w": self.def_w.value(),
            "h": self.def_h.value(),
            "orientation": self.orient_combo.currentText(),
            "angle": self.def_angle.value(),
        }

    # ── Selection sync ────────────────────────────────────────────────

    def _on_spot_selected(self, spot: SpotItem | None) -> None:
        self._selected_spot = spot
        self.edit_group.setEnabled(spot is not None)
        if spot is None:
            return
        self._syncing = True
        d = spot.data
        self.edit_label.setText(d.label)
        self.edit_orient.setCurrentText(d.orientation)
        self.edit_w.setValue(int(d.w))
        self.edit_h.setValue(int(d.h))
        self.edit_angle.setValue(d.angle)
        self.edit_x.setValue(int(d.x))
        self.edit_y.setValue(int(d.y))
        self._syncing = False

    def _on_label_edit(self, text: str) -> None:
        if self._syncing or not self._selected_spot:
            return
        self._selected_spot.update_label(text)

    def _on_orient_edit(self, text: str) -> None:
        if self._syncing or not self._selected_spot:
            return
        self._selected_spot.data.orientation = text

    def _on_geom_edit(self) -> None:
        if self._syncing or not self._selected_spot:
            return
        self._selected_spot.update_geometry(
            self.edit_w.value(), self.edit_h.value(), self.edit_angle.value()
        )

    def _on_pos_edit(self) -> None:
        if self._syncing or not self._selected_spot:
            return
        self._selected_spot.setPos(self.edit_x.value(), self.edit_y.value())

    def _on_cursor(self, x: int, y: int) -> None:
        self.coord_label.setText(f"x: {x}  y: {y}")

    # ── Export ────────────────────────────────────────────────────────

    def _export_svg(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save SVG", "parking_map.svg", "SVG (*.svg)")
        if path:
            Path(path).write_text(self.scene.to_svg(), encoding="utf-8")
            self.status_bar.showMessage(f"SVG saved: {path}")

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save JSON", "spots.json", "JSON (*.json)")
        if path:
            data = self.scene.to_json(self.state.bev_width, self.state.bev_height)
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.status_bar.showMessage(f"JSON saved: {path}")

    def _export_both(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export Folder")
        if not folder:
            return
        p = Path(folder)
        p.joinpath("parking_map.svg").write_text(self.scene.to_svg(), encoding="utf-8")
        data = self.scene.to_json(self.state.bev_width, self.state.bev_height)
        p.joinpath("spots.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.status_bar.showMessage(f"Exported to: {folder}")
