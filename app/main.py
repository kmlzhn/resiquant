"""FastAPI application: /extract, /batch-extract, /metrics, /health."""
from __future__ import annotations
import hashlib
import io
import logging
import sys
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import metrics as metrics_store
from app.extractor import extract
from app.models import BatchExtractionResult, ExtractionResult, MetricsResponse
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


def _read_files(uploads: list[UploadFile], contents: list[bytes]) -> tuple[list, list[bytes]]:
    """Parse uploaded files into (docs, bytes_list)."""
    parsed_docs, files_bytes = [], []
    for upload, content in zip(uploads, contents):
        if not content:
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
    parsed_docs, files_bytes = _read_files(files, contents)

    if not parsed_docs:
        raise HTTPException(status_code=400, detail="All uploaded files were empty.")

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


async def _batch_from_mixed_files(
    files: list[UploadFile], contents: list[bytes]
) -> BatchExtractionResult:
    """
    Group files into submissions by detecting email PDFs.
    An email PDF contains 'From:' and 'To:' near the top of its first page.
    All files between two email PDFs belong to the same submission.
    """
    from app.parser import parse_file as _parse

    # Parse all files first
    parsed = []
    for upload, content in zip(files, contents):
        if not content:
            continue
        doc = _parse(upload.filename or "unknown", content)
        parsed.append((upload.filename or "unknown", content, doc))

    # Detect which files are "email" files
    def is_email_doc(doc) -> bool:
        first_page = doc.pages[0] if doc.pages else ""
        return ("From:" in first_page or "From" in first_page[:200]) and (
            "To:" in first_page or "Subject:" in first_page
        )

    # Group: each email starts a new submission; attachments follow
    groups: list[list[tuple]] = []
    for item in parsed:
        fname, content, doc = item
        if is_email_doc(doc) or not groups:
            groups.append([item])
        else:
            groups[-1].append(item)

    if not groups:
        raise HTTPException(status_code=400, detail="Could not detect any email files in the upload.")

    results = []
    for i, group in enumerate(groups):
        sub_name = f"submission_{i+1}"
        # Use the email filename as the submission name if possible
        email_fname = group[0][0]
        if email_fname and email_fname != "unknown":
            sub_name = Path(email_fname).stem[:40]

        files_bytes = [c for _, c, _ in group]
        docs = [d for _, _, d in group]
        result = extract(docs, files_bytes)
        results.append({"submission_id": sub_name, "result": result})

    return BatchExtractionResult(submissions=results, total=len(results))


def _empty_result(submission_id: str, error: str) -> ExtractionResult:
    import uuid
    from app.models import FieldResult
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


@app.get("/metrics", response_model=MetricsResponse, summary="Cost & latency metrics")
async def get_metrics():
    """Returns aggregate token usage, latency, and error counts."""
    return MetricsResponse(**metrics_store.snapshot())


@app.get("/health", summary="Health check")
async def health():
    return {"status": "ok"}
