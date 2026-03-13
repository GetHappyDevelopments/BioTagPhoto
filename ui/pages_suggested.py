from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Sequence, cast

import cv2
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dialog_auto_assign_preview import AutoAssignPreviewDialog, AutoAssignPreviewRow
from .dialog_photo_viewer import PhotoViewerDialog
import db as dbmod


ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft
ORIENT_H = Qt.Orientation.Horizontal
ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
TRANS_SMOOTH = Qt.TransformationMode.SmoothTransformation
IMG_RGB888 = QImage.Format.Format_RGB888


SETTINGS_ORG = "BioTagPhoto"
SETTINGS_APP = "BioTagPhoto"
SETTING_AUTO_THRESHOLD = "unknown/auto_assign_threshold"


PAGE_QSS = """
QLabel#Title { font-size: 16px; font-weight: 800; }
QLabel#Subtle { color: #555; font-size: 12px; }

QPushButton#Ghost {
  background: #ffffff; border: 1px solid #dcdcdc;
  padding: 8px 12px; border-radius: 8px;
}
QPushButton#Ghost:hover { background: #f6f6f6; }

QFrame#Panel {
  border: 1px solid #e4e4e4;
  border-radius: 10px;
  background: #ffffff;
}
"""


@dataclass(frozen=True)
class UnknownFace:
    face_id: int
    path: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class SuggestionRow:
    face_id: int
    person_id: int
    person_name: str
    score: float


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


def db_suggest_people_for_faces(face_ids: Sequence[int], top_k: int = 3) -> dict[int, list[tuple[int, float]]]:
    try:
        rows_any = _call_db("suggest_people_for_faces", [int(fid) for fid in face_ids], int(top_k))
    except Exception:
        return {}
    raw = cast(dict[Any, Any], rows_any)
    out: dict[int, list[tuple[int, float]]] = {}
    for key, value in raw.items():
        try:
            fid = int(key)
        except Exception:
            continue
        rows = cast(Iterable[Any], value)
        parsed: list[tuple[int, float]] = []
        for row in rows:
            try:
                pid, score = row
                parsed.append((int(pid), float(score)))
            except Exception:
                continue
        out[fid] = parsed
    return out


def db_begin_assignment_batch() -> str:
    return str(_call_db("begin_assignment_batch"))


def db_apply_assignments(
    batch_id: str,
    assignments: list[tuple[int, int]],
    progress_cb: Callable[[int, int], None] | None = None,
) -> None:
    _call_db("apply_assignments", str(batch_id), list(assignments), progress_cb)


def db_add_excluded_image(path: str) -> None:
    _call_db("add_excluded_image", str(path))


def db_add_excluded_face(face_id: int) -> None:
    _call_db("add_excluded_face", int(face_id))


class SuggestedPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(PAGE_QSS)

        self._settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._auto_threshold = float(self._settings.value(SETTING_AUTO_THRESHOLD, 0.85, type=float))
        self._auto_threshold = max(0.50, min(0.99, self._auto_threshold))

        self._faces: list[UnknownFace] = []
        self._face_by_id: dict[int, UnknownFace] = {}
        self._people: list[tuple[int, str, int]] = []
        self._person_name_by_id: dict[int, str] = {}
        self._last_dry_run: list[SuggestionRow] = []
        self._visible_dry_run: list[SuggestionRow] = []
        self._thumb_cache: dict[tuple[int, int], QPixmap] = {}
        self._image_cache: OrderedDict[str, Any] = OrderedDict()
        self._image_cache_max = 32

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("Suggested")
        title.setObjectName("Title")
        root.addWidget(title)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addStretch(1)
        root.addLayout(top)

        panel = QFrame()
        panel.setObjectName("Panel")
        p_lay = QHBoxLayout(panel)
        p_lay.setContentsMargins(10, 8, 10, 8)
        p_lay.setSpacing(8)

        p_lay.addWidget(QLabel("Threshold:"), alignment=ALIGN_LEFT)
        self.sld_threshold = QSlider(ORIENT_H)
        self.sld_threshold.setMinimum(50)
        self.sld_threshold.setMaximum(99)
        self.sld_threshold.setValue(int(round(self._auto_threshold * 100)))
        self.sld_threshold.valueChanged.connect(self._on_threshold_changed)
        p_lay.addWidget(self.sld_threshold, 1)

        self.lbl_threshold = QLabel(f"{self._auto_threshold:.2f}")
        self.lbl_threshold.setMinimumWidth(42)
        p_lay.addWidget(self.lbl_threshold)

        p_lay.addWidget(QLabel("Person:"), alignment=ALIGN_LEFT)
        self.cmb_person_filter = QComboBox()
        self.cmb_person_filter.currentIndexChanged.connect(self._on_person_filter_changed)
        p_lay.addWidget(self.cmb_person_filter)

        self.btn_dry_run = QPushButton("Similar faces")
        self.btn_dry_run.setObjectName("Ghost")
        self.btn_dry_run.clicked.connect(self._run_dry_run)
        p_lay.addWidget(self.btn_dry_run)

        self.btn_apply = QPushButton("Apply selected")
        self.btn_apply.setObjectName("Ghost")
        self.btn_apply.clicked.connect(self._apply_selected_assignments)
        p_lay.addWidget(self.btn_apply)

        self.btn_exclude_faces = QPushButton("Exclude selected faces")
        self.btn_exclude_faces.setObjectName("Ghost")
        self.btn_exclude_faces.clicked.connect(self._exclude_selected_faces)
        p_lay.addWidget(self.btn_exclude_faces)

        self.btn_exclude_images = QPushButton("Exclude selected images")
        self.btn_exclude_images.setObjectName("Ghost")
        self.btn_exclude_images.clicked.connect(self._exclude_selected_images)
        p_lay.addWidget(self.btn_exclude_images)

        root.addWidget(panel)

        self.subtle = QLabel("")
        self.subtle.setObjectName("Subtle")
        root.addWidget(self.subtle)

        list_panel = QFrame()
        list_panel.setObjectName("Panel")
        list_lay = QVBoxLayout(list_panel)
        list_lay.setContentsMargins(10, 8, 10, 8)
        list_lay.setSpacing(6)

        self.lbl_list_title = QLabel("Current dry-run matches")
        list_lay.addWidget(self.lbl_list_title)

        self.tbl_matches = QTableWidget()
        self.tbl_matches.setColumnCount(4)
        self.tbl_matches.setHorizontalHeaderLabels(["Face", "FaceID", "Person", "Score"])
        self.tbl_matches.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_matches.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.tbl_matches.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_matches.verticalHeader().setVisible(False)
        self.tbl_matches.cellDoubleClicked.connect(self._open_match_viewer)
        hdr = self.tbl_matches.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        list_lay.addWidget(self.tbl_matches, 1)

        root.addWidget(list_panel, 1)

        self.refresh()

    def _on_threshold_changed(self, value: int) -> None:
        self._auto_threshold = float(int(value)) / 100.0
        self.lbl_threshold.setText(f"{self._auto_threshold:.2f}")
        self._settings.setValue(SETTING_AUTO_THRESHOLD, float(self._auto_threshold))

    def _on_person_filter_changed(self, _index: int) -> None:
        self._refresh_match_table()

    def refresh(
        self,
        _ignored: object | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        cb = progress_cb if callable(progress_cb) else None
        if cb is not None:
            cb(0, 4, "Loading unknown faces...")
        self._faces = db_list_unknown_faces()
        if cb is not None:
            cb(1, 4, "Loading people...")
        self._face_by_id = {int(face.face_id): face for face in self._faces}
        self._people = db_list_people_with_face_count()
        self._person_name_by_id = {int(pid): str(name) for pid, name, _ in self._people}
        self._last_dry_run = []
        self._visible_dry_run = []
        self._thumb_cache.clear()
        self._refresh_person_filter()
        if cb is not None:
            cb(2, 4, "Preparing suggested matches...")
        self._refresh_match_table(progress_cb=cb)
        if cb is not None:
            cb(4, 4, "Suggested view ready.")
        self._update_status()

    def _refresh_person_filter(self) -> None:
        self.cmb_person_filter.blockSignals(True)
        self.cmb_person_filter.clear()
        self.cmb_person_filter.addItem("All persons", 0)
        for pid, name, _cnt in self._people:
            self.cmb_person_filter.addItem(str(name), int(pid))
        self.cmb_person_filter.setCurrentIndex(0)
        self.cmb_person_filter.blockSignals(False)

    def _current_person_filter_id(self) -> int:
        data = self.cmb_person_filter.currentData()
        if data is None:
            return 0
        try:
            return int(data)
        except Exception:
            return 0

    def _update_status(self, dry_run_matches: Optional[int] = None) -> None:
        known_people = len(self._people)
        unknown_faces = len(self._faces)
        if dry_run_matches is None:
            self.subtle.setText(f"Unknown faces: {unknown_faces} | People: {known_people}")
            return
        self.subtle.setText(
            f"Unknown faces: {unknown_faces} | People: {known_people} | Dry-run matches: {int(dry_run_matches)}"
        )

    def _refresh_match_table(self, progress_cb: Callable[[int, int, str], None] | None = None) -> None:
        person_filter_id = self._current_person_filter_id()
        if person_filter_id <= 0:
            rows = list(self._last_dry_run)
        else:
            rows = [r for r in self._last_dry_run if int(r.person_id) == int(person_filter_id)]
        self._visible_dry_run = rows

        self.tbl_matches.setRowCount(len(rows))
        total = max(1, len(rows))
        if progress_cb is not None:
            progress_cb(0, total, "Preparing suggested tiles...")
        for i, row in enumerate(rows):
            self.tbl_matches.setRowHeight(i, 60)
            thumb_item = QTableWidgetItem("")
            thumb = self._face_thumb_pixmap(int(row.face_id), 56)
            if not thumb.isNull():
                thumb_item.setData(Qt.ItemDataRole.DecorationRole, thumb)
            self.tbl_matches.setItem(i, 0, thumb_item)
            self.tbl_matches.setItem(i, 1, QTableWidgetItem(str(row.face_id)))
            self.tbl_matches.setItem(i, 2, QTableWidgetItem(str(row.person_name)))
            self.tbl_matches.setItem(i, 3, QTableWidgetItem(f"{row.score:.4f}"))
            if progress_cb is not None:
                progress_cb(i + 1, total, f"Preparing suggested tiles... {i + 1}/{total}")
        self.btn_apply.setEnabled(len(rows) > 0)

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

    def _face_thumb_pixmap(self, face_id: int, size: int = 56) -> QPixmap:
        key = (int(face_id), int(size))
        if key in self._thumb_cache:
            return self._thumb_cache[key]

        face = self._face_by_id.get(int(face_id))
        if face is None:
            pix = QPixmap()
            self._thumb_cache[key] = pix
            return pix

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

    def _open_match_viewer(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._visible_dry_run):
            return
        match = self._visible_dry_run[int(row)]
        face = self._face_by_id.get(int(match.face_id))
        if face is None:
            return
        dlg = PhotoViewerDialog(
            image_path=face.path,
            face_rect=(face.x, face.y, face.w, face.h),
            title="Suggested - Photo",
            parent=self,
        )
        dlg.exec()

    def _compute_dry_run_rows(
        self,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> list[SuggestionRow]:
        threshold = float(self._auto_threshold)
        rows: list[SuggestionRow] = []
        face_ids = [int(face.face_id) for face in self._faces]
        suggestions_by_face = db_suggest_people_for_faces(face_ids, top_k=1)

        total = max(1, len(self._faces))
        if progress_cb is not None:
            progress_cb(0, total, "Computing similar faces...")

        for i, face in enumerate(self._faces, start=1):
            suggestions = suggestions_by_face.get(int(face.face_id), [])
            if not suggestions:
                if progress_cb is not None:
                    progress_cb(i, total, f"Computing similar faces... {i}/{total}")
                continue
            person_id, score = suggestions[0]
            if float(score) < threshold:
                if progress_cb is not None:
                    progress_cb(i, total, f"Computing similar faces... {i}/{total}")
                continue
            person_name = self._person_name_by_id.get(int(person_id), f"Person {int(person_id)}")
            rows.append(
                SuggestionRow(
                    face_id=int(face.face_id),
                    person_id=int(person_id),
                    person_name=str(person_name),
                    score=float(score),
                )
            )
            if progress_cb is not None:
                progress_cb(i, total, f"Computing similar faces... {i}/{total}")
        rows.sort(key=lambda r: r.score, reverse=True)
        return rows

    def _apply_assignments_with_progress(self, batch_id: str, assignments: list[tuple[int, int]]) -> None:
        total = max(1, len(assignments))
        dlg = QProgressDialog("Applying assignments...", "", 0, total, self)
        dlg.setWindowTitle("Auto-Assign")
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
            dlg.setRange(0, t)
            dlg.setValue(c)
            dlg.setLabelText(f"Applying assignments... {c}/{t}")
            QApplication.processEvents()

        try:
            db_apply_assignments(batch_id, assignments, progress_cb=_on_progress)
            dlg.setLabelText("Recomputing prototypes...")
            dlg.setValue(total)
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

    def _show_preview_and_apply(self, rows: list[SuggestionRow]) -> None:
        preview_rows = [
            AutoAssignPreviewRow(
                face_id=int(r.face_id),
                person_id=int(r.person_id),
                person_name=str(r.person_name),
                score=float(r.score),
            )
            for r in rows
        ]
        dlg = AutoAssignPreviewDialog(rows=preview_rows, total_faces=len(self._faces), parent=self)
        if dlg.exec() != int(QDialog.DialogCode.Accepted):
            return
        if not dlg.apply_requested:
            return

        assignments = dlg.selected_assignments()
        if not assignments:
            QMessageBox.information(self, "Auto-assign", "No assignments selected.")
            return

        try:
            batch_id = db_begin_assignment_batch()
            self._apply_assignments_with_progress(batch_id, assignments)
        except Exception as e:
            QMessageBox.critical(self, "Apply failed", f"Could not apply assignments:\n{e}")
            return

        QMessageBox.information(self, "Auto-assign", f"Applied {len(assignments)} assignments.")
        self.refresh()

    def _selected_rows(self) -> list[SuggestionRow]:
        model = self.tbl_matches.selectionModel()
        if model is None:
            return []
        indices = model.selectedRows()
        selected: list[SuggestionRow] = []
        for idx in indices:
            row_idx = int(idx.row())
            if row_idx < 0 or row_idx >= len(self._visible_dry_run):
                continue
            selected.append(self._visible_dry_run[row_idx])
        return selected

    def _run_dry_run(self) -> None:
        compute_total = max(1, len(self._faces))
        render_total = max(1, len(self._faces))
        grand_total = compute_total + render_total

        dlg = QProgressDialog("Computing similar faces...", "", 0, grand_total, self)
        dlg.setWindowTitle("Similar faces")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        def _compute_cb(current: int, total: int, message: str) -> None:
            t = max(1, int(total))
            c = max(0, min(int(current), t))
            mapped = min(compute_total, int(round((c / t) * compute_total)))
            dlg.setRange(0, grand_total)
            dlg.setValue(mapped)
            dlg.setLabelText(str(message))
            QApplication.processEvents()

        def _render_cb(current: int, total: int, message: str) -> None:
            t = max(1, int(total))
            c = max(0, min(int(current), t))
            mapped = compute_total + min(render_total, int(round((c / t) * render_total)))
            dlg.setRange(0, grand_total)
            dlg.setValue(mapped)
            dlg.setLabelText(str(message))
            QApplication.processEvents()

        rows: list[SuggestionRow] = []
        try:
            rows = self._compute_dry_run_rows(progress_cb=_compute_cb)
            self._last_dry_run = rows
            self._refresh_match_table(progress_cb=_render_cb)
            self._update_status(dry_run_matches=len(rows))
            dlg.setValue(grand_total)
            dlg.setLabelText("Done.")
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

        if not rows:
            QMessageBox.information(self, "Dry-run", "No matches above threshold.")

    def _apply_selected_assignments(self) -> None:
        if not self._last_dry_run:
            self._last_dry_run = self._compute_dry_run_rows()
            self._refresh_match_table()
            self._update_status(dry_run_matches=len(self._last_dry_run))
        if not self._last_dry_run:
            QMessageBox.information(self, "No assignments", "No dry-run matches above threshold.")
            return

        selected = self._selected_rows()
        if not selected:
            QMessageBox.information(self, "No selection", "Select one or more rows first.")
            return
        self._show_preview_and_apply(selected)

    def _exclude_selected_images(self) -> None:
        selected = self._selected_rows()
        if not selected:
            QMessageBox.information(self, "No selection", "Select one or more rows first.")
            return

        paths: set[str] = set()
        for row in selected:
            face = self._face_by_id.get(int(row.face_id))
            if face is None:
                continue
            paths.add(str(face.path))
        if not paths:
            return

        confirm = QMessageBox.question(
            self,
            "Exclude Images",
            f"Exclude {len(paths)} image(s) from search and analysis?\n"
            "You can re-include them later in Settings > Sources > Excluded Images.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            for path in sorted(paths):
                db_add_excluded_image(path)
        except Exception as e:
            QMessageBox.critical(self, "Exclude failed", str(e))
            return

        self._mark_pages_dirty()
        self.refresh()

    def _exclude_selected_faces(self) -> None:
        selected = self._selected_rows()
        if not selected:
            QMessageBox.information(self, "No selection", "Select one or more rows first.")
            return

        face_ids = sorted({int(row.face_id) for row in selected})
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

        self._mark_pages_dirty()
        self.refresh()
    def _mark_pages_dirty(self) -> None:
        win = self.window()
        if win is None:
            return
        fn = getattr(win, "_mark_all_pages_dirty", None)
        if callable(fn):
            fn()
