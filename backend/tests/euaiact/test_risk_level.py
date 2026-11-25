"""EU AI Act risk level beside the Futran tier (11-25 change): four levels in the Commission's terms, worked out from
three screening questions, first match wins: an Art. 5 practice, then Annex I or an Annex III area (unless a documented
Art. 6(3) assessment), then an Art. 50 situation, else minimal. A signed-off EU classification overrides the screening."""
from app.euaiact import risk


def _scr(**kw):
    base = {"art5": ["none"], "annex_iii_area": "none", "annex_i": False, "art6_3_exception": False, "art50": ["none"], "gpai": False}
    return base | kw


def test_level_names_are_the_eu_terms():
    assert risk.LEVELS == {"prohibited": "Prohibited", "high_risk": "High-risk", "limited": "Limited risk", "minimal": "Minimal risk"}
    assert "low" not in risk.LEVELS


def test_unanswered_screening_is_not_screened():
    assert risk.level_for(None) == (None, "Not screened against the EU AI Act yet.")
    assert risk.level_for({"art5": ["none"]})[0] is None  # Annex III and Art. 50 still unanswered


def test_prohibited_wins_over_everything():
    level, reason = risk.level_for(_scr(art5=["emotion_work_education"], annex_iii_area="employment", art50=["interacts"]))
    assert level == "prohibited"
    assert "Art. 5(1)(f)" in reason


def test_annex_iii_area_is_high_risk():
    level, reason = risk.level_for(_scr(annex_iii_area="employment"))
    assert level == "high_risk"
    assert "Employment and workers management (point 4)" in reason


def test_annex_i_product_is_high_risk():
    assert risk.level_for(_scr(annex_i=True))[0] == "high_risk"


def test_art6_3_assessment_takes_an_annex_iii_use_out_of_high_risk():
    assert risk.level_for(_scr(annex_iii_area="employment", art6_3_exception=True))[0] == "minimal"
    assert risk.level_for(_scr(annex_iii_area="employment", art6_3_exception=True, art50=["interacts"]))[0] == "limited"
    # the exception never covers an Annex I product
    assert risk.level_for(_scr(annex_i=True, art6_3_exception=True))[0] == "high_risk"


def test_art50_situation_is_limited_risk():
    level, reason = risk.level_for(_scr(art50=["interacts", "synthetic_content"]))
    assert level == "limited"
    assert "Art. 50(1)" in reason and "Art. 50(2)" in reason


def test_nothing_applies_is_minimal_risk():
    assert risk.level_for(_scr())[0] == "minimal"


def test_gpai_is_a_flag_not_a_level():
    assert risk.level_for(_scr(gpai=True))[0] == "minimal"


def test_clean_screening_validates_and_normalises():
    errs: list = []
    out = risk.clean_screening({"art5": ["social_scoring", "none"], "annex_iii_area": "employment", "annex_i": "yes", "art50": [], "gpai": 0}, errs)
    assert errs == []
    assert out["art5"] == ["social_scoring"]  # "none" with a practice is dropped
    assert out["art50"] == []  # left unanswered, not "none"
    assert out["annex_i"] is True and out["gpai"] is False
    errs = []
    risk.clean_screening({"art5": ["mind_control"], "annex_iii_area": "astrology"}, errs)
    assert {e["field"] for e in errs} == {"eu_screening.art5", "eu_screening.annex_iii_area"}


def test_signed_off_classification_maps_to_a_level():
    assert risk.level_from_classification("prohibited") == "prohibited"
    assert risk.level_from_classification("high_risk_annex_iii") == "high_risk"
    assert risk.level_from_classification("high_risk_annex_i") == "high_risk"
    assert risk.level_from_classification("transparency") == "limited"
    assert risk.level_from_classification("minimal") == "minimal"
    assert risk.level_from_classification("gpai") is None  # a model, not a level: the screening decides


def test_workspace_labels_use_the_eu_terms():
    from app.euaiact import rules

    c = rules.classifications()
    assert c["transparency"] == "Limited risk · transparency (Art. 50)"
    assert c["minimal"] == "Minimal risk"
    assert c["prohibited"] == "Prohibited (Art. 5)"


def test_a_ticked_prohibited_practice_shows_even_if_the_rest_is_blank():
    """Review 11-25 #6."""
    level, reason = risk.level_for({"art5": ["social_scoring"]})
    assert level == "prohibited" and "Art. 5(1)(c)" in reason


def test_high_risk_also_names_transparency_duties():
    """Review 11-25 #13: first match wins for the level, but Art. 50 duties still apply to a high-risk system."""
    level, reason = risk.level_for(_scr(annex_iii_area="employment", art50=["interacts"]))
    assert level == "high_risk" and "Art. 50" in reason


def test_legal_wording():
    """Review 11-25 #13: Art. 5(1)(g) includes philosophical beliefs; the Art. 6(3) label carries its conditions."""
    assert "philosophical beliefs" in risk.art5_practices()["biometric_categorisation"]
    o = risk.options()
    assert "profiling" in o["art6_3_label"] and "Art. 6(4)" in o["art6_3_label"]


def test_reason_fits_the_400_character_column_when_many_answers_are_ticked():
    """BUG-K01: every banned practice gave a 795-character reason, and credit + Art. 6(3) + all of Art. 50 gave 440. The
    columns are String(400): PostgreSQL refused the save. Long lists name the articles instead."""
    level, why = risk.level_for(_scr(art5=list(risk.art5_practices())))
    assert level == "prohibited" and len(why) <= risk.MAX_REASON
    assert why == "Prohibited practices: Art. 5(1)(a), Art. 5(1)(b), Art. 5(1)(c), Art. 5(1)(d), Art. 5(1)(e), Art. 5(1)(f), Art. 5(1)(g), Art. 5(1)(h)."
    level, why = risk.level_for(_scr(annex_iii_area="credit", art6_3_exception=True, art50=list(risk.art50_situations())))
    assert level == "limited" and len(why) <= risk.MAX_REASON
    assert why.startswith("Transparency duties apply: Art. 50(1), Art. 50(2), Art. 50(3), Art. 50(4). Annex III area (")


def test_short_lists_keep_the_full_wording():
    level, why = risk.level_for(_scr(art5=["manipulation", "social_scoring"]))
    assert why == ("Prohibited practice: Manipulates or deceives people in ways that cause significant harm (Art. 5(1)(a)); "
                   "Social scoring that leads to unfair or unrelated treatment (Art. 5(1)(c)).")
