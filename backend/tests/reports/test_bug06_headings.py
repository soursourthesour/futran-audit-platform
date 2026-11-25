"""BUG-06: a severity group heading must not read as a count. 'High findings (4)' looked like four findings."""
import re

from app.reports.service import GROUP_LABEL
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.reports.test_report_content import _draft
from tests.reports.test_reports import ready  # noqa: F401


def test_group_labels_name_the_severity_level():
    assert GROUP_LABEL["high"] == "High findings (severity 4)"
    assert GROUP_LABEL["observation"] == "Observations (severity 1)"
    for label in GROUP_LABEL.values():
        assert not re.search(r"\(\d+\)", label), label


def test_report_heading_names_the_severity_not_a_bare_number(client, db, ready, people):
    cid, e, maria, f = ready
    md = _draft(client, db, people, cid)
    assert "High findings (severity 4)" in md
    assert not re.search(r"^#+ .*findings \(\d+\)", md, re.M) and not re.search(r"^#+ Observations \(\d+\)", md, re.M)
