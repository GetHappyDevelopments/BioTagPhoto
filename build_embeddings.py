from __future__ import annotations

import sys
from typing import Iterable, Tuple, Optional

import numpy as np

from db import (
    init_db,
    iter_faces_for_embedding,
    face_embedding_exists,
    upsert_face_embedding,
    recompute_person_prototype,
    list_people_ids,
)

from face_embedder import FaceEmbedder, FaceRect


def main() -> int:
    init_db()

    # CPU by default (ctx_id=-1). If you installed onnxruntime-gpu, use ctx_id=0.
    embedder = FaceEmbedder(models_dir="models", model_name="buffalo_l", ctx_id=-1)

    total = 0
    done = 0
    skipped = 0
    failed = 0

    print("Scanning faces...")
    faces = list(iter_faces_for_embedding())
    total = len(faces)
    print(f"Found {total} faces in DB.")

    for face_id, path, x, y, w, h, person_id in faces:
        if face_embedding_exists(face_id):
            skipped += 1
            continue

        emb = embedder.embed_from_face_rect(path, FaceRect(x=x, y=y, w=w, h=h))
        if emb is None:
            failed += 1
            continue

        upsert_face_embedding(face_id, emb)
        done += 1

        if done % 50 == 0:
            print(f"Embedded {done} faces (skipped {skipped}, failed {failed})...")

    print(f"\nEmbedding done. ok={done}, skipped={skipped}, failed={failed}, total={total}")

    # Recompute prototypes for all people
    print("\nRecomputing person prototypes...")
    for pid in list_people_ids():
        recompute_person_prototype(pid)

    print("Prototypes updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
