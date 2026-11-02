"""Deterministic answers for the in-process fake model (tests, demo, browser tests). Each handler reads the same
context the prompt was built from and only quotes sentences it was given, so its suggestions pass the quote check.
It is a stand-in for the real model, not a model: keyword overlap picks the passage, and simple cues pick the answer."""
import re

from app.ai.text import sentences

STOP = set("""a an and are as at be been by can do does for from has have how if in into is it its of on or that the their them there these this to was
were what when where which who whom why will with within without would your you our we any all each other than then also not only per such who's""".split())
HEDGE = re.compile(r"\b(tbd|to be (?:confirmed|decided|completed)|not yet|planned|draft|missing|incomplete|informal|ad hoc|no formal|partial(?:ly)?|pending)\b", re.I)
NEGATIVE = re.compile(r"\b(no|not|none|never|without|tbd)\b", re.I)
FREQ = ["real-time", "hourly", "daily", "weekly", "fortnightly", "monthly", "quarterly", "annually", "yearly"]
YES = ("yes", "always", "documented")


def _stem(w: str) -> str:
    return w[:6]


def words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9-]+", (text or "").lower()) if len(w) > 2 and w not in STOP}


def _passages(documents: list[dict], refs: list[str] | None = None):
    for d in documents:
        if refs is not None and d["ref"] not in refs:
            continue
        for p in d.get("pages") or []:
            for s in sentences(p["text"]):
                yield d, p["page"], s


def best(documents: list[dict], text: str, refs: list[str] | None = None, minimum: int = 2):
    """(document, page, sentence, score) with the most words in common with `text`, or None."""
    want = words(text)
    top = None
    for d, page, s in _passages(documents, refs):
        score = len(want & words(s))
        if score >= minimum and (top is None or score > top[3]):
            top = (d, page, s, score)
    return top


def _choice(q: dict, s: str) -> str | None:
    opts = q.get("options") or []
    values = {o["value"] for o in opts}
    low = s.lower()
    for o in opts:  # an option named in the passage
        if o["value"] not in ("yes", "no", "unknown", "na", "none") and (o["label"].lower() in low or o["value"].replace("_", " ") in low or any(w in low for w in o["label"].lower().split() if len(w) > 4)):
            return o["value"]
    if values & {"yes", "no"}:
        if HEDGE.search(s) or NEGATIVE.search(s):
            return "no" if "no" in values else None
        return "yes"
    if "always" in values:
        return "specific" if HEDGE.search(s) else "always"
    return None


def _value(q: dict, s: str):
    t = q["type"]
    if t in ("single", "yes_no", "yes_no_unknown"):
        return _choice(q, s)
    if t == "multi":
        hits = [o["value"] for o in q.get("options") or [] if o["label"].lower() in s.lower()]
        return ", ".join(hits) or None
    if t in ("number", "percent"):
        m = re.search(r"\d+(?:\.\d+)?", s)
        return m.group(0) if m else None
    if t == "date":
        m = re.search(r"\b(20\d\d-\d\d-\d\d)\b", s)
        return m.group(1) if m else None
    if t in ("text", "long_text"):
        return s[:2000]
    return None


def prefill(ctx: dict) -> dict:
    out = []
    for q in ctx.get("questions") or []:
        hit = best(ctx.get("documents") or [], f"{q['label']} {q.get('help') or ''} " + " ".join(o["label"] for o in q.get("options") or []))
        value = _value(q, hit[2]) if hit else None
        if not hit or value is None:
            out.append({"code": q["code"], "answer": None, "detail": None, "document": None, "page": None, "quote": None, "confidence": "low",
                        "not_found_note": "No passage in the uploaded documents answers this question.", "draft_finding": None})
            continue
        d, page, s, score = hit
        hedge = bool(HEDGE.search(s))
        conf = "medium" if hedge else ("high" if score >= 3 else "low")
        draft = None
        if hedge:
            draft = {"title": f"{q['label']}: documentation incomplete", "severity": "medium",
                     "condition": f"{d['filename']} (page {page}) states: \"{s}\"", "criteria": f"Template question {q['code']} ({q['label']}) expects this to be documented and in place.",
                     "cause": "The documentation was not completed before the system went into use.",
                     "effect": "The auditor cannot confirm that the control operates as the template expects.",
                     "recommendation": f"Complete and approve the documentation for {q['label'].lower()}, and provide the approved version as evidence."}
        out.append({"code": q["code"], "answer": value, "detail": f"From {d['filename']}, page {page}.", "document": d["ref"], "page": page, "quote": s, "confidence": conf,
                    "not_found_note": None, "draft_finding": draft})
    return {"suggestions": out}


def evidence_check(ctx: dict) -> dict:
    out = []
    for it in ctx.get("items") or []:
        hit = best(ctx.get("documents") or [], it["text"], it.get("documents"))
        if hit is None:
            out.append({"code": it["code"], "verdict": "does_not_support", "reason": "None of the linked files addresses this item.", "document": None, "page": None, "quote": None, "confidence": "medium"})
            continue
        d, page, s, score = hit
        if "independent" in it["text"].lower() and re.search(r"model owner|same team|own team|data science team", s, re.I):
            verdict, reason = "does_not_support", "The linked file says the work is done by the model owner's own team, which is not independent."
        elif HEDGE.search(s) or score < 3:
            verdict, reason = "partly", "The linked file touches on this item but does not show it fully in place."
        else:
            verdict, reason = "supports", "The linked file states this directly."
        out.append({"code": it["code"], "verdict": verdict, "reason": reason, "document": d["ref"], "page": page, "quote": s, "confidence": "high" if score >= 3 else "medium"})
    return {"items": out}


def contradictions(ctx: dict) -> dict:
    out = []
    for iv in ctx.get("interviews") or []:
        said = f"{iv.get('answer') or ''} {iv.get('detail') or ''}".lower()
        mine = [f for f in FREQ if f in said]
        if not mine:
            continue
        for d, page, s in _passages(ctx.get("documents") or []):
            theirs = [f for f in FREQ if f in s.lower()]
            if theirs and not set(theirs) & set(mine) and len(words(iv["label"]) & words(s)) >= 1:
                out.append({"code": iv["code"], "interview_says": f"{iv.get('person') or 'The interviewee'} said {mine[0]}.", "document_says": f"{d['filename']} says {theirs[0]}.",
                            "document": d["ref"], "page": page, "quote": s, "confidence": "high"})
                break
    return {"contradictions": out}


def ask(ctx: dict) -> dict:
    hit = best(ctx.get("documents") or [], ctx.get("question") or "")
    if hit is None:
        return {"answer": "None of the uploaded documents answers this question.", "citations": [], "confidence": "low"}
    d, page, s, score = hit
    return {"answer": f"{d['filename']} (page {page}) says: \"{s}\"", "citations": [{"document": d["ref"], "page": page, "quote": s}], "confidence": "high" if score >= 3 else "medium"}


def draft_finding(ctx: dict) -> dict:
    f = ctx.get("finding") or {}
    answers = ctx.get("answers") or []
    seen = "; ".join(f"{a['code']} {a['label']}: {a['answer']}" for a in answers) or "the answers recorded for this system"
    return {"title": f.get("title") or "Finding", "severity": f.get("severity") or "medium", "condition": f"The answers recorded show: {seen}.",
            "criteria": f"Template question{'s' if len(answers) != 1 else ''} {', '.join(a['code'] for a in answers) or 'in scope'}" + (f" and the rule \"{ctx['rule']}\"." if ctx.get("rule") else "."),
            "cause": "The control has not been designed or put into operation for this system.", "effect": "The organisation cannot show that the risk this control addresses is managed.",
            "recommendation": "Assign an owner, put the control in place, and keep evidence that it operates."}


def summary(ctx: dict) -> dict:
    facts = ctx.get("facts") or []
    findings = [f for f in facts if f.startswith("Finding ")]
    refs = [re.match(r"Finding (\S+)", f).group(1) for f in findings][:3]
    sev = {}
    for f in findings:
        m = re.match(r"Finding \S+ \((\w+)", f)
        if m:
            sev[m.group(1)] = sev.get(m.group(1), 0) + 1
    counts = ", ".join(f"{n} {k}" for k, n in sev.items()) or "no findings"
    text = f"{facts[0] if facts else ''} The review covers {ctx.get('label')}. It has {counts}."
    if findings:
        text += " The most significant: " + "; ".join(f.split(": ", 1)[-1] for f in findings[:3]) + "."
    return {"summary": text, "sources": refs or [r for r in ctx.get("refs") or []][:2], "confidence": "medium"}


def explain(ctx: dict) -> dict:
    q = ctx.get("question") or {}
    text = (f"This question asks about {q.get('label', '').rstrip('?').lower()}. " + (q.get("help") or "") +
            " The auditor asks it to understand how this part of the AI system is run in practice. Answer from what your team actually does, and say who gave the answer;"
            " if you are unsure, say so rather than guessing.")
    return {"explanation": " ".join(text.split()), "terms": [{"term": t["term"], "meaning": t["meaning"]} for t in ctx.get("glossary") or []]}


DUTY = re.compile(r"\b(shall|must|is required to|are required to|may not|shall not)\b", re.I)
ACTORS = [("data_fiduciary", r"data fiduciar"), ("employer", r"employer"), ("deployer", r"deployer|user of"), ("developer", r"developer"), ("provider", r"provider")]
DEADLINE = re.compile(r"(within \d+ (?:business |calendar )?days?[^.;,]*|no (?:later|less) than [^.;,]+|before [^.;,]+|at least \d+ [^.;,]+ (?:before|prior)[^.;,]*|annually|once a year|every year)", re.I)
CITE = re.compile(r"(§+\s?[\d\-\w().]+|Section \d+[\w.()]*|Article \d+[\w.()]*|Art\. \d+[\w.()]*)")


def obligations(ctx: dict) -> dict:
    out = []
    default_actor = ctx.get("default_actor") or "deployer"
    for src in ctx.get("sources") or []:
        for s in sentences(src["text"]):
            if not DUTY.search(s):
                continue
            actor = next((a for a, pat in ACTORS if re.search(pat, s, re.I)), default_actor)
            m, c = DEADLINE.search(s), CITE.search(s)
            reqs = [r["code"] for r in ctx.get("requirements") or [] if len(words(r["text"]) & words(s)) >= 3]
            qs = [k for k, pat in (ctx.get("question_cues") or {}).items() if re.search(pat, s, re.I)]
            out.append({"text": s[:600], "actor": actor, "action": DUTY.split(s, maxsplit=1)[-1].strip()[:300] or s[:300], "condition": None, "deadline": m.group(0) if m else None,
                        "citation": c.group(0) if c else src.get("citation"), "quote": s, "requirement_codes": reqs, "question_codes": qs[:4], "confidence": "high" if reqs else "medium"})
    return {"obligations": out[:40]}


def questionnaire(ctx: dict) -> dict:
    out = []
    for it in ctx.get("items") or []:
        top = None
        for src in ctx.get("sources") or []:
            for s in sentences(src["text"]) if src["kind"] != "library" else [src["answer"]]:
                score = len(words(it["question"]) & words((src.get("question") or "") + " " + s))
                if score >= 2 and (top is None or score > top[2]):
                    top = (src, s, score)
        if top is None:
            out.append({"item": it["ref"], "answer": None, "source": None, "quote": None, "confidence": "low"})
            continue
        src, s, score = top
        out.append({"item": it["ref"], "answer": s if src["kind"] != "library" else src["answer"], "source": src["ref"], "quote": s, "confidence": "high" if score >= 4 else "medium"})
    return {"answers": out}


HANDLERS = {"copilot_prefill": prefill, "evidence_check": evidence_check, "review_check": contradictions, "ask": ask, "draft_finding": draft_finding, "summary": summary,
            "explain": explain, "obligation_extract": obligations, "questionnaire": questionnaire}


def answer(task: str, context: dict) -> dict:
    handler = HANDLERS.get(task)
    return handler(context) if handler else {}
