from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
Device.pin_factory = LGPIOFactory()

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
)
from PyQt6.QtCore import Qt

from utils import screen_size

# ── Pin assignments ──────────────────────────────────────────────────────────
PIN_MOTOR_IN1          = 17
PIN_MOTOR_IN2          = 27

PCA9685_ADDRESS        = 0x40
PCA9685_SORTER_CHANNEL = 5
SORTER_FREQ_HZ         = 50

PW_NEUTRAL             = 1500
PW_REJECT              =  900
PW_QUALIFIED           = 2100

def _us_to_duty(us: int) -> int:
    return int((us / (1_000_000 / SORTER_FREQ_HZ)) * 4096)


class HardwareTestDialog(QDialog):
    """Manual test controls for the conveyor motor and sorter servo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hardware Diagnostics")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, _ = screen_size()
        scale = SW / 800
        fs    = max(13, int(18 * scale))
        btn_h = max(50, int(70 * scale))

        if not self._init_gpio():
            return

        self._build_ui(scale, fs, btn_h)

    # ── Hardware init ────────────────────────────────────────────────────────

    def _init_gpio(self) -> bool:
        try:
            from gpiozero import OutputDevice
            self.motor_in1 = OutputDevice(PIN_MOTOR_IN1, active_high=True, initial_value=False)
            self.motor_in2 = OutputDevice(PIN_MOTOR_IN2, active_high=True, initial_value=False)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"Motor GPIO failed:\n{e}")
            self.reject()
            return False

        try:
            from adafruit_pca9685 import PCA9685   # type: ignore
            import board, busio                     # type: ignore
            i2c        = busio.I2C(board.SCL, board.SDA)
            self._pca  = PCA9685(i2c, address=PCA9685_ADDRESS)
            self._pca.frequency = SORTER_FREQ_HZ
            self._sorter_ch = self._pca.channels[PCA9685_SORTER_CHANNEL]
            self._set_pulse(PW_NEUTRAL)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"PCA9685 servo failed:\n{e}")
            self.reject()
            return False

        return True

    def _set_pulse(self, us: int):
        if hasattr(self, '_sorter_ch'):
            self._sorter_ch.duty_cycle = _us_to_duty(us) << 4

    def _stop_pulse(self):
        if hasattr(self, '_sorter_ch'):
            self._sorter_ch.duty_cycle = 0

    # ── Conveyor helpers ─────────────────────────────────────────────────────

    def _conveyor_on(self):
        self.motor_in1.on()
        self.motor_in2.off()

    def _conveyor_off(self):
        self.motor_in1.off()
        self.motor_in2.off()

    # ── Servo helpers ─────────────────────────────────────────────────────────

    def _servo_reject(self):
        self.sorter_servo.value = _deg_to_value(ANGLE_REJECT)

    def _servo_neutral(self):
        self.sorter_servo.value = _deg_to_value(ANGLE_NEUTRAL)
        from PyQt6.QtCore import QTimer
        pass  # lgpio does not support value=None; servo holds neutral position

    def _servo_qualified(self):
        self.sorter_servo.value = _deg_to_value(ANGLE_QUALIFIED)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float, fs: int, btn_h: int):
        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(10 * scale))
        main_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("Hardware Diagnostic Mode")
        title.setStyleSheet(
            f"font-size: {max(16, int(24*scale))}px; font-weight: bold; color: #333;"
        )
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

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def _cleanup(self):
        if hasattr(self, "motor_in1"):
            self._conveyor_off()
            self.motor_in1.close()
            self.motor_in2.close()
        if hasattr(self, "sorter_servo"):
            self.sorter_servo.value = _deg_to_value(ANGLE_NEUTRAL)
            self.sorter_servo.close()

    def accept(self):
        self._cleanup()
        super().accept()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)