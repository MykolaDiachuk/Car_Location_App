"""Main window with tab navigation."""
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QStatusBar

from app.state import AppState
from app.tabs.camera import CameraTab
from app.tabs.bev import BevTab
from app.tabs.paint_mask import PaintTab
from app.tabs.map_builder import MapBuilderTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Parking Configurator")
        self.setMinimumSize(1280, 800)

        self.state = AppState()
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.camera_tab = CameraTab(self.state, self.status_bar)
        self.bev_tab = BevTab(self.state, self.status_bar)
        self.parking_mask_tab = PaintTab(self.state, self.status_bar, mask_type="parking")
        self.orient_tab = PaintTab(self.state, self.status_bar, mask_type="orientation")
        self.map_tab = MapBuilderTab(self.state, self.status_bar)

        self.tabs.addTab(self.camera_tab, "1 · Camera")
        self.tabs.addTab(self.bev_tab, "2 · BEV Calibration")
        self.tabs.addTab(self.parking_mask_tab, "3 · Parking Mask")
        self.tabs.addTab(self.orient_tab, "4 · Orientation Zones")
        self.tabs.addTab(self.map_tab, "5 · Map Builder")

        self.tabs.currentChanged.connect(self._on_tab_change)

    def _on_tab_change(self, index: int) -> None:
        if index == 1:
            self.bev_tab.on_activate()
        elif index == 2:
            self.parking_mask_tab.on_activate()
        elif index == 3:
            self.orient_tab.on_activate()
        elif index == 4:
            self.map_tab.on_activate()
