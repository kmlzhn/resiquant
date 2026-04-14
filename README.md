# ResiQuant Submission Extractor

A FastAPI service that accepts insurance submission emails and attachments, then extracts structured broker and property data using an LLM (Perplexity `sonar-pro`).

---

## What it extracts

| Field | Description |
|---|---|
| `broker_name` | Original broker's full name |
| `broker_email` | Broker's email address |
| `brokerage` | Brokerage company name |
| `complete_brokerage_address` | Full office address of the brokerage |
| `property_addresses` | All insured property addresses found in attachments |

Every field includes `confidence` (0.0–1.0) and `provenance` (document name, page, verbatim snippet).

---

## Quick start

### Option 1 — Docker (recommended)

```bash
cp .env.example .env
# Edit .env and add your PERPLEXITY_API_KEY
docker compose up --build
```

Service is live at **http://localhost:8000**

### Option 2 — Local dev

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env
# Edit .env and add your PERPLEXITY_API_KEY
make dev
```

Service is live at **http://localhost:8000**

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `PERPLEXITY_API_KEY` | **Yes** | — | API key from [perplexity.ai](https://www.perplexity.ai) |
| `PERPLEXITY_MODEL` | No | `sonar-pro` | Perplexity model name |
| `LLM_TIMEOUT_SECONDS` | No | `30` | Per-request LLM timeout |
| `CACHE_DIR` | No | `cache/` | Directory for cached extraction results |

---

## API

### Upload & extract — `POST /extract`

Upload one submission's files (email PDF + attachments):

```bash
curl -X POST http://localhost:8000/extract \
  -F "files=@email.pdf" \
  -F "files=@schedule_of_values.xlsx"
```

**Response:**

```json
{
  "request_id": "3f2a...",
  "cache_hit": false,
  "broker_name": {
    "value": "Emily Gooding",
    "confidence": 0.97,
    "provenance": {
      "doc_name": "email.pdf",
      "page": 1,
      "snippet": "Emily Gooding | Associate Broker, Property"
    }
  },
  "broker_email": { "value": "egooding@brcins.com", "confidence": 0.99, "provenance": {...} },
  "brokerage": { "value": "Brown & Riding", "confidence": 0.97, "provenance": {...} },
  "complete_brokerage_address": { "value": "600 University St, Suite 3000, Seattle, WA 98101", "confidence": 0.95, "provenance": {...} },
  "property_addresses": [
    { "address": "7924 212th St SW, Edmonds, WA 98026", "confidence": 0.95, "provenance": {...} }
  ],
  "latency_ms": 2341.5,
  "token_usage": { "prompt_tokens": 14200, "completion_tokens": 480, "total_tokens": 14680, "estimated_cost_usd": 0.0499 },
  "errors": []
}
```

### Batch extract — `POST /batch-extract`

Upload multiple submissions at once. Supports:
- **ZIP mode:** one `.zip` per submission
- **Mixed mode:** all files together — the service detects which PDF is the email and groups accordingly

### Metrics — `GET /metrics`

```bash
curl http://localhost:8000/metrics
```

Returns token usage, cost, latency, cache hit rate, and error counts.  
Visiting `/metrics` in a browser shows a formatted dashboard.

### Interactive docs — `GET /docs`

FastAPI auto-generated Swagger UI at **http://localhost:8000/docs**

Full OpenAPI spec also available at `OPENAPI.yaml`.

---

## Web UI

Visit **http://localhost:8000** to use the drag-and-drop interface. Upload files and view extracted JSON with a card view or raw JSON toggle.

---

## Running tests

```bash
make test
```

Integration tests (`test_sub2_*`, `test_sub5_*`, etc.) run against the real Perplexity API. Results are cached, so re-runs after the first are free.

To point tests at your local copy of the sample submissions:

```bash
SUBMISSION_DATA_DIR=/path/to/submission_files make test
```

Unit-only tests (no API calls):

```bash
python3 -m pytest tests/ -v -k "cache or validator or parser"
```

---

## Project structure

```
app/
  main.py         — FastAPI app, /extract, /batch-extract, /metrics, /health
  extractor.py    — Core extraction logic: prompt building, LLM call, validation
  llm.py          — Perplexity API client (OpenAI-SDK-compatible)
  parser.py       — PDF / XLSX / DOCX → plain text
  cache.py        — SHA256 file-based cache
  validators.py   — Email format + address structure validation
  metrics.py      — In-memory token/cost/latency counters
  models.py       — Pydantic response schemas
static/
  index.html      — Single-page drag-and-drop UI
tests/
  test_extraction.py  — Integration + unit tests
ARCHITECTURE.md   — System design, prompts, caching, tradeoffs
RUNBOOK.md        — Key rotation, prompt tuning, debugging
prompts.md        — Full prompt text and design decisions
OPENAPI.yaml      — OpenAPI 3.1 spec
```

---

## Key design decisions

- **LLM:** Perplexity `sonar-pro` via the OpenAI-compatible SDK — swap provider by changing env vars in `llm.py`
- **Caching:** SHA256 of file bytes → `cache/<hash>.json`; identical uploads never hit the API twice
- **Provenance:** The prompt requires the model to cite the exact document, page, and snippet for every extracted value
- **Validation:** Pydantic schema validation + email regex + address structure check run on every LLM response
- **Cost:** ~$0.05/submission at current Perplexity pricing; tracked at `/metrics`

See `ARCHITECTURE.md` for full details.
