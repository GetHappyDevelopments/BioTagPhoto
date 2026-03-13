from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterator, Optional

import numpy as np

from db import (
    get_connection,
    list_excluded_images,
    normalize_image_path,
    pack_embedding,
)
from face_engine import FaceEngine


def _iter_image_files(folder: str) -> Iterator[Path]:
    exts = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    for root, _, files in os.walk(folder):
        for name in files:
            p = Path(root) / name
            if p.suffix.lower() in exts:
                yield p


def count_image_files(folder: str) -> int:
    excluded = {normalize_image_path(path) for path in list_excluded_images()}
    count = 0
    for p in _iter_image_files(str(folder)):
        if normalize_image_path(str(p)) in excluded:
            continue
        count += 1
    return int(count)


def _upsert_face_embedding_with_conn(conn, face_id: int, emb: np.ndarray) -> None:
    blob, dim = pack_embedding(np.asarray(emb, dtype=np.float32))
    conn.execute(
        """
        INSERT INTO face_embeddings(face_id, model_id, embedding, dim, created_at)
        VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT(face_id) DO UPDATE SET
            model_id=excluded.model_id,
            embedding=excluded.embedding,
            dim=excluded.dim,
            created_at=excluded.created_at
        """,
        (int(face_id), "default", blob, int(dim)),
    )


def ingest_folder(folder: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> None:
    engine = FaceEngine()
    excluded = {normalize_image_path(path) for path in list_excluded_images()}
    files = [
        p for p in _iter_image_files(folder)
        if normalize_image_path(str(p)) not in excluded
    ]
    total = int(len(files))
    if progress_callback is not None:
        progress_callback(0, total)

    with get_connection() as conn:
        cur = conn.cursor()

        for idx, img_path in enumerate(files, start=1):
            path = str(img_path.resolve())

            row = cur.execute("SELECT id FROM photos WHERE path=?", (path,)).fetchone()
            if row is not None:
                # Already analyzed: keep existing DB rows untouched to avoid churn/inconsistency.
                if progress_callback is not None:
                    progress_callback(int(idx), total)
                print(f"Skipped (already analyzed): {path}")
                continue

            cur.execute("INSERT INTO photos(path) VALUES(?)", (path,))
            photo_id = int(cur.lastrowid)

            faces = engine.detect_faces(path)
            for face in faces:
                x, y, w, h = face["bbox"]
                cur.execute(
                    "INSERT INTO faces(photo_id, x, y, w, h, person_id) VALUES(?, ?, ?, ?, ?, NULL)",
                    (photo_id, int(x), int(y), int(w), int(h)),
                )
                face_id = int(cur.lastrowid)

                emb = face.get("embedding")
                if emb is not None:
                    _upsert_face_embedding_with_conn(conn, face_id, np.asarray(emb, dtype=np.float32))

            conn.commit()
            print(f"Imported: {path} (faces={len(faces)})")
            if progress_callback is not None:
                progress_callback(int(idx), total)

    return None
