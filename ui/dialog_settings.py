from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter


class DeleteConfirmDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Reset")
        self.resize(420, 180)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        text = QLabel(
            "This action is irreversible and will delete your current database.\n"
            "Type 'delete' to continue."
        )
        text.setWordWrap(True)
        root.addWidget(text)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Type: delete")
        self.edit.textChanged.connect(self._on_text_changed)
        root.addWidget(self.edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_delete = QPushButton("Delete and Reset")
        self.btn_delete.setEnabled(False)
        buttons.addButton(self.btn_delete, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_delete.clicked.connect(self.accept)
        root.addWidget(buttons)

    def _on_text_changed(self, value: str) -> None:
        self.btn_delete.setEnabled(value.strip() == "delete")


class SettingsDialog(QDialog):
    def __init__(
        self,
        on_reset_database: Callable[[], Tuple[bool, str]],
        on_get_model_root: Callable[[], str],
        on_set_model_root: Callable[[str], Tuple[bool, str]],
        on_clear_model_root: Callable[[], Tuple[bool, str]],
        on_list_sources: Callable[[], Sequence[str]],
        on_add_source: Callable[[str], Tuple[bool, str]],
        on_remove_source: Callable[[str], Tuple[bool, str]],
        on_list_excluded_images: Callable[[], Sequence[str]],
        on_add_excluded_image: Callable[[str], Tuple[bool, str]],
        on_remove_excluded_image: Callable[[str], Tuple[bool, str]],
        on_list_excluded_faces: Callable[[], Sequence[Tuple[int, str]]],
        on_add_excluded_face: Callable[[int], Tuple[bool, str]],
        on_remove_excluded_face: Callable[[int], Tuple[bool, str]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._on_reset_database = on_reset_database
        self._on_get_model_root = on_get_model_root
        self._on_set_model_root = on_set_model_root
        self._on_clear_model_root = on_clear_model_root
        self._on_list_sources = on_list_sources
        self._on_add_source = on_add_source
        self._on_remove_source = on_remove_source
        self._on_list_excluded_images = on_list_excluded_images
        self._on_add_excluded_image = on_add_excluded_image
        self._on_remove_excluded_image = on_remove_excluded_image
        self._on_list_excluded_faces = on_list_excluded_faces
        self._on_add_excluded_face = on_add_excluded_face
        self._on_remove_excluded_face = on_remove_excluded_face

        self.setWindowTitle("Settings")
        self.resize(760, 460)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        self.categories = QListWidget()
        self.categories.addItem("Models")
        self.categories.addItem("Sources")
        self.categories.addItem("Database")
        self.categories.setFixedWidth(180)
        content.addWidget(self.categories)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_models_page())
        self.pages.addWidget(self._build_sources_page())
        self.pages.addWidget(self._build_database_page())
        content.addWidget(self.pages, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        root.addWidget(buttons)

        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)

    def _build_models_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)

        title = QLabel("Models")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(title)

        hint = QLabel(
            "BioTagPhoto does not ship the InsightFace model pack. "
            "Select the parent folder that contains 'buffalo_l', or select the "
            "'buffalo_l' folder itself."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.model_path_edit = QLineEdit()
        self.model_path_edit.setReadOnly(True)
        lay.addWidget(self.model_path_edit)

        btn_row = QHBoxLayout()
        self.btn_browse_model = QPushButton("Select Model Folder...")
        self.btn_clear_model = QPushButton("Clear")
        self.btn_browse_model.clicked.connect(self._on_select_model_clicked)
        self.btn_clear_model.clicked.connect(self._on_clear_model_clicked)
        btn_row.addWidget(self.btn_browse_model)
        btn_row.addWidget(self.btn_clear_model)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.model_status = QLabel("")
        self.model_status.setWordWrap(True)
        lay.addWidget(self.model_status)

        lay.addStretch(1)
        self._refresh_model_path()
        return page

    def _refresh_model_path(self) -> None:
        try:
            value = str(self._on_get_model_root())
        except Exception as exc:
            value = ""
            self.model_status.setText(f"Could not load model path:\n{exc}")
        self.model_path_edit.setText(value)
        if value.strip():
            self.model_status.setText("Configured model path is stored for future runs.")
        elif not self.model_status.text().strip():
            self.model_status.setText("No model path configured.")

    def _on_select_model_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select InsightFace Model Folder")
        if not folder:
            return
        ok, message = self._on_set_model_root(str(folder))
        if not ok:
            QMessageBox.critical(self, "Model Configuration Failed", message)
            return
        self._refresh_model_path()
        QMessageBox.information(self, "Models", message)

    def _on_clear_model_clicked(self) -> None:
        ok, message = self._on_clear_model_root()
        if not ok:
            QMessageBox.critical(self, "Model Configuration Failed", message)
            return
        self._refresh_model_path()
        QMessageBox.information(self, "Models", message)

    def _build_sources_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)

        title = QLabel("Sources")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(title)

        hint = QLabel("Folders listed here are monitored as image sources for analysis.")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.sources_list = QListWidget()
        lay.addWidget(self.sources_list, 1)

        btn_row = QHBoxLayout()
        self.btn_add_source = QPushButton("Add Folder...")
        self.btn_remove_source = QPushButton("Remove Selected")
        self.btn_add_source.clicked.connect(self._on_add_source_clicked)
        self.btn_remove_source.clicked.connect(self._on_remove_source_clicked)
        btn_row.addWidget(self.btn_add_source)
        btn_row.addWidget(self.btn_remove_source)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        excluded_title = QLabel("Excluded Images")
        excluded_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        lay.addWidget(excluded_title)

        excluded_hint = QLabel(
            "Images listed here are excluded from analysis and search pages. "
            "Existing database data remains unchanged and can be re-included by removal."
        )
        excluded_hint.setWordWrap(True)
        lay.addWidget(excluded_hint)

        self.excluded_list = QListWidget()
        lay.addWidget(self.excluded_list, 1)

        excluded_btn_row = QHBoxLayout()
        self.btn_add_excluded = QPushButton("Add Image...")
        self.btn_remove_excluded = QPushButton("Remove Selected")
        self.btn_add_excluded.clicked.connect(self._on_add_excluded_clicked)
        self.btn_remove_excluded.clicked.connect(self._on_remove_excluded_clicked)
        excluded_btn_row.addWidget(self.btn_add_excluded)
        excluded_btn_row.addWidget(self.btn_remove_excluded)
        excluded_btn_row.addStretch(1)
        lay.addLayout(excluded_btn_row)

        excluded_faces_title = QLabel("Excluded Faces")
        excluded_faces_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        lay.addWidget(excluded_faces_title)

        excluded_faces_hint = QLabel(
            "Faces listed here are excluded from suggestions/views. "
            "Other faces of the same image remain available."
        )
        excluded_faces_hint.setWordWrap(True)
        lay.addWidget(excluded_faces_hint)

        self.excluded_faces_list = QListWidget()
        lay.addWidget(self.excluded_faces_list, 1)

        excluded_faces_btn_row = QHBoxLayout()
        self.btn_add_excluded_face = QPushButton("Add Face ID...")
        self.btn_add_excluded_face.clicked.connect(self._on_add_excluded_face_clicked)
        excluded_faces_btn_row.addWidget(self.btn_add_excluded_face)
        self.btn_remove_excluded_face = QPushButton("Re-include Selected Face")
        self.btn_remove_excluded_face.clicked.connect(self._on_remove_excluded_face_clicked)
        excluded_faces_btn_row.addWidget(self.btn_remove_excluded_face)
        excluded_faces_btn_row.addStretch(1)
        lay.addLayout(excluded_faces_btn_row)

        self._refresh_sources()
        self._refresh_excluded_images()
        self._refresh_excluded_faces()
        return page

    def _refresh_sources(self) -> None:
        self.sources_list.clear()
        try:
            rows = list(self._on_list_sources())
        except Exception as exc:
            QMessageBox.critical(self, "Sources Error", f"Could not load sources:\n{exc}")
            rows = []
        for path in rows:
            self.sources_list.addItem(QListWidgetItem(str(path)))

    def _on_add_source_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Source Folder")
        if not folder:
            return
        ok, message = self._on_add_source(str(folder))
        if not ok:
            QMessageBox.critical(self, "Add Source Failed", message)
            return
        self._refresh_sources()

    def _on_remove_source_clicked(self) -> None:
        item = self.sources_list.currentItem()
        if item is None:
            return
        path = item.text().strip()
        if not path:
            return

        warn = QMessageBox.question(
            self,
            "Remove Source Folder",
            "Do you really want to remove this source folder?\n\n"
            "Important: Existing face/person analysis data already stored in the database "
            "will remain unchanged. Only future monitoring/import from this folder is removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if warn != QMessageBox.StandardButton.Yes:
            return

        ok, message = self._on_remove_source(path)
        if not ok:
            QMessageBox.critical(self, "Remove Source Failed", message)
            return
        self._refresh_sources()

    def _refresh_excluded_images(self) -> None:
        self.excluded_list.clear()
        try:
            rows = list(self._on_list_excluded_images())
        except Exception as exc:
            QMessageBox.critical(self, "Excluded Images Error", f"Could not load excluded images:\n{exc}")
            rows = []
        for path in rows:
            self.excluded_list.addItem(QListWidgetItem(str(path)))

    def _on_add_excluded_clicked(self) -> None:
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Image to Exclude",
            "",
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )
        if not image_path:
            return
        ok, message = self._on_add_excluded_image(str(image_path))
        if not ok:
            QMessageBox.critical(self, "Exclude Image Failed", message)
            return
        self._refresh_excluded_images()

    def _on_remove_excluded_clicked(self) -> None:
        item = self.excluded_list.currentItem()
        if item is None:
            return
        path = item.text().strip()
        if not path:
            return

        warn = QMessageBox.question(
            self,
            "Remove Excluded Image",
            "Do you want to include this image again in analysis and search pages?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if warn != QMessageBox.StandardButton.Yes:
            return

        ok, message = self._on_remove_excluded_image(path)
        if not ok:
            QMessageBox.critical(self, "Remove Excluded Image Failed", message)
            return
        self._refresh_excluded_images()

        self._refresh_excluded_faces()

    def _refresh_excluded_faces(self) -> None:
        self.excluded_faces_list.clear()
        try:
            rows = list(self._on_list_excluded_faces())
        except Exception as exc:
            QMessageBox.critical(self, "Excluded Faces Error", f"Could not load excluded faces:\n{exc}")
            rows = []
        for face_id, path in rows:
            item = QListWidgetItem(f"Face #{int(face_id)} | {str(path)}")
            item.setData(Qt.ItemDataRole.UserRole, int(face_id))
            self.excluded_faces_list.addItem(item)

    def _on_remove_excluded_face_clicked(self) -> None:
        if not hasattr(self, "excluded_faces_list"):
            return
        item = self.excluded_faces_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if data is None:
            return
        face_id = int(data)

        warn = QMessageBox.question(
            self,
            "Re-include Face",
            f"Do you want to include face #{face_id} again?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if warn != QMessageBox.StandardButton.Yes:
            return

        ok, message = self._on_remove_excluded_face(face_id)
        if not ok:
            QMessageBox.critical(self, "Re-include Face Failed", message)
            return
        self._refresh_excluded_faces()

    def _on_add_excluded_face_clicked(self) -> None:
        face_id, ok_pressed = QInputDialog.getInt(
            self,
            "Exclude Face",
            "Face ID:",
            1,
            1,
            2_000_000_000,
            1,
        )
        if not ok_pressed:
            return
        ok, message = self._on_add_excluded_face(int(face_id))
        if not ok:
            QMessageBox.critical(self, "Exclude Face Failed", message)
            return
        self._refresh_excluded_faces()

    def _build_database_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(10)

        title = QLabel("Database")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        lay.addWidget(title)

        description = QLabel(
            "Reset the database to factory state.\n"
            "All persons, faces, assignments, and embeddings will be permanently removed."
        )
        description.setWordWrap(True)
        lay.addWidget(description)

        self.btn_reset = QPushButton("Reset Database to Factory State")
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        lay.addWidget(self.btn_reset, alignment=ALIGN_CENTER)

        lay.addStretch(1)
        return page

    def _on_reset_clicked(self) -> None:
        warning = QMessageBox.warning(
            self,
            "Irreversible Action",
            "Do you really want to permanently delete the database\n"
            "and reset to factory state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if warning != QMessageBox.StandardButton.Yes:
            return

        confirm = DeleteConfirmDialog(self)
        if confirm.exec() != int(QDialog.DialogCode.Accepted):
            return

        ok, message = self._on_reset_database()
        if ok:
            QMessageBox.information(self, "Reset Complete", message)
        else:
            QMessageBox.critical(self, "Reset Failed", message)
