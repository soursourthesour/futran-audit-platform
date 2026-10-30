"""Email: the outbox (every message the platform sends, readable in Admin > Outbox), and from v0.5 the mailbox
connections, directory, groups, templates, sends and replies of spec §26 and §27.1.

`organization_id` is the owning organisation: the Futran organisation for Futran connections and groups, the client
for client ones. Futran's shipped templates use the constant owner id "futran".
"""
from datetime import datetime

from sqlalchemy import DDL, JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin, TimestampedTenantMixin

FUTRAN_OWNER = "futran"  # organization_id of Futran's shipped templates


class OutboxMessage(TimestampedTenantMixin, Base):
    __tablename__ = "outbox_messages"

    to: Mapped[list] = mapped_column(JSON)
    cc: Mapped[list | None] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(300))
    body_html: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    template_key: Mapped[str] = mapped_column(String(80))
    related_type: Mapped[str | None] = mapped_column(String(60))
    related_id: Mapped[str | None] = mapped_column(String(36))
    attachments: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | failed
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String(500))
    # v0.5: the send this message belongs to, and the channel it went through (outbox | smtp | microsoft365 | google)
    mail_send_id: Mapped[str | None] = mapped_column(String(36), index=True)
    channel: Mapped[str | None] = mapped_column(String(20))
    bcc: Mapped[list | None] = mapped_column(JSON)


# ---- connections (§26.1, §27.1)
class MailConnection(TimestampedTenantMixin, Base):
    """The organisation mailbox: Futran's (E1) or a client's (E2). One per organisation."""

    __tablename__ = "mail_connections"

    owner: Mapped[str] = mapped_column(String(10))  # futran | client
    provider: Mapped[str | None] = mapped_column(String(20))  # microsoft365 | google
    tenant_id: Mapped[str | None] = mapped_column(String(120))  # Entra tenant ID or Google Workspace customer
    domain: Mapped[str | None] = mapped_column(String(200))
    mailbox_address: Mapped[str | None] = mapped_column(String(254))
    send_as_name: Mapped[str | None] = mapped_column(String(200))
    reply_to: Mapped[str | None] = mapped_column(String(254))
    reply_to_mode: Mapped[str] = mapped_column(String(20), default="mailbox", server_default="mailbox")  # mailbox | chief_auditor | caico
    sender_mode: Mapped[str] = mapped_column(String(20), default="own", server_default="own")  # own | futran_on_behalf (client only)
    scopes: Mapped[list | None] = mapped_column(JSON)
    token_ref: Mapped[str | None] = mapped_column(String(40))  # key label of the encrypted token below
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    consent_by: Mapped[str | None] = mapped_column(String(254))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="not_connected", server_default="not_connected")  # not_connected | consent_requested | connected | error | disconnected
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(String(500))
    spf_ok: Mapped[bool | None] = mapped_column(Boolean)
    dkim_ok: Mapped[bool | None] = mapped_column(Boolean)
    dmarc_ok: Mapped[bool | None] = mapped_column(Boolean)
    sync_interval_min: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    options: Mapped[dict | None] = mapped_column(JSON)  # save_activity, sync_replies, track_bounces, futran_copy
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    it_request_email: Mapped[str | None] = mapped_column(String(254))
    it_request_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    test_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    test_sent_to: Mapped[str | None] = mapped_column(String(254))
    onboarding_step: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class UserMailConnection(TimestampedTenantMixin, Base):
    """One user's own mailbox (delegated OAuth, §27.1). Only threads the platform started are read back."""

    __tablename__ = "user_mail_connections"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    mailbox: Mapped[str | None] = mapped_column(String(254))
    scopes: Mapped[list | None] = mapped_column(JSON)
    token_ref: Mapped[str | None] = mapped_column(String(40))
    token_encrypted: Mapped[str | None] = mapped_column(Text)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | connected | disconnected | declined
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))


class MailOrgSettings(TimestampedTenantMixin, Base):
    """Per-organisation email settings: whether users must connect their own mailbox at first sign-in."""

    __tablename__ = "mail_org_settings"
    __table_args__ = (UniqueConstraint("organization_id", name="uq_mail_org_settings_org"),)

    per_user_sync: Mapped[str] = mapped_column(String(10), default="optional", server_default="optional")  # required | optional | off


# ---- directory (§26.2)
class DirectorySync(TimestampedTenantMixin, Base):
    __tablename__ = "directory_syncs"

    connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_connections.id"), index=True)
    scope_group: Mapped[str | None] = mapped_column(String(200))  # directory group ID; blank = everyone
    scope_group_name: Mapped[str | None] = mapped_column(String(200))
    include_guests: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    use_directory_groups: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    schedule: Mapped[str] = mapped_column(String(10), default="daily", server_default="daily")  # daily | 6h | weekly | off
    department_field: Mapped[str] = mapped_column(String(20), default="department", server_default="department")  # department | office
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    people: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    joined: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    left: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    changed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="never", server_default="never")  # never | ok | failed
    report: Mapped[dict | None] = mapped_column(JSON)


class DirectoryGroup(TimestampedTenantMixin, Base):
    """A group in the client's (or Futran's) Microsoft 365 or Google directory. Read only; never changed."""

    __tablename__ = "directory_groups"

    connection_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mail_connections.id"))
    directory_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime)


class DirectoryPerson(TimestampedTenantMixin, Base):
    """A person who can receive email: from directory sync, a user with a login, or added by hand to a list."""

    __tablename__ = "directory_people"

    directory_id: Mapped[str | None] = mapped_column(String(200), index=True)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # directory | platform | manual
    email: Mapped[str] = mapped_column(String(254), index=True)
    name: Mapped[str] = mapped_column(String(160))
    department: Mapped[str | None] = mapped_column(String(160))  # as the directory names it
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))
    job_title: Mapped[str | None] = mapped_column(String(160))
    manager_id: Mapped[str | None] = mapped_column(String(200))  # the manager's directory_id
    office: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | left | on_leave
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    directory_group_ids: Mapped[list | None] = mapped_column(JSON)
    reminders_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    left_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---- groups (§26.3)
class MailGroup(TimestampedTenantMixin, Base):
    """A group that lives only in the platform. It is expanded to people at the moment an email is sent."""

    __tablename__ = "mail_groups"

    owner: Mapped[str] = mapped_column(String(10))  # futran | client
    owner_role: Mapped[str | None] = mapped_column(String(20))  # futran_admin | client_admin (who created it, §27.1)
    name: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(10))  # manual | rule | directory
    rule: Mapped[dict | None] = mapped_column(JSON)
    directory_group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("directory_groups.id"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    system_key: Mapped[str | None] = mapped_column(String(60))  # default groups: all_employees, dept_heads, ...
    department_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("departments.id"))  # a department's own group
    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"))
    exclude_on_leave: Mapped[bool] = mapped_column(Boolean, default=True)
    exclusions: Mapped[list | None] = mapped_column(JSON)  # person IDs never included
    used_by: Mapped[str | None] = mapped_column(String(200))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)


class MailGroupMember(TimestampedTenantMixin, Base):
    """A person or a nested group in a manual list. Rule and directory groups are computed, not stored."""

    __tablename__ = "mail_group_members"

    group_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_groups.id"), index=True)
    person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("directory_people.id"), index=True)
    nested_group_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mail_groups.id"))
    added_by: Mapped[str | None] = mapped_column(String(36))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---- templates (§26.6)
class MailTemplate(TimestampedTenantMixin, Base):
    """One version of a template. An edit adds a new version and marks the old one superseded."""

    __tablename__ = "mail_templates"

    owner: Mapped[str] = mapped_column(String(10))  # futran | client
    key: Mapped[str] = mapped_column(String(60), index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)  # the same for every version
    name: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(40))  # attestation | approval | evidence | notice | training | alert | initiation | general
    default_mode: Mapped[str] = mapped_column(String(10), default="personal")  # personal | bcc
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    button_label: Mapped[str | None] = mapped_column(String(80))
    merge_fields: Mapped[list | None] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    language: Mapped[str] = mapped_column(String(10), default="en")
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime)
    copied_from_id: Mapped[str | None] = mapped_column(String(36))


# ---- sends (§26.4, §26.5)
class MailSend(TimestampedTenantMixin, Base):
    """One send: to groups (E4), or a single system email (invitation, package, reminder, notice). organization_id is
    the client the email concerns, or the Futran organisation."""

    __tablename__ = "mail_sends"

    engagement_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("engagements.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="group")  # group | system | test | reminder
    template_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mail_templates.id"))
    template_version: Mapped[int | None] = mapped_column(Integer)
    template_key: Mapped[str | None] = mapped_column(String(80))
    template_name: Mapped[str | None] = mapped_column(String(160))
    subject: Mapped[str | None] = mapped_column(String(300))
    sender_connection_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mail_connections.id"))
    sender_user_id: Mapped[str | None] = mapped_column(String(36))  # a user's own mailbox (§27.1)
    sender_label: Mapped[str | None] = mapped_column(String(300))
    channel: Mapped[str | None] = mapped_column(String(20))  # outbox | smtp | microsoft365 | google
    groups: Mapped[list | None] = mapped_column(JSON)  # [{id, name}]
    exclusions: Mapped[list | None] = mapped_column(JSON)  # [{id, name}] groups, plus "responded"
    mode: Mapped[str] = mapped_column(String(10), default="personal")  # personal | bcc | direct
    batch_size: Mapped[int | None] = mapped_column(Integer)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_by: Mapped[str | None] = mapped_column(String(36))
    sent_by_name: Mapped[str | None] = mapped_column(String(200))
    reminder_plan: Mapped[list | None] = mapped_column(JSON)  # days after sending, e.g. [3, 7]
    link_days: Mapped[int] = mapped_column(Integer, default=14)
    campaign_type: Mapped[str | None] = mapped_column(String(30))  # attestation | ...
    campaign_id: Mapped[str | None] = mapped_column(String(36))
    context: Mapped[dict | None] = mapped_column(JSON)  # merge values given by the caller
    expansion: Mapped[list | None] = mapped_column(JSON)  # [{label, count, kind}] as shown before sending
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(12), default="queued")  # scheduled | queued | sending | sent
    shared_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # BCC mode: one shared link
    shared_link_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    parent_send_id: Mapped[str | None] = mapped_column(String(36))  # a reminder's original send
    department_scope: Mapped[list | None] = mapped_column(JSON)  # a Department Compliance Lead's own departments
    related_type: Mapped[str | None] = mapped_column(String(60))
    related_id: Mapped[str | None] = mapped_column(String(36))
    retain_until: Mapped[datetime | None] = mapped_column(DateTime)


class MailRecipient(TimestampedTenantMixin, Base):
    __tablename__ = "mail_recipients"

    send_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_sends.id"), index=True)
    person_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("directory_people.id"), index=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    name: Mapped[str | None] = mapped_column(String(160))
    link_token_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # sha256 of the personal link token
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    link_revoked_at: Mapped[datetime | None] = mapped_column(DateTime)  # a resend replaced this link
    provider_message_id: Mapped[str | None] = mapped_column(String(300))
    provider_thread_id: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="queued")  # queued | sent | delivered | bounced | opened | completed
    reminders_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(String(500))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    batch_no: Mapped[int | None] = mapped_column(Integer)  # BCC mode
    out_of_office: Mapped[bool] = mapped_column(Boolean, default=False)


class MailOneTimeCode(TimestampedTenantMixin, Base):
    """A 6-digit code for a shared (BCC) link: proves the person reads the work email they typed (§26.5)."""

    __tablename__ = "mail_one_time_codes"

    send_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_sends.id"), index=True)
    recipient_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_recipients.id"))
    email: Mapped[str] = mapped_column(String(254))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    proof_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime)


# ---- replies (§26.2)
class MailThread(TimestampedTenantMixin, Base):
    __tablename__ = "mail_threads"

    send_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("mail_sends.id"), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    connection_id: Mapped[str | None] = mapped_column(String(36))
    user_connection_id: Mapped[str | None] = mapped_column(String(36))
    provider_thread_id: Mapped[str | None] = mapped_column(String(300))
    subject_ref: Mapped[str] = mapped_column(String(20), unique=True)  # FAP-1042
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime)


class MailReply(TimestampedTenantMixin, Base):
    __tablename__ = "mail_replies"

    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("mail_threads.id"), index=True)
    recipient_id: Mapped[str | None] = mapped_column(String(36))
    provider_message_id: Mapped[str | None] = mapped_column(String(300), index=True)
    from_address: Mapped[str | None] = mapped_column(String(254))
    received_at: Mapped[datetime] = mapped_column(DateTime)
    subject: Mapped[str | None] = mapped_column(String(300))
    snippet: Mapped[str | None] = mapped_column(String(500))
    attachment_ids: Mapped[list | None] = mapped_column(JSON)
    kind: Mapped[str] = mapped_column(String(12), default="reply")  # reply | out_of_office | bounce
    linked_entity: Mapped[str | None] = mapped_column(String(80))


# ---- admin log (§26.7): append-only, kept 7 years
class AdminLogEntry(IdMixin, Base):
    __tablename__ = "admin_log"

    owner: Mapped[str] = mapped_column(String(10))  # futran | client
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    engagement_id: Mapped[str | None] = mapped_column(String(36), index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20), index=True)  # connection | consent | sender | group | directory | send | template | settings
    action: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict | None] = mapped_column(JSON)
    send_id: Mapped[str | None] = mapped_column(String(36))
    department_id: Mapped[str | None] = mapped_column(String(36))
    retain_until: Mapped[datetime] = mapped_column(DateTime)


@event.listens_for(AdminLogEntry, "before_update")
def _no_update(*_):
    raise PermissionError("The admin log is append-only.")


@event.listens_for(AdminLogEntry, "before_delete")
def _no_delete(*_):
    raise PermissionError("The admin log is append-only.")


@event.listens_for(Session, "do_orm_execute")
def _no_bulk_changes(state):
    if state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and getattr(table, "name", None) == AdminLogEntry.__tablename__:
            raise PermissionError("The admin log is append-only.")


ADMIN_LOG_SQLITE_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS admin_log_no_update BEFORE UPDATE ON admin_log BEGIN SELECT RAISE(ABORT, 'admin log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS admin_log_no_delete BEFORE DELETE ON admin_log BEGIN SELECT RAISE(ABORT, 'admin log is append-only'); END",
]
ADMIN_LOG_POSTGRES_TRIGGERS = [
    "CREATE OR REPLACE FUNCTION admin_log_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'admin log is append-only'; END; $$ LANGUAGE plpgsql",
    "DROP TRIGGER IF EXISTS admin_log_no_change ON admin_log",
    "CREATE TRIGGER admin_log_no_change BEFORE UPDATE OR DELETE ON admin_log FOR EACH ROW EXECUTE FUNCTION admin_log_append_only()",
]
for _sql in ADMIN_LOG_SQLITE_TRIGGERS:
    event.listen(AdminLogEntry.__table__, "after_create", DDL(_sql).execute_if(dialect="sqlite"))
for _sql in ADMIN_LOG_POSTGRES_TRIGGERS:
    event.listen(AdminLogEntry.__table__, "after_create", DDL(_sql).execute_if(dialect="postgresql"))
