import random

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from utils import screen_size


class WeightSensorTestDialog(QDialog):
    """Diagnostic dialog for the HX711 load-cell amplifier."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Weight Sensor Test")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, _ = screen_size()
        scale  = SW / 800
        fs     = max(13, int(18 * scale))
        fs_big = max(30, int(60 * scale))
        btn_h  = max(50, int(70 * scale))

        self.MOCK_HARDWARE = True
        self.mock_weight   = 0.00

        if not self.MOCK_HARDWARE:
            self._init_hx711()

        self._build_ui(scale, fs, fs_big, btn_h)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_weight_reading)
        self.timer.start(500)

    # ── Hardware init ────────────────────────────────────────────────────────

    def _init_hx711(self):
        try:
            from hx711_multi import HX711
            self.hx = HX711(dout_pins=[5], sck_pin=6)
            self.hx.tare()
        except ImportError:
            QMessageBox.warning(
                self, "Library Missing", "Please install the HX711 library."
            )
            self.MOCK_HARDWARE = True
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"HX711 setup failed: {e}")
            self.MOCK_HARDWARE = True

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float, fs: int, fs_big: int, btn_h: int):
        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(10 * scale))
        main_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("Load Cell & HX711 Diagnostics")
        title.setStyleSheet(
            f"font-size: {max(16, int(22*scale))}px; font-weight: bold; color: #333;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        self.reading_label = QLabel("0.00 kg")
        self.reading_label.setStyleSheet(
            f"font-size: {fs_big}px; font-weight: bold; color: #1565C0; "
            f"background-color: white; border: 4px solid #ccc; "
            f"border-radius: 12px; padding: 10px;"
        )
        self.reading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.reading_label)

        main_layout.addLayout(self._action_buttons(fs, btn_h))

        exit_btn = QPushButton("Exit Hardware Test")
        exit_btn.setMinimumHeight(btn_h)
        exit_btn.setStyleSheet(
            f"font-size: {fs}px; font-weight: bold; "
            f"background-color: #9e9e9e; color: white; border-radius: 8px;"
        )
        exit_btn.clicked.connect(self.accept)
        main_layout.addWidget(exit_btn)

        self.setLayout(main_layout)

    def _action_buttons(self, fs: int, btn_h: int) -> QHBoxLayout:
        row = QHBoxLayout()

        tare_btn = QPushButton("Tare (Zero Scale)")
        tare_btn.setMinimumHeight(btn_h)
        tare_btn.setStyleSheet(
            f"font-size: {fs}px; font-weight: bold; "
            f"background-color: #FF9800; color: white; border-radius: 8px;"
        )
        tare_btn.clicked.connect(self._tare_scale)
        row.addWidget(tare_btn)

        if self.MOCK_HARDWARE:
            sim_btn = QPushButton("Simulate +100g")
            sim_btn.setMinimumHeight(btn_h)
            sim_btn.setStyleSheet(
                f"font-size: {fs}px; font-weight: bold; "
                f"background-color: #4CAF50; color: white; border-radius: 8px;"
            )
            sim_btn.clicked.connect(self._simulate_weight)
            row.addWidget(sim_btn)

        return row

    # ── Callbacks ────────────────────────────────────────────────────────────

    def _update_weight_reading(self):
        if self.MOCK_HARDWARE:
            display = self.mock_weight + random.uniform(-0.002, 0.002)
            self.reading_label.setText(f"{display:.3f} kg")
        else:
            try:
                raw = self.hx.get_weight_mean(readings=5)
                self.reading_label.setText(f"{raw:.3f} kg")
            except Exception:
                self.reading_label.setText("Error Reading")

    def _tare_scale(self):
        if self.MOCK_HARDWARE:
            self.mock_weight = 0.00
            self.reading_label.setText("0.000 kg")
        else:
            self.reading_label.setText("Taring...")
            self.hx.zero()

    def _simulate_weight(self):
        self.mock_weight += 0.100

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def accept(self):
        self.timer.stop()
        super().accept()