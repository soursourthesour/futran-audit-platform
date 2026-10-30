"""Regulator and provider deadline rules for incidents (spec §27.3: EU AI Act Art. 73 and 26(5), Colorado AG notice where in
scope, CERT-In 6 hours).

Every rule was checked against the official text on 30 October 2026. The quotes below are copied from these sources:

- EU AI Act, Regulation (EU) 2024/1689, consolidated text as at 27 July 2026 (EUR-Lex CELEX 02024R1689-20260727) and the
  Commission's AI Act Service Desk pages for Articles 26 and 73:
    https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02024R1689-20260727
    https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-73
    https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26
  Art. 73(2): "not later than 15 days after the provider or, where applicable, the deployer, becomes aware of the serious incident."
  Art. 73(3): "in the event of a widespread infringement or a serious incident as defined in Article 3, point (49)(b) ... immediately,
              and not later than two days after the provider or, where applicable, the deployer becomes aware of that incident."
  Art. 73(4): "in the event of the death of a person ... not later than 10 days after the date on which the provider or, where
              applicable, the deployer becomes aware of the serious incident."
  Art. 73(5): an initial report that is incomplete may be followed by a complete report.
  Art. 26(5): "Where deployers have identified a serious incident, they shall also immediately inform first the provider, and then
              the importer or distributor and the relevant market surveillance authorities of that incident."
              "If the deployer is not able to reach the provider, Article 73 shall apply mutatis mutandis."
              Where use may present a risk within Art. 79(1): "they shall, without undue delay, inform the provider or distributor
              and the relevant market surveillance authority, and shall suspend the use of that system."
  Art. 3(49) "serious incident": (a) death or serious harm to health; (b) serious and irreversible disruption of critical
              infrastructure; (c) infringement of obligations under Union law intended to protect fundamental rights;
              (d) serious harm to property or the environment.
  Application: Regulation (EU) 2026/1744 (Digital Omnibus on AI; OJ 24 July 2026, in force 27 July 2026) moved the high-risk
  duties, which include Art. 26 and Art. 73, to 2 December 2027 for Annex III systems (2 August 2028 for Annex I).
  Source: White & Case, "EU AI Omnibus enters into force, amending the AI Act"
    https://www.whitecase.com/insight-alert/eu-ai-omnibus-enters-force-amending-ai-act

- CERT-In Directions No. 20(3)/2022-CERT-In of 28 April 2022 under section 70B(6) of the IT Act 2000, direction (ii):
    https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf
  "shall mandatorily report cyber incidents as mentioned in Annexure I to CERT-In within 6 hours of noticing such incidents or
   being brought to notice about such incidents." In force 60 days after issue (27 June 2022).

- Colorado SB 26-189 (engrossed text, https://leg.colorado.gov/bill_files/115943/download), which repeals and re-enacts
  part 17 of article 1 of title 6, C.R.S. It contains no duty for a developer or deployer to notify the Attorney General:
  SB 24-205's 90-day notice of algorithmic discrimination was not carried forward. The only Attorney General clock is the cure
  period in §6-1-1706(3)(b): "IF THE DEVELOPER OR DEPLOYER FAILS TO CURE A VIOLATION WITHIN SIXTY DAYS AFTER RECEIPT OF A NOTICE
  OF VIOLATION". The platform therefore tracks the 60-day cure period from the day an AG notice of violation is received.
  The act applies from 1 January 2027.

Where the law says "immediately" or "without undue delay" there is no fixed period; the platform sets a target (24 or 72 hours)
and labels it as a target, not a statutory deadline.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

EUR_LEX = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX%3A02024R1689-20260727"
ART_73 = "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-73"
ART_26 = "https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-26"
CERT_IN = "https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf"
CO_SB189 = "https://leg.colorado.gov/bill_files/115943/download"

EU_HIGH_RISK_FROM = date(2027, 12, 2)  # Annex III, as amended by Regulation (EU) 2026/1744
CO_FROM = date(2027, 1, 1)
EU_NOT_YET = "Not yet binding: EU AI Act high-risk duties apply from 2 Dec 2027 (Regulation (EU) 2026/1744). Tracked as good practice."
CO_NOT_YET = "Colorado SB 26-189 applies from 1 Jan 2027."

LAW_FAMILIES = ("eu_ai_act", "colorado", "india")
FAMILY_LABELS = {"eu_ai_act": "EU AI Act", "colorado": "Colorado SB 26-189", "india": "India (CERT-In Directions)"}

SERIOUS_LABELS = {
    "none": "Not a serious incident",
    "death": "Death of a person",
    "health": "Serious harm to a person's health",
    "critical_infrastructure": "Serious and irreversible disruption of critical infrastructure",
    "fundamental_rights": "Infringement of EU law protecting fundamental rights",
    "property_environment": "Serious harm to property or the environment",
    "widespread_infringement": "Widespread infringement",
}


@dataclass(frozen=True)
class Rule:
    code: str
    family: str
    recipient: str
    law: str
    citation: str
    quote: str
    source_url: str
    period_text: str
    statutory: bool
    applies_from: date | None


ART73_15 = Rule("eu_art73_15d", "eu_ai_act", "Market surveillance authority", "EU AI Act", "EU AI Act Art. 73(2), with Art. 26(5)",
                "not later than 15 days after the provider or, where applicable, the deployer, becomes aware of the serious incident",
                ART_73, "15 days from becoming aware", True, EU_HIGH_RISK_FROM)
ART73_2 = Rule("eu_art73_2d", "eu_ai_act", "Market surveillance authority", "EU AI Act", "EU AI Act Art. 73(3), with Art. 26(5)",
               "immediately, and not later than two days after the provider or, where applicable, the deployer becomes aware of that incident",
               ART_73, "2 days from becoming aware", True, EU_HIGH_RISK_FROM)
ART73_10 = Rule("eu_art73_10d", "eu_ai_act", "Market surveillance authority", "EU AI Act", "EU AI Act Art. 73(4), with Art. 26(5)",
                "not later than 10 days after the date on which the provider or, where applicable, the deployer becomes aware of the serious incident",
                ART_73, "10 days from becoming aware", True, EU_HIGH_RISK_FROM)
ART26_PROVIDER = Rule("eu_art26_provider", "eu_ai_act", "AI provider", "EU AI Act", "EU AI Act Art. 26(5)",
                      "Where deployers have identified a serious incident, they shall also immediately inform first the provider",
                      ART_26, "Immediately (platform target: 24 hours)", False, EU_HIGH_RISK_FROM)
ART26_RISK = Rule("eu_art26_risk", "eu_ai_act", "AI provider or distributor, and the market surveillance authority; suspend use", "EU AI Act",
                  "EU AI Act Art. 26(5), Art. 79(1)", "they shall, without undue delay, inform the provider or distributor and the relevant market surveillance authority",
                  ART_26, "Without undue delay (platform target: 72 hours)", False, EU_HIGH_RISK_FROM)
CERTIN_6H = Rule("certin_6h", "india", "CERT-In", "CERT-In Directions (India)", "CERT-In Directions of 28 Apr 2022, direction (ii)",
                 "report cyber incidents as mentioned in Annexure I to CERT-In within 6 hours of noticing such incidents or being brought to notice about such incidents",
                 CERT_IN, "6 hours from noticing", True, date(2022, 6, 27))
CO_CURE_60D = Rule("co_ag_cure_60d", "colorado", "Colorado Attorney General: cure the violation", "Colorado SB 26-189", "§6-1-1706(3)(b), C.R.S. (SB 26-189)",
                   "IF THE DEVELOPER OR DEPLOYER FAILS TO CURE A VIOLATION WITHIN SIXTY DAYS AFTER RECEIPT OF A NOTICE OF VIOLATION",
                   CO_SB189, "60 days from receiving the AG notice of violation", True, CO_FROM)

RULES = (ART26_PROVIDER, ART73_15, ART73_2, ART73_10, ART26_RISK, CERTIN_6H, CO_CURE_60D)
RULES_BY_CODE = {r.code: r for r in RULES}

# periods; "immediately" and "without undue delay" have platform targets (statutory=False)
PERIODS = {"eu_art73_15d": timedelta(days=15), "eu_art73_2d": timedelta(days=2), "eu_art73_10d": timedelta(days=10), "eu_art26_provider": timedelta(hours=24),
           "eu_art26_risk": timedelta(hours=72), "certin_6h": timedelta(hours=6), "co_ag_cure_60d": timedelta(days=60)}


def art73_rule(serious_kind: str) -> Rule | None:
    if serious_kind in (None, "", "none"):
        return None
    if serious_kind == "death":
        return ART73_10
    if serious_kind in ("critical_infrastructure", "widespread_infringement"):
        return ART73_2
    return ART73_15


@dataclass(frozen=True)
class Due:
    rule: Rule
    clock_start_at: datetime
    due_at: datetime
    binding: bool
    binding_note: str | None


def due_for(rule: Rule, start: datetime) -> Due:
    """The deadline a rule gives for a clock that starts at `start`. Day periods ending on a calendar day end at 23:59 that day."""
    if rule.code == "co_ag_cure_60d":
        end = datetime.combine(start.date() + PERIODS[rule.code], time(23, 59))
    else:
        end = start + PERIODS[rule.code]
    binding = rule.applies_from is None or start.date() >= rule.applies_from
    note = None if binding else (EU_NOT_YET if rule.family == "eu_ai_act" else CO_NOT_YET)
    return Due(rule, start, end, binding, note)


def applicable(families: set[str], *, found_at: datetime, serious_kind: str, risk_to_rights: bool, cyber_incident: bool, ag_notice_received_on: date | None) -> list[Due]:
    """The deadlines an incident needs, given the law families in scope for its system."""
    out: list[Due] = []
    if "eu_ai_act" in families:
        r73 = art73_rule(serious_kind)
        if r73 is not None:
            out.append(due_for(ART26_PROVIDER, found_at))
            out.append(due_for(r73, found_at))
        if risk_to_rights:
            out.append(due_for(ART26_RISK, found_at))
    if "india" in families and cyber_incident:
        out.append(due_for(CERTIN_6H, found_at))
    if "colorado" in families and ag_notice_received_on is not None:
        out.append(due_for(CO_CURE_60D, datetime.combine(ag_notice_received_on, time(0, 0))))
    return out


def reminder_at(clock_start_at: datetime, due_at: datetime) -> datetime:
    """When to remind: a quarter of the period before the deadline, at most 24 hours before it."""
    lead = min((due_at - clock_start_at) / 4, timedelta(hours=24))
    return due_at - lead
