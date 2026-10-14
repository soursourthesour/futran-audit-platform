from app.inventory.models import AITool
from app.inventory.service import propose_tier

COMPANY = AITool(vendor="Microsoft", product="Copilot", account_type="enterprise", training_on_inputs="no")


def test_tier3_consequential():
    assert propose_tier("consequential", ["none"], [COMPANY]) == 3


def test_tier2_pii():
    assert propose_tier("informs", ["pii"], [COMPANY]) == 2
    for cat in ("phi", "client", "confidential"):
        assert propose_tier("none", [cat], [COMPANY]) == 2


def test_tier2_personal_account_tool():
    for acct in ("personal_free", "personal_paid", "unknown"):
        assert propose_tier("none", ["none"], [AITool(vendor="OpenAI", product="ChatGPT", account_type=acct, training_on_inputs="no")]) == 2
    assert propose_tier("none", [], [AITool(vendor="OpenAI", product="ChatGPT", account_type="enterprise", training_on_inputs="unknown")]) == 1  # spec §11 has no training-on-inputs rule


def test_tier1_otherwise():
    assert propose_tier("none", ["none"], [COMPANY]) == 1
    assert propose_tier("informs", [], [COMPANY]) == 1
    assert propose_tier(None, [], []) == 1
