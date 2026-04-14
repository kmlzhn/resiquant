"""File-based SHA256 cache to avoid duplicate LLM calls."""
from __future__ import annotations
import hashlib
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def compute_hash(files_content: list[bytes]) -> str:
    """Order-independent hash: SHA256 each file, sort the digests, hash the sorted list."""
    digests = sorted(hashlib.sha256(c).hexdigest() for c in files_content)
    h = hashlib.sha256()
    for d in digests:
        h.update(d.encode())
    return h.hexdigest()


def get(source_hash: str) -> dict | None:
    path = _CACHE_DIR / f"{source_hash}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("cache_corrupt key=%s (%s) — deleting", source_hash[:12], e)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def put(source_hash: str, result: dict) -> None:
    path = _CACHE_DIR / f"{source_hash}.json"
    try:
        path.write_text(json.dumps(result, indent=2))
    except OSError as e:
        logger.warning("cache_write_error key=%s: %s", source_hash[:12], e)
