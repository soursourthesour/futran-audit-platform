"""SPF, DKIM and DMARC check for the sending domain (E1). Looks up public DNS through DNS over HTTPS (dns.google), so no
DNS library is needed. A failed lookup leaves the result unknown (None) rather than wrong."""
import httpx

DOH = "https://dns.google/resolve"
DKIM_SELECTORS = {"microsoft365": ["selector1", "selector2"], "google": ["google"]}


def _answers(c: httpx.Client, name: str, typ: str) -> list[str]:
    r = c.get(DOH, params={"name": name, "type": typ})
    r.raise_for_status()
    data = r.json()
    return [str(a.get("data", "")).strip('"') for a in data.get("Answer", []) or []]


def check_domain(domain: str, provider: str | None, transport: httpx.BaseTransport | None = None) -> dict:
    domain = (domain or "").strip().lower()
    try:
        with httpx.Client(timeout=10.0, transport=transport) as c:
            spf = any(a.lower().startswith("v=spf1") for a in _answers(c, domain, "TXT"))
            dmarc = any(a.lower().startswith("v=dmarc1") for a in _answers(c, f"_dmarc.{domain}", "TXT"))
            dkim = False
            for sel in DKIM_SELECTORS.get(provider or "", ["selector1", "google"]):
                name = f"{sel}._domainkey.{domain}"
                if _answers(c, name, "CNAME") or any("v=dkim1" in a.lower() or "p=" in a.lower() for a in _answers(c, name, "TXT")):
                    dkim = True
                    break
        return {"spf_ok": spf, "dkim_ok": dkim, "dmarc_ok": dmarc}
    except (httpx.HTTPError, ValueError):
        return {"spf_ok": None, "dkim_ok": None, "dmarc_ok": None}
