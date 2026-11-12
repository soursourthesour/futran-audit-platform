"""Master price list (spec §4.9, §4.11): items, saved versions, the change history, suggestions, packages and estimates.

The catalog is Futran's own reference data: no client tenant owns it, and only Futran staff hold the actions that read it.
Items are never deleted (retire instead); every change is a CatalogChange row tied to the CatalogVersion of its batch."""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.models import Base, IdMixin


class CatalogVersion(IdMixin, Base):
    """One saved batch. `version` increases by one per batch, so an estimate or proposal can name the prices it used."""

    __tablename__ = "catalog_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_catalog_version"),)

    version: Mapped[int] = mapped_column(Integer, index=True)
    saved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(12), default="grid")  # grid | bulk | import | item | seed | scheduled | confirmed
    change_count: Mapped[int] = mapped_column(Integer, default=0)


class CatalogItem(IdMixin, Base):
    __tablename__ = "catalog_items"
    __table_args__ = (UniqueConstraint("code", name="uq_catalog_item_code"),)

    catalog_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("catalog_versions.id"))  # version that last changed it
    code: Mapped[str] = mapped_column(String(12), index=True)
    product: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)  # short proposal text
    pricing_unit: Mapped[str | None] = mapped_column(String(80))
    billing: Mapped[str] = mapped_column(String(12), default="one_time")  # one_time | annual | quarterly | monthly | share
    basis: Mapped[str] = mapped_column(String(1), default="$")  # $ | %
    periods_per_year: Mapped[int] = mapped_column(Integer, default=1)
    low: Mapped[float | None] = mapped_column(Float)
    list_price: Mapped[float | None] = mapped_column(Float)  # spec "list"
    high: Mapped[float | None] = mapped_column(Float)
    price_status: Mapped[str] = mapped_column(String(10), default="proposed")  # existing | proposed | approved
    deliverables: Mapped[str | None] = mapped_column(Text)  # client-facing: what is delivered, how, what the client provides, duration
    sellable_status: Mapped[str] = mapped_column(String(16), default="available")  # available | manual_delivery | roadmap
    delivery_mode: Mapped[str | None] = mapped_column(String(12))  # mixed | platform | consultant
    platform_feature_ref: Mapped[str | None] = mapped_column(String(120))
    included_quantities: Mapped[dict] = mapped_column(JSON, default=dict)  # {"systems": 50, "docs": 5}
    applies_to: Mapped[list] = mapped_column(JSON, default=list)  # %-items: codes or products the percentage is taken of (empty = every $ line)
    remediation_of: Mapped[list] = mapped_column(JSON, default=list)  # finding domains this line remediates (independence rule I-1)
    engagement_type: Mapped[str | None] = mapped_column(String(40))
    entitlement_key: Mapped[str | None] = mapped_column(String(60))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(8), default="active", index=True)  # active | retired
    pending_change_id: Mapped[str | None] = mapped_column(String(36))  # the latest change waiting for its date or a second check
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False)  # demo/starter row from the designs, until the workbook is loaded
    version_no: Mapped[int] = mapped_column(Integer, default=1)  # catalog version number that last changed this row (conflict check)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def is_recurring(self) -> bool:
        return self.billing != "one_time"


class CatalogChange(IdMixin, Base):
    """One field change. `field` is a CatalogItem attribute, or `created` for a new item. Values are JSON."""

    __tablename__ = "catalog_changes"

    catalog_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("catalog_versions.id"), index=True)
    item_code: Mapped[str] = mapped_column(String(12), index=True)
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[object | None] = mapped_column(JSON)
    new_value: Mapped[object | None] = mapped_column(JSON)
    effective_from: Mapped[date | None] = mapped_column(Date)  # null: took effect when saved
    status: Mapped[str] = mapped_column(String(12), default="applied", index=True)  # applied | pending | awaiting_check | declined
    applied_at: Mapped[datetime | None] = mapped_column(DateTime)
    applied_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("catalog_versions.id"))
    reason: Mapped[str] = mapped_column(Text, default="")
    changed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))  # the other owner, when the second check is on
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class PriceSuggestion(IdMixin, Base):
    """'Suggest a change' from anyone who views the grid: a task for the Price List Owners."""

    __tablename__ = "price_suggestions"

    item_code: Mapped[str | None] = mapped_column(String(12), index=True)  # null: a new item
    suggested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    field: Mapped[str] = mapped_column(String(40))  # list_price | low | high | deliverables | description | new_item | other
    suggested_value: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | accepted | declined
    decided_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PackageTemplate(IdMixin, Base):
    __tablename__ = "catalog_packages"
    __table_args__ = (UniqueConstraint("key", name="uq_catalog_package_key"),)

    key: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    catalog_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("catalog_versions.id"))
    lines: Mapped[list] = mapped_column(JSON, default=list)  # [{"code", "qty"}]
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_starter: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Estimate(IdMixin, Base):
    """One saved version of an estimate (SM-15). Versions of the same estimate share `thread_id` (the first version's id).
    Internal only: never sent to a client. The master price list never changes from here."""

    __tablename__ = "estimates"
    __table_args__ = (UniqueConstraint("thread_id", "version", name="uq_estimate_version"),)

    thread_id: Mapped[str] = mapped_column(String(36), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("opportunities.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    package: Mapped[str | None] = mapped_column(String(30))
    lines: Mapped[list] = mapped_column(JSON, default=list)
    discount_recurring_pct: Mapped[float] = mapped_column(Float, default=0)
    term: Mapped[int] = mapped_column(Integer, default=1)  # contract term in years
    data_region: Mapped[str | None] = mapped_column(String(20))
    terms: Mapped[dict] = mapped_column(JSON, default=dict)  # payment_days, custom_liability, sla_credits, discount_one_time_pct
    totals: Mapped[dict] = mapped_column(JSON, default=dict)
    catalog_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    saved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    saved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    converted_proposal_id: Mapped[str | None] = mapped_column(String(36))


class CatalogImport(IdMixin, Base):
    """An uploaded workbook between preview and save. The parsed rows are kept so the save applies exactly what was previewed."""

    __tablename__ = "catalog_imports"

    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    rows: Mapped[list] = mapped_column(JSON, default=list)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    base_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="preview")  # preview | saved | discarded
    uploaded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    saved_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("catalog_versions.id"))


class CatalogSetting(IdMixin, Base):
    """Price list settings (one row, key "platform"). No row means the defaults: second check off."""

    __tablename__ = "catalog_settings"

    key: Mapped[str] = mapped_column(String(20), unique=True, default="platform")
    second_check: Mapped[bool] = mapped_column(Boolean, default=False)
    second_check_pct: Mapped[float] = mapped_column(Float, default=10)  # price changes above this % wait for the other owner
    manager_discount_limit_pct: Mapped[float] = mapped_column(Float, default=15)  # R2-Q1 default; P-2 / P-3 boundary
    updated_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
