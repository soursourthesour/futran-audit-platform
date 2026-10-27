"""The engagement letter's address block and salutation are separate paragraphs, with or without an address."""
from pathlib import Path

from app.reference.templates import render_string

BODY = (Path(__file__).resolve().parents[2] / "seeds" / "templates" / "engagement_letter.md.j2").read_text()


def _ctx(address):
    return {"engagement": {"name": "Initial", "audit_ref": "FSL-1"}, "today": "Oct 27, 2026",
            "client": {"name": "Acme", "legal_name": "Acme Inc.", "hq_address": address}, "contacts": {"caico": {"name": "Pat Lee"}}}


def test_address_and_salutation_are_separate_paragraphs():
    out = render_string(BODY, _ctx("1 Main St, Edison, NJ 08817"))
    assert "Acme Inc.\n\n1 Main St, Edison, NJ 08817\n\nDear Pat Lee," in out


def test_no_address_leaves_a_clean_gap():
    out = render_string(BODY, _ctx(None))
    assert "Acme Inc.\n\nDear Pat Lee," in out
