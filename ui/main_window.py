from __future__ import annotations

from datetime import datetime
from html import escape
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
from typing import Callable
import zipfile

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app_info import APP_ADDRESS, APP_AUTHOR, APP_COPYRIGHT, APP_EMAIL, APP_LICENSE, APP_NAME, APP_VERSION
from db import (
    DB_PATH,
    add_excluded_face,
    add_excluded_image,
    add_source_folder,
    init_db,
    list_excluded_faces,
    list_excluded_images,
    list_source_folders,
    remove_excluded_face,
    remove_excluded_image,
    remove_source_folder,
    reset_database_to_factory,
)
from model_config import (
    describe_model_root,
    ensure_saved_model_root,
    get_saved_model_root,
    is_valid_model_root,
    normalize_model_root_selection,
    set_saved_model_root,
)
from embedding_model_adapter import StubEmbeddingModel
from ingest import count_image_files, ingest_folder
from .dialog_settings import SettingsDialog
from .dialog_document import DocumentDialog
from .dialog_license import LicenseDialog
from .jobs_rebuild import RebuildEmbeddingsHandle, create_rebuild_face_embeddings_runner
from .pages_people import PeoplePage
from .pages_stats import StatsPage
from .pages_suggested import SuggestedPage
from .pages_unknown import UnknownPage


APP_QSS = """
QMainWindow { background: #ffffff; }

#TopBar { background: #ffffff; border-bottom: 1px solid #e6e6e6; }

QPushButton#TopTab {
  min-height: 44px;
  padding: 8px 18px;
  border-radius: 10px;
  border: 1px solid #dcdcdc;
  background: #ffffff;
  font-size: 14px;
}

QPushButton#TopTab:checked {
  background: #0aa4e8;
  color: white;
  border: 1px solid #0aa4e8;
}

QPushButton#TopTab:hover:!checked {
  background: #f6f6f6;
}

QPushButton#ImportBtn {
  min-height: 44px;
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid #dcdcdc;
  background: #ffffff;
}

QPushButton#ImportBtn:hover {
  background: #f6f6f6;
}
"""


class ImportWorker(QObject):
    finished = Signal()
    error = Signal(str)
    progress = Signal(int, int)
    status = Signal(str)

    def __init__(self, folders: tuple[str, ...]):
        super().__init__()
        self._folders = tuple(str(x) for x in folders)
        self._folder_totals = [int(count_image_files(folder)) for folder in self._folders]
        self._grand_total = int(sum(self._folder_totals))

    def _format_eta(self, eta_seconds: float | None) -> str:
        if eta_seconds is None:
            return "--:--"
        seconds = max(0, int(round(float(eta_seconds))))
        minutes, sec = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _status_html(
        self,
        current_index: int,
        current_done: int,
        current_total: int,
        processed_global: int,
        total_global: int,
        eta_seconds: float | None,
    ) -> str:
        lines: list[str] = [
            (
                "<b>Overall:</b> "
                f"{int(processed_global)}/{int(total_global)}"
                f"&nbsp;&nbsp;<b>ETA:</b> {self._format_eta(eta_seconds)}"
            ),
            "",
        ]
        for idx, folder in enumerate(self._folders):
            folder_name = escape(str(folder))
            if idx < current_index:
                lines.append(f"<span style='color:#2e7d32;'>?</span> {folder_name}")
            elif idx == current_index:
                if current_total == 0 or current_done >= current_total:
                    lines.append(f"<span style='color:#2e7d32;'>?</span> {folder_name}")
                else:
                    lines.append(
                        f"<span style='color:#1565c0;'>?</span> Analyzing: {folder_name} "
                        f"({current_done}/{current_total})"
                    )
            elif idx == current_index + 1:
                lines.append(f"<span style='color:#555;'>Next:</span> {folder_name}")
            else:
                lines.append(f"<span style='color:#888;'>•</span> {folder_name}")
        return "<br/>".join(lines)

    def run(self) -> None:
        try:
            done_global = 0
            grand_total = int(self._grand_total)
            started_at = time.perf_counter()
            if grand_total > 0:
                self.progress.emit(0, grand_total)

            for idx, folder in enumerate(self._folders):
                folder_total = int(self._folder_totals[idx])

                def _progress(current: int, total: int) -> None:
                    current_i = int(current)
                    total_i = int(total)
                    processed_global = int(done_global + current_i)
                    if grand_total > 0:
                        self.progress.emit(processed_global, grand_total)
                    eta_seconds: float | None = None
                    if grand_total > 0 and processed_global > 0:
                        elapsed = max(0.001, time.perf_counter() - started_at)
                        rate = float(processed_global) / elapsed
                        if rate > 0.0:
                            remaining = max(0, grand_total - processed_global)
                            eta_seconds = float(remaining) / rate
                    self.status.emit(
                        self._status_html(
                            idx,
                            current_i,
                            total_i,
                            processed_global,
                            grand_total,
                            eta_seconds,
                        )
                    )

                self.status.emit(
                    self._status_html(
                        idx,
                        0,
                        folder_total,
                        done_global,
                        grand_total,
                        None,
                    )
                )
                ingest_folder(str(folder), progress_callback=_progress)
                done_global += folder_total

                if grand_total > 0:
                    self.progress.emit(done_global, grand_total)
                self.status.emit(
                    self._status_html(
                        idx,
                        folder_total,
                        folder_total,
                        done_global,
                        grand_total,
                        0.0 if grand_total > 0 and done_global >= grand_total else None,
                    )
                )
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, startup_progress_cb: Callable[[int, int, str], None] | None = None):
        super().__init__()
        self._startup_progress_cb = startup_progress_cb
        self._startup_progress_total = 100

        self._emit_startup_progress(5, "Initializing application...")

        self.setWindowTitle("BioTagPhoto")
        self.resize(1300, 850)

        self._emit_startup_progress(15, "Initializing database...")
        init_db()
        self._emit_startup_progress(25, "Preparing layout...")
        self.setStyleSheet(APP_QSS)

        root = QWidget()
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)

        top = QWidget()
        top.setObjectName("TopBar")

        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(6, 6, 6, 6)
        top_layout.setSpacing(10)

        self.btn_people = self._mk_tab("People")
        self.btn_suggested = self._mk_tab("Suggested")
        self.btn_unknown = self._mk_tab("Unknown")
        self.btn_stats = self._mk_tab("Statistics")

        for b in (self.btn_people, self.btn_suggested, self.btn_unknown, self.btn_stats):
            top_layout.addWidget(b)

        top_layout.addStretch(1)

        self.btn_import = QPushButton("Analyze Images")
        self.btn_import.setObjectName("ImportBtn")
        self.btn_import.clicked.connect(self.analyze_images)
        top_layout.addWidget(self.btn_import)

        root_layout.addWidget(top)

        self.stack = QStackedWidget()
        root_layout.addWidget(self.stack, 1)

        self._emit_startup_progress(35, "Creating pages...")
        self.page_people = PeoplePage()
        self.page_suggested = SuggestedPage()
        self.page_unknown = UnknownPage()
        self.page_stats = StatsPage()

        self.stack.addWidget(self.page_people)     # index 0
        self.stack.addWidget(self.page_suggested)  # index 1
        self.stack.addWidget(self.page_unknown)    # index 2
        self.stack.addWidget(self.page_stats)      # index 3

        self.btn_people.clicked.connect(lambda: self._activate(self.btn_people, 0))
        self.btn_suggested.clicked.connect(lambda: self._activate(self.btn_suggested, 1))
        self.btn_unknown.clicked.connect(lambda: self._activate(self.btn_unknown, 2))
        self.btn_stats.clicked.connect(lambda: self._activate(self.btn_stats, 3))

        self._rebuild_handle: RebuildEmbeddingsHandle | None = None
        self._rebuild_progress: QProgressDialog | None = None
        self._rebuild_error: str | None = None

        self._import_thread: QThread | None = None
        self._import_worker: ImportWorker | None = None
        self._import_progress: QProgressDialog | None = None
        self._tile_prepare_progress: QProgressDialog | None = None
        self._import_error: str | None = None

        self._page_dirty: dict[int, bool] = {0: True, 1: True, 2: True, 3: True}

        self._emit_startup_progress(45, "Building menu...")
        self._build_menu()
        self._startup_refresh_page(0, 45, 30, "Loading registered faces...")
        self._startup_refresh_page(2, 75, 20, "Loading unknown faces...")
        self._page_dirty[0] = False
        self._page_dirty[2] = False

        self._emit_startup_progress(95, "Loading initial page...")
        self._activate(self.btn_people, 0)
        self._emit_startup_progress(100, "Startup complete.")

    def _emit_startup_progress(self, current: int, message: str) -> None:
        cb = self._startup_progress_cb
        if cb is None:
            return
        try:
            cb(int(current), int(self._startup_progress_total), str(message))
        except Exception:
            pass

    def _startup_refresh_page(self, index: int, start: int, span: int, label: str) -> None:
        start_i = int(start)
        span_i = max(1, int(span))
        self._emit_startup_progress(start_i, label)

        def _cb(current: int, total: int, message: str) -> None:
            total_i = max(1, int(total))
            current_i = max(0, min(int(current), total_i))
            frac = float(current_i) / float(total_i)
            absolute = start_i + int(round(frac * span_i))
            self._emit_startup_progress(absolute, str(message))

        try:
            self._refresh_page(int(index), progress_cb=_cb)
        except Exception:
            self._emit_startup_progress(start_i + span_i, f"{label} skipped.")

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")
        edit_menu = menu_bar.addMenu("Edit")
        help_menu = menu_bar.addMenu("Help")

        self.action_export_backup = QAction("Export Backup...", self)
        self.action_export_backup.triggered.connect(self._export_backup)
        file_menu.addAction(self.action_export_backup)

        self.action_import_backup = QAction("Import Backup...", self)
        self.action_import_backup.triggered.connect(self._import_backup)
        file_menu.addAction(self.action_import_backup)

        file_menu.addSeparator()

        action_exit = QAction("Exit", self)
        action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        action_exit.triggered.connect(self.close)
        file_menu.addAction(action_exit)

        action_settings = QAction("Settings", self)
        action_settings.triggered.connect(self._open_settings_dialog)
        edit_menu.addAction(action_settings)

        self.action_rebuild_embeddings = QAction("Rebuild Embeddings...", self)
        self.action_rebuild_embeddings.triggered.connect(self.rebuild_embeddings)
        edit_menu.addAction(self.action_rebuild_embeddings)

        self.action_about = QAction("About", self)
        self.action_about.triggered.connect(self._show_about_dialog)
        help_menu.addAction(self.action_about)

        self.action_licenses = QAction("Licenses", self)
        self.action_licenses.triggered.connect(self._show_license_dialog)
        help_menu.addAction(self.action_licenses)

        self.action_privacy = QAction("Privacy", self)
        self.action_privacy.triggered.connect(self._show_privacy_dialog)
        help_menu.addAction(self.action_privacy)

        self.action_legal = QAction("Legal", self)
        self.action_legal.triggered.connect(self._show_legal_dialog)
        help_menu.addAction(self.action_legal)

    def _show_about_dialog(self) -> None:
        text = (
            f"{APP_NAME}\n"
            f"Version: {APP_VERSION}\n"
            f"Author: {APP_AUTHOR}\n"
            f"Address: {APP_ADDRESS}\n"
            f"E-mail: {APP_EMAIL}\n"
            f"{APP_COPYRIGHT}\n"
            f"License: {APP_LICENSE}"
        )
        QMessageBox.information(self, "About", text)

    def _show_license_dialog(self) -> None:
        dlg = LicenseDialog(self)
        dlg.exec()

    def _show_privacy_dialog(self) -> None:
        dlg = DocumentDialog("Privacy", "PRIVACY.md", "Privacy and data processing notice", self)
        dlg.exec()

    def _show_legal_dialog(self) -> None:
        dlg = DocumentDialog("Legal", "LEGAL.md", "Legal and usage notice", self)
        dlg.exec()

    def _is_background_job_running(self) -> bool:
        return (self._import_thread is not None and self._import_thread.isRunning()) or (
            self._rebuild_handle is not None and self._rebuild_handle.runner.is_running()
        )

    def _default_backup_name(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"BioTagPhoto_Backup_{stamp}.btp"

    def _sha256_bytes(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _export_backup(self) -> None:
        if self._is_background_job_running():
            QMessageBox.warning(self, "Backup", "Please wait until running jobs are finished.")
            return

        target_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Backup",
            self._default_backup_name(),
            "BioTagPhoto Backup (*.btp)",
        )
        if not target_path:
            return
        if not str(target_path).lower().endswith(".btp"):
            target_path = f"{target_path}.btp"

        tmp_db_path: Path | None = None
        try:
            fd, raw_tmp_path = tempfile.mkstemp(prefix="biotagphoto_export_", suffix=".db")
            try:
                os.close(fd)
            except Exception:
                pass
            tmp_db_path = Path(raw_tmp_path)

            with sqlite3.connect(DB_PATH) as src, sqlite3.connect(tmp_db_path) as dst:
                src.backup(dst)
            db_name = "tagthatphoto.db"
            db_bytes = tmp_db_path.read_bytes()
            db_size = int(len(db_bytes))
            db_sha256 = self._sha256_bytes(db_bytes)
            manifest = {
                "backup_format_version": 1,
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                "created_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "db_filename": db_name,
                "db_size_bytes": db_size,
                "db_sha256": db_sha256,
            }
            with zipfile.ZipFile(target_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=True))
                zf.writestr(db_name, db_bytes)
        except Exception as exc:
            QMessageBox.critical(self, "Backup failed", f"Could not export backup:\n{exc}")
            return
        finally:
            if tmp_db_path is not None:
                try:
                    tmp_db_path.unlink(missing_ok=True)
                except Exception:
                    pass

        QMessageBox.information(self, "Backup exported", f"Backup created:\n{target_path}")

    def _import_backup(self) -> None:
        if self._is_background_job_running():
            QMessageBox.warning(self, "Backup", "Please wait until running jobs are finished.")
            return

        src_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Backup",
            "",
            "BioTagPhoto Backup (*.btp)",
        )
        if not src_path:
            return

        confirm = QMessageBox.warning(
            self,
            "Import Backup",
            "Importing a backup will replace the current database.\n"
            "This cannot be undone.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        tmp_db_path: Path | None = None
        try:
            fd, raw_tmp_path = tempfile.mkstemp(prefix="biotagphoto_import_", suffix=".db")
            try:
                # Close OS handle immediately so sqlite/open can use the file on Windows.
                os.close(fd)
            except Exception:
                pass
            tmp_db_path = Path(raw_tmp_path)

            with zipfile.ZipFile(src_path, mode="r") as zf:
                manifest: dict[str, object] | None = None
                if "manifest.json" in zf.namelist():
                    try:
                        manifest_raw = zf.read("manifest.json")
                        parsed = json.loads(manifest_raw.decode("utf-8"))
                        if isinstance(parsed, dict):
                            manifest = parsed
                    except Exception:
                        manifest = None

                db_member: str | None = None
                if manifest is not None:
                    m_name = manifest.get("db_filename")
                    if isinstance(m_name, str) and m_name in zf.namelist():
                        db_member = m_name
                if db_member is None:
                    for name in zf.namelist():
                        n = str(name)
                        if n.endswith("/"):
                            continue
                        if n.lower().endswith(".db"):
                            db_member = str(name)
                            break
                if db_member is None:
                    raise ValueError("No database file found in backup.")
                db_bytes = zf.read(db_member)
                if not db_bytes:
                    raise ValueError("Backup contains an empty database payload.")
                if manifest is not None:
                    m_size = manifest.get("db_size_bytes")
                    if isinstance(m_size, int) and int(m_size) != int(len(db_bytes)):
                        raise ValueError("Backup manifest size mismatch.")
                    m_hash = manifest.get("db_sha256")
                    if isinstance(m_hash, str):
                        calc_hash = self._sha256_bytes(db_bytes)
                        if calc_hash.lower() != m_hash.lower():
                            raise ValueError("Backup manifest checksum mismatch.")

            with open(tmp_db_path, "wb") as dst_file:
                dst_file.write(db_bytes)

            with sqlite3.connect(tmp_db_path) as check_conn:
                check_conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()

            if DB_PATH.exists():
                DB_PATH.unlink()
            shutil.copy2(tmp_db_path, DB_PATH)
            init_db()
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", f"Could not import backup:\n{exc}")
            return
        finally:
            if tmp_db_path is not None:
                try:
                    tmp_db_path.unlink(missing_ok=True)
                except Exception:
                    pass

        self._reload_all_pages_from_db()
        QMessageBox.information(self, "Import complete", "Backup imported successfully.")

    def _open_settings_dialog(self) -> None:
        dlg = SettingsDialog(
            on_reset_database=self._reset_database_to_factory,
            on_get_model_root=self._get_model_root,
            on_set_model_root=self._set_model_root,
            on_clear_model_root=self._clear_model_root,
            on_list_sources=self._list_sources,
            on_add_source=self._add_source,
            on_remove_source=self._remove_source,
            on_list_excluded_images=self._list_excluded_images,
            on_add_excluded_image=self._add_excluded_image,
            on_remove_excluded_image=self._remove_excluded_image,
            on_list_excluded_faces=self._list_excluded_faces,
            on_add_excluded_face=self._add_excluded_face,
            on_remove_excluded_face=self._remove_excluded_face,
            parent=self,
        )
        dlg.exec()
        self._refresh_current_page_if_dirty()

    def _get_model_root(self) -> str:
        path = get_saved_model_root()
        return str(path) if path is not None else ""

    def _set_model_root(self, path: str) -> tuple[bool, str]:
        root = normalize_model_root_selection(path)
        if not is_valid_model_root(root):
            return (False, describe_model_root(root))
        set_saved_model_root(root)
        return (True, describe_model_root(root))

    def _clear_model_root(self) -> tuple[bool, str]:
        set_saved_model_root(None)
        return (True, "Stored model path cleared.")

    def _list_sources(self) -> tuple[str, ...]:
        try:
            return tuple(list_source_folders())
        except Exception:
            return tuple()

    def _add_source(self, path: str) -> tuple[bool, str]:
        try:
            add_source_folder(str(path))
            return (True, "Source folder added.")
        except Exception as exc:
            return (False, f"Could not add source folder:\n{exc}")

    def _remove_source(self, path: str) -> tuple[bool, str]:
        try:
            remove_source_folder(str(path))
            return (True, "Source folder removed.")
        except Exception as exc:
            return (False, f"Could not remove source folder:\n{exc}")

    def _list_excluded_images(self) -> tuple[str, ...]:
        try:
            return tuple(list_excluded_images())
        except Exception:
            return tuple()

    def _add_excluded_image(self, path: str) -> tuple[bool, str]:
        try:
            add_excluded_image(str(path))
            self._mark_all_pages_dirty()
            return (True, "Image excluded.")
        except Exception as exc:
            return (False, f"Could not exclude image:\n{exc}")

    def _remove_excluded_image(self, path: str) -> tuple[bool, str]:
        try:
            remove_excluded_image(str(path))
            self._mark_all_pages_dirty()
            return (True, "Image re-included.")
        except Exception as exc:
            return (False, f"Could not remove excluded image:\n{exc}")

    def _list_excluded_faces(self) -> tuple[tuple[int, str], ...]:
        try:
            rows = list_excluded_faces()
            out: list[tuple[int, str]] = []
            for face_id, path, _x, _y, _w, _h, _pid in rows:
                out.append((int(face_id), str(path)))
            return tuple(out)
        except Exception:
            return tuple()

    def _add_excluded_face(self, face_id: int) -> tuple[bool, str]:
        try:
            add_excluded_face(int(face_id))
            self._mark_all_pages_dirty()
            return (True, "Face excluded.")
        except Exception as exc:
            return (False, f"Could not exclude face:\n{exc}")

    def _remove_excluded_face(self, face_id: int) -> tuple[bool, str]:
        try:
            remove_excluded_face(int(face_id))
            self._mark_all_pages_dirty()
            return (True, "Face re-included.")
        except Exception as exc:
            return (False, f"Could not remove excluded face:\n{exc}")

    def _reset_database_to_factory(self) -> tuple[bool, str]:
        if (self._import_thread is not None and self._import_thread.isRunning()) or (
            self._rebuild_handle is not None and self._rebuild_handle.runner.is_running()
        ):
            return (False, "Cannot reset while import or rebuild is running.")

        try:
            reset_database_to_factory()
        except Exception as exc:
            return (False, f"Database reset failed:\n{exc}")

        self._mark_all_pages_dirty()
        self._refresh_current_page_if_dirty()
        return (True, "Database was reset to factory state.")

    def _mk_tab(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("TopTab")
        b.setCheckable(True)
        return b

    def _activate(self, btn: QPushButton, index: int) -> None:
        for b in (self.btn_people, self.btn_suggested, self.btn_unknown, self.btn_stats):
            b.setChecked(b is btn)

        self._update_top_actions_visibility(int(index))
        self.stack.setCurrentIndex(index)
        self._refresh_page_if_dirty(int(index))

    def _update_top_actions_visibility(self, index: int) -> None:
        is_unknown = int(index) == 2
        self.btn_import.setVisible(bool(is_unknown))

    def _refresh_page_if_dirty(
        self,
        index: int,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        idx = int(index)
        if not self._page_dirty.get(idx, True):
            return

        if progress_cb is None and self.isVisible():
            self._show_tile_prepare_dialog()
            try:
                def _cb(current: int, total: int, message: str) -> None:
                    self._update_tile_prepare_progress(int(current), int(total), str(message))

                self._refresh_page(idx, progress_cb=_cb)
                self._update_tile_prepare_progress(1, 1, "Done.")
            finally:
                self._close_tile_prepare_dialog()
        else:
            self._refresh_page(idx, progress_cb=progress_cb)

        self._page_dirty[idx] = False

    def _refresh_page(
        self,
        index: int,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        if int(index) == 0:
            self.page_people.refresh(progress_cb=progress_cb)
        elif int(index) == 1:
            self.page_suggested.refresh(progress_cb=progress_cb)
        elif int(index) == 2:
            self.page_unknown.refresh(progress_cb=progress_cb)
        elif int(index) == 3:
            self.page_stats.refresh(progress_cb=progress_cb)

    def _mark_all_pages_dirty(self) -> None:
        for idx in (0, 1, 2, 3):
            self._page_dirty[idx] = True

    def _refresh_current_page_if_dirty(
        self,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> None:
        self._refresh_page_if_dirty(int(self.stack.currentIndex()), progress_cb=progress_cb)

    def _reload_all_pages_from_db(self) -> None:
        current_index = int(self.stack.currentIndex())
        for idx in (0, 1, 2, 3):
            self._refresh_page(idx, progress_cb=None)
            self._page_dirty[idx] = False
        self.stack.setCurrentIndex(current_index)

    def analyze_images(self) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            return

        model_root = ensure_saved_model_root()
        if model_root is None or not is_valid_model_root(model_root):
            QMessageBox.warning(
                self,
                "Model Not Configured",
                "The InsightFace model pack 'buffalo_l' is not configured.\n"
                "Please configure it in Settings > Models before analyzing images.",
            )
            return

        folders = tuple(list_source_folders())
        if not folders:
            QMessageBox.information(
                self,
                "No Sources Configured",
                "No source folders configured.\n"
                "Please add folders in Settings > Sources first.",
            )
            return

        self._import_error = None
        self._set_busy_ui(True)
        self._show_import_progress_dialog()

        thread = QThread(self)
        worker = ImportWorker(folders)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_import_progress)
        worker.status.connect(self._on_import_status)
        worker.error.connect(self._on_import_error)
        worker.finished.connect(self._on_import_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._import_thread = thread
        self._import_worker = worker
        thread.start()

    def _show_import_progress_dialog(self) -> None:
        dlg = QProgressDialog("Preparing source analysis...", "", 0, 100, self)
        dlg.setWindowTitle("Analyze Images")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setValue(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        self._import_progress = dlg
        dlg.show()

    def _show_tile_prepare_dialog(self) -> None:
        dlg = QProgressDialog("Preparing image tiles...", "", 0, 1, self)
        dlg.setWindowTitle("Preparing View")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setValue(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        self._tile_prepare_progress = dlg
        dlg.show()
        QApplication.processEvents()

    def _close_tile_prepare_dialog(self) -> None:
        if self._tile_prepare_progress is None:
            return
        self._tile_prepare_progress.close()
        self._tile_prepare_progress.deleteLater()
        self._tile_prepare_progress = None

    def _update_tile_prepare_progress(self, current: int, total: int, message: str) -> None:
        if self._tile_prepare_progress is None:
            return
        total_i = max(1, int(total))
        current_i = max(0, min(int(current), total_i))
        self._tile_prepare_progress.setRange(0, total_i)
        self._tile_prepare_progress.setValue(current_i)
        self._tile_prepare_progress.setLabelText(str(message))
        QApplication.processEvents()

    def _on_import_progress(self, current: int, total: int) -> None:
        if self._import_progress is None:
            return
        if int(total) <= 0:
            self._import_progress.setRange(0, 0)
            return
        self._import_progress.setRange(0, int(total))
        self._import_progress.setValue(int(current))

    def _on_import_status(self, message: str) -> None:
        if self._import_progress is not None:
            self._import_progress.setLabelText(str(message))

    def _on_import_error(self, message: str) -> None:
        self._import_error = str(message)

    def _on_import_finished(self) -> None:
        if self._import_progress is not None:
            self._import_progress.close()
            self._import_progress.deleteLater()
            self._import_progress = None

        self._set_busy_ui(False)

        if self._import_thread is not None:
            self._import_thread = None
        if self._import_worker is not None:
            self._import_worker = None

        if self._import_error:
            QMessageBox.critical(self, "Import failed", self._import_error)
            return

        self._mark_all_pages_dirty()
        self._refresh_current_page_if_dirty()

    def rebuild_embeddings(self) -> None:
        if self._rebuild_handle is not None and self._rebuild_handle.runner.is_running():
            return

        handle = create_rebuild_face_embeddings_runner(
            parent=self,
            model=StubEmbeddingModel(
                hint=(
                    "Integrate a real EmbeddingModel adapter (InsightFace/FaceNet) "
                    "before running rebuild."
                )
            ),
            model_id="default",
        )
        self._rebuild_handle = handle
        self._rebuild_error = None

        runner = handle.runner
        runner.worker.progress.connect(self._on_rebuild_progress)
        runner.worker.status.connect(self._on_rebuild_status)
        runner.worker.error.connect(self._on_rebuild_error)
        runner.worker.finished.connect(self._on_rebuild_finished)

        self._set_busy_ui(True)
        self._show_rebuild_progress_dialog()
        runner.start()

    def _set_busy_ui(self, busy: bool) -> None:
        enabled = not bool(busy)
        self.btn_import.setEnabled(enabled)
        for action_name in ("action_export_backup", "action_import_backup", "action_rebuild_embeddings"):
            action = getattr(self, action_name, None)
            if action is not None:
                action.setEnabled(enabled)

    def _show_rebuild_progress_dialog(self) -> None:
        dlg = QProgressDialog("Preparing rebuild...", "Cancel", 0, 0, self)
        dlg.setWindowTitle("Rebuild Embeddings")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        dlg.canceled.connect(self._cancel_rebuild_embeddings)
        self._rebuild_progress = dlg
        dlg.show()

    def _cancel_rebuild_embeddings(self) -> None:
        if self._rebuild_handle is None:
            return
        self._rebuild_handle.runner.cancel()

    def _on_rebuild_progress(self, current: int, total: int) -> None:
        if self._rebuild_progress is None:
            return
        if int(total) <= 0:
            self._rebuild_progress.setRange(0, 0)
            return
        self._rebuild_progress.setRange(0, int(total))
        self._rebuild_progress.setValue(int(current))

    def _on_rebuild_status(self, message: str) -> None:
        if self._rebuild_progress is not None:
            self._rebuild_progress.setLabelText(str(message))

    def _on_rebuild_error(self, message: str) -> None:
        self._rebuild_error = str(message)

    def _on_rebuild_finished(self) -> None:
        if self._rebuild_progress is not None:
            self._rebuild_progress.close()
            self._rebuild_progress.deleteLater()
            self._rebuild_progress = None

        self._set_busy_ui(False)

        handle = self._rebuild_handle
        self._rebuild_handle = None
        if handle is None:
            return

        result = handle.result
        if self._rebuild_error:
            QMessageBox.critical(self, "Rebuild embeddings failed", self._rebuild_error)
            return

        summary = (
            f"Rebuild finished.\n\n"
            f"OK: {result.ok}\n"
            f"Skipped: {result.skipped}\n"
            f"Failed: {result.failed}\n"
            f"Total: {result.total}\n"
            f"Cancelled: {'yes' if result.cancelled else 'no'}\n"
            f"Prototypes recomputed: {'yes' if result.prototypes_recomputed else 'no'}"
        )
        QMessageBox.information(self, "Rebuild embeddings", summary)

        self._mark_all_pages_dirty()
        self._refresh_current_page_if_dirty()


