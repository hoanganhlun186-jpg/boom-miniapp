"""BOOM miniapp / PyQt6 entry point."""
import sys
if __name__ == '__main__' and '--boom-apply-update' in sys.argv:
    from boom_updater import worker
    sys.exit(worker(sys.argv[sys.argv.index('--boom-apply-update')+1]))
from studio_qt import MainWindow, QApplication
from boom_login import LoginDialog

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    from boom_updater import startup
    if startup(app):sys.exit(0)
    login=LoginDialog()
    if not login.exec():sys.exit(0)
    window = MainWindow(login.account)
    app.setQuitOnLastWindowClosed(True)
    window.show()
    sys.exit(app.exec())
