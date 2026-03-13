from __future__ import annotations

import sqlite3
from pathlib import Path

from db import DB_PATH, init_db


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _print_schema_status(conn: sqlite3.Connection) -> None:
    required_tables = ["photos", "faces", "face_embeddings", "person_embeddings"]
    for table in required_tables:
        print(f"table {table}: {'ok' if _table_exists(conn, table) else 'missing'}")

    if _table_exists(conn, "face_embeddings"):
        cols = conn.execute("PRAGMA table_info(face_embeddings)").fetchall()
        print("face_embeddings cols:", [c[1] for c in cols])

    if _table_exists(conn, "person_embeddings"):
        cols = conn.execute("PRAGMA table_info(person_embeddings)").fetchall()
        print("person_embeddings cols:", [c[1] for c in cols])

    faces_idx = conn.execute("PRAGMA index_list(faces)").fetchall()
    print("faces indexes:", [r[1] for r in faces_idx])

    face_emb_idx = conn.execute("PRAGMA index_list(face_embeddings)").fetchall()
    print("face_embeddings indexes:", [r[1] for r in face_emb_idx])

    person_emb_idx = conn.execute("PRAGMA index_list(person_embeddings)").fetchall()
    print("person_embeddings indexes:", [r[1] for r in person_emb_idx])


def main() -> int:
    db_file = Path(DB_PATH)
    if not db_file.exists():
        print(f"Database not found at {db_file.resolve()}. It will be created.")

    init_db()

    with sqlite3.connect(db_file) as conn:
        _print_schema_status(conn)

    print("Migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
