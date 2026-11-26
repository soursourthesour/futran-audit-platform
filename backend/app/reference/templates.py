"""Versioned document templates (Markdown + Jinja). Admin edits create a new version."""
import contextvars
import functools
import inspect
import math
import re
import string
import time

import yaml
from jinja2 import StrictUndefined, TemplateSyntaxError, Undefined
from jinja2.compiler import CodeGenerator, optimizeconst
from jinja2.exceptions import SecurityError
from jinja2.filters import make_attrgetter
from jinja2.runtime import markup_join
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jinja2.utils import Namespace, generate_lorem_ipsum
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_log import service as audit
from app.core.errors import Invalid, NotFound
from app.reference.jurisdictions import SEEDS
from app.reference.models import DocumentTemplate
from app.tenancy.models import User

TEMPLATE_DIR = SEEDS / "templates"

# Review 11-25 H07: admins edit these templates in the browser and the hosted app is one process, so one render must not
# be able to stall it. Each render gets a budget; the generated template code counts against it (cooperative: no threads
# or processes, so it works the same on the Windows laptop).
MAX_SEQ = 1_000_000  # characters or items one expression may build
MAX_STEPS = 200_000  # loop iterations plus calls in one render
MAX_OUTPUT = 5_000_000  # characters of output in one render, counted at every output, buffered blocks included
MAX_BODY = 500_000  # characters in one template body, checked on save
MAX_DIGITS = 100  # digits in an integer that * or ** may produce
MAX_TABSIZE = 100
RENDER_SECONDS = 10  # at generation
SAVE_SECONDS = 2  # the trial render on save

_INT_BITS = int(MAX_DIGITS * math.log2(10)) + 1
_SEQ = (str, bytes, list, tuple)
_SIZED = (str, bytes, list, tuple, dict, set, frozenset)


class TemplateTooLarge(Invalid):
    """A template that would make one render do unbounded work."""

    def __init__(self, reason: str):
        message = f"This template does too much work to render: {reason}. Simplify it."
        super().__init__(message, [{"field": "body", "message": message}])


class _Budget:
    __slots__ = ("steps", "out", "seconds", "deadline")

    def __init__(self, seconds: float):
        self.steps = self.out = 0
        self.seconds = seconds
        self.deadline = time.monotonic() + seconds


_budget: contextvars.ContextVar[_Budget | None] = contextvars.ContextVar("template_budget", default=None)


def _tick() -> None:
    b = _budget.get()
    if b is None:
        return
    b.steps += 1
    if b.steps > MAX_STEPS:
        raise TemplateTooLarge(f"it runs more than {MAX_STEPS:,} loop steps and calls")
    if time.monotonic() > b.deadline:
        raise TemplateTooLarge(f"it takes longer than {b.seconds:g} seconds")


def _too_long():
    return TemplateTooLarge(f"it builds a value of more than {MAX_SEQ:,} characters or items")


def _check_size(value):
    if isinstance(value, _SIZED) and len(value) > MAX_SEQ:
        raise _too_long()
    return value


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_width(width, limit: int = MAX_SEQ) -> None:
    if _is_int(width) and width > limit:
        raise TemplateTooLarge(f"a width or size of {width:,} is over the limit of {limit:,}")


def _text_len(v, seen: dict) -> int:
    """An upper bound on len(str(v)), cheap for the common cases."""
    if isinstance(v, (str, bytes)):
        return len(v)
    if v is None or isinstance(v, (bool, float)):
        return 32
    if isinstance(v, int):
        return v.bit_length() // 3 + 2
    key = id(v)
    if key not in seen:
        seen[key] = len(str(v))
    return seen[key]


def _check_spread(fmt: str, fields: int, values) -> None:
    """A format string repeats its arguments once per field: refuse when that would build an oversize string."""
    if not fields:
        return
    seen: dict = {}
    widest = max((_text_len(v, seen) for v in values), default=0)
    if len(fmt) + fields * widest > MAX_SEQ:
        raise _too_long()


_PERCENT = re.compile(r"%%|%(?:\([^)]*\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d*))?")
_BIG_NUMBER = re.compile(r"\d{7,}")


def _check_percent(fmt: str, right) -> None:
    """`fmt % right`: no * widths, no width or precision of 7+ digits, no oversize result."""
    fields = 0
    for m in _PERCENT.finditer(fmt):
        if m.group(0) == "%%":
            continue
        fields += 1
        for part in m.groups():
            if part == "*":
                raise TemplateTooLarge("a format takes its width from an argument; write the width as a number")
            if part and len(part) >= 7:
                raise TemplateTooLarge(f"a format width or precision is {MAX_SEQ:,} or more")
    _check_spread(fmt, fields, right if isinstance(right, tuple) else (right,))


def _check_str_format(fmt: str, values) -> None:
    """str.format and format_map: no nested or 7+ digit widths, no oversize result."""
    fields = 0
    try:
        parsed = list(string.Formatter().parse(fmt))
    except ValueError:
        return  # a malformed format fails in the call itself
    for _, name, spec, _ in parsed:
        if name is None:
            continue
        fields += 1
        if spec and "{" in spec:
            raise TemplateTooLarge("a format takes its width from an argument; write the width as a number")
        if spec and _BIG_NUMBER.search(spec):
            raise TemplateTooLarge(f"a format width or precision is {MAX_SEQ:,} or more")
    _check_spread(fmt, fields, values)


def _check_replace(s, old, new, count) -> None:
    if not isinstance(s, (str, bytes)) or not isinstance(old, type(s)) or not isinstance(new, type(s)) or len(new) <= len(old):
        return
    n = s.count(old)
    if _is_int(count) and count >= 0:
        n = min(n, count)
    if len(s) + n * (len(new) - len(old)) > MAX_SEQ:
        raise _too_long()


def _check_join(sep, items, attribute=None, environment=None) -> None:
    if attribute is not None and environment is not None:
        getter = make_attrgetter(environment, attribute)
        items = [getter(x) for x in items]
    seen: dict = {}
    sep_len = len(sep) if isinstance(sep, (str, bytes)) else _text_len(sep, seen)
    total = sep_len * max(len(items) - 1, 0)
    for x in items:
        total += _text_len(x, seen)
        if total > MAX_SEQ:
            raise _too_long()


def _check_str_method(s, name: str, args: tuple, kwargs: dict) -> tuple:
    """Bound str and bytes methods whose cost is set by an argument rather than by the string. Returns the args to call
    with (join gets its iterable as a list, so it can be measured first)."""
    def arg(i, key, default=None):
        return args[i] if len(args) > i else kwargs.get(key, default)

    if name in ("ljust", "rjust", "center", "zfill"):
        _check_width(arg(0, "width"))
    elif name == "expandtabs":
        size = arg(0, "tabsize", 8)
        _check_width(size, MAX_TABSIZE)
        if _is_int(size) and len(s) + s.count("\t" if isinstance(s, str) else b"\t") * size > MAX_SEQ:
            raise _too_long()
    elif name == "replace":
        _check_replace(s, arg(0, "old"), arg(1, "new"), arg(2, "count", -1))
    elif name == "join" and args:
        items = args[0] if isinstance(args[0], (list, tuple)) else list(args[0])
        _check_join(s, items)
        args = (items, *args[1:])
    elif name == "translate" and isinstance(s, str) and args and isinstance(args[0], dict):
        widest = max((len(v) for v in args[0].values() if isinstance(v, str)), default=1)
        if len(s) * widest > MAX_SEQ:
            raise _too_long()
    elif name in ("format", "format_map") and isinstance(s, str):
        _check_str_format(s, (*args, *kwargs.values()) if name == "format" else args)
    return args


def _lipsum(n=5, html=True, min=20, max=100):  # noqa: A002 - Jinja's own argument names
    if _is_int(n) and _is_int(max) and n * max > 100_000:
        raise TemplateTooLarge("lipsum is asked for more than 100,000 words")
    return generate_lorem_ipsum(n=n, html=html, min=min, max=max)


class _GuardedNamespace(Namespace):
    """`namespace()` whose values cannot grow past the size limit, and whose every write counts as a step."""

    def __setitem__(self, name, value):
        _tick()
        _check_size(value)
        super().__setitem__(name, value)


class _BudgetedCodeGenerator(CodeGenerator):
    """Writes `environment.budget_*(...)` around loop iterables, concatenation and output. The calls go to the module
    global `environment`, which a template cannot shadow: template variables compile to prefixed local names. (Jinja
    refuses custom node types, so the loop iterable is marked by identity rather than wrapped in a node.)"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop_iters: set[int] = set()

    def visit_For(self, node, frame):
        if node.recursive:  # every call of a recursive loop, the first included, iterates `reciter`: see write()
            return super().visit_For(node, frame)
        self._loop_iters.add(id(node.iter))
        try:
            super().visit_For(node, frame)
        finally:
            self._loop_iters.discard(id(node.iter))

    def visit(self, node, *args, **kwargs):
        if id(node) not in self._loop_iters:
            return super().visit(node, *args, **kwargs)
        self._loop_iters.discard(id(node))
        self.write("environment.budget_iter(")
        super().visit(node, *args, **kwargs)
        self.write(")")

    def write(self, x):
        super().write("environment.budget_iter(reciter)" if x == "reciter" else x)

    @optimizeconst
    def visit_Concat(self, node, frame):
        if frame.eval_ctx.volatile:
            markup = "context.eval_ctx.autoescape"
        else:
            markup = "True" if frame.eval_ctx.autoescape else "False"
        self.write("environment.budget_concat((")
        for arg in node.nodes:
            self.visit(arg, frame)
            self.write(", ")
        self.write(f"), {markup})")

    def _output_const_repr(self, group):
        return f"environment.budget_out({super()._output_const_repr(group)})"

    def _output_child_pre(self, node, frame, finalize):
        self.write("environment.budget_out(")
        super()._output_child_pre(node, frame, finalize)

    def _output_child_post(self, node, frame, finalize):
        super()._output_child_post(node, frame, finalize)
        self.write(")")


class _CountedIter:
    __slots__ = ("_inner",)

    def __init__(self, inner):
        self._inner = inner

    def __iter__(self):
        for item in self._inner:
            _tick()
            yield item

    def __len__(self):
        return len(self._inner)  # TypeError when the inner has no length, which LoopContext handles


def _guard_filter(name: str, func):
    """A filter whose str or list result cannot pass the size limit, with a pre-check for the filters whose cost is set
    by an argument."""
    pre = _FILTER_CHECKS.get(name)
    inner = inspect.unwrap(func)
    # Jinja's async_variant filters (slice, for one) take a pass argument their wrapped function does not declare
    skip = 1 if getattr(func, "jinja_pass_arg", None) is not None and getattr(inner, "jinja_pass_arg", None) is None else 0
    sig = inspect.signature(inner) if pre else None

    @functools.wraps(func)  # keeps the jinja_pass_arg marker
    def guarded(*args, **kwargs):
        if pre is not None:
            try:
                bound = sig.bind(*args[skip:], **kwargs)
            except TypeError:
                pass  # wrong arguments: the filter raises its own error
            else:
                bound.apply_defaults()
                pre(bound.arguments)
                args, kwargs = (*args[:skip], *bound.args), bound.kwargs
        result = func(*args, **kwargs)
        if isinstance(result, (str, list)) and len(result) > MAX_SEQ:
            raise _too_long()
        return result

    return guarded


def _pre_indent(a):
    width = a["width"]
    w = len(width) if isinstance(width, str) else width if _is_int(width) else 0
    s = str(a["s"])
    if len(s) + (s.count("\n") + 1) * w > MAX_SEQ:
        raise _too_long()


def _pre_format(a):
    _check_percent(str(a["value"]), a["kwargs"] or a["args"])


def _pre_join(a):
    value = a["value"]
    if not isinstance(value, (list, tuple)):
        a["value"] = value = list(value)
    eval_ctx = a.get("eval_ctx")
    _check_join(a["d"], value, a["attribute"], eval_ctx.environment if eval_ctx is not None else None)


def _pre_sum(a):
    if not (isinstance(a["start"], (int, float)) or a["start"] is None):
        raise TemplateTooLarge("the sum filter adds numbers only")


_FILTER_CHECKS = {
    "center": lambda a: _check_width(a["width"]),
    "indent": _pre_indent,
    "format": _pre_format,
    "join": _pre_join,
    "replace": lambda a: _check_replace(str(a["s"]), a["old"], a["new"], a["count"]),
    "batch": lambda a: _check_width(a["linecount"]),
    "slice": lambda a: _check_width(a["slices"]),
    "sum": _pre_sum,
}


class _Lenient(Undefined):
    """Missing merge fields render as blank instead of failing the whole document."""

    def __str__(self):
        return ""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self

    def __getitem__(self, key):
        return self

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False


class _Sandbox(ImmutableSandboxedEnvironment):
    """Admins edit templates in the browser, so templates never reach Python internals or mutate data."""

    code_generator_class = _BudgetedCodeGenerator
    intercepted_binops = frozenset({"*", "**", "+", "%"})  # also stops Jinja folding these at compile time

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.globals["namespace"] = _GuardedNamespace
        self.globals["lipsum"] = _lipsum

    def guard_filters(self) -> None:
        self.filters = {name: _guard_filter(name, f) for name, f in self.filters.items()}

    def unsafe_undefined(self, obj, attribute):
        raise SecurityError(f"Templates cannot use '{attribute}'.")

    def budget_iter(self, iterable):
        return _CountedIter(iterable)

    def budget_concat(self, parts, markup):
        """`a ~ b`: measured before joining, so doubling a string cannot run away."""
        if markup:  # inside {% autoescape true %}: escaping can lengthen the parts, so the result is checked too
            if sum(len(p) for p in parts if isinstance(p, str)) > MAX_SEQ:
                raise _too_long()
            return _check_size(markup_join(parts))
        parts = [p if isinstance(p, str) else str(p) for p in parts]
        if sum(map(len, parts)) > MAX_SEQ:
            raise _too_long()
        return "".join(parts)

    def budget_out(self, text):
        b = _budget.get()
        if b is not None:
            b.out += len(text)
            if b.out > MAX_OUTPUT:
                raise TemplateTooLarge(f"it writes more than {MAX_OUTPUT:,} characters")
        return text

    def call_binop(self, context, operator, left, right):
        if operator == "*":
            for seq, n in ((left, right), (right, left)):
                if isinstance(seq, _SEQ) and _is_int(n) and len(seq) * n > MAX_SEQ:
                    raise _too_long()
            if _is_int(left) and _is_int(right) and left.bit_length() + right.bit_length() > _INT_BITS:
                raise TemplateTooLarge(f"it builds a number of more than {MAX_DIGITS} digits")
        elif operator == "+":
            if isinstance(left, _SEQ) and isinstance(right, _SEQ) and len(left) + len(right) > MAX_SEQ:
                raise _too_long()
        elif operator == "**":
            if _is_int(left) and _is_int(right) and right > 0 and abs(left) > 1 and (right > _INT_BITS or right * math.log10(abs(left)) > MAX_DIGITS):
                raise TemplateTooLarge(f"it builds a number of more than {MAX_DIGITS} digits")
        elif operator == "%" and isinstance(left, str):
            _check_percent(left, right)
        return super().call_binop(context, operator, left, right)

    def call(__self, __context, __obj, *args, **kwargs):  # noqa: N805 - Jinja's signature, so no keyword can clash
        _tick()
        try:
            target = getattr(__obj, "__wrapped__", __obj)  # str.format comes wrapped by the sandbox
            owner = getattr(target, "__self__", None)
            name = getattr(target, "__name__", "")
        except Exception:
            owner = None
        if isinstance(owner, (str, bytes)):
            args = _check_str_method(owner, name, args, kwargs)
        elif _is_int(owner) and name == "to_bytes":
            _check_width(args[0] if args else kwargs.get("length"))
        return _check_size(super().call(__context, __obj, *args, **kwargs))


MD_SPECIAL = str.maketrans({c: "\\" + c for c in "\\[]*_`<>"})  # the backslash too: left alone it undoes the other escapes (review 11-25 #4)


class _MdSafe(str):
    """Text a filter has already escaped completely; the finaliser leaves it as it is."""


def md_inline(value):
    """Escape Markdown that would turn client-supplied text into links, emphasis or code. A missing value prints as
    nothing, never as "None"."""
    if value is None:
        return ""
    if isinstance(value, _MdSafe):
        return str(value)
    return value.translate(MD_SPECIAL) if isinstance(value, str) else value


_ORDERED = re.compile(r"^(\d+)([.)])")


def md_block(value) -> str:
    """Client-written paragraphs (a planned action, a commitment): line breaks and paragraphs are kept, but no line can
    start a heading, list, quote, table, code block or setext underline, and links and emphasis are escaped as in
    md_inline."""
    if value is None or isinstance(value, Undefined):
        return _MdSafe("")
    out = []
    for line in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.strip().translate(MD_SPECIAL).replace("|", "\\|")  # leading spaces would make a code block
        if m := _ORDERED.match(line):
            line = m.group(1) + "\\" + line[len(m.group(1)):]
        elif line[:1] in ("#", "+", "-", "=", "~"):
            line = "\\" + line
        out.append(line)
    return _MdSafe("\n".join(out))


def md_cell(value) -> str:
    """Make a value safe inside a Markdown table cell: no line breaks, pipes escaped."""
    if value is None or isinstance(value, Undefined):
        return ""
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value)
    return " ".join(str(value).split()).replace("|", "\\|")


_env = _Sandbox(undefined=_Lenient, trim_blocks=True, lstrip_blocks=True, autoescape=False, finalize=md_inline)
_env.filters["md_cell"] = md_cell
_env.filters["md_block"] = md_block
_env.guard_filters()
_strict = _Sandbox(undefined=StrictUndefined)
_strict.filters["md_cell"] = md_cell
_strict.filters["md_block"] = md_block
_strict.guard_filters()


def load_templates(db: Session) -> str:
    index = yaml.safe_load((TEMPLATE_DIR / "index.yaml").read_text(encoding="utf-8"))["templates"]
    n = refreshed = 0
    for t in index:
        rows = list(db.scalars(select(DocumentTemplate).where(DocumentTemplate.key == t["key"])))
        if rows:
            # a template nobody has edited follows the shipped file; an admin's edit is a new version and is kept
            if len(rows) == 1 and rows[0].created_by is None and rows[0].active:
                shipped = (TEMPLATE_DIR / f"{t['key']}.md.j2").read_text(encoding="utf-8")
                if rows[0].body != shipped:
                    rows[0].body = shipped
                    refreshed += 1
            continue
        db.add(DocumentTemplate(
            key=t["key"], name=t["name"], type=t["type"], version=1, body=(TEMPLATE_DIR / f"{t['key']}.md.j2").read_text(encoding="utf-8"),
            package_item=t.get("package_item"), requires_action=t.get("requires_action"), format=t.get("format", "md"), active=True,
        ))
        n += 1
    db.flush()
    return f"{n} templates added" + (f", {refreshed} updated to the shipped version" if refreshed else "")


def active_template(db: Session, key: str) -> DocumentTemplate:
    t = db.scalar(select(DocumentTemplate).where(DocumentTemplate.key == key, DocumentTemplate.active.is_(True)))
    if t is None:
        raise NotFound(f"Template {key} not found.")
    return t


def render_string(body: str, context: dict, seconds: float = RENDER_SECONDS) -> str:
    """Render a template body within its own budget; raises TemplateTooLarge (422) when it would do too much work."""
    token = _budget.set(_Budget(seconds))
    try:
        return _env.from_string(body).render(**context).strip()
    finally:
        _budget.reset(token)


def render_template(db: Session, key: str, context: dict) -> str:
    return render_string(active_template(db, key).body, context)


def edit_template(db: Session, actor: User, key: str, body: str) -> DocumentTemplate:
    if len(body) > MAX_BODY:
        raise Invalid("The template is too long.", [{"field": "body", "message": f"A template can be up to {MAX_BODY:,} characters; this one has {len(body):,}."}])
    try:
        _strict.parse(body)
    except TemplateSyntaxError as exc:
        raise Invalid("The template has a merge-field error.", [{"field": "body", "message": f"Line {exc.lineno}: {exc.message}"}])
    try:
        render_string(body, {}, seconds=SAVE_SECONDS)  # test render: missing fields are blank, unsafe, broken or runaway expressions fail here, not at generation
    except TemplateTooLarge:
        raise
    except Exception as exc:
        raise Invalid("The template could not be rendered.", [{"field": "body", "message": str(exc)[:300]}])
    current = active_template(db, key)
    latest = db.scalar(select(func.max(DocumentTemplate.version)).where(DocumentTemplate.key == key)) or 1
    current.active = False
    new = DocumentTemplate(key=key, name=current.name, type=current.type, version=latest + 1, body=body, package_item=current.package_item, requires_action=current.requires_action, format=current.format, active=True, created_by=actor.id)
    db.add(new)
    db.flush()
    audit.record(db, actor_id=actor.id, action="template.edit", object_type="DocumentTemplate", object_id=new.id, organization_id=actor.organization_id, summary=f"Saved {current.name} as version {new.version}")
    return new
