"""Parking Configurator — standalone tool for parking lot setup.

Usage:
    python parking_configurator/main.py
"""
import sys
from PyQt5.QtWidgets import QApplication
from app.window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Parking Configurator")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
