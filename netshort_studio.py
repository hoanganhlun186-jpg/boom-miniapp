"""BOOM miniapp / PyQt6 entry point."""
import sys
from studio_qt import MainWindow, QApplication
from boom_login import LoginDialog

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    login=LoginDialog()
    if not login.exec():sys.exit(0)
    window = MainWindow(login.account)
    app.setQuitOnLastWindowClosed(True)
    window.show()
    sys.exit(app.exec())
