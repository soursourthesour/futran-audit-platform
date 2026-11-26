"""Review 11-25 H07: an editable template cannot tie up the server. The two attacks from the security pass (a huge
string and nested loops) and the other ways to make one render do unbounded work are refused, on save and at
generation."""
import time

import pytest

from app.core.errors import Invalid
from app.reference.jurisdictions import seed_iso
from app.reference.templates import TemplateTooLarge, edit_template, load_templates, render_string
from tests.factories import make_org, make_user


@pytest.fixture
def admin(db):
    seed_iso(db)
    f = make_org(db, type="futran")
    load_templates(db)
    return make_user(db, f, roles=["admin"], name="Ada Admin", email="admin@f.test")


ATTACKS = {
    "string times a big number": "{{ 'A' * 20000000 }}",
    "list times a big number": "{{ ([1] * 20000000) | length }}",
    "big power": "{{ 9 ** 999999 }}",
    "nested loops": "{% for i in range(3000) %}{% for j in range(3000) %}{% endfor %}{% endfor %}",
    "three nested loops": "{% for i in range(100) %}{% for j in range(100) %}{% for k in range(100) %}x{% endfor %}{% endfor %}{% endfor %}",
    "doubling a namespace": "{% set ns = namespace(s='AAAAAAAA') %}{% for i in range(40) %}{% set ns.s = ns.s ~ ns.s %}{% endfor %}{{ ns.s | length }}",
    "padding method": "{{ 'a'.ljust(500000000) }}",
    "padding filter": "{{ 'a' | center(500000000) }}",
    "huge output": "{% for i in range(5000) %}{{ 'ABCDEFGHIJ' * 1000 }}{% endfor %}",
}


@pytest.mark.parametrize("body", ATTACKS.values(), ids=ATTACKS.keys())
def test_runaway_templates_are_stopped_quickly(body):
    start = time.monotonic()
    with pytest.raises(TemplateTooLarge):
        render_string(body, {})
    assert time.monotonic() - start < 3


@pytest.mark.parametrize("body", [ATTACKS["string times a big number"], ATTACKS["nested loops"]], ids=["string", "loops"])
def test_a_runaway_template_is_refused_on_save(db, admin, body):
    with pytest.raises(Invalid) as e:
        edit_template(db, admin, "roles_note", body)
    assert "too much work" in str(e.value.errors[0]["message"])


def test_a_template_body_over_the_size_limit_is_refused(db, admin):
    with pytest.raises(Invalid):
        edit_template(db, admin, "roles_note", "x" * 600_000)


def test_ordinary_templates_still_render():
    body = ("{% for f in findings %}| {{ f.title | md_cell }} | {{ loop.index }} |\n{% endfor %}"
            "{{ '-' * 40 }} {{ 2 ** 10 }} {% for i in range(12) %}{{ i }}{% endfor %} {{ 'x' | center(20) }}")
    out = render_string(body, {"findings": [{"title": f"Finding {n}"} for n in range(500)]})
    assert "| Finding 499 | 500 |" in out and "1024" in out and "01234567891011" in out


def test_each_render_gets_its_own_budget():
    body = "{% for i in range(60000) %}{% endfor %}done"
    for _ in range(5):  # 300,000 iterations across five renders, each well inside its own budget
        assert render_string(body, {}) == "done"


# Other shapes of the same attack: output built inside buffered blocks, concatenation inside autoescape, and methods,
# filters and operators whose cost is set by an argument rather than by the template's size.
MORE_ATTACKS = {
    "output inside a set block": "{% set x %}{% for i in range(100000) %}{{ 'A' * 999999 }}{% endfor %}{% endset %}ok",
    "output inside a macro": "{% macro m() %}{% for i in range(100000) %}{{ 'A' * 999999 }}{% endfor %}{% endmacro %}{% set y = m() %}",
    "literal text in a loop": "{% for i in range(100000) %}" + "A" * 1000 + "{% endfor %}",
    "doubling inside autoescape": "{% autoescape true %}{% set x = 'AAAAAAAA' %}" + "{% set x = x ~ x %}" * 40 + "{% endautoescape %}{{ x | length }}",
    "doubling a list": "{% set ns = namespace(l=[0]) %}{% for i in range(30) %}{% set ns.l = ns.l + ns.l %}{% endfor %}",
    "squaring a number": "{% set ns = namespace(x=3) %}{% for i in range(40) %}{% set ns.x = ns.x * ns.x %}{% endfor %}",
    "join filter": "{{ (['A' * 999999] * 999999) | join | length }}",
    "join separator": "{{ range(99999) | join('A' * 999999) | length }}",
    "join method": "{{ ('A' * 999999).join(['a'] * 999999) | length }}",
    "replace method": "{{ ('A' * 999999).replace('A', 'B' * 999999) | length }}",
    "replace filter": "{{ ('A' * 999999) | replace('', 'B' * 999) | length }}",
    "percent repeats an argument": "{{ (('%s' * 99999) % (('A' * 999999,) * 99999)) | length }}",
    "percent star width": "{{ '%*s' % (500000000, 'a') }}",
    "percent width": "{{ '%500000000s' % 'a' }}",
    "format filter width": "{{ '%500000000s' | format('a') }}",
    "format method width": "{{ '{:>500000000}'.format('a') }}",
    "format method nested width": "{{ '{:>{w}}'.format('a', w=500000000) }}",
    "lipsum": "{{ lipsum(100000, max=1000) | length }}",
    "to_bytes": "{{ (1).to_bytes(500000000, 'big') | length }}",
    "sum of lists": "{{ ([[0] * 999999] * 999) | sum(start=[]) | length }}",
    "batch padding": "{{ [1] | batch(500000000, 0) | list | length }}",
    "slice count": "{{ [1] | slice(500000000) | list | length }}",
    "indent": "{{ ('\\n' * 999999) | indent(999999) | length }}",
    "expandtabs": "{{ ('\\t' * 999999).expandtabs(99) | length }}",
    "translate": "{{ ('a' * 999999).translate({97: 'b' * 999}) | length }}",
    "recursive loop": "{% for x in range(99999) recursive %}{% if loop.depth < 5 %}{{ loop(range(99999)) }}{% endif %}{% endfor %}",
    "macro calls": "{% macro f() %}{% endmacro %}{% for i in range(99999) %}{% for j in range(99999) %}{{ f() }}{% endfor %}{% endfor %}",
}


@pytest.mark.parametrize("body", MORE_ATTACKS.values(), ids=MORE_ATTACKS.keys())
def test_other_runaway_shapes_are_stopped_quickly(body):
    start = time.monotonic()
    with pytest.raises(TemplateTooLarge):
        render_string(body, {})
    assert time.monotonic() - start < 3


def test_every_shipped_template_renders_inside_the_limits():
    from app.reference.templates import TEMPLATE_DIR

    shipped = sorted(TEMPLATE_DIR.glob("*.md.j2"))
    assert len(shipped) >= 10
    for path in shipped:
        render_string(path.read_text(encoding="utf-8"), {})  # raises TemplateTooLarge if one trips a limit


def test_loops_keep_their_loop_variable_and_else():
    body = ("{% for x in range(3) %}{{ loop.index }}/{{ loop.length }} {% endfor %}"
            "{% for x in [] %}x{% else %}empty{% endfor %} "
            "{% for x in range(9) if x is even %}{{ x }}{% endfor %} "
            "{% for k, v in {'a': 1}.items() %}{{ k }}={{ v }}{% endfor %} "
            "{% set ns = namespace(n=0) %}{% for i in range(4) %}{% set ns.n = ns.n + i %}{% endfor %}{{ ns.n }} "
            "{{ '%05.1f' % 3.14159 }} {{ '{:>6}'.format('ab') }} {{ 'a-b' | replace('-', '+') }} {{ [1, 2] | join(', ') }}")
    assert render_string(body, {}) == "1/3 2/3 3/3 empty 02468 a=1 6 003.1     ab a+b 1, 2"


def test_a_render_past_its_time_limit_is_stopped():
    with pytest.raises(TemplateTooLarge, match="longer than"):
        render_string("{% for i in range(10) %}{% endfor %}", {}, seconds=0)


# Review 11-25 (Chitragupta) on f6abc0a, probes ported with the expectation flipped.

S = "{% set s = 'x' * 999999 %}"
TEXT_EXPANDERS = {  # a cheap container turned into text: each builds 200 MB or more if nothing measures it first
    "output a list of one big string x200": S + "{{ [s] * 200 }}",
    "concat a list": S + "{{ 'a' ~ ([s] * 200) }}",
    "string filter": S + "{{ ([s] * 200) | string | length }}",
    "tojson filter": S + "{{ ([s] * 200) | tojson | length }}",
    "join measures str(list)": S + "{{ [[s] * 200] | join | length }}",
    "percent with a list": S + "{{ '%s' % ([s] * 200,) }}",
    "replace filter str(list)": S + "{{ ([s] * 200) | replace('a', 'b') | length }}",
}
# the same conversions from a two-item literal, which no repeat check sees: only the conversion itself can refuse it
L = S + "{% set l = [s, s] %}"
TEXT_FROM_LITERALS = {
    "output": L + "{{ l }}",
    "concat": L + "{{ 'a' ~ l }}",
    "string filter": L + "{{ l | string | length }}",
    "tojson filter": L + "{{ l | tojson | length }}",
    "pprint filter": L + "{{ l | pprint | length }}",
    "upper filter": L + "{{ l | upper | length }}",
    "md_cell filter": L + "{{ l | md_cell | length }}",
    "join of lists": L + "{{ [l] | join | length }}",
    "percent": L + "{{ '%s' % (l,) }}",
    "format method": L + "{{ '{}'.format(l) }}",
    "replace filter": L + "{{ l | replace('a', 'b') | length }}",
    "list plus list": L + "{{ (l + ['a']) | length }}",
    "dict values": S + "{% set d = {'a': s, 'b': s} %}{{ d.values() }}",
}


@pytest.mark.parametrize("body", [*TEXT_EXPANDERS.values(), *TEXT_FROM_LITERALS.values()],
                         ids=[*TEXT_EXPANDERS.keys(), *("literal " + k for k in TEXT_FROM_LITERALS)])
def test_a_container_is_measured_before_it_becomes_text(body):
    start = time.monotonic()
    with pytest.raises(TemplateTooLarge):
        render_string(body, {})
    assert time.monotonic() - start < 3


def test_a_million_copies_of_a_big_string_is_refused_within_a_memory_cap():
    """The reviewer's proof: 999,999 references to a 1M-character string, then text; and a 2,000-item literal of the
    same, which no repeat check sees. Each would build 2 GB or more. Run in a child process capped at 1.5 GB of address
    space, so a regression fails with MemoryError there instead of taking the shared machine down."""
    import subprocess
    import sys
    from pathlib import Path

    tails = ["{{ l }}", "{{ l | string | length }}", "{{ 'a' ~ l }}", "{{ l | tojson | length }}", "{{ l | pprint | length }}",
             "{{ l | upper | length }}", "{{ l | md_cell | length }}", "{{ [l] | join | length }}", "{{ '%s' % (l,) }}",
             "{{ '{}'.format(l) }}", "{{ l | replace('a', 'b') | length }}", "{{ (l + ['a']) | length }}"]
    heads = ["{% set s = 'x' * 999999 %}{% set l = [s] * 999999 %}", "{% set s = 'x' * 999999 %}{% set l = [" + "s, " * 2000 + "] %}"]
    script = (
        "import resource, sys\n"
        "resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))\n"
        "from app.reference.templates import TemplateTooLarge, render_string\n"
        "heads, tails = eval(sys.argv[1]), eval(sys.argv[2])\n"
        "for head in heads:\n"
        "    for tail in tails:\n"
        "        try:\n"
        "            render_string(head + tail, {})\n"
        "            print('rendered', tail)\n"
        "        except TemplateTooLarge:\n"
        "            print('refused')\n"
        "        except MemoryError:\n"
        "            print('memory-error', tail)\n"
    )
    backend = Path(__file__).resolve().parents[2]
    run = subprocess.run([sys.executable, "-c", script, repr(heads), repr(tails)], cwd=backend, capture_output=True, text=True, timeout=180)
    assert run.stdout.split() == ["refused"] * (len(heads) * len(tails)), run.stdout + run.stderr[-2000:]


FILTER_CHAINS = {  # one expression, no loop and no call: only the filters themselves can see the clock
    "map a filter": S + "{{ s" + "|map('upper')" * 60 + "|list|length }}",
    "map an attribute": S + "{{ s|list" + "|map(attribute=0)" * 60 + "|list|length }}",
    "select with a test": "{% set n = range(99999) | list %}{{ n" + "|select('number')" * 80 + "|list|length }}",
    "selectattr": S + "{{ s|list" + "|selectattr(0)|rejectattr(1)" * 30 + "|list|length }}",
    "sort and unique": "{% set s = 'abcdefghij' * 99999 %}" + "{{ s|list|sort|list|reverse|list|sort|unique|list|length }}" * 40,
    "groupby": "{% set d = [{'a': 1}] * 20000 %}" + "{{ d | groupby('a') | length }}" * 1000,
}


@pytest.mark.parametrize("body", FILTER_CHAINS.values(), ids=FILTER_CHAINS.keys())
def test_a_long_filter_chain_stops_at_the_deadline(body):
    start = time.monotonic()
    with pytest.raises(TemplateTooLarge, match="longer than"):
        render_string(body, {}, seconds=1)
    assert time.monotonic() - start < 2.5


@pytest.mark.parametrize("body", [
    "{% set environment = 1 %}{{ 'a' ~ 'b' }}{% for x in [1] %}{{ x }}{% endfor %}",
    "{% macro m(environment) %}{{ environment ~ 'x' }}{% for i in [1] %}{% endfor %}{% endmacro %}{{ m(1) }}",
    "{% for environment in [1, 2] %}{{ 'a' ~ environment }}{% endfor %}",
    "{% with environment = 3 %}{{ environment ~ 'x' }}{% endwith %}",
    "{{ environment }}|{{ budget_iter }}|{{ self }}",
])
def test_a_template_cannot_shadow_the_environment_the_guards_call(body):
    from app.reference import templates as T

    src = T._env.compile(body, raw=True)
    assert "\nenvironment =" not in src
    assert " environment = " not in src.replace("l_0_environment", "").replace("l_1_environment", "")
    render_string(body, {})


def _large_report_context(findings=500, systems=100, chars=1600):
    para = ("The organization has not documented a bias test for this system and the owner could not show evidence of "
            "review. " * (chars // 100 + 1))[:chars]
    fs = [{"ref": f"F-{i:03d}", "title": f"Finding {i} title about governance", "severity": "high", "severity_label": "High",
           "section": "Governance", "system": f"SYS-{i % systems:03d}", "use_cases": "Hiring", "owner": "Owner Name",
           "due": "1 Jan 2027", "system_or_scope": "SYS", "condition": para, "risk": para, "remediation": para,
           "citations": [f"NYC LL144 §20-87{k}" for k in range(4)],
           "questions": [{"code": f"Q{k}", "label": "Is there a documented test?", "answer": "No"} for k in range(6)],
           "evidence": [{"ref": f"EV-{k}", "text": para[:200], "status": "Accepted", "answer": "Yes"} for k in range(6)]}
          for i in range(findings)]
    ss = [{"ref": f"SYS-{i:03d}", "name": f"System {i}", "vendor": "Vendor", "built_by": "Vendor", "department": "HR",
           "use_cases": "Hiring", "inherent": 3.2, "maturity": 2, "residual": 2.4, "rating": "High", "depth": "Full",
           "calc": "3.2 x 0.75", "computed": "x", "knockouts": ["K1", "K2"], "weights": "Standard", "eu_level": "High"}
          for i in range(systems)]
    responses = [{"ref": f"F-{i:03d}", "owner": "O", "target_date": "2027", "response": para} for i in range(findings)]
    return {"findings": fs, "findings_by_severity": [{"label": "High findings", "items": fs}], "systems": ss,
            "management_responses": responses, "summary": {"critical": fs[:50]}}


def test_the_shipped_report_renders_for_a_large_engagement():
    from app.reference.templates import TEMPLATE_DIR

    body = (TEMPLATE_DIR / "report.md.j2").read_text(encoding="utf-8")
    out = render_string(body, _large_report_context())  # past the first limit of 5,000,000 characters
    assert len(out) > 5_000_000 and "F-499" in out


def test_the_refusal_names_the_limit_and_suits_who_sees_it(db, admin):
    with pytest.raises(TemplateTooLarge) as e:
        render_string("{{ 'A' * 20000000 }}", {})  # at generation: the reader may not be the editor
    assert e.value.detail.startswith("The document template does too much work to render (")
    assert "1,000,000 characters" in e.value.detail and "An administrator can check the template." in e.value.detail
    assert "Simplify" not in e.value.detail
    with pytest.raises(TemplateTooLarge) as e:
        edit_template(db, admin, "roles_note", "{% for i in range(3000) %}{% for j in range(3000) %}{% endfor %}{% endfor %}")
    assert "200,000" in e.value.errors[0]["message"] and "Simplify it." in e.value.errors[0]["message"]


# Review 11-25 (Chitragupta) on b7647ed: many separate values, each inside the per-value limit, held at once.
MANY_VALUES = {
    "a list literal of 2,500 long strings": "{% set l = [" + ",".join(["'x'*999999"] * 2500) + "] %}{{ l|length }}",
    "2,500 separate set lines": "".join(f"{{% set a{n} = 'x'*999999 %}}" for n in range(2500)) + "done",
}


def test_many_separate_large_values_are_refused_within_a_memory_cap():
    """Each would hold about 2.5 GB. Run in a child process capped at 1.5 GB of address space, as above; the save-time
    trial render (2 s) is checked with 6,000 values, which reached MemoryError at 2.24 s under a 3 GB cap."""
    import subprocess
    import sys
    from pathlib import Path

    cases = [(body, False) for body in MANY_VALUES.values()]
    cases.append(("{% set l = [" + ",".join(["'x'*999999"] * 6000) + "] %}{{ l|length }}", True))
    script = (
        "import resource, sys, time\n"
        "resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))\n"
        "from app.reference.templates import SAVE_SECONDS, TemplateTooLarge, render_string\n"
        "for body, saving in eval(sys.stdin.read()):\n"
        "    start = time.monotonic()\n"
        "    try:\n"
        "        render_string(body, {}, seconds=SAVE_SECONDS if saving else 10, editing=saving)\n"
        "        print('rendered')\n"
        "    except TemplateTooLarge as exc:\n"
        "        print('refused' if time.monotonic() - start < 3 and 'in total' in exc.reason else 'slow-or-other:' + exc.reason.replace(' ', '_'))\n"
        "    except MemoryError:\n"
        "        print('memory-error')\n"
    )
    backend = Path(__file__).resolve().parents[2]
    run = subprocess.run([sys.executable, "-c", script], input=repr(cases), cwd=backend, capture_output=True, text=True, timeout=180)
    assert run.stdout.split() == ["refused"] * len(cases), run.stdout + run.stderr[-2000:]


def test_the_large_report_builds_well_inside_the_total():
    from app.reference import templates as T

    body = (T.TEMPLATE_DIR / "report.md.j2").read_text(encoding="utf-8")
    budget = T._Budget(T.RENDER_SECONDS)
    token = T._budget.set(budget)
    try:
        T._env.from_string(body).render(**_large_report_context())
    finally:
        T._budget.reset(token)
    assert budget.built < T.MAX_BUILT // 5, budget.built
