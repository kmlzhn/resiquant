"""In-memory metrics store (resets on restart)."""
from __future__ import annotations
from threading import Lock

_lock = Lock()
_state: dict = {
    "total_requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_tokens": 0,
    "total_latency_ms": 0.0,
    "errors_by_type": {},
}


def record(*, cache_hit: bool, tokens: int, latency_ms: float, errors: list[str]) -> None:
    with _lock:
        _state["total_requests"] += 1
        if cache_hit:
            _state["cache_hits"] += 1
        else:
            _state["cache_misses"] += 1
        _state["total_tokens"] += tokens
        _state["total_latency_ms"] += latency_ms
        for err in errors:
            etype = err.split(":")[0]
            _state["errors_by_type"][etype] = _state["errors_by_type"].get(etype, 0) + 1


def snapshot() -> dict:
    with _lock:
        n = _state["total_requests"]
        return {
            "total_requests": n,
            "cache_hits": _state["cache_hits"],
            "cache_misses": _state["cache_misses"],
            "total_tokens_used": _state["total_tokens"],
            "total_latency_ms": round(_state["total_latency_ms"], 2),
            "avg_latency_ms": round(_state["total_latency_ms"] / n, 2) if n > 0 else 0.0,
            "errors_by_type": dict(_state["errors_by_type"]),
        }
