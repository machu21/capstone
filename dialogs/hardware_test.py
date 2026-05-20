"""
dialogs/hardware_test.py
────────────────────────
Manual test controls for conveyor motor and sorter servo.
"""

import os
import lgpio  # type: ignore

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from utils import screen_size

os.environ["BLINKA_FORCEBOARD"] = "RASPBERRY_PI_5"

# ── Pin & Hardware assignments ───────────────────────────────────────────────
GPIO_CHIP       = 0
PIN_MOTOR_IN1   = 17
PIN_MOTOR_IN2   = 27

PCA9685_ADDRESS = 0x40
SERVO_CHANNEL   = 4
FREQ_HZ         = 50

PW_NEUTRAL      = 1500
PW_REJECT       =  900
PW_QUALIFIED    = 2100


def _us_to_duty(us: int) -> int:
    """Convert pulse width in microseconds to PCA9685 16-bit duty cycle."""
    period_us = 1_000_000 / FREQ_HZ
    return int((us / period_us) * 65535)


class HardwareTestDialog(QDialog):
    """Manual test controls for conveyor motor and sorter servo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hardware Diagnostics")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, _ = screen_size()
        scale = SW / 800
        fs    = max(13, int(18 * scale))
        btn_h = max(50, int(70 * scale))

        self._h = None
        self._pca = None
        
        self._init_hardware()
        self._build_ui(scale, fs, btn_h)

    # ── Hardware init ─────────────────────────────────────────────────────────

    def _init_hardware(self):
        # 1. Init Conveyor Motor via direct GPIO
        try:
            self._h = lgpio.gpiochip_open(GPIO_CHIP)
            lgpio.gpio_claim_output(self._h, PIN_MOTOR_IN1)
            lgpio.gpio_claim_output(self._h, PIN_MOTOR_IN2)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"lgpio (Motor) init failed:\n{e}")
            self._h = None

        # 2. Init Sorter Servo via PCA9685
        try:
            import board                          # type: ignore
            import busio                          # type: ignore
            from adafruit_pca9685 import PCA9685  # type: ignore

            i2c = busio.I2C(board.SCL, board.SDA)
            self._pca = PCA9685(i2c, address=PCA9685_ADDRESS)
            self._pca.frequency = FREQ_HZ

            # Initialize to neutral, then cut PWM to stop jitter
            self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(PW_NEUTRAL)
            QTimer.singleShot(600, self._stop_pulse)

        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"PCA9685 (Servo) init failed:\n{e}")
            self._pca = None

    # ── Conveyor helpers ──────────────────────────────────────────────────────

    def _conveyor_on(self):
        if self._h:
            lgpio.gpio_write(self._h, PIN_MOTOR_IN1, 1)
            lgpio.gpio_write(self._h, PIN_MOTOR_IN2, 0)

    def _conveyor_off(self):
        if self._h:
            lgpio.gpio_write(self._h, PIN_MOTOR_IN1, 0)
            lgpio.gpio_write(self._h, PIN_MOTOR_IN2, 0)

    # ── Servo helpers ─────────────────────────────────────────────────────────

    def _servo_reject(self):
        if self._pca:
            self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(PW_REJECT)
            QTimer.singleShot(600, self._stop_pulse)

    def _servo_neutral(self):
        if self._pca:
            self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(PW_NEUTRAL)
            QTimer.singleShot(600, self._stop_pulse)

    def _servo_qualified(self):
        if self._pca:
            self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(PW_QUALIFIED)
            QTimer.singleShot(600, self._stop_pulse)

    def _stop_pulse(self):
        """Cuts the PWM signal completely to eliminate MG996R jitter and overheating."""
        if self._pca:
            self._pca.channels[SERVO_CHANNEL].duty_cycle = 0

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float, fs: int, btn_h: int):
        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(10 * scale))
        main_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("Hardware Diagnostic Mode")
        title.setStyleSheet(f"font-size: {max(16, int(24*scale))}px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        main_layout.addWidget(self._section_label("DC Motor: Conveyor Belt", fs))
        main_layout.addLayout(self._conveyor_buttons(fs, btn_h))

        main_layout.addWidget(self._section_label("MG996R: Sorter Alignment", fs))
        main_layout.addLayout(self._servo_buttons(fs, btn_h))

        exit_btn = QPushButton("Exit Hardware Test")
        exit_btn.setMinimumHeight(btn_h)
        exit_btn.setStyleSheet(
            f"font-size: {fs}px; font-weight: bold; "
            f"background-color: #9e9e9e; color: white; border-radius: 8px;"
        )
        exit_btn.clicked.connect(self.accept)
        main_layout.addWidget(exit_btn)

        self.setLayout(main_layout)

    def _section_label(self, text: str, fs: int) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {fs}px; font-weight: bold;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _conveyor_buttons(self, fs: int, btn_h: int) -> QHBoxLayout:
        row = QHBoxLayout()
        for label, color, slot in [
            ("Start Conveyor", "#4CAF50", self._conveyor_on),
            ("Stop Conveyor",  "#f44336", self._conveyor_off),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(
                f"font-size: {fs}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 8px;"
            )
            btn.clicked.connect(slot)
            row.addWidget(btn)
        return row

    def _servo_buttons(self, fs: int, btn_h: int) -> QHBoxLayout:
        row = QHBoxLayout()
        for label, color, slot in [
            ("Left / Reject",    "#FF9800", self._servo_reject),
            ("Center / Neutral", "#2196F3", self._servo_neutral),
            ("Right / Qualified","#8BC34A", self._servo_qualified),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(
                f"font-size: {fs}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 8px;"
            )
            btn.clicked.connect(slot)
            row.addWidget(btn)
        return row

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup(self):
        # Shut down motor
        if self._h:
            self._conveyor_off()
            lgpio.gpiochip_close(self._h)
            self._h = None
            
        # Shut down servo
        if self._pca:
            self._pca.channels[SERVO_CHANNEL].duty_cycle = 0
            self._pca.deinit()
            self._pca = None

    def accept(self):
        self._cleanup()
        super().accept()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)