from PyQt6.QtWidgets import QApplication


def screen_size():
    """Returns the primary screen (width, height) in pixels."""
    screen = QApplication.primaryScreen().size()
    return screen.width(), screen.height()