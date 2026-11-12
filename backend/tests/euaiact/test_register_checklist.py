"""The seeded provider, importer and distributor rows reach a register system's requirements checklist only when the
client built it: a bought (vendor or shadow) high-risk system keeps its deployer checklist."""
from app.euaiact import lawseed
from app.register.models import RegisterSystem, RegisterSystemLaw
from app.register.requirements import requirements_for
from tests.factories import make_org


def _system(db, org, sourcing, reg):
    s = RegisterSystem(organization_id=org.id, reference=f"AIS-{sourcing[:3]}", name=f"Credit model ({sourcing})", type="in_house_model" if sourcing == "in_house" else "vendor_app",
                       sourcing=sourcing, decision_impact="consequential", stage="proposed")
    db.add(s)
    db.flush()
    db.add(RegisterSystemLaw(organization_id=org.id, register_system_id=s.id, regulation_id=reg.id))
    db.flush()
    return s


def test_provider_rows_only_on_systems_the_client_built(matrix):
    from app.regmaster.seed import seed_regmaster

    db = matrix
    seed_regmaster(db)
    lawseed.ensure_requirements(db)
    reg, _v = lawseed.eu_ai_act(db)
    org = make_org(db, name="Northbank Credit Union")
    built, bought = _system(db, org, "in_house", reg), _system(db, org, "vendor", reg)

    def cites(s):
        return {r.citation for r, _ in requirements_for(db, s)}

    assert "EU AI Act Art. 9(1)" in cites(built) and "EU AI Act Art. 26(1)" in cites(built)
    assert "EU AI Act Art. 9(1)" not in cites(bought) and "EU AI Act Art. 23(1)" not in cites(bought)
    assert {"EU AI Act Art. 26(1)", "EU AI Act Art. 26(2)", "EU AI Act Art. 14(4)(e)"} <= cites(bought)
