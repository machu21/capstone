from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
Device.pin_factory = LGPIOFactory()

# PCA9685 sorter servo channel
PCA9685_SORTER_CHANNEL = 5
SORTER_FREQ_HZ         = 50
PW_NEUTRAL             = 1500
PW_REJECT              =  900
PW_QUALIFIED           = 2100

def _us_to_duty(us: int) -> int:
    period_us = 1_000_000 / SORTER_FREQ_HZ
    return int((us / period_us) * 4096)

import random

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QImage
from picamera2 import Picamera2

from utils import screen_size

# ── Pin assignments ──────────────────────────────────────────────────────────
PIN_MOTOR_IN1   = 17
PIN_MOTOR_IN2   = 27
PIN_TRIG        = 23
PIN_ECHO        = 24
PIN_HX711_DT    = 5
PIN_HX711_SCK   = 6

# ── PCA9685 config ────────────────────────────────────────────────────────────
PCA9685_ADDRESS        = 0x40
PCA9685_SORTER_CHANNEL = 5
SORTER_FREQ_HZ         = 50
COIN_CHANNELS          = {0: 1, 1: 5, 2: 10, 3: 20}

# ── Sorter servo pulse widths (us) ────────────────────────────────────────────
PW_NEUTRAL   = 1500   # forward
PW_REJECT    =  900   # left  → reject
PW_QUALIFIED = 2100   # right → qualified

# ── Coin dispenser angles ─────────────────────────────────────────────────────
COIN_DISPENSE_ANGLE = 90
COIN_NEUTRAL_ANGLE  =  0

# ── Timing (ms) ──────────────────────────────────────────────────────────────
DETECT_STABILIZE_MS = 800
SORT_DWELL_MS       = 2000
COIN_DISPENSE_MS    = 600
COIN_RETURN_MS      = 400


def _break_into_coins(amount_php: float) -> dict:
    coins = {}
    remaining = int(round(amount_php))
    for denom in sorted(COIN_CHANNELS.values(), reverse=True):
        count = remaining // denom
        if count:
            coins[denom] = count
        remaining %= denom
    return coins


class ActualTransactionDialog(QDialog):
    """
    Live transaction dialog.
    Connected hardware: conveyor (L298N), sorter servo (MG996R), camera.
    Ultrasonic, HX711, and PCA9685 are stubbed — weight is simulated,
    qualification is random until AI/sensor integration is complete.
    """

    # Set to False to run real hardware
    MOCK_ULTRASONIC = True
    MOCK_WEIGHT     = True
    MOCK_COINS      = True

    def __init__(self, material: str, parent=None):
        super().__init__(parent)
        self.material       = material
        self.current_weight = 0.00

        self.setWindowTitle(f"Sorting {material}...")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        self.CAM_W = int(SW * 0.55)
        self.CAM_H = int(self.CAM_W * 3 / 4)
        scale = SW / 800

        self._init_conveyor()
        self._init_servo()
        self._init_camera()

        if not self.MOCK_ULTRASONIC:
            self._init_ultrasonic()

        if not self.MOCK_WEIGHT:
            self._init_hx711()

        if not self.MOCK_COINS:
            self._init_pca9685()

        self._build_ui(scale)
        self._init_state_machine()

    # ── Hardware init ────────────────────────────────────────────────────────

    def _init_conveyor(self):
        try:
            from gpiozero import OutputDevice
            self.motor_in1 = OutputDevice(PIN_MOTOR_IN1, active_high=True, initial_value=False)
            self.motor_in2 = OutputDevice(PIN_MOTOR_IN2, active_high=True, initial_value=False)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"Conveyor motor init failed:\n{e}")
            self.reject()

    def _init_servo(self):
        try:
            from adafruit_pca9685 import PCA9685   # type: ignore
            import board, busio                     # type: ignore
            i2c = busio.I2C(board.SCL, board.SDA)
            if not hasattr(self, '_pca') or self._pca is None:
                self._pca = PCA9685(i2c, address=PCA9685_ADDRESS)
                self._pca.frequency = SORTER_FREQ_HZ
            self._sorter_ch = self._pca.channels[PCA9685_SORTER_CHANNEL]
            self._set_servo_pulse(PW_NEUTRAL)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"Servo (PCA9685) init failed:\n{e}")
            self.reject()

    def _set_servo_pulse(self, us: int):
        if hasattr(self, '_sorter_ch'):
            self._sorter_ch.duty_cycle = _us_to_duty(us) << 4

    def _stop_servo_pulse(self):
        if hasattr(self, '_sorter_ch'):
            self._sorter_ch.duty_cycle = 0

    def _init_ultrasonic(self):
        try:
            from gpiozero import DistanceSensor
            self.ultrasonic = DistanceSensor(
                echo=PIN_ECHO, trigger=PIN_TRIG,
                max_distance=1.0, threshold_distance=0.1,
            )
        except Exception as e:
            QMessageBox.warning(self, "Ultrasonic", f"Sensor init failed:\n{e}")
            self.MOCK_ULTRASONIC = True

    def _init_hx711(self):
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setmode(GPIO.BCM)
            from hx711_multi import HX711  # type: ignore
            self.hx = HX711(dout_pins=[PIN_HX711_DT], sck_pin=PIN_HX711_SCK)
            self.hx.tare()
        except Exception as e:
            QMessageBox.warning(self, "Weight Sensor", f"HX711 init failed:\n{e}")
            self.MOCK_WEIGHT = True

    def _init_pca9685(self):
        try:
            from adafruit_pca9685 import PCA9685        # type: ignore
            from adafruit_motor import servo as aservo  # type: ignore
            import board, busio                          # type: ignore
            i2c = busio.I2C(board.SCL, board.SDA)
            self.pca = PCA9685(i2c, address=PCA9685_ADDRESS)
            self.pca.frequency = 50
            self.coin_servos = {
                denom: aservo.Servo(self.pca.channels[ch])
                for ch, denom in COIN_CHANNELS.items()
            }
        except Exception as e:
            QMessageBox.warning(self, "Coin Dispenser", f"PCA9685 init failed:\n{e}")
            self.MOCK_COINS = True

    def _init_camera(self):
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": (self.CAM_W, self.CAM_H), "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()

    # ── Conveyor helpers ─────────────────────────────────────────────────────

    def _conveyor_on(self):
        self.motor_in1.on()
        self.motor_in2.off()

    def _conveyor_off(self):
        self.motor_in1.off()
        self.motor_in2.off()

    # ── Servo helpers ─────────────────────────────────────────────────────────

    def _servo_go(self, pw: int):
        self._set_servo_pulse(pw)

    def _servo_neutral(self):
        self._set_servo_pulse(PW_NEUTRAL)
        QTimer.singleShot(600, self._stop_servo_pulse)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float):
        fs_title  = max(14, int(20 * scale))
        fs_status = max(13, int(17 * scale))
        fs_weight = max(18, int(28 * scale))
        fs_btn    = max(13, int(18 * scale))
        btn_h     = max(50, int(70 * scale))

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # Left — camera
        self.camera_label = QLabel()
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setFixedSize(self.CAM_W, self.CAM_H)
        self.camera_label.setStyleSheet(
            "background-color: black; border: 3px solid #333; border-radius: 8px;"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root_layout.addWidget(self.camera_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Right — info panel
        info_layout = QVBoxLayout()
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.setSpacing(int(8 * scale))

        self.title_label = QLabel(f"Active Sorting:\n{self.material}")
        self.title_label.setStyleSheet(f"font-size: {fs_title}px; font-weight: bold; color: #333;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.title_label)

        self.status_label = QLabel("Status: INITIALIZING...")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"font-size: {fs_status}px; font-weight: bold; color: #FF9800;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.status_label)

        self.weight_label = QLabel("Weight:\n0.00 kg")
        self.weight_label.setStyleSheet(
            f"font-size: {fs_weight}px; font-weight: bold; color: #1565C0; "
            f"background: white; border: 3px solid #ccc; border-radius: 8px; padding: 6px;"
        )
        self.weight_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.weight_label)

        self.finish_btn = QPushButton("Finish &\nCalculate")
        self.finish_btn.setMinimumHeight(btn_h)
        self.finish_btn.setStyleSheet(
            f"font-size: {fs_btn}px; font-weight: bold; "
            f"background-color: #f44336; color: white; border-radius: 8px;"
        )
        self.finish_btn.clicked.connect(self.accept)
        info_layout.addWidget(self.finish_btn)

        root_layout.addLayout(info_layout)
        self.setLayout(root_layout)

    # ── State machine ────────────────────────────────────────────────────────

    def _init_state_machine(self):
        self.system_state = "IDLE"
        self.is_qualified = False

        self.feed_timer = QTimer(self)
        self.feed_timer.timeout.connect(self._update_feed)
        self.feed_timer.start(60)

        self._reset_for_next_object()

    def _update_feed(self):
        self._render_camera_frame()
        self._poll_sensor()

    def _render_camera_frame(self):
        try:
            frame = self.picam2.capture_array("main")
            frame = frame[:, :, ::-1].copy()
            h, w, ch = frame.shape
            qimg  = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg).scaled(
                self.CAM_W, self.CAM_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._draw_overlay(pixmap)
            self.camera_label.setPixmap(pixmap)
        except Exception:
            pass

    def _draw_overlay(self, pixmap: QPixmap):
        if self.system_state not in ("SCANNING", "SORTING"):
            return
        painter = QPainter(pixmap)
        painter.setFont(QFont("Arial", max(10, int(14 * self.CAM_W / 640)), QFont.Weight.Bold))

        if self.is_qualified:
            pen = QPen(QColor(0, 255, 0))
            pen.setWidth(4)
            painter.setPen(pen)
            x, y   = int(pixmap.width() * 0.18), int(pixmap.height() * 0.18)
            bw, bh = int(pixmap.width() * 0.62), int(pixmap.height() * 0.62)
            painter.drawRect(x, y, bw, bh)
            painter.drawText(x + 5, y + 20, f"QUALIFIED: {self.material}")
        else:
            pen = QPen(QColor(255, 0, 0))
            pen.setWidth(4)
            painter.setPen(pen)
            x, y   = int(pixmap.width() * 0.22), int(pixmap.height() * 0.25)
            bw, bh = int(pixmap.width() * 0.53), int(pixmap.height() * 0.50)
            painter.drawRect(x, y, bw, bh)
            painter.drawText(x + 5, y + 20, "REJECT: Foreign Object")
        painter.end()

    def _poll_sensor(self):
        if self.system_state != "WAITING":
            return

        if self.MOCK_ULTRASONIC:
            object_detected = random.random() < 0.01
        else:
            raw_dist = self.ultrasonic.distance
            # Clamp negative/invalid readings
            dist_cm  = max(0.0, raw_dist * 100)
            object_detected = 0 < dist_cm < 10.0

        if object_detected:
            # Debounce — require 3 consecutive detections before triggering
            self._detect_count = getattr(self, '_detect_count', 0) + 1
            if self._detect_count < 3:
                return
            self._detect_count = 0
            self.system_state = "DETECTED"
            self._conveyor_off()
            self.status_label.setText("Status: Object Detected.\nStabilizing...")
            self.status_label.setStyleSheet("color: #FF9800;")
            QTimer.singleShot(DETECT_STABILIZE_MS, self._scan_and_actuate)
        else:
            self._detect_count = 0

    def _scan_and_actuate(self):
        self.system_state = "SCANNING"
        self.status_label.setText("Status: Scanning Object...")

        # Weight reading
        if not self.MOCK_WEIGHT and hasattr(self, "hx") and self.hx:
            try:
                weight_g = self.hx.get_weight_mean(readings=5)
                self.current_weight += max(0.0, weight_g / 1000)
            except Exception:
                self.current_weight += random.uniform(0.02, 0.05)
        else:
            self.current_weight += random.uniform(0.02, 0.05)

        self.weight_label.setText(f"Weight:\n{self.current_weight:.2f} kg")

        # Qualification — random until AI is integrated
        self.is_qualified = random.choices([True, False], weights=[70, 30], k=1)[0]
        self.system_state = "SORTING"

        if self.is_qualified:
            self.status_label.setText("Status: QUALIFIED\n(Right bin)")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self._servo_go(PW_QUALIFIED)
        else:
            self.status_label.setText("Status: REJECT\n(Left bin)")
            self.status_label.setStyleSheet("color: #f44336;")
            self._servo_go(PW_REJECT)

        QTimer.singleShot(SORT_DWELL_MS, self._reset_for_next_object)

    def _reset_for_next_object(self):
        self.system_state = "WAITING"
        self._servo_neutral()
        self._conveyor_on()
        self.status_label.setText("Status: Conveyor Running.\nWaiting for object...")
        self.status_label.setStyleSheet("color: #2196F3;")

    # ── Coin dispensing ──────────────────────────────────────────────────────

    def dispense_coins(self, total_php: float):
        coins = _break_into_coins(total_php)
        if not coins:
            return
        self._dispense_queue = []
        for denom in sorted(coins.keys(), reverse=True):
            for _ in range(coins[denom]):
                self._dispense_queue.append(denom)
        self._dispense_next()

    def _dispense_next(self):
        if not self._dispense_queue:
            self.status_label.setText("Status: Payout complete!")
            self.status_label.setStyleSheet("color: #4CAF50;")
            return

        denom = self._dispense_queue.pop(0)
        self.status_label.setText(f"Dispensing ₱{denom} coin...")
        self.status_label.setStyleSheet("color: #9C27B0;")

        if not self.MOCK_COINS and hasattr(self, "coin_servos") and denom in self.coin_servos:
            self.coin_servos[denom].angle = COIN_DISPENSE_ANGLE
        else:
            print(f"[MOCK] Dispense ₱{denom}")

        QTimer.singleShot(COIN_DISPENSE_MS, lambda: self._return_coin_servo(denom))

    def _return_coin_servo(self, denom: int):
        if not self.MOCK_COINS and hasattr(self, "coin_servos") and denom in self.coin_servos:
            self.coin_servos[denom].angle = COIN_NEUTRAL_ANGLE
        QTimer.singleShot(COIN_RETURN_MS, self._dispense_next)

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def get_final_weight(self) -> float:
        self.feed_timer.stop()
        self._conveyor_off()
        self._set_servo_pulse(PW_NEUTRAL)
        self.picam2.stop()
        self.picam2.close()
        return round(self.current_weight, 2)

    def _stop_all(self):
        self.feed_timer.stop()
        self._conveyor_off()
        if hasattr(self, "sorter_servo"):
            self._set_servo_pulse(PW_NEUTRAL)
            self.sorter_servo.close()
        if hasattr(self, "motor_in1"):
            self.motor_in1.close()
            self.motor_in2.close()
        if hasattr(self, "pca") and self.pca:
            self.pca.deinit()
        if hasattr(self, "picam2"):
            self.picam2.stop()
            self.picam2.close()

    def accept(self):
        self._stop_all()
        super().accept()

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)