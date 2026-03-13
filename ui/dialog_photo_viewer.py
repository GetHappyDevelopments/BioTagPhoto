from __future__ import annotations

from typing import Optional, Tuple

import cv2
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QMessageBox
)

ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
ASPECT_KEEP = Qt.AspectRatioMode.KeepAspectRatio
TRANS_SMOOTH = Qt.TransformationMode.SmoothTransformation
IMG_RGB888 = QImage.Format.Format_RGB888


class PhotoViewerDialog(QDialog):
    """
    Offline photo viewer:
    - shows original image
    - draws one face rectangle (x,y,w,h)
    - Fit / 100% toggle
    - Ctrl+Wheel zoom (anchored to mouse position; disables Fit)
    - Drag-to-pan in zoom mode
    - Double click: Fit <-> 100%
    """
    def __init__(
        self,
        image_path: str,
        face_rect: Optional[Tuple[int, int, int, int]] = None,
        title: str = "Photo",
        parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1100, 800)

        self._image_path = image_path
        self._face_rect = face_rect

        self._fit = True
        self._zoom = 1.0
        self._zoom_min = 0.10
        self._zoom_max = 8.00
        self._zoom_step = 1.15  # per wheel notch

        # Pan state
        self._panning = False
        self._pan_start_pos: Optional[QPoint] = None
        self._pan_start_h: int = 0
        self._pan_start_v: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Toolbar
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.btn_fit = QPushButton("Fit")
        self.btn_fit.setCheckable(True)
        self.btn_fit.setChecked(True)

        self.btn_100 = QPushButton("100%")
        self.btn_close = QPushButton("Close")

        bar.addWidget(self.btn_fit)
        bar.addWidget(self.btn_100)
        bar.addStretch(1)
        bar.addWidget(self.btn_close)
        root.addLayout(bar)

        # Image area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.lbl = QLabel()
        self.lbl.setAlignment(ALIGN_CENTER)
        self.scroll_area.setWidget(self.lbl)
        root.addWidget(self.scroll_area, 1)

        # We want wheel/mouse events from the viewport
        vp = self.scroll_area.viewport()
        vp.setMouseTracking(True)
        vp.installEventFilter(self)

        # Wire
        self.btn_fit.clicked.connect(self._set_fit)
        self.btn_100.clicked.connect(self._set_100)
        self.btn_close.clicked.connect(self.close)

        # Load
        self._base_pix = self._load_pixmap_with_overlay()
        if self._base_pix.isNull():
            QMessageBox.critical(self, "Error", f"Could not load:\n{image_path}")
            return

        self._render()

    # ---------------- Image load ----------------

    def _load_pixmap_with_overlay(self) -> QPixmap:
        img = cv2.imread(self._image_path)
        if img is None:
            return QPixmap()

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w, _ = img.shape
        qimg = QImage(img.data, w, h, 3 * w, IMG_RGB888)
        pix = QPixmap.fromImage(qimg)

        if self._face_rect is None:
            return pix

        x, y, fw, fh = self._face_rect

        out = QPixmap(pix)
        p = QPainter(out)
        pen = QPen(Qt.GlobalColor.cyan)
        pen.setWidth(4)
        p.setPen(pen)
        p.drawRect(x, y, fw, fh)
        p.end()

        return out

    # ---------------- Rendering ----------------

    def _render(self):
        if self._base_pix.isNull():
            return

        if self._fit:
            vp_size = self.scroll_area.viewport().size()
            pix = self._base_pix.scaled(vp_size, ASPECT_KEEP, TRANS_SMOOTH)
            self.lbl.setPixmap(pix)
            return

        w = max(1, int(self._base_pix.width() * self._zoom))
        h = max(1, int(self._base_pix.height() * self._zoom))
        pix = self._base_pix.scaled(
            w, h,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            TRANS_SMOOTH
        )
        self.lbl.setPixmap(pix)

    def _set_fit(self):
        self._fit = True
        self.btn_fit.setChecked(True)
        self._zoom = 1.0
        self._stop_pan()
        self._render()

    def _set_100(self):
        self._fit = False
        self.btn_fit.setChecked(False)
        self._zoom = 1.0
        self._render()

    # ---------------- Mapping for double click Fit->100% ----------------

    def _fit_scaled_size_and_offset(self) -> tuple[int, int, int, int, float]:
        """
        Returns: fit_w, fit_h, off_x, off_y, scale
        scale = fit_w / base_w
        """
        vp = self.scroll_area.viewport().size()
        base_w = max(1, self._base_pix.width())
        base_h = max(1, self._base_pix.height())

        # compute fit size (KeepAspectRatio)
        scale = min(vp.width() / base_w, vp.height() / base_h)
        fit_w = int(round(base_w * scale))
        fit_h = int(round(base_h * scale))

        off_x = max(0, (vp.width() - fit_w) // 2)
        off_y = max(0, (vp.height() - fit_h) // 2)
        return fit_w, fit_h, off_x, off_y, scale

    def _map_fit_viewport_pos_to_image(self, pos_vp: QPoint) -> tuple[float, float]:
        """
        Map viewport position to image coordinates while in Fit mode.
        """
        _, _, off_x, off_y, scale = self._fit_scaled_size_and_offset()
        x = (pos_vp.x() - off_x) / max(scale, 1e-9)
        y = (pos_vp.y() - off_y) / max(scale, 1e-9)

        # clamp to image bounds
        x = max(0.0, min(float(self._base_pix.width()), x))
        y = max(0.0, min(float(self._base_pix.height()), y))
        return x, y

    def _scroll_to_keep_image_point_under_cursor(self, img_x: float, img_y: float, pos_vp: QPoint):
        """
        In zoom mode, set scrollbars so that (img_x,img_y) is under pos_vp.
        """
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()

        new_content_x = img_x * self._zoom
        new_content_y = img_y * self._zoom

        new_h = int(round(new_content_x - pos_vp.x()))
        new_v = int(round(new_content_y - pos_vp.y()))

        new_h = max(hbar.minimum(), min(hbar.maximum(), new_h))
        new_v = max(vbar.minimum(), min(vbar.maximum(), new_v))

        hbar.setValue(new_h)
        vbar.setValue(new_v)

    # ---------------- Zoom helpers ----------------

    def _apply_zoom_clamped(self, new_zoom: float) -> float:
        if new_zoom < self._zoom_min:
            new_zoom = self._zoom_min
        if new_zoom > self._zoom_max:
            new_zoom = self._zoom_max
        return new_zoom

    def _zoom_at(self, mouse_pos_in_viewport: QPoint, factor: float) -> None:
        """
        Zoom in/out keeping the point under the mouse stable.
        """
        # Switch to zoom mode if currently Fit
        if self._fit:
            self._fit = False
            self.btn_fit.setChecked(False)
            self._zoom = 1.0
            self._render()

        old_zoom = self._zoom
        new_zoom = self._apply_zoom_clamped(old_zoom * factor)
        if abs(new_zoom - old_zoom) < 1e-9:
            return

        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()

        content_x = hbar.value() + mouse_pos_in_viewport.x()
        content_y = vbar.value() + mouse_pos_in_viewport.y()

        img_x = content_x / old_zoom
        img_y = content_y / old_zoom

        self._zoom = new_zoom
        self._render()

        self._scroll_to_keep_image_point_under_cursor(img_x, img_y, mouse_pos_in_viewport)

    # ---------------- Pan helpers ----------------

    def _start_pan(self, pos: QPoint):
        if self._fit:
            return
        self._panning = True
        self._pan_start_pos = QPoint(pos)
        self._pan_start_h = self.scroll_area.horizontalScrollBar().value()
        self._pan_start_v = self.scroll_area.verticalScrollBar().value()
        self.scroll_area.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def _stop_pan(self):
        self._panning = False
        self._pan_start_pos = None
        self.scroll_area.viewport().setCursor(Qt.CursorShape.ArrowCursor)

    def _do_pan(self, pos: QPoint):
        if not self._panning or self._pan_start_pos is None:
            return
        delta = pos - self._pan_start_pos
        hbar = self.scroll_area.horizontalScrollBar()
        vbar = self.scroll_area.verticalScrollBar()
        hbar.setValue(self._pan_start_h - delta.x())
        vbar.setValue(self._pan_start_v - delta.y())

    # ---------------- Double click toggle ----------------

    def _toggle_fit_100(self, pos_vp: QPoint):
        if self._fit:
            # Fit -> 100%: map click to image coordinate and keep it under cursor
            img_x, img_y = self._map_fit_viewport_pos_to_image(pos_vp)
            self._set_100()
            self._scroll_to_keep_image_point_under_cursor(img_x, img_y, pos_vp)
        else:
            # zoom mode -> Fit
            self._set_fit()

    # ---------------- EventFilter ----------------

    def eventFilter(self, obj, event):
        et = event.type()

        # Double click: Fit <-> 100%
        if et == event.Type.MouseButtonDblClick:
            if event.button() == Qt.MouseButton.LeftButton:
                self._toggle_fit_100(event.position().toPoint())
                return True

        # Ctrl+Wheel zoom (anchored to mouse)
        if et == event.Type.Wheel:
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier) == Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    factor = self._zoom_step
                elif delta < 0:
                    factor = 1.0 / self._zoom_step
                else:
                    return True

                self._zoom_at(event.position().toPoint(), factor)
                return True

        # Pan (left mouse drag)
        if et == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                self._start_pan(event.position().toPoint())
                return True

        if et == event.Type.MouseMove:
            if self._panning:
                self._do_pan(event.position().toPoint())
                return True

        if et == event.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and self._panning:
                self._stop_pan()
                return True

        return super().eventFilter(obj, event)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fit:
            self._render()
