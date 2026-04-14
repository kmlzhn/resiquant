# DESIGN.md — AI Usage Summary

## How AI helped

Claude (claude-sonnet-4-6) was used throughout this project via Claude Code (interactive CLI).

### Scaffolding & architecture
- Reviewed the questionnaire requirements and proposed the full project structure before writing any code
- Suggested the Perplexity API as an OpenAI-compatible provider, simplifying provider abstraction

### Reading sample data
- Extracted and read all 5 sample submission PDFs using pdfplumber to understand the actual email format
- Read the manual extraction XLSX files to understand expected output schema
- Used this real data to build accurate few-shot examples in the prompt

### Code generation
- Generated all core modules (`parser.py`, `llm.py`, `cache.py`, `validators.py`, `extractor.py`, `metrics.py`, `main.py`)
- Built the full test suite with ground-truth assertions derived from the real sample data
- Generated the UI (`static/index.html`) with drag-and-drop upload and visual/JSON tabs

### Documentation
- Wrote `ARCHITECTURE.md`, `RUNBOOK.md`, `DESIGN.md`, `prompts.md`, `OPENAPI.yaml`

---

## How outputs were validated

| Component | Validation method |
|---|---|
| Parser | Manually verified extracted text matched expected email content from sample PDFs |
| Few-shot examples | Compared LLM-suggested values against manually inspected broker signatures |
| Validators | Unit tests: email regex, address structure checks |
| End-to-end | Integration tests assert correct broker name/email/brokerage for sub_2, sub_5, sub_19, sub_56 |
| Caching | Unit test verifies roundtrip put/get with temp directory |

---

## What was written by hand vs AI-assisted

| File | Human | AI |
|---|---|---|
| Few-shot examples in `extractor.py` | Reviewed & corrected | Drafted |
| Ground-truth values in tests | Verified against PDFs | Drafted |
| `.env` / secrets | Provided API key | Scaffolded template |
| All other code | Reviewed | Generated |
