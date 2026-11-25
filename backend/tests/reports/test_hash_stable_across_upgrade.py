"""Review 11-25 #3: the 25 Nov upgrade adds the EU AI Act level to the system table and rewords the severity headings.
Neither may change the hash a signed v0.2 was sealed with, or every engagement would need its v0.2 signed again."""
import hashlib
import json

from app.reports import service as rs


def _legacy_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def test_eu_level_and_new_severity_headings_do_not_change_the_hash():
    item = {"ref": "F-1", "severity": "high"}
    before = {"systems": [{"ref": "AIS-1", "name": "Screener", "use_cases": "Résumé screening"}],
              "findings_by_severity": [{"label": "High findings (4)", "items": [item]}, {"label": "Observations (1)", "items": [{"ref": "O-1", "severity": "observation"}]}]}
    after = {"systems": [{"ref": "AIS-1", "name": "Screener", "use_cases": "Résumé screening", "eu_level": "High-risk"}],
             "findings_by_severity": [{"label": rs.GROUP_LABEL["high"], "items": [item]}, {"label": rs.GROUP_LABEL["observation"], "items": [{"ref": "O-1", "severity": "observation"}]}]}
    assert rs.GROUP_LABEL["high"] != "High findings (4)"  # the wording did change
    assert rs._hash(after) == _legacy_hash(before)


def test_real_changes_still_change_the_hash():
    a = {"systems": [{"ref": "AIS-1", "name": "Screener", "eu_level": "High-risk"}], "findings_by_severity": []}
    b = {"systems": [{"ref": "AIS-1", "name": "Screener v2", "eu_level": "High-risk"}], "findings_by_severity": []}
    assert rs._hash(a) != rs._hash(b)
