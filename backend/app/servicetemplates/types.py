"""Engagement types (spec §9.2, Release 2 B6). The one place they are defined: `Engagement.type` takes a key of
ENGAGEMENT_TYPES, and every screen shows its label. No imports from the rest of the app, so anything can import it."""

ENGAGEMENT_TYPES: dict[str, str] = {
    # v0.6.1
    "initial_assessment": "Initial AI governance assessment",
    "ll144_bias_audit": "LL144 bias audit",
    "annual_review": "Annual review",
    # Release 2 B6
    "vendor_due_diligence": "Vendor AI due diligence",
    "vendor_sponsored_audit": "Vendor-sponsored LL144 audit",
    "ll144_applicability": "LL144 applicability (8-case map)",
    "copilot_readiness": "Microsoft 365 Copilot readiness",
    "eu_ai_act_readiness": "EU AI Act conformity readiness",
    "iso42001_readiness": "ISO/IEC 42001 readiness",
    "ma_due_diligence": "M&A AI due diligence",
    "agent_assurance": "Agent Assure",
    "training_workshop": "Training workshop",
    "advisory_retainer": "Advisory retainer",
}
ORIGINAL_ENGAGEMENT_TYPES: tuple[str, ...] = ("initial_assessment", "ll144_bias_audit", "annual_review")
NEW_ENGAGEMENT_TYPES: tuple[str, ...] = tuple(k for k in ENGAGEMENT_TYPES if k not in ORIGINAL_ENGAGEMENT_TYPES)


def type_label(key: str | None) -> str:
    return ENGAGEMENT_TYPES.get(key or "", (key or "").replace("_", " ").capitalize())
