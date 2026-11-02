"""Futran policy templates (spec §21 F7): ten deterministic templates, versioned, rendered from guided answers."""
import pytest

from app.policies import templates as T

CODES = {"acceptable_use", "governance_committee_charter", "bias_committee_tor", "raci", "incident_response", "vendor_due_diligence",
         "data_classification", "employee_data_notice", "human_oversight", "model_change_management"}


def test_ten_templates_with_versions_and_questions():
    lib = T.library()
    assert set(lib) == CODES
    for t in lib.values():
        assert t.version and t.title and t.summary
        keys = [q["key"] for q in t.questions]
        assert {"company_name", "policy_owner", "review_cycle"} <= set(keys), t.code
        assert len(keys) == len(set(keys))
        for q in t.questions:
            assert q.get("help"), f"{t.code}.{q['key']} needs help text"


def test_every_template_renders_with_its_defaults():
    for t in T.library().values():
        blocks = T.render(t, T.defaults(t, "ABC Corp"))
        assert blocks[0] == {"type": "heading", "level": 1, "text": f"ABC Corp {t.title}"}, t.code
        assert any(b["type"] == "list" for b in blocks), t.code
        text = T.blocks_to_markdown(blocks)
        assert "{{" not in text and "{%" not in text and "None" not in text, t.code


def test_acceptable_use_fills_in_the_choices():
    t = T.library()["acceptable_use"]
    a = T.defaults(t, "ABC Corp") | {"approved_tools": ["Microsoft Copilot (company account)", "ATS screening"], "personal_accounts": "not_allowed",
                                      "prohibited_data": ["client_data", "personal_data", "source_code"], "policy_owner": "Maria Lopez, Chief AI Compliance Officer"}
    answers, errors = T.clean_answers(t, a)
    assert errors == []
    md = T.blocks_to_markdown(T.render(t, answers))
    assert "Microsoft Copilot (company account)" in md and "ATS screening" in md
    assert "Use of personal or free AI accounts for ABC Corp work is not allowed." in md
    assert "Client or customer data" in md and "Health information" not in md
    allowed = T.blocks_to_markdown(T.render(t, answers | {"personal_accounts": "public_only"}))
    assert "not allowed" not in allowed.split("## 3")[0] and "information that is already public" in allowed


def test_answers_are_validated():
    t = T.library()["acceptable_use"]
    answers, errors = T.clean_answers(t, {"company_name": " ", "personal_accounts": "sometimes", "prohibited_data": ["client_data", "made_up"], "review_cycle": "12"})
    fields = {e["field"] for e in errors}
    assert {"company_name", "personal_accounts", "prohibited_data", "approved_tools", "policy_owner"} <= fields


def test_answer_text_cannot_inject_template_syntax_or_markup():
    t = T.library()["acceptable_use"]
    a = T.defaults(t, "ABC {{ 7*7 }} Corp") | {"approved_tools": ["<script>alert(1)</script>", "{% raw %}x"], "policy_owner": "Maria Lopez, CAICO"}
    answers, errors = T.clean_answers(t, a)
    assert errors == []
    md = T.blocks_to_markdown(T.render(t, answers))
    assert "49" not in md and "{{ 7*7 }}" in md
    assert "<script>alert(1)</script>" in md  # kept as text: the editor and the PDF writer escape it


def test_blocks_are_limited_to_headings_paragraphs_and_lists():
    ok, errors = T.clean_blocks([{"type": "heading", "level": 2, "text": " Scope "}, {"type": "paragraph", "text": "Text."},
                                 {"type": "list", "ordered": True, "items": ["One", " ", "Two"]}])
    assert errors == []
    assert ok == [{"type": "heading", "level": 2, "text": "Scope"}, {"type": "paragraph", "text": "Text."}, {"type": "list", "ordered": True, "items": ["One", "Two"]}]
    _, errors = T.clean_blocks([{"type": "image", "src": "x"}, {"type": "heading", "level": 7, "text": "x"}, {"type": "list", "items": []}])
    assert len(errors) == 3
    _, errors = T.clean_blocks("nope")
    assert errors


def test_markdown_round_trip():
    blocks = [{"type": "heading", "level": 1, "text": "Title"}, {"type": "paragraph", "text": "A paragraph."},
              {"type": "list", "ordered": False, "items": ["a", "b"]}, {"type": "list", "ordered": True, "items": ["c"]}]
    assert T.parse_markdown(T.blocks_to_markdown(blocks)) == blocks


@pytest.mark.parametrize("cycle,months", [("annually", 12), ("six_months", 6)])
def test_review_cycle_months(cycle, months):
    assert T.REVIEW_MONTHS[cycle] == months


def test_display_name_is_sentence_case():
    lib = T.library()
    assert lib["acceptable_use"].name == "AI acceptable use policy"
    assert lib["raci"].name == "RACI for AI systems"
    assert lib["bias_committee_tor"].name == "Bias and fairness review committee terms of reference"


def test_catalog_codes_map_to_templates():
    assert T.for_catalog_code("GD-04") == "acceptable_use"
    assert T.for_catalog_code("GR-05") == "human_oversight"
    assert T.for_catalog_code("GD-05") is None
