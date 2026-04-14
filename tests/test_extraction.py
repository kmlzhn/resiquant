"""
Integration tests for all 5 sample submissions.
Runs against the real Perplexity API (results are cached so re-runs are free).

Usage:
    cd resiquant
    python3 -m pytest tests/ -v
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

import pytest

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.extractor import extract
from app.parser import parse_file

DATA_DIR = Path("/Users/kamilazhandildayeva/Documents/submission_files")

# Ground truth for broker fields (from manual inspection)
EXPECTED = {
    "sub_2": {
        "broker_name": "Emily Gooding",
        "broker_email": "egooding@brcins.com",
        "brokerage": "Brown & Riding",
        "address_contains": ["Seattle", "WA"],
        "property_keywords": ["Edmonds", "212th"],
    },
    "sub_5": {
        "broker_name": "Eli Chlomovitz",
        "broker_email": "eli.chlomovitz@xptspecialty.com",
        "brokerage": "XPT Specialty",
        "address_contains": [],
        "property_keywords": ["Burbank", "14950"],
    },
    "sub_7": {
        "broker_name": None,  # extracted from docx/email — flexible
        "broker_email": None,
        "brokerage": None,
        "address_contains": [],
        "property_keywords": ["Remmet", "8010"],
    },
    "sub_19": {
        "broker_name": "Rich Lombard",
        "broker_email": "richard.lombard@rtspecialty.com",
        "brokerage": "RT Specialty",
        "address_contains": ["New York", "NY"],
        "property_keywords": ["Bothell", "Alameda", "Seattle"],
    },
    "sub_56": {
        "broker_name": "Christopher Romero",
        "broker_email": "chris.romero@rtspecialty.com",
        "brokerage": "RT Specialty",
        "address_contains": ["Burbank", "CA"],
        "property_keywords": ["Alvarado", "Marengo", "Wilshire"],
    },
}


def load_submission(sub_id: str):
    folder = DATA_DIR / sub_id
    docs, bytes_list = [], []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in (".pdf", ".xlsx", ".xls", ".docx"):
            content = f.read_bytes()
            bytes_list.append(content)
            docs.append(parse_file(f, content))
    return docs, bytes_list


def _val(field) -> str | None:
    return field.value if field else None


# ── sub_2 ──────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub2_broker_name():
    docs, b = load_submission("sub_2")
    r = extract(docs, b)
    assert _val(r.broker_name) and "Gooding" in _val(r.broker_name)

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub2_broker_email():
    docs, b = load_submission("sub_2")
    r = extract(docs, b)
    assert _val(r.broker_email) == "egooding@brcins.com"

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub2_brokerage():
    docs, b = load_submission("sub_2")
    r = extract(docs, b)
    assert _val(r.brokerage) and "Brown" in _val(r.brokerage)

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub2_property_addresses():
    docs, b = load_submission("sub_2")
    r = extract(docs, b)
    addrs = " ".join(a.address for a in r.property_addresses)
    assert "212th" in addrs or "Edmonds" in addrs


# ── sub_5 ──────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub5_broker_email():
    docs, b = load_submission("sub_5")
    r = extract(docs, b)
    assert _val(r.broker_email) == "eli.chlomovitz@xptspecialty.com"

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub5_property_addresses():
    docs, b = load_submission("sub_5")
    r = extract(docs, b)
    addrs = " ".join(a.address for a in r.property_addresses)
    assert "Burbank" in addrs or "14950" in addrs


# ── sub_7 ──────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub7_property_addresses():
    docs, b = load_submission("sub_7")
    r = extract(docs, b)
    addrs = " ".join(a.address for a in r.property_addresses)
    assert "Remmet" in addrs or "8010" in addrs

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub7_has_broker_info():
    docs, b = load_submission("sub_7")
    r = extract(docs, b)
    # At least one broker field should be non-null
    assert any([_val(r.broker_name), _val(r.broker_email), _val(r.brokerage)])


# ── sub_19 ─────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub19_broker_email():
    docs, b = load_submission("sub_19")
    r = extract(docs, b)
    assert _val(r.broker_email) == "richard.lombard@rtspecialty.com"

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub19_multiple_properties():
    docs, b = load_submission("sub_19")
    r = extract(docs, b)
    assert len(r.property_addresses) >= 5  # 13 locations expected

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub19_brokerage_address():
    docs, b = load_submission("sub_19")
    r = extract(docs, b)
    addr = _val(r.complete_brokerage_address) or ""
    assert "NY" in addr or "New York" in addr


# ── sub_56 ─────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub56_broker_name():
    docs, b = load_submission("sub_56")
    r = extract(docs, b)
    assert _val(r.broker_name) and "Romero" in _val(r.broker_name)

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub56_broker_email():
    docs, b = load_submission("sub_56")
    r = extract(docs, b)
    assert _val(r.broker_email) == "chris.romero@rtspecialty.com"

@pytest.mark.skipif(not DATA_DIR.exists(), reason="Sample data not found")
def test_sub56_property_addresses():
    docs, b = load_submission("sub_56")
    r = extract(docs, b)
    addrs = " ".join(a.address for a in r.property_addresses)
    assert "Alvarado" in addrs or "Marengo" in addrs


# ── Validation layer ────────────────────────────────────────────────────────
def test_email_validator_rejects_invalid():
    from app.validators import validate_broker_email
    assert validate_broker_email("not-an-email") != []
    assert validate_broker_email("") == []

def test_email_validator_accepts_valid():
    from app.validators import validate_broker_email
    assert validate_broker_email("user@example.com") == []

def test_address_validator_rejects_city_only():
    from app.validators import validate_brokerage_address
    assert validate_brokerage_address("New York") != []

def test_address_validator_accepts_full():
    from app.validators import validate_brokerage_address
    assert validate_brokerage_address("600 University St, Seattle, WA 98101") == []


# ── Cache layer ─────────────────────────────────────────────────────────────
def test_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    import importlib
    import app.cache as c
    importlib.reload(c)
    h = c.compute_hash([b"hello", b"world"])
    assert c.get(h) is None
    c.put(h, {"foo": "bar"})
    assert c.get(h) == {"foo": "bar"}


# ── Parser smoke tests ──────────────────────────────────────────────────────
def test_parser_pdf():
    pdf_path = DATA_DIR / "sub_2" / "Resiquant Mail - FW_ Town Squire Owners Association, File # BR138084-01.pdf"
    if not pdf_path.exists():
        pytest.skip("Sample PDF not found")
    doc = parse_file(pdf_path)
    assert "Emily Gooding" in doc.full_text or "egooding" in doc.full_text

def test_parser_xlsx():
    xlsx_path = DATA_DIR / "sub_2" / "24-25 DIC SOV - $8,104,498.xlsx"
    if not xlsx_path.exists():
        pytest.skip("Sample XLSX not found")
    doc = parse_file(xlsx_path)
    assert len(doc.full_text) > 10
