import sys
import os

os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtWidgets import QApplication
import database
import sync_sheets
from ui_login import LoginWindow


def main():
    # 1. Initialize database
    database.setup_database()

    # 2. Start background Google Sheets sync service
    sync_sheets.start()

    # 3. Start the application
    app = QApplication(sys.argv)

    # 4. Show login window
    window = LoginWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()