"""Starter cases for the litigation tracker (demo and browser tests). Every case is real. Facts were checked on
30 October 2026 against the sources listed with each case; stages and courts are as those sources publish them, and
details that could not be confirmed are left out. Check the court record before quoting a stage to a client."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.laws.publish import current_regulations
from app.litigation.models import Case
from app.litigation.service import match_case
from app.reference.models import Jurisdiction

CHECKED_ON = "2026-10-30"  # the day these records were last checked against their sources
HIRING_USES = ["applicant", "candidate", "résumé", "resume", "hiring", "recruit", "screening", "interview"]

CASES = [
    {
        "name": "Mobley v. Workday, Inc.", "jurisdiction": "US", "geography": "United States · federal", "area": "Hiring discrimination (ADEA, Title VII, ADA)",
        "court": "U.S. District Court, Northern District of California", "docket_ref": "3:23-cv-00770", "stage": "discovery",
        "stage_note": "Age (ADEA) collective preliminarily certified", "last_update_on": CHECKED_ON,
        "description": "An applicant says AI screening features in Workday's software rejected him because of his age, race and disability. The claims are brought against the software vendor, not an employer.",
        "why_matters": "A vendor of an AI screening tool can face discrimination claims alongside the employers that use it.\nAge effects (applicants aged 40 and over) are being litigated, not only race and sex.\nDiscovery covers the vendor's bias-testing and applicant data.",
        "talking_points_futran": "If a client uses a vendor's screening tool, ask when it was last independently bias-audited and whether the audit covered age.\nOffer: bias audit that includes age; vendor due-diligence review of hiring tools.",
        "talking_points_client": "List every hiring tool that ranks, scores or filters applicants.\nAsk each vendor for its most recent bias audit, including age.\nKeep a person reviewing automated rejections, and keep the records.",
        "timeline": [{"on": "2025-05-16", "stage": "pleadings", "label": "Order granting preliminary certification of the age (ADEA) collective"},
                     {"on": "2026-05", "stage": "discovery", "label": "Discovery order on bias-testing data, customer applicant data and EEO-1 records"},
                     {"on": "2026-06", "stage": "discovery", "label": "Some FEHA and ADA claims proceed; several newly added claims dismissed"}],
        "laws": [("US", "Title VII"), ("US", "Age Discrimination in Employment Act"), ("US", "Americans with Disabilities Act")],
        "match_rule": {"types": ["vendor_app", "embedded_feature"], "uses": HIRING_USES},
        "sources": [
            {"title": "Order granting preliminary collective certification, 16 May 2025 (Civil Rights Litigation Clearinghouse)", "url": "https://clearinghouse.net/doc/166151"},
            {"title": "Gunderson Dettmer, Quarterly employment law update, spring 2026", "url": "https://www.gunder.com/en/news-insights/insights/client-insight-quarterly-employment-law-update-spring-2026"},
        ],
    },
    {
        "name": "Harper v. Sirius XM Radio, LLC", "jurisdiction": "US", "geography": "United States · federal", "area": "Race discrimination in hiring (Title VII, Section 1981)",
        "court": "U.S. District Court, Eastern District of Michigan", "docket_ref": "2:25-cv-12403", "stage": "dismissed",
        "stage_note": "Dismissed without prejudice on the pleadings", "last_update_on": CHECKED_ON,
        "description": "An applicant said an AI-assisted applicant tracking system (iCIMS) screened him out because of his race, and sought to bring a class action against the employer.",
        "why_matters": "The employer, not only the vendor, was sued over a vendor's AI screening system.\nThe complaint was dismissed because it lacked group-level facts; dismissal without prejudice allows a new complaint.",
        "talking_points_futran": "Employers carry the risk of the hiring tools they buy. Records of adverse-impact testing are the evidence that answers a claim like this.",
        "talking_points_client": "Keep adverse-impact test results for each AI hiring tool.\nRecord which tool features rank or reject applicants.",
        "timeline": [{"on": "2025-08-04", "stage": "filed", "label": "Complaint filed"},
                     {"on": "2026-09-30", "stage": "dismissed", "label": "Judgment on the pleadings granted; complaint dismissed without prejudice"}],
        "laws": [("US", "Title VII")],
        "match_rule": {"types": ["vendor_app", "embedded_feature"], "uses": HIRING_USES},
        "sources": [
            {"title": "Fisher Phillips, Another employer faces AI hiring bias lawsuit", "url": "https://www.fisherphillips.com/en/news-insights/another-employer-faces-ai-hiring-bias-lawsuit.html"},
            {"title": "HR Morning, Sirius XM wins dismissal of AI hiring bias lawsuit", "url": "https://www.hrmorning.com/news/ai-hiring-bias-sirius-xm-harper/"},
        ],
    },
    {
        "name": "xAI LLC v. Weiser", "jurisdiction": "US-CO", "geography": "United States · Colorado", "area": "Challenge to the Colorado AI Act",
        "court": "U.S. District Court, District of Colorado", "docket_ref": "1:26-cv-01515", "stage": "stayed",
        "stage_note": "Enforcement and deadlines stayed by agreement until a ruling on a preliminary injunction", "last_update_on": CHECKED_ON,
        "description": "An AI developer challenges Colorado's AI Act (SB 24-205) as unconstitutional. The United States intervened as a plaintiff. The parties agreed that the Attorney General will not start enforcement until 14 days after the court rules on a preliminary injunction.",
        "why_matters": "Colorado obligations may be delayed or narrowed by the court.\nThe law matrix records that SB 26-189 later repealed and replaced SB 24-205; check how the case treats the new law.",
        "talking_points_futran": "Keep Colorado readiness work going; plan for the 1 January 2027 compliance date under SB 26-189 unless a court order changes it.",
        "talking_points_client": "Do not pause Colorado preparation on the strength of this case alone.\nKeep your inventory of consequential-decision AI current.",
        "timeline": [{"on": "2026-04-09", "stage": "filed", "label": "Complaint filed"},
                     {"on": "2026-04-24", "stage": "pleadings", "label": "United States allowed to intervene"},
                     {"on": "2026-04-27", "stage": "stayed", "label": "Stipulated stay of enforcement; scheduling conference vacated and deadlines stayed"}],
        "laws": [("US-CO", "SB 26-189")],
        "match_rule": {"decision_impact": ["consequential"]},
        "sources": [{"title": "Civil Rights Litigation Clearinghouse, xAI v. Weiser", "url": "https://clearinghouse.net/case/48129/"},
                    {"title": "Jenner & Block, DOJ joins xAI in lawsuit challenging Colorado AI Act", "url": "https://www.jenner.com/en/news-insights/client-alerts/doj-joins-xai-in-lawsuit-challenging-colorado-ai-act"}],
    },
    {
        "name": "Garcia v. Character Technologies, Inc.", "jurisdiction": "US", "geography": "United States · federal", "area": "Product liability (companion chatbot)",
        "court": "U.S. District Court, Middle District of Florida", "docket_ref": None, "stage": "settled", "stage_note": "Settlement reported in a court filing, January 2026",
        "last_update_on": CHECKED_ON,
        "description": "A mother sued a chatbot company and Google over her 14-year-old son's suicide after conversations with a companion chatbot. The court denied the companies' early attempt to dismiss the case in May 2025; the parties later agreed to settle.",
        "why_matters": "Chatbots that talk with minors or vulnerable users carry product-liability exposure.\nThe court did not dismiss the claims at the outset.",
        "talking_points_futran": "Clients running consumer-facing chatbots should be able to show age assurance, crisis escalation and conversation monitoring.",
        "talking_points_client": "Check whether any chatbot you run can reach minors.\nConfirm it routes self-harm topics to human help and crisis resources.",
        "timeline": [{"on": "2025-05", "stage": "pleadings", "label": "Early motion to dismiss rejected"},
                     {"on": "2026-01-07", "stage": "settled", "label": "Court filing reports the parties agreed to settle"}],
        "laws": [],
        "match_rule": {"types": ["genai_chat_tool"], "uses": ["chat", "companion", "assistant", "conversation"]},
        "sources": [{"title": "Deccan Chronicle (Reuters), Google and AI firm settle lawsuit over teen's suicide", "url": "https://www.deccanchronicle.com/technology/google-ai-firm-settle-lawsuit-over-teens-suicide-linked-to-chatbot-1929144"},
                    {"title": "FIRE, Garcia v. Character Technologies: filings and rulings", "url": "https://www.fire.org/cases/garcia-v-character-technologies-inc/filings-rulings"}],
    },
    {
        "name": "Raine v. OpenAI, Inc.", "jurisdiction": "US-CA", "geography": "United States · California", "area": "Product liability (general chatbot)",
        "court": "Superior Court of California, County of San Francisco", "docket_ref": "CGC-25-628528", "stage": "filed", "stage_note": None, "last_update_on": CHECKED_ON,
        "description": "Parents sued OpenAI over their 16-year-old son's suicide, alleging ChatGPT contributed to his death. OpenAI denies responsibility.",
        "why_matters": "General-purpose chatbots, not only companion apps, face wrongful-death claims.\nThe case tests whether terms of use and safety prompts are a defence.",
        "talking_points_futran": "Clients that deploy general chatbots to the public should document safeguards for self-harm topics and how they monitor them.",
        "talking_points_client": "Review how any public-facing chatbot handles self-harm topics.\nKeep records of safety testing before release.",
        "timeline": [{"on": "2025-08-26", "stage": "filed", "label": "Complaint filed"},
                     {"on": "2025-11-26", "stage": "filed", "label": "OpenAI's response denies responsibility"}],
        "laws": [],
        "match_rule": {"types": ["genai_chat_tool"], "uses": ["chat", "assistant", "customer", "public"]},
        "sources": [{"title": "Raine v. OpenAI (Wikipedia, with links to the filings)", "url": "https://en.wikipedia.org/wiki/Raine_v._OpenAI"},
                    {"title": "Insurance Journal, OpenAI and Altman sued over ChatGPT's role in teen's suicide", "url": "https://www.insurancejournal.com/news/national/2025/08/27/837112.htm"}],
    },
    {
        "name": "The New York Times Co. v. Microsoft Corp. and OpenAI", "jurisdiction": "US", "geography": "United States · federal", "area": "Copyright (training data)",
        "court": "U.S. District Court, Southern District of New York", "docket_ref": "MDL No. 3143 (In re OpenAI Copyright Infringement Litigation)",
        "stage": "discovery", "stage_note": "Summary judgment briefing began September 2026", "last_update_on": CHECKED_ON,
        "description": "The Times says OpenAI and Microsoft used its articles without permission to train their models. The case is consolidated with other copyright suits against OpenAI before Judge Stein.",
        "why_matters": "The outcome shapes whether training on copyrighted text needs a licence.\nClients relying on generative AI vendors should know what their contracts say about copyright indemnity.",
        "talking_points_futran": "Ask clients which generative AI vendors indemnify them for copyright claims.",
        "talking_points_client": "Check your generative AI contracts for copyright indemnity.\nKeep a record of which tools produce public-facing content.",
        "timeline": [{"on": "2026-09-04", "stage": "discovery", "label": "Summary judgment briefing starts in the MDL"}],
        "laws": [("US", "Copyright Act")],
        "match_rule": {"types": ["foundation_model_api", "genai_chat_tool"]},
        "sources": [{"title": "ChatGPT is eating the world, Summary judgment briefing starts in OpenAI MDL litigation", "url": "https://chatgptiseatingtheworld.com/2026/09/04/summary-judgment-briefing-starts-in-openai-mdl-litigation-before-judge-stein/embed/"},
                    {"title": "OpenAI copyright MDL 3143 overview", "url": "https://openclassactions.com/investigations/openai-copyright-mdl-lawsuit.php"}],
    },
    {
        "name": "Moffatt v. Air Canada", "jurisdiction": "CA-BC", "geography": "Canada · British Columbia", "area": "Negligent misrepresentation (customer chatbot)",
        "court": "Civil Resolution Tribunal of British Columbia", "docket_ref": "2024 BCCRT 149", "stage": "decided", "stage_note": "Decided 14 February 2024", "last_update_on": CHECKED_ON,
        "description": "A customer relied on the airline's website chatbot, which gave wrong advice about bereavement fares. The tribunal held the airline responsible for the chatbot's answer and ordered it to pay $812.02.",
        "why_matters": "A company answers for what its chatbot tells customers.\n“It should be obvious to Air Canada that it is responsible for all the information on its website.”",
        "talking_points_futran": "Customer chatbots need content controls and a way to check answers against policy.",
        "talking_points_client": "Test what your customer chatbots say about prices, refunds and policies.\nMake sure answers match the published policy, or route the question to a person.",
        "timeline": [{"on": "2024-02-14", "stage": "decided", "label": "Decision: Air Canada liable for its chatbot's misrepresentation"}],
        "laws": [],
        "match_rule": {"types": ["genai_chat_tool"], "uses": ["customer", "refund", "support", "chatbot", "service"]},
        "sources": [{"title": "Moffatt v. Air Canada, 2024 BCCRT 149 (Civil Resolution Tribunal decision)", "url": "https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do"}],
    },
    {
        "name": "OQ v. Land Hessen (SCHUFA Holding, scoring), C-634/21", "jurisdiction": "EU", "geography": "European Union", "area": "GDPR Art. 22 (automated decisions)",
        "court": "Court of Justice of the European Union", "docket_ref": "C-634/21", "stage": "decided", "stage_note": "Judgment of 7 December 2023", "last_update_on": CHECKED_ON,
        "description": "A credit score produced by a credit agency is itself an automated individual decision under Article 22 GDPR where the lender gives it a determining role in granting credit.",
        "why_matters": "A score supplied to someone else can count as the automated decision.\nScoring providers and the firms that rely on them both need an Article 22 basis and safeguards.",
        "talking_points_futran": "Clients that buy or supply scores used in lending, insurance or hiring decisions should map who makes the decision under Article 22.",
        "talking_points_client": "List every score from a third party that drives a decision about a person.\nCheck the legal basis and the human review for each.",
        "timeline": [{"on": "2023-12-07", "stage": "decided", "label": "Judgment delivered"}],
        "laws": [("EU", "GDPR")],
        "match_rule": {"uses": ["credit", "scoring", "loan", "lending", "underwriting"]},
        "sources": [{"title": "Court of Justice of the EU, press release on Case C-634/21", "url": "https://curia.europa.eu/jcms/jcms/p1_4213242/en"}],
    },
    {
        "name": "CK v. Dun & Bradstreet Austria GmbH, C-203/22", "jurisdiction": "EU", "geography": "European Union", "area": "GDPR Art. 15 (explanation of automated decisions)",
        "court": "Court of Justice of the European Union (First Chamber)", "docket_ref": "C-203/22", "stage": "decided", "stage_note": "Judgment of 27 February 2025", "last_update_on": CHECKED_ON,
        "description": "A person can ask for a clear, accessible explanation of the procedure and principles actually used to reach an automated result such as a credit profile. Trade secrets are weighed by the supervisory authority or court, not withheld outright.",
        "why_matters": "“Trade secret” is not a blanket reason to refuse an explanation.\nClients need explanations of automated decisions they can actually give to the person.",
        "talking_points_futran": "Ask clients whether they can explain each automated decision about a person in plain terms, and who holds the vendor's logic.",
        "talking_points_client": "For each automated decision about people, prepare a plain explanation of how the result was reached.\nAgree with vendors how trade-secret information is shared with a regulator or court.",
        "timeline": [{"on": "2025-02-27", "stage": "decided", "label": "Judgment delivered"}],
        "laws": [("EU", "GDPR")],
        "match_rule": {"uses": ["credit", "scoring", "loan", "lending", "profile"]},
        "sources": [{"title": "EU Agency for Fundamental Rights case summary, C-203/22", "url": "https://fra.europa.eu/en/node/46254"},
                    {"title": "Court of Justice of the EU, press release 22/25", "url": "https://curia.europa.eu/jcms/upload/docs/application/pdf/2025-02/cp250022en.pdf"}],
    },
    {
        "name": "ANI Media Pvt. Ltd. v. OpenAI Inc.", "jurisdiction": "IN", "geography": "India", "area": "Copyright (training data)",
        "court": "High Court of Delhi", "docket_ref": "CS(COMM) 1028/2024", "stage": "filed", "stage_note": "Interim injunction refused on 24 July 2026; the suit continues",
        "last_update_on": CHECKED_ON,
        "description": "A news agency says OpenAI used its articles to train ChatGPT without permission. The court refused an interim injunction, finding the use not prima facie infringing at this stage.",
        "why_matters": "India's first major ruling on training generative AI with copyrighted news.\nThe interim view favours the AI developer; the full trial is still to come.",
        "talking_points_futran": "Clients using generative AI in India should track this suit and their vendor contracts.",
        "talking_points_client": "Note which generative AI tools you use in India and what their contracts say about copyright.",
        "timeline": [{"on": "2026-07-24", "stage": "filed", "label": "Interim injunction application dismissed"}],
        "laws": [("IN", "Copyright Act 1957")],
        "match_rule": {"types": ["foundation_model_api", "genai_chat_tool"]},
        "sources": [{"title": "Digital Policy Alert, ANI Media v OpenAI, CS(COMM) 1028/2024", "url": "https://digitalpolicyalert.org/change/20625-lawsuit-relating-to-copyright-infringement-claims-arising-from-use-of-copyrighted-literary-works-in-training-ai-models-ani-media-v-open-ai-cscomm-10282024"},
                    {"title": "LiveLaw, Delhi High Court rejects ANI's interim plea against ChatGPT", "url": "https://www.livelaw.in/high-court/delhi-high-court/delhi-high-court-rejects-ani-copyright-suit-open-ai-chatgpt-542736"}],
    },
]

COURT_SOURCES = [
    ("US", "U.S. federal courts (district court sites)", "https://www.uscourts.gov", "uscourts.gov"),
    ("US-CA", "Superior Court of California, County of San Francisco", "https://sfsuperiorcourt.org", "sfsuperiorcourt.org"),
    ("EU", "Court of Justice of the European Union", "https://curia.europa.eu", "curia.europa.eu"),
    ("IN", "High Court of Delhi", "https://delhihighcourt.nic.in", "delhihighcourt.nic.in"),
    ("CA-BC", "Civil Resolution Tribunal (British Columbia)", "https://civilresolutionbc.ca", "civilresolutionbc.ca"),
]


def _law_ids(db: Session, refs: list[tuple[str, str]]) -> list[str]:
    regs = current_regulations(db)
    codes = dict(db.execute(select(Jurisdiction.id, Jurisdiction.code)).all())
    out = []
    for code, pattern in refs:
        hit = next((r for r in regs if codes.get(r.jurisdiction_id) == code and pattern.lower() in r.short_name.lower()), None)
        if hit is not None:
            out.append(hit.id)
    return out


def seed_court_sources(db: Session) -> int:
    from app.regmaster.models import Source

    n = 0
    for code, name, url, domain in COURT_SOURCES:
        if db.scalar(select(Source.id).where(Source.domain == domain)):
            continue
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == code))
        db.add(Source(jurisdiction_id=j.id if j else None, name=name, url=url, domain=domain, kind="official"))
        n += 1
    db.flush()
    return n


def seed_cases(db: Session) -> int:
    """Add the starter cases that are not there yet (matched by name). Returns how many were added."""
    seed_court_sources(db)
    have = set(db.scalars(select(Case.name)))
    added = 0
    for c in CASES:
        if c["name"] in have:
            continue
        j = db.scalar(select(Jurisdiction).where(Jurisdiction.code == c["jurisdiction"]))
        case = Case(
            jurisdiction_id=j.id if j else None, geography=c["geography"], area=c["area"], name=c["name"], court=c["court"], docket_ref=c["docket_ref"],
            description=c["description"], why_matters=c["why_matters"], stage=c["stage"], stage_note=c["stage_note"],
            last_update_on=date.fromisoformat(c["last_update_on"]), regulation_ids=_law_ids(db, c["laws"]), talking_points_futran=c["talking_points_futran"],
            talking_points_client=c["talking_points_client"], sources=c["sources"], timeline=c["timeline"], match_rule=c["match_rule"], origin="seed", version=1,
        )
        db.add(case)
        db.flush()
        match_case(db, case)
        added += 1
    return added
