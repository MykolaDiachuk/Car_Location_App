"""Camera tab — connect to camera and capture a frame."""
import re
import threading
import cv2
import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFileDialog, QSizePolicy,
)

from app.state import AppState


class FrameSignal(QObject):
    frame_ready = pyqtSignal(np.ndarray)
    error = pyqtSignal(str)


class CameraTab(QWidget):
    def __init__(self, state: AppState, status_bar) -> None:
        super().__init__()
        self.state = state
        self.status_bar = status_bar
        self._cap = None
        self._live = False
        self._signal = FrameSignal()
        self._signal.frame_ready.connect(self._on_live_frame)
        self._signal.error.connect(self._on_error)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Connection group ──────────────────────────────────────────
        conn_group = QGroupBox("Camera Connection")
        conn_layout = QVBoxLayout(conn_group)

        rtsp_row = QHBoxLayout()
        rtsp_row.addWidget(QLabel("RTSP URL:"))
        self.rtsp_input = QLineEdit()
        self.rtsp_input.setPlaceholderText("rtsp://user:pass@192.168.0.1:554/stream")
        self.rtsp_input.setText("rtsp://")
        rtsp_row.addWidget(self.rtsp_input)
        conn_layout.addLayout(rtsp_row)

        helper_row = QHBoxLayout()
        helper_row.addWidget(QLabel("  or build:"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("192.168.0.172")
        self.ip_input.setFixedWidth(140)
        self.port_input = QLineEdit("5554")
        self.port_input.setFixedWidth(60)
        self.user_input = QLineEdit("admin")
        self.user_input.setFixedWidth(80)
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        self.pass_input.setFixedWidth(100)
        self.pass_input.setPlaceholderText("password")
        self.channel_input = QLineEdit("1")
        self.channel_input.setFixedWidth(40)
        build_btn = QPushButton("Build URL")
        build_btn.setFixedWidth(90)
        build_btn.clicked.connect(self._build_url)

        for w, lbl in [
            (self.ip_input, "IP"),
            (self.port_input, "Port"),
            (self.user_input, "User"),
            (self.pass_input, "Pass"),
            (self.channel_input, "Ch"),
        ]:
            helper_row.addWidget(QLabel(lbl))
            helper_row.addWidget(w)
        helper_row.addWidget(build_btn)
        helper_row.addStretch()
        conn_layout.addLayout(helper_row)

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect & Preview")
        self.connect_btn.clicked.connect(self._connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        btn_row.addStretch()
        conn_layout.addLayout(btn_row)

        root.addWidget(conn_group)

        # ── Preview + capture ─────────────────────────────────────────
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_label = QLabel("No frame — connect to camera or load a file")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(400)
        self.preview_label.setStyleSheet("background: #1e1e1e; color: #888;")
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        preview_layout.addWidget(self.preview_label)

        capture_row = QHBoxLayout()
        self.capture_btn = QPushButton("Capture Frame")
        self.capture_btn.setFixedHeight(36)
        self.capture_btn.setEnabled(False)
        self.capture_btn.clicked.connect(self._capture)
        load_btn = QPushButton("Load from File…")
        load_btn.setFixedHeight(36)
        load_btn.clicked.connect(self._load_file)
        self.frame_info = QLabel("")
        capture_row.addWidget(self.capture_btn)
        capture_row.addWidget(load_btn)
        capture_row.addWidget(self.frame_info)
        capture_row.addStretch()
        preview_layout.addLayout(capture_row)

        root.addWidget(preview_group)

    # ── Camera logic ──────────────────────────────────────────────────

    def _build_url(self) -> None:
        ip = self.ip_input.text().strip()
        port = self.port_input.text().strip()
        user = self.user_input.text().strip()
        pwd = self.pass_input.text()
        ch = self.channel_input.text().strip()
        url = f"rtsp://{user}:{pwd}@{ip}:{port}/cam/realmonitor?channel={ch}&subtype=0"
        self.rtsp_input.setText(url)

    def _connect(self) -> None:
        url = self.rtsp_input.text().strip()
        if not url:
            self.status_bar.showMessage("Enter camera URL first")
            return

        self.state.camera_url = url
        self.status_bar.showMessage("Connecting…")
        self.connect_btn.setEnabled(False)

        def worker():
            cap = cv2.VideoCapture(url)
            if not cap.isOpened():
                self._signal.error.emit("Could not connect to camera")
                return
            for _ in range(5):
                cap.read()
            ret, frame = cap.read()
            if not ret:
                cap.release()
                self._signal.error.emit("Connected but could not read frame")
                return
            self._cap = cap
            self._live = True
            self._signal.frame_ready.emit(frame)
            while self._live:
                try:
                    ret, frame = cap.read()
                except cv2.error:
                    # OpenCV may throw if the stream is closed while reading
                    break
                if not self._live:
                    break
                if ret and frame is not None:
                    self._signal.frame_ready.emit(frame)
            
            cap.release()

        threading.Thread(target=worker, daemon=True).start()

    def _disconnect(self) -> None:
        self._live = False
        if self._cap:
            self._cap.release()
            self._cap = None
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.capture_btn.setEnabled(False)
        self.status_bar.showMessage("Disconnected")

    def _on_live_frame(self, frame: np.ndarray) -> None:
        self.disconnect_btn.setEnabled(True)
        self.capture_btn.setEnabled(True)
        self.connect_btn.setEnabled(False)
        self._show_frame(frame)
        self._last_frame = frame
        self.status_bar.showMessage(f"Live  {frame.shape[1]}×{frame.shape[0]}")

    def _on_error(self, msg: str) -> None:
        self.status_bar.showMessage(f"ERROR: {msg}")
        self.connect_btn.setEnabled(True)

    def _capture(self) -> None:
        frame = getattr(self, "_last_frame", None)
        if frame is None:
            return
        self._disconnect()
        self.state.frame = frame.copy()
        self.frame_info.setText(f"✓ Captured  {frame.shape[1]}×{frame.shape[0]}")
        self.status_bar.showMessage("Frame captured — go to BEV Calibration")

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "", "Images (*.jpg *.jpeg *.png *.bmp)"
        )
        if not path:
            return
        frame = cv2.imread(path)
        if frame is None:
            self.status_bar.showMessage("Failed to load image")
            return
        self.state.frame = frame
        self._show_frame(frame)
        self.frame_info.setText(f"✓ Loaded  {frame.shape[1]}×{frame.shape[0]}")
        self.status_bar.showMessage("Image loaded — go to BEV Calibration")

    def _show_frame(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        lw, lh = self.preview_label.width(), self.preview_label.height()
        scale = min(lw / w, lh / h, 1.0)
        dw, dh = max(1, int(w * scale)), max(1, int(h * scale))
        resized = cv2.resize(frame, (dw, dh))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        q_img = QImage(rgb.data, dw, dh, 3 * dw, QImage.Format_RGB888)
        self.preview_label.setPixmap(QPixmap.fromImage(q_img))
