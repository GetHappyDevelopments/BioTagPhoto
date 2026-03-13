from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
)

from db import create_person


class CreatePersonDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Person")
        self.resize(320, 120)

        layout = QVBoxLayout(self)

        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("Person name")
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self.edit_name)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_ok = QPushButton("Create")
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self._on_create)

        self.created_person_id: Optional[int] = None

    def _on_create(self):
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Name cannot be empty.")
            return

        try:
            person_id = create_person(name)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        self.created_person_id = person_id
        self.accept()
