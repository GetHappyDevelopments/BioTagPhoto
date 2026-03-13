from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget

from app_info import APP_NAME, APP_LICENSE, APP_VERSION
from .dialog_document import _document_path


class LicenseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Licenses")
        self.setModal(True)
        self.resize(860, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel(
            f"{APP_NAME}\nVersion: {APP_VERSION}\nLicense summary: {APP_LICENSE}"
        )
        header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(header)

        tabs = QTabWidget()
        tabs.addTab(self._build_text_tab(self._read_text_file("LICENSE")), "BioTagPhoto")
        tabs.addTab(self._build_text_tab(self._read_text_file("NOTICE")), "Notice")
        tabs.addTab(
            self._build_text_tab(self._read_text_file("THIRD_PARTY_NOTICES.md")),
            "Third-Party",
        )
        root.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _build_text_tab(self, text: str) -> QWidget:
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        editor.setText(text)
        editor.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return editor

    def _read_text_file(self, filename: str) -> str:
        path = _document_path(filename)
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"Could not load {filename}:\n{exc}"
