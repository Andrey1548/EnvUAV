import sys
import threading
import time
import webbrowser
import sys
print("Python executable:", sys.executable)

from PyQt5.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineProfile
from PyQt5.QtCore import QUrl

from app import app, socketio

class MainWindow(QMainWindow):
    def __init__(self, url):
        super().__init__()

        self.setWindowTitle("EnvUAV")
        self.setGeometry(200, 100, 1200, 800)

        self.browser = QWebEngineView()
        self.browser.load(QUrl(url))
        self.setCentralWidget(self.browser)

        profile = QWebEngineProfile.defaultProfile()
        profile.downloadRequested.connect(self.on_downloadRequested)

        self.show()

    def on_downloadRequested(self, download):
        print("Завантаження розпочато:", download.url())

        path, _ = QFileDialog.getSaveFileName(
            self, "Зберегти файл", download.suggestedFileName()
        )

        if path:
            download.setPath(path)
            download.accept()
        else:
            download.cancel()

def run_flask():
    socketio.run(app, host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    time.sleep(1.5)

    qt_app = QApplication(sys.argv)
    window = MainWindow("http://127.0.0.1:5000/")
    sys.exit(qt_app.exec_())