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
    "huge output": "{% for i in range(1000) %}{{ 'ABCDEFGHIJ' * 1000 }}{% endfor %}",
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
