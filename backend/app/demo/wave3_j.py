"""Demo data for screens 30 and 31 (wave 3 WS-J): ABC Corp on the Monitor plan, with Okta and Google Workspace connected
through the in-process fakes, an expense CSV, discovered tools the Client Admin has worked (one mapped to the inventory,
one confirmed into it, one dismissed with a reason, the rest still undeclared), a SOC 2 report close to expiry, and a
monitoring run with healthy, attention and failed checks.

Everything goes through the platform's API as the person who would do it: the Futran Admin sets the plan, Sam Okafor
(Client Admin) connects and decides, Maria Lopez (CAICO) records the report's expiry and runs the checks. Nothing touches
the network: CONNECTOR_MODE is fake while email stays in the outbox.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.demo.seed_demo import ABC, Demo, DemoError

EXPENSE_CSV = f"""Date,Employee,Email,Department,Merchant,Description,Amount
{{d1}},Dev Shah,dev.shah@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d1}},Carla Gomez,carla.gomez@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d2}},Owen Hart,owen.hart@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d2}},Marco Diaz,marco.diaz@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d3}},Lena Fox,lena.fox@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d3}},Ravi Menon,ravi.menon@{ABC},Sales & Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
{{d1}},Nina Patel,nina.patel@{ABC},Finance,Anthropic,CLAUDE.AI SUBSCRIPTION,20.00
{{d2}},Ben Ortiz,ben.ortiz@{ABC},Finance,Anthropic,CLAUDE.AI SUBSCRIPTION,20.00
{{d2}},Carla Gomez,carla.gomez@{ABC},Sales & Marketing,Midjourney Inc,MIDJOURNEY INC.,10.00
{{d1}},Tom Reyes,tom.reyes@{ABC},HR,Staples,STAPLES 0042 OFFICE SUPPLIES,54.10
{{d3}},Lee Park,lee.park@{ABC},HR,Delta Air Lines,DELTA AIR 0062 NEW YORK,412.80
"""


def _connect_oauth(m: Demo, ctype: str, provider: str) -> None:
    url = m.post(f"/integrations/{ctype}/connect", {})["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    m.post(f"/connectors/oauth/{provider}/test", {"state": state, "domain": ABC})


def seed(m: Demo, ids: dict) -> dict:
    cid = ids["abc"]
    sam, maria = m.user(f"sam.okafor@{ABC}"), m.user(f"maria.lopez@{ABC}")

    # the Futran Admin moves ABC Corp to the Monitor plan
    m.as_(m.user("admin@futran.demo")).put(f"/clients/{cid}/subscription", {"plan": "monitor", "next_review_on": m.d(150),
                                                                             "note": "Monitor plan agreed with the annual audit renewal."})

    # the Client Admin connects Okta and Google Workspace (read-only) and syncs them
    m.as_(sam).post("/integrations/okta/credentials", {"domain": "abccorp.okta.com", "client_id": "0oa-futran-discovery", "client_secret": "demo-okta-secret"})
    m.post("/integrations/okta/sync")
    _connect_oauth(m, "google_workspace", "google")
    m.post("/integrations/google_workspace/sync")

    # an expense export from the card system
    csv = EXPENSE_CSV.format(d1=m.d(-60), d2=m.d(-35), d3=m.d(-5)).encode()
    r = m.c.post("/api/v1/integrations/expense_csv/upload", files={"file": ("card-transactions-q3.csv", csv, "text/csv")})
    if r.status_code != 200:
        raise DemoError(f"Expense upload → {r.status_code}: {r.text[:400]}")
    m.db.expire_all()

    page = m.get("/integrations")
    tools = {(t["product"], t["source"]): t for t in page["tools"]}
    inventory = {a["label"]: a["id"] for a in page["ai_tools"]}
    chatgpt_inv = next((v for k, v in inventory.items() if "ChatGPT" in k), None)
    if chatgpt_inv is None:
        raise DemoError("ABC Corp's inventory has no ChatGPT tool to map the card subscriptions to")
    m.post(f"/discovered-tools/{tools[('ChatGPT', 'expense_csv')]['id']}/map", {"ai_tool_id": chatgpt_inv})
    m.post(f"/discovered-tools/{tools[('Claude', 'expense_csv')]['id']}/confirm")
    m.post(f"/discovered-tools/{tools[('Midjourney', 'expense_csv')]['id']}/dismiss",
           {"reason": "One-off purchase for a trade-show banner, refunded in October. Image tools are not approved for client work."})

    # the CAICO records when the vendor's SOC 2 report expires, then runs the checks
    m.as_(maria)
    docs = m.get("/me/document-requests")["requests"]
    soc2 = [d for d in docs if d["code"] == "DR-603" and d["status"] == "received"]
    for i, d in enumerate(soc2):
        m.put(f"/document-requests/{d['id']}/expiry", {"expires_on": m.d(24 if i == 0 else 260)})
    run = m.post("/monitoring/run")
    m.db.commit()
    counts = run["counts"]
    if not (counts["healthy"] and counts["attention"] and counts["failed"]):
        raise DemoError(f"The monitoring run should show healthy, attention and failed checks: {counts}")
    return {"monitoring_run": run["id"]}
