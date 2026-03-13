from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence, cast

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .dialog_photo_viewer import PhotoViewerDialog
import db as dbmod


ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
TRANS_SMOOTH = Qt.TransformationMode.SmoothTransformation
IMG_RGB888 = QImage.Format.Format_RGB888


PAGE_QSS = """
QLabel#Title { font-size: 16px; font-weight: 800; }
QLabel#Subtle { color: #555; font-size: 12px; }

QPushButton#Ghost {
  background: #ffffff; border: 1px solid #dcdcdc;
  padding: 8px 12px; border-radius: 8px;
}
QPushButton#Ghost:hover { background: #f6f6f6; }

QLineEdit#Search {
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #dcdcdc;
  border-radius: 8px;
}

QFrame#FaceTile {
  border: 1px solid #e4e4e4;
  border-radius: 10px;
  background: #ffffff;
}
QFrame#FaceTile[selected="true"] {
  border: 2px solid #0aa4e8;
  background: #f2fbff;
}
QLabel#FaceId { color: #666; font-size: 11px; }
"""


@dataclass(frozen=True)
class UnknownFace:
    face_id: int
    path: str
    x: int
    y: int
    w: int
    h: int


def _call_db(name: str, *args: Any) -> Any:
    fn = getattr(dbmod, name, None)
    if not callable(fn):
        raise RuntimeError(f"db.{name} not found")
    return fn(*args)


def db_list_unknown_faces() -> list[UnknownFace]:
    rows_any = _call_db("list_unknown_faces")
    rows = cast(Iterable[Any], rows_any)
    out: list[UnknownFace] = []
    for row in rows:
        try:
            fid, path, x, y, w, h = row
            out.append(UnknownFace(int(fid), str(path), int(x), int(y), int(w), int(h)))
        except Exception:
            continue
    return out


def db_list_people_with_face_count() -> list[tuple[int, str, int]]:
    rows_any = _call_db("list_people_with_face_count")
    rows = cast(Iterable[Any], rows_any)
    out: list[tuple[int, str, int]] = []
    for row in rows:
        try:
            pid, name, cnt = row
            out.append((int(pid), str(name), int(cnt)))
        except Exception:
            continue
    return out


def db_create_person(name: str) -> int:
    return int(_call_db("create_person", str(name)))


def db_assign_faces_to_person(
    face_ids: Sequence[int],
    person_id: int,
    progress_cb: Callable[[int, int], None] | None = None,
) -> None:
    _call_db(
        "assign_faces_to_person",
        [int(fid) for fid in face_ids],
        int(person_id),
        progress_cb,
    )


def db_add_excluded_image(path: str) -> None:
    _call_db("add_excluded_image", str(path))


def db_add_excluded_face(face_id: int) -> None:
    _call_db("add_excluded_face", int(face_id))


class FaceTile(QFrame):
    def __init__(
        self,
        face: UnknownFace,
        pix: QPixmap,
        on_select: Callable[[int], None],
        on_open: Callable[[UnknownFace], None],
    ):
        super().__init__()
        self.setObjectName("FaceTile")
        self.setProperty("selected", False)
        self._face = face
        self._on_select = on_select
        self._on_open = on_open

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        self.img = QLabel()
        self.img.setAlignment(ALIGN_CENTER)
        self.img.setPixmap(pix)
        lay.addWidget(self.img)

        self.lbl = QLabel(f"#{face.face_id}")
        self.lbl.setObjectName("FaceId")
        self.lbl.setAlignment(ALIGN_CENTER)
        lay.addWidget(self.lbl)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event: Any) -> None:
        self._on_select(int(self._face.face_id))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self._on_open(self._face)
        super().mouseDoubleClickEvent(event)


class UnknownPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(PAGE_QSS)

        self._faces: list[UnknownFace] = []
        self._filtered: list[UnknownFace] = []
        self._selected_ids: list[int] = []
        self._thumb_cache: dict[tuple[int, int], QPixmap] = {}
        self._image_cache: OrderedDict[str, Any] = OrderedDict()
        self._image_cache_max = 48

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("Unknown Faces")
        title.setObjectName("Title")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(8)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setObjectName("Ghost")
        self.btn_refresh.clicked.connect(self.refresh)
        top.addWidget(self.btn_refresh)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search by file path...")
        self.search.textChanged.connect(self._apply_filter)
        top.addWidget(self.search, 1)

        self.sort_box = QComboBox()
        self.sort_box.addItems(["Face ID", "File"])
        self.sort_box.currentIndexChanged.connect(self._apply_filter)
        top.addWidget(self.sort_box)
        root.addLayout(top)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.btn_assign = QPushButton("Assign Selected")
        self.btn_assign.setObjectName("Ghost")
        self.btn_assign.clicked.connect(self._assign_selected)
        actions.addWidget(self.btn_assign)

        self.btn_create = QPushButton("Create Person + Assign")
        self.btn_create.setObjectName("Ghost")
        self.btn_create.clicked.connect(self._create_and_assign)
        actions.addWidget(self.btn_create)

        self.btn_exclude_faces = QPushButton("Exclude Selected Faces")
        self.btn_exclude_faces.setObjectName("Ghost")
        self.btn_exclude_faces.clicked.connect(self._exclude_selected_faces)
        actions.addWidget(self.btn_exclude_faces)

        self.btn_exclude_images = QPushButton("Exclude Selected Images")
        self.btn_exclude_images.setObjectName("Ghost")
        self.btn_exclude_images.clicked.connect(self._exclude_selected_images)
        actions.addWidget(self.btn_exclude_images)

        actions.addStretch(1)
        root.addLayout(actions)

        self.subtle = QLabel("")
        self.subtle.setObjectName("Subtle")
        root.addWidget(self.subtle)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)

        self.host = QWidget()
        self.grid = QGridLayout(self.host)
        self.grid.setContentsMargins(4, 4, 4, 4)
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(10)
        self.scroll.setWidget(self.host)

        self.refresh()

    def refresh(
        self,
        _ignored: object | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        cb = progress_cb if callable(progress_cb) else None
        if cb is not None:
            cb(0, 1, "Loading unknown faces...")
        self._faces = db_list_unknown_faces()
        self._prune_thumb_cache({int(face.face_id) for face in self._faces})
        self._apply_filter(progress_cb=cb)

    def _prune_thumb_cache(self, valid_face_ids: set[int]) -> None:
        if not self._thumb_cache:
            return
        remove_keys = [key for key in self._thumb_cache.keys() if int(key[0]) not in valid_face_ids]
        for key in remove_keys:
            self._thumb_cache.pop(key, None)

    def _apply_filter(
        self,
        _ignored: object | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        q = self.search.text().strip().lower()
        if not q:
            faces = list(self._faces)
        else:
            faces = [f for f in self._faces if q in f.path.lower()]

        if self.sort_box.currentText() == "File":
            faces.sort(key=lambda f: f.path.lower())
        else:
            faces.sort(key=lambda f: f.face_id)

        self._filtered = faces
        visible = {f.face_id for f in self._filtered}
        self._selected_ids = [fid for fid in self._selected_ids if fid in visible]
        self._render(progress_cb=progress_cb)
        self._update_status()

    def _render(self, progress_cb: Callable[[int, int, str], None] | None = None) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

        if not self._filtered:
            lbl = QLabel("No unknown faces.")
            lbl.setObjectName("Subtle")
            self.grid.addWidget(lbl, 0, 0, alignment=ALIGN_CENTER)
            if progress_cb is not None:
                progress_cb(1, 1, "No unknown faces.")
            return

        cols = 6
        r = 0
        c = 0
        total = max(1, len(self._filtered))
        if progress_cb is not None:
            progress_cb(0, total, "Preparing unknown face tiles...")
        for i, face in enumerate(self._filtered, start=1):
            tile = FaceTile(
                face=face,
                pix=self._face_pixmap(face, 120),
                on_select=self._on_select_face,
                on_open=self._open_viewer,
            )
            tile.set_selected(face.face_id in self._selected_ids)
            self.grid.addWidget(tile, r, c)
            if progress_cb is not None:
                progress_cb(i, total, f"Preparing unknown face tiles... {i}/{total}")
            c += 1
            if c >= cols:
                c = 0
                r += 1

    def _read_image_cached(self, path: str) -> Any:
        key = str(path)
        cached = self._image_cache.get(key)
        if cached is not None:
            self._image_cache.move_to_end(key)
            return cached

        img = cv2.imread(key)
        if img is None:
            return None

        self._image_cache[key] = img
        if len(self._image_cache) > int(self._image_cache_max):
            self._image_cache.popitem(last=False)
        return img

    def _face_pixmap(self, face: UnknownFace, size: int) -> QPixmap:
        key = (face.face_id, int(size))
        if key in self._thumb_cache:
            return self._thumb_cache[key]

        image = self._read_image_cached(face.path)
        if image is None:
            pix = QPixmap()
            self._thumb_cache[key] = pix
            return pix

        crop = image[face.y:face.y + face.h, face.x:face.x + face.w]
        if crop.size == 0:
            pix = QPixmap()
            self._thumb_cache[key] = pix
            return pix

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        hh, ww, _ = rgb.shape
        qimg = QImage(rgb.data, ww, hh, 3 * ww, IMG_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(size, size, ASPECT_KEEP, TRANS_SMOOTH)
        self._thumb_cache[key] = pix
        return pix

    def _on_select_face(self, face_id: int) -> None:
        if face_id in self._selected_ids:
            self._selected_ids.remove(face_id)
        else:
            self._selected_ids.append(int(face_id))
        self._render()
        self._update_status()

    def _open_viewer(self, face: UnknownFace) -> None:
        dlg = PhotoViewerDialog(
            image_path=face.path,
            face_rect=(face.x, face.y, face.w, face.h),
            title="Unknown - Photo",
            parent=self,
        )
        dlg.exec()

    def _update_status(self) -> None:
        self.subtle.setText(f"{len(self._filtered)} faces | {len(self._selected_ids)} selected")

    def _run_assign_with_progress(self, face_ids: Sequence[int], person_id: int) -> None:
        ids = [int(fid) for fid in face_ids]
        assign_total = max(1, len(ids))
        update_total = max(1, len(self._faces))
        grand_total = assign_total + update_total

        dlg = QProgressDialog("Assigning faces...", "", 0, grand_total, self)
        dlg.setWindowTitle("Assign Faces")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        def _on_progress(current: int, total_count: int) -> None:
            t = max(1, int(total_count))
            c = max(0, min(int(current), t))
            mapped = min(assign_total, int(round((c / t) * assign_total)))
            dlg.setRange(0, grand_total)
            dlg.setValue(mapped)
            dlg.setLabelText(f"Assigning faces... {c}/{t}")
            QApplication.processEvents()

        def _on_update_progress(current: int, total_count: int, message: str) -> None:
            t = max(1, int(total_count))
            c = max(0, min(int(current), t))
            mapped = assign_total + min(update_total, int(round((c / t) * update_total)))
            dlg.setRange(0, grand_total)
            dlg.setValue(mapped)
            dlg.setLabelText(str(message))
            QApplication.processEvents()

        try:
            db_assign_faces_to_person(ids, int(person_id), progress_cb=_on_progress)
            dlg.setLabelText("Recomputing person prototype...")
            dlg.setValue(assign_total)
            QApplication.processEvents()
            dlg.setLabelText("Updating unknown view...")
            self._remove_assigned_faces_from_view(ids, progress_cb=_on_update_progress)
            dlg.setValue(grand_total)
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

    def _remove_assigned_faces_from_view(
        self,
        removed_face_ids: Sequence[int],
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        remove_set = {int(fid) for fid in removed_face_ids}
        if not remove_set:
            return

        self._faces = [face for face in self._faces if int(face.face_id) not in remove_set]
        self._selected_ids = [fid for fid in self._selected_ids if int(fid) not in remove_set]
        self._prune_thumb_cache({int(face.face_id) for face in self._faces})
        self._apply_filter(progress_cb=progress_cb)

    def _assign_selected(self) -> None:
        if not self._selected_ids:
            return
        people = db_list_people_with_face_count()
        if not people:
            QMessageBox.information(self, "No people", "Create a person first.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Assign to person")
        dlg.resize(420, 130)
        lay = QVBoxLayout(dlg)
        combo = QComboBox()
        for pid, name, cnt in people:
            combo.addItem(f"{name} ({cnt} faces)", int(pid))
        lay.addWidget(combo)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != int(QDialog.DialogCode.Accepted):
            return

        pid_data = combo.currentData()
        if pid_data is None:
            return
        person_id = int(cast(Any, pid_data))
        try:
            self._run_assign_with_progress(self._selected_ids, person_id)
            self._mark_pages_dirty()
        except Exception as e:
            QMessageBox.critical(self, "Assign error", str(e))
            return

    def _create_and_assign(self) -> None:
        if not self._selected_ids:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Create person")
        dlg.resize(420, 130)
        lay = QVBoxLayout(dlg)
        edit = QLineEdit()
        edit.setPlaceholderText("Person name")
        lay.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != int(QDialog.DialogCode.Accepted):
            return

        name = edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
            return

        try:
            pid = db_create_person(name)
            self._run_assign_with_progress(self._selected_ids, int(pid))
            self._mark_pages_dirty()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

    def _exclude_selected_images(self) -> None:
        if not self._selected_ids:
            QMessageBox.information(self, "No selection", "Select at least one face first.")
            return

        id_set = {int(fid) for fid in self._selected_ids}
        selected_faces = [face for face in self._faces if int(face.face_id) in id_set]
        unique_paths = sorted({str(face.path) for face in selected_faces})
        if not unique_paths:
            return

        confirm = QMessageBox.question(
            self,
            "Exclude Images",
            f"Exclude {len(unique_paths)} image(s) from search and analysis?\n"
            "You can re-include them later in Settings > Sources > Excluded Images.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            for path in unique_paths:
                db_add_excluded_image(path)
        except Exception as e:
            QMessageBox.critical(self, "Exclude failed", str(e))
            return

        self._selected_ids = []
        self._mark_pages_dirty()
        self.refresh()

    def _exclude_selected_faces(self) -> None:
        if not self._selected_ids:
            QMessageBox.information(self, "No selection", "Select at least one face first.")
            return

        face_ids = sorted({int(fid) for fid in self._selected_ids})
        confirm = QMessageBox.question(
            self,
            "Exclude Faces",
            f"Exclude {len(face_ids)} selected face(s)?\n"
            "Other faces in the same image remain available.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            for fid in face_ids:
                db_add_excluded_face(int(fid))
        except Exception as e:
            QMessageBox.critical(self, "Exclude failed", str(e))
            return

        self._selected_ids = []
        self._mark_pages_dirty()
        self.refresh()
    def _mark_pages_dirty(self) -> None:
        win = self.window()
        if win is None:
            return
        fn = getattr(win, "_mark_all_pages_dirty", None)
        if callable(fn):
            fn()
