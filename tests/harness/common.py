"""Small helpers shared by the harness modules (standard library only)."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def entry_path(entry: dict, root: Path = ROOT) -> Path:
    """Absolute path of a manifest entry's EPUB (manifest paths are relative to the repo root)."""
    p = Path(entry["path"])
    return p if p.is_absolute() else Path(root) / p


def default_timeout(entry: dict) -> int:
    """Per-conversion timeout: 120 s below 2 MB, 300 s otherwise."""
    return 120 if (entry.get("size_bytes") or 0) < 2 * 1024 * 1024 else 300


def write_json_atomic(path: Path, obj) -> None:
    """Write JSON (UTF-8) via a temp file + rename, so readers never see a half-written file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def select_entries(entries: list[dict], ids: str | None) -> list[dict]:
    """Filter manifest entries by a comma-separated list of ids or fnmatch globs (None/'' = all)."""
    if not ids:
        return entries
    pats = [p.strip() for p in ids.split(",") if p.strip()]
    return [e for e in entries if any(fnmatch.fnmatchcase(e["id"], p) or e["id"] == p for p in pats)]
