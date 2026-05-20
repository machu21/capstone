import os
import json
import random
import statistics

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton, QWidget, QProgressBar,
    QVBoxLayout, QHBoxLayout, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QImage
from picamera2 import Picamera2
from gpiozero import Motor, DistanceSensor

from utils import screen_size

os.environ["BLINKA_FORCEBOARD"] = "RASPBERRY_PI_5"

# ── Pin assignments (Raspberry Pi GPIO) ───────────────────────────────────────
PIN_MOTOR_IN1 = 17
PIN_MOTOR_IN2 = 27
PIN_TRIG      = 23
PIN_ECHO      = 24
PIN_HX711_DT  = 5
PIN_HX711_SCK = 6

# ── PCA9685 channels (I2C) ────────────────────────────────────────────────────
PCA9685_ADDRESS = 0x40
SERVO_CHANNEL   = 4
COIN_CHANNELS   = {1: 0, 5: 1, 10: 2, 20: 3}

# ── Servo pulse widths (us) ───────────────────────────────────────────────────
FREQ_HZ      = 50
PW_NEUTRAL   = 1500
PW_REJECT    =  900
PW_QUALIFIED = 2100

COIN_PW_NEUTRAL  =  500
COIN_PW_DISPENSE = 2500

# ── Timing (ms) & Thresholds ─────────────────────────────────────────────────
DETECT_STABILIZE_MS = 800
SORT_DWELL_MS       = 2000
COIN_DISPENSE_MS    = 600
COIN_RETURN_MS      = 400

DETECT_THRESHOLD_M  = 0.20  # 20 cm, matches test_ultrasonic.py

# Assumes dialogs/ folder is adjacent to hardware/ folder
CALIB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hardware", "weight_calibration.json")


def _us_to_duty(us: int) -> int:
    """Convert pulse width in microseconds to PCA9685 16-bit duty cycle."""
    period_us = 1_000_000 / FREQ_HZ
    return int((us / period_us) * 65535)

def _break_into_coins(amount_php: float) -> dict:
    """Rounds to nearest 5 and breaks down into denominations."""
    coins = {}
    remaining = int(round(amount_php / 5.0) * 5)
    for denom in sorted(COIN_CHANNELS.keys(), reverse=True):
        count = remaining // denom
        if count:
            coins[denom] = count
        remaining %= denom
    return coins


class LoadingOverlay(QWidget):
    """A semi-transparent overlay that blocks clicks and shows a loading state."""
    def __init__(self, parent):
        super().__init__(parent)
        # Block mouse clicks from passing through
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background-color: rgba(0, 0, 0, 180);")
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.message_label = QLabel("Please wait...")
        self.message_label.setStyleSheet(
            "color: white; font-size: 24px; font-weight: bold; background: transparent;"
        )
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_label)
        
        self.spinner = QProgressBar()
        self.spinner.setRange(0, 0)  # Animated endless spinner
        self.spinner.setFixedSize(300, 15)
        self.spinner.setTextVisible(False)
        self.spinner.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 7px;
                background-color: #555;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 7px;
            }
        """)
        layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hide()

    def show_message(self, text: str):
        if self.parentWidget():
            self.resize(self.parentWidget().size())
        self.message_label.setText(text)
        self.show()
        self.raise_()


class ActualTransactionDialog(QDialog):
    """
    Live transaction dialog.
    Uses PCA9685 for servos, gpiozero for Motor/Ultrasonic, and median filter for HX711.
    Machine Learning image detection is currently mocked (70% qualified).
    """

    MOCK_ULTRASONIC = False
    MOCK_WEIGHT     = False
    MOCK_SERVOS     = False

    def __init__(self, material: str, parent=None):
        super().__init__(parent)
        self.material       = material
        self.current_weight = 0.00
        self._detect_count  = 0
        self.calib          = {"offset": 0, "units_per_kg": 1.0}

        self.setWindowTitle(f"Sorting {material}...")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        self.CAM_W = int(SW * 0.55)
        self.CAM_H = int(self.CAM_W * 3 / 4)
        scale = SW / 800

        self._pca = None

        self._init_motors()
        self._init_pca9685()
        self._init_camera()

        if not self.MOCK_ULTRASONIC:
            self._init_ultrasonic()
        if not self.MOCK_WEIGHT:
            self._init_hx711()

        self._build_ui(scale)
        self._init_state_machine()
        
        # Initialize the loading overlay last so it sits on top of everything
        self.overlay = LoadingOverlay(self)

    # ── Hardware init ─────────────────────────────────────────────────────────

    def _init_motors(self):
        """Init DC Conveyor Motor via gpiozero."""
        try:
            self.conveyor = Motor(forward=PIN_MOTOR_IN1, backward=PIN_MOTOR_IN2)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"Conveyor init failed:\n{e}")
            self.reject()

    def _init_pca9685(self):
        """Init PCA9685 for Sorter and Coin servos."""
        try:
            import board                          # type: ignore
            import busio                          # type: ignore
            from adafruit_pca9685 import PCA9685  # type: ignore

            i2c = busio.I2C(board.SCL, board.SDA)
            self._pca = PCA9685(i2c, address=PCA9685_ADDRESS)
            self._pca.frequency = FREQ_HZ

            # Send all servos to neutral on startup
            self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(PW_NEUTRAL)
            for ch in COIN_CHANNELS.values():
                self._pca.channels[ch].duty_cycle = _us_to_duty(COIN_PW_NEUTRAL)
            
            # Cut PWM for ONLY coin dispensers to stop jitter.
            # Sorter servo remains ON to fight the rubber band.
            QTimer.singleShot(600, self._stop_all_pca_pulses)
            
        except Exception as e:
            print(f"PCA9685 init failed, running servos in MOCK mode:\n{e}")
            self.MOCK_SERVOS = True

    def _init_ultrasonic(self):
        try:
            self.ultrasonic = DistanceSensor(
                echo=PIN_ECHO, trigger=PIN_TRIG,
                max_distance=2.0, threshold_distance=DETECT_THRESHOLD_M,
            )
        except Exception as e:
            print(f"Ultrasonic init failed:\n{e}")
            self.MOCK_ULTRASONIC = True

    def _init_hx711(self):
        try:
            import RPi.GPIO as GPIO  # type: ignore
            from hx711 import HX711  # type: ignore
            GPIO.setmode(GPIO.BCM)
            self.hx = HX711(dout_pin=PIN_HX711_DT, pd_sck_pin=PIN_HX711_SCK)
            self.hx.reset()

            if os.path.exists(CALIB_FILE):
                with open(CALIB_FILE, "r") as f:
                    data = json.load(f)
                    if "offset" in data and "units_per_kg" in data:
                        self.calib = data
                        print(f"Loaded Weight Calib: {self.calib}")
            else:
                print("WARNING: weight_calibration.json not found!")
                
        except Exception as e:
            print(f"HX711 init failed:\n{e}")
            self.MOCK_WEIGHT = True

    def _init_camera(self):
        try:
            self.picam2 = Picamera2()
            config = self.picam2.create_preview_configuration(
                main={"size": (self.CAM_W, self.CAM_H), "format": "RGB888"}
            )
            self.picam2.configure(config)
            self.picam2.start()
        except Exception as e:
            print(f"Camera init failed:\n{e}")

    # ── Actuator helpers ──────────────────────────────────────────────────────

    def _conveyor_on(self):
        if getattr(self, "conveyor", None) is not None:
            try:
                self.conveyor.forward()
            except Exception:
                pass

    def _conveyor_off(self):
        if getattr(self, "conveyor", None) is not None:
            try:
                self.conveyor.stop()
            except Exception:
                pass

    def _servo_go(self, pw: int):
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            try:
                # We leave the duty cycle ON so the MG996R actively fights the rubber band
                self._pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(pw)
            except Exception:
                pass

    def _servo_neutral(self):
        self._servo_go(PW_NEUTRAL)

    def _stop_all_pca_pulses(self):
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            try:
                # ONLY stop coin servos so they don't overheat.
                for ch in COIN_CHANNELS.values():
                    self._pca.channels[ch].duty_cycle = 0
            except Exception:
                pass

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float):
        fs_title  = max(14, int(20 * scale))
        fs_status = max(13, int(17 * scale))
        fs_weight = max(18, int(28 * scale))
        fs_btn    = max(13, int(18 * scale))
        btn_h     = max(50, int(70 * scale))

        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        self.camera_label = QLabel()
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setFixedSize(self.CAM_W, self.CAM_H)
        self.camera_label.setStyleSheet(
            "background-color: black; border: 3px solid #333; border-radius: 8px;"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root_layout.addWidget(self.camera_label, alignment=Qt.AlignmentFlag.AlignVCenter)

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
        # Connect to payout instead of immediately accepting
        self.finish_btn.clicked.connect(self._start_payout)
        info_layout.addWidget(self.finish_btn)

        root_layout.addLayout(info_layout)
        self.setLayout(root_layout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'overlay'):
            self.overlay.resize(self.size())

    # ── State machine ─────────────────────────────────────────────────────────

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
        if not hasattr(self, "picam2") or self.picam2 is None: return
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

        if self.MOCK_ULTRASONIC or not hasattr(self, "ultrasonic") or self.ultrasonic is None:
            object_detected = random.random() < 0.01
        else:
            try:
                raw_dist = self.ultrasonic.distance
                dist_cm  = max(0.0, raw_dist * 100)
                object_detected = 0 < dist_cm < (DETECT_THRESHOLD_M * 100)
            except Exception:
                object_detected = False

        if object_detected:
            self._detect_count += 1
            if self._detect_count >= 2:
                self._detect_count  = 0
                self.system_state   = "DETECTED"
                self._conveyor_off()
                self.status_label.setText("Status: Object Detected.\nStabilizing...")
                self.status_label.setStyleSheet("color: #FF9800;")
                QTimer.singleShot(DETECT_STABILIZE_MS, self._scan_and_actuate)
        else:
            self._detect_count = max(0, self._detect_count - 1)

    def _get_raw_median(self, times: int = 5) -> float | None:
        """Gets raw ADC data and applies median filter to ignore OS spikes."""
        if not hasattr(self, "hx"): return None
        try:
            data = self.hx.get_raw_data(times=times)
            if data and len(data) >= 3:
                return statistics.median(data)
            elif data and len(data) > 0:
                return sum(data) / len(data)
        except Exception:
            pass
        return None

    def _scan_and_actuate(self):
        self.system_state = "SCANNING"
        self.status_label.setText("Status: Scanning Object...")

        if not self.MOCK_WEIGHT:
            raw = self._get_raw_median(times=10)
            if raw is not None:
                kg = (raw - self.calib["offset"]) / self.calib["units_per_kg"]
                if kg > 0:
                    self.current_weight += kg
        else:
            self.current_weight += random.uniform(0.02, 0.05)

        self.weight_label.setText(f"Weight:\n{self.current_weight:.2f} kg")

        # Mock Machine Learning classification
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

    # ── Payout & Coin Dispensing ──────────────────────────────────────────────

    def _start_payout(self):
        """Stops sorting, shows loading UI, and begins payout sequence."""
        self.finish_btn.setEnabled(False)
        self.overlay.show_message("Calculating and Dispensing...\nPlease keep your hands clear.")
        
        self.feed_timer.stop()
        self._conveyor_off()
        
        # Shut off sorter servo safely since we are done sorting
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            try:
                self._pca.channels[SERVO_CHANNEL].duty_cycle = 0
            except Exception:
                pass

        # ---- SET YOUR PRICES HERE ----
        PRICE_PER_KG = 30.0  # e.g., 30 pesos per kg
        total_php = self.current_weight * PRICE_PER_KG
        
        self.dispense_coins(total_php)

    def dispense_coins(self, total_php: float):
        rounded_total = int(round(total_php / 5.0) * 5)
        
        if rounded_total <= 0:
            self.status_label.setText("Status: Payout complete! (Amount rounded to ₱0)")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.overlay.message_label.setText("Payout Complete!\nClosing...")
            QTimer.singleShot(2000, self.accept)
            return
            
        coins = _break_into_coins(total_php)
        if not coins:
            self.overlay.message_label.setText("Payout Complete!\nClosing...")
            QTimer.singleShot(2000, self.accept)
            return
            
        self._dispense_queue = []
        for denom in sorted(coins.keys(), reverse=True):
            for _ in range(coins[denom]):
                self._dispense_queue.append(denom)
                
        self.status_label.setText(f"Dispensing ₱{rounded_total} total...")
        self._dispense_next()

    def _dispense_next(self):
        if not self._dispense_queue:
            self.status_label.setText("Status: Payout complete!")
            self.status_label.setStyleSheet("color: #4CAF50;")
            self.overlay.message_label.setText("Payout Complete!\nClosing...")
            QTimer.singleShot(2000, self.accept)
            return

        denom = self._dispense_queue.pop(0)
        self.status_label.setText(f"Dispensing ₱{denom} coin...")
        self.status_label.setStyleSheet("color: #9C27B0;")

        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            ch = COIN_CHANNELS.get(denom)
            if ch is not None:
                self._pca.channels[ch].duty_cycle = _us_to_duty(COIN_PW_DISPENSE)
        else:
            print(f"[MOCK] Dispense ₱{denom}")

        QTimer.singleShot(COIN_DISPENSE_MS, lambda: self._return_coin_servo(denom))

    def _return_coin_servo(self, denom: int):
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            ch = COIN_CHANNELS.get(denom)
            if ch is not None:
                self._pca.channels[ch].duty_cycle = _us_to_duty(COIN_PW_NEUTRAL)
        
        QTimer.singleShot(COIN_RETURN_MS, lambda: self._stop_coin_servo_and_continue(denom))

    def _stop_coin_servo_and_continue(self, denom: int):
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            ch = COIN_CHANNELS.get(denom)
            if ch is not None:
                self._pca.channels[ch].duty_cycle = 0
        self._dispense_next()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def get_final_weight(self) -> float:
        self._stop_all()
        return round(self.current_weight, 2)

    def _stop_all(self):
        """Strict hardware cleanup that is safe to call multiple times."""
        self.feed_timer.stop()
        self._conveyor_off()
        
        # Cleanup Motor
        if getattr(self, "conveyor", None) is not None:
            try:
                self.conveyor.close()
            except Exception:
                pass
            self.conveyor = None

        # Cleanup Ultrasonic
        if getattr(self, "ultrasonic", None) is not None:
            try:
                self.ultrasonic.close()
            except Exception:
                pass
            self.ultrasonic = None

        # Cleanup PCA9685
        if not self.MOCK_SERVOS and getattr(self, "_pca", None) is not None:
            try:
                self._pca.channels[SERVO_CHANNEL].duty_cycle = 0
                for ch in COIN_CHANNELS.values():
                    self._pca.channels[ch].duty_cycle = 0
                self._pca.deinit()
            except Exception:
                pass
            self._pca = None
            
        # Cleanup Camera
        if getattr(self, "picam2", None) is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None

    def accept(self):
        self._stop_all()
        super().accept()

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)