from typing import Callable

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGridLayout, QFrame
from PySide6.QtCore import Qt

from db import get_connection

CARD_QSS = """
QFrame#Card {
  border-radius: 12px;
  padding: 10px;
}
QLabel#CardNum { font-size: 28px; font-weight: 700; }
QLabel#CardLbl { font-size: 12px; color: #333; }
"""

ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
ALIGN_HCENTER = Qt.AlignmentFlag.AlignHCenter


def _card(bg_hex: str, number: str, label: str) -> QFrame:
    f = QFrame()
    f.setObjectName("Card")
    f.setStyleSheet(CARD_QSS + f"QFrame#Card{{ background: {bg_hex}; }}")

    lay = QVBoxLayout(f)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(6)

    n = QLabel(number)
    n.setObjectName("CardNum")
    n.setAlignment(ALIGN_CENTER)

    t = QLabel(label)
    t.setObjectName("CardLbl")
    t.setAlignment(ALIGN_CENTER)

    lay.addStretch(1)
    lay.addWidget(n)
    lay.addWidget(t)
    lay.addStretch(1)
    return f


class StatsPage(QWidget):
    def __init__(self):
        super().__init__()

        # Do not use self.layout as attribute name (QWidget has layout() method)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 30, 10, 10)
        self.main_layout.setSpacing(20)

        title = QLabel("Tagging Statistics")
        title.setAlignment(ALIGN_HCENTER)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        self.main_layout.addWidget(title)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)

        self.c_total_photos = _card("#cfeefc", "0", "Total Photos")
        self.c_people = _card("#d7f7d8", "0", "People")
        self.c_total_faces = _card("#ffd6c9", "0", "Total Faces")
        self.c_tagged = _card("#f6b1b1", "0", "Tagged Faces")
        self.c_sugg = _card("#ffd48a", "0", "Suggestions")
        self.c_unknown = _card("#f6c0d3", "0", "Unknown")
        self.c_excluded = _card("#e2e2e2", "0", "Excluded Images")

        self.grid.addWidget(self.c_total_photos, 0, 0)
        self.grid.addWidget(self.c_people, 0, 1)
        self.grid.addWidget(self.c_total_faces, 0, 2)
        self.grid.addWidget(self.c_tagged, 1, 0)
        self.grid.addWidget(self.c_sugg, 1, 1)
        self.grid.addWidget(self.c_unknown, 1, 2)
        self.grid.addWidget(self.c_excluded, 2, 1)

        wrap = QWidget()
        wrap.setLayout(self.grid)
        wrap.setMaximumWidth(780)
        wrap.setStyleSheet("background: transparent;")
        self.main_layout.addWidget(wrap, alignment=ALIGN_HCENTER)

        bar = QFrame()
        bar.setStyleSheet("background:#d9a7e8; border-radius: 14px; min-height: 54px;")

        bar_lay = QVBoxLayout(bar)
        bar_lbl = QLabel("Top 10 People by Face Count")
        bar_lbl.setAlignment(ALIGN_CENTER)
        bar_lbl.setStyleSheet("font-size: 16px; font-weight: 700;")
        bar_lay.addWidget(bar_lbl)

        bar.setMaximumWidth(780)
        self.main_layout.addWidget(bar, alignment=ALIGN_HCENTER)

        self.main_layout.addStretch(1)

    def _set_card_value(self, card: QFrame, value: int) -> None:
        num = card.findChild(QLabel, "CardNum")
        if num:
            num.setText(str(value))

    def _resolve_people_table(self, cur) -> str:
        row = cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name IN ('people', 'persons')
            ORDER BY CASE name WHEN 'people' THEN 0 ELSE 1 END
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return "people"
        return str(row[0])

    def refresh(self, progress_cb: Callable[[int, int, str], None] | None = None) -> None:
        if progress_cb is not None:
            progress_cb(0, 1, "Loading statistics...")
        with get_connection() as con:
            cur = con.cursor()

            cur.execute("SELECT COUNT(*) FROM photos")
            total_photos = int(cur.fetchone()[0])

            people_table = self._resolve_people_table(cur)
            cur.execute(f"SELECT COUNT(*) FROM {people_table}")
            people = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM faces")
            total_faces = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM faces WHERE person_id IS NOT NULL")
            tagged = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM faces WHERE person_id IS NULL")
            unknown = int(cur.fetchone()[0])

            suggestions = 0
            cur.execute("SELECT COUNT(*) FROM excluded_images")
            excluded = int(cur.fetchone()[0])

        self._set_card_value(self.c_total_photos, total_photos)
        self._set_card_value(self.c_people, people)
        self._set_card_value(self.c_total_faces, total_faces)
        self._set_card_value(self.c_tagged, tagged)
        self._set_card_value(self.c_sugg, suggestions)
        self._set_card_value(self.c_unknown, unknown)
        self._set_card_value(self.c_excluded, excluded)
        if progress_cb is not None:
            progress_cb(1, 1, "Statistics ready.")
