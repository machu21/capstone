"""
keyboard.py — Embedded on-screen keyboard for PyQt6 fullscreen apps.

Usage:
    from keyboard import NumpadDialog, QwertyDialog, install_keyboard

    # Auto-attach to every QLineEdit in a widget (recommended):
    install_keyboard(my_widget)

    # Or manually pop up:
    NumpadDialog.get_number(parent, current_text, title)
    QwertyDialog.get_text(parent, current_text, title)
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QApplication, QWidget, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _screen():
    s = QApplication.primaryScreen().size()
    return s.width(), s.height()


def _btn(text, h, fs, bg="#455A64", fg="white", radius=8):
    b = QPushButton(text)
    b.setMinimumHeight(h)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.setStyleSheet(
        f"font-size:{fs}px; font-weight:bold; background:{bg}; "
        f"color:{fg}; border-radius:{radius}px; border:none;"
    )
    return b


# ---------------------------------------------------------------------------
# Numpad Dialog  (0-9, decimal, backspace, clear, OK)
# ---------------------------------------------------------------------------

class NumpadDialog(QDialog):
    """
    Modal numpad. Returns (value_str, accepted).
    Call via:  NumpadDialog.get_number(parent, current, title)
    """

    KEYS = [
        ["7", "8", "9"],
        ["4", "5", "6"],
        ["1", "2", "3"],
        [".", "0", "⌫"],
    ]

    def __init__(self, parent=None, current="", title="Enter Number"):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        SW, SH = _screen()
        scale = SW / 800

        pad_w = int(min(360, SW * 0.45) * scale / scale)  # fixed ~ half screen
        btn_h = max(48, int(58 * scale))
        fs    = max(16, int(22 * scale))
        fs_sm = max(12, int(15 * scale))

        # Outer card
        card = QWidget(self)
        card.setStyleSheet(
            "background:#263238; border-radius:16px; "
            "border: 2px solid #37474F;"
        )
        card.setFixedWidth(pad_w)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # Title
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color:#B0BEC5; font-size:{fs_sm}px; font-weight:bold;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # Display
        self.display = QLineEdit(current)
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.display.setStyleSheet(
            f"font-size:{fs+6}px; font-weight:bold; color:white; "
            f"background:#1C262B; border-radius:8px; padding:8px; border:none;"
        )
        self.display.setMinimumHeight(int(btn_h * 1.1))
        layout.addWidget(self.display)

        # Number grid
        for row in self.KEYS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            for key in row:
                if key == "⌫":
                    b = _btn(key, btn_h, fs, bg="#C62828", fg="white")
                    b.clicked.connect(self._backspace)
                else:
                    b = _btn(key, btn_h, fs, bg="#37474F")
                    b.clicked.connect(lambda _, k=key: self._press(k))
                row_layout.addWidget(b)
            layout.addLayout(row_layout)

        # Clear + OK row
        bot = QHBoxLayout()
        bot.setSpacing(6)
        clr = _btn("Clear", btn_h, fs_sm, bg="#546E7A")
        clr.clicked.connect(lambda: self.display.clear())
        bot.addWidget(clr)

        ok = _btn("OK ✓", btn_h, fs, bg="#2E7D32", fg="white")
        ok.clicked.connect(self.accept)
        bot.addWidget(ok, stretch=2)

        cancel = _btn("✕", btn_h, fs_sm, bg="#37474F")
        cancel.clicked.connect(self.reject)
        bot.addWidget(cancel)

        layout.addLayout(bot)

    def _press(self, key):
        t = self.display.text()
        if key == "." and "." in t:
            return
        self.display.setText(t + key)

    def _backspace(self):
        t = self.display.text()
        self.display.setText(t[:-1])

    def get_value(self):
        return self.display.text()

    @staticmethod
    def get_number(parent=None, current="", title="Enter Number"):
        """Convenience static method. Returns (str, bool_accepted)."""
        dlg = NumpadDialog(parent, current, title)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        return dlg.get_value(), accepted


# ---------------------------------------------------------------------------
# QWERTY Dialog  (full keyboard with Shift, numbers row, backspace, OK)
# ---------------------------------------------------------------------------

class QwertyDialog(QDialog):
    """
    Modal QWERTY keyboard. Returns (text_str, accepted).
    Call via:  QwertyDialog.get_text(parent, current, title)
    """

    ROWS_LOWER = [
        list("1234567890"),
        list("qwertyuiop"),
        list("asdfghjkl"),
        list("zxcvbnm"),
    ]
    ROWS_UPPER = [
        list("1234567890"),
        list("QWERTYUIOP"),
        list("ASDFGHJKL"),
        list("ZXCVBNM"),
    ]

    def __init__(self, parent=None, current="", title="Enter Text"):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)

        SW, SH = _screen()
        scale = SW / 800
        self._shifted = False

        btn_h  = max(36, int(44 * scale))
        fs     = max(13, int(16 * scale))
        fs_sm  = max(11, int(13 * scale))
        pad_w  = int(SW * 0.98)

        # Outer card
        card = QWidget(self)
        card.setStyleSheet(
            "background:#263238; border-radius:14px; border:2px solid #37474F;"
        )
        card.setFixedWidth(pad_w)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)

        # Title
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color:#B0BEC5; font-size:{fs_sm}px; font-weight:bold;")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl_title)

        # Display
        self.display = QLineEdit(current)
        self.display.setReadOnly(True)
        self.display.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.display.setStyleSheet(
            f"font-size:{fs+2}px; color:white; background:#1C262B; "
            f"border-radius:6px; padding:6px; border:none;"
        )
        self.display.setMinimumHeight(btn_h)
        layout.addWidget(self.display)

        # Key grid (we keep refs to rebuild on shift)
        self.key_grid_layout = QVBoxLayout()
        self.key_grid_layout.setSpacing(4)
        layout.addLayout(self.key_grid_layout)

        self._btn_h  = btn_h
        self._fs     = fs
        self._fs_sm  = fs_sm
        self._build_keys()

        # Bottom bar: Shift | Space | Backspace | OK | Cancel
        bot = QHBoxLayout()
        bot.setSpacing(5)

        self.shift_btn = _btn("⇧ Shift", btn_h, fs_sm, bg="#546E7A")
        self.shift_btn.setCheckable(False)
        self.shift_btn.clicked.connect(self._toggle_shift)
        bot.addWidget(self.shift_btn, stretch=2)

        space = _btn("Space", btn_h, fs_sm, bg="#37474F")
        space.clicked.connect(lambda: self._press(" "))
        bot.addWidget(space, stretch=4)

        bsp = _btn("⌫", btn_h, fs, bg="#C62828")
        bsp.clicked.connect(self._backspace)
        bot.addWidget(bsp, stretch=1)

        ok = _btn("OK ✓", btn_h, fs, bg="#2E7D32")
        ok.clicked.connect(self.accept)
        bot.addWidget(ok, stretch=2)

        cancel = _btn("✕", btn_h, fs_sm, bg="#37474F")
        cancel.clicked.connect(self.reject)
        bot.addWidget(cancel, stretch=1)

        layout.addLayout(bot)

    def _build_keys(self):
        # Clear existing widgets from the grid layout
        while self.key_grid_layout.count():
            item = self.key_grid_layout.takeAt(0)
            if item.layout():
                while item.layout().count():
                    w = item.layout().takeAt(0).widget()
                    if w:
                        w.deleteLater()

        rows = self.ROWS_UPPER if self._shifted else self.ROWS_LOWER
        for row in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)
            for key in row:
                b = _btn(key, self._btn_h, self._fs, bg="#37474F")
                b.clicked.connect(lambda _, k=key: self._press(k))
                row_layout.addWidget(b)
            self.key_grid_layout.addLayout(row_layout)

    def _press(self, key):
        self.display.setText(self.display.text() + key)
        if self._shifted:
            self._shifted = False
            self._build_keys()
            self.shift_btn.setStyleSheet(
                f"font-size:{self._fs_sm}px; font-weight:bold; background:#546E7A; "
                f"color:white; border-radius:8px; border:none;"
            )

    def _backspace(self):
        t = self.display.text()
        self.display.setText(t[:-1])

    def _toggle_shift(self):
        self._shifted = not self._shifted
        self._build_keys()
        active_bg = "#1565C0" if self._shifted else "#546E7A"
        self.shift_btn.setStyleSheet(
            f"font-size:{self._fs_sm}px; font-weight:bold; background:{active_bg}; "
            f"color:white; border-radius:8px; border:none;"
        )

    def get_value(self):
        return self.display.text()

    @staticmethod
    def get_text(parent=None, current="", title="Enter Text"):
        """Convenience static method. Returns (str, bool_accepted)."""
        dlg = QwertyDialog(parent, current, title)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        return dlg.get_value(), accepted


# ---------------------------------------------------------------------------
# install_keyboard — auto-attaches the right keyboard to every QLineEdit
# ---------------------------------------------------------------------------

def install_keyboard(widget: QWidget, numeric_inputs=None):
    """
    Walks all QLineEdit children of `widget` and hooks the correct keyboard.

    Args:
        widget:         The parent QWidget to scan (e.g. self in MainWindow.__init__)
        numeric_inputs: Optional list/set of QLineEdit objects that should use
                        the numpad. Any QLineEdit whose objectName contains
                        'price', 'weight', or 'num' will also auto-use numpad.
                        All others get QWERTY.

    Example:
        install_keyboard(self)
        # or with explicit numeric fields:
        install_keyboard(self, numeric_inputs={self.pet_price_input, self.metal_price_input})
    """
    numeric_inputs = set(numeric_inputs or [])
    _NUMERIC_NAMES = ("price", "weight", "num", "qty", "amount", "kg", "cost")

    for child in widget.findChildren(QLineEdit):
        # decide keyboard type
        name = child.objectName().lower()
        is_numeric = (
            child in numeric_inputs or
            any(kw in name for kw in _NUMERIC_NAMES)
        )

        # make read-only so the system keyboard never pops up
        child.setReadOnly(True)
        child.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # connect tap → dialog
        if is_numeric:
            child.mousePressEvent = _make_numpad_handler(child)
        else:
            child.mousePressEvent = _make_qwerty_handler(child)


def _make_numpad_handler(field: QLineEdit):
    def handler(event):
        val, ok = NumpadDialog.get_number(
            field.window(), field.text(), field.placeholderText() or "Enter Number"
        )
        if ok:
            field.setText(val)
    return handler


def _make_qwerty_handler(field: QLineEdit):
    def handler(event):
        val, ok = QwertyDialog.get_text(
            field.window(), field.text(), field.placeholderText() or "Enter Text"
        )
        if ok:
            field.setText(val)
    return handler