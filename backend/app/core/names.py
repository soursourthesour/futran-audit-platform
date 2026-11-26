"""Display names shared across screens and messages."""


def tool_name(vendor: str | None, product: str | None) -> str:
    """'Microsoft Copilot', but 'Otter.ai' (not 'Otter.ai Otter.ai') when vendor and product are the same name, ignoring
    case and surrounding spaces (OBS-07). The frontend has the same rule in src/lib/toolName.ts."""
    v, p = (vendor or "").strip(), (product or "").strip()
    if not v or v.casefold() == p.casefold():
        return p or v
    return f"{v} {p}" if p else v
