"""The AI vendor list drives matching of SSO apps, OAuth clients, licences, card descriptors and web domains."""
from app.connectors import vendors


def test_every_entry_has_the_required_fields_and_a_unique_key():
    keys = [v.key for v in vendors.all_vendors()]
    assert len(keys) == len(set(keys)) and len(keys) >= 20
    for v in vendors.all_vendors():
        assert v.vendor and v.product and v.category


def test_app_names_match_the_longest_phrase():
    assert vendors.match_name("GitHub Copilot Business").key == "github_copilot"
    assert vendors.match_name("Microsoft 365 Copilot").key == "microsoft_copilot"
    assert vendors.match_name("Otter.ai Meeting Notes").key == "otter"
    assert vendors.match_name("Workday HCM") is None


def test_names_match_whole_words_only():
    assert vendors.match_name("Cursory Review Tool") is None
    assert vendors.match_name("ClaudeBot") is None


def test_domains_match_the_domain_or_a_subdomain():
    assert vendors.match_domain("chatgpt.com").key == "openai_chatgpt"
    assert vendors.match_domain("ab.chat.openai.com").key == "openai_chatgpt"
    assert vendors.match_domain("https://claude.ai/new").key == "anthropic_claude"
    assert vendors.match_domain("notopenai.com") is None
    assert vendors.match_domain("") is None


def test_expense_descriptors_match_a_phrase_in_the_text():
    assert vendors.match_expense("OPENAI *CHATGPT SUBSCR SAN FRANCISCO CA").key == "openai_chatgpt"
    assert vendors.match_expense("Claude.ai subscription").key == "anthropic_claude"
    assert vendors.match_expense("STAPLES 0042") is None


def test_attestation_values_name_their_vendor_entry():
    assert vendors.for_attestation_value("chatgpt").key == "openai_chatgpt"
    assert vendors.for_attestation_value("in_app") is None
