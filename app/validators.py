"""Field-level validators for broker extraction output."""
from __future__ import annotations
import re

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# US state abbreviations
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}


def validate_broker_email(value: str | None) -> list[str]:
    errors = []
    if not value:
        return errors
    if not EMAIL_RE.match(value.strip()):
        errors.append(f"broker_email '{value}' is not a valid email format")
    return errors


def validate_brokerage_address(value: str | None) -> list[str]:
    """Address must contain at least a street number/name, a city-like word, and a US state."""
    errors = []
    if not value:
        return errors
    v = value.strip()
    has_street = bool(re.search(r"\d+\s+\w+", v))
    has_state = any(f" {s}" in f" {v.upper()}" or f",{s}" in f",{v.upper()}" for s in US_STATES)
    # City heuristic: there must be at least two comma-separated segments (street, city[, state...])
    # or a word that appears between the street portion and the state abbreviation.
    parts = [p.strip() for p in v.split(",")]
    has_city = len(parts) >= 2 and len(parts[1]) >= 2
    if not has_street:
        errors.append(f"complete_brokerage_address missing street number: '{v}'")
    if not has_city:
        errors.append(f"complete_brokerage_address missing city: '{v}'")
    if not has_state:
        errors.append(f"complete_brokerage_address missing US state abbreviation: '{v}'")
    return errors


def run_all(result: dict) -> list[str]:
    errors = []
    email_field = result.get("broker_email") or {}
    addr_field  = result.get("complete_brokerage_address") or {}
    errors += validate_broker_email(email_field.get("value") if isinstance(email_field, dict) else None)
    errors += validate_brokerage_address(addr_field.get("value") if isinstance(addr_field, dict) else None)
    return errors
