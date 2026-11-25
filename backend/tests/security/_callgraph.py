"""Static call graph of the `app` package, used by the permission tests to prove a route handler reaches `authorize`.

The graph is deliberately generous: a function "uses" every name it mentions (called or passed, as with `Depends(x)`), and a
nested function's names count for the function that defines it. A route that does not reach `authorize` even under these
rules has no path to the permission check at all.
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "app"
AUTHORIZE = "app.policy.authorize.authorize"


def _module_name(path: Path) -> str:
    rel = path.relative_to(APP_DIR.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class _Module:
    def __init__(self, name: str, tree: ast.Module, is_pkg: bool):
        self.name = name
        self.is_pkg = is_pkg
        self.imports: dict[str, str] = {}
        self.toplevel: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        self.imports[a.asname] = a.name
                    else:
                        self.imports[a.name.split(".")[0]] = a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    pkg = name.split(".") if is_pkg else name.split(".")[:-1]
                    pkg = pkg[: len(pkg) - (node.level - 1)]
                    base = ".".join(pkg + ([node.module] if node.module else []))
                for a in node.names:
                    self.imports[a.asname or a.name] = f"{base}.{a.name}"
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.toplevel.add(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        self.toplevel.add(t.id)


def _dotted(node: ast.AST) -> list[str] | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return None


class CallGraph:
    def __init__(self) -> None:
        self.modules: dict[str, _Module] = {}
        self.funcs: dict[str, set[tuple[str, ...]]] = {}  # qualified name -> raw dotted references
        self.func_module: dict[str, str] = {}
        self.local_defs: dict[str, dict[str, str]] = {}  # function qualname -> nested def name -> qualname
        trees = {}
        for path in sorted(APP_DIR.rglob("*.py")):
            name = _module_name(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            trees[name] = tree
            self.modules[name] = _Module(name, tree, path.name == "__init__.py")
        for name, tree in trees.items():
            self._collect(name, tree.body, prefix="", owner=None)
        self.edges = {q: self._resolve_refs(q) for q in self.funcs}
        self._reach: dict[str, bool] = {}

    def _collect(self, mod: str, body, prefix: str, owner: str | None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{mod}.{prefix}{node.name}"
                refs = set()
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.Name, ast.Attribute)):
                        d = _dotted(sub)
                        if d:
                            refs.add(tuple(d))
                self.funcs[qual] = refs
                self.func_module[qual] = mod
                if owner:
                    self.local_defs.setdefault(owner, {})[node.name] = qual
                    # the enclosing function uses what its nested function uses
                    self.funcs[owner].add(("<nested>", qual))
                self._collect(mod, node.body, prefix=f"{prefix}{node.name}.<locals>.", owner=qual)
            elif isinstance(node, ast.ClassDef):
                self._collect(mod, node.body, prefix=f"{prefix}{node.name}.", owner=owner)

    def _canonical(self, target: str, depth: int = 0) -> str:
        """Follow re-exports: `app.x.f` where module app.x imported f from elsewhere."""
        if depth > 10 or target in self.funcs or target in self.modules:
            return target
        mod, _, attr = target.rpartition(".")
        m = self.modules.get(mod)
        if m and attr in m.imports and attr not in m.toplevel:
            return self._canonical(m.imports[attr], depth + 1)
        return target

    def _resolve(self, qual: str, parts: tuple[str, ...]) -> str | None:
        if parts[0] == "<nested>":
            return parts[1]
        mod = self.func_module[qual]
        m = self.modules[mod]
        head, rest = parts[0], list(parts[1:])
        # nested defs visible from this function or an enclosing one
        scope = qual
        while True:
            if head in self.local_defs.get(scope, {}):
                return self.local_defs[scope][head]
            if ".<locals>." not in scope:
                break
            scope = scope.rsplit(".<locals>.", 1)[0]
        if head in m.toplevel:
            base = f"{mod}.{head}"
        elif head in m.imports:
            base = self._canonical(m.imports[head])
        else:
            return None
        while rest:
            nxt = self._canonical(f"{base}.{rest[0]}")
            if nxt in self.funcs or nxt in self.modules or base in self.modules or f"{base}.{rest[0]}" in self.funcs:
                base = nxt
                rest.pop(0)
            else:
                break
        return base

    def _resolve_refs(self, qual: str) -> set[str]:
        out = set()
        for parts in self.funcs[qual]:
            r = self._resolve(qual, parts)
            if r:
                out.add(self._canonical(r))
        return out

    def reaches(self, qual: str, target: str = AUTHORIZE) -> bool:
        """True when `qual` mentions `target`, directly or through any function it mentions."""
        seen: set[str] = set()
        stack = [qual]
        while stack:
            q = stack.pop()
            if q in seen:
                continue
            seen.add(q)
            for nxt in self.edges.get(q, ()):
                if nxt == target:
                    return True
                if nxt in self.edges and nxt not in seen:
                    stack.append(nxt)
        return False


@lru_cache(maxsize=1)
def graph() -> CallGraph:
    return CallGraph()


def qualname(fn) -> str:
    fn = getattr(fn, "__wrapped__", fn)
    return f"{fn.__module__}.{fn.__qualname__}"
