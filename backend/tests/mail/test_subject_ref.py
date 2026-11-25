"""Thread references (FAP-n) come from a counter: unique, increasing, continuing from the highest already used, and
without reading every mail thread for each email (load test BUG-V01, gap G8)."""
from sqlalchemy import event

from app.mail.models import MailCounter, MailThread
from app.mail.sending import next_subject_ref
from tests.factories import make_org


def _thread(db, org, ref):
    db.add(MailThread(organization_id=org.id, subject_ref=ref))
    db.flush()


def test_references_continue_from_the_highest_existing_thread_and_never_repeat(db):
    org = make_org(db, type="client")
    _thread(db, org, "FAP-1500")
    _thread(db, org, "FAP-1042")
    refs = [next_subject_ref(db) for _ in range(5)]
    assert refs == ["FAP-1501", "FAP-1502", "FAP-1503", "FAP-1504", "FAP-1505"]
    for r in refs:
        _thread(db, org, r)
    db.commit()
    assert next_subject_ref(db) == "FAP-1506"
    assert db.get(MailCounter, "subject_ref").value == 1506


def test_the_first_reference_on_an_empty_platform_is_fap_1000(db):
    assert next_subject_ref(db) == "FAP-1000"
    assert next_subject_ref(db) == "FAP-1001"


def test_a_reference_does_not_read_the_mail_threads_table(db, engine):
    org = make_org(db, type="client")
    for i in range(20):
        _thread(db, org, f"FAP-{2000 + i}")
    next_subject_ref(db)  # starts the counter (reads the threads once)
    seen = []

    def _watch(conn, cursor, statement, *_):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _watch)
    try:
        refs = [next_subject_ref(db) for _ in range(10)]
    finally:
        event.remove(engine, "before_cursor_execute", _watch)
    assert refs[0] == "FAP-2021" and refs[-1] == "FAP-2030"
    assert not [s for s in seen if "mail_threads" in s]
    assert len(seen) == 10  # one UPDATE ... RETURNING each


def test_a_rolled_back_send_gives_its_number_back(db):
    org = make_org(db, type="client")
    db.commit()
    assert next_subject_ref(db) == "FAP-1000"
    db.commit()
    assert next_subject_ref(db) == "FAP-1001"
    db.rollback()
    assert next_subject_ref(db) == "FAP-1001"
    assert org.id
