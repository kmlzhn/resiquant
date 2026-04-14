# Runbook — ResiQuant Submission Extractor

## Starting the service

```bash
# Local dev
make install
make dev
# → http://localhost:8000

# Docker
make docker-up
# → http://localhost:8000
```

---

## Rotating API keys

1. Generate a new key at [perplexity.ai](https://perplexity.ai) → API → Keys
2. Update `.env`:
   ```
   PERPLEXITY_API_KEY=pplx-<new-key>
   ```
3. Restart the service (`make dev` or `docker compose restart`)
4. The old key can be revoked from the Perplexity dashboard immediately after restart
5. **Never commit `.env` to git** — it is in `.gitignore`

---

## Tuning prompts

Prompts live in `app/extractor.py`:
- `SYSTEM_PROMPT` — rules and output schema
- `FEW_SHOT` — 2 examples with input/output pairs

**When to update:**
- Model returns wrong broker (e.g. picks the forwarding intermediary instead of original sender) → strengthen the rule in `SYSTEM_PROMPT`
- Addresses are incomplete → add a new few-shot example showing a complete address
- New document format appears → add it as a third few-shot example

**Process:**
1. Edit `extractor.py`
2. Clear the relevant cache entry (or wipe `cache/` entirely) so the new prompt is used
3. Re-run tests: `make test`
4. Verify output manually on the affected submission

---

## Debugging bad parses

### Step 1 — Identify what text the parser sees
```python
from app.parser import parse_file
doc = parse_file("path/to/file.pdf")
print(doc.full_text)
```

### Step 2 — Check the raw LLM response
Add a temporary `print(llm_resp.content)` in `extractor.py` after `call_llm(...)`.

### Step 3 — Check for JSON parse failures
If `extract_json_from_response` raises, the LLM returned non-JSON.
Fix: tighten the system prompt or switch to a model with better JSON compliance.

### Step 4 — Inspect the cache
Cache files are in `cache/<sha256>.json`. Delete a file to force a fresh LLM call.
```bash
rm cache/<hash>.json
```

### Step 5 — Check metrics
```bash
curl http://localhost:8000/metrics
```
Look at `errors_by_type` for `provider_error` or `validation_error` counts.

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `provider_error: 401` | Invalid or expired API key | Rotate key (see above) |
| `provider_error: 429` | Rate limit exceeded | Reduce concurrent requests or upgrade plan |
| `provider_error: timeout` | LLM took too long | Retry; reduce per-page char limit in `extractor.py` |
| `validation_error: broker_email` | LLM returned malformed email | Add example to few-shot with correct email format |
| `validation_error: address` | Address missing state | Add example showing full address with state |
| PDF returns empty text | Scanned / image-only PDF | Integrate OCR (pytesseract + pdf2image) |

---

## Clearing the cache

```bash
rm -rf cache/*.json
```

---

## Running tests

```bash
# All tests — integration tests use real Perplexity API (cached, so re-runs are free)
make test

# Unit tests only (no API calls at all)
python3 -m pytest tests/ -v -k "cache or validator or parser"
```
