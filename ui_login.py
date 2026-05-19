from PyQt6.QtWidgets import QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt

import database
from windows import MainWindow
from keyboard import QwertyDialog


class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Login")
        self.showFullScreen()

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("System Login")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold; margin-bottom: 30px;")
        layout.addWidget(title)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.username_input.setMinimumHeight(50)
        self.username_input.setMinimumWidth(300)
        self.username_input.setStyleSheet("font-size: 18px; padding: 5px;")
        self.username_input.setReadOnly(True)
        self.username_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.username_input.mousePressEvent = lambda e: self._open_kb(self.username_input)
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumHeight(50)
        self.password_input.setMinimumWidth(300)
        self.password_input.setStyleSheet("font-size: 18px; padding: 5px;")
        self.password_input.setReadOnly(True)
        self.password_input.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.password_input.mousePressEvent = lambda e: self._open_kb(self.password_input)
        layout.addWidget(self.password_input)

        self.login_btn = QPushButton("Login")
        self.login_btn.setMinimumHeight(60)
        self.login_btn.setStyleSheet(
            "font-size: 20px; background-color: #2196F3; color: white; margin-top: 20px;"
        )
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        self.exit_btn = QPushButton("Exit")
        self.exit_btn.setMinimumHeight(60)
        self.exit_btn.setStyleSheet(
            "font-size: 20px; background-color: #9e9e9e; color: white; margin-top: 10px;"
        )
        self.exit_btn.clicked.connect(self.close)
        layout.addWidget(self.exit_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: red; font-size: 16px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.setLayout(layout)

    def _open_kb(self, field):
        is_password = field.echoMode() == QLineEdit.EchoMode.Password
        title = "Enter Password" if is_password else (field.placeholderText() or "Enter Text")
        val, ok = QwertyDialog.get_text(self, "" if is_password else field.text(), title)
        if ok:
            field.setText(val)

    def handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        role = database.verify_login(username, password)  # returns "admin"/"user" or None
        if role:
            self.main_window = MainWindow(username, role)
            self.main_window.show()
            self.close()
        else:
            self.status_label.setText("Invalid username or password.")