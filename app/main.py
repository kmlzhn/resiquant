"""FastAPI application: /extract, /batch-extract, /metrics, /health."""
from __future__ import annotations
import hashlib
import html
import io
import logging
import sys
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import metrics as metrics_store
from app.extractor import extract
from app.models import BatchExtractionResult, ExtractionResult, FieldResult, MetricsResponse
from app.parser import parse_file

# ---------------------------------------------------------------------------
# Structured logging — never log raw email addresses, hash them instead
# ---------------------------------------------------------------------------
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ResiQuant Submission Extractor",
    description="Extracts broker & property data from insurance submission emails.",
    version="1.0.0",
)

# Serve static UI
_static = Path(__file__).parent.parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

ALLOWED_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".docx"}
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per file


def _check_size(filename: str, content: bytes) -> None:
    """Raise HTTP 413 if content exceeds MAX_FILE_BYTES."""
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File '{filename}' is {len(content) // (1024*1024)} MB — limit is 50 MB.",
        )


def _read_files(uploads: list[UploadFile], contents: list[bytes]) -> tuple[list, list[bytes]]:
    """Parse uploaded files into (docs, bytes_list), skipping unsupported extensions."""
    parsed_docs, files_bytes = [], []
    for upload, content in zip(uploads, contents):
        if not content:
            continue
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            logger.warning(
                "skipped_unsupported_file name_hash=%s ext=%s",
                hashlib.sha256((upload.filename or "").encode()).hexdigest()[:12],
                ext,
            )
            continue
        files_bytes.append(content)
        doc = parse_file(upload.filename or "unknown", content)
        parsed_docs.append(doc)
        logger.info(
            "received_file name_hash=%s size=%d",
            hashlib.sha256((upload.filename or "").encode()).hexdigest()[:12],
            len(content),
        )
    return parsed_docs, files_bytes


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root():
    html_file = _static / "index.html"
    if html_file.exists():
        return HTMLResponse(html_file.read_text())
    return HTMLResponse("<h1>ResiQuant Extractor</h1><p>POST /extract with files.</p>")


@app.post("/extract", response_model=ExtractionResult, summary="Extract from one submission")
async def extract_endpoint(files: list[UploadFile] = File(...)):
    """Upload one submission's files (email PDF + attachments). Returns one extraction result."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    contents = [await f.read() for f in files]
    for f, c in zip(files, contents):
        _check_size(f.filename or "unknown", c)

    parsed_docs, files_bytes = _read_files(files, contents)

    if not parsed_docs:
        raise HTTPException(status_code=400, detail="All uploaded files were empty or unsupported.")

    return extract(parsed_docs, files_bytes)


@app.post("/batch-extract", response_model=BatchExtractionResult, summary="Extract from multiple submissions")
async def batch_extract_endpoint(files: list[UploadFile] = File(...)):
    """
    Upload multiple submissions at once.

    Two modes:
    - ZIP mode: upload one .zip per submission — each ZIP contains the email + attachments.
    - Multi-group mode: upload all files; the service groups them by detecting which PDF
      is the email (contains From:/To:/Subject: header) and treats each email + its
      following attachments as one submission.

    Returns a list of extraction results, one per submission.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    contents = [await f.read() for f in files]
    for f, c in zip(files, contents):
        _check_size(f.filename or "unknown", c)

    # --- ZIP mode: each uploaded file is a .zip ---
    zip_uploads = [(f, c) for f, c in zip(files, contents) if f.filename and f.filename.lower().endswith(".zip")]
    if zip_uploads:
        return await _batch_from_zips(zip_uploads)

    # --- Multi-group mode: group by email detection ---
    return await _batch_from_mixed_files(files, contents)


async def _batch_from_zips(zip_uploads: list[tuple[UploadFile, bytes]]) -> BatchExtractionResult:
    results = []
    for upload, content in zip_uploads:
        sub_name = Path(upload.filename or "submission").stem
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                parsed_docs, files_bytes = [], []
                for entry in zf.infolist():
                    if entry.is_dir():
                        continue
                    ext = Path(entry.filename).suffix.lower()
                    if ext not in ALLOWED_EXTENSIONS:
                        continue
                    if entry.file_size > MAX_FILE_BYTES:
                        logger.warning(
                            "zip_entry_too_large submission=%s file=%s size=%d",
                            sub_name, entry.filename, entry.file_size,
                        )
                        continue
                    file_bytes = zf.read(entry.filename)
                    fname = Path(entry.filename).name
                    files_bytes.append(file_bytes)
                    parsed_docs.append(parse_file(fname, file_bytes))
                    logger.info("zip_entry submission=%s file=%s size=%d", sub_name, fname, len(file_bytes))

            if parsed_docs:
                result = extract(parsed_docs, files_bytes)
            else:
                raise ValueError("No supported files inside ZIP")
        except Exception as e:
            logger.error("zip_error submission=%s: %s", sub_name, e)
            result = _empty_result(sub_name, str(e))

        results.append({"submission_id": sub_name, "result": result})

    return BatchExtractionResult(submissions=results, total=len(results))


def _is_email_doc(doc) -> bool:
    """Heuristic: a PDF is the submission email if its first page starts with From: and To:/Subject:."""
    first_page = doc.pages[0] if doc.pages else ""
    text = first_page[:500]
    has_from = "From:" in text or "From " in text
    has_to_subj = "To:" in text or "Subject:" in text
    return has_from and has_to_subj


async def _batch_from_mixed_files(
    files: list[UploadFile], contents: list[bytes]
) -> BatchExtractionResult:
    """
    Group files into submissions by detecting email PDFs.

    Strategy:
    - 0 or 1 email detected → treat ALL uploaded files as a single submission
      (handles the common case: one email PDF + one attachment, any upload order)
    - 2+ emails detected → each email starts a new submission; non-email files
      uploaded before the first email are prepended to the first group.
    """
    # Parse all files
    parsed = []
    for upload, content in zip(files, contents):
        if not content:
            continue
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        doc = parse_file(upload.filename or "unknown", content)
        parsed.append((upload.filename or "unknown", content, doc))

    if not parsed:
        raise HTTPException(status_code=400, detail="All uploaded files were empty or unsupported.")

    email_indices = [i for i, (_, _, doc) in enumerate(parsed) if _is_email_doc(doc)]

    # ── 0 or 1 email: everything is one submission ──────────────────────────
    if len(email_indices) <= 1:
        groups = [parsed]

    # ── Multiple emails: split by email boundaries ──────────────────────────
    else:
        groups = []
        for gi, email_idx in enumerate(email_indices):
            next_email_idx = email_indices[gi + 1] if gi + 1 < len(email_indices) else len(parsed)
            group = list(parsed[email_idx:next_email_idx])
            # Files uploaded before the first email belong to the first group
            if gi == 0 and email_idx > 0:
                group = list(parsed[:email_idx]) + group
            groups.append(group)

    results = []
    for i, group in enumerate(groups):
        sub_name = f"submission_{i+1}"
        # Use the email filename as submission name (prefer email doc, fall back to first)
        email_items = [(fn, c, d) for fn, c, d in group if _is_email_doc(d)]
        name_source = email_items[0][0] if email_items else group[0][0]
        if name_source and name_source != "unknown":
            sub_name = Path(name_source).stem[:40]

        files_bytes = [c for _, c, _ in group]
        docs = [d for _, _, d in group]
        result = extract(docs, files_bytes)
        results.append({"submission_id": sub_name, "result": result})

    return BatchExtractionResult(submissions=results, total=len(results))


def _empty_result(submission_id: str, error: str) -> ExtractionResult:
    return ExtractionResult(
        request_id=str(uuid.uuid4()),
        cache_hit=False,
        broker_name=FieldResult(value=None, confidence=0.0),
        broker_email=FieldResult(value=None, confidence=0.0),
        brokerage=FieldResult(value=None, confidence=0.0),
        complete_brokerage_address=FieldResult(value=None, confidence=0.0),
        property_addresses=[],
        latency_ms=0.0,
        errors=[f"provider_error: {error}"],
    )


@app.get("/metrics", summary="Cost & latency metrics")
async def get_metrics(request: Request):
    """
    Returns aggregate token usage, cost, latency, and error counts.
    - API clients (Accept: application/json) receive JSON.
    - Browsers receive a formatted HTML dashboard.
    """
    snap = metrics_store.snapshot()

    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return HTMLResponse(_metrics_html(snap))

    return MetricsResponse(**snap)


def _metrics_html(s: dict) -> str:
    def row(label, value, sub=""):
        return f"""
        <div class="metric">
          <div class="metric-label">{html.escape(str(label))}</div>
          <div class="metric-value">{html.escape(str(value))}</div>
          {f'<div class="metric-sub">{html.escape(str(sub))}</div>' if sub else ''}
        </div>"""

    errors_html = "".join(
        f'<div class="err-row"><span class="err-type">{html.escape(str(k))}</span>'
        f'<span class="err-cnt">{html.escape(str(v))}</span></div>'
        for k, v in s["errors_by_type"].items()
    ) or '<div class="err-row" style="color:#999">No errors recorded</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>ResiQuant — Metrics</title>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet"/>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Plus Jakarta Sans',sans-serif;background:#fff;color:#0c0c0c;min-height:100vh;font-size:15px;-webkit-font-smoothing:antialiased}}
nav{{height:54px;display:flex;align-items:center;justify-content:space-between;padding:0 28px;border-bottom:1px solid rgba(0,0,0,0.07)}}
.nav-wordmark{{font-size:14px;font-weight:500;letter-spacing:-0.01em;text-decoration:none;color:#0c0c0c}}
.nav-back{{font-size:12px;color:#666;text-decoration:none;display:flex;align-items:center;gap:5px;padding:5px 12px;border:1px solid rgba(0,0,0,0.12);border-radius:6px}}
.nav-back:hover{{color:#0c0c0c;border-color:rgba(0,0,0,0.22)}}
.page{{max-width:900px;margin:0 auto;padding:40px 28px 80px}}
.page-eyebrow{{font-size:11px;font-weight:500;letter-spacing:0.1em;text-transform:uppercase;color:#999;margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.page-eyebrow::before{{content:'';display:block;width:20px;height:1px;background:#ccc}}
h1{{font-size:clamp(24px,3vw,36px);font-weight:500;letter-spacing:-0.02em;margin-bottom:8px}}
.subtitle{{font-size:14px;color:#666;margin-bottom:36px}}
.note{{font-size:11px;color:#aaa;margin-top:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:32px}}
.metric{{background:#f9f9f9;border:1px solid rgba(0,0,0,0.07);border-radius:10px;padding:18px 20px}}
.metric-label{{font-size:11px;font-weight:500;letter-spacing:0.06em;text-transform:uppercase;color:#999;margin-bottom:8px}}
.metric-value{{font-size:28px;font-weight:500;letter-spacing:-0.02em;color:#0c0c0c;line-height:1}}
.metric-sub{{font-size:11px;color:#aaa;margin-top:6px}}
.section-title{{font-size:11px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#999;margin-bottom:12px}}
.errors-box{{background:#f9f9f9;border:1px solid rgba(0,0,0,0.07);border-radius:10px;padding:18px 20px}}
.err-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(0,0,0,0.06)}}
.err-row:last-child{{border-bottom:none}}
.err-type{{font-size:13px;color:#0c0c0c;font-family:monospace}}
.err-cnt{{font-size:13px;font-weight:600;color:#d93025}}
.refresh{{font-size:12px;color:#999;text-align:right;margin-top:20px}}
</style>
</head>
<body>
<nav>
  <a class="nav-wordmark" href="/">ResiQuant</a>
  <a class="nav-back" href="/">← Back to app</a>
</nav>
<div class="page">
  <div class="page-eyebrow">Observability</div>
  <h1>Service Metrics</h1>
  <p class="subtitle">In-memory — resets on restart. All costs are estimates based on Perplexity sonar-pro pricing.</p>

  <div class="grid">
    {row("Total requests", s["total_requests"])}
    {row("Cache hits", s["cache_hits"], f'{s["cache_hit_rate"]*100:.1f}% hit rate')}
    {row("Cache misses", s["cache_misses"])}
    {row("Total cost", f'${s["total_cost_usd"]:.4f}', f'~${s["avg_cost_per_request_usd"]:.4f} / request')}
    {row("Total tokens", f'{s["total_tokens_used"]:,}', f'{s["total_prompt_tokens"]:,} prompt · {s["total_completion_tokens"]:,} completion')}
    {row("Avg latency", f'{s["avg_latency_ms"]:.0f} ms', f'{s["total_latency_ms"]:.0f} ms total')}
    {row("Error rate", f'{s["error_rate"]*100:.1f}%')}
  </div>

  <div class="section-title">Errors by type</div>
  <div class="errors-box">{errors_html}</div>

  <div class="refresh">Auto-refresh: <a href="/metrics" style="color:#666">reload page</a> · <a href="/metrics" style="color:#666" onclick="setTimeout(()=>location.reload(),5000);return false">refresh in 5s</a></div>
</div>
</body>
</html>"""


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}
