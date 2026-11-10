"""Old import files with extra columns import with a warning (review R3)."""



def test_an_old_file_with_an_extra_column_imports_with_a_warning(client, db, reg):
    reg.as_(reg.caico)
    text = ("name,type,sourcing,department,stage,purpose,vendor,ai_provider,model_name,decision_impact,owner_email,notes\n"
            "X,Vendor app with AI,Bought from vendor,Human Resources,,,,,,,,hello\n")
    r = client.post("/api/v1/register/import", files={"file": ("old.csv", text.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["errors"] == [] and body["created"] == 1
    assert any("notes" in w["message"] for w in body.get("warnings", []))


def test_a_missing_required_column_is_still_refused(client, db, reg):
    reg.as_(reg.caico)
    r = client.post("/api/v1/register/import", files={"file": ("x.csv", b"name,notes\nX,hello\n", "text/csv")})
    body = r.json()
    assert body.get("created", 0) == 0 and "missing" in body["errors"][0]["message"]
