"""Client Q&A helper (spec §21 F1): explains what a questionnaire question means, from the glossary and the question's
help text. It never suggests an answer: the prompt forbids it, and an explanation that still proposes one (names the
answer, or tells the person which option to choose, in the explanation or in any term's meaning) is discarded, recorded as rejected, and replaced by the help text."""
import re

from sqlalchemy.orm import Session

from app.ai import prompts as P
from app.ai import service as ai
from app.ai.glossary import terms_for
from app.questionnaire import service as qs
from app.questionnaire.models import Question
from app.tenancy.models import User

PROPOSES = re.compile(r"the (?:correct |right )?answer (?:is|would be|should be)|you should (?:answer|choose|select|pick|say)|(?:answer|choose|select|pick|tick) (?:\"|')?(?:yes|no)\b|so choose|best answer", re.I)


def proposes_answer(text: str, q: Question) -> bool:
    if PROPOSES.search(text or ""):
        return True
    low = (text or "").lower()
    return any(re.search(rf"(?:choose|select|pick|answer|tick)\s+[\"']?{re.escape(o['label'].lower())}", low) for o in q.options or [])


def fallback(q: Question) -> str:
    return " ".join(f"This question asks about {q.label.rstrip('?').lower()}. {q.help_text or ''} Answer from what your team actually does; if you are unsure, ask the person responsible.".split())


def explain(db: Session, app_state, settings, actor: User, t: qs.Target, code: str) -> dict:
    ai.require_ai(t.engagement)
    q = qs._question(db, t, code, futran=False)
    glossary = terms_for(q.label, q.help_text or "", q.section_title)
    opts = "; ".join(o["label"] for o in q.options or [])
    prompt = (f"Section: {q.section_title}\nQuestion {q.code}: {q.label}\nHelp text: {q.help_text or '(none)'}\nAnswer format: {q.type}" + (f" (options: {opts})" if opts else "") +
              "\n\nGlossary:\n" + ("\n".join(f"- {g['term']}: {g['meaning']}" for g in glossary) or "(no glossary terms)") +
              "\n\nExplain the question. Never suggest which answer applies.")
    c = ai.call(app_state, settings, task="explain", prompt_version=P.EXPLAIN_VERSION, system=P.EXPLAIN_SYSTEM, prompt=prompt, schema=P.EXPLAIN_SCHEMA,
                context={"question": {"code": q.code, "label": q.label, "help": q.help_text, "section": q.section_title}, "glossary": glossary})
    text = str(c.reply.data.get("explanation") or "").strip()
    terms = [x for x in c.reply.data.get("terms") or [] if isinstance(x, dict) and x.get("term")]
    # every text the client would see is checked, not only the explanation
    shown_texts = [text] + [str(x.get(k) or "") for x in terms for k in ("term", "meaning")]
    bad = not text or any(proposes_answer(t, q) for t in shown_texts)
    shown = fallback(q) if bad else text
    row = ai.record(db, actor, c, organization_id=t.engagement.client_id, feature="explain", engagement_id=t.engagement.id, ai_system_id=t.system_id,
                    input_refs=[{"type": "question", "id": q.id}], target_type="question", target_id=q.id, target_code=q.code,
                    output={"explanation": text, "shown": shown, "terms": terms, "proposed_an_answer": bad and bool(text)},
                    citations=[{"source_type": "glossary", "source_id": None, "label": g["term"], "quote": g["meaning"], "found": True} for g in glossary], confidence=None)
    if bad:
        ai.decide(db, actor, row, "rejected", "The explanation proposed an answer, so the help text was shown instead." if text else "The explanation was empty.")
    ai.log_call(db, actor, c, [row], f"Explained question {q.code} to {actor.name}", t.engagement.id, t.engagement.client_id)
    return {"code": q.code, "explanation": shown, "terms": terms if not bad else glossary}
