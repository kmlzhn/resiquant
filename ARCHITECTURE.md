# Architecture — ResiQuant Submission Extractor

## Overview

A FastAPI service that accepts insurance submission emails and attachments, extracts five structured fields using an LLM, validates the output, caches results, and tracks cost/latency.

---

## Request Flow

```
POST /extract (multipart files)
        │
        ▼
   app/parser.py          — PDF / XLSX / DOCX → plain text per page/sheet
        │
        ▼
   app/cache.py           — SHA256(all file bytes) → lookup cache/
        │ miss
        ▼
   app/extractor.py       — build_user_prompt(docs) with FEW_SHOT examples
        │
        ▼
   app/llm.py             — call Perplexity (OpenAI-compatible) → raw JSON string
        │
        ▼
   app/validators.py      — broker_email format, address street+city+state check
        │
        ▼
   app/cache.py           — write result to cache/ if no provider errors
        │
        ▼
   app/metrics.py         — record tokens, latency, cache hit, errors
        │
        ▼
   ExtractionResult JSON  — 5 fields + confidence + provenance + token usage
```

---

## Prompting Strategy

**System prompt** instructs the model to:
- Extract only from provided text (no hallucination)
- Identify the **original** broker (not the forwarding intermediary)
- Return strict JSON matching the output schema
- Set `value: null` and `confidence: 0.0` when a field is absent

**Few-shot examples** (2 examples in `extractor.py`):
- Example 1: `sub_2` — Emily Gooding / Brown & Riding
- Example 2: `sub_56` — Christopher Romero / RT Specialty

Each example shows the exact input format (document blocks) and expected JSON output, teaching the model the provenance format and confidence scale.

**Token budget:** Each document page is capped at 4,000 characters. With 5 files averaging 3 pages each, worst-case input is ~60k characters (~15k tokens). `sonar-pro` context window is 200k tokens.

---

## Validation

| Field | Rule |
|---|---|
| `broker_email` | Must match `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$` |
| `complete_brokerage_address` | Must contain a street number + US state abbreviation |

Validation errors are returned in the `errors[]` array alongside the result rather than rejecting the response — the LLM output is still surfaced for human review.

---

## Caching

- Key: SHA256 of all uploaded file bytes concatenated
- Store: `cache/<hash>.json` on disk
- Policy: written on successful LLM extraction; read before every LLM call
- Assumption: identical bytes = identical submission. If a broker resends with minor edits, the hash changes and a new LLM call is made. This is intentional — we prefer accuracy over aggressive cache reuse.

---

## Cost & Latency

Tracked per request in `app/metrics.py` (in-memory, resets on restart):
- `total_tokens_used` — sum of `prompt_tokens + completion_tokens`
- `avg_latency_ms` — rolling average
- `errors_by_type` — `provider_error`, `validation_error`

Exposed at `GET /metrics`.

**Perplexity `sonar-pro` pricing (April 2026):** ~$3/M input tokens, ~$15/M output tokens.
A typical submission (~15k input + ~0.5k output tokens) costs ≈ $0.05/call.

---

## Provider Abstraction

Set `LLM_PROVIDER` in `.env`:
- `perplexity` — uses `PERPLEXITY_API_KEY`, OpenAI-SDK-compatible endpoint
- `openai` — uses `OPENAI_API_KEY`
- `mock` — returns hardcoded fixture, no network call (for CI / unit tests)

---

## Tradeoffs & Assumptions

| Decision | Tradeoff |
|---|---|
| File-based cache (not Redis) | Simple, zero dependencies; not suitable for multi-replica deploy |
| pdfplumber for PDFs | Good text extraction; fails on fully scanned/image PDFs (would need OCR) |
| Single LLM call per submission | Simple and fast; a two-pass approach (email first, then attachments) could improve accuracy on large SOV files |
| In-memory metrics | Zero ops overhead; lost on restart — use Prometheus in production |
| Perplexity `sonar-pro` | Strong instruction-following; if citations/web search are not needed, `gpt-4o` may be cheaper |
| 4k char cap per page | Prevents token blowup on large SOVs; assumption: broker info is always in the first pages |
