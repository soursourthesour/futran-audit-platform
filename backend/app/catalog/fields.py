"""The price list's fields: labels, allowed values, parsing and the validation rules of spec §4.9."""
import re

PRODUCTS = ("Audit", "Monitor", "Agent Assure", "AgentWarden", "LL144", "Other", "Terms")
BILLING = {"one_time": "One-time", "annual": "Annual", "quarterly": "Quarterly", "monthly": "Monthly", "share": "Partner share"}
BILLING_PERIODS = {"one_time": 1, "annual": 1, "quarterly": 4, "monthly": 12, "share": 0}
PRICE_STATUS = {"existing": "Existing", "proposed": "Proposed", "approved": "Approved"}
SELLABLE = {"available": "Available", "manual_delivery": "Manual delivery", "roadmap": "Roadmap"}
DELIVERY = {"mixed": "Mixed", "platform": "Platform", "consultant": "Consultant"}
BASIS = ("$", "%")
CODE_RE = re.compile(r"^[A-Z]{1,2}-\d{2}[a-z]?$")
LIST_MOVE_WARN = 0.25

# Editable fields in grid order, with labels. `code` is set when the item is added and never changes afterwards.
FIELDS: dict[str, str] = {
    "product": "Product", "name": "Line item", "deliverables": "Deliverables", "description": "Description", "pricing_unit": "Pricing unit",
    "billing": "Billing", "basis": "Basis", "periods_per_year": "Periods per year", "low": "Low", "list_price": "List", "high": "High",
    "price_status": "Price status", "sellable_status": "Sellable status", "delivery_mode": "Delivery mode",
    "platform_feature_ref": "Platform feature", "included_quantities": "Included quantities", "applies_to": "Applies to (% items)",
    "remediation_of": "Remediation of", "engagement_type": "Engagement type", "entitlement_key": "Entitlement key", "notes": "Notes",
}
FIELD_LABELS = {**FIELDS, "code": "Code", "status": "Status", "created": "Item added"}
PRICE_FIELDS = ("low", "list_price", "high")
NUMBER_FIELDS = PRICE_FIELDS
TEXT_LIMITS = {"name": 200, "pricing_unit": 80, "platform_feature_ref": 120, "engagement_type": 40, "entitlement_key": 60, "product": 40}


class FieldError(ValueError):
    pass


def _num(v):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise FieldError("Enter a number.")
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        s = str(v).strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            n = float(s)
        except ValueError as exc:
            raise FieldError("Enter a number.") from exc
    if n < 0:
        raise FieldError("Prices cannot be negative.")
    n = round(n, 2)
    return int(n) if n == int(n) else n


def parse_quantities(v) -> dict:
    """'50 systems; 5 docs; 1 readout' -> {"systems": 50, "docs": 5, "readout": 1}. A dict passes through."""
    if v is None or v == "":
        return {}
    if isinstance(v, dict):
        return v
    out: dict = {}
    for part in re.split(r"[;\n]", str(v)):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", part)
        if not m:
            raise FieldError(f"Write included quantities as a number and a unit, for example \"50 systems; 5 docs\" (not \"{part}\").")
        n = float(m.group(1))
        out[m.group(2).strip()] = int(n) if n == int(n) else n
    return out


def quantities_text(q: dict | None) -> str:
    return "; ".join(f"{n} {unit}" for unit, n in (q or {}).items())


def _list(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[,;\n]", str(v)) if x.strip()]


def _choice(v, choices: dict, what: str, allow_none=False):
    if v is None or v == "":
        if allow_none:
            return None
        raise FieldError(f"Choose a {what}.")
    s = str(v).strip()
    if s in choices:
        return s
    for key, label in choices.items():
        if s.casefold() in (label.casefold(), key.replace("_", " ")):
            return key
    raise FieldError(f"Choose a {what}: {', '.join(choices.values())}.")


def parse(field: str, value):
    """Normalise one field's value as typed in the grid, the side panel or a workbook cell. Raises FieldError."""
    if field not in FIELDS:
        raise FieldError("This field cannot be changed." if field == "code" else "Unknown field.")
    if field in NUMBER_FIELDS:
        return _num(value)
    if field == "periods_per_year":
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError) as exc:
            raise FieldError("Periods per year must be 1, 4 or 12 (0 for a partner share).") from exc
    if field == "product":
        s = str(value or "").strip()
        for p in PRODUCTS:
            if s.casefold() == p.casefold():
                return p
        raise FieldError(f"Choose a product: {', '.join(PRODUCTS)}.")
    if field == "billing":
        s = str(value or "").strip().casefold().replace("-", " ").replace("_", " ")
        aliases = {"one time": "one_time", "once": "one_time", "yearly": "annual", "annually": "annual", "per year": "annual", "quarter": "quarterly",
                   "month": "monthly", "partner share": "share", "share": "share"}
        if s in aliases:
            return aliases[s]
        return _choice(value, BILLING, "billing")
    if field == "basis":
        s = str(value or "$").strip()
        if s in ("$", "USD", "usd", "dollar", "Dollar"):
            return "$"
        if s in ("%", "percent", "Percent", "pct"):
            return "%"
        raise FieldError("Basis is $ or %.")
    if field == "price_status":
        return _choice(value, PRICE_STATUS, "price status")
    if field == "sellable_status":
        return _choice(value, SELLABLE, "sellable status")
    if field == "delivery_mode":
        return _choice(value, DELIVERY, "delivery mode", allow_none=True)
    if field == "included_quantities":
        return parse_quantities(value)
    if field in ("applies_to", "remediation_of"):
        return _list(value)
    s = None if value is None else str(value).strip()
    if field == "name" and not s:
        raise FieldError("Give the line item a name.")
    if s and field in TEXT_LIMITS and len(s) > TEXT_LIMITS[field]:
        raise FieldError(f"Keep this under {TEXT_LIMITS[field]} characters.")
    return s or None


def check_code(code: str) -> str:
    code = (code or "").strip()
    if not CODE_RE.match(code):
        raise FieldError("Codes look like XX-00 with an optional letter, for example A-02a or AA-02.")
    return code


def item_errors(v: dict) -> list[str]:
    """Rules that look at the whole row (spec §4.9 Validation). `v` holds every field's value after the change."""
    errs = []
    low, lst, high = v.get("low"), v.get("list_price"), v.get("high")
    if v.get("basis") == "%":
        for label, n in (("Low", low), ("List", lst), ("High", high)):
            if n is not None and not 0 <= n <= 100:
                errs.append(f"{label} must be between 0 and 100 for a % item.")
    if low is not None and lst is not None and low > lst:
        errs.append("Low must not be above List.")
    if lst is not None and high is not None and lst > high:
        errs.append("List must not be above High.")
    if low is not None and high is not None and low > high and (lst is None):
        errs.append("Low must not be above High.")
    ppy = v.get("periods_per_year")
    share = v.get("billing") == "share" or "share" in (v.get("pricing_unit") or "").casefold()
    if ppy not in (1, 4, 12) and not (ppy == 0 and share):
        errs.append("Periods per year must be 1, 4 or 12 (0 for a partner share).")
    if v.get("price_status") == "approved" and not (v.get("deliverables") or "").strip():
        errs.append("Every item must have deliverables before it can be Approved.")
    return errs


def list_move_warning(old, new) -> str | None:
    if old and new is not None and abs(new - old) / old > LIST_MOVE_WARN:
        return f"List moves more than 25% in one edit ({fmt_money(old)} to {fmt_money(new)})."
    return None


def fmt_money(n) -> str:
    if n is None:
        return ""
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def display(field: str, value) -> str:
    """A value as people read it in history and exports."""
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if field in NUMBER_FIELDS:
        return f"{value:,}" if isinstance(value, (int, float)) else str(value)
    if field == "billing":
        return BILLING.get(value, value)
    if field == "price_status":
        return PRICE_STATUS.get(value, value)
    if field == "sellable_status":
        return SELLABLE.get(value, value)
    if field == "delivery_mode":
        return DELIVERY.get(value, value)
    if field == "included_quantities":
        return quantities_text(value)
    if isinstance(value, list):
        return ", ".join(str(x) for x in value)
    return str(value)
