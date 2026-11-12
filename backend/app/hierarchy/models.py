"""G-04 records. The tree itself is `Organization.parent_id` and `Organization.relationship` (app.tenancy.models).

Tenancy is unchanged (spec B4, v0.6.1 §3): each entity is its own tenant. The only data that crosses from a subsidiary
to its parent is the roll-up (counts and statuses), and only while the subsidiary's CAICO consents. Consent rows are
never edited after the fact except to record the revocation; a new consent is a new row.
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, TimestampedTenantMixin

RELATIONSHIPS = ("subsidiary", "end_client", "customer_of_vendor")
RELATIONSHIP_LABELS = {"subsidiary": "Subsidiary", "end_client": "End-client (staffing)", "customer_of_vendor": "Customer of vendor (L-10)"}


class RollupConsent(TimestampedTenantMixin, Base):
    """A subsidiary CAICO's consent to its parent seeing roll-up counts. organization_id is the subsidiary (the tenant
    whose data is shared)."""

    __tablename__ = "rollup_consents"

    parent_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), index=True)
    given_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    given_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class EndClientScope(TimestampedTenantMixin, Base):
    """LL144 scope for one end-client of a staffing firm (L-09) or one customer of an HR-tech vendor (L-10).
    organization_id is the parent (the firm whose AEDTs are used); end_client_id is the child entity."""

    __tablename__ = "end_client_scopes"
    __table_args__ = (UniqueConstraint("end_client_id", name="uq_end_client_scope"),)

    end_client_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"))
    ll144_in_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    aedt_system_ids: Mapped[list] = mapped_column(JSON, default=list)  # the parent's register systems used for this client's roles
    roles_note: Mapped[str | None] = mapped_column(String(300))  # "NYC roles placed at this client", "NJ roles only"
    own_public_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    vendor_allows_summary: Mapped[bool] = mapped_column(Boolean, default=False)  # L-10: the vendor lets this customer read its summary
    note: Mapped[str | None] = mapped_column(Text)
