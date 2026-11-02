"""Futran policy templates (spec §21 F7): deterministic rendering from the client's answers. No AI.

Each template is a Markdown file in `templates/` with YAML front matter:

    ---
    code: acceptable_use
    version: "1.0"
    title: AI acceptable use policy
    summary: One line for the template library.
    catalog_codes: [GD-04]          # governance catalog items (spec §10.5) the template answers
    questions: [{key, label, type, help, required, default, options}]
    ---
    # {{ company_name }} AI Acceptable Use Policy
    ...

The body is a Jinja2 template rendered in a sandbox. Answers are passed as values, never as template source, so text a
client types ("{{ 7*7 }}", "<script>") stays text. The rendered Markdown is parsed into blocks of three kinds only:
heading (levels 1–3), paragraph and list. Those blocks are what the client edits and what the PDF is written from.

Question types: text, textarea, list (one entry per line), choice (one of options), multi (any of options), yesno.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

HERE = Path(__file__).parent / "templates"
REVIEW_MONTHS = {"annually": 12, "six_months": 6}
COMMON_KEYS = ("company_name", "policy_owner", "review_cycle")
TYPES = {"text", "textarea", "list", "choice", "multi", "yesno"}
MAX_TEXT = 600
MAX_LONG = 4000
MAX_ITEMS = 40
MAX_BLOCKS = 400
MAX_BLOCK_TEXT = 6000


@dataclass(frozen=True)
class TemplateDef:
    code: str
    version: str
    title: str
    summary: str
    catalog_codes: tuple[str, ...]
    questions: list[dict] = field(hash=False)
    body: str = field(hash=False)

    @property
    def name(self) -> str:
        """The title in sentence case for screens ("AI acceptable use policy"); the document itself keeps title case."""
        words = self.title.split()
        return " ".join([words[0]] + [w if w.isupper() else w.lower() for w in words[1:]])

    def question(self, key: str) -> dict | None:
        return next((q for q in self.questions if q["key"] == key), None)


def _split(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        raise ValueError("A policy template starts with YAML front matter between --- lines.")
    return yaml.safe_load(m.group(1)), m.group(2)


def _load(path: Path) -> TemplateDef:
    meta, body = _split(path.read_text(encoding="utf-8"))
    qs = meta.get("questions") or []
    for q in qs:
        if q.get("type", "text") not in TYPES:
            raise ValueError(f"{path.name}: unknown question type {q.get('type')}")
        q.setdefault("type", "text")
    return TemplateDef(code=meta["code"], version=str(meta["version"]), title=meta["title"], summary=meta["summary"],
                       catalog_codes=tuple(meta.get("catalog_codes") or ()), questions=qs, body=body)


@lru_cache(maxsize=1)
def library() -> dict[str, TemplateDef]:
    out = {}
    for p in sorted(HERE.glob("*.md")):
        t = _load(p)
        out[t.code] = t
    return out


def for_catalog_code(code: str) -> str | None:
    """The template that answers a governance catalog item (GD-04 → acceptable_use)."""
    return next((t.code for t in library().values() if code in t.catalog_codes), None)


# ---- answers
def defaults(t: TemplateDef, company_name: str) -> dict:
    out: dict = {}
    for q in t.questions:
        if q["key"] == "company_name":
            out["company_name"] = company_name
        elif "default" in q:
            d = q["default"]
            out[q["key"]] = list(d) if isinstance(d, list) else d
        elif q["type"] in ("list", "multi"):
            out[q["key"]] = []
        elif q["type"] == "yesno":
            out[q["key"]] = False
        else:
            out[q["key"]] = ""
    return out


def _one_line(v, limit: int) -> str:
    return " ".join(str(v if v is not None else "").split())[:limit]


def clean_answers(t: TemplateDef, raw: dict) -> tuple[dict, list[dict]]:
    """Answers checked against the template's questions. Unknown keys are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    errs: list[dict] = []
    for q in t.questions:
        k, typ, v = q["key"], q["type"], raw.get(q["key"])
        opts = [o["value"] for o in q.get("options") or []]
        if typ in ("text", "textarea"):
            val = _one_line(v, MAX_TEXT) if typ == "text" else str(v or "").strip()[:MAX_LONG]
            if q.get("required") and not val:
                errs.append({"field": k, "message": f"Answer “{q['label']}”."})
            out[k] = val
        elif typ == "list":
            items = v if isinstance(v, list) else str(v or "").splitlines()
            val = [s for s in (_one_line(i, MAX_TEXT) for i in items) if s][:MAX_ITEMS]
            if q.get("required") and not val:
                errs.append({"field": k, "message": f"Add at least one entry to “{q['label']}”."})
            out[k] = val
        elif typ == "choice":
            if v not in opts:
                errs.append({"field": k, "message": f"Choose an option for “{q['label']}”."})
                v = q.get("default") if q.get("default") in opts else opts[0]
            out[k] = v
        elif typ == "multi":
            vals = v if isinstance(v, list) else []
            if any(x not in opts for x in vals):
                errs.append({"field": k, "message": f"Choose from the options for “{q['label']}”."})
            val = [o for o in opts if o in vals]
            if q.get("required") and not val:
                errs.append({"field": k, "message": f"Choose at least one option for “{q['label']}”."})
            out[k] = val
        else:  # yesno
            out[k] = bool(v) and v not in ("false", "no", "0")
    return out, errs


# ---- rendering
def _join_and(items) -> str:
    items = [str(i) for i in items]
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _env(t: TemplateDef) -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, autoescape=False)
    env.filters["join_and"] = _join_and
    env.filters["lower_first"] = lambda s: s[:1].lower() + s[1:] if s and not s[1:2].isupper() else s

    def label(key: str, value) -> str:
        q = t.question(key) or {}
        return next((o["label"] for o in q.get("options") or [] if o["value"] == value), str(value))

    env.globals["label"] = label
    env.globals["labels"] = lambda key, values: [label(key, v) for v in values or []]
    return env


def render(t: TemplateDef, answers: dict) -> list[dict]:
    md = _env(t).from_string(t.body).render(**answers, review_months=REVIEW_MONTHS.get(answers.get("review_cycle"), 12))
    return parse_markdown(md)


_ORDERED = re.compile(r"^\d+\.\s+(.*)$")


def parse_markdown(md: str) -> list[dict]:
    """Markdown with headings (#, ##, ###), paragraphs and lists (- or 1.) into blocks. Anything else is a paragraph."""
    blocks: list[dict] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append({"type": "paragraph", "text": " ".join(para)})
            para.clear()

    for line in md.splitlines():
        s = line.strip()
        if not s:
            flush()
            continue
        h = re.match(r"^(#{1,3})\s+(.*)$", s)
        o = _ORDERED.match(s)
        if h:
            flush()
            blocks.append({"type": "heading", "level": len(h.group(1)), "text": h.group(2).strip()})
        elif s.startswith("- ") or o:
            flush()
            ordered = bool(o)
            item = o.group(1) if o else s[2:]
            last = blocks[-1] if blocks else None
            if last and last["type"] == "list" and last["ordered"] == ordered:
                last["items"].append(item.strip())
            else:
                blocks.append({"type": "list", "ordered": ordered, "items": [item.strip()]})
        else:
            if blocks and blocks[-1]["type"] == "list" and not para and line.startswith("  "):
                blocks[-1]["items"][-1] += " " + s  # a wrapped list item
            else:
                para.append(s)
    flush()
    return blocks


def blocks_to_markdown(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        if b["type"] == "heading":
            out.append(f"{'#' * b['level']} {b['text']}")
        elif b["type"] == "paragraph":
            out.append(b["text"])
        else:
            out.append("\n".join(f"{n}. {i}" if b["ordered"] else f"- {i}" for n, i in enumerate(b["items"], 1)))
    return "\n\n".join(out) + "\n"


def clean_blocks(raw) -> tuple[list[dict], list[dict]]:
    """What the client's editor may store: headings (1–3), paragraphs and lists of plain text."""
    if not isinstance(raw, list):
        return [], [{"field": "blocks", "message": "The policy text is missing."}]
    out: list[dict] = []
    errs: list[dict] = []
    if len(raw) > MAX_BLOCKS:
        errs.append({"field": "blocks", "message": f"A policy can have up to {MAX_BLOCKS} headings, paragraphs and lists."})
    for i, b in enumerate(raw[:MAX_BLOCKS]):
        b = b if isinstance(b, dict) else {}
        typ = b.get("type")
        if typ == "heading":
            level = b.get("level")
            text = _one_line(b.get("text"), 300)
            if level not in (1, 2, 3) or not text:
                errs.append({"field": f"blocks.{i}", "message": f"Block {i + 1}: a heading needs text and a level from 1 to 3."})
                continue
            out.append({"type": "heading", "level": level, "text": text})
        elif typ == "paragraph":
            text = " ".join(str(b.get("text") or "").split())[:MAX_BLOCK_TEXT]
            if text:
                out.append({"type": "paragraph", "text": text})
        elif typ == "list":
            items = [s for s in (" ".join(str(x or "").split())[:MAX_BLOCK_TEXT] for x in (b.get("items") if isinstance(b.get("items"), list) else [])) if s][:200]
            if not items:
                errs.append({"field": f"blocks.{i}", "message": f"Block {i + 1}: a list needs at least one item."})
                continue
            out.append({"type": "list", "ordered": bool(b.get("ordered")), "items": items})
        else:
            errs.append({"field": f"blocks.{i}", "message": f"Block {i + 1}: only headings, paragraphs and lists can be used."})
    if not errs and not out:
        errs.append({"field": "blocks", "message": "The policy has no text."})
    return out, errs


def plain_text(blocks: list[dict]) -> str:
    return "\n".join(b["text"] if b["type"] != "list" else "\n".join(b["items"]) for b in blocks)
