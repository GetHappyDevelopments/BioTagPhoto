from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QTabWidget,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
)

try:
    from PIL import ExifTags, Image, IptcImagePlugin  # type: ignore
except Exception:
    ExifTags = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    IptcImagePlugin = None  # type: ignore[assignment]


def _safe_text(value: Any) -> str:
    if isinstance(value, bytes):
        for enc in ("utf-8", "latin-1"):
            try:
                return value.decode(enc, errors="replace")
            except Exception:
                continue
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_safe_text(v) for v in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(f"{_safe_text(k)}={_safe_text(v)}" for k, v in value.items())
        return "{" + items + "}"
    return str(value)


def _extract_exif(path: Path) -> list[tuple[str, str]]:
    if Image is None:
        return [("Info", "Pillow not installed, EXIF unavailable.")]
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return [("Info", "No EXIF data found.")]
            rows: list[tuple[str, str]] = []
            tag_names = getattr(ExifTags, "TAGS", {}) if ExifTags is not None else {}
            gps_tag_names = getattr(ExifTags, "GPSTAGS", {}) if ExifTags is not None else {}
            for tag_id, value in exif.items():
                key = str(tag_names.get(tag_id, tag_id))
                if key == "GPSInfo" and isinstance(value, dict):
                    gps_val: dict[str, Any] = {}
                    for gps_id, gps_data in value.items():
                        gps_key = str(gps_tag_names.get(gps_id, gps_id))
                        gps_val[gps_key] = gps_data
                    rows.append((key, _safe_text(gps_val)))
                else:
                    rows.append((key, _safe_text(value)))
            rows.sort(key=lambda r: r[0].lower())
            return rows
    except Exception as exc:
        return [("Error", f"Failed to read EXIF: {exc}")]


def _extract_iptc(path: Path) -> list[tuple[str, str]]:
    if Image is None or IptcImagePlugin is None:
        return [("Info", "Pillow IPTC plugin not available.")]
    try:
        with Image.open(path) as img:
            data = IptcImagePlugin.getiptcinfo(img)
            if not data:
                return [("Info", "No IPTC data found.")]
            rows: list[tuple[str, str]] = []
            for key, value in data.items():
                if isinstance(key, tuple) and len(key) == 2:
                    k = f"{key[0]}:{key[1]}"
                else:
                    k = _safe_text(key)
                rows.append((k, _safe_text(value)))
            rows.sort(key=lambda r: r[0].lower())
            return rows
    except Exception as exc:
        return [("Error", f"Failed to read IPTC: {exc}")]


def _extract_xmp(path: Path) -> list[tuple[str, str]]:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        return [("Error", f"Failed to read file: {exc}")]

    match = re.search(br"<x:xmpmeta[\s\S]*?</x:xmpmeta>", raw)
    if not match:
        return [("Info", "No XMP packet found.")]

    packet = match.group(0)
    xml_text = packet.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        preview = xml_text[:2000]
        return [("Error", f"Failed to parse XMP XML: {exc}"), ("Raw", preview)]

    rows: list[tuple[str, str]] = []
    for elem in root.iter():
        tag = elem.tag
        if "}" in tag:
            tag = tag.split("}", 1)[1]
        text = (elem.text or "").strip()
        if text:
            rows.append((tag, text))
        for attr_key, attr_val in elem.attrib.items():
            a = attr_key.split("}", 1)[1] if "}" in attr_key else attr_key
            rows.append((f"{tag}@{a}", attr_val))

    if not rows:
        return [("Info", "XMP packet found, but no readable key/value entries.")]
    rows.sort(key=lambda r: r[0].lower())
    return rows


def _format_rows(rows: list[tuple[str, str]]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in rows)


class MetadataDialog(QDialog):
    def __init__(self, image_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Image Metadata")
        self.setModal(True)
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        root.addWidget(QLabel(f"File: {image_path}"))

        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        p = Path(image_path)
        exif_rows = _extract_exif(p)
        iptc_rows = _extract_iptc(p)
        xmp_rows = _extract_xmp(p)

        tabs.addTab(self._build_text_tab(_format_rows(exif_rows)), "EXIF")
        tabs.addTab(self._build_text_tab(_format_rows(iptc_rows)), "IPTC")
        tabs.addTab(self._build_text_tab(_format_rows(xmp_rows)), "XMP")

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _build_text_tab(self, text: str):
        host = QTextEdit()
        host.setReadOnly(True)
        host.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        host.setText(text if text.strip() else "No data available.")
        host.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return host

