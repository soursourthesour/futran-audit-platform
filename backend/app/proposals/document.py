"""The proposal document (SM-10 preview, PDF and DOCX; SM-12 full document), built as Markdown by section.

Sections, in order: cover; your situation; what we'll do (one block per line from its deliverables, as tailored on this
proposal); deliverables and timeline; pricing; assumptions (automatic: unknown answers, what each line includes,
roadmap items excluded, manual-delivery notes); terms; independence statement (only when flagged, rule I-4);
acceptance. Merge fields: [Company], [Rep name], [Valid until], [Version], [Date].

Nothing internal goes into the document: no rule codes, reasons, list prices, Low/High ranges or approvals."""
import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.clock import today
from app.proposals.models import Proposal, ProposalLine

PRODUCT = "Futran Audit Platform"
BILLING_WORDS = {"one_time": "One-time", "annual": "Annual", "quarterly": "Quarterly", "monthly": "Monthly", "share": "Share"}
INCLUDED_WORDS = {"systems": "AI systems in scope", "docs": "policy documents reviewed", "readout": "board readout", "seats": "user seats",
                  "ai_systems": "AI systems", "advisor_hours": "advisor hours", "tracing_systems": "traced systems"}
MANUAL_NOTE = "Delivered by Futran consultants until the platform feature ships."


def money(v) -> str:
    if v is None:
        return "—"
    v = round(float(v), 2)
    return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"


def fmt_day(d: date | None) -> str:
    return f"{d.day} {d:%B %Y}" if d else "—"


def valid_until(p: Proposal) -> date:
    return p.valid_until or (today() + timedelta(days=p.valid_days or 30))


def _md_escape(text: str) -> str:
    """Text from the catalog or the rep is shown as text: Markdown table pipes and stray HTML can't change the layout
    (the renderer already escapes HTML)."""
    return (text or "").replace("|", "\\|")


def merge_values(db: Session, p: Proposal) -> dict:
    from app.sales.models import Opportunity
    from app.tenancy.models import Organization, User

    org = db.get(Organization, p.organization_id)
    opp = db.get(Opportunity, p.opportunity_id)
    rep = db.get(User, p.sent_by or (opp.owner_id if opp else None) or p.created_by) if (p.sent_by or opp or p.created_by) else None
    return {"Company": org.name if org else "the client", "Rep name": rep.name if rep else "your Futran contact", "Valid until": fmt_day(valid_until(p)),
            "Version": f"v{p.version}", "Date": fmt_day((p.sent_at.date() if p.sent_at else today()))}


def merge(text: str, values: dict) -> str:
    return re.sub(r"\[([A-Za-z ]+)\]", lambda m: values.get(m.group(1), m.group(0)), text or "")


def offered(ls: list[ProposalLine]) -> list[ProposalLine]:
    return [ln for ln in ls if not ln.removed_reason and ln.on_catalog and ln.sellable_status != "roadmap"]


def optional(ls: list[ProposalLine]) -> list[ProposalLine]:
    return [ln for ln in ls if not ln.removed_reason and ln.on_catalog and ln.sellable_status == "roadmap"]


def _duration(text: str | None) -> str:
    for line in (text or "").splitlines():
        s = line.strip().rstrip(".")
        if s.lower().startswith("typical duration"):
            return s.split(":", 1)[-1].strip() or "—"
    m = re.search(r"(\d+\s*[–-]\s*\d+|\d+)\s+weeks?", text or "")
    return m.group(0) if m else "—"


def _summary(text: str | None) -> str:
    first = next((ln.strip(" •-") for ln in (text or "").splitlines() if ln.strip()), "")
    return first[:180] + ("…" if len(first) > 180 else "")


def _bullets(text: str) -> str:
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(f"- {s.lstrip('•-* ').strip()}" if s[:1] in "•-*" else s)
    return "\n".join(out)


def included(ln: ProposalLine) -> str | None:
    q = ln.included_quantities or {}
    if not q:
        return None
    parts = [f"{v:g} {INCLUDED_WORDS.get(k, k.replace('_', ' '))}" if isinstance(v, (int, float)) else f"{k.replace('_', ' ')}: {v}" for k, v in q.items()]
    return f"{ln.name} ({ln.catalog_code}) includes {', '.join(parts)}."


def assumptions(db: Session, p: Proposal, ls: list[ProposalLine]) -> list[str]:
    out = []
    if p.questionnaire_id:
        try:
            from app.scoping import service as scoping

            q = scoping.get(db, p.questionnaire_id)
            out += [a["text"] for a in scoping.assumptions(db, q)]
        except Exception:  # noqa: BLE001  scoping is another workstream's module; without it there are no answer assumptions
            pass
    out += [x for x in (included(ln) for ln in offered(ls)) if x]
    for ln in optional(ls):
        out.append(f"{ln.name} ({ln.catalog_code}) is not yet available and is not included or priced in this proposal.")
    for ln in offered(ls):
        if ln.sellable_status == "manual_delivery":
            note = next((s.strip() for s in reversed((ln.deliverables_text or "").splitlines()) if s.strip().lower().startswith("delivered by futran consultants")),
                        MANUAL_NOTE)
            out.append(f"{ln.name} ({ln.catalog_code}): {note}")
    return list(dict.fromkeys(out))


def pricing_rows(p: Proposal, ls: list[ProposalLine]) -> list[dict]:
    rows = []
    for ln in offered(ls):
        billing = BILLING_WORDS.get(ln.billing, ln.billing)
        if ln.billing in ("quarterly", "monthly") and ln.periods_per_year:
            billing = f"{billing} × {ln.periods_per_year}"
        unit = f"{ln.unit_price_used:g}% of related services" if ln.basis == "%" and ln.unit_price_used is not None else money(ln.unit_price_used)
        rows.append({"code": ln.catalog_code, "name": ln.name, "qty": ln.qty, "billing": billing, "unit": unit, "value": ln.line_value,
                     "recurring": ln.billing != "one_time"})
    return rows


def totals_rows(p: Proposal) -> list[tuple[str, float]]:
    t = p.totals or {}
    d = p.discount_recurring_pct or 0
    rows = [("One-time services", t.get("one_time")), ("Recurring, year 1", t.get("recurring_y1"))]
    if t.get("discount"):
        rows.append((f"Discount{f' on recurring ({d:g}%)' if d else ''}", -(t.get("discount") or 0)))
    rows += [("Total, year 1", t.get("y1_total")), ("Annual recurring after year 1", t.get("arr"))]
    return rows


def terms_lines(p: Proposal) -> list[str]:
    from app.proposals.service import REGIONS

    t = p.terms or {}
    out = [f"Valid for {p.valid_days or 30} days, until {fmt_day(valid_until(p))}."]
    out.append(f"Payment: {t['payment_terms']}" if t.get("payment_terms") else f"Payment within {t.get('payment_days', 30)} days of invoice.")
    years = t.get("term_years") or 1
    out.append(f"Contract term: {years} year{'s' if years != 1 else ''}.")
    if t.get("sla"):
        out.append(f"Service levels: {t['sla']}")
    if t.get("sla_credits"):
        out.append(f"Service credits: {t['sla_credits'] if isinstance(t['sla_credits'], str) else 'as agreed'}")
    if t.get("custom_liability"):
        out.append(f"Liability: {t['custom_liability'] if isinstance(t['custom_liability'], str) else 'as agreed'}")
    if t.get("data_region"):
        out.append(f"Data residency: your data is held in {REGIONS.get(t['data_region'], t['data_region'])}.")
    if t.get("start_on"):
        out.append(f"Start date: {t['start_on']}.")
    return out


def sections(db: Session, p: Proposal) -> list[dict]:
    """[{key, number, title, md}] — the document by section, merged and with its generated parts."""
    from app.proposals.service import lines

    ls = lines(db, p)
    values = merge_values(db, p)
    out = []
    n = 0
    for s in p.sections or []:
        if s["key"] == "independence" and not (p.independence or {}).get("flag"):
            continue
        n += 1
        intro = merge(s.get("body") or "", values)
        key = s["key"]
        parts: list[str] = []
        if key == "cover":
            parts = [f"**{PRODUCT} · Futran Solutions**", intro, f"Proposal {values['Version']} · {values['Date']} · Valid until {values['Valid until']}"]
        elif key == "services":
            parts = [intro]
            for ln in offered(ls):
                parts.append(f"### {_md_escape(ln.name)} ({ln.catalog_code})")
                parts.append(_bullets(merge(ln.deliverables_text or ln.description or "", values)) or "Details to follow.")
            if optional(ls):
                parts.append("### Optional, when available")
                parts += [f"- {_md_escape(ln.name)} ({ln.catalog_code}): {(_summary(ln.deliverables_text) or 'not yet available').rstrip('.')}. Not priced in this proposal."
                          for ln in optional(ls)]
        elif key == "deliverables":
            rows = ["| Service | What you receive | Typical duration |", "|---|---|---|"]
            rows += [f"| {_md_escape(ln.name)} ({ln.catalog_code}) | {_md_escape(_summary(ln.deliverables_text or ln.description))} | {_duration(ln.deliverables_text)} |"
                     for ln in offered(ls)]
            parts = [intro, "\n".join(rows)]
        elif key == "pricing":
            rows = ["| Service | Qty | Billing | Unit price | Year-1 value |", "|---|---|---|---|---|"]
            rows += [f"| {_md_escape(r['name'])} ({r['code']}) | {r['qty']:g} | {r['billing']} | {r['unit']} | {money(r['value'])} |" for r in pricing_rows(p, ls)]
            total = ["| | |", "|---|---|"] + [f"| {'**' + label + '**' if label.startswith('Total') else label} | {money(v) if v is None or v >= 0 else '−' + money(-v)} |"
                                                for label, v in totals_rows(p)]
            parts = [intro, "\n".join(rows), "\n".join(total)]
            if optional(ls):
                parts.append("Optional, when available: " + "; ".join(f"{ln.name} ({ln.catalog_code})" for ln in optional(ls)) + ". Not priced in this proposal.")
        elif key == "assumptions":
            parts = [intro, "\n".join(f"- {_md_escape(a)}" for a in assumptions(db, p, ls))]
        elif key == "terms":
            parts = [intro, "\n".join(f"- {t}" for t in terms_lines(p))]
        elif key == "acceptance":
            parts = [intro, f"I am authorised to accept this proposal for {values['Company']}.",
                     "Name: ______________________  Title: ______________________", "Signature: __________________  Date: ______________________"]
        else:
            parts = [intro]
        out.append({"key": key, "number": n, "title": s["title"], "md": "\n\n".join(x for x in parts if x)})
    return out


def markdown(db: Session, p: Proposal) -> str:
    secs = sections(db, p)
    chunks = [f"# {p.title}"]
    for s in secs:
        if s["key"] == "cover":
            chunks.append(s["md"])
            chunks.append("<!-- pagebreak -->")
        else:
            chunks.append(f"## {s['title']}\n\n{s['md']}")
    return "\n\n".join(chunks) + "\n"


def html_sections(db: Session, p: Proposal) -> list[dict]:
    """For the preview and the client page: each section as safe HTML (raw HTML in any text is escaped)."""
    from app.documents.render import render_markdown

    return [{"key": s["key"], "number": s["number"], "title": s["title"], "html": render_markdown(s["md"])} for s in sections(db, p)]


def filename(db: Session, p: Proposal, ext: str) -> str:
    company = merge_values(db, p)["Company"]
    base = re.sub(r"[^A-Za-z0-9]+", "-", f"Futran proposal {company} v{p.version}").strip("-")
    return f"{base}.{ext}"


def to_pdf(db: Session, p: Proposal) -> bytes:
    from app.documents.pdf import to_pdf as pdf

    return pdf(markdown(db, p), p.title, {"audit_ref": f"Proposal v{p.version}", "cover": True})


def to_docx(db: Session, p: Proposal) -> bytes:
    from app.documents.docx import to_docx as docx

    return docx(markdown(db, p), p.title, {"audit_ref": f"Proposal v{p.version}", "cover": True})
