"""OBS-07: a tool whose vendor and product are the same is named once ('Otter.ai', not 'Otter.ai Otter.ai')."""
from app.core.names import tool_name
from tests.factories import login_as
from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401


def test_tool_name_shows_a_repeated_name_once():
    assert tool_name("Otter.ai", "Otter.ai") == "Otter.ai"
    assert tool_name(" otter.AI ", "Otter.ai ") == "Otter.ai"
    assert tool_name("Microsoft", "Copilot") == "Microsoft Copilot"
    assert tool_name("", "Copilot") == "Copilot"
    assert tool_name(None, "Copilot") == "Copilot"


def test_the_register_and_the_systems_screen_name_the_tool_once(client, db, inv, people):
    cid, e, maria, hr, copilot, chatgpt = inv
    login_as(client, db, maria)
    t = client.post(f"/api/v1/clients/{cid}/tools", json={"vendor": "Otter.ai", "product": "Otter.ai", "account_type": "enterprise", "training_on_inputs": "no"})
    assert t.status_code == 200, t.text
    rows = client.get("/api/v1/ai-systems").json()
    rows = rows["rows"] if isinstance(rows, dict) else rows
    names = [r["name"] for r in rows if r.get("kind") == "tool"]
    assert "Otter.ai" in names and "Otter.ai Otter.ai" not in names
    login_as(client, db, people["aud"])
    opts = client.get(f"/api/v1/clients/{cid}/systems").json()["tool_options"]
    labels = {o["label"] for o in opts}
    assert "Otter.ai" in labels and "Microsoft Copilot" in labels and "Otter.ai Otter.ai" not in labels
