"""Futran AI literacy modules (spec §21 F12): structured content in `modules/*.yaml`, short quizzes scored on the server,
and a SCORM 1.2 package for clients who run their own LMS.

A module file holds: code, version, title, minutes, audience, summary, pass_mark, pages [{title, paragraphs, points}] and
quiz [{id, question, options [{id, text}], answer, explanation}]. "{company}" in any text is replaced by the client's name.
Answers and explanations never go to the learner's browser before they answer (the SCORM package is the exception: it
runs inside the client's own LMS without the platform, so it carries its own answer key).
"""
from __future__ import annotations

import copy
import io
import json
import zipfile
from functools import lru_cache
from html import escape
from pathlib import Path

import yaml

HERE = Path(__file__).parent / "modules"
ORDER = ["acceptable_use", "shadow_ai", "human_oversight", "bias_basics_hr", "prompt_hygiene"]


@lru_cache(maxsize=1)
def library() -> dict[str, dict]:
    out = {}
    for p in sorted(HERE.glob("*.yaml")):
        m = yaml.safe_load(p.read_text(encoding="utf-8"))
        m["version"] = str(m["version"])
        m.setdefault("pass_mark", 80)
        out[m["code"]] = m
    return dict(sorted(out.items(), key=lambda kv: ORDER.index(kv[0]) if kv[0] in ORDER else len(ORDER)))


def _fill(obj, company: str):
    if isinstance(obj, str):
        return obj.replace("{company}", company)
    if isinstance(obj, list):
        return [_fill(x, company) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, company) for k, v in obj.items()}
    return obj


def for_client(m: dict, company: str) -> dict:
    return _fill(copy.deepcopy(m), company)


def card(m: dict, company: str) -> dict:
    c = for_client(m, company)
    return {k: c[k] for k in ("code", "version", "title", "minutes", "audience", "summary", "pass_mark")} | {"questions": len(c["quiz"])}


def learner_view(m: dict, company: str) -> dict:
    """The module as the learner's browser receives it: pages and questions, without answers or explanations."""
    c = for_client(m, company)
    return card(m, company) | {"pages": c["pages"], "quiz": [{"id": q["id"], "question": q["question"], "options": q["options"]} for q in c["quiz"]]}


def question(m: dict, qid: str) -> dict | None:
    return next((q for q in m["quiz"] if q["id"] == qid), None)


def score(m: dict, answers: dict) -> int:
    right = sum(1 for q in m["quiz"] if answers.get(q["id"]) == q["answer"])
    return round(100 * right / len(m["quiz"])) if m["quiz"] else 0


# ---- SCORM 1.2
MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="futran-{ident}" version="1.2"
  xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2"
  xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://www.imsproject.org/xsd/imscp_rootv1p1p2 imscp_rootv1p1p2.xsd http://www.imsglobal.org/xsd/imsmd_rootv1p2p1 imsmd_rootv1p2p1.xsd http://www.adlnet.org/xsd/adlcp_rootv1p2 adlcp_rootv1p2.xsd">
  <metadata>
    <schema>ADL SCORM</schema>
    <schemaversion>1.2</schemaversion>
  </metadata>
  <organizations default="org-1">
    <organization identifier="org-1">
      <title>{title}</title>
      <item identifier="item-1" identifierref="res-1" isvisible="true">
        <title>{title}</title>
        <adlcp:masteryscore>{mastery}</adlcp:masteryscore>
      </item>
    </organization>
  </organizations>
  <resources>
    <resource identifier="res-1" type="webcontent" adlcp:scormtype="sco" href="index.html">
      <file href="index.html"/>
    </resource>
  </resources>
</manifest>
"""

PLAYER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#16233A;background:#fff;line-height:1.55}}
main{{max-width:720px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:19px;margin:24px 0 8px}}
.meta{{color:#5A6577;font-size:14px;margin:0 0 16px}}
.opt{{display:flex;gap:10px;align-items:center;border:1px solid #D9DFE7;border-radius:8px;padding:12px;margin:8px 0;min-height:44px;box-sizing:border-box}}
button{{min-height:44px;padding:0 18px;border-radius:6px;border:1px solid #1B3A6B;background:#1B3A6B;color:#fff;font:inherit;font-weight:600}}
.result{{margin-top:16px;font-weight:600}}
</style></head>
<body><main>
<h1>{title}</h1><p class="meta">{meta}</p>
<div id="content"></div>
<h2>Quick check</h2>
<form id="quiz"></form>
<button type="button" id="submit">Submit answers</button>
<p class="result" id="result" role="status"></p>
</main>
<script>
var MODULE = {data};
var API = null;
function findAPI(win){{var n=0;while(win&&!win.API&&win.parent&&win.parent!==win&&n<10){{win=win.parent;n++;}}return win?win.API:null;}}
API = findAPI(window) || (window.opener ? findAPI(window.opener) : null);
function lms(fn, a, b){{ if(!API) return ""; try {{ return b===undefined ? API[fn](a) : API[fn](a,b); }} catch(e) {{ return ""; }} }}
lms("LMSInitialize", "");
if (lms("LMSGetValue", "cmi.core.lesson_status") === "not attempted") lms("LMSSetValue", "cmi.core.lesson_status", "incomplete");
function el(tag, text){{var e=document.createElement(tag); if(text!==undefined) e.textContent=text; return e;}}
var content = document.getElementById("content");
MODULE.pages.forEach(function(p){{
  content.appendChild(el("h2", p.title));
  (p.paragraphs||[]).forEach(function(t){{content.appendChild(el("p", t));}});
  if (p.points && p.points.length){{var ul=el("ul"); p.points.forEach(function(t){{ul.appendChild(el("li", t));}}); content.appendChild(ul);}}
}});
var form = document.getElementById("quiz");
MODULE.quiz.forEach(function(q, i){{
  var fs=el("fieldset"); fs.style.border="none"; fs.style.padding="0"; fs.appendChild(el("legend", (i+1)+". "+q.question));
  q.options.forEach(function(o){{var l=el("label"); l.className="opt"; var r=el("input"); r.type="radio"; r.name=q.id; r.value=o.id; l.appendChild(r); l.appendChild(document.createTextNode(o.text)); fs.appendChild(l);}});
  form.appendChild(fs);
}});
document.getElementById("submit").addEventListener("click", function(){{
  var right=0;
  MODULE.quiz.forEach(function(q){{var c=form.querySelector('input[name="'+q.id+'"]:checked'); if(c&&c.value===q.answer) right++;}});
  var score=Math.round(100*right/MODULE.quiz.length), passed=score>=MODULE.pass_mark;
  lms("LMSSetValue","cmi.core.score.min","0"); lms("LMSSetValue","cmi.core.score.max","100");
  lms("LMSSetValue","cmi.core.score.raw", String(score));
  lms("LMSSetValue","cmi.core.lesson_status", passed ? "passed" : "failed");
  lms("LMSCommit","");
  document.getElementById("result").textContent = (passed ? "Passed" : "Not passed yet") + ": " + score + "%. " + (passed ? "You can close this module." : "Read the module again and retry.");
  if (passed) lms("LMSFinish","");
}});
window.addEventListener("beforeunload", function(){{ lms("LMSFinish",""); }});
</script>
</body></html>
"""


def scorm_zip(m: dict, company: str) -> bytes:
    c = for_client(m, company)
    data = {"pages": c["pages"], "quiz": c["quiz"], "pass_mark": c["pass_mark"]}
    # JSON inside a <script>: escape "<", ">" and "&" so no text in the module can close the script element
    js = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    title = escape(c["title"])
    html = PLAYER.format(title=title, meta=escape(f"{c['minutes']} minutes · {c['audience']} · Futran module v{c['version']} · pass mark {c['pass_mark']}%"), data=js)
    manifest = MANIFEST.format(ident=f"{c['code']}-{c['version']}".replace(".", "-"), title=title, mastery=c["pass_mark"])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("imsmanifest.xml", manifest)
        z.writestr("index.html", html)
    return buf.getvalue()
