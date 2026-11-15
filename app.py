import sys

from PySide6.QtWidgets import QApplication

from folder_scout.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("FolderScout")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()