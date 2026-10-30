"""Law versions: the first version from a matrix row, copying a version forward, and applying approved changes."""
import re

GUIDANCE_TYPES = {"voluntary", "guidance", "policy", "framework"}


def status_from_text(status_text: str | None, reg_type: str | None) -> str:
    """Best first guess at a LawVersion status from the matrix's free text and type (used by the v1 data move)."""
    t = (status_text or "").lower()
    if re.search(r"repeal|lapsed|struck down|vetoed", t):
        return "repealed"
    if re.search(r"delay|postpon|under amendment", t):
        return "delayed"
    if re.search(r"enacted|not yet in force|effective \d|from \d", t) and "in force" not in t:
        return "enacted_not_in_force"
    if "phased" in t:
        return "in_force_phased"
    if reg_type in GUIDANCE_TYPES:
        return "guidance"
    if reg_type == "pending":
        return "pending"
    return "in_force"
