"""
dialogs/coin_dispenser.py
─────────────────────────
Admin dialog to test coin dispensing.
Enter an amount → rounds to nearest ₱5 → dispenses via PCA9685 SG90s.
"""

from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
Device.pin_factory = LGPIOFactory()

from PyQt6.QtWidgets import (
    QDialog, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QLineEdit, QMessageBox, QFrame,
)
from PyQt6.QtCore import Qt, QTimer

from utils import screen_size
from keyboard import install_keyboard

# ── PCA9685 config ────────────────────────────────────────────────────────────
PCA9685_ADDRESS = 0x40
COIN_CHANNELS   = {0: 1, 1: 5, 2: 10, 3: 20}

ANGLE_DISPENSE  = 180
ANGLE_NEUTRAL   =   0
DISPENSE_MS     = 600
RETURN_MS       = 400


# ── Helpers ───────────────────────────────────────────────────────────────────

def _round_to_nearest_5(amount: float) -> int:
    """Round to nearest multiple of 5."""
    return round(round(amount / 5) * 5)


def _break_into_coins(amount: int) -> dict:
    """Greedy breakdown into coin denominations."""
    coins = {}
    remaining = amount
    for denom in sorted(COIN_CHANNELS.values(), reverse=True):
        count = remaining // denom
        if count:
            coins[denom] = count
        remaining %= denom
    return coins


class CoinDispenserDialog(QDialog):
    """Admin UI for testing coin dispenser with amount input."""

    MOCK_COINS = False   # ← set True if PCA9685 not connected

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Coin Dispenser Test")
        self.showFullScreen()
        self.setStyleSheet("background-color: #ECEFF1;")

        SW, _ = screen_size()
        scale  = SW / 800
        self._scale = scale

        self._dispense_queue = []
        self._coin_servos    = {}
        self._pca            = None

        if not self.MOCK_COINS:
            self._init_pca9685()

        self._build_ui(scale)
        install_keyboard(self, numeric_inputs={self.amount_input})

    # ── Hardware init ─────────────────────────────────────────────────────────

    def _init_pca9685(self):
        try:
            from adafruit_pca9685 import PCA9685               # type: ignore
            from adafruit_motor import servo as adafruit_servo  # type: ignore
            import board, busio                                  # type: ignore
            i2c          = busio.I2C(board.SCL, board.SDA)
            self._pca    = PCA9685(i2c, address=PCA9685_ADDRESS)
            self._pca.frequency = 50
            self._coin_servos = {
                denom: adafruit_servo.Servo(
                    self._pca.channels[ch],
                    min_pulse=500,
                    max_pulse=2400,
                )
                for ch, denom in COIN_CHANNELS.items()
            }
            # All to neutral on start
            for s in self._coin_servos.values():
                s.angle = ANGLE_NEUTRAL
        except Exception as e:
            QMessageBox.warning(
                self, "Coin Dispenser",
                f"PCA9685 init failed — running in mock mode.\n{e}"
            )
            self.MOCK_COINS = True

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, scale: float):
        fs_title  = max(16, int(22 * scale))
        fs_label  = max(13, int(18 * scale))
        fs_status = max(12, int(16 * scale))
        btn_h     = max(50, int(70 * scale))

        main_layout = QVBoxLayout()
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.setSpacing(int(12 * scale))
        main_layout.setContentsMargins(30, 20, 30, 20)

        # Title
        title = QLabel("Coin Dispenser Test")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: {fs_title}px; font-weight: bold; color: #333;"
        )
        main_layout.addWidget(title)

        # Mode badge
        mode_lbl = QLabel("● MOCK MODE" if self.MOCK_COINS else "● HARDWARE MODE")
        mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mode_lbl.setStyleSheet(
            f"font-size: {max(11, int(14*scale))}px; font-weight: bold; "
            f"color: {'#FF9800' if self.MOCK_COINS else '#4CAF50'};"
        )
        main_layout.addWidget(mode_lbl)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #ccc;")
        main_layout.addWidget(line)

        # Amount input row
        input_row = QHBoxLayout()
        input_row.setSpacing(int(8 * scale))

        amt_lbl = QLabel("Amount (₱):")
        amt_lbl.setStyleSheet(f"font-size: {fs_label}px; font-weight: bold;")
        input_row.addWidget(amt_lbl)

        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("e.g. 37")
        self.amount_input.setMinimumHeight(btn_h)
        self.amount_input.setStyleSheet(
            f"font-size: {fs_label}px; padding: 6px; border: 2px solid #ccc; border-radius: 8px;"
        )
        self.amount_input.setReadOnly(True)
        self.amount_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.amount_input.mousePressEvent = lambda e: self._open_kb()
        input_row.addWidget(self.amount_input)

        main_layout.addLayout(input_row)

        # Rounded preview label
        self.rounded_label = QLabel("Rounded: —")
        self.rounded_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rounded_label.setStyleSheet(
            f"font-size: {fs_label}px; color: #555;"
        )
        main_layout.addWidget(self.rounded_label)
        self.amount_input.textChanged.connect(self._update_preview)

        # Coin breakdown label
        self.breakdown_label = QLabel("Breakdown: —")
        self.breakdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.breakdown_label.setStyleSheet(
            f"font-size: {fs_label}px; color: #1565C0; font-weight: bold;"
        )
        main_layout.addWidget(self.breakdown_label)

        # Dispense button
        self.dispense_btn = QPushButton("Dispense Coins")
        self.dispense_btn.setMinimumHeight(btn_h)
        self.dispense_btn.setStyleSheet(
            f"font-size: {fs_label}px; font-weight: bold; "
            f"background-color: #00897B; color: white; border-radius: 8px;"
        )
        self.dispense_btn.clicked.connect(self._start_dispense)
        main_layout.addWidget(self.dispense_btn)

        # Individual coin buttons
        sep = QLabel("── Test individual coins ──")
        sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sep.setStyleSheet(f"font-size: {max(11,int(14*scale))}px; color: #888;")
        main_layout.addWidget(sep)

        main_layout.addWidget(self._coin_buttons_row(scale, btn_h))

        # Status label
        self.status_label = QLabel("Ready.")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            f"font-size: {fs_status}px; color: #333; "
            f"background: white; border: 2px solid #ccc; "
            f"border-radius: 8px; padding: 8px;"
        )
        main_layout.addWidget(self.status_label)

        # Exit button
        exit_btn = QPushButton("Close")
        exit_btn.setMinimumHeight(btn_h)
        exit_btn.setStyleSheet(
            f"font-size: {fs_label}px; font-weight: bold; "
            f"background-color: #9e9e9e; color: white; border-radius: 8px;"
        )
        exit_btn.clicked.connect(self.accept)
        main_layout.addWidget(exit_btn)

        self.setLayout(main_layout)

    def _coin_buttons_row(self, scale, btn_h) -> QFrame:
        frame  = QFrame()
        layout = QHBoxLayout(frame)
        layout.setSpacing(int(8 * scale))
        fs = max(13, int(16 * scale))

        for denom, color in [(1, "#78909C"), (5, "#43A047"), (10, "#1E88E5"), (20, "#E53935")]:
            btn = QPushButton(f"₱{denom}")
            btn.setMinimumHeight(btn_h)
            btn.setStyleSheet(
                f"font-size: {fs}px; font-weight: bold; "
                f"background-color: {color}; color: white; border-radius: 8px;"
            )
            btn.clicked.connect(lambda checked, d=denom: self._dispense_single(d))
            layout.addWidget(btn)

        return frame

    # ── Preview ───────────────────────────────────────────────────────────────

    def _open_kb(self):
        from keyboard import QwertyDialog
        val, ok = QwertyDialog.get_text(self, self.amount_input.text(), "Enter Amount (₱)")
        if ok:
            self.amount_input.setText(val)

    def _update_preview(self, text: str):
        try:
            amount  = float(text)
            rounded = _round_to_nearest_5(amount)
            coins   = _break_into_coins(rounded)
            breakdown = "  +  ".join(
                f"₱{d} × {c}" for d, c in sorted(coins.items(), reverse=True)
            ) if coins else "₱0"
            self.rounded_label.setText(f"Rounded: ₱{rounded}")
            self.breakdown_label.setText(f"Breakdown: {breakdown}")
        except ValueError:
            self.rounded_label.setText("Rounded: —")
            self.breakdown_label.setText("Breakdown: —")

    # ── Dispense logic ────────────────────────────────────────────────────────

    def _start_dispense(self):
        text = self.amount_input.text().strip()
        try:
            amount = float(text)
        except ValueError:
            QMessageBox.warning(self, "Input Error", "Please enter a valid amount.")
            return

        rounded = _round_to_nearest_5(amount)
        if rounded <= 0:
            QMessageBox.warning(self, "Input Error", "Amount must be greater than ₱0.")
            return

        coins = _break_into_coins(rounded)
        if not coins:
            QMessageBox.information(self, "Nothing to dispense", "Amount rounds to ₱0.")
            return

        # Build flat queue
        self._dispense_queue = []
        for denom in sorted(coins.keys(), reverse=True):
            for _ in range(coins[denom]):
                self._dispense_queue.append(denom)

        total = sum(coins.values())
        self.status_label.setText(
            f"Dispensing ₱{rounded} — {total} coins\n"
            + "  ".join(f"₱{d}×{c}" for d, c in sorted(coins.items(), reverse=True))
        )
        self.status_label.setStyleSheet(
            self.status_label.styleSheet().replace("color: #333", "color: #9C27B0")
        )
        self.dispense_btn.setEnabled(False)
        self._dispense_next()

    def _dispense_single(self, denom: int):
        self._dispense_queue = [denom]
        self.status_label.setText(f"Dispensing ₱{denom}...")
        self.dispense_btn.setEnabled(False)
        self._dispense_next()

    def _dispense_next(self):
        if not self._dispense_queue:
            self.status_label.setText("✓ Dispense complete!")
            self.status_label.setStyleSheet(
                self.status_label.styleSheet()
                    .replace("color: #9C27B0", "color: #4CAF50")
                    .replace("color: #333",    "color: #4CAF50")
            )
            self.dispense_btn.setEnabled(True)
            return

        denom = self._dispense_queue.pop(0)
        remaining = len(self._dispense_queue)
        self.status_label.setText(
            f"Dispensing ₱{denom}...  ({remaining} coins remaining)"
        )

        if not self.MOCK_COINS and denom in self._coin_servos:
            self._coin_servos[denom].angle = ANGLE_DISPENSE
        else:
            print(f"[MOCK] Dispense ₱{denom}")

        QTimer.singleShot(DISPENSE_MS, lambda: self._return_servo(denom))

    def _return_servo(self, denom: int):
        if not self.MOCK_COINS and denom in self._coin_servos:
            self._coin_servos[denom].angle = ANGLE_NEUTRAL
        QTimer.singleShot(RETURN_MS, self._dispense_next)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup(self):
        if not self.MOCK_COINS:
            for s in self._coin_servos.values():
                try:
                    s.angle = ANGLE_NEUTRAL
                except Exception:
                    pass
            if self._pca:
                try:
                    self._pca.deinit()
                except Exception:
                    pass

    def accept(self):
        self._cleanup()
        super().accept()

    def closeEvent(self, event):
        self._cleanup()
        super().closeEvent(event)