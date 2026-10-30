"""send_to_groups: the one entry point for group email (spec §26.4). WS-D client alerts build on it."""
from app.mail.groups import add_member, create_group
from app.mail.models import MailRecipient, MailSend, OutboxMessage
from app.mail.people import upsert_person
from app.mail.sending import send_to_groups
from tests.factories import make_org, make_user


def _setup(db):
    futran = make_org(db, type="futran")
    org = make_org(db, type="client")
    caico = make_user(db, org, roles=["caico"], name="Priya Shah", email="priya@abc.com")
    return futran, org, caico


def test_send_to_a_manual_group_saves_the_expanded_list_and_delivers_to_the_outbox(db, settings):
    _, org, caico = _setup(db)
    g = create_group(db, caico, org.id, name="AI-EUAct", source="manual")
    ana = upsert_person(db, org.id, email="ana@abc.com", name="Ana Ruiz")
    ben = upsert_person(db, org.id, email="ben@abc.com", name="Ben Ode", status="left")
    add_member(db, caico, g, person_id=ana.id)
    add_member(db, caico, g, person_id=ben.id)

    s = send_to_groups(db, settings, caico, organization_id=org.id, group_ids=[g.id], template_key="regulatory_change_alert")

    assert isinstance(s, MailSend)
    rows = db.query(MailRecipient).filter_by(send_id=s.id).all()
    assert [r.email for r in rows] == ["ana@abc.com"]  # the leaver is left out
    assert rows[0].status == "sent"
    assert s.recipient_count == 1
    assert [st["label"] for st in s.expansion][-1] == "Will receive"
    msgs = db.query(OutboxMessage).all()
    assert len(msgs) == 1 and msgs[0].to == ["ana@abc.com"]
