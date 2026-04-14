"""Core extraction logic: parse documents → LLM → validate → structured result."""
from __future__ import annotations
import time
import uuid
import logging
from typing import Any

from app import cache, validators
from app.llm import call_llm, estimate_cost, extract_json_from_response
from app.metrics import record
from app.models import (
    ExtractionResult, FieldResult, PropertyAddress,
    Provenance, TokenUsage,
)
from app.parser import ParsedDocument

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert insurance document analyst.
Your job is to extract specific broker and property information from insurance submission emails and their attachments.

Rules:
- Extract ONLY from the provided text. Never invent or infer values not present.
- The broker is the ORIGINAL sender of the email (not the forwarding intermediary).
  Look for email signatures at the bottom of the forwarded message body.
- If a field is not found, set value to null and confidence to 0.0.
- confidence is a float 0.0–1.0 representing how certain you are.
- provenance must name the exact doc_name, page number (null if not applicable), and a short verbatim snippet (<120 chars) from that document.
- property_addresses: list every insured property address found across all documents.
- Output ONLY valid JSON. No markdown, no explanation, no extra text.

Output schema:
{
  "broker_name":               {"value": string|null, "confidence": float, "provenance": {"doc_name": string, "page": int|null, "snippet": string}|null},
  "broker_email":              {"value": string|null, "confidence": float, "provenance": {"doc_name": string, "page": int|null, "snippet": string}|null},
  "brokerage":                 {"value": string|null, "confidence": float, "provenance": {"doc_name": string, "page": int|null, "snippet": string}|null},
  "complete_brokerage_address":{"value": string|null, "confidence": float, "provenance": {"doc_name": string, "page": int|null, "snippet": string}|null},
  "property_addresses": [
    {"address": string, "confidence": float, "provenance": {"doc_name": string, "page": int|null, "snippet": string}}
  ]
}"""

# ---------------------------------------------------------------------------
# Few-shot examples (built from the real sub_2 and sub_56 data we inspected)
# ---------------------------------------------------------------------------
FEW_SHOT = """
--- EXAMPLE 1 ---
DOCUMENT: Resiquant Mail - FW_ Town Squire Owners Association.pdf  [Page 1]
...
From: Emily Gooding <egooding@brcins.com>
Emily Gooding | Associate Broker, Property  resident license: 1190929
direct: 206.816.6789 | mobile: 425.919.4177 | egooding@brcins.com
Brown & Riding | 600 University Street, Suite 3000, Seattle, WA 98101
...
DOCUMENT: 24-25 DIC SOV.xlsx  [Sheet: locexp]
Loc  Address            City     State  Zip
1    7924 212th St SW   Edmonds  WA     98026

EXPECTED OUTPUT:
{
  "broker_name": {"value": "Emily Gooding", "confidence": 0.97, "provenance": {"doc_name": "Resiquant Mail - FW_ Town Squire Owners Association.pdf", "page": 1, "snippet": "Emily Gooding | Associate Broker, Property"}},
  "broker_email": {"value": "egooding@brcins.com", "confidence": 0.99, "provenance": {"doc_name": "Resiquant Mail - FW_ Town Squire Owners Association.pdf", "page": 1, "snippet": "egooding@brcins.com"}},
  "brokerage": {"value": "Brown & Riding", "confidence": 0.97, "provenance": {"doc_name": "Resiquant Mail - FW_ Town Squire Owners Association.pdf", "page": 1, "snippet": "Brown & Riding | 600 University Street, Suite 3000, Seattle, WA 98101"}},
  "complete_brokerage_address": {"value": "600 University Street, Suite 3000, Seattle, WA 98101", "confidence": 0.95, "provenance": {"doc_name": "Resiquant Mail - FW_ Town Squire Owners Association.pdf", "page": 1, "snippet": "600 University Street, Suite 3000, Seattle, WA 98101"}},
  "property_addresses": [
    {"address": "7924 212th St SW, Edmonds, WA 98026", "confidence": 0.95, "provenance": {"doc_name": "24-25 DIC SOV.xlsx", "page": null, "snippet": "7924 212th St SW   Edmonds  WA  98026"}}
  ]
}

--- EXAMPLE 2 ---
DOCUMENT: Resiquant Mail - FW_ DIC Submission Clinica Msr. Oscar A. Romero.pdf  [Page 1]
...
From: Romero, Chris <chris.romero@rtspecialty.com>
Christopher Romero I Account Executive
License #2091013
RT Specialty
3900 W. Alameda Avenue Suite 2000 l Burbank CA 91505
D 213 213 1787
...
DOCUMENT: FILE SUMMARY.PDF  [Page 2]
Location 1: 123 S Alvarado St, Los Angeles, CA 90057
Location 2: 2032-2034 Marengo St, Los Angeles, CA 90033
Location 3: 2969 Wilshire Blvd, Los Angeles, CA 90010

EXPECTED OUTPUT:
{
  "broker_name": {"value": "Christopher Romero", "confidence": 0.96, "provenance": {"doc_name": "Resiquant Mail - FW_ DIC Submission Clinica Msr. Oscar A. Romero.pdf", "page": 1, "snippet": "Christopher Romero I Account Executive"}},
  "broker_email": {"value": "chris.romero@rtspecialty.com", "confidence": 0.99, "provenance": {"doc_name": "Resiquant Mail - FW_ DIC Submission Clinica Msr. Oscar A. Romero.pdf", "page": 1, "snippet": "chris.romero@rtspecialty.com"}},
  "brokerage": {"value": "RT Specialty", "confidence": 0.97, "provenance": {"doc_name": "Resiquant Mail - FW_ DIC Submission Clinica Msr. Oscar A. Romero.pdf", "page": 1, "snippet": "RT Specialty\\n3900 W. Alameda Avenue Suite 2000"}},
  "complete_brokerage_address": {"value": "3900 W. Alameda Avenue Suite 2000, Burbank, CA 91505", "confidence": 0.94, "provenance": {"doc_name": "Resiquant Mail - FW_ DIC Submission Clinica Msr. Oscar A. Romero.pdf", "page": 1, "snippet": "3900 W. Alameda Avenue Suite 2000 l Burbank CA 91505"}},
  "property_addresses": [
    {"address": "123 S Alvarado St, Los Angeles, CA 90057", "confidence": 0.95, "provenance": {"doc_name": "FILE SUMMARY.PDF", "page": 2, "snippet": "Location 1: 123 S Alvarado St, Los Angeles, CA 90057"}},
    {"address": "2032-2034 Marengo St, Los Angeles, CA 90033", "confidence": 0.95, "provenance": {"doc_name": "FILE SUMMARY.PDF", "page": 2, "snippet": "Location 2: 2032-2034 Marengo St, Los Angeles, CA 90033"}},
    {"address": "2969 Wilshire Blvd, Los Angeles, CA 90010", "confidence": 0.95, "provenance": {"doc_name": "FILE SUMMARY.PDF", "page": 2, "snippet": "Location 3: 2969 Wilshire Blvd, Los Angeles, CA 90010"}}
  ]
}
--- END EXAMPLES ---
"""


def build_user_prompt(docs: list[ParsedDocument]) -> str:
    parts = [FEW_SHOT, "\nNow extract from the following documents:\n"]
    for doc in docs:
        parts.append(f"\n--- DOCUMENT: {doc.name} ---")
        for page_text in doc.pages:
            parts.append(page_text[:4000])  # cap per page to avoid token blowup
    parts.append("\nReturn ONLY the JSON object:")
    return "\n".join(parts)


def _build_field(raw: Any, key: str) -> FieldResult:
    if not isinstance(raw, dict):
        return FieldResult(value=None, confidence=0.0)
    prov_raw = raw.get("provenance")
    prov = None
    if isinstance(prov_raw, dict):
        prov = Provenance(
            doc_name=prov_raw.get("doc_name", ""),
            page=prov_raw.get("page"),
            snippet=prov_raw.get("snippet", ""),
        )
    return FieldResult(
        value=raw.get("value"),
        confidence=float(raw.get("confidence", 0.0)),
        provenance=prov,
    )


def _build_addresses(raw: Any) -> list[PropertyAddress]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        prov_raw = item.get("provenance")
        prov = None
        if isinstance(prov_raw, dict):
            prov = Provenance(
                doc_name=prov_raw.get("doc_name", ""),
                page=prov_raw.get("page"),
                snippet=prov_raw.get("snippet", ""),
            )
        result.append(PropertyAddress(
            address=item.get("address", ""),
            confidence=float(item.get("confidence", 0.0)),
            provenance=prov,
        ))
    return result


def extract(docs: list[ParsedDocument], files_bytes: list[bytes]) -> ExtractionResult:
    request_id = str(uuid.uuid4())
    source_hash = cache.compute_hash(files_bytes)

    # --- cache lookup ---
    cached = cache.get(source_hash)
    if cached:
        logger.info("cache_hit request_id=%s source_hash=%s", request_id, source_hash)
        result = ExtractionResult(**cached)
        result.request_id = request_id
        result.cache_hit = True
        record(cache_hit=True, tokens=0, latency_ms=0, errors=[])
        return result

    logger.info("cache_miss request_id=%s source_hash=%s", request_id, source_hash)

    t0 = time.perf_counter()
    llm_errors: list[str] = []
    raw: dict = {}

    try:
        user_prompt = build_user_prompt(docs)
        llm_resp = call_llm(SYSTEM_PROMPT, user_prompt)
        raw = extract_json_from_response(llm_resp.content)
    except TimeoutError as e:
        llm_errors.append(f"timeout: {e}")
        logger.error("LLM timeout request_id=%s: %s", request_id, e)
        llm_resp = None  # type: ignore
    except Exception as e:
        llm_errors.append(f"provider_error: {e}")
        logger.error("LLM error request_id=%s: %s", request_id, e)
        llm_resp = None  # type: ignore

    latency_ms = (time.perf_counter() - t0) * 1000

    # --- validate ---
    validation_errors = validators.run_all(raw)
    all_errors = llm_errors + validation_errors

    token_usage = None
    if llm_resp:
        token_usage = TokenUsage(
            prompt_tokens=llm_resp.prompt_tokens,
            completion_tokens=llm_resp.completion_tokens,
            total_tokens=llm_resp.total_tokens,
            estimated_cost_usd=estimate_cost(
                llm_resp.prompt_tokens, llm_resp.completion_tokens
            ),
        )

    result = ExtractionResult(
        request_id=request_id,
        cache_hit=False,
        broker_name=_build_field(raw.get("broker_name"), "broker_name"),
        broker_email=_build_field(raw.get("broker_email"), "broker_email"),
        brokerage=_build_field(raw.get("brokerage"), "brokerage"),
        complete_brokerage_address=_build_field(raw.get("complete_brokerage_address"), "complete_brokerage_address"),
        property_addresses=_build_addresses(raw.get("property_addresses")),
        latency_ms=round(latency_ms, 2),
        token_usage=token_usage,
        errors=all_errors,
    )

    record(cache_hit=False, tokens=token_usage.total_tokens if token_usage else 0, latency_ms=latency_ms, errors=all_errors)
    logger.info(
        "extracted request_id=%s source_hash=%s latency_ms=%.1f tokens=%s errors=%d",
        request_id, source_hash, latency_ms,
        token_usage.total_tokens if token_usage else 0,
        len(all_errors),
    )

    # cache (only if no provider errors)
    if not llm_errors:
        cache.put(source_hash, result.model_dump())

    return result
