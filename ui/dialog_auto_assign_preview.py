from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


HIGH_CONFIDENCE_MIN = 0.85


@dataclass(frozen=True)
class AutoAssignPreviewRow:
    face_id: int
    person_id: int
    person_name: str
    score: float


class AutoAssignPreviewDialog(QDialog):
    def __init__(self, rows: Sequence[AutoAssignPreviewRow], total_faces: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Assign Preview")
        self.resize(760, 500)

        self._all_rows: List[AutoAssignPreviewRow] = list(rows)
        self._apply_requested = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.summary_label = QLabel("")
        root.addWidget(self.summary_label)

        self.chk_only_high = QCheckBox("Only high confidence")
        self.chk_only_high.setChecked(True)
        self.chk_only_high.stateChanged.connect(self._refresh_table)
        root.addWidget(self.chk_only_high)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["FaceID", "Person", "Score"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox()
        self.btn_close = buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_apply = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_close.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        root.addWidget(buttons)

        self._total_faces = int(total_faces)
        self._refresh_table()

    @property
    def apply_requested(self) -> bool:
        return bool(self._apply_requested)

    def selected_assignments(self) -> list[tuple[int, int]]:
        rows = self._visible_rows()
        return [(int(r.face_id), int(r.person_id)) for r in rows]

    def _visible_rows(self) -> list[AutoAssignPreviewRow]:
        only_high = bool(self.chk_only_high.isChecked())
        if not only_high:
            return list(self._all_rows)
        return [r for r in self._all_rows if float(r.score) >= HIGH_CONFIDENCE_MIN]

    def _refresh_table(self) -> None:
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))

        for i, row in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(row.face_id)))
            self.table.setItem(i, 1, QTableWidgetItem(str(row.person_name)))
            self.table.setItem(i, 2, QTableWidgetItem(f"{row.score:.4f}"))

        self.summary_label.setText(
            f"Faces total: {self._total_faces}    Dry-run matched: {len(self._all_rows)}    "
            f"Shown: {len(rows)}"
        )
        self.btn_apply.setEnabled(len(rows) > 0)

    def _on_apply_clicked(self) -> None:
        self._apply_requested = True
        self.accept()
