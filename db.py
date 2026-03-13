from __future__ import annotations

import os
import sqlite3
from array import array
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, cast
from uuid import uuid4

import numpy as np

APP_DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "BioTagPhoto"
DB_PATH = APP_DATA_DIR / "tagthatphoto.db"
DEFAULT_MODEL_ID = "default"


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_db_parent() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _migrate_legacy_db_if_needed() -> None:
    legacy = Path.cwd() / "tagthatphoto.db"
    if DB_PATH.exists():
        return
    if not legacy.exists():
        return
    if legacy.resolve() == DB_PATH.resolve():
        return
    _ensure_db_parent()
    shutil.copy2(legacy, DB_PATH)


def get_connection() -> sqlite3.Connection:
    _ensure_db_parent()
    _migrate_legacy_db_if_needed()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection, table: str) -> Dict[str, sqlite3.Row]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    out: Dict[str, sqlite3.Row] = {}
    for row in rows:
        name = row["name"]
        if name is not None:
            out[str(name)] = row
    return out


def _people_table(conn: sqlite3.Connection) -> str:
    if _table_exists(conn, "persons"):
        return "persons"
    return "people"


def _create_base_tables(conn: sqlite3.Connection) -> None:
    people_table = _people_table(conn)
    if people_table == "people":
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
            """
        )

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS source_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS excluded_images (
            path TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS excluded_faces (
            face_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            FOREIGN KEY(face_id) REFERENCES faces(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id INTEGER NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            w INTEGER NOT NULL,
            h INTEGER NOT NULL,
            person_id INTEGER NULL,
            FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces(person_id);
        CREATE INDEX IF NOT EXISTS idx_source_folders_path ON source_folders(path);
        CREATE INDEX IF NOT EXISTS idx_excluded_images_path ON excluded_images(path);
        CREATE INDEX IF NOT EXISTS idx_excluded_faces_face_id ON excluded_faces(face_id);
        """
    )


def _create_embedding_tables(conn: sqlite3.Connection) -> None:
    people_table = _people_table(conn)
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS face_embeddings (
            face_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            dim INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(face_id) REFERENCES faces(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS person_prototypes (
            person_id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            embedding BLOB NOT NULL,
            dim INTEGER NOT NULL,
            sample_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(person_id) REFERENCES {people_table}(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS person_embeddings (
            person_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            dim INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(person_id) REFERENCES {people_table}(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assignment_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            face_id INTEGER NOT NULL,
            old_person_id INTEGER NULL,
            new_person_id INTEGER NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(face_id) REFERENCES faces(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_person_embeddings_person_id ON person_embeddings(person_id);
        CREATE INDEX IF NOT EXISTS idx_assignment_log_batch_id ON assignment_log(batch_id);
        CREATE INDEX IF NOT EXISTS idx_assignment_log_face_id ON assignment_log(face_id);
        """
    )


def _migrate_face_embeddings(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "face_embeddings"):
        return
    cols = _table_columns(conn, "face_embeddings")
    if cols.get("face_id") and int(cols["face_id"]["pk"]) == 1 and {"face_id", "model_id", "embedding", "dim", "created_at"}.issubset(cols):
        return

    if _table_exists(conn, "face_embeddings_legacy"):
        conn.execute("DROP TABLE face_embeddings_legacy")
    conn.execute("ALTER TABLE face_embeddings RENAME TO face_embeddings_legacy")
    _create_embedding_tables(conn)
    old = _table_columns(conn, "face_embeddings_legacy")
    if not {"face_id", "embedding"}.issubset(old):
        return

    model_expr = (
        "COALESCE(NULLIF(model_id, ''), NULLIF(model, ''), 'default')"
        if "model_id" in old and "model" in old
        else "COALESCE(NULLIF(model_id, ''), 'default')"
        if "model_id" in old
        else "COALESCE(NULLIF(model, ''), 'default')"
        if "model" in old
        else "'default'"
    )
    dim_expr = "dim" if "dim" in old else "CAST(LENGTH(embedding) / 4 AS INTEGER)"
    ts_expr = "created_at" if "created_at" in old else "updated_at" if "updated_at" in old else "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    conn.execute(
        f"""
        INSERT OR REPLACE INTO face_embeddings(face_id, model_id, embedding, dim, created_at)
        SELECT face_id, {model_expr}, embedding, {dim_expr},
               COALESCE({ts_expr}, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        FROM face_embeddings_legacy
        WHERE face_id IS NOT NULL AND embedding IS NOT NULL
        """
    )


def _migrate_person_prototypes(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "person_prototypes"):
        return
    cols = _table_columns(conn, "person_prototypes")
    if cols.get("person_id") and int(cols["person_id"]["pk"]) == 1 and {"person_id", "model_id", "embedding", "dim", "sample_count", "updated_at"}.issubset(cols):
        return

    if _table_exists(conn, "person_prototypes_legacy"):
        conn.execute("DROP TABLE person_prototypes_legacy")
    conn.execute("ALTER TABLE person_prototypes RENAME TO person_prototypes_legacy")
    _create_embedding_tables(conn)
    old = _table_columns(conn, "person_prototypes_legacy")
    if not {"person_id", "embedding"}.issubset(old):
        return

    model_expr = (
        "COALESCE(NULLIF(model_id, ''), NULLIF(model, ''), 'default')"
        if "model_id" in old and "model" in old
        else "COALESCE(NULLIF(model_id, ''), 'default')"
        if "model_id" in old
        else "COALESCE(NULLIF(model, ''), 'default')"
        if "model" in old
        else "'default'"
    )
    dim_expr = "dim" if "dim" in old else "CAST(LENGTH(embedding) / 4 AS INTEGER)"
    sample_expr = "sample_count" if "sample_count" in old else "0"
    ts_expr = "updated_at" if "updated_at" in old else "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    conn.execute(
        f"""
        INSERT OR REPLACE INTO person_prototypes(person_id, model_id, embedding, dim, sample_count, updated_at)
        SELECT person_id, {model_expr}, embedding, {dim_expr}, COALESCE({sample_expr}, 0),
               COALESCE({ts_expr}, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        FROM person_prototypes_legacy
        WHERE person_id IS NOT NULL AND embedding IS NOT NULL
        """
    )


def _ensure_embedding_columns(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "face_embeddings"):
        cols = _table_columns(conn, "face_embeddings")
        if "model_id" not in cols:
            conn.execute("ALTER TABLE face_embeddings ADD COLUMN model_id TEXT")
        if "dim" not in cols:
            conn.execute("ALTER TABLE face_embeddings ADD COLUMN dim INTEGER")
        if "created_at" not in cols:
            conn.execute("ALTER TABLE face_embeddings ADD COLUMN created_at TEXT")
        if "model" in cols and "updated_at" in cols:
            conn.execute(
                """
                UPDATE face_embeddings
                SET model_id = COALESCE(NULLIF(model_id, ''), NULLIF(model, ''), 'default'),
                    dim = COALESCE(dim, CAST(LENGTH(embedding) / 4 AS INTEGER)),
                    created_at = COALESCE(created_at, updated_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """
            )
        elif "model" in cols:
            conn.execute(
                """
                UPDATE face_embeddings
                SET model_id = COALESCE(NULLIF(model_id, ''), NULLIF(model, ''), 'default'),
                    dim = COALESCE(dim, CAST(LENGTH(embedding) / 4 AS INTEGER)),
                    created_at = COALESCE(created_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """
            )
        else:
            conn.execute(
                """
                UPDATE face_embeddings
                SET model_id = COALESCE(NULLIF(model_id, ''), 'default'),
                    dim = COALESCE(dim, CAST(LENGTH(embedding) / 4 AS INTEGER)),
                    created_at = COALESCE(created_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """
            )

    if _table_exists(conn, "person_prototypes"):
        cols = _table_columns(conn, "person_prototypes")
        if "model_id" not in cols:
            conn.execute("ALTER TABLE person_prototypes ADD COLUMN model_id TEXT")
        if "dim" not in cols:
            conn.execute("ALTER TABLE person_prototypes ADD COLUMN dim INTEGER")
        if "sample_count" not in cols:
            conn.execute("ALTER TABLE person_prototypes ADD COLUMN sample_count INTEGER")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE person_prototypes ADD COLUMN updated_at TEXT")
        if "model" in cols:
            conn.execute(
                """
                UPDATE person_prototypes
                SET model_id = COALESCE(NULLIF(model_id, ''), NULLIF(model, ''), 'default'),
                    dim = COALESCE(dim, CAST(LENGTH(embedding) / 4 AS INTEGER)),
                    sample_count = COALESCE(sample_count, 0),
                    updated_at = COALESCE(updated_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """
            )
        else:
            conn.execute(
                """
                UPDATE person_prototypes
                SET model_id = COALESCE(NULLIF(model_id, ''), 'default'),
                    dim = COALESCE(dim, CAST(LENGTH(embedding) / 4 AS INTEGER)),
                    sample_count = COALESCE(sample_count, 0),
                    updated_at = COALESCE(updated_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                """
            )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_faces_person_id ON faces(person_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_face_embeddings_model_id ON face_embeddings(model_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_person_prototypes_model_id ON person_prototypes(model_id)")


def ensure_schema() -> None:
    with get_connection() as conn:
        _create_base_tables(conn)
        _create_embedding_tables(conn)
        _migrate_face_embeddings(conn)
        _migrate_person_prototypes(conn)
        _ensure_embedding_columns(conn)
        conn.commit()


def normalize_image_path(path: str) -> str:
    clean = str(path).strip()
    if not clean:
        raise ValueError("Image path cannot be empty")
    return str(Path(clean).expanduser().resolve(strict=False))


def init_db() -> None:
    ensure_schema()


def pack_embedding(vec: np.ndarray) -> tuple[bytes, int]:
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        raise ValueError("Embedding vector must not be empty")
    return arr.tobytes(), int(arr.size)


def unpack_embedding(blob: bytes, dim: int) -> np.ndarray:
    n = int(dim)
    if n <= 0:
        raise ValueError("Embedding dim must be > 0")
    arr = np.frombuffer(blob, dtype=np.float32)
    if int(arr.size) != n:
        raise ValueError(f"Embedding dim mismatch: expected {n}, got {arr.size}")
    return np.asarray(arr, dtype=np.float32)


def _pack_f32(values: Sequence[float] | np.ndarray) -> bytes:
    arr = np.asarray(values, dtype=np.float32).reshape(-1)
    buf = array("f")
    buf.fromlist(arr.tolist())
    return buf.tobytes()


def _unpack_f32(blob: bytes) -> List[float]:
    arr = array("f")
    arr.frombytes(blob)
    return [float(x) for x in arr]


def _normalize(values: Sequence[float] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm > 0:
        arr = arr / norm
    return arr


def create_person(name: str) -> int:
    clean = (name or "").strip()
    if not clean:
        raise ValueError("Name cannot be empty")
    with get_connection() as conn:
        table = _people_table(conn)
        cur = conn.execute(f"INSERT INTO {table}(name) VALUES(?)", (clean,))
        conn.commit()
        if cur.lastrowid is None:
            raise RuntimeError("Could not create person")
        return int(cur.lastrowid)


def rename_person(person_id: int, new_name: str) -> None:
    clean = (new_name or "").strip()
    if not clean:
        raise ValueError("New name cannot be empty")
    with get_connection() as conn:
        table = _people_table(conn)
        conn.execute(f"UPDATE {table} SET name=? WHERE id=?", (clean, int(person_id)))
        conn.commit()


def delete_person(person_id: int) -> None:
    with get_connection() as conn:
        table = _people_table(conn)
        conn.execute("UPDATE faces SET person_id=NULL WHERE person_id=?", (int(person_id),))
        conn.execute("DELETE FROM person_prototypes WHERE person_id=?", (int(person_id),))
        conn.execute("DELETE FROM person_embeddings WHERE person_id=?", (int(person_id),))
        conn.execute(f"DELETE FROM {table} WHERE id=?", (int(person_id),))
        conn.commit()


def list_people_ids() -> List[int]:
    with get_connection() as conn:
        table = _people_table(conn)
        rows = conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()
        return [int(r["id"]) for r in rows if r["id"] is not None]


def list_people_with_face_count() -> List[Tuple[int, str, int]]:
    with get_connection() as conn:
        table = _people_table(conn)
        rows = conn.execute(
            f"""
            SELECT p.id AS person_id, p.name AS name,
                   COALESCE(SUM(CASE WHEN ei.path IS NULL AND ef.face_id IS NULL AND f.id IS NOT NULL THEN 1 ELSE 0 END), 0) AS cnt
            FROM {table} p
            LEFT JOIN faces f ON f.person_id = p.id
            LEFT JOIN photos ph ON ph.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = ph.path
            LEFT JOIN excluded_faces ef ON ef.face_id = f.id
            GROUP BY p.id
            ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()
        out: List[Tuple[int, str, int]] = []
        for row in rows:
            if row["person_id"] is None or row["name"] is None or row["cnt"] is None:
                continue
            out.append((int(row["person_id"]), str(row["name"]), int(row["cnt"])))
        return out


def list_source_folders() -> List[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT path
            FROM source_folders
            ORDER BY path COLLATE NOCASE
            """
        ).fetchall()
        out: List[str] = []
        for row in rows:
            if row["path"] is None:
                continue
            out.append(str(row["path"]))
        return out


def add_source_folder(path: str) -> None:
    clean = str(path).strip()
    if not clean:
        raise ValueError("Source folder path cannot be empty")
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT OR IGNORE INTO source_folders(path, created_at)
                VALUES (?, ?)
                """,
                (clean, _now_iso_utc()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def remove_source_folder(path: str) -> None:
    clean = str(path).strip()
    if not clean:
        raise ValueError("Source folder path cannot be empty")
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM source_folders WHERE path=?", (clean,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def list_excluded_images() -> List[str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT path
            FROM excluded_images
            ORDER BY path COLLATE NOCASE
            """
        ).fetchall()
        out: List[str] = []
        for row in rows:
            if row["path"] is None:
                continue
            out.append(str(row["path"]))
        return out


def add_excluded_image(path: str) -> None:
    normalized = normalize_image_path(path)
    affected_people: set[int] = set()
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            rows = conn.execute(
                """
                SELECT DISTINCT f.person_id
                FROM faces f
                JOIN photos p ON p.id = f.photo_id
                WHERE p.path=? AND f.person_id IS NOT NULL
                """,
                (normalized,),
            ).fetchall()
            affected_people = {int(r["person_id"]) for r in rows if r["person_id"] is not None}
            conn.execute(
                """
                INSERT OR IGNORE INTO excluded_images(path, created_at)
                VALUES (?, ?)
                """,
                (normalized, _now_iso_utc()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    for person_id in affected_people:
        recompute_person_prototype(int(person_id), model_id=DEFAULT_MODEL_ID)


def remove_excluded_image(path: str) -> None:
    normalized = normalize_image_path(path)
    affected_people: set[int] = set()
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            rows = conn.execute(
                """
                SELECT DISTINCT f.person_id
                FROM faces f
                JOIN photos p ON p.id = f.photo_id
                WHERE p.path=? AND f.person_id IS NOT NULL
                """,
                (normalized,),
            ).fetchall()
            affected_people = {int(r["person_id"]) for r in rows if r["person_id"] is not None}
            conn.execute("DELETE FROM excluded_images WHERE path=?", (normalized,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    for person_id in affected_people:
        recompute_person_prototype(int(person_id), model_id=DEFAULT_MODEL_ID)


def is_excluded_image(path: str) -> bool:
    normalized = normalize_image_path(path)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM excluded_images WHERE path=? LIMIT 1",
            (normalized,),
        ).fetchone()
        return row is not None


def count_excluded_images() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM excluded_images").fetchone()
        if row is None or row["cnt"] is None:
            return 0
        return int(row["cnt"])


def list_excluded_faces() -> List[Tuple[int, str, int, int, int, int, Optional[int]]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ef.face_id, p.path, f.x, f.y, f.w, f.h, f.person_id
            FROM excluded_faces ef
            JOIN faces f ON f.id = ef.face_id
            JOIN photos p ON p.id = f.photo_id
            ORDER BY ef.face_id DESC
            """
        ).fetchall()
        out: List[Tuple[int, str, int, int, int, int, Optional[int]]] = []
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            pid = int(row["person_id"]) if row["person_id"] is not None else None
            out.append(
                (
                    int(row["face_id"]),
                    str(row["path"]),
                    int(row["x"]),
                    int(row["y"]),
                    int(row["w"]),
                    int(row["h"]),
                    pid,
                )
            )
        return out


def add_excluded_face(face_id: int) -> None:
    fid = int(face_id)
    with get_connection() as conn:
        row = conn.execute("SELECT person_id FROM faces WHERE id=?", (fid,)).fetchone()
        if row is None:
            raise ValueError(f"Face not found: {fid}")
        old_person_id = int(row["person_id"]) if row["person_id"] is not None else None
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT OR IGNORE INTO excluded_faces(face_id, created_at)
                VALUES (?, ?)
                """,
                (fid, _now_iso_utc()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if old_person_id is not None:
        recompute_person_prototype(old_person_id, model_id=DEFAULT_MODEL_ID)


def remove_excluded_face(face_id: int) -> None:
    fid = int(face_id)
    old_person_id: Optional[int] = None
    with get_connection() as conn:
        row = conn.execute("SELECT person_id FROM faces WHERE id=?", (fid,)).fetchone()
        if row is not None and row["person_id"] is not None:
            old_person_id = int(row["person_id"])
        try:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM excluded_faces WHERE face_id=?", (fid,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    if old_person_id is not None:
        recompute_person_prototype(old_person_id, model_id=DEFAULT_MODEL_ID)


def count_excluded_faces() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS cnt FROM excluded_faces").fetchone()
        if row is None or row["cnt"] is None:
            return 0
        return int(row["cnt"])


def list_faces_for_person(person_id: int, limit: Optional[int] = None) -> List[Tuple[int, str, int, int, int, int]]:
    sql = """
        SELECT f.id AS face_id, p.path AS path, f.x, f.y, f.w, f.h
        FROM faces f
        JOIN photos p ON p.id = f.photo_id
        LEFT JOIN excluded_images ei ON ei.path = p.path
        LEFT JOIN excluded_faces ef ON ef.face_id = f.id
        WHERE f.person_id = ?
          AND ei.path IS NULL
          AND ef.face_id IS NULL
        ORDER BY f.id DESC
    """
    params: List[object] = [int(person_id)]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        out: List[Tuple[int, str, int, int, int, int]] = []
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            out.append((int(row["face_id"]), str(row["path"]), int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])))
        return out


def get_first_face_for_person(person_id: int) -> Optional[Tuple[str, int, int, int, int]]:
    rows = list_faces_for_person(int(person_id), limit=1)
    if not rows:
        return None
    _, path, x, y, w, h = rows[0]
    return (path, x, y, w, h)


def list_unknown_faces() -> List[Tuple[int, str, int, int, int, int]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS face_id, p.path AS path, f.x, f.y, f.w, f.h
            FROM faces f
            JOIN photos p ON p.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = p.path
            LEFT JOIN excluded_faces ef ON ef.face_id = f.id
            WHERE f.person_id IS NULL
              AND ei.path IS NULL
              AND ef.face_id IS NULL
            ORDER BY f.id DESC
            """
        ).fetchall()
        out: List[Tuple[int, str, int, int, int, int]] = []
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            out.append((int(row["face_id"]), str(row["path"]), int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])))
        return out


def create_or_get_photo(path: str) -> int:
    clean = str(path).strip()
    if not clean:
        raise ValueError("photo path cannot be empty")
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM photos WHERE path=?", (clean,)).fetchone()
        if row is not None and row["id"] is not None:
            return int(row["id"])
        cur = conn.execute("INSERT INTO photos(path) VALUES(?)", (clean,))
        conn.commit()
        if cur.lastrowid is None:
            raise RuntimeError("Could not create photo")
        return int(cur.lastrowid)


def add_face(
    photo_id: int,
    x: int,
    y: int,
    w: int,
    h: int,
    person_id: Optional[int] = None,
    embedding: Optional[list[float]] = None,
    model: str = "default",
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO faces(photo_id, x, y, w, h, person_id) VALUES(?, ?, ?, ?, ?, ?)",
            (int(photo_id), int(x), int(y), int(w), int(h), int(person_id) if person_id is not None else None),
        )
        conn.commit()
        if cur.lastrowid is None:
            raise RuntimeError("Could not create face")
        face_id = int(cur.lastrowid)
    if embedding is not None:
        upsert_face_embedding(face_id, embedding, model=model)
    if person_id is not None:
        recompute_person_prototype(int(person_id), model=model)
    return face_id


def assign_face_to_person(face_id: int, person_id: int) -> None:
    assign_faces_to_person([int(face_id)], int(person_id))


def assign_faces_to_person(
    face_ids: Sequence[int],
    person_id: int,
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    ids = [int(fid) for fid in face_ids]
    if not ids:
        return
    total = len(ids)
    with get_connection() as conn:
        placeholders = ",".join("?" for _ in ids)
        old_rows = conn.execute(
            f"SELECT DISTINCT person_id FROM faces WHERE id IN ({placeholders}) AND person_id IS NOT NULL",
            ids,
        ).fetchall()
        old_person_ids = {int(r["person_id"]) for r in old_rows if r["person_id"] is not None}
        for idx, fid in enumerate(ids, start=1):
            conn.execute("UPDATE faces SET person_id=? WHERE id=?", (int(person_id), int(fid)))
            if progress_cb is not None:
                progress_cb(int(idx), int(total))
        conn.commit()
    if progress_cb is not None:
        progress_cb(int(total), int(total))
    recompute_person_prototype(int(person_id), model="default")
    for old_person_id in old_person_ids:
        if old_person_id != int(person_id):
            recompute_person_prototype(old_person_id, model="default")


def unassign_face(face_id: int) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT person_id FROM faces WHERE id=?", (int(face_id),)).fetchone()
        if row is None:
            return
        old_person = int(row["person_id"]) if row["person_id"] is not None else None
        conn.execute("UPDATE faces SET person_id=NULL WHERE id=?", (int(face_id),))
        conn.commit()
    if old_person is not None:
        recompute_person_prototype(old_person, model="default")


def unassign_all_faces_from_person(person_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE faces SET person_id=NULL WHERE person_id=?", (int(person_id),))
        conn.commit()
    recompute_person_prototype(int(person_id), model="default")


def begin_assignment_batch() -> str:
    return f"{_now_iso_utc()}_{uuid4().hex}"


def log_assignment(batch_id: str, face_id: int, old_person_id: Optional[int], new_person_id: Optional[int]) -> None:
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                INSERT INTO assignment_log(batch_id, face_id, old_person_id, new_person_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(batch_id),
                    int(face_id),
                    int(old_person_id) if old_person_id is not None else None,
                    int(new_person_id) if new_person_id is not None else None,
                    _now_iso_utc(),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def apply_assignments(
    batch_id: str,
    assignments: list[tuple[int, int]],
    progress_cb: Optional[Callable[[int, int], None]] = None,
) -> None:
    if not assignments:
        return

    affected_people: set[int] = set()
    total = len(assignments)
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            for idx, (face_id_raw, new_person_id_raw) in enumerate(assignments, start=1):
                face_id = int(face_id_raw)
                new_person_id = int(new_person_id_raw)

                row = conn.execute("SELECT person_id FROM faces WHERE id=?", (face_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Face not found: {face_id}")
                old_person_id = int(row["person_id"]) if row["person_id"] is not None else None

                conn.execute(
                    """
                    INSERT INTO assignment_log(batch_id, face_id, old_person_id, new_person_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(batch_id),
                        face_id,
                        old_person_id,
                        new_person_id,
                        _now_iso_utc(),
                    ),
                )
                conn.execute("UPDATE faces SET person_id=? WHERE id=?", (new_person_id, face_id))

                affected_people.add(new_person_id)
                if old_person_id is not None:
                    affected_people.add(int(old_person_id))
                if progress_cb is not None:
                    progress_cb(int(idx), int(total))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    for pid in affected_people:
        recompute_person_prototype(int(pid), model_id=DEFAULT_MODEL_ID)


def get_last_assignment_batch_id() -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT batch_id
            FROM assignment_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None or row["batch_id"] is None:
            return None
        return str(row["batch_id"])


def undo_assignment_batch(batch_id: str) -> int:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, face_id, old_person_id, new_person_id
            FROM assignment_log
            WHERE batch_id=?
            ORDER BY id DESC
            """,
            (str(batch_id),),
        ).fetchall()
        if not rows:
            return 0

        affected_people: set[int] = set()
        try:
            conn.execute("BEGIN")
            reverted = 0
            for row in rows:
                if row["face_id"] is None:
                    continue
                face_id = int(row["face_id"])
                old_person_id = int(row["old_person_id"]) if row["old_person_id"] is not None else None
                new_person_id = int(row["new_person_id"]) if row["new_person_id"] is not None else None

                conn.execute(
                    "UPDATE faces SET person_id=? WHERE id=?",
                    (old_person_id, face_id),
                )
                reverted += 1

                if old_person_id is not None:
                    affected_people.add(old_person_id)
                if new_person_id is not None:
                    affected_people.add(new_person_id)

            conn.execute("DELETE FROM assignment_log WHERE batch_id=?", (str(batch_id),))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    for pid in affected_people:
        recompute_person_prototype(int(pid), model_id=DEFAULT_MODEL_ID)
    return int(reverted)


def iter_faces_for_embedding() -> Iterable[Tuple[int, str, int, int, int, int, Optional[int]]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS face_id, p.path AS path, f.x, f.y, f.w, f.h, f.person_id
            FROM faces f
            JOIN photos p ON p.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = p.path
            LEFT JOIN excluded_faces ef ON ef.face_id = f.id
            WHERE ei.path IS NULL
              AND ef.face_id IS NULL
            ORDER BY f.id ASC
            """
        ).fetchall()
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            pid = int(row["person_id"]) if row["person_id"] is not None else None
            yield (int(row["face_id"]), str(row["path"]), int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]), pid)


def list_all_faces_with_rects() -> List[Tuple[int, str, int, int, int, int]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS face_id, p.path AS path, f.x, f.y, f.w, f.h
            FROM faces f
            JOIN photos p ON p.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = p.path
            LEFT JOIN excluded_faces ef ON ef.face_id = f.id
            WHERE ei.path IS NULL
              AND ef.face_id IS NULL
            ORDER BY f.id ASC
            """
        ).fetchall()
        out: List[Tuple[int, str, int, int, int, int]] = []
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            out.append((int(row["face_id"]), str(row["path"]), int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"])))
        return out


def iter_faces_missing_embeddings() -> Iterable[Tuple[int, str, int, int, int, int, Optional[int]]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id AS face_id, p.path AS path, f.x, f.y, f.w, f.h, f.person_id
            FROM faces f
            JOIN photos p ON p.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = p.path
            LEFT JOIN excluded_faces ef ON ef.face_id = f.id
            LEFT JOIN face_embeddings fe ON fe.face_id = f.id
            WHERE fe.face_id IS NULL
              AND ei.path IS NULL
              AND ef.face_id IS NULL
            ORDER BY f.id ASC
            """
        ).fetchall()
        for row in rows:
            if None in (row["face_id"], row["path"], row["x"], row["y"], row["w"], row["h"]):
                continue
            pid = int(row["person_id"]) if row["person_id"] is not None else None
            yield (int(row["face_id"]), str(row["path"]), int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]), pid)


def upsert_face_embedding(face_id: int, embedding: list[float], model: str = "default") -> None:
    vec = _normalize(embedding)
    blob = _pack_f32(vec)
    created_at = _now_iso_utc()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO face_embeddings(face_id, model_id, embedding, dim, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(face_id) DO UPDATE SET
                model_id=excluded.model_id,
                embedding=excluded.embedding,
                dim=excluded.dim,
                created_at=excluded.created_at
            """,
            (int(face_id), str(model), blob, int(vec.size), created_at),
        )
        conn.commit()


def upsert_person_prototype(person_id: int, embedding: list[float], model: str, sample_count: Optional[int] = None) -> None:
    vec = _normalize(embedding)
    blob = _pack_f32(vec)
    updated_at = _now_iso_utc()
    count = max(0, int(sample_count) if sample_count is not None else 0)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO person_prototypes(person_id, model_id, embedding, dim, sample_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
                model_id=excluded.model_id,
                embedding=excluded.embedding,
                dim=excluded.dim,
                sample_count=excluded.sample_count,
                updated_at=excluded.updated_at
            """,
            (int(person_id), str(model), blob, int(vec.size), count, updated_at),
        )
        conn.execute(
            """
            INSERT INTO person_embeddings(person_id, embedding, dim, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(person_id) DO UPDATE SET
                embedding=excluded.embedding,
                dim=excluded.dim,
                updated_at=excluded.updated_at
            """,
            (int(person_id), blob, int(vec.size), updated_at),
        )
        conn.commit()


def upsert_person_embedding(person_id: int, vec: np.ndarray) -> None:
    values = cast(list[float], np.asarray(vec, dtype=np.float32).reshape(-1).tolist())
    upsert_person_prototype(int(person_id), values, model="default")


def get_face_embedding(face_id: int, model: str = "default") -> Optional[list[float]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT embedding, model_id FROM face_embeddings WHERE face_id=? LIMIT 1",
            (int(face_id),),
        ).fetchone()
        if row is None or row["embedding"] is None:
            return None
        row_model = str(row["model_id"]) if row["model_id"] is not None else "default"
        if row_model != str(model):
            return None
        return _unpack_f32(cast(bytes, row["embedding"]))


def get_person_prototype(person_id: int, model: str) -> Optional[list[float]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT embedding
            FROM person_prototypes
            WHERE person_id=? AND COALESCE(NULLIF(model_id, ''), 'default')=?
            LIMIT 1
            """,
            (int(person_id), str(model)),
        ).fetchone()
        if row is None or row["embedding"] is None:
            return None
        return _unpack_f32(cast(bytes, row["embedding"]))


def get_person_embedding(person_id: int) -> Optional[np.ndarray]:
    vec = get_person_prototype(int(person_id), model="default")
    if vec is None:
        return None
    return np.asarray(vec, dtype=np.float32)


def list_person_prototypes(model: str) -> list[tuple[int, list[float]]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT person_id, embedding
            FROM person_prototypes
            WHERE COALESCE(NULLIF(model_id, ''), 'default')=?
            ORDER BY person_id
            """,
            (str(model),),
        ).fetchall()
        out: list[tuple[int, list[float]]] = []
        for row in rows:
            if row["person_id"] is None or row["embedding"] is None:
                continue
            out.append((int(row["person_id"]), _unpack_f32(cast(bytes, row["embedding"]))))
        return out


def face_embedding_exists(face_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM face_embeddings WHERE face_id=? LIMIT 1", (int(face_id),)).fetchone()
        return row is not None


def get_face_embeddings(face_ids: Sequence[int]) -> Dict[int, np.ndarray]:
    ids = [int(fid) for fid in face_ids]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        rows = conn.execute(f"SELECT face_id, embedding FROM face_embeddings WHERE face_id IN ({placeholders})", ids).fetchall()
    out: Dict[int, np.ndarray] = {}
    for row in rows:
        if row["face_id"] is None or row["embedding"] is None:
            continue
        out[int(row["face_id"])] = _normalize(_unpack_f32(cast(bytes, row["embedding"])))
    return out


def cosine_similarity_01(a: np.ndarray, b: np.ndarray) -> float:
    va = _normalize(a)
    vb = _normalize(b)
    if va.size == 0 or vb.size == 0 or va.size != vb.size:
        return 0.0
    cosine = float(np.dot(va, vb))
    cosine = max(-1.0, min(1.0, cosine))
    return (cosine + 1.0) * 0.5


def suggest_people_for_face(
    face_id: int,
    top_k: int = 3,
    model_id: str = DEFAULT_MODEL_ID,
    min_samples: int = 1,
    **kwargs: Any,
) -> list[tuple[int, float]]:
    legacy_model = kwargs.pop("model", None)
    if legacy_model is not None:
        model_id = str(legacy_model)
    if kwargs:
        unknown = ", ".join(kwargs.keys())
        raise TypeError(f"Unknown keyword argument(s): {unknown}")

    result = suggest_people_for_faces(
        [int(face_id)],
        top_k=int(top_k),
        model_id=str(model_id),
        min_samples=int(min_samples),
    )
    return list(result.get(int(face_id), []))


def suggest_people_for_faces(face_ids: Sequence[int], top_k: int = 3, model_id: str = DEFAULT_MODEL_ID, min_samples: int = 1) -> Dict[int, List[Tuple[int, float]]]:
    ids = [int(v) for v in face_ids]
    out: Dict[int, List[Tuple[int, float]]] = {fid: [] for fid in ids}
    if not ids:
        return out

    target_model_id = str(model_id or DEFAULT_MODEL_ID)
    min_count = max(1, int(min_samples))
    k = max(1, int(top_k))

    placeholders = ",".join("?" for _ in ids)
    with get_connection() as conn:
        fe_rows = conn.execute(
            f"""
            SELECT face_id, embedding, dim
            FROM face_embeddings
            WHERE face_id IN ({placeholders})
              AND COALESCE(NULLIF(model_id, ''), ?) = ?
            """,
            [*ids, DEFAULT_MODEL_ID, target_model_id],
        ).fetchall()

    face_embeddings: Dict[int, np.ndarray] = {}
    for row in fe_rows:
        if row["face_id"] is None or row["embedding"] is None or row["dim"] is None:
            continue
        dim = int(row["dim"])
        if dim <= 0:
            continue
        try:
            vec = _normalize(unpack_embedding(cast(bytes, row["embedding"]), dim))
        except Exception:
            continue
        face_embeddings[int(row["face_id"])] = np.asarray(vec, dtype=np.float32)
    if not face_embeddings:
        return out

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT person_id, embedding, dim
            FROM person_prototypes
            WHERE COALESCE(NULLIF(model_id, ''), ?) = ?
              AND sample_count >= ?
            """,
            (DEFAULT_MODEL_ID, target_model_id, int(min_count)),
        ).fetchall()

    proto_lists: Dict[int, Tuple[List[int], List[np.ndarray]]] = {}
    for row in rows:
        if row["person_id"] is None or row["embedding"] is None or row["dim"] is None:
            continue
        dim = int(row["dim"])
        if dim <= 0:
            continue
        try:
            vec = _normalize(unpack_embedding(cast(bytes, row["embedding"]), dim))
        except Exception:
            continue
        person_id = int(row["person_id"])
        if dim not in proto_lists:
            proto_lists[dim] = ([], [])
        ids_for_dim, vecs_for_dim = proto_lists[dim]
        ids_for_dim.append(person_id)
        vecs_for_dim.append(np.asarray(vec, dtype=np.float32))

    proto_by_dim: Dict[int, Tuple[List[int], np.ndarray]] = {}
    for dim, (ids_for_dim, vecs_for_dim) in proto_lists.items():
        if not ids_for_dim or not vecs_for_dim:
            continue
        proto_by_dim[int(dim)] = (ids_for_dim, np.stack(vecs_for_dim, axis=0).astype(np.float32, copy=False))

    if not proto_by_dim:
        return out

    faces_by_dim: Dict[int, List[Tuple[int, np.ndarray]]] = {}
    for fid in ids:
        vec = face_embeddings.get(int(fid))
        if vec is None:
            continue
        dim = int(vec.size)
        if dim <= 0:
            continue
        faces_by_dim.setdefault(dim, []).append((int(fid), np.asarray(vec, dtype=np.float32)))

    for dim, face_rows in faces_by_dim.items():
        proto_entry = proto_by_dim.get(int(dim))
        if proto_entry is None:
            continue
        proto_ids, proto_mat = proto_entry
        if not proto_ids or proto_mat.size == 0:
            continue

        face_mat = np.stack([row[1] for row in face_rows], axis=0).astype(np.float32, copy=False)
        cosine = face_mat @ proto_mat.T
        scores = (np.clip(cosine, -1.0, 1.0) + 1.0) * 0.5
        top_n = min(int(k), int(scores.shape[1]))
        if top_n <= 0:
            continue

        for i, (fid, _vec) in enumerate(face_rows):
            row_scores = scores[i]
            order = np.argsort(row_scores)[::-1][:top_n]
            out[int(fid)] = [(int(proto_ids[j]), float(row_scores[j])) for j in order]

    return out


def recompute_person_prototype(person_id: int, model_id: str = DEFAULT_MODEL_ID, **kwargs: Any) -> None:
    legacy_model = kwargs.pop("model", None)
    if legacy_model is not None:
        model_id = str(legacy_model)
    if kwargs:
        unknown = ", ".join(kwargs.keys())
        raise TypeError(f"Unknown keyword argument(s): {unknown}")

    target_model_id = str(model_id or DEFAULT_MODEL_ID)
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fe.embedding, fe.dim
            FROM faces f
            JOIN photos p ON p.id = f.photo_id
            LEFT JOIN excluded_images ei ON ei.path = p.path
            LEFT JOIN excluded_faces exf ON exf.face_id = f.id
            JOIN face_embeddings fe ON fe.face_id = f.id
            WHERE f.person_id=?
              AND ei.path IS NULL
              AND exf.face_id IS NULL
              AND COALESCE(NULLIF(fe.model_id, ''), ?) = ?
            """,
            (int(person_id), DEFAULT_MODEL_ID, target_model_id),
        ).fetchall()

    vectors: List[np.ndarray] = []
    expected_dim: Optional[int] = None
    for row in rows:
        if row["embedding"] is None or row["dim"] is None:
            continue
        dim = int(row["dim"])
        if dim <= 0:
            continue
        try:
            vec = unpack_embedding(cast(bytes, row["embedding"]), dim)
        except Exception:
            continue
        if expected_dim is None:
            expected_dim = int(vec.size)
        if int(vec.size) != expected_dim:
            continue
        vectors.append(np.asarray(vec, dtype=np.float32))

    if not vectors:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM person_prototypes WHERE person_id=? AND COALESCE(NULLIF(model_id, ''), 'default')=?",
                (int(person_id), target_model_id),
            )
            conn.execute("DELETE FROM person_embeddings WHERE person_id=?", (int(person_id),))
            conn.commit()
        return

    matrix = np.stack(vectors, axis=0).astype(np.float32, copy=False)
    mean_vec = np.mean(matrix, axis=0, dtype=np.float32).astype(np.float32, copy=False)
    upsert_person_prototype(
        int(person_id),
        cast(list[float], mean_vec.tolist()),
        target_model_id,
        sample_count=int(matrix.shape[0]),
    )


def recompute_all_person_prototypes(model_id: str = DEFAULT_MODEL_ID) -> None:
    for person_id in list_people_ids():
        recompute_person_prototype(int(person_id), model_id=str(model_id))


def list_person_embeddings() -> List[Tuple[int, np.ndarray]]:
    out: List[Tuple[int, np.ndarray]] = []
    for pid, vec in list_person_prototypes("default"):
        out.append((int(pid), _normalize(vec)))
    return out
