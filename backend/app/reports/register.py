"""Wires the report into the sign-off workflow: sign-off 7 (final report) and sign-off 8 (public summary)."""
from app.reports import public_summary, service
from app.signoffs import service as so_svc

so_svc.PRECONDITIONS[7] = [service.final_unmet]
so_svc.ON_APPROVED[7] = [service.issue_final]
so_svc.STATEMENTS[7] = service.final_statement
so_svc.PRECONDITIONS[8] = [public_summary.summary_unmet]
so_svc.STATEMENTS[8] = public_summary.summary_statement
