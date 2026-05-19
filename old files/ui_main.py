import os
from datetime import datetime
from gpiozero import Servo, OutputDevice, DistanceSensor
import random
from picamera2 import Picamera2
from PyQt6.QtWidgets import (QWidget, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QHBoxLayout, QMessageBox, QTabWidget,
                             QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
                             QApplication, QSizePolicy)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen, QFont, QImage
from keyboard import install_keyboard
import database


def screen_size():
    """Returns the primary screen width and height."""
    screen = QApplication.primaryScreen().size()
    return screen.width(), screen.height()


# --- 1. The Live Hardware Transaction Dialog ---
class ActualTransactionDialog(QDialog):
    def __init__(self, material, parent=None):
        super().__init__(parent)
        self.material = material
        self.current_weight = 0.00
        self.setWindowTitle(f"Sorting {material}...")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()  # e.g. 800 x 480 for 7" DSI

        # Camera preview fills ~55% of screen width, preserving 4:3 ratio
        self.CAM_W = int(SW * 0.55)
        self.CAM_H = int(self.CAM_W * 3 / 4)

        # Scale factor for fonts/buttons relative to a 800px baseline
        scale = SW / 800

        # --- DEV TOGGLE ---
        self.MOCK_HARDWARE = True

        # --- HARDWARE INITIALIZATION ---
        if not self.MOCK_HARDWARE:
            try:
                self.sorter_servo = Servo(18, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000)
                self.conveyor_motor = OutputDevice(27)
                self.ultrasonic = DistanceSensor(echo=24, trigger=23, max_distance=1.0, threshold_distance=0.1)
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"GPIO setup failed: {e}")
                self.reject()
        else:
            print("RUNNING IN MOCK HARDWARE MODE - No GPIO pins required.")

        # Initialize Picamera2
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": (self.CAM_W, self.CAM_H), "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()

        # --- UI LAYOUT (horizontal split: camera left, info right) ---
        root_layout = QHBoxLayout()
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # -- Left: Camera --
        self.camera_label = QLabel()
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setFixedSize(self.CAM_W, self.CAM_H)
        self.camera_label.setStyleSheet(
            "background-color: black; border: 3px solid #333; border-radius: 8px;"
        )
        self.camera_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root_layout.addWidget(self.camera_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # -- Right: Info panel --
        info_layout = QVBoxLayout()
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.setSpacing(int(8 * scale))

        fs_title  = max(14, int(20 * scale))
        fs_status = max(13, int(17 * scale))
        fs_weight = max(18, int(28 * scale))
        fs_btn    = max(13, int(18 * scale))
        btn_h     = max(50, int(70 * scale))

        self.title_label = QLabel(f"Active Sorting:\n{material}")
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

        # --- SYSTEM STATE ---
        self.system_state = "IDLE"
        self.is_qualified = False

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_feed)
        self.timer.start(60)

        self.reset_for_next_object()

    def update_feed(self):
        try:
            frame = self.picam2.capture_array("main")
            frame = frame[:, :, ::-1].copy()
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            pixmap = pixmap.scaled(
                self.CAM_W, self.CAM_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            painter = QPainter(pixmap)
            painter.setFont(QFont("Arial", max(10, int(14 * self.CAM_W / 640)), QFont.Weight.Bold))

            if self.system_state in ("SCANNING", "SORTING"):
                if self.is_qualified:
                    pen = QPen(QColor(0, 255, 0))
                    pen.setWidth(4)
                    painter.setPen(pen)
                    x, y = int(pixmap.width() * 0.18), int(pixmap.height() * 0.18)
                    bw, bh = int(pixmap.width() * 0.62), int(pixmap.height() * 0.62)
                    painter.drawRect(x, y, bw, bh)
                    painter.drawText(x + 5, y + 20, f"QUALIFIED: {self.material}")
                else:
                    pen = QPen(QColor(255, 0, 0))
                    pen.setWidth(4)
                    painter.setPen(pen)
                    x, y = int(pixmap.width() * 0.22), int(pixmap.height() * 0.25)
                    bw, bh = int(pixmap.width() * 0.53), int(pixmap.height() * 0.50)
                    painter.drawRect(x, y, bw, bh)
                    painter.drawText(x + 5, y + 20, "REJECT: Foreign Object")

            painter.end()
            self.camera_label.setPixmap(pixmap)

        except Exception:
            pass

        # --- SENSOR POLLING ---
        if self.system_state == "WAITING":
            object_detected = False

            if self.MOCK_HARDWARE:
                if random.random() < 0.01:
                    object_detected = True
            else:
                if self.ultrasonic.distance < 0.10:
                    object_detected = True

            if object_detected:
                self.system_state = "DETECTED"
                if not self.MOCK_HARDWARE:
                    self.conveyor_motor.off()
                self.status_label.setText("Status: Object Detected. Stabilizing...")
                self.status_label.setStyleSheet("color: #FF9800;")
                QTimer.singleShot(500, self.scan_and_actuate)

    def scan_and_actuate(self):
        self.system_state = "SCANNING"
        self.status_label.setText("Status: Scanning Object...")

        self.is_qualified = random.choices([True, False], weights=[70, 30], k=1)[0]

        self.system_state = "SORTING"
        if self.is_qualified:
            self.status_label.setText("Status: QUALIFIED\n(Right)")
            self.status_label.setStyleSheet("color: #4CAF50;")
            if not self.MOCK_HARDWARE:
                self.sorter_servo.max()
            self.current_weight += random.uniform(0.02, 0.05)
            self.weight_label.setText(f"Weight:\n{self.current_weight:.2f} kg")
        else:
            self.status_label.setText("Status: REJECT\n(Left)")
            self.status_label.setStyleSheet("color: #f44336;")
            if not self.MOCK_HARDWARE:
                self.sorter_servo.min()

        if not self.MOCK_HARDWARE:
            self.conveyor_motor.on()

        QTimer.singleShot(2000, self.reset_for_next_object)

    def reset_for_next_object(self):
        self.system_state = "WAITING"
        if not self.MOCK_HARDWARE:
            self.sorter_servo.mid()
            self.conveyor_motor.on()
        self.status_label.setText("Status: Conveyor Running.\nWaiting for object...")
        self.status_label.setStyleSheet("color: #2196F3;")

    def get_final_weight(self):
        self.timer.stop()
        if not self.MOCK_HARDWARE:
            self.conveyor_motor.off()
            self.sorter_servo.detach()
        self.picam2.stop()
        self.picam2.close()
        return round(self.current_weight, 2)

    def closeEvent(self, event):
        self.timer.stop()
        if not self.MOCK_HARDWARE:
            if hasattr(self, 'conveyor_motor'):
                self.conveyor_motor.off()
                self.conveyor_motor.close()
            if hasattr(self, 'sorter_servo'):
                self.sorter_servo.detach()
                self.sorter_servo.close()
        if hasattr(self, 'picam2'):
            self.picam2.stop()
            self.picam2.close()
        super().closeEvent(event)

    def accept(self):
        self.timer.stop()
        if not self.MOCK_HARDWARE:
            self.conveyor_motor.off()
            self.sorter_servo.detach()
        self.picam2.stop()
        self.picam2.close()
        super().accept()


# --- 2. The AI Training Data Collection Dialog ---
class DataCollectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Collection")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        scale = SW / 800

        # Camera fills left ~60% of width
        self.CAM_W = int(SW * 0.58)
        self.CAM_H = int(self.CAM_W * 3 / 4)
        # If camera taller than screen, shrink to fit
        max_cam_h = SH - 20
        if self.CAM_H > max_cam_h:
            self.CAM_H = max_cam_h
            self.CAM_W = int(self.CAM_H * 4 / 3)

        self.base_dir = "dataset"
        self.categories = ["pet_qualified", "pet_reject", "metal_qualified", "metal_reject"]
        for cat in self.categories:
            os.makedirs(os.path.join(self.base_dir, cat), exist_ok=True)

        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": (self.CAM_W, self.CAM_H), "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Left: Camera
        self.camera_label = QLabel()
        self.camera_label.setFixedSize(self.CAM_W, self.CAM_H)
        self.camera_label.setStyleSheet(
            "background-color: black; border: 3px solid #333; border-radius: 8px;"
        )
        main_layout.addWidget(self.camera_label, alignment=Qt.AlignmentFlag.AlignVCenter)

        # Right: Buttons
        fs_title = max(13, int(18 * scale))
        fs_btn   = max(12, int(16 * scale))
        btn_h    = max(45, int(60 * scale))

        btn_layout = QVBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.setSpacing(int(6 * scale))

        title = QLabel("Capture\nTraining Data")
        title.setStyleSheet(f"font-size: {fs_title}px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(title)

        self.btn_pq = QPushButton("PET Qualified")
        self.btn_pr = QPushButton("PET Reject")
        self.btn_mq = QPushButton("Metal Qualified")
        self.btn_mr = QPushButton("Metal Reject")

        btns = [
            (self.btn_pq, "pet_qualified", "#4CAF50"),
            (self.btn_pr, "pet_reject", "#f44336"),
            (self.btn_mq, "metal_qualified", "#2196F3"),
            (self.btn_mr, "metal_reject", "#FF9800"),
        ]

        for btn, cat, color in btns:
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(
                f"font-size: {fs_btn}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 8px;"
            )
            btn.clicked.connect(lambda checked, c=cat: self.capture_image(c))
            btn_layout.addWidget(btn)

        self.exit_btn = QPushButton("Exit Camera")
        self.exit_btn.setMinimumHeight(btn_h)
        self.exit_btn.setStyleSheet(
            f"font-size: {fs_btn}px; font-weight: bold; "
            f"background-color: #9e9e9e; color: white; border-radius: 8px; margin-top: 10px;"
        )
        self.exit_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.exit_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        self.current_qimg = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_feed)
        self.timer.start(60)

    def update_feed(self):
        try:
            frame = self.picam2.capture_array("main")
            frame = frame[:, :, ::-1].copy()
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            self.current_qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(self.current_qimg)
            pixmap = pixmap.scaled(
                self.CAM_W, self.CAM_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.camera_label.setPixmap(pixmap)
        except Exception:
            pass

    def capture_image(self, category):
        if self.current_qimg:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath = os.path.join(self.base_dir, category, f"{timestamp}.jpg")
            self.current_qimg.save(filepath)
            QMessageBox.information(self, "Saved", f"Image saved to:\n{category}")

    def accept(self):
        self.timer.stop()
        self.picam2.stop()
        self.picam2.close()
        super().accept()

    def closeEvent(self, event):
        self.timer.stop()
        if hasattr(self, 'picam2'):
            self.picam2.stop()
            self.picam2.close()
        super().closeEvent(event)


# --- 3. Hardware Diagnostic Test Dialog ---
class HardwareTestDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Hardware Diagnostics")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        scale = SW / 800
        fs   = max(13, int(18 * scale))
        btn_h = max(50, int(70 * scale))

        try:
            self.sorter_servo = Servo(18, min_pulse_width=0.5/1000, max_pulse_width=2.5/1000)
            self.conveyor_motor = OutputDevice(27)
        except Exception as e:
            QMessageBox.critical(self, "Hardware Error", f"Failed to connect to GPIO.\nError: {e}")
            self.reject()

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(10 * scale))
        main_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("Hardware Diagnostic Mode")
        title.setStyleSheet(f"font-size: {max(16, int(24*scale))}px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Conveyor
        conveyor_label = QLabel("DC Motor: Conveyor Belt")
        conveyor_label.setStyleSheet(f"font-size: {fs}px; font-weight: bold;")
        conveyor_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(conveyor_label)

        conveyor_btn_layout = QHBoxLayout()
        self.btn_conv_start = QPushButton("Start Conveyor")
        self.btn_conv_start.setMinimumHeight(btn_h)
        self.btn_conv_start.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #4CAF50; color: white; border-radius: 8px;")
        self.btn_conv_start.clicked.connect(self.conveyor_motor.on)
        conveyor_btn_layout.addWidget(self.btn_conv_start)

        self.btn_conv_stop = QPushButton("Stop Conveyor")
        self.btn_conv_stop.setMinimumHeight(btn_h)
        self.btn_conv_stop.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #f44336; color: white; border-radius: 8px;")
        self.btn_conv_stop.clicked.connect(self.conveyor_motor.off)
        conveyor_btn_layout.addWidget(self.btn_conv_stop)
        main_layout.addLayout(conveyor_btn_layout)

        # Servo
        servo_label = QLabel("MG996R: Sorter Alignment")
        servo_label.setStyleSheet(f"font-size: {fs}px; font-weight: bold;")
        servo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(servo_label)

        servo_btn_layout = QHBoxLayout()
        for label, color, fn in [
            ("Left (Reject)",      "#FF9800", self.sorter_servo.min),
            ("Center (Neutral)",   "#2196F3", self.sorter_servo.mid),
            ("Right (Qualified)",  "#8BC34A", self.sorter_servo.max),
        ]:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: {color}; color: white; border-radius: 8px;")
            btn.clicked.connect(fn)
            servo_btn_layout.addWidget(btn)
        main_layout.addLayout(servo_btn_layout)

        self.exit_btn = QPushButton("Exit Hardware Test")
        self.exit_btn.setMinimumHeight(btn_h)
        self.exit_btn.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #9e9e9e; color: white; border-radius: 8px;")
        self.exit_btn.clicked.connect(self.accept)
        main_layout.addWidget(self.exit_btn)

        self.setLayout(main_layout)

    def _cleanup(self):
        if hasattr(self, 'conveyor_motor'):
            self.conveyor_motor.off()
            self.conveyor_motor.close()
        if hasattr(self, 'sorter_servo'):
            self.sorter_servo.detach()
            self.sorter_servo.close()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)

    def accept(self):
        self._cleanup()
        super().accept()


# --- 4. Weight Sensor (Load Cell) Test Dialog ---
class WeightSensorTestDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Weight Sensor Test")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        scale = SW / 800
        fs     = max(13, int(18 * scale))
        fs_big = max(30, int(60 * scale))
        btn_h  = max(50, int(70 * scale))

        self.MOCK_HARDWARE = True
        self.mock_weight = 0.00

        if not self.MOCK_HARDWARE:
            try:
                from hx711_multi import HX711
                self.hx = HX711(dout_pins=[5], sck_pin=6)
                self.hx.tare()
            except ImportError:
                QMessageBox.warning(self, "Library Missing", "Please install the HX711 library.")
                self.MOCK_HARDWARE = True
            except Exception as e:
                QMessageBox.critical(self, "Hardware Error", f"HX711 setup failed: {e}")
                self.MOCK_HARDWARE = True

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(10 * scale))
        main_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("Load Cell & HX711 Diagnostics")
        title.setStyleSheet(f"font-size: {max(16, int(22*scale))}px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        self.reading_label = QLabel("0.00 kg")
        self.reading_label.setStyleSheet(
            f"font-size: {fs_big}px; font-weight: bold; color: #1565C0; "
            f"background-color: white; border: 4px solid #ccc; border-radius: 12px; padding: 10px;"
        )
        self.reading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.reading_label)

        btn_layout = QHBoxLayout()

        self.btn_tare = QPushButton("Tare (Zero Scale)")
        self.btn_tare.setMinimumHeight(btn_h)
        self.btn_tare.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #FF9800; color: white; border-radius: 8px;")
        self.btn_tare.clicked.connect(self.tare_scale)
        btn_layout.addWidget(self.btn_tare)

        if self.MOCK_HARDWARE:
            self.btn_sim_add = QPushButton("Simulate +100g")
            self.btn_sim_add.setMinimumHeight(btn_h)
            self.btn_sim_add.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #4CAF50; color: white; border-radius: 8px;")
            self.btn_sim_add.clicked.connect(self.simulate_weight)
            btn_layout.addWidget(self.btn_sim_add)

        main_layout.addLayout(btn_layout)

        self.exit_btn = QPushButton("Exit Hardware Test")
        self.exit_btn.setMinimumHeight(btn_h)
        self.exit_btn.setStyleSheet(f"font-size: {fs}px; font-weight: bold; background-color: #9e9e9e; color: white; border-radius: 8px;")
        self.exit_btn.clicked.connect(self.accept)
        main_layout.addWidget(self.exit_btn)

        self.setLayout(main_layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_weight_reading)
        self.timer.start(500)

    def update_weight_reading(self):
        if self.MOCK_HARDWARE:
            display_weight = self.mock_weight + random.uniform(-0.002, 0.002)
            self.reading_label.setText(f"{display_weight:.3f} kg")
        else:
            try:
                raw_val = self.hx.get_weight_mean(readings=5)
                self.reading_label.setText(f"{raw_val:.3f} kg")
            except Exception:
                self.reading_label.setText("Error Reading")

    def tare_scale(self):
        if self.MOCK_HARDWARE:
            self.mock_weight = 0.00
            self.reading_label.setText("0.000 kg")
        else:
            self.reading_label.setText("Taring...")
            self.hx.zero()

    def simulate_weight(self):
        self.mock_weight += 0.100

    def accept(self):
        self.timer.stop()
        super().accept()


# --- 5. Main Window ---
class MainWindow(QWidget):
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.setWindowTitle("RTL Junkshop System")
        self.showFullScreen()

        SW, SH = screen_size()
        scale = SW / 800

        self.setStyleSheet(f"""
            QWidget {{
                font-family: 'Arial';
                font-size: {max(11, int(13*scale))}px;
            }}
            QPushButton {{
                padding: 4px;
                border-radius: 6px;
            }}
            QTabWidget::pane {{
                border: 1px solid #ccc;
                top: -1px;
            }}
            QTabBar::tab {{
                height: {max(32, int(40*scale))}px;
                width: {max(100, int(130*scale))}px;
                font-size: {max(11, int(13*scale))}px;
                background: #f0f0f0;
            }}
            QTabBar::tab:selected {{
                background: #ffffff;
                font-weight: bold;
            }}
            QLineEdit {{
                height: {max(28, int(35*scale))}px;
                font-size: {max(13, int(16*scale))}px;
            }}
        """)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(4, 4, 4, 4)
        self.tabs = QTabWidget()

        fs_large = max(16, int(22 * scale))
        fs_med   = max(13, int(18 * scale))
        btn_h_lg = max(80, int(130 * scale))
        btn_h_sm = max(40, int(55 * scale))

        # --- Transaction Tab ---
        transaction_tab = QWidget()
        transaction_layout = QVBoxLayout()
        transaction_layout.setSpacing(int(8 * scale))

        instruction_label = QLabel("Select material to sell:")
        instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_label.setStyleSheet(f"font-size: {fs_large}px; font-weight: bold; margin-bottom: 8px;")
        transaction_layout.addWidget(instruction_label)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(int(10 * scale))

        self.pet_btn = QPushButton("PET Bottles")
        self.pet_btn.setMinimumHeight(btn_h_lg)
        self.pet_btn.setStyleSheet(f"font-size: {fs_large}px; font-weight: bold; background-color: #4CAF50; color: white; border-radius: 10px;")
        self.pet_btn.clicked.connect(lambda: self.start_sorting("PET"))
        button_layout.addWidget(self.pet_btn)

        self.metal_btn = QPushButton("Metallic Cans")
        self.metal_btn.setMinimumHeight(btn_h_lg)
        self.metal_btn.setStyleSheet(f"font-size: {fs_large}px; font-weight: bold; background-color: #607D8B; color: white; border-radius: 10px;")
        self.metal_btn.clicked.connect(lambda: self.start_sorting("Metal"))
        button_layout.addWidget(self.metal_btn)

        transaction_layout.addLayout(button_layout)

        self.exit_btn = QPushButton("Exit System")
        self.exit_btn.setMinimumHeight(btn_h_sm)
        self.exit_btn.setStyleSheet(f"font-size: {fs_med}px; font-weight: bold; background-color: #f44336; color: white; border-radius: 8px;")
        self.exit_btn.clicked.connect(self.close)
        transaction_layout.addWidget(self.exit_btn)

        transaction_tab.setLayout(transaction_layout)
        self.tabs.addTab(transaction_tab, "New Transaction")

        # --- History Tab ---
        history_tab = QWidget()
        history_layout = QVBoxLayout()

        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(["ID", "Date & Time", "Material", "Weight (kg)", "Total (PHP)"])
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.setStyleSheet(f"font-size: {max(11, int(14*scale))}px;")
        self.history_table.verticalHeader().setDefaultSectionSize(max(30, int(40 * scale)))
        history_layout.addWidget(self.history_table)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setMinimumHeight(btn_h_sm)
        self.refresh_btn.setStyleSheet(f"font-size: {fs_med}px; font-weight: bold; background-color: #FF9800; color: white; border-radius: 8px;")
        self.refresh_btn.clicked.connect(self.load_transaction_history)
        history_layout.addWidget(self.refresh_btn)

        history_tab.setLayout(history_layout)
        self.tabs.addTab(history_tab, "History")

        # --- Admin Settings Tab ---
        if self.username == "admin":
            settings_tab = QWidget()
            settings_layout = QFormLayout()
            settings_layout.setSpacing(int(8 * scale))

            self.pet_price_input = QLineEdit()
            self.metal_price_input = QLineEdit()
            self.load_current_prices()

            label_style = f"font-size: {fs_med}px; font-weight: bold;"
            pet_label = QLabel("PET Bottles Price (PHP/kg):")
            pet_label.setStyleSheet(label_style)
            metal_label = QLabel("Metallic Cans Price (PHP/kg):")
            metal_label.setStyleSheet(label_style)

            settings_layout.addRow(pet_label, self.pet_price_input)
            settings_layout.addRow(metal_label, self.metal_price_input)

            for label, color, slot in [
                ("Save New Prices",                    "#2196F3", self.save_prices),
                ("Open Camera for AI Training",        "#673AB7", self.open_data_collection),
                ("Open Hardware Diagnostics",          "#607D8B", self.open_hardware_test),
                ("Open Weight Sensor (Load Cell) Test","#8D6E63", self.open_weight_test),
            ]:
                btn = QPushButton(label)
                btn.setMinimumHeight(btn_h_sm)
                btn.setStyleSheet(f"font-size: {fs_med}px; font-weight: bold; background-color: {color}; color: white; border-radius: 8px; margin-top: 6px;")
                btn.clicked.connect(slot)
                settings_layout.addRow(btn)

            settings_tab.setLayout(settings_layout)
            self.tabs.addTab(settings_tab, "Admin Settings")

        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        self.load_transaction_history()

        # ✅ Attach keyboards HERE — all inputs exist by this point
        if self.username == "admin":
            install_keyboard(self, numeric_inputs={self.pet_price_input, self.metal_price_input})

    def load_current_prices(self):
        self.pet_price_input.setText(str(database.get_price("PET")))
        self.metal_price_input.setText(str(database.get_price("Metal")))

    def save_prices(self):
        try:
            new_pet = float(self.pet_price_input.text())
            new_metal = float(self.metal_price_input.text())
            database.update_prices(new_pet, new_metal)
            QMessageBox.information(self, "Success", "Prices updated successfully!")
        except ValueError:
            QMessageBox.warning(self, "Error", "Please enter valid numbers for prices.")

    def load_transaction_history(self):
        records = database.get_all_transactions()
        self.history_table.setRowCount(0)
        for row_idx, row_data in enumerate(records):
            self.history_table.insertRow(row_idx)
            for col_idx, data in enumerate(row_data):
                if col_idx in [3, 4]:
                    item = QTableWidgetItem(f"{data:.2f}")
                else:
                    item = QTableWidgetItem(str(data))
                item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                self.history_table.setItem(row_idx, col_idx, item)

    def start_sorting(self, material):
        price_per_kg = database.get_price(material)
        act_dialog = ActualTransactionDialog(material, self)
        if act_dialog.exec():
            final_weight = act_dialog.get_final_weight()
            if final_weight > 0:
                total_payout = final_weight * price_per_kg
                database.log_transaction(material, final_weight, total_payout)
                self.load_transaction_history()
                msg = QMessageBox(self)
                msg.setWindowTitle("Transaction Complete")
                msg.setText(
                    f"Material: {material}\n"
                    f"Final Weight: {final_weight:.2f} kg\n"
                    f"Total Payout: ₱{total_payout:.2f}\n\n"
                    f"Dispensing Coins..."
                )
                msg.setStyleSheet("QLabel{font-size: 16px;}")
                msg.exec()
            else:
                QMessageBox.warning(self, "Cancelled", "No weight detected. Transaction cancelled.")

    def open_data_collection(self):
        DataCollectionDialog(self).exec()

    def open_hardware_test(self):
        HardwareTestDialog(self).exec()

    def open_weight_test(self):
        WeightSensorTestDialog(self).exec()