# Architecture — ResiQuant Submission Extractor

## Overview

A FastAPI service that accepts insurance submission emails and attachments, extracts five structured fields using an LLM, validates the output, caches results, and tracks cost/latency.

---

## Request Flow

```
POST /batch-extract (multipart files)
        │
        ▼
   app/main.py             — detect ZIPs or group files by email detection
        │
        ▼
   app/parser.py           — PDF / XLSX / DOCX → plain text, labelled by page
        │
        ▼
   app/cache.py            — SHA256(all file bytes) → lookup cache/
        │ miss
        ▼
   app/extractor.py        — build_user_prompt(docs) with FEW_SHOT examples
        │
        ▼
   app/llm.py              — call Perplexity sonar-pro → raw JSON string
        │
        ▼
   app/validators.py       — broker_email format, address street+city+state check
        │
        ▼
   app/cache.py            — write result if no provider errors
        │
        ▼
   app/metrics.py          — record tokens, cost, latency, cache hit, errors
        │
        ▼
   ExtractionResult JSON   — 5 fields + confidence + provenance + token usage + cost
```

---

## Prompting Strategy

**System prompt** instructs the model to:
- Extract only from provided text (no hallucination)
- Identify the **original** broker (not the forwarding intermediary)
- Return strict JSON matching the output schema
- Set `value: null` and `confidence: 0.0` when a field is absent

**Few-shot examples** (2 real examples in `app/extractor.py`):
- Example 1: `sub_2` — Emily Gooding / Brown & Riding
- Example 2: `sub_56` — Christopher Romero / RT Specialty

Each example shows the exact input format (document blocks with `[Page N]` labels) and expected JSON output, teaching the model the provenance format and confidence scale.

**Token budget:** Each document page is capped at **6,000 characters**. With 5 files averaging 3 pages each, worst-case input is ~90k characters (~22k tokens). `sonar-pro` context window is 200k tokens.

---

## Validation

| Field | Rule |
|---|---|
| `broker_email` | Must match `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$` |
| `complete_brokerage_address` | Must contain a street number, a city segment (comma-separated), and a US state abbreviation |

Validation errors are returned in the `errors[]` array alongside the result — the LLM output is still surfaced for human review rather than rejected.

---

## Caching

- **Key:** SHA256 of all uploaded file bytes concatenated
- **Store:** `cache/<hash>.json` on disk
- **Policy:** Written on successful LLM extraction; read before every LLM call
- **Assumption:** identical bytes = identical submission. If a broker resends with minor edits, the hash changes and a new LLM call is made — accuracy over aggressive reuse.

---

## Cost & Latency

Tracked per request in `app/metrics.py` (in-memory, resets on restart).  
Exposed at `GET /metrics` — returns JSON for API clients, HTML dashboard for browsers.

| Metric | Description |
|---|---|
| `total_cost_usd` | Running sum of estimated LLM cost |
| `avg_cost_per_request_usd` | Cost averaged over LLM calls (cache hits excluded) |
| `avg_latency_ms` | Rolling average end-to-end latency |
| `cache_hit_rate` | Fraction of requests served from cache |
| `errors_by_type` | Counts of `provider_error`, `validation_error`, `timeout` |
| `error_rate` | Fraction of requests with at least one error |

**Perplexity `sonar-pro` pricing (April 2026):** $3/M input tokens, $15/M output tokens.  
A typical submission (~15k prompt + ~0.5k completion tokens) costs ≈ **$0.05/call**.

---

## LLM Provider

**Assumption:** The questionnaire lists OpenAI/Anthropic/mock as example providers. We chose **Perplexity `sonar-pro`** because:
1. It is OpenAI-SDK-compatible (`base_url="https://api.perplexity.ai"`), keeping the integration simple
2. Strong instruction-following and JSON compliance for structured extraction tasks
3. Competitive cost vs GPT-4o for long-context document inputs

The `app/llm.py` module is the single integration point. Swapping providers requires only changing `_MODEL` and `_API_KEY` — the rest of the stack is provider-agnostic.

---

## Tradeoffs & Assumptions

| Decision | Tradeoff |
|---|---|
| File-based cache (not Redis) | Simple, zero dependencies; not suitable for multi-replica deploy |
| pdfplumber for PDFs | Good text extraction; fails on fully scanned/image PDFs (would need OCR) |
| Single LLM call per submission | Simple and fast; a two-pass approach (email first, then attachments) could improve accuracy on large SOV files |
| In-memory metrics | Zero ops overhead; lost on restart — use Prometheus in production |
| 6k char cap per page | Prevents token blowup on large SOVs; raised from 4k to capture broker signatures in long forwarded email chains |
| Auto email-grouping | Enables flat upload UX; heuristic (`From:` + `To:/Subject:` in first 500 chars) may misfire on non-standard PDFs |