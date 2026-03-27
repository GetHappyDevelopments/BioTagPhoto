from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, cast

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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
from image_loader import load_bgr_image
import db as dbmod


ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
TRANS_SMOOTH = Qt.TransformationMode.SmoothTransformation

DEFAULT_PAGE_SIZE = 240
PAGE_SIZE_OPTIONS = (120, 240, 480, 960)
THUMB_JPEG_QUALITY = 85


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
        self._image_cache_max = 24
        self._current_page = 0
        self._page_size = int(DEFAULT_PAGE_SIZE)
        self._thumb_root = Path(getattr(dbmod, "APP_DATA_DIR", Path.cwd())) / "face_thumbs"
        self._thumb_root.mkdir(parents=True, exist_ok=True)

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

        paging = QHBoxLayout()
        paging.setSpacing(8)

        self.btn_prev = QPushButton("Previous")
        self.btn_prev.setObjectName("Ghost")
        self.btn_prev.clicked.connect(self._go_prev_page)
        paging.addWidget(self.btn_prev)

        self.btn_next = QPushButton("Next")
        self.btn_next.setObjectName("Ghost")
        self.btn_next.clicked.connect(self._go_next_page)
        paging.addWidget(self.btn_next)

        self.page_info = QLabel("")
        self.page_info.setObjectName("Subtle")
        paging.addWidget(self.page_info)

        paging.addWidget(QLabel("Page:"))

        self.page_jump = QLineEdit()
        self.page_jump.setObjectName("Search")
        self.page_jump.setPlaceholderText("1")
        self.page_jump.setFixedWidth(64)
        self.page_jump.returnPressed.connect(self._go_to_page_from_input)
        paging.addWidget(self.page_jump)

        self.btn_go_page = QPushButton("Go")
        self.btn_go_page.setObjectName("Ghost")
        self.btn_go_page.clicked.connect(self._go_to_page_from_input)
        paging.addWidget(self.btn_go_page)

        paging.addStretch(1)
        paging.addWidget(QLabel("Per page:"))

        self.page_size_box = QComboBox()
        for value in PAGE_SIZE_OPTIONS:
            self.page_size_box.addItem(str(value), int(value))
        idx = self.page_size_box.findData(int(self._page_size))
        if idx >= 0:
            self.page_size_box.setCurrentIndex(idx)
        self.page_size_box.currentIndexChanged.connect(self._on_page_size_changed)
        paging.addWidget(self.page_size_box)
        root.addLayout(paging)

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
            cb(0, 2, "Loading unknown faces...")
        self._faces = db_list_unknown_faces()
        self._prune_thumb_cache({int(face.face_id) for face in self._faces})
        if cb is not None:
            cb(1, 2, "Applying filters...")
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

        total_pages = self._total_pages()
        if total_pages <= 0:
            self._current_page = 0
        else:
            self._current_page = max(0, min(self._current_page, total_pages - 1))

        self._render(progress_cb=progress_cb)
        self._update_pagination_controls()
        self._update_status()

    def _total_pages(self) -> int:
        if not self._filtered:
            return 0
        return (len(self._filtered) + self._page_size - 1) // self._page_size

    def _page_slice(self) -> list[UnknownFace]:
        if not self._filtered:
            return []
        start = int(self._current_page * self._page_size)
        end = min(len(self._filtered), start + self._page_size)
        return self._filtered[start:end]

    def _render(self, progress_cb: Callable[[int, int, str], None] | None = None) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

        page_faces = self._page_slice()
        if not page_faces:
            lbl = QLabel("No unknown faces.")
            lbl.setObjectName("Subtle")
            self.grid.addWidget(lbl, 0, 0, alignment=ALIGN_CENTER)
            if progress_cb is not None:
                progress_cb(1, 1, "No unknown faces.")
            return

        cols = 6
        r = 0
        c = 0
        total = max(1, len(page_faces))
        start_index = self._current_page * self._page_size + 1
        end_index = start_index + len(page_faces) - 1
        if progress_cb is not None:
            progress_cb(0, total, f"Preparing unknown face tiles {start_index}-{end_index}...")

        for i, face in enumerate(page_faces, start=1):
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

        img = load_bgr_image(key)
        if img is None:
            return None

        self._image_cache[key] = img
        if len(self._image_cache) > int(self._image_cache_max):
            self._image_cache.popitem(last=False)
        return img

    def _thumb_path(self, face: UnknownFace, size: int) -> Path:
        bucket = self._thumb_root / f"{int(face.face_id) // 1000:05d}"
        return bucket / f"{int(face.face_id)}_{int(size)}.jpg"

    def _build_thumb_file(self, face: UnknownFace, size: int) -> Path | None:
        image = self._read_image_cached(face.path)
        if image is None:
            return None

        crop = image[face.y:face.y + face.h, face.x:face.x + face.w]
        if crop.size == 0:
            return None

        src_h, src_w = crop.shape[:2]
        if src_h <= 0 or src_w <= 0:
            return None

        scale = min(float(size) / float(src_w), float(size) / float(src_h))
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized = cv2.resize(crop, (new_w, new_h), interpolation=interp)

        canvas = np.full((int(size), int(size), 3), 245, dtype=np.uint8)
        off_x = max(0, (int(size) - new_w) // 2)
        off_y = max(0, (int(size) - new_h) // 2)
        canvas[off_y:off_y + new_h, off_x:off_x + new_w] = resized

        thumb_path = self._thumb_path(face, size)
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        ok = bool(cv2.imwrite(str(thumb_path), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), int(THUMB_JPEG_QUALITY)]))
        if not ok:
            return None
        return thumb_path

    def _face_pixmap(self, face: UnknownFace, size: int) -> QPixmap:
        key = (int(face.face_id), int(size))
        cached = self._thumb_cache.get(key)
        if cached is not None:
            return cached

        thumb_path = self._thumb_path(face, size)
        if not thumb_path.exists():
            built = self._build_thumb_file(face, size)
            if built is None:
                pix = QPixmap()
                self._thumb_cache[key] = pix
                return pix
            thumb_path = built

        pix = QPixmap(str(thumb_path))
        if pix.isNull():
            try:
                thumb_path.unlink(missing_ok=True)
            except Exception:
                pass
            rebuilt = self._build_thumb_file(face, size)
            if rebuilt is None:
                pix = QPixmap()
                self._thumb_cache[key] = pix
                return pix
            pix = QPixmap(str(rebuilt))

        if not pix.isNull() and (pix.width() != int(size) or pix.height() != int(size)):
            pix = pix.scaled(int(size), int(size), ASPECT_KEEP, TRANS_SMOOTH)
        self._thumb_cache[key] = pix
        return pix

    def _go_prev_page(self) -> None:
        if self._current_page <= 0:
            return
        self._current_page -= 1
        self._render()
        self._update_pagination_controls()
        self._update_status()
        self.scroll.verticalScrollBar().setValue(0)

    def _go_next_page(self) -> None:
        total_pages = self._total_pages()
        if self._current_page + 1 >= total_pages:
            return
        self._current_page += 1
        self._render()
        self._update_pagination_controls()
        self._update_status()
        self.scroll.verticalScrollBar().setValue(0)

    def _go_to_page_from_input(self) -> None:
        total_pages = self._total_pages()
        if total_pages <= 0:
            self.page_jump.clear()
            return

        raw = self.page_jump.text().strip()
        if not raw:
            self.page_jump.setText(str(self._current_page + 1))
            return

        try:
            page_number = int(raw)
        except Exception:
            self.page_jump.setText(str(self._current_page + 1))
            self.page_jump.selectAll()
            return

        page_number = max(1, min(page_number, total_pages))
        target_page = page_number - 1
        if target_page == int(self._current_page):
            self.page_jump.setText(str(page_number))
            return

        self._current_page = int(target_page)
        self._render()
        self._update_pagination_controls()
        self._update_status()
        self.scroll.verticalScrollBar().setValue(0)

    def _on_page_size_changed(self, _index: int) -> None:
        data = self.page_size_box.currentData()
        if data is None:
            return
        try:
            new_size = int(data)
        except Exception:
            return
        if new_size <= 0 or new_size == int(self._page_size):
            return
        self._page_size = int(new_size)
        self._current_page = 0
        self._render()
        self._update_pagination_controls()
        self._update_status()
        self.scroll.verticalScrollBar().setValue(0)

    def _update_pagination_controls(self) -> None:
        total_items = len(self._filtered)
        total_pages = self._total_pages()
        if total_items <= 0 or total_pages <= 0:
            self.page_info.setText("Page 0/0")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            self.page_jump.clear()
            self.page_jump.setEnabled(False)
            self.btn_go_page.setEnabled(False)
            return

        start = self._current_page * self._page_size + 1
        end = min(total_items, start + self._page_size - 1)
        self.page_info.setText(
            f"Page {self._current_page + 1}/{total_pages} | showing {start}-{end} of {total_items}"
        )
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page + 1 < total_pages)
        self.page_jump.setEnabled(True)
        self.btn_go_page.setEnabled(True)
        self.page_jump.setText(str(self._current_page + 1))

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
        total_pages = self._total_pages()
        if total_pages <= 0:
            page_text = "page 0/0"
        else:
            page_text = f"page {self._current_page + 1}/{total_pages}"
        self.subtle.setText(
            f"{len(self._filtered)} faces | {page_text} | {len(self._selected_ids)} selected"
        )

    def _run_assign_with_progress(self, face_ids: Sequence[int], person_id: int) -> None:
        ids = [int(fid) for fid in face_ids]
        assign_total = max(1, len(ids))
        update_total = max(1, len(ids))
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
            dlg.setLabelText("Updating unknown view...")
            dlg.setValue(assign_total)
            QApplication.processEvents()
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

        total = max(1, len(remove_set))
        if progress_cb is not None:
            progress_cb(0, total, "Updating unknown view...")

        self._faces = [face for face in self._faces if int(face.face_id) not in remove_set]
        self._selected_ids = [fid for fid in self._selected_ids if int(fid) not in remove_set]
        self._prune_thumb_cache({int(face.face_id) for face in self._faces})

        if progress_cb is not None:
            progress_cb(total, total, "Updating unknown view...")
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
