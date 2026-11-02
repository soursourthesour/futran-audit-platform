"""Comments and mentions (spec §21 F18).

Who sees what:
- Futran people on the engagement team (or the Chief Auditor, who sees every engagement) see every comment on objects of
  that engagement. A Futran comment is `internal` unless the author chooses `shared`.
- Client people see only `shared` comments, and only on objects their own role lets them see (a Department Compliance
  Lead: their department's systems; findings: approved and shared with the draft report, from stage 7). Their own
  comments are always `shared`.
- Comments on a finding that is not approved (a draft, or one in review) are always `internal`.
- A mention must name someone who can read the comment: the Futran engagement team, and for a shared comment also the
  client's people who can see the object. Mentions and replies notify in the app and by email (§14).
"""
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.auth.deps import Actor
from app.comments.models import OBJECT_TYPES, Comment
from app.core.clock import utcnow
from app.core.errors import Conflict, Forbidden, Invalid, NotFound
from app.engagements.models import Engagement, EngagementTeam
from app.policy.actions import Action
from app.policy.authorize import authorize
from app.tenancy.models import Organization, User
from app.tenancy.service import roles_of

EDIT_WINDOW = timedelta(minutes=15)
MAX_BODY = 4000
FINDINGS_TO_CLIENT_STAGE = 7  # findings reach the client with the draft report (app.findings.router.CLIENT_STAGE)


@dataclass
class Target:
    object_type: str
    object_id: str
    engagement: Engagement
    label: str
    shared_allowed: bool
    futran_link: str
    client_link: str
    client_visible: bool = True  # False: the object is never shown to the client (a draft finding)


def _load(db: Session, model, oid: str):
    obj = db.get(model, oid)
    if obj is None or getattr(obj, "deleted_at", None) is not None:
        raise NotFound()
    return obj


def _engagement(db: Session, eid: str) -> Engagement:
    e = db.get(Engagement, eid)
    if e is None or e.deleted_at is not None:
        raise NotFound()
    return e


def _system_dept(db: Session, system_id: str | None) -> str | None:
    from app.systems.models import AISystem

    s = db.get(AISystem, system_id) if system_id else None
    return s.department_id if s else None


def _client_check(db: Session, actor: Actor, actions: tuple[Action, ...], e: Engagement, department_id: str | None, system_id: str | None = None) -> None:
    """Pass when any action allows the client actor on this object. Department and system scopes see only their own."""
    last: Exception = NotFound()
    for a in actions:
        try:
            authorize(db, actor, a, engagement_id=e.id, department_id=department_id, system_id=system_id)
            return
        except (Forbidden, NotFound) as exc:
            last = exc
    raise last


def resolve(db: Session, actor: Actor, object_type: str, object_id: str) -> Target:
    """The object the comments sit on, as 404 when the actor cannot see it."""
    if object_type not in OBJECT_TYPES:
        raise Invalid(errors=[{"field": "object_type", "message": f"Choose one of: {', '.join(OBJECT_TYPES)}."}])
    t = _target(db, object_type, object_id)
    e = t.engagement
    if actor.is_futran:
        authorize(db, actor, Action.VIEW_ENGAGEMENT, engagement_id=e.id)
        return t
    if e.client_id != actor.organization.id or not t.client_visible:
        raise NotFound()
    _client_check(db, actor, _CLIENT_ACTIONS[object_type], e, *_client_scope(db, object_type, object_id))
    return t


_CLIENT_ACTIONS: dict[str, tuple[Action, ...]] = {
    "response": (Action.PREFILL_SYSTEM,),
    "evidence_request": (Action.UPLOAD_REQUESTED_DOCUMENT, Action.VIEW_EVIDENCE),
    "document_request": (Action.UPLOAD_REQUESTED_DOCUMENT, Action.VIEW_EVIDENCE),
    "finding": (Action.VIEW_FINDINGS_RESPONSES,),
    "remediation": (Action.VIEW_FINDINGS_RESPONSES,),
}


def _client_scope(db: Session, object_type: str, object_id: str) -> tuple[str | None, str | None]:
    """(department_id, system_id) of the object, for department and system scoped client roles."""
    from app.docrequests.models import DocumentRequest, EvidenceRequest
    from app.findings.models import Finding
    from app.questionnaire.models import Response
    from app.remediation.models import RemediationItem

    model = {"response": Response, "evidence_request": EvidenceRequest, "document_request": DocumentRequest, "finding": Finding, "remediation": RemediationItem}[object_type]
    obj = db.get(model, object_id)
    sys_id = getattr(obj, "ai_system_id", None)
    if object_type == "remediation" and obj.finding_id:
        sys_id = db.get(Finding, obj.finding_id).ai_system_id
    return _system_dept(db, sys_id), sys_id


def _target(db: Session, object_type: str, object_id: str) -> Target:
    from app.docrequests.models import DocumentRequest, EvidenceRequest
    from app.findings.models import Finding
    from app.questionnaire.models import Question, Response
    from app.remediation.models import RemediationItem

    if object_type == "finding":
        f = _load(db, Finding, object_id)
        e = _engagement(db, f.engagement_id)
        approved = f.status == "approved"
        return Target(object_type, f.id, e, f"finding {f.ref} {f.title}", approved, f"/clients/{e.client_id}/findings", "/responses",
                      client_visible=approved and e.stage >= FINDINGS_TO_CLIENT_STAGE)
    if object_type == "remediation":
        it = _load(db, RemediationItem, object_id)
        e = _engagement(db, it.engagement_id)
        f = db.get(Finding, it.finding_id) if it.finding_id else None
        visible = f is None or f.status == "approved"
        return Target(object_type, it.id, e, f"remediation item{' for ' + f.ref if f else ''}: {it.action[:80]}", visible, f"/clients/{e.client_id}/remediation", "/remediation",
                      client_visible=visible)
    if object_type == "response":
        r = _load(db, Response, object_id)
        e = _engagement(db, r.engagement_id)
        q = db.get(Question, r.question_id)
        fl = f"/systems/{r.ai_system_id}/assess" if r.ai_system_id else f"/clients/{e.client_id}/assessment"
        cl = f"/systems/{r.ai_system_id}" if r.ai_system_id else "/systems"
        return Target(object_type, r.id, e, f"question {q.code} {q.label}" if q else "a question", True, fl, cl)
    if object_type == "evidence_request":
        er = _load(db, EvidenceRequest, object_id)
        e = _engagement(db, er.engagement_id)
        fl = f"/clients/{e.client_id}/fieldwork/{er.use_case_id}" if er.use_case_id else f"/clients/{e.client_id}/documents"
        return Target(object_type, er.id, e, f"evidence request {er.ref}", True, fl, "/documents")
    dr = _load(db, DocumentRequest, object_id)
    e = _engagement(db, dr.engagement_id)
    return Target(object_type, dr.id, e, "a document request", True, f"/clients/{e.client_id}/documents", "/documents")


# ---------------------------------------------------------------- reading
def visibility_filter(actor: Actor):
    """The visibilities this actor may read."""
    return ("internal", "shared") if actor.is_futran else ("shared",)


def comment_out(db: Session, c: Comment, actor: Actor, names: dict[str, str]) -> dict:
    withdrawn = c.withdrawn_at is not None
    mine = c.author_id == actor.id
    return {
        "id": c.id, "parent_id": c.parent_id, "author": names.get(c.author_id), "author_id": c.author_id, "author_side": c.author_side, "visibility": c.visibility,
        "body": None if withdrawn else c.body, "mentions": [] if withdrawn else [{"id": i, "name": names.get(i)} for i in (c.mention_ids or [])],
        "at": c.created_at.isoformat(), "edited_at": c.edited_at.isoformat() if c.edited_at else None, "withdrawn": withdrawn,
        "withdrawn_at": c.withdrawn_at.isoformat() if withdrawn else None,
        "can_edit": mine and not withdrawn and utcnow() - c.created_at <= EDIT_WINDOW, "can_withdraw": mine and not withdrawn,
    }


def _names(db: Session, rows: list[Comment]) -> dict[str, str]:
    ids = {c.author_id for c in rows} | {i for c in rows for i in (c.mention_ids or [])}
    return {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def threads(db: Session, actor: Actor, t: Target) -> dict:
    rows = list(db.scalars(select(Comment).where(Comment.object_type == t.object_type, Comment.object_id == t.object_id, Comment.deleted_at.is_(None),
                                                 Comment.visibility.in_(visibility_filter(actor))).order_by(Comment.created_at, Comment.id)))
    names = _names(db, rows)
    roots = [c for c in rows if c.parent_id is None]
    replies: dict[str, list] = {}
    for c in rows:
        if c.parent_id:
            replies.setdefault(c.parent_id, []).append(comment_out(db, c, actor, names))
    out = [{**comment_out(db, c, actor, names), "replies": replies.get(c.id, [])} for c in roots]
    options = (["internal", "shared"] if t.shared_allowed else ["internal"]) if actor.is_futran else ["shared"]
    return {"threads": out, "shared_allowed": t.shared_allowed, "visibility_options": options, "default_visibility": options[0], "label": t.label, "can_post": True}


def counts(db: Session, actor: Actor, object_type: str, ids: list[str]) -> dict[str, int]:
    """Comment counts per object, for list screens. Objects the actor cannot see are left out."""
    visible = []
    for oid in list(dict.fromkeys(i for i in ids if i))[:500]:
        try:
            resolve(db, actor, object_type, oid)
            visible.append(oid)
        except (NotFound, Forbidden):
            continue
    if not visible:
        return {}
    rows = db.execute(select(Comment.object_id, func.count()).where(Comment.object_type == object_type, Comment.object_id.in_(visible), Comment.deleted_at.is_(None),
                                                                   Comment.withdrawn_at.is_(None), Comment.visibility.in_(visibility_filter(actor))).group_by(Comment.object_id))
    return {oid: n for oid, n in rows}


# ---------------------------------------------------------------- who can be mentioned
def _actor_for(db: Session, u: User) -> Actor:
    return Actor(user=u, organization=db.get(Organization, u.organization_id), roles=roles_of(db, u.id))


def can_read(db: Session, u: User, t: Target, visibility: str) -> bool:
    """Would `u` see a comment with this visibility on this object?"""
    if u.status != "active" or u.deleted_at is not None:
        return False
    a = _actor_for(db, u)
    if not a.is_futran and visibility != "shared":
        return False
    try:
        resolve(db, a, t.object_type, t.object_id)
    except (NotFound, Forbidden):
        return False
    return True


def mentionable(db: Session, t: Target, visibility: str) -> list[User]:
    """The Futran engagement team, and for a shared comment the client's people who can see the object."""
    team = list(db.scalars(select(User).join(EngagementTeam, EngagementTeam.user_id == User.id).where(
        EngagementTeam.engagement_id == t.engagement.id, EngagementTeam.deleted_at.is_(None), User.deleted_at.is_(None), User.status == "active").distinct()))
    people = {u.id: u for u in team}
    if visibility == "shared":
        for u in db.scalars(select(User).where(User.organization_id == t.engagement.client_id, User.deleted_at.is_(None), User.status == "active")):
            if can_read(db, u, t, "shared"):
                people[u.id] = u
    return sorted(people.values(), key=lambda u: u.name.casefold())


def _check_mentions(db: Session, t: Target, visibility: str, ids: list[str]) -> list[User]:
    ids = list(dict.fromkeys(i for i in ids or [] if i))
    if len(ids) > 20:
        raise Invalid(errors=[{"field": "mention_ids", "message": "Mention at most 20 people in one comment."}])
    allowed = {u.id: u for u in mentionable(db, t, visibility)}
    bad = [i for i in ids if i not in allowed]
    if bad:
        msg = ("An internal comment is seen by the Futran team only. Mention a client person in a shared comment."
               if visibility == "internal" else "You can mention only people who can see this item: the audit team and the client people who work on it.")
        raise Invalid(msg, errors=[{"field": "mention_ids", "message": msg}])
    return [allowed[i] for i in ids]


# ---------------------------------------------------------------- writing
def _clean_body(body: str | None) -> str:
    text = (body or "").strip()
    if not text:
        raise Invalid(errors=[{"field": "body", "message": "Write a comment."}])
    if len(text) > MAX_BODY:
        raise Invalid(errors=[{"field": "body", "message": f"Keep a comment under {MAX_BODY} characters."}])
    return text


def _link_for(u: User, t: Target, db: Session) -> str:
    org = db.get(Organization, u.organization_id)
    return t.futran_link if org.type == "futran" else t.client_link


def _notify(db: Session, settings, actor: Actor, t: Target, c: Comment, users: list[User], kind: str) -> None:
    from app.notifications.service import notify

    by_link: dict[str, list[User]] = {}
    for u in users:
        if u.id != actor.id and can_read(db, u, t, c.visibility):
            by_link.setdefault(_link_for(u, t, db), []).append(u)
    verb = "mentioned you" if kind == "comment_mention" else "replied to your comment"
    for link, people in by_link.items():
        notify(db, people, kind, f"{actor.user.name} {verb} on {t.label}"[:300], c.body[:400], link, engagement=t.engagement, settings=settings, email_template="notification")


def post(db: Session, settings, actor: Actor, t: Target, body: str | None, visibility: str | None, parent_id: str | None, mention_ids: list[str] | None) -> Comment:
    text = _clean_body(body)
    parent = None
    if parent_id:
        parent = db.get(Comment, parent_id)
        if parent is None or parent.deleted_at is not None or parent.object_type != t.object_type or parent.object_id != t.object_id \
                or parent.visibility not in visibility_filter(actor):
            raise NotFound()
        if parent.parent_id:  # one level of threading: a reply to a reply joins the thread
            parent = db.get(Comment, parent.parent_id)
        vis = parent.visibility
    elif actor.is_futran:
        vis = visibility or "internal"
        if vis not in ("internal", "shared"):
            raise Invalid(errors=[{"field": "visibility", "message": "Choose internal or shared."}])
        if vis == "shared" and not t.shared_allowed:
            raise Invalid("Comments on a finding that is not approved stay internal.", errors=[{"field": "visibility", "message": "Comments on a finding that is not approved stay internal."}])
    else:
        if visibility not in (None, "shared"):
            raise Invalid("Your comments are shared with the audit team.", errors=[{"field": "visibility", "message": "Your comments are shared with the audit team."}])
        vis = "shared"
    mentioned = _check_mentions(db, t, vis, mention_ids or [])
    c = Comment(organization_id=t.engagement.client_id, engagement_id=t.engagement.id, object_type=t.object_type, object_id=t.object_id, parent_id=parent.id if parent else None,
                author_id=actor.id, author_side="futran" if actor.is_futran else "client", visibility=vis, body=text, mention_ids=[u.id for u in mentioned],
                created_by=actor.id, updated_by=actor.id)
    db.add(c)
    db.flush()
    audit.record(db, actor_id=actor.id, action="comment.posted", obj=c, request=actor.request, summary=f"{vis.capitalize()} comment on {t.label}"[:300],
                 after={"visibility": vis, "object_type": t.object_type, "object_id": t.object_id, "mentions": c.mention_ids})
    _notify(db, settings, actor, t, c, mentioned, "comment_mention")
    if parent is not None:
        root_author = db.get(User, parent.author_id)
        if root_author is not None and root_author.id not in {u.id for u in mentioned}:
            _notify(db, settings, actor, t, c, [root_author], "comment_reply")
    return c


def _own(db: Session, actor: Actor, comment_id: str) -> tuple[Comment, Target]:
    c = db.get(Comment, comment_id)
    if c is None or c.deleted_at is not None or c.visibility not in visibility_filter(actor):
        raise NotFound()
    t = resolve(db, actor, c.object_type, c.object_id)
    if c.author_id != actor.id:
        raise Forbidden("Only the author can change a comment.")
    if c.withdrawn_at is not None:
        raise Conflict("This comment was withdrawn.")
    return c, t


def edit(db: Session, settings, actor: Actor, comment_id: str, body: str | None, mention_ids: list[str] | None) -> Comment:
    c, t = _own(db, actor, comment_id)
    if utcnow() - c.created_at > EDIT_WINDOW:
        raise Conflict("A comment can be edited for 15 minutes after posting. Add a new comment instead.")
    text = _clean_body(body)
    before = {"body": c.body, "mentions": list(c.mention_ids or [])}
    mentioned = _check_mentions(db, t, c.visibility, mention_ids if mention_ids is not None else c.mention_ids)
    new = [u for u in mentioned if u.id not in set(c.mention_ids or [])]
    c.body, c.mention_ids, c.edited_at, c.updated_by = text, [u.id for u in mentioned], utcnow(), actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="comment.edited", obj=c, request=actor.request, before=before, after={"body": c.body, "mentions": c.mention_ids},
                 summary=f"Edited a comment on {t.label}"[:300])
    _notify(db, settings, actor, t, c, new, "comment_mention")
    return c


def withdraw(db: Session, actor: Actor, comment_id: str, reason: str | None) -> Comment:
    c, t = _own(db, actor, comment_id)
    c.withdrawn_at, c.withdrawn_by, c.withdrawn_reason, c.updated_by = utcnow(), actor.id, (reason or "").strip()[:500] or None, actor.id
    db.flush()
    audit.record(db, actor_id=actor.id, action="comment.withdrawn", obj=c, request=actor.request, before={"body": c.body, "visibility": c.visibility},
                 after={"reason": c.withdrawn_reason}, summary=f"Withdrew a comment on {t.label}"[:300])
    return c


def shared_for_object(db: Session, object_type: str, object_id: str) -> list[dict]:
    """Shared, not withdrawn comments on one object, for the public API (which serves the client)."""
    rows = list(db.scalars(select(Comment).where(Comment.object_type == object_type, Comment.object_id == object_id, Comment.visibility == "shared",
                                                 Comment.withdrawn_at.is_(None), Comment.deleted_at.is_(None)).order_by(Comment.created_at)))
    names = _names(db, rows)
    return [{"id": c.id, "parent_id": c.parent_id, "author": names.get(c.author_id), "author_side": c.author_side, "body": c.body, "at": c.created_at.isoformat()} for c in rows]
