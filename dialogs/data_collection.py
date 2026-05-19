import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap, QImage
from picamera2 import Picamera2

from utils import screen_size


class DataCollectionDialog(QDialog):
    """Camera dialog for capturing labelled training images."""

    CATEGORIES = ["pet_qualified", "pet_reject", "metal_qualified", "metal_reject"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Collection")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, SH = screen_size()
        scale = SW / 800

        self.CAM_W = int(SW * 0.58)
        self.CAM_H = int(self.CAM_W * 3 / 4)
        max_cam_h  = SH - 20
        if self.CAM_H > max_cam_h:
            self.CAM_H = max_cam_h
            self.CAM_W = int(self.CAM_H * 4 / 3)

        self._setup_dataset_dirs()
        self._init_camera()
        self._build_ui(scale)

        self.current_qimg = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_feed)
        self.timer.start(60)

    # ── Setup ────────────────────────────────────────────────────────────────

    def _setup_dataset_dirs(self):
        self.base_dir = "dataset"
        for cat in self.CATEGORIES:
            os.makedirs(os.path.join(self.base_dir, cat), exist_ok=True)

    def _init_camera(self):
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(
            main={"size": (self.CAM_W, self.CAM_H), "format": "RGB888"}
        )
        self.picam2.configure(config)
        self.picam2.start()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float):
        fs_title = max(13, int(18 * scale))
        fs_btn   = max(12, int(16 * scale))
        btn_h    = max(45, int(60 * scale))

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Left – camera preview
        self.camera_label = QLabel()
        self.camera_label.setFixedSize(self.CAM_W, self.CAM_H)
        self.camera_label.setStyleSheet(
            "background-color: black; border: 3px solid #333; border-radius: 8px;"
        )
        main_layout.addWidget(
            self.camera_label, alignment=Qt.AlignmentFlag.AlignVCenter
        )

        # Right – capture buttons
        btn_layout = QVBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.setSpacing(int(6 * scale))

        title = QLabel("Capture\nTraining Data")
        title.setStyleSheet(f"font-size: {fs_title}px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_layout.addWidget(title)

        buttons = [
            ("PET Qualified",   "pet_qualified",   "#4CAF50"),
            ("PET Reject",      "pet_reject",      "#f44336"),
            ("Metal Qualified", "metal_qualified", "#2196F3"),
            ("Metal Reject",    "metal_reject",    "#FF9800"),
        ]
        for label, category, color in buttons:
            btn = QPushButton(label)
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(
                f"font-size: {fs_btn}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 8px;"
            )
            btn.clicked.connect(lambda checked, c=category: self._capture_image(c))
            btn_layout.addWidget(btn)

        exit_btn = QPushButton("Exit Camera")
        exit_btn.setMinimumHeight(btn_h)
        exit_btn.setStyleSheet(
            f"font-size: {fs_btn}px; font-weight: bold; "
            f"background-color: #9e9e9e; color: white; border-radius: 8px; margin-top: 10px;"
        )
        exit_btn.clicked.connect(self.accept)
        btn_layout.addWidget(exit_btn)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    # ── Feed & capture ───────────────────────────────────────────────────────

    def _update_feed(self):
        try:
            frame = self.picam2.capture_array("main")
            frame = frame[:, :, ::-1].copy()
            h, w, ch = frame.shape
            self.current_qimg = QImage(
                frame.data, w, h, ch * w, QImage.Format.Format_RGB888
            )
            pixmap = QPixmap.fromImage(self.current_qimg).scaled(
                self.CAM_W, self.CAM_H,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.camera_label.setPixmap(pixmap)
        except Exception:
            pass

    def _capture_image(self, category: str):
        if self.current_qimg:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath  = os.path.join(self.base_dir, category, f"{timestamp}.jpg")
            self.current_qimg.save(filepath)
            QMessageBox.information(self, "Saved", f"Image saved to:\n{category}")

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def _stop_camera(self):
        self.timer.stop()
        if hasattr(self, "picam2"):
            self.picam2.stop()
            self.picam2.close()

    def accept(self):
        self._stop_camera()
        super().accept()

    def closeEvent(self, event):
        self._stop_camera()
        super().closeEvent(event)