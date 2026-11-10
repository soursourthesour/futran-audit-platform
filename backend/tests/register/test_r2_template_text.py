"""Catalogue names are written to the import template as text, and refused when they start like a formula (review R2)."""
import io

from tests.factories import login_as, make_org, make_user


def test_catalogue_names_starting_with_a_formula_character_are_refused(client, db, reg):
    from app.register import catalogue as cat

    cat.ensure_seeded(db)
    fo = make_org(db, type="futran")
    adm = make_user(db, fo, roles=["admin"], name="Fran", email="fran2@futran.test")
    db.commit()
    login_as(client, db, adm)
    for bad in ('=HYPERLINK("https://evil.test","Acme")', "+1 vendor", "-x", "@sum"):
        r = client.post("/api/v1/admin/model-catalogue/vendors", json={"name": bad})
        assert r.status_code == 422, (bad, r.text)
    vid = client.get("/api/v1/admin/model-catalogue").json()["vendors"][0]["id"]
    r = client.post("/api/v1/admin/model-catalogue/models", json={"vendor_id": vid, "name": "=1+1"})
    assert r.status_code == 422, r.text


def test_template_writes_catalogue_names_as_text(client, db, reg):
    from openpyxl import load_workbook

    from app.register import catalogue as cat
    from app.register.models import ModelVendor

    cat.ensure_seeded(db)
    db.add(ModelVendor(code="evil", name='=HYPERLINK("https://evil.test","Acme")', sort=999, active=True))  # e.g. from an older accepted proposal
    db.commit()
    reg.as_(reg.caico)
    x = client.get("/api/v1/register/import-template.xlsx")
    wb = load_workbook(io.BytesIO(x.content))
    formulas = [(ws.title, c.coordinate) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.data_type == "f"]
    assert formulas == []
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row if isinstance(c.value, str) and "evil.test" in c.value]
    assert cells and all(c.data_type == "s" for c in cells)
    assert '=HYPERLINK("https://evil.test","Acme")' in [c.value for c in cells]  # the name itself, shown as text
