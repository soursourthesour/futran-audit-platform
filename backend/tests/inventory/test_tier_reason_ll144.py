"""BUG-02: the Tier 3 reason names NYC Local Law 144 only for employment decisions in New York City."""
from app.inventory.service import tier_reason

LL144 = "Local Law 144"


def test_a_consequential_use_case_outside_new_york_city_does_not_mention_ll144():
    reason = tier_reason("consequential", ["pii"], [], text="Credit scoring for consumer loans in Germany")
    assert "decisions about people" in reason
    assert LL144 not in reason


def test_the_default_call_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [])


def test_employment_use_outside_new_york_city_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [], text="Résumé screening for Berlin roles", in_nyc=False)


def test_non_employment_use_in_new_york_city_does_not_mention_ll144():
    assert LL144 not in tier_reason("consequential", [], [], text="Fraud scoring of card payments", in_nyc=True)


def test_employment_use_in_new_york_city_mentions_ll144():
    reason = tier_reason("consequential", [], [], text="Résumé screening: ranks applicants for recruiters", in_nyc=True)
    assert "decisions about people" in reason and LL144 in reason


def test_an_aedt_determined_in_scope_mentions_ll144():
    assert LL144 in tier_reason("consequential", [], [], aedt_determination="in_scope")


def test_lower_tier_reasons_never_mention_ll144():
    for args in (("informs", ["pii"], []), ("none", [], [])):
        assert LL144 not in tier_reason(*args, text="Hiring", in_nyc=True)
