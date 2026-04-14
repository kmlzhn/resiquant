"""In-memory metrics store (resets on restart)."""
from __future__ import annotations
from threading import Lock

_lock = Lock()
_state: dict = {
    "total_requests": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "total_tokens": 0,
    "total_prompt_tokens": 0,
    "total_completion_tokens": 0,
    "total_cost_usd": 0.0,
    "total_latency_ms": 0.0,
    "errors_by_type": {},
}


def record(
    *,
    cache_hit: bool,
    tokens: int,
    latency_ms: float,
    errors: list[str],
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    with _lock:
        _state["total_requests"] += 1
        if cache_hit:
            _state["cache_hits"] += 1
        else:
            _state["cache_misses"] += 1
        _state["total_tokens"] += tokens
        _state["total_prompt_tokens"] += prompt_tokens
        _state["total_completion_tokens"] += completion_tokens
        _state["total_cost_usd"] += cost_usd
        _state["total_latency_ms"] += latency_ms
        for err in errors:
            etype = err.split(":")[0].strip()
            _state["errors_by_type"][etype] = _state["errors_by_type"].get(etype, 0) + 1


def snapshot() -> dict:
    with _lock:
        n = _state["total_requests"]
        hits = _state["cache_hits"]
        return {
            "total_requests": n,
            "cache_hits": hits,
            "cache_misses": _state["cache_misses"],
            "cache_hit_rate": round(hits / n, 4) if n > 0 else 0.0,
            "total_tokens_used": _state["total_tokens"],
            "total_prompt_tokens": _state["total_prompt_tokens"],
            "total_completion_tokens": _state["total_completion_tokens"],
            "total_cost_usd": round(_state["total_cost_usd"], 6),
            "avg_cost_per_request_usd": round(_state["total_cost_usd"] / max(n - hits, 1), 6),
            "total_latency_ms": round(_state["total_latency_ms"], 2),
            "avg_latency_ms": round(_state["total_latency_ms"] / n, 2) if n > 0 else 0.0,
            "errors_by_type": dict(_state["errors_by_type"]),
            "error_rate": round(sum(_state["errors_by_type"].values()) / n, 4) if n > 0 else 0.0,
        }
