"""Register CSV export and import, and "Import from inventory". Registered before the register router so these paths are
not read as system ids."""
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
def export_csv(ids: str | None = Query(None), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = client_org(actor)
    authorize(db, actor, Action.VIEW_REGISTER, org_id=org.id, list_view=True)
    if ids:
        systems = [load(db, actor, i) for i in dict.fromkeys(x for x in ids.split(",") if x)]
    else:
        systems = svc.systems_for(db, org.id, departments_for(actor, Action.VIEW_REGISTER))
    return _csv(to_csv(seeding.EXPORT_HEADER, seeding.export_rows(db, systems)), "ai-system-register.csv")


@router.get("/register/import-template.csv")
def import_template(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = client_org(actor)
    authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id, list_view=True)
    example = [["Résumé screening", "Vendor app with AI", "Bought from vendor", "Human Resources", "In development / procurement", "Ranks applicants for recruiters", "TalentRank Inc.",
                "Unknown, vendor did not disclose", "Ranking model", "Supports a decision a person makes", "owner@example.com"]]
    return _csv(to_csv(seeding.IMPORT_HEADER, example), "ai-system-register-template.csv")


@router.post("/register/import")
async def import_csv(file: UploadFile = File(...), actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = client_org(actor)
    authorize(db, actor, Action.EDIT_REGISTER, org_id=org.id, list_view=True)
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise Invalid(errors=[{"field": "file", "message": "The file is over 5 MB. Split it and import each part."}])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    return seeding.import_csv(db, actor.user, org, text, departments_for(actor, Action.EDIT_REGISTER))


@router.post("/register/import-inventory")
def import_inventory(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    org = client_org(actor)
    authorize(db, actor, Action.IMPORT_INVENTORY_TO_REGISTER, org_id=org.id)
    return seeding.import_inventory(db, actor.user, org)
