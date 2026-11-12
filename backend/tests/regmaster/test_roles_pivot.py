"""Feedback of 10 November, F4: Roles and committees as a pivot of the selected regulations, from the law library's own maps."""
import csv
import io

from sqlalchemy import select

from app.laws.models import Regulation
from app.regmaster.models import CommitteeRule, LawRoleMap, RoleCatalog
from tests.factories import login_as, make_org, make_user

API = "/api/v1"


def _ids(body: dict, *labels: str) -> list[str]:
    by = {r["label"]: r["id"] for r in body["regulations"]}
    return [by[x] for x in labels]


def test_pivot_lists_regulations_grouped_by_jurisdiction(client, db, seeded):
    login_as(client, db, seeded["aud"])
    r = client.get(f"{API}/reg/roles/pivot")
    assert r.status_code == 200, r.text
    b = r.json()
    nyc = next(x for x in b["regulations"] if x["label"] == "NYC LL144")
    assert nyc["jurisdiction"] and nyc["jurisdiction_code"] and nyc["region_label"]
    # every regulation offered has role maps or committee rules in the library
    assert all(x["mapped"] for x in b["regulations"])
    assert b["selected"] == [] and b["roles"] == [] and b["committees"] == [] and b["summary"] == []


def test_pivot_rows_are_what_the_selected_regulations_require(client, db, seeded):
    login_as(client, db, seeded["aud"])
    every = client.get(f"{API}/reg/roles/pivot").json()
    nyc, eu = _ids(every, "NYC LL144", "EU AI Act")
    b = client.get(f"{API}/reg/roles/pivot?laws={nyc},{eu}").json()
    assert [s["id"] for s in b["selected"]] == [nyc, eu]
    # the cells match the law library's LawRoleMap rows, and nothing else is shown
    expected: dict[str, dict] = {}
    for law_id in (nyc, eu):
        reg = db.get(Regulation, law_id)
        for m, role in db.execute(select(LawRoleMap, RoleCatalog).join(RoleCatalog, RoleCatalog.id == LawRoleMap.role_id).where(LawRoleMap.law_version_id == reg.current_version_id)):
            expected.setdefault(role.code, {})[law_id] = (m.level, m.needed_by_stage or role.default_stage)
    got = {row["code"]: {k: (v["level"], v["needed_by_stage"]) for k, v in row["cells"].items()} for row in b["roles"]}
    assert got == expected
    bias = next(row for row in b["roles"] if row["code"] == "bias_testing_lead")
    assert bias["cells"][nyc]["level"] == "required" and bias["cells"][nyc]["needed_by_label"]
    # committees come from CommitteeRule rows of the selected laws
    want_comm = {c.committee_type for law_id in (nyc, eu) for c in db.scalars(select(CommitteeRule).where(CommitteeRule.law_version_id == db.get(Regulation, law_id).current_version_id))}
    assert {c["committee_type"] for c in b["committees"]} == want_comm
    # the summary: every role or committee needed by any selected regulation, the stricter level and the earlier stage
    assert {s["code"] for s in b["summary"] if s["kind"] == "role"} == set(expected)
    s_bias = next(s for s in b["summary"] if s["code"] == "bias_testing_lead")
    assert s_bias["level"] == "required" and "NYC LL144" in s_bias["laws"]
    stages = b["stages"]
    for s in (x for x in b["summary"] if x["kind"] == "role"):
        cells = expected[s["code"]].values()
        assert s["level"] == ("required" if any(lv == "required" for lv, _ in cells) else "recommended")
        assert s["needed_by_stage"] == min((st for _, st in cells), key=stages.index)


def test_pivot_csv_is_formula_safe_and_matches_the_table(client, db, seeded):
    login_as(client, db, seeded["aud"])
    every = client.get(f"{API}/reg/roles/pivot").json()
    nyc, = _ids(every, "NYC LL144")
    role = db.scalar(select(RoleCatalog).where(RoleCatalog.code == "bias_testing_lead"))
    role.name = "=HYPERLINK(\"http://x\")"
    db.commit()
    r = client.get(f"{API}/reg/roles/pivot.csv?laws={nyc}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0][:3] == ["Type", "Role or committee", "Level"] and "NYC LL144" in rows[0]
    names = [x[1] for x in rows[1:]]
    assert "'=HYPERLINK(\"http://x\")" in names
    assert not any(c[:1] in "=+-@" for row in rows for c in row if c)


def test_pivot_needs_law_library_access(client, db, seeded):
    f = make_org(db, name="ABC Corp")
    caico = make_user(db, f, roles=["caico"], name="Casey Caico", email="casey@abc.test")
    db.commit()
    login_as(client, db, caico)
    assert client.get(f"{API}/reg/roles/pivot").status_code in (403, 404)
    assert client.get(f"{API}/reg/roles/pivot.csv").status_code in (403, 404)


def test_unknown_or_unmapped_ids_are_ignored(client, db, seeded):
    login_as(client, db, seeded["aud"])
    b = client.get(f"{API}/reg/roles/pivot?laws=nope,,").json()
    assert b["selected"] == [] and b["roles"] == []


def test_pivot_csv_header_is_formula_safe_too(client, db, seeded):
    login_as(client, db, seeded["aud"])
    every = client.get(f"{API}/reg/roles/pivot").json()
    nyc, = _ids(every, "NYC LL144")
    reg = db.get(Regulation, nyc)
    reg.label = "=cmd|' /C calc'!A0"
    db.commit()
    r = client.get(f"{API}/reg/roles/pivot.csv?laws={nyc}")
    header = next(csv.reader(io.StringIO(r.text.lstrip("﻿"))))
    assert not any(c[:1] in "=+-@" for c in header if c), header
