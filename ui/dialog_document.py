from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from app_info import APP_NAME, APP_VERSION


def _document_path(filename: str) -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent / "_internal",
        Path(sys.executable).resolve().parent,
        Path(__file__).resolve().parent.parent,
    ]
    for base in candidates:
        if not str(base):
            continue
        path = base / filename
        if path.exists():
            return path
    return Path(__file__).resolve().parent.parent / filename


class DocumentDialog(QDialog):
    def __init__(
        self,
        title: str,
        filename: str,
        heading: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(860, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QLabel(f"{APP_NAME}\nVersion: {APP_VERSION}\n{heading}")
        header.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(header)

        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        editor.setText(self._read_text_file(filename))
        editor.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        root.addWidget(editor, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _read_text_file(self, filename: str) -> str:
        path = _document_path(filename)
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"Could not load {filename}:\n{exc}"
