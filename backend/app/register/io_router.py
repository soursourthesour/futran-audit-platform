"""Register CSV export and import, and "Import from inventory". Registered before the register router so these paths are
not read as system ids."""
import csv

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth.deps import Actor, current_actor
from app.core.db import get_db
from app.core.errors import Invalid
from app.documents.csvsafe import to_csv
from app.policy.actions import Action
from app.policy.authorize import authorize, departments_for
from app.register import seeding
from app.register import service as svc
from app.register.router import client_org, load

router = APIRouter(tags=["register"])


def _csv(text: str, filename: str) -> Response:
    return Response(content=text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"})


@router.get("/register/export.csv")
def export_csv(ids: str | None = Query(None), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    if ids:
        systems = [load(db, actor, i) for i in dict.fromkeys(x for x in ids.split(",") if x)]
    else:
        systems = svc.systems_for(db, org.id, departments_for(actor, Action.VIEW_REGISTER))
    return _csv(to_csv(seeding.EXPORT_HEADER, seeding.export_rows(db, systems)), "ai-system-register.csv")


@router.get("/register/import-template.csv")
def import_template(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id, list_view=True)
    return _csv(seeding.template_csv(), "ai-system-register-template.csv")


@router.get("/register/import-template.xlsx")
def import_template_xlsx(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The template as a workbook: an AI systems sheet with dropdowns and an Instructions sheet (11-03 C7)."""
    org = client_org(actor)
    authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id, list_view=True)
    return Response(content=seeding.template_xlsx(db), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="ai-system-register-template.xlsx"', "Cache-Control": "private, no-store"})


@router.post("/register/import")
async def import_csv(file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id, list_view=True)
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise Invalid(errors=[{"field": "file", "message": "The file is over 5 MB. Split it and import each part."}])
    from app.register.router import may

    try:
        rows = seeding.rows_from_upload(raw)
    except Invalid as e:
        return {"created": 0, "errors": [{"row": 0, **x} for x in e.errors]}
    except csv.Error:
        return {"created": 0, "errors": [{"row": 0, "field": "file", "message": "The file could not be read. Save it as CSV (comma delimited) from the template and try again."}]}
    can_add_law = may(db, actor, Action.ADD_SYSTEM_LAW, department_id=None) or departments_for(actor, Action.ADD_SYSTEM_LAW) is not None
    return seeding.import_csv(db, actor.user, org, rows, departments_for(actor, Action.EDIT_REGISTER), can_add_law=can_add_law)


@router.post("/register/import-inventory")
def import_inventory(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    org = client_org(actor)
    authorize(db, actor, Action.IMPORT_INVENTORY_TO_REGISTER, org_id=org.id)
    return seeding.import_inventory(db, actor.user, org)


@router.get("/register/role-catalog")
def role_catalog(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """The governance roles (§24.1), for the bulk edit role picker."""
    from app.register.roles import catalog_roles

    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    return [{"id": r.id, "code": r.code, "number": r.number, "name": r.name, "level": r.level, "default_stage": r.default_stage, "main_sources": r.main_sources, "extra_checks": r.extra_checks}
            for r in catalog_roles(db)]


@router.post("/register/law-suggestions")
def law_suggestions(data: dict, actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Laws for a system being added or edited, from its places and features (11-03 C14). Nothing is saved."""
    from app.register.geo_laws import Draft, suggest
    from app.tenancy.models import Department

    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    v = svc.clean(db, org, {k: data[k] for k in ("run_location", "data_locations", "data", "type", "sourcing", "decision_impact", "algorithm_type") if k in data}, current=_Blank(),
                  require_department=False)
    dept = db.get(Department, data["department_id"]) if isinstance(data.get("department_id"), str) else None
    dd = v.get("_data") or {}
    d = Draft(name=str(data.get("name") or "")[:160], purpose=str(data.get("purpose") or "")[:4000], department_name=dept.name if dept and dept.organization_id == org.id else "",
              type=v.get("type"), sourcing=v.get("sourcing"), algorithm_type=v.get("algorithm_type"), decision_impact=v.get("decision_impact"),
              data_categories=dd.get("data_categories") or [], data_subjects=dd.get("data_subjects") or [], run_location=v.get("run_location"), data_locations=v.get("data_locations") or [])
    exclude = {x for x in data.get("exclude") or [] if isinstance(x, str)} if isinstance(data.get("exclude"), list) else set()
    return suggest(db, org.id, d, exclude=exclude)


class _Blank:
    """Stands in for a saved system when a draft is checked: nothing is required."""

    type = None
    department_id = None
    company_wide = False
    stage = "proposed"


@router.get("/register/model-catalogue")
def model_catalogue(actor: Actor = Depends(current_actor), db: Session = Depends(get_db, scope="function")):
    """Vendors and their models for the "Model or algorithm" field, with this client's own "Other" models (11-03 C12)."""
    from app.register.catalogue import client_catalogue

    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    return client_catalogue(db, org.id)
