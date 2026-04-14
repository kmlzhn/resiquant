"""File-based SHA256 cache to avoid duplicate LLM calls."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))


def _ensure_dir() -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def compute_hash(files_content: list[bytes]) -> str:
    """SHA256 over all file bytes concatenated."""
    h = hashlib.sha256()
    for content in files_content:
        h.update(content)
    return h.hexdigest()


def get(source_hash: str) -> dict | None:
    path = _ensure_dir() / f"{source_hash}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def put(source_hash: str, result: dict) -> None:
    path = _ensure_dir() / f"{source_hash}.json"
    path.write_text(json.dumps(result, indent=2))
