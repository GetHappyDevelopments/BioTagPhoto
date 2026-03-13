from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from .dialog_document import DocumentDialog


class FirstRunConsentDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Usage Confirmation")
        self.setModal(True)
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Please confirm the intended use before continuing.")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(title)

        body = QLabel(
            "BioTagPhoto can process face images, person names, assignments, and embeddings.\n\n"
            "You may only use the software if you are authorized to process the images and face data "
            "under the laws and rules that apply to your use case.\n\n"
            "The software can produce incorrect matches. Results must be reviewed by a human and must "
            "not be used as the sole basis for high-risk decisions."
        )
        body.setWordWrap(True)
        root.addWidget(body)

        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(
            "- I will only process images and face data when I have a valid legal basis.\n"
            "- I understand that face suggestions and auto-assignments can be wrong.\n"
            "- I understand that third-party model licenses must be checked separately.\n"
            "- I understand that this software is not legal advice and not a compliance substitute."
        )
        root.addWidget(summary, 1)

        self.checkbox = QCheckBox(
            "I confirm that I am responsible for lawful use of this software and the data processed with it."
        )
        self.checkbox.stateChanged.connect(self._on_check_state_changed)
        root.addWidget(self.checkbox)

        links = QHBoxLayout()
        btn_privacy = QPushButton("View Privacy")
        btn_legal = QPushButton("View Legal")
        btn_privacy.clicked.connect(self._show_privacy)
        btn_legal.clicked.connect(self._show_legal)
        links.addWidget(btn_privacy)
        links.addWidget(btn_legal)
        links.addStretch(1)
        root.addLayout(links)

        buttons = QDialogButtonBox()
        self.btn_decline = buttons.addButton("Exit", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_accept = buttons.addButton("Accept and Continue", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_accept.setEnabled(False)
        self.btn_decline.clicked.connect(self.reject)
        self.btn_accept.clicked.connect(self._accept_checked)
        root.addWidget(buttons)

    def _on_check_state_changed(self, state: int) -> None:
        enabled = state != 0
        self.btn_accept.setEnabled(bool(enabled))

    def _show_privacy(self) -> None:
        dlg = DocumentDialog("Privacy", "PRIVACY.md", "Privacy and data processing notice", self)
        dlg.exec()

    def _show_legal(self) -> None:
        dlg = DocumentDialog("Legal", "LEGAL.md", "Legal and usage notice", self)
        dlg.exec()

    def _accept_checked(self) -> None:
        if not self.checkbox.isChecked():
            QMessageBox.warning(self, "Usage Confirmation", "Please confirm the checkbox first.")
            return
        self.accept()
