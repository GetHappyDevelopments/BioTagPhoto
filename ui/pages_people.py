from __future__ import annotations

from typing import Callable, Optional

import cv2
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QEvent
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPainterPath, QColor, QShortcut, QKeySequence
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QScrollArea, QGridLayout,
    QFrame, QSplitter, QPushButton, QMessageBox, QInputDialog,
    QLineEdit, QComboBox, QGraphicsDropShadowEffect, QProgressDialog, QCheckBox
)

from .dialog_photo_viewer import PhotoViewerDialog
from .dialog_metadata import MetadataDialog
from image_loader import load_bgr_image
from xmp_tools import ensure_person_name_in_xmp, has_person_name_in_xmp, remove_person_name_from_xmp

from db import (
    list_people_with_face_count,
    list_faces_for_person,
    rename_person,
    delete_person,
    unassign_all_faces_from_person,
    unassign_face,
    get_first_face_for_person,
    recompute_person_prototype,
    get_connection,
)

# --- Pylance/Stub-sichere Enums
ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
ORIENT_H = Qt.Orientation.Horizontal
CURSOR_POINTING = Qt.CursorShape.PointingHandCursor
ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
TRANS_SMOOTH = Qt.TransformationMode.SmoothTransformation
IMG_RGB888 = QImage.Format.Format_RGB888
DEFAULT_FACE_PAGE_SIZE = 240
FACE_PAGE_SIZE_OPTIONS = (120, 240, 480, 960)


PAGE_QSS = """
QLabel#Title { font-size: 16px; font-weight: 800; }
QLabel#Subtle { color: #555; font-size: 12px; }

QLineEdit#Search {
  min-height: 38px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid #dcdcdc;
  background: #ffffff;
  font-size: 13px;
}
QLineEdit#Search:focus { border: 1px solid #0aa4e8; }

QPushButton#ClearSearch {
  min-height: 38px;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid #dcdcdc;
  background: #ffffff;
}
QPushButton#ClearSearch:hover { background: #f6f6f6; }

QComboBox#SortBox {
  min-height: 38px;
  padding: 6px 10px;
  border-radius: 10px;
  border: 1px solid #dcdcdc;
  background: #ffffff;
}

QFrame#PersonTile {
  border: 1px solid #e4e4e4;
  border-radius: 14px;
  background: #ffffff;
}
QFrame#PersonTile:hover {
  border: 1px solid #bfe7ff;
  background: #f7fbff;
}
QFrame#PersonTile[selected="true"] {
  border: 2px solid #0aa4e8;
  background: #f2fbff;
}

QLabel#PersonName { font-size: 13px; font-weight: 700; }
QLabel#PersonCount { font-size: 12px; color: #444; }

QLabel#Avatar {
  border-radius: 17px;
  border: 1px solid #d6eef9;
  background: #ffffff;
}

QFrame#FaceTile {
  border: 1px solid #e4e4e4;
  border-radius: 12px;
  background: #ffffff;
}
QFrame#FaceTile:hover { background: #f7fbff; border: 1px solid #bfe7ff; }
QFrame#FaceTile[selected="true"] {
  border: 2px solid #0aa4e8;
  background: #f2fbff;
}

QPushButton#Ghost {
  background: #ffffff; border: 1px solid #dcdcdc;
  padding: 10px 12px; border-radius: 10px;
}
QPushButton#Ghost:hover { background: #f6f6f6; }

QPushButton#Danger {
  background: #fff5f5; border: 1px solid #f2b8b8;
  padding: 10px 12px; border-radius: 10px;
}
QPushButton#Danger:hover { background: #ffecec; }
"""


class PersonTile(QFrame):
    def __init__(
        self,
        person_id: int,
        name: str,
        count: int,
        avatar_pix: Optional[QPixmap],
        on_click: Callable[[int], None],
    ):
        super().__init__()
        self.setObjectName("PersonTile")
        self.setCursor(CURSOR_POINTING)
        self.person_id = int(person_id)
        self.on_click = on_click

        self.setProperty("selected", False)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setOffset(0, 3)
        self._shadow.setColor(QColor(0, 0, 0, 35))
        self.setGraphicsEffect(self._shadow)

        self._sticky_anim: Optional[QPropertyAnimation] = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        avatar = QLabel()
        avatar.setObjectName("Avatar")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(ALIGN_CENTER)
        if avatar_pix is not None and not avatar_pix.isNull():
            avatar.setPixmap(avatar_pix)
        lay.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        lbl_name = QLabel(name)
        lbl_name.setObjectName("PersonName")

        lbl_cnt = QLabel(f"{count} faces")
        lbl_cnt.setObjectName("PersonCount")

        text_col.addWidget(lbl_name)
        text_col.addWidget(lbl_cnt)
        lay.addLayout(text_col, 1)

    def _start_sticky(self) -> None:
        if self._sticky_anim is not None:
            return
        anim = QPropertyAnimation(self._shadow, b"blurRadius", self)
        anim.setStartValue(18)
        anim.setEndValue(26)
        anim.setDuration(900)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.setLoopCount(-1)
        anim.start()
        self._sticky_anim = anim

    def _stop_sticky(self) -> None:
        if self._sticky_anim is None:
            return
        self._sticky_anim.stop()
        self._sticky_anim.deleteLater()
        self._sticky_anim = None

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        self.setProperty("selected", selected)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

        if selected:
            self._shadow.setOffset(0, 4)
            self._shadow.setColor(QColor(0, 0, 0, 55))
            self._start_sticky()
        else:
            self._stop_sticky()
            self._shadow.setBlurRadius(14)
            self._shadow.setOffset(0, 3)
            self._shadow.setColor(QColor(0, 0, 0, 35))

    def enterEvent(self, e):
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 7)
        self._shadow.setColor(QColor(0, 0, 0, 70))
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.property("selected") is True:
            self._shadow.setOffset(0, 4)
            self._shadow.setColor(QColor(0, 0, 0, 55))
        else:
            self._shadow.setBlurRadius(14)
            self._shadow.setOffset(0, 3)
            self._shadow.setColor(QColor(0, 0, 0, 35))
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if callable(self.on_click):
            self.on_click(self.person_id)
        super().mousePressEvent(e)


class FaceTile(QFrame):
    def __init__(
        self,
        pix: QPixmap,
        on_select: Callable[[bool, bool], None],
        on_click: Callable[[], None],
    ):
        super().__init__()
        self.setObjectName("FaceTile")
        self.setCursor(CURSOR_POINTING)
        self._on_select = on_select
        self._on_click = on_click
        self.setProperty("selected", False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(0)

        img = QLabel()
        img.setPixmap(pix)
        img.setAlignment(ALIGN_CENTER)
        lay.addWidget(img)

    def mousePressEvent(self, e):
        additive = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        range_select = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if callable(self._on_select):
            self._on_select(additive, range_select)
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if callable(self._on_click):
            self._on_click()
        super().mouseDoubleClickEvent(e)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class PeoplePage(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet(PAGE_QSS)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(ORIENT_H)
        root.addWidget(self.splitter)

        # ---------------- LEFT ----------------
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(10, 10, 10, 10)
        left_lay.setSpacing(8)

        title = QLabel("People")
        title.setObjectName("Title")
        left_lay.addWidget(title)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("Search")
        self.search_edit.setPlaceholderText("Search people…")
        self.search_edit.textChanged.connect(self._apply_filter)
        self.search_edit.returnPressed.connect(self._select_first_result)

        self.btn_clear = QPushButton("✕")
        self.btn_clear.setObjectName("ClearSearch")
        self.btn_clear.setToolTip("Clear search")
        self.btn_clear.clicked.connect(lambda: self.search_edit.setText(""))

        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("SortBox")
        self.sort_combo.addItems(["Sort by Count", "Sort by Name"])
        self.sort_combo.currentIndexChanged.connect(self._apply_filter)

        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(self.btn_clear)
        search_row.addWidget(self.sort_combo)
        left_lay.addLayout(search_row)

        self.result_label = QLabel("")
        self.result_label.setObjectName("Subtle")
        left_lay.addWidget(self.result_label)

        self.people_scroll = QScrollArea()
        self.people_scroll.setWidgetResizable(True)
        self.people_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.people_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.people_host = QWidget()
        self.people_list = QVBoxLayout(self.people_host)
        self.people_list.setContentsMargins(4, 4, 4, 4)
        self.people_list.setSpacing(10)

        self.people_scroll.setWidget(self.people_host)
        left_lay.addWidget(self.people_scroll, 1)

        # ---------------- RIGHT ----------------
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(14, 14, 14, 14)
        right_lay.setSpacing(10)

        self.detail_title = QLabel("No person selected")
        self.detail_title.setStyleSheet("font-size:14px;font-weight:800;")
        right_lay.addWidget(self.detail_title)

        self.detail_sub = QLabel("")
        self.detail_sub.setObjectName("Subtle")
        right_lay.addWidget(self.detail_sub)

        self.detail_proto = QLabel("")
        self.detail_proto.setObjectName("Subtle")
        right_lay.addWidget(self.detail_proto)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_rename = QPushButton("Rename")
        self.btn_rename.setObjectName("Ghost")
        self.btn_rename.setEnabled(False)

        self.btn_unassign = QPushButton("Unassign all")
        self.btn_unassign.setObjectName("Ghost")
        self.btn_unassign.setEnabled(False)

        self.btn_recompute = QPushButton("Rebuild prototype")
        self.btn_recompute.setObjectName("Ghost")
        self.btn_recompute.setEnabled(False)

        self.btn_tag_photo = QPushButton("Tag Photo")
        self.btn_tag_photo.setObjectName("Ghost")
        self.btn_tag_photo.setEnabled(False)

        self.btn_tag_all_photos = QPushButton("Tag all Photos")
        self.btn_tag_all_photos.setObjectName("Ghost")
        self.btn_tag_all_photos.setEnabled(False)

        self.btn_metadata = QPushButton("Metadata")
        self.btn_metadata.setObjectName("Ghost")
        self.btn_metadata.setEnabled(False)

        self.btn_remove_faces = QPushButton("Remove")
        self.btn_remove_faces.setObjectName("Ghost")
        self.btn_remove_faces.setEnabled(False)

        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setObjectName("Danger")
        self.btn_delete.setEnabled(False)

        btn_row.addWidget(self.btn_rename)
        btn_row.addWidget(self.btn_unassign)
        btn_row.addWidget(self.btn_recompute)
        btn_row.addWidget(self.btn_tag_photo)
        btn_row.addWidget(self.btn_tag_all_photos)
        btn_row.addWidget(self.btn_metadata)
        btn_row.addWidget(self.btn_remove_faces)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_delete)
        right_lay.addLayout(btn_row)

        face_paging = QHBoxLayout()
        face_paging.setSpacing(8)

        self.btn_faces_prev = QPushButton("Previous")
        self.btn_faces_prev.setObjectName("Ghost")
        self.btn_faces_prev.setEnabled(False)
        self.btn_faces_prev.clicked.connect(self._go_prev_face_page)
        face_paging.addWidget(self.btn_faces_prev)

        self.btn_faces_next = QPushButton("Next")
        self.btn_faces_next.setObjectName("Ghost")
        self.btn_faces_next.setEnabled(False)
        self.btn_faces_next.clicked.connect(self._go_next_face_page)
        face_paging.addWidget(self.btn_faces_next)

        self.face_page_info = QLabel("")
        self.face_page_info.setObjectName("Subtle")
        face_paging.addWidget(self.face_page_info)

        self.chk_missing_only = QCheckBox("Only missing metadata")
        self.chk_missing_only.stateChanged.connect(self._on_missing_filter_toggled)
        face_paging.addWidget(self.chk_missing_only)

        face_paging.addWidget(QLabel("Page:"))

        self.face_page_jump = QLineEdit()
        self.face_page_jump.setObjectName("Search")
        self.face_page_jump.setPlaceholderText("1")
        self.face_page_jump.setFixedWidth(64)
        self.face_page_jump.returnPressed.connect(self._go_to_face_page_from_input)
        face_paging.addWidget(self.face_page_jump)

        self.btn_face_page_go = QPushButton("Go")
        self.btn_face_page_go.setObjectName("Ghost")
        self.btn_face_page_go.setEnabled(False)
        self.btn_face_page_go.clicked.connect(self._go_to_face_page_from_input)
        face_paging.addWidget(self.btn_face_page_go)

        face_paging.addStretch(1)
        face_paging.addWidget(QLabel("Per page:"))

        self.face_page_size_box = QComboBox()
        for value in FACE_PAGE_SIZE_OPTIONS:
            self.face_page_size_box.addItem(str(value), int(value))
        page_idx = self.face_page_size_box.findData(int(DEFAULT_FACE_PAGE_SIZE))
        if page_idx >= 0:
            self.face_page_size_box.setCurrentIndex(page_idx)
        self.face_page_size_box.currentIndexChanged.connect(self._on_face_page_size_changed)
        face_paging.addWidget(self.face_page_size_box)
        right_lay.addLayout(face_paging)

        self.faces_scroll = QScrollArea()
        self.faces_scroll.setWidgetResizable(True)
        self.faces_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.faces_host = QWidget()
        self.faces_grid = QGridLayout(self.faces_host)
        self.faces_grid.setContentsMargins(4, 4, 4, 4)
        self.faces_grid.setHorizontalSpacing(12)
        self.faces_grid.setVerticalSpacing(12)

        self.faces_scroll.setWidget(self.faces_host)
        right_lay.addWidget(self.faces_scroll, 1)

        self.splitter.addWidget(left)
        self.splitter.addWidget(right)
        self.splitter.setSizes([460, 840])

        # State
        self._all_people: list[tuple[int, str, int]] = []
        self._filtered_people: list[tuple[int, str, int]] = []
        self._selected_person_id: Optional[int] = None
        self._selected_person_name: str = ""

        self._avatar_cache: dict[int, QPixmap] = {}
        self._tile_by_id: dict[int, PersonTile] = {}
        self._face_tile_by_id: dict[int, FaceTile] = {}
        self._face_path_by_id: dict[int, str] = {}
        self._face_order: list[int] = []
        self._selected_face_ids: set[int] = set()
        self._last_selected_face_id: Optional[int] = None
        self._person_faces: list[tuple[int, str, int, int, int, int]] = []
        self._visible_person_faces: list[tuple[int, str, int, int, int, int]] = []
        self._face_page = 0
        self._face_page_size = int(DEFAULT_FACE_PAGE_SIZE)
        self._show_only_missing_metadata = False
        self._name_in_xmp_cache: dict[str, bool] = {}

        self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_unassign.clicked.connect(self._unassign_selected)
        self.btn_recompute.clicked.connect(self._recompute_selected_prototype)
        self.btn_tag_photo.clicked.connect(self._tag_selected_person_photos)
        self.btn_tag_all_photos.clicked.connect(self._tag_all_person_photos)
        self.btn_metadata.clicked.connect(self._show_selected_face_metadata)
        self.btn_remove_faces.clicked.connect(self._remove_selected_faces)

        # Keyboard navigation
        self.search_edit.installEventFilter(self)
        self.people_scroll.viewport().installEventFilter(self)
        self.faces_scroll.viewport().installEventFilter(self)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._shortcut_select_all = QShortcut(QKeySequence.StandardKey.SelectAll, self)
        self._shortcut_select_all.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_select_all.activated.connect(self._select_all_faces)

        self.refresh()

    # ---------------- Keyboard navigation ----------------

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()

            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                delta = -1 if key == Qt.Key.Key_Up else 1
                self._move_selection(delta)
                return True

            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._selected_person_id is None:
                    self._select_first_result()
                else:
                    self._ensure_selected_visible()
                return False

            if key == Qt.Key.Key_Escape:
                if self.search_edit.text():
                    self.search_edit.setText("")
                    self.search_edit.setFocus()
                    return True
                return False

        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int) -> None:
        if not self._filtered_people:
            return

        ids = [pid for pid, _, _ in self._filtered_people]

        if self._selected_person_id is None or self._selected_person_id not in ids:
            new_id = ids[0] if delta > 0 else ids[-1]
            self._select_person(new_id)
            return

        idx = ids.index(self._selected_person_id)
        new_idx = max(0, min(len(ids) - 1, idx + delta))
        if new_idx != idx:
            self._select_person(ids[new_idx])

    # ---------------- Refresh ----------------

    def refresh(self, progress_cb: Callable[[int, int, str], None] | None = None):
        self._avatar_cache.clear()
        if progress_cb is not None:
            progress_cb(0, 1, "Loading registered faces...")
        self._all_people = list_people_with_face_count()
        self._apply_filter(progress_cb=progress_cb)

        if self._selected_person_id is not None:
            if not any(pid == self._selected_person_id for pid, _, _ in self._all_people):
                self._clear_detail()
            else:
                self._load_person_faces(self._selected_person_id, progress_cb=progress_cb)
                self._update_selection_visuals()
                self._ensure_selected_visible()

    # ---------------- Search + sort ----------------

    def _apply_filter(
        self,
        _ignored: object | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ):
        q = self.search_edit.text().strip().lower()

        data = self._all_people
        if q:
            data = [(pid, name, cnt) for pid, name, cnt in data if q in name.lower()]

        if self.sort_combo.currentIndex() == 0:
            data.sort(key=lambda x: (-x[2], x[1].lower()))
        else:
            data.sort(key=lambda x: x[1].lower())

        self._filtered_people = data
        self.result_label.setText(f"{len(data)} results")

        self._render_people_list(progress_cb=progress_cb)

        if self._selected_person_id is not None:
            if not any(pid == self._selected_person_id for pid, _, _ in data):
                self._clear_detail()
            else:
                self._update_selection_visuals()
                self._ensure_selected_visible()

    def _select_first_result(self):
        if not self._filtered_people:
            return
        self._select_person(self._filtered_people[0][0])

    # ---------------- UI helpers ----------------

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _clear_faces_grid(self):
        self._face_tile_by_id.clear()
        self._face_path_by_id.clear()
        self._face_order.clear()
        self._selected_face_ids.clear()
        self._last_selected_face_id = None
        while self.faces_grid.count():
            item = self.faces_grid.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _clear_detail(self):
        self._selected_person_id = None
        self._selected_person_name = ""
        self._person_faces = []
        self._visible_person_faces = []
        self._name_in_xmp_cache.clear()
        self._face_page = 0
        self.detail_title.setText("No person selected")
        self.detail_sub.setText("")
        self.detail_proto.setText("")
        self.btn_rename.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self.btn_unassign.setEnabled(False)
        self.btn_recompute.setEnabled(False)
        self.btn_tag_photo.setEnabled(False)
        self.btn_tag_all_photos.setEnabled(False)
        self.btn_metadata.setEnabled(False)
        self.btn_remove_faces.setEnabled(False)
        self.chk_missing_only.blockSignals(True)
        self.chk_missing_only.setChecked(False)
        self.chk_missing_only.blockSignals(False)
        self.chk_missing_only.setEnabled(False)
        self._show_only_missing_metadata = False
        self._clear_faces_grid()
        self._update_face_pagination_controls()
        self._update_selection_visuals()

    def _update_selection_visuals(self):
        for pid, tile in self._tile_by_id.items():
            tile.set_selected(self._selected_person_id is not None and pid == self._selected_person_id)

    def _ensure_selected_visible(self):
        if self._selected_person_id is None:
            return
        tile = self._tile_by_id.get(self._selected_person_id)
        if tile is None:
            return
        self.people_scroll.ensureWidgetVisible(tile, 0, 20)

    def _render_people_list(self, progress_cb: Callable[[int, int, str], None] | None = None):
        self._tile_by_id.clear()
        self._clear_layout(self.people_list)

        if not self._filtered_people:
            empty = QLabel("No matches.")
            empty.setObjectName("Subtle")
            self.people_list.addWidget(empty)
            self.people_list.addStretch(1)
            if progress_cb is not None:
                progress_cb(1, 1, "No people to render.")
            return

        total = max(1, len(self._filtered_people))
        if progress_cb is not None:
            progress_cb(0, total, "Preparing people tiles...")
        for i, (pid, name, cnt) in enumerate(self._filtered_people, start=1):
            avatar_pix = self._get_avatar_pixmap(pid, size=34)
            tile = PersonTile(pid, name, cnt, avatar_pix, self._select_person)
            self._tile_by_id[pid] = tile
            tile.set_selected(self._selected_person_id is not None and pid == self._selected_person_id)
            self.people_list.addWidget(tile)
            if progress_cb is not None:
                progress_cb(i, total, f"Preparing people tiles... {i}/{total}")

        self.people_list.addStretch(1)
        self._ensure_selected_visible()

    # ---------------- Selection + details ----------------

    def _select_person(self, person_id: int):
        self._selected_person_id = int(person_id)
        self._face_page = 0
        self.chk_missing_only.blockSignals(True)
        self.chk_missing_only.setChecked(False)
        self.chk_missing_only.blockSignals(False)
        self._show_only_missing_metadata = False
        self._load_person_faces_with_progress(self._selected_person_id)
        self._update_selection_visuals()
        self._ensure_selected_visible()

    def _load_person_faces_with_progress(self, person_id: int) -> None:
        dlg = QProgressDialog("Loading person faces...", "", 0, 1, self)
        dlg.setWindowTitle("Loading Person")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        def _cb(current: int, total: int, message: str) -> None:
            total_i = max(1, int(total))
            current_i = max(0, min(int(current), total_i))
            dlg.setRange(0, total_i)
            dlg.setValue(current_i)
            dlg.setLabelText(str(message))
            QApplication.processEvents()

        try:
            self._load_person_faces(person_id, progress_cb=_cb)
            dlg.setRange(0, 1)
            dlg.setValue(1)
            dlg.setLabelText("Done.")
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

    def _open_photo_viewer(self, path: str, x: int, y: int, w: int, h: int):
        dlg = PhotoViewerDialog(
            image_path=path,
            face_rect=(x, y, w, h),
            title=f"{self._selected_person_name} – Photo",
            parent=self
        )
        dlg.exec()

    def _show_metadata_dialog(self, image_path: str) -> None:
        dlg = MetadataDialog(image_path=image_path, parent=self)
        dlg.exec()

    def _on_face_tile_selected(self, face_id: int, additive: bool, range_select: bool) -> None:
        fid = int(face_id)
        if range_select and self._last_selected_face_id is not None:
            try:
                a = self._face_order.index(int(self._last_selected_face_id))
                b = self._face_order.index(fid)
                lo, hi = (a, b) if a <= b else (b, a)
                span = set(self._face_order[lo:hi + 1])
                if additive:
                    self._selected_face_ids.update(span)
                else:
                    self._selected_face_ids = span
            except ValueError:
                self._selected_face_ids = {fid}
        elif additive:
            if fid in self._selected_face_ids:
                self._selected_face_ids.remove(fid)
            else:
                self._selected_face_ids.add(fid)
        else:
            self._selected_face_ids = {fid}
        self._last_selected_face_id = fid
        self._update_face_selection_visuals()

    def _update_face_selection_visuals(self) -> None:
        for fid, tile in self._face_tile_by_id.items():
            tile.set_selected(fid in self._selected_face_ids)
        self.btn_metadata.setEnabled(len(self._face_path_by_id) > 0)
        self.btn_remove_faces.setEnabled(len(self._selected_face_ids) > 0)
        self.btn_tag_photo.setEnabled(len(self._selected_face_ids) > 0)
        self.btn_tag_all_photos.setEnabled(len(self._visible_person_faces) > 0)

    def _show_selected_face_metadata(self) -> None:
        if not self._selected_face_ids:
            QMessageBox.information(self, "Metadata", "Please select one face first.")
            return
        if len(self._selected_face_ids) > 1:
            QMessageBox.information(self, "Metadata", "Please select only one face.")
            return
        face_id = next(iter(self._selected_face_ids))
        image_path = self._face_path_by_id.get(face_id)
        if image_path is None or not image_path.strip():
            QMessageBox.warning(self, "Metadata", "No image path found for selected face.")
            return
        self._show_metadata_dialog(image_path)

    def _select_all_faces(self) -> None:
        if not self._face_order:
            return
        self._selected_face_ids = set(self._face_order)
        self._last_selected_face_id = self._face_order[-1]
        self._update_face_selection_visuals()

    def _load_person_faces(
        self,
        person_id: int,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ):
        faces = list_faces_for_person(person_id)

        name = next((n for pid, n, _ in self._all_people if pid == person_id), "Unknown")
        count = next((c for pid, _, c in self._all_people if pid == person_id), len(faces))
        self._selected_person_name = name

        self.detail_title.setText(name)
        self.detail_sub.setText(f"{count} faces assigned")
        self.detail_proto.setText(self._prototype_status_for_person(person_id))

        self.btn_rename.setEnabled(True)
        self.btn_delete.setEnabled(True)
        self.btn_unassign.setEnabled(len(faces) > 0)
        self.btn_recompute.setEnabled(True)
        self.btn_tag_photo.setEnabled(False)
        self.btn_tag_all_photos.setEnabled(len(faces) > 0)
        self.btn_metadata.setEnabled(False)
        self.btn_remove_faces.setEnabled(False)

        self._person_faces = [
            (int(face_id), str(path), int(x), int(y), int(w), int(h))
            for face_id, path, x, y, w, h in faces
        ]
        self._name_in_xmp_cache.clear()
        self._visible_person_faces = self._build_visible_person_faces(progress_cb=progress_cb)
        total_pages = self._face_total_pages()
        if total_pages <= 0:
            self._face_page = 0
        else:
            self._face_page = max(0, min(int(self._face_page), total_pages - 1))

        self.chk_missing_only.setEnabled(len(self._person_faces) > 0)
        self._render_person_faces(progress_cb=progress_cb)
        self._update_face_pagination_controls()

    def _face_total_pages(self) -> int:
        if not self._visible_person_faces:
            return 0
        return (len(self._visible_person_faces) + self._face_page_size - 1) // self._face_page_size

    def _face_page_slice(self) -> list[tuple[int, str, int, int, int, int]]:
        if not self._visible_person_faces:
            return []
        start = int(self._face_page * self._face_page_size)
        end = min(len(self._visible_person_faces), start + self._face_page_size)
        return self._visible_person_faces[start:end]

    def _build_visible_person_faces(
        self,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> list[tuple[int, str, int, int, int, int]]:
        if not self._show_only_missing_metadata or not self._selected_person_name.strip():
            if progress_cb is not None:
                progress_cb(1, 1, "Preparing face tiles...")
            return list(self._person_faces)

        person_name = self._selected_person_name.strip()
        unique_paths = sorted({path for _fid, path, _x, _y, _w, _h in self._person_faces if path.strip()})
        total_paths = max(1, len(unique_paths))
        if progress_cb is not None:
            progress_cb(0, total_paths, "Checking metadata tags...")
        for i, path in enumerate(unique_paths, start=1):
            cached = self._name_in_xmp_cache.get(path)
            if cached is None:
                self._name_in_xmp_cache[path] = bool(has_person_name_in_xmp(path, person_name))
            if progress_cb is not None:
                progress_cb(i, total_paths, f"Checking metadata tags... {i}/{total_paths}")

        visible = [
            face for face in self._person_faces
            if not self._name_in_xmp_cache.get(face[1], False)
        ]
        return visible

    def _render_person_faces(
        self,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self._clear_faces_grid()

        faces = self._face_page_slice()
        if not faces:
            empty = QLabel("No faces assigned.")
            empty.setObjectName("Subtle")
            empty.setAlignment(ALIGN_CENTER)
            self.faces_grid.addWidget(empty, 0, 0)
            if progress_cb is not None:
                progress_cb(1, 1, "No assigned faces.")
            return

        cols = 6
        r = 0
        c = 0
        total = max(1, len(faces))
        start_index = self._face_page * self._face_page_size + 1
        end_index = start_index + len(faces) - 1
        if progress_cb is not None:
            progress_cb(0, total, f"Preparing face tiles {start_index}-{end_index}...")
        for i, (face_id, path, x, y, w, h) in enumerate(faces, start=1):
            pix = self._face_pixmap(path, x, y, w, h, size=120)
            tile = FaceTile(
                pix=pix,
                on_select=lambda additive, range_select, fid=face_id: self._on_face_tile_selected(fid, additive, range_select),
                on_click=lambda p=path, xx=x, yy=y, ww=w, hh=h: self._open_photo_viewer(p, xx, yy, ww, hh)
            )
            self._face_tile_by_id[int(face_id)] = tile
            self._face_path_by_id[int(face_id)] = str(path)
            self._face_order.append(int(face_id))
            cell = QWidget()
            cell_lay = QVBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.setSpacing(6)
            cell_lay.addWidget(tile)

            self.faces_grid.addWidget(cell, r, c)
            if progress_cb is not None:
                progress_cb(i, total, f"Preparing face tiles... {i}/{total}")
            c += 1
            if c >= cols:
                c = 0
                r += 1

        self._selected_face_ids.clear()
        self._last_selected_face_id = None
        self._update_face_selection_visuals()
        self._update_face_pagination_controls()

    def _go_prev_face_page(self) -> None:
        if self._face_page <= 0:
            return
        self._face_page -= 1
        self._render_person_faces_with_progress()
        self.faces_scroll.verticalScrollBar().setValue(0)

    def _go_next_face_page(self) -> None:
        total_pages = self._face_total_pages()
        if self._face_page + 1 >= total_pages:
            return
        self._face_page += 1
        self._render_person_faces_with_progress()
        self.faces_scroll.verticalScrollBar().setValue(0)

    def _on_face_page_size_changed(self, _index: int) -> None:
        data = self.face_page_size_box.currentData()
        if data is None:
            return
        try:
            new_size = int(data)
        except Exception:
            return
        if new_size <= 0 or new_size == int(self._face_page_size):
            return
        self._face_page_size = int(new_size)
        self._face_page = 0
        self._render_person_faces_with_progress()
        self.faces_scroll.verticalScrollBar().setValue(0)

    def _go_to_face_page_from_input(self) -> None:
        total_pages = self._face_total_pages()
        if total_pages <= 0:
            self.face_page_jump.clear()
            return

        raw = self.face_page_jump.text().strip()
        if not raw:
            self.face_page_jump.setText(str(self._face_page + 1))
            return

        try:
            page_number = int(raw)
        except Exception:
            self.face_page_jump.setText(str(self._face_page + 1))
            self.face_page_jump.selectAll()
            return

        page_number = max(1, min(page_number, total_pages))
        target_page = page_number - 1
        if target_page == int(self._face_page):
            self.face_page_jump.setText(str(page_number))
            return

        self._face_page = int(target_page)
        self._render_person_faces_with_progress()
        self.faces_scroll.verticalScrollBar().setValue(0)

    def _render_person_faces_with_progress(self) -> None:
        dlg = QProgressDialog("Preparing face tiles...", "", 0, 1, self)
        dlg.setWindowTitle("Loading Faces")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        def _cb(current: int, total: int, message: str) -> None:
            total_i = max(1, int(total))
            current_i = max(0, min(int(current), total_i))
            dlg.setRange(0, total_i)
            dlg.setValue(current_i)
            dlg.setLabelText(str(message))
            QApplication.processEvents()

        try:
            self._visible_person_faces = self._build_visible_person_faces(progress_cb=_cb)
            self._render_person_faces(progress_cb=_cb)
            dlg.setRange(0, 1)
            dlg.setValue(1)
            dlg.setLabelText("Done.")
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

    def _on_missing_filter_toggled(self, state: int) -> None:
        self._show_only_missing_metadata = bool(state != 0)
        self._face_page = 0
        if self._selected_person_id is None:
            return
        self._render_person_faces_with_progress()
        self.faces_scroll.verticalScrollBar().setValue(0)

    def _update_face_pagination_controls(self) -> None:
        total_items = len(self._visible_person_faces)
        total_pages = self._face_total_pages()
        if total_items <= 0 or total_pages <= 0:
            self.face_page_info.setText("Page 0/0")
            self.btn_faces_prev.setEnabled(False)
            self.btn_faces_next.setEnabled(False)
            self.face_page_size_box.setEnabled(False)
            self.face_page_jump.clear()
            self.face_page_jump.setEnabled(False)
            self.btn_face_page_go.setEnabled(False)
            return

        start = self._face_page * self._face_page_size + 1
        end = min(total_items, start + self._face_page_size - 1)
        self.face_page_info.setText(
            f"Page {self._face_page + 1}/{total_pages} | showing {start}-{end} of {total_items}"
        )
        self.btn_faces_prev.setEnabled(self._face_page > 0)
        self.btn_faces_next.setEnabled(self._face_page + 1 < total_pages)
        self.face_page_size_box.setEnabled(True)
        self.face_page_jump.setEnabled(True)
        self.btn_face_page_go.setEnabled(True)
        self.face_page_jump.setText(str(self._face_page + 1))

    def _prototype_status_for_person(self, person_id: int) -> str:
        with get_connection() as conn:
            cols = conn.execute("PRAGMA table_info(person_prototypes)").fetchall()
            col_names = {str(c[1]) for c in cols if len(c) > 1 and c[1] is not None}
            model_col = "model_id" if "model_id" in col_names else "model" if "model" in col_names else None

            if model_col is None:
                row = conn.execute(
                    """
                    SELECT updated_at
                    FROM person_prototypes
                    WHERE person_id=?
                    ORDER BY COALESCE(updated_at, '') DESC
                    LIMIT 1
                    """,
                    (int(person_id),),
                ).fetchone()
                if row is None:
                    return "Prototype: missing"
                updated_at = str(row["updated_at"]) if row["updated_at"] is not None else ""
                if updated_at:
                    return f"Prototype: available (model: default, updated: {updated_at})"
                return "Prototype: available (model: default)"

            row = conn.execute(
                f"""
                SELECT {model_col} AS model_name, updated_at
                FROM person_prototypes
                WHERE person_id=?
                ORDER BY COALESCE(updated_at, '') DESC
                LIMIT 1
                """,
                (int(person_id),),
            ).fetchone()
            if row is None:
                return "Prototype: missing"

            model = str(row["model_name"]) if row["model_name"] is not None else "default"
            updated_at = str(row["updated_at"]) if row["updated_at"] is not None else ""
            if updated_at:
                return f"Prototype: available (model: {model}, updated: {updated_at})"
            return f"Prototype: available (model: {model})"

    def _face_embedding_count_for_person(self, person_id: int) -> int:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM faces f
                JOIN face_embeddings fe ON fe.face_id = f.id
                WHERE f.person_id=?
                """,
                (int(person_id),),
            ).fetchone()
            if row is None or row["cnt"] is None:
                return 0
            return int(row["cnt"])

    # ---------------- Avatar + Face Pixmaps ----------------

    def _make_round_pixmap(self, pix: QPixmap, size: int) -> QPixmap:
        if pix.isNull():
            return pix

        pix = pix.scaled(size, size, ASPECT_KEEP, TRANS_SMOOTH)

        rounded = QPixmap(size, size)
        rounded.fill(Qt.GlobalColor.transparent)

        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)

        painter.drawPixmap(0, 0, pix)
        painter.end()

        return rounded

    def _get_avatar_pixmap(self, person_id: int, size: int = 34) -> Optional[QPixmap]:
        if person_id in self._avatar_cache:
            pix = self._avatar_cache[person_id]
            return pix if not pix.isNull() else None

        rep = get_first_face_for_person(person_id)
        if rep is None:
            self._avatar_cache[person_id] = QPixmap()
            return None

        path, x, y, w, h = rep
        pix = self._face_pixmap(path, x, y, w, h, size=size)
        pix = self._make_round_pixmap(pix, size)

        self._avatar_cache[person_id] = pix
        return pix if not pix.isNull() else None

    def _face_pixmap(self, path: str, x: int, y: int, w: int, h: int, size: int = 120) -> QPixmap:
        img = load_bgr_image(path)
        if img is None:
            return QPixmap()

        crop = img[y:y + h, x:x + w]
        if crop.size == 0:
            return QPixmap()

        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        hh, ww, _ = crop.shape
        bytes_per_line = 3 * ww

        qimg = QImage(crop.data, ww, hh, bytes_per_line, IMG_RGB888)
        return QPixmap.fromImage(qimg).scaled(size, size, ASPECT_KEEP, TRANS_SMOOTH)

    # ---------------- Actions ----------------

    def _rename_selected(self):
        if self._selected_person_id is None:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Rename person",
            "New name:",
            text=self._selected_person_name
        )
        if not ok:
            return

        new_name = new_name.strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
            return

        try:
            rename_person(self._selected_person_id, new_name)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not rename person:\n{e}")
            return

        self.refresh()

    def _unassign_selected(self):
        if self._selected_person_id is None:
            return

        res = QMessageBox.question(
            self,
            "Unassign all faces",
            f"Unassign all faces from '{self._selected_person_name}'?\n"
            "They will appear in Unknown again."
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            unassign_all_faces_from_person(self._selected_person_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not unassign:\n{e}")
            return

        self.refresh()

    def _unassign_single_face(self, face_id: int) -> None:
        if self._selected_person_id is None:
            return
        try:
            unassign_face(int(face_id))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not unassign face:\n{e}")
            return
        self.refresh()

    def _remove_selected_faces(self) -> None:
        if self._selected_person_id is None:
            return
        selected = sorted(self._selected_face_ids)
        if not selected:
            QMessageBox.information(self, "Remove faces", "Please select one or more faces first.")
            return

        res = QMessageBox.question(
            self,
            "Remove faces",
            f"Remove {len(selected)} selected face(s) from '{self._selected_person_name}'?",
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        person_id = int(self._selected_person_id)
        person_name = self._selected_person_name.strip()
        affected_paths = {
            self._face_path_by_id[fid]
            for fid in selected
            if fid in self._face_path_by_id and self._face_path_by_id[fid].strip()
        }

        errors: list[str] = []
        removed = 0
        for fid in selected:
            try:
                unassign_face(int(fid))
                removed += 1
            except Exception as e:
                errors.append(f"Face {fid}: {e}")

        xmp_removed = 0
        xmp_errors = 0
        if person_name:
            for photo_path in sorted(affected_paths):
                if self._person_has_faces_in_photo(person_id, photo_path):
                    continue
                result = remove_person_name_from_xmp(photo_path, person_name)
                if result == "removed":
                    xmp_removed += 1
                elif result == "error":
                    xmp_errors += 1

        if errors:
            QMessageBox.warning(
                self,
                "Remove faces",
                f"Removed {removed} face(s). {len(errors)} failed.\n\n" + "\n".join(errors[:8]),
            )
        elif xmp_removed > 0 or xmp_errors > 0:
            QMessageBox.information(
                self,
                "Remove faces",
                f"Removed {removed} face(s).\nXMP updated: {xmp_removed}\nXMP errors: {xmp_errors}",
            )
        self.refresh()

    def _person_has_faces_in_photo(self, person_id: int, photo_path: str) -> bool:
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM faces f
                JOIN photos p ON p.id = f.photo_id
                WHERE f.person_id = ? AND p.path = ?
                """,
                (int(person_id), str(photo_path)),
            ).fetchone()
            if row is None or row["cnt"] is None:
                return False
            return int(row["cnt"]) > 0

    def _delete_selected(self):
        if self._selected_person_id is None:
            return

        res = QMessageBox.warning(
            self,
            "Delete person",
            f"Delete '{self._selected_person_name}'?\n"
            "All assigned faces will be unassigned and reappear in Unknown.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if res != QMessageBox.StandardButton.Yes:
            return

        try:
            delete_person(self._selected_person_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not delete person:\n{e}")
            return

        self._clear_detail()
        self.refresh()

    def _recompute_selected_prototype(self):
        if self._selected_person_id is None:
            return

        emb_count = self._face_embedding_count_for_person(self._selected_person_id)
        if emb_count <= 0:
            QMessageBox.warning(
                self,
                "No face embeddings",
                "No face embeddings exist for this person yet.\n"
                "Import/build face embeddings first, then rebuild prototype.",
            )
            return

        try:
            recompute_person_prototype(self._selected_person_id)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not recompute prototype:\n{e}")
            return

        QMessageBox.information(self, "Done", "Prototype updated.")
        self.refresh()

    def _tag_selected_person_photos(self) -> None:
        if self._selected_person_id is None:
            return
        person_name = self._selected_person_name.strip()
        if not person_name:
            QMessageBox.warning(self, "Missing person name", "Selected person has no valid name.")
            return

        selected = sorted(self._selected_face_ids)
        if not selected:
            QMessageBox.information(self, "Tag Photo", "Please select one or more faces first.")
            return

        unique_paths = sorted(
            {
                self._face_path_by_id[fid]
                for fid in selected
                if fid in self._face_path_by_id and self._face_path_by_id[fid].strip()
            }
        )
        if not unique_paths:
            QMessageBox.information(self, "No photos", "No photos found for this person.")
            return

        self._tag_person_photos(unique_paths, dialog_title="Tag Photo")

    def _tag_all_person_photos(self) -> None:
        if self._selected_person_id is None:
            return
        person_name = self._selected_person_name.strip()
        if not person_name:
            QMessageBox.warning(self, "Missing person name", "Selected person has no valid name.")
            return

        source_faces = self._visible_person_faces if self._show_only_missing_metadata else self._person_faces
        unique_paths = sorted({str(path) for _fid, path, _x, _y, _w, _h in source_faces if str(path).strip()})
        if not unique_paths:
            QMessageBox.information(self, "No photos", "No photos found for this person.")
            return

        self._tag_person_photos(unique_paths, dialog_title="Tag all Photos")

    def _tag_person_photos(self, unique_paths: list[str], dialog_title: str) -> None:
        person_name = self._selected_person_name.strip()
        if not person_name:
            QMessageBox.warning(self, "Missing person name", "Selected person has no valid name.")
            return

        dlg = QProgressDialog("Writing XMP tags...", "", 0, len(unique_paths), self)
        dlg.setWindowTitle(str(dialog_title))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.show()
        QApplication.processEvents()

        tagged = 0
        already = 0
        skipped_unsupported = 0
        skipped_missing = 0
        errors = 0

        try:
            total = len(unique_paths)
            for i, photo_path in enumerate(unique_paths, start=1):
                dlg.setValue(i - 1)
                dlg.setLabelText(f"Tagging photo {i}/{total}...")
                QApplication.processEvents()

                result = ensure_person_name_in_xmp(photo_path, person_name)
                if result == "tagged":
                    tagged += 1
                elif result == "already_present":
                    already += 1
                elif result == "skipped_unsupported":
                    skipped_unsupported += 1
                elif result == "skipped_missing":
                    skipped_missing += 1
                else:
                    errors += 1

            dlg.setValue(total)
            dlg.setLabelText("Done.")
            QApplication.processEvents()
        finally:
            dlg.close()
            dlg.deleteLater()

        QMessageBox.information(
            self,
            str(dialog_title),
            "XMP tagging completed.\n\n"
            f"Tagged: {tagged}\n"
            f"Already present: {already}\n"
            f"Unsupported format: {skipped_unsupported}\n"
            f"Missing files: {skipped_missing}\n"
            f"Errors: {errors}",
        )
