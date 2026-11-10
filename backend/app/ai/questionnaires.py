"""Customer security and AI questionnaires (spec §21 F10), on the client side.

Detection is deterministic: XLSX by a header cell containing "question" (else the column with most cells ending in
"?"), the answer going in the column headed answer/response/comment or the next column; DOCX by paragraphs and table
cells ending in "?"; PDF by lines, joining wrapped lines, ending in "?". Drafting reads the client's answer library,
its published policies (WS-I, when present) and its latest signed Futran report. Every quote is checked against its
source. A draft whose quote (of checked length) comes from the signed report itself is proposed for the "Audited by
Futran" label; the label stays only when the client's approver confirms it on approval, and only a confirmed label
reaches an export or the answer library. A quote can be real while the answer says more than it, so the model's say-so
is never enough. The client's reviewer decides each one.
Export writes the answers into the original file (XLSX: answer column; DOCX: an "Answer:" paragraph after each
question, or the next table cell), and a PDF comes back as a Word document with a note.

The AIInteraction rows of this feature carry no engagement: a customer's questionnaire is the client's business, not
part of Futran's audit, so it stays out of the engagement's AI log (organization_id is the client)."""
import re
from datetime import date
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai import service as ai
from app.ai.models import AIInteraction, AnswerLibraryItem, Questionnaire, QuestionnaireItem
from app.ai.text import PAGE_CHARS, normalise, quote_in
from app.audit_log import service as audit
from app.core.clock import utcnow
from app.core.errors import Conflict, Invalid
from app.files.models import FileObject
from app.tenancy.models import Organization, User

FORMATS = {".xlsx": "xlsx", ".docx": "docx", ".pdf": "pdf"}
AUDITED = "Audited by Futran"


# ---- detection
def _is_question(text: str) -> bool:
    t = " ".join(str(text or "").split())
    return len(t) >= 8 and (t.endswith("?") or bool(re.match(r"^(describe|explain|list|provide|confirm|state|outline)\b", t, re.I)))


XLSX_MAX_ROWS = 5000
XLSX_MAX_COLS = 100


def detect_xlsx(data: bytes) -> list[dict]:
    from app.core import xlsx_guard

    wb = xlsx_guard.open_workbook(data, max_rows=XLSX_MAX_ROWS, max_cols=XLSX_MAX_COLS, read_only=False)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(min_row=1, max_row=min(ws.max_row, XLSX_MAX_ROWS), max_col=min(ws.max_column, XLSX_MAX_COLS)))
        header_row = q_col = a_col = s_col = None
        for r in rows[:15]:
            for c in r:
                v = str(c.value or "").strip().lower()
                if header_row is None and len(v) < 60 and re.search(r"\bquestions?\b", v):
                    header_row, q_col = c.row, c.column
            if header_row is not None:
                for c in r:
                    v = str(c.value or "").strip().lower()
                    if c.column != q_col and re.search(r"answer|response|comment|reply", v):
                        a_col = a_col or c.column
                    if re.search(r"section|category|domain|area", v):
                        s_col = s_col or c.column
                break
        if header_row is None:  # no header: the column with most question-like cells
            counts: dict[int, int] = {}
            for r in rows:
                for c in r:
                    if _is_question(c.value) and str(c.value).strip().endswith("?"):
                        counts[c.column] = counts.get(c.column, 0) + 1
            if not counts:
                continue
            q_col, header_row = max(counts, key=counts.get), 0
        a_col = a_col or q_col + 1
        for r in rows:
            if r[0].row <= header_row:
                continue
            cell = ws.cell(row=r[0].row, column=q_col)
            text = " ".join(str(cell.value or "").split())
            if not _is_question(text):
                continue
            section = " ".join(str(ws.cell(row=cell.row, column=s_col).value or "").split()) if s_col else None
            out.append({"question": text, "section": section or None, "locator": {"sheet": ws.title, "row": cell.row, "col": q_col, "answer_col": a_col}})
    return out


def _heading(p) -> bool:
    return (p.style is not None and (p.style.name or "").lower().startswith("heading")) or bool(re.match(r"^(section|part)\s+\w+[:.]", p.text.strip(), re.I))


def detect_docx(data: bytes) -> list[dict]:
    import docx

    d = docx.Document(BytesIO(data))
    out, section = [], None
    for i, p in enumerate(d.paragraphs):
        t = " ".join(p.text.split())
        if not t:
            continue
        if _heading(p) and not t.endswith("?"):
            section = t[:200]
            continue
        if _is_question(t) and t.endswith("?"):
            out.append({"question": t, "section": section, "locator": {"paragraph": i}})
    for ti, table in enumerate(d.tables):
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                t = " ".join(cell.text.split())
                if _is_question(t) and t.endswith("?"):
                    out.append({"question": t, "section": section, "locator": {"table": ti, "row": ri, "cell": ci}})
                    break
    return out


def detect_pdf(data: bytes) -> list[dict]:
    from pypdf import PdfReader

    out = []
    for pn, page in enumerate(PdfReader(BytesIO(data)).pages, start=1):
        buf: list[str] = []
        for line in (page.extract_text() or "").splitlines():
            t = " ".join(line.split())
            if not t:
                buf = []
                continue
            starts = bool(re.match(r"^(\(?[A-Za-z]?\d+[.)]|[A-Z]{1,4}-\d+|Q\d+)", t))
            if starts:
                buf = []
            buf.append(t)
            if t.endswith("?"):
                q = " ".join(buf)
                if _is_question(q):
                    out.append({"question": q, "section": None, "locator": {"page": pn}})
                buf = []
            elif t.endswith((".", ":")) and not starts:
                buf = []
    return out


def detect(fmt: str, data: bytes) -> list[dict]:
    from app.core.xlsx_guard import WorkbookTooLarge

    try:
        return {"xlsx": detect_xlsx, "docx": detect_docx, "pdf": detect_pdf}[fmt](data)
    except Invalid:
        raise
    except WorkbookTooLarge as exc:
        raise Invalid(str(exc), [{"field": "file", "message": str(exc)}]) from None
    except Exception:  # noqa: BLE001 - a damaged file
        raise Invalid("This file could not be read. Upload the questionnaire as XLSX, DOCX or PDF.", [{"field": "file", "message": "Unreadable file."}]) from None


def create(db: Session, settings, actor: User, org: Organization, data: bytes, filename: str, customer_name: str | None, title: str | None, due_date: str | None) -> Questionnaire:
    from app.files.service import upload

    fmt = FORMATS.get(Path(filename or "").suffix.lower())
    if fmt is None:
        raise Invalid("Upload the questionnaire as an Excel workbook (XLSX), a Word document (DOCX) or a PDF.", [{"field": "file", "message": "Use XLSX, DOCX or PDF."}])
    found = detect(fmt, data)
    if not found:
        raise Invalid("No questions were found in this file. Questions should end with a question mark, or sit in a column headed \"Question\".", [{"field": "file", "message": "No questions found."}])
    due = None
    if due_date:
        try:
            due = date.fromisoformat(due_date)
        except ValueError:
            raise Invalid(errors=[{"field": "due_date", "message": "Enter a date."}]) from None
    f = upload(db, settings, actor, data=data, filename=filename, content_type=None, organization_id=org.id, linked_type="customer_questionnaire")
    q = Questionnaire(organization_id=org.id, title=(" ".join(str(title or "").split()) or Path(filename).stem.replace("_", " "))[:200], customer_name=(customer_name or "").strip()[:200] or None,
                      file_id=f.id, format=fmt, status="in_progress", due_date=due, created_by=actor.id)
    db.add(q)
    db.flush()
    f.linked_id = q.id
    for n, x in enumerate(found):
        db.add(QuestionnaireItem(organization_id=org.id, questionnaire_id=q.id, order=n, locator=x["locator"], section=x["section"], question=x["question"][:4000], status="open",
                                 citations=[], created_by=actor.id))
    db.flush()
    audit.record(db, actor_id=actor.id, action="questionnaire.upload", obj=q, after={"items": len(found), "format": fmt}, summary=f"Uploaded questionnaire {q.title} ({len(found)} questions)")
    return q


def items(db: Session, q: Questionnaire) -> list[QuestionnaireItem]:
    return list(db.scalars(select(QuestionnaireItem).where(QuestionnaireItem.questionnaire_id == q.id, QuestionnaireItem.deleted_at.is_(None)).order_by(QuestionnaireItem.order)))


# ---- sources
def _signed_report(db: Session, org_id: str):
    from app.reports.models import Report

    return db.scalar(select(Report).where(Report.organization_id == org_id, Report.status == "final", Report.signed_at.is_not(None), Report.deleted_at.is_(None))
                     .order_by(Report.signed_at.desc()).limit(1))


def _policies(db: Session, org_id: str) -> list[dict]:
    """Published policies from the policy builder (WS-I), when that module is installed."""
    try:
        from app.policies.models import PolicyDocument  # type: ignore[import-not-found]
    except ImportError:
        return []
    out = []
    try:
        rows = db.scalars(select(PolicyDocument).where(PolicyDocument.organization_id == org_id, PolicyDocument.status == "published", PolicyDocument.deleted_at.is_(None)))
        for p in rows:
            text = next((getattr(p, k) for k in ("body_md", "body", "content", "text") if isinstance(getattr(p, k, None), str)), None)
            if text:
                out.append({"id": p.id, "label": getattr(p, "title", None) or "Policy", "text": text})
    except Exception:  # noqa: BLE001 - a different shape than expected: read no policies rather than fail
        return []
    return out


def sources(db: Session, org_id: str) -> list[dict]:
    out = []
    for n, li in enumerate(db.scalars(select(AnswerLibraryItem).where(AnswerLibraryItem.organization_id == org_id, AnswerLibraryItem.archived_at.is_(None),
                                                                       AnswerLibraryItem.deleted_at.is_(None)).order_by(AnswerLibraryItem.created_at))):
        out.append({"ref": f"L{n + 1}", "kind": "library", "id": li.id, "label": "Answer library", "question": li.question, "answer": li.answer, "text": li.answer,
                    "audited": li.audited_by_futran})
    for n, p in enumerate(_policies(db, org_id)):
        out.append({"ref": f"P{n + 1}", "kind": "policy", "id": p["id"], "label": p["label"], "text": p["text"], "audited": False})
    r = _signed_report(db, org_id)
    if r is not None:
        text, chunks, cur = r.body_md or "", [], ""
        for para in text.split("\n"):
            if cur and len(cur) + len(para) > PAGE_CHARS:
                chunks.append(cur)
                cur = ""
            cur = f"{cur}\n{para}" if cur else para
        if cur:
            chunks.append(cur)
        for n, c in enumerate(chunks):
            out.append({"ref": f"R{n + 1}", "kind": "report", "id": r.id, "label": f"Futran audit report {r.version}, signed {r.signed_at:%d %B %Y}", "text": c, "audited": True})
    return out


# ---- drafting and review
BATCH_ITEMS = 20  # questions per model call, so the drafted answers fit well inside the model's reply limit
CUT_NOTE = "(Some source text was left out because the set is long. Do not answer from text you were not given.)"


def _capped_sources(srcs: list[dict]) -> tuple[list[dict], bool]:
    """The sources sent with every call, in order (library, policies, signed report), up to ai.MAX_PROMPT_CHARS of text.
    A source that does not fit is left out (and the prompt says so); a later, shorter one may still fit."""
    out, used, cut = [], 0, False
    for s in srcs:
        n = len(s["text"]) + len(s.get("question") or "")
        if used + n > ai.MAX_PROMPT_CHARS:
            cut = True
            continue
        out.append(s)
        used += n
    return out, cut


def draft(db: Session, app_state, settings, actor: User, q: Questionnaire, engagement) -> dict:
    """Draft answers BATCH_ITEMS questions per call. Answers from calls that succeed are kept even when another call
    fails; the result says how many questions were not drafted. When every call fails nothing is saved (503)."""
    ai.require_ai(engagement)
    todo = [i for i in items(db, q) if i.status in ("open", "suggested", "unsupported", "rejected")]
    if not todo:
        raise Conflict("Every question already has an approved answer.")
    srcs, cut = _capped_sources(sources(db, q.organization_id))
    src_text = "\n\n".join(f"[{s['ref']}] {s['label']}" + (f"\nQuestion: {s['question']}\nAnswer: {s['answer']}" if s["kind"] == "library" else f"\n{s['text']}") for s in srcs) or "(no sources)"
    if cut:
        src_text += f"\n\n{CUT_NOTE}"
    by_src = {s["ref"]: s for s in srcs}
    refs_all = list({f"Q{n + 1}": it for n, it in enumerate(todo)}.items())
    batches = [dict(refs_all[n:n + BATCH_ITEMS]) for n in range(0, len(refs_all), BATCH_ITEMS)]
    failed, not_drafted, error = 0, 0, None
    for refs in batches:
        prompt = (f"Customer: {q.customer_name or 'not named'}\nQuestionnaire: {q.title}\n\nQuestions:\n" + "\n".join(f"- {k}: {it.question}" for k, it in refs.items()) +
                  f"\n\nSources:\n{src_text}")
        try:
            c = ai.call(app_state, settings, task="questionnaire", prompt_version=P.QUESTIONNAIRE_VERSION, system=P.QUESTIONNAIRE_SYSTEM, prompt=prompt, schema=P.QUESTIONNAIRE_SCHEMA,
                        context={"items": [{"ref": k, "question": it.question} for k, it in refs.items()], "sources": srcs})
        except ai.AIUnavailable as ex:
            failed, not_drafted, error = failed + 1, not_drafted + len(refs), ex
            continue
        by_ref = {x.get("item"): x for x in c.reply.data.get("answers") or [] if isinstance(x, dict)}
        rows = []
        for n, (k, it) in enumerate(refs.items()):
            x = by_ref.get(k) or {}
            src = by_src.get(x.get("source"))
            quote = str(x.get("quote") or "").strip()
            found = bool(src and quote and quote_in(src["text"] if src["kind"] != "library" else f"{src['question']} {src['answer']}", quote))
            answer = str(x.get("answer") or "").strip()
            supported = bool(answer) and found
            cite = [{"source_type": src["kind"], "source_id": src["id"], "label": src["label"], "quote": quote[:2000], "found": found}] if src else []
            row = ai.record(db, actor, c, organization_id=q.organization_id, feature="questionnaire", input_refs=[{"type": "questionnaire_item", "id": it.id}] + [{"type": s["kind"], "id": s["id"]} for s in srcs],
                            target_type="questionnaire_item", target_id=it.id, target_code=k, output={"answer": answer or None}, citations=cite, confidence=x.get("confidence"),
                            status="suggested" if supported else "unsupported", first=n == 0)
            rows.append(row)
            it.answer, it.status, it.citations, it.confidence = (answer or None), row.status, cite, row.confidence
            it.audited_by_futran = bool(supported and src and src["kind"] == "report")  # a proposal: the approver confirms it or it is dropped
            it.audited_confirmed_by = it.audited_confirmed_at = None
            it.interaction_id, it.decided_by, it.decided_at, it.updated_by = row.id, None, None, actor.id
        ai.log_call(db, actor, c, rows, f"Drafted answers for {len(rows)} question{'s' if len(rows) != 1 else ''} of {q.title}", None, q.organization_id)
    if failed == len(batches) and error is not None:
        raise error
    message = (f"{not_drafted} question{'s were' if not_drafted != 1 else ' was'} not drafted because the model did not answer ({failed} of {len(batches)} batches). "
               "Draft answers again to retry them.") if failed else None
    return {"batches": len(batches), "failed_batches": failed, "not_drafted": not_drafted, "sources_cut": cut, "message": message}


def _grow_library(db: Session, actor: User, it: QuestionnaireItem) -> AnswerLibraryItem:
    key = normalise(it.question)
    li = next((x for x in db.scalars(select(AnswerLibraryItem).where(AnswerLibraryItem.organization_id == it.organization_id, AnswerLibraryItem.archived_at.is_(None),
                                                                      AnswerLibraryItem.deleted_at.is_(None))) if normalise(x.question) == key), None)
    if li is None:
        li = AnswerLibraryItem(organization_id=it.organization_id, question=it.question, answer=it.answer or "", tags=[], source="questionnaire", source_item_id=it.id, created_by=actor.id)
        db.add(li)
    li.answer, li.audited_by_futran, li.citations, li.approved_by, li.approved_at, li.updated_by = it.answer or "", _confirmed(it), it.citations or [], actor.id, utcnow(), actor.id
    db.flush()
    it.library_item_id = li.id
    return li


def _confirmed(it: QuestionnaireItem) -> bool:
    return bool(it.audited_by_futran and it.audited_confirmed_at is not None)


def accept(db: Session, actor: User, it: QuestionnaireItem, answer: str | None, confirm_audited: bool = False) -> QuestionnaireItem:
    """Approve a draft. A proposed "Audited by Futran" label is kept only when the approver confirms it here."""
    if it.status == "unsupported":
        raise Conflict("This draft has no supporting passage in your sources, so it cannot be approved. Write the answer yourself.")
    if it.status != "suggested":
        raise Conflict("Only a drafted answer can be approved here.")
    i = db.get(AIInteraction, it.interaction_id)
    edited = answer is not None and " ".join(answer.split()) and answer.strip() != (it.answer or "")
    if confirm_audited is True and (edited or not it.audited_by_futran):
        raise Invalid(errors=[{"field": "confirm_audited", "message": "Only an unedited answer drawn from the signed Futran report can carry the Audited by Futran label."}])
    if edited:
        it.answer = answer.strip()[:8000]
    if confirm_audited is True:
        it.audited_confirmed_by, it.audited_confirmed_at = actor.id, utcnow()
        audit.record(db, actor_id=actor.id, action="questionnaire.audited_label", obj=it, after={"answer": it.answer, "citations": it.citations or []},
                     summary=f"Confirmed the Audited by Futran label for: {it.question[:100]}")
    else:
        it.audited_by_futran = False  # not confirmed: the label is dropped
    it.status, it.decided_by, it.decided_at, it.updated_by = "edited" if edited else "accepted", actor.id, utcnow(), actor.id
    li = _grow_library(db, actor, it)
    if i is not None:
        ai.decide(db, actor, i, "edited" if edited else "accepted", result_refs=[{"type": "answer_library_item", "id": li.id}])
    return it


def reject(db: Session, actor: User, it: QuestionnaireItem, reason: str | None) -> QuestionnaireItem:
    if it.status not in ("suggested", "unsupported"):
        raise Conflict("Only a drafted answer can be rejected.")
    reason = " ".join(str(reason or "").split()) or "Not used."
    i = db.get(AIInteraction, it.interaction_id)
    it.status, it.answer, it.audited_by_futran, it.updated_by = "rejected", None, False, actor.id
    if i is not None:
        ai.decide(db, actor, i, "rejected", reason[:2000])
    return it


def answer_manually(db: Session, actor: User, it: QuestionnaireItem, answer) -> QuestionnaireItem:
    text = str(answer or "").strip()
    if not text:
        raise Invalid(errors=[{"field": "answer", "message": "Write the answer."}])
    i = db.get(AIInteraction, it.interaction_id) if it.interaction_id else None
    if i is not None and i.status in ("suggested", "unsupported"):
        ai.decide(db, actor, i, "rejected", "The reviewer wrote the answer.")
    it.answer, it.status, it.audited_by_futran, it.citations, it.decided_by, it.decided_at, it.updated_by = text[:8000], "answered", False, [], actor.id, utcnow(), actor.id
    _grow_library(db, actor, it)
    audit.record(db, actor_id=actor.id, action="questionnaire.answer", obj=it, summary=f"Answered a questionnaire question: {it.question[:100]}")
    return it


# ---- export
def _final(it: QuestionnaireItem) -> str | None:
    if it.status not in ("accepted", "edited", "answered") or not it.answer:
        return None
    return f"{it.answer} [{AUDITED}]" if _confirmed(it) else it.answer


def export(db: Session, settings, q: Questionnaire) -> tuple[bytes, str, str]:
    from app.files.service import read

    f = db.get(FileObject, q.file_id)
    data = read(settings, f)
    stem = Path(f.filename).stem
    rows = items(db, q)
    if q.format == "xlsx":
        from app.core import xlsx_guard

        wb = xlsx_guard.open_workbook(data, max_rows=XLSX_MAX_ROWS, max_cols=XLSX_MAX_COLS, read_only=False, data_only=False)
        for it in rows:
            a = _final(it)
            if a is not None:
                loc = it.locator
                wb[loc["sheet"]].cell(row=loc["row"], column=loc["answer_col"]).value = a
        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue(), f"{stem} - answers.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    import docx
    from docx.oxml import OxmlElement
    from docx.text.paragraph import Paragraph

    if q.format == "docx":
        d = docx.Document(BytesIO(data))
        paras = d.paragraphs
        for it in sorted([x for x in rows if "paragraph" in x.locator], key=lambda x: -x.locator["paragraph"]):
            a = _final(it)
            if a is None:
                continue
            p = paras[it.locator["paragraph"]]
            new = OxmlElement("w:p")
            p._p.addnext(new)
            Paragraph(new, p._parent).add_run(f"Answer: {a}")
        for it in [x for x in rows if "table" in x.locator]:
            a = _final(it)
            if a is None:
                continue
            row = d.tables[it.locator["table"]].rows[it.locator["row"]]
            cells = row.cells
            target = cells[it.locator["cell"] + 1] if it.locator["cell"] + 1 < len(cells) else cells[it.locator["cell"]]
            if target is cells[it.locator["cell"]]:
                target.add_paragraph(f"Answer: {a}")
            else:
                target.text = a
        buf = BytesIO()
        d.save(buf)
        return buf.getvalue(), f"{stem} - answers.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    d = docx.Document()
    d.add_heading(q.title, level=1)
    d.add_paragraph(f"Answers for {q.customer_name or 'the customer'}. The original was a PDF, which cannot be edited in place, so the answers are given here in the order of the "
                    f"questionnaire ({f.filename}).")
    for it in rows:
        d.add_paragraph(it.question, style="List Number")
        d.add_paragraph(f"Answer: {_final(it) or 'Not answered.'}")
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue(), f"{stem} - answers.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def item_out(it: QuestionnaireItem) -> dict:
    return {"id": it.id, "order": it.order, "locator": it.locator, "section": it.section, "question": it.question, "answer": it.answer, "status": it.status, "citations": it.citations or [],
            "confidence": it.confidence, "audited_by_futran": it.audited_by_futran, "audited_confirmed": _confirmed(it), "decided_at": it.decided_at.isoformat() if it.decided_at else None}


def questionnaire_out(db: Session, q: Questionnaire, with_items: bool = True) -> dict:
    rows = items(db, q)
    f = db.get(FileObject, q.file_id)
    out = {"id": q.id, "title": q.title, "customer_name": q.customer_name, "format": q.format, "status": q.status, "filename": f.filename if f else None,
           "due_date": q.due_date.isoformat() if q.due_date else None, "created_at": q.created_at.isoformat() if q.created_at else None,
           "counts": {"questions": len(rows), "approved": sum(r.status in ("accepted", "edited", "answered") for r in rows), "to_review": sum(r.status in ("suggested", "unsupported") for r in rows),
                      "open": sum(r.status in ("open", "rejected") for r in rows), "audited": sum(_confirmed(r) and r.status in ("accepted", "edited") for r in rows)}}
    if with_items:
        out["items"] = [item_out(r) for r in rows]
    return out


def library_out(li: AnswerLibraryItem) -> dict:
    return {"id": li.id, "question": li.question, "answer": li.answer, "tags": li.tags or [], "source": li.source, "audited_by_futran": li.audited_by_futran,
            "approved_at": li.approved_at.isoformat() if li.approved_at else None}
