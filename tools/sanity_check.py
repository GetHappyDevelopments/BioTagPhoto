from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from embeddings import rebuild_all_face_embeddings, rebuild_all_person_prototypes
from db import get_connection, init_db, list_unknown_faces, suggest_people_for_face


def _resolve_people_table(conn) -> str:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name IN ('persons', 'people')
        ORDER BY CASE name WHEN 'persons' THEN 0 ELSE 1 END
        LIMIT 1
        """
    ).fetchone()
    if row is None or row[0] is None:
        return "people"
    return str(row[0])


def _counts() -> Dict[str, int]:
    with get_connection() as conn:
        people_table = _resolve_people_table(conn)

        persons = int(conn.execute(f"SELECT COUNT(*) FROM {people_table}").fetchone()[0])
        faces = int(conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0])
        unknown_faces = int(conn.execute("SELECT COUNT(*) FROM faces WHERE person_id IS NULL").fetchone()[0])
        face_embeddings = int(conn.execute("SELECT COUNT(*) FROM face_embeddings").fetchone()[0])
        person_prototypes = int(conn.execute("SELECT COUNT(*) FROM person_prototypes").fetchone()[0])

    return {
        "persons": persons,
        "faces": faces,
        "unknown_faces": unknown_faces,
        "face_embeddings": face_embeddings,
        "person_prototypes": person_prototypes,
    }


def _person_name_map() -> Dict[int, str]:
    with get_connection() as conn:
        people_table = _resolve_people_table(conn)
        rows = conn.execute(f"SELECT id, name FROM {people_table}").fetchall()
    out: Dict[int, str] = {}
    for row in rows:
        if row[0] is None:
            continue
        out[int(row[0])] = str(row[1]) if row[1] is not None else f"Person {int(row[0])}"
    return out


def _print_counts(title: str) -> None:
    c = _counts()
    print(f"\n{title}")
    print(f"persons: {c['persons']}")
    print(f"faces: {c['faces']}")
    print(f"unknown faces: {c['unknown_faces']}")
    print(f"face_embeddings: {c['face_embeddings']}")
    print(f"person_prototypes: {c['person_prototypes']}")


def _print_sample_suggestions() -> None:
    unknown = list_unknown_faces()
    if not unknown:
        print("\nNo unknown faces found. Skipping suggestion sample.")
        return

    sample_size = min(3, len(unknown))
    sample_faces: List[Tuple[int, str, int, int, int, int]] = random.sample(unknown, sample_size)
    name_map = _person_name_map()

    print(f"\nTop 5 suggestions for {sample_size} random unknown faces:")
    for face_id, path, *_ in sample_faces:
        suggestions = suggest_people_for_face(int(face_id), top_k=5, model="default")
        print(f"\nface_id={face_id} file={path}")
        if not suggestions:
            print("  (no suggestions)")
            continue
        for rank, (person_id, score) in enumerate(suggestions, start=1):
            person_name = name_map.get(int(person_id), f"Person {int(person_id)}")
            print(f"  {rank}. {person_name} (id={person_id}) score={score:.4f}")


def main() -> int:
    init_db()

    _print_counts("Before rebuild")

    print("\nRebuilding face embeddings...")
    rebuild_all_face_embeddings(model="default")

    print("Rebuilding person prototypes...")
    rebuild_all_person_prototypes(model="default")

    _print_counts("After rebuild")
    _print_sample_suggestions()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
