"""Client screen /questionnaires (spec §21 F10): customer questionnaires and the answer library. Client Admin and CAICO.
AI drafting needs AI turned on for the client's current engagement (§21 rule 4); upload, manual answers and export do not."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import questionnaires as qn
from app.ai import service as ai
from app.ai.models import AnswerLibraryItem, Questionnaire, QuestionnaireItem
from app.audit_log import service as audit
from app.auth.deps import Actor, current_actor
from app.core.clock import utcnow
from app.core.db import get_db
from app.core.errors import Invalid, NotFound
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.people import current_engagement

router = APIRouter(tags=["questionnaires"])


class AnswerIn(BaseModel):
    answer: str | None = None
    confirm_audited: bool = False  # the approver confirms the "Audited by Futran" label a draft proposed


class ReasonIn(BaseModel):
    reason: str | None = None


class LibraryIn(BaseModel):
    question: str | None = None
    answer: str | None = None
    tags: list[str] = []


def _client(db: Session, actor: Actor) -> None:
    if actor.is_futran:
        raise NotFound()
    authorize(db, actor, Action.USE_QUESTIONNAIRES, org_id=actor.organization.id)


def _q(db: Session, actor: Actor, qid: str) -> Questionnaire:
    _client(db, actor)
    q = db.get(Questionnaire, qid)
    if q is None or q.deleted_at is not None or q.organization_id != actor.organization.id:
        raise NotFound()
    return q


def _item(db: Session, q: Questionnaire, item_id: str) -> QuestionnaireItem:
    it = db.get(QuestionnaireItem, item_id)
    if it is None or it.questionnaire_id != q.id or it.deleted_at is not None:
        raise NotFound()
    return it


@router.get("/questionnaires")
def list_questionnaires(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _client(db, actor)
    org = actor.organization
    rows = db.scalars(select(Questionnaire).where(Questionnaire.organization_id == org.id, Questionnaire.deleted_at.is_(None)).order_by(Questionnaire.created_at.desc()))
    lib = db.scalars(select(AnswerLibraryItem.id).where(AnswerLibraryItem.organization_id == org.id, AnswerLibraryItem.archived_at.is_(None), AnswerLibraryItem.deleted_at.is_(None))).all()
    return {"ai_enabled": ai.ai_enabled(current_engagement(db, org)), "has_signed_report": qn._signed_report(db, org.id) is not None, "library_count": len(lib),
            "rows": [qn.questionnaire_out(db, q, with_items=False) for q in rows]}


@router.post("/questionnaires")
def upload_questionnaire(request: Request, file: UploadFile = File(...), customer_name: str | None = Form(None), title: str | None = Form(None), due_date: str | None = Form(None),
                         actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _client(db, actor)
    settings = request.app.state.settings
    data = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not data:
        raise Invalid(errors=[{"field": "file", "message": "The file is empty."}])
    q = qn.create(db, settings, actor.user, actor.organization, data, file.filename or "questionnaire", customer_name, title, due_date)
    return qn.questionnaire_out(db, q)


@router.get("/questionnaires/{qid}")
def get_questionnaire(qid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    return qn.questionnaire_out(db, q) | {"ai_enabled": ai.ai_enabled(current_engagement(db, actor.organization))}


@router.post("/questionnaires/{qid}/draft")
def draft_answers(qid: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    res = qn.draft(db, request.app.state, request.app.state.settings, actor.user, q, current_engagement(db, actor.organization))
    return qn.questionnaire_out(db, q) | {"draft": res}


@router.post("/questionnaires/{qid}/items/{item_id}/accept")
def accept_item(qid: str, item_id: str, body: AnswerIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    return qn.item_out(qn.accept(db, actor.user, _item(db, q, item_id), body.answer, body.confirm_audited))


@router.post("/questionnaires/{qid}/items/{item_id}/reject")
def reject_item(qid: str, item_id: str, body: ReasonIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    return qn.item_out(qn.reject(db, actor.user, _item(db, q, item_id), body.reason))


@router.put("/questionnaires/{qid}/items/{item_id}")
def answer_item(qid: str, item_id: str, body: AnswerIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    return qn.item_out(qn.answer_manually(db, actor.user, _item(db, q, item_id), body.answer))


@router.post("/questionnaires/{qid}/complete")
def complete(qid: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    q.status, q.completed_at, q.completed_by = "completed", utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="questionnaire.complete", obj=q, summary=f"Marked questionnaire {q.title} complete")
    return qn.questionnaire_out(db, q)


@router.get("/questionnaires/{qid}/export")
def export(qid: str, request: Request, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    q = _q(db, actor, qid)
    data, name, ctype = qn.export(db, request.app.state.settings, q)
    audit.record(db, actor_id=actor.id, action="questionnaire.export", obj=q, summary=f"Exported questionnaire {q.title}")
    return Response(content=data, media_type=ctype, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@router.get("/answer-library")
def library(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _client(db, actor)
    rows = db.scalars(select(AnswerLibraryItem).where(AnswerLibraryItem.organization_id == actor.organization.id, AnswerLibraryItem.archived_at.is_(None),
                                                      AnswerLibraryItem.deleted_at.is_(None)).order_by(AnswerLibraryItem.question))
    return {"rows": [qn.library_out(li) for li in rows]}


@router.post("/answer-library")
def add_library(body: LibraryIn, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _client(db, actor)
    q, a = " ".join(str(body.question or "").split()), str(body.answer or "").strip()
    errs = ([{"field": "question", "message": "Enter the question."}] if not q else []) + ([{"field": "answer", "message": "Enter the approved answer."}] if not a else [])
    if errs:
        raise Invalid(errors=errs)
    li = AnswerLibraryItem(organization_id=actor.organization.id, question=q[:4000], answer=a[:8000], tags=[t.strip()[:40] for t in body.tags if t.strip()][:10], source="manual",
                           approved_by=actor.id, approved_at=utcnow(), citations=[], created_by=actor.id)
    db.add(li)
    db.flush()
    audit.record(db, actor_id=actor.id, action="answer_library.add", obj=li, summary=f"Added an approved answer to the library: {q[:100]}")
    return qn.library_out(li)


@router.post("/answer-library/{item_id}/archive")
def archive_library(item_id: str, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    _client(db, actor)
    li = db.get(AnswerLibraryItem, item_id)
    if li is None or li.organization_id != actor.organization.id or li.archived_at is not None:
        raise NotFound()
    li.archived_at, li.updated_by = utcnow(), actor.id
    audit.record(db, actor_id=actor.id, action="answer_library.archive", obj=li, summary=f"Archived a library answer: {li.question[:100]}")
    return {"archived": True}
