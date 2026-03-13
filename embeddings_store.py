from __future__ import annotations

from array import array
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from db import get_connection

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def serialize_embedding(vec: Sequence[float]) -> tuple[bytes, int]:
    values = [float(v) for v in vec]
    if not values:
        raise ValueError("Embedding vector must not be empty")

    if np is not None:
        arr = np.asarray(values, dtype=np.float32).reshape(-1)
        return arr.tobytes(), int(arr.size)

    buf = array("f", values)
    return buf.tobytes(), int(len(buf))


def deserialize_embedding(blob: bytes, dim: int) -> list[float]:
    n = int(dim)
    if n <= 0:
        raise ValueError("dim must be > 0")

    if np is not None:
        arr = np.frombuffer(blob, dtype=np.float32, count=n)
        if int(arr.size) != n:
            raise ValueError(f"Embedding blob mismatch: expected {n}, got {arr.size}")
        return [float(x) for x in arr.tolist()]

    buf = array("f")
    buf.frombytes(blob)
    if len(buf) != n:
        raise ValueError(f"Embedding blob mismatch: expected {n}, got {len(buf)}")
    return [float(x) for x in buf]


def upsert_face_embedding(face_id: int, model_id: str, embedding: Sequence[float]) -> None:
    blob, dim = serialize_embedding(embedding)
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
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
                (int(face_id), str(model_id), blob, int(dim), _now_iso_utc()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_face_embedding(face_id: int, model_id: str) -> Optional[list[float]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT embedding, dim
            FROM face_embeddings
            WHERE face_id=? AND model_id=?
            LIMIT 1
            """,
            (int(face_id), str(model_id)),
        ).fetchone()
        if row is None:
            return None
        blob = row["embedding"]
        dim = row["dim"]
        if blob is None or dim is None:
            return None
        return deserialize_embedding(bytes(blob), int(dim))


def delete_face_embedding(face_id: int, model_id: str) -> None:
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM face_embeddings WHERE face_id=? AND model_id=?",
                (int(face_id), str(model_id)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def upsert_person_prototype(person_id: int, model_id: str, embedding: Sequence[float], sample_count: int) -> None:
    blob, dim = serialize_embedding(embedding)
    count = max(0, int(sample_count))
    with get_connection() as conn:
        try:
            conn.execute("BEGIN")
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
                (int(person_id), str(model_id), blob, int(dim), count, _now_iso_utc()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_person_prototype(person_id: int, model_id: str) -> Optional[Tuple[list[float], int]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT embedding, dim, sample_count
            FROM person_prototypes
            WHERE person_id=? AND model_id=?
            LIMIT 1
            """,
            (int(person_id), str(model_id)),
        ).fetchone()
        if row is None:
            return None
        blob = row["embedding"]
        dim = row["dim"]
        sample_count = row["sample_count"]
        if blob is None or dim is None or sample_count is None:
            return None
        vec = deserialize_embedding(bytes(blob), int(dim))
        return (vec, int(sample_count))
