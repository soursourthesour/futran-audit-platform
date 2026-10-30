"""The regulator deadline catalogue (spec §27.3). Periods and quotes are checked against the official texts cited in
app/tracing/deadlines.py."""
from datetime import date, datetime

from app.tracing import deadlines as D

FOUND = datetime(2028, 3, 1, 9, 30)


def codes(dues):
    return [d.rule.code for d in dues]


def test_art73_periods_follow_the_kind_of_serious_incident():
    assert D.art73_rule("none") is None
    assert D.art73_rule("health").code == "eu_art73_15d"
    assert D.art73_rule("fundamental_rights").code == "eu_art73_15d"
    assert D.art73_rule("property_environment").code == "eu_art73_15d"
    assert D.art73_rule("critical_infrastructure").code == "eu_art73_2d"
    assert D.art73_rule("widespread_infringement").code == "eu_art73_2d"
    assert D.art73_rule("death").code == "eu_art73_10d"
    assert D.due_for(D.ART73_15, FOUND).due_at == datetime(2028, 3, 16, 9, 30)
    assert D.due_for(D.ART73_2, FOUND).due_at == datetime(2028, 3, 3, 9, 30)
    assert D.due_for(D.ART73_10, FOUND).due_at == datetime(2028, 3, 11, 9, 30)


def test_serious_incident_in_the_eu_tells_the_provider_first_then_the_authority():
    got = D.applicable({"eu_ai_act"}, found_at=FOUND, serious_kind="health", risk_to_rights=False, cyber_incident=False, ag_notice_received_on=None)
    assert codes(got) == ["eu_art26_provider", "eu_art73_15d"]
    provider = got[0]
    assert provider.rule.statutory is False and provider.rule.period_text == "Immediately (platform target: 24 hours)"
    assert provider.due_at == datetime(2028, 3, 2, 9, 30)
    assert "immediately inform first the provider" in provider.rule.quote


def test_not_serious_and_no_risk_needs_no_eu_notice():
    assert D.applicable({"eu_ai_act"}, found_at=FOUND, serious_kind="none", risk_to_rights=False, cyber_incident=False, ag_notice_received_on=None) == []
    got = D.applicable({"eu_ai_act"}, found_at=FOUND, serious_kind="none", risk_to_rights=True, cyber_incident=False, ag_notice_received_on=None)
    assert codes(got) == ["eu_art26_risk"] and got[0].due_at == datetime(2028, 3, 4, 9, 30)


def test_cert_in_six_hours_only_for_cyber_incidents_where_india_applies():
    assert D.applicable({"india"}, found_at=FOUND, serious_kind="death", risk_to_rights=True, cyber_incident=False, ag_notice_received_on=None) == []
    got = D.applicable({"india"}, found_at=FOUND, serious_kind="none", risk_to_rights=False, cyber_incident=True, ag_notice_received_on=None)
    assert codes(got) == ["certin_6h"] and got[0].due_at == datetime(2028, 3, 1, 15, 30) and got[0].binding
    assert "within 6 hours of noticing" in got[0].rule.quote
    # India's rule does not apply where only the EU is in scope
    assert D.applicable({"eu_ai_act"}, found_at=FOUND, serious_kind="none", risk_to_rights=False, cyber_incident=True, ag_notice_received_on=None) == []


def test_colorado_cure_period_runs_60_days_from_an_ag_notice():
    assert D.applicable({"colorado"}, found_at=FOUND, serious_kind="death", risk_to_rights=True, cyber_incident=True, ag_notice_received_on=None) == []
    got = D.applicable({"colorado"}, found_at=FOUND, serious_kind="none", risk_to_rights=False, cyber_incident=False, ag_notice_received_on=date(2028, 4, 1))
    assert codes(got) == ["co_ag_cure_60d"] and got[0].due_at == datetime(2028, 5, 31, 23, 59)


def test_eu_duties_are_not_yet_binding_before_2_december_2027():
    early = D.applicable({"eu_ai_act"}, found_at=datetime(2026, 10, 30, 8, 0), serious_kind="death", risk_to_rights=False, cyber_incident=False, ag_notice_received_on=None)
    assert [d.binding for d in early] == [False, False]
    assert "2 Dec 2027" in early[0].binding_note
    late = D.applicable({"eu_ai_act"}, found_at=datetime(2027, 12, 2, 0, 0), serious_kind="death", risk_to_rights=False, cyber_incident=False, ag_notice_received_on=None)
    assert all(d.binding for d in late)


def test_reminder_is_a_quarter_of_the_period_at_most_a_day_before():
    six = D.due_for(D.CERTIN_6H, FOUND)
    assert D.reminder_at(six.clock_start_at, six.due_at) == datetime(2028, 3, 1, 14, 0)
    fifteen = D.due_for(D.ART73_15, FOUND)
    assert D.reminder_at(fifteen.clock_start_at, fifteen.due_at) == datetime(2028, 3, 15, 9, 30)


def test_every_rule_cites_an_official_source():
    for r in D.RULES:
        assert r.source_url.startswith(("https://eur-lex.europa.eu", "https://ai-act-service-desk.ec.europa.eu", "https://www.cert-in.org.in", "https://leg.colorado.gov"))
        assert r.quote and r.citation and r.code in D.PERIODS
