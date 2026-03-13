from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
import ctypes

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCursor, QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app_info import APP_CONSENT_VERSION, APP_NAME, APP_ORGANIZATION, APP_VERSION
from model_config import (
    describe_model_root,
    ensure_saved_model_root,
    is_valid_model_root,
    normalize_model_root_selection,
    set_saved_model_root,
)
from ui.dialog_consent import FirstRunConsentDialog
from ui.main_window import MainWindow


CONSENT_KEY_VERSION = "legal/consent_version"
CONSENT_KEY_ACCEPTED_AT = "legal/consent_accepted_at"


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BioTagPhoto.App")
    except Exception:
        pass


def _resource_path(*parts: str) -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent / "_internal",
        Path(sys.executable).resolve().parent,
        Path(__file__).resolve().parent,
        Path.cwd(),
    ]
    for base in candidates:
        if not str(base):
            continue
        path = base.joinpath(*parts)
        if path.exists():
            return path
    return Path(parts[0]).joinpath(*parts[1:])


class StartupSplash(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Starting BioTagPhoto")
        self.setObjectName("StartupSplash")
        self.setStyleSheet(
            """
            QWidget#StartupSplash {
                background: #ffffff;
                border: 1px solid #dddddd;
                border-radius: 12px;
            }
            QLabel#StartupStatus {
                color: #444444;
                font-size: 12px;
                font-weight: 600;
            }
            QProgressBar {
                min-height: 16px;
                border: 1px solid #d0d0d0;
                border-radius: 8px;
                text-align: center;
                background: #f5f5f5;
            }
            QProgressBar::chunk {
                background: #0aa4e8;
                border-radius: 7px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setScaledContents(True)
        self.image.setMinimumSize(0, 0)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        root.addWidget(self.image, 1)

        self.status = QLabel("Starting...")
        self.status.setObjectName("StartupStatus")
        self.status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.status.setMinimumWidth(240)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(4, 0, 4, 2)
        bottom.setSpacing(10)
        bottom.addWidget(self.status, 0)
        bottom.addWidget(self.progress, 1)
        root.addLayout(bottom, 0)

        self.resize(760, 460)
        self._load_logo()

    def center_on_screen(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos())
        if screen is None:
            screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.x() + (area.width() - self.width()) // 2
        y = area.y() + (area.height() - self.height()) // 2
        self.move(x, y)

    def _load_logo(self) -> None:
        chosen = _resource_path("ui", "BioTagPhotoStart.png")
        if not chosen.exists():
            self.image.setText("BioTagPhotoStart.png not found")
            return

        pix = QPixmap(str(chosen))
        if pix.isNull():
            self.image.setText(f"Could not load {chosen.name}")
            return

        self.image.setPixmap(pix)

    def update_progress(self, current: int, total: int, message: str) -> None:
        total_i = max(1, int(total))
        current_i = max(0, min(int(current), total_i))
        percent = int(round((current_i / total_i) * 100.0))
        self.progress.setValue(percent)
        self.status.setText(str(message))


def _ensure_model_available() -> bool:
    root = ensure_saved_model_root()
    if root is not None and is_valid_model_root(root):
        return True

    while True:
        msg = QMessageBox()
        msg.setWindowTitle("Model Setup Required")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            "BioTagPhoto requires the InsightFace model pack 'buffalo_l' for face analysis.\n\n"
            "This model is not bundled with the application. Please download it separately "
            "and then select the folder that contains 'buffalo_l', or the 'buffalo_l' folder itself."
        )
        btn_select = msg.addButton("Select Folder...", QMessageBox.ButtonRole.AcceptRole)
        btn_continue = msg.addButton("Continue Without Model", QMessageBox.ButtonRole.ActionRole)
        btn_exit = msg.addButton("Exit", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is btn_select:
            folder = QFileDialog.getExistingDirectory(None, "Select InsightFace Model Folder")
            if not folder:
                continue
            root = normalize_model_root_selection(folder)
            if not is_valid_model_root(root):
                QMessageBox.critical(None, "Invalid Model Folder", describe_model_root(root))
                continue
            set_saved_model_root(root)
            return True
        if clicked is btn_continue:
            return True
        if clicked is btn_exit:
            return False
        return False


def _ensure_usage_consent() -> bool:
    settings = QSettings(APP_ORGANIZATION, APP_NAME)
    saved_version = str(settings.value(CONSENT_KEY_VERSION, "", type=str) or "")
    if saved_version == APP_CONSENT_VERSION:
        return True

    dialog = FirstRunConsentDialog()
    if dialog.exec() != int(dialog.DialogCode.Accepted):
        return False

    settings.setValue(CONSENT_KEY_VERSION, APP_CONSENT_VERSION)
    settings.setValue(
        CONSENT_KEY_ACCEPTED_AT,
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    settings.sync()
    return True


def main() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    icon_path = _resource_path("ui", "BioTagPhotoIcon.png")
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
    else:
        app_icon = QIcon()

    splash = StartupSplash()
    if not app_icon.isNull():
        splash.setWindowIcon(app_icon)
    splash.show()
    splash.center_on_screen()
    app.processEvents()

    splash.update_progress(3, 100, "Checking usage confirmation...")
    app.processEvents()
    if not _ensure_usage_consent():
        splash.close()
        return 0

    if not _ensure_model_available():
        splash.close()
        return 0

    def _on_startup_progress(current: int, total: int, message: str) -> None:
        splash.update_progress(current, total, message)
        app.processEvents()

    window = MainWindow(startup_progress_cb=_on_startup_progress)
    if not app_icon.isNull():
        window.setWindowIcon(app_icon)
    window.show()

    splash.close()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
