"""Minimal valid request bodies built from the OpenAPI document, so a request gets past schema validation and reaches
the permission check (a 422 from schema validation proves nothing about permissions)."""
from __future__ import annotations

import re
import uuid
from functools import lru_cache

from tests.security._routes import bare_app

PLACEHOLDER = re.compile(r"\{(\w+)(?::\w+)?\}")


@lru_cache(maxsize=1)
def openapi() -> dict:
    return bare_app().openapi()


def _deref(spec: dict, schema: dict) -> dict:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 20:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
        seen += 1
    return schema or {}


def sample(spec: dict, schema: dict, depth: int = 0):
    schema = _deref(spec, schema)
    if depth > 6:
        return None
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [o for o in schema[key] if _deref(spec, o).get("type") != "null"]
            return sample(spec, options[0], depth + 1) if options else None
    if "allOf" in schema:
        out = {}
        for part in schema["allOf"]:
            v = sample(spec, part, depth + 1)
            if isinstance(v, dict):
                out.update(v)
        return out
    t = schema.get("type")
    fmt = schema.get("format", "")
    if t == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {k: sample(spec, props[k], depth + 1) for k in schema.get("required", []) if k in props}
    if t == "array":
        n = schema.get("minItems", 0)
        return [sample(spec, schema.get("items", {}), depth + 1) for _ in range(n)]
    if t == "integer":
        return max(1, schema.get("minimum", 1))
    if t == "number":
        return max(1, schema.get("minimum", 1))
    if t == "boolean":
        return False
    if t == "string":
        if fmt == "uuid":
            return str(uuid.uuid4())
        if fmt == "date":
            return "2026-11-02"
        if fmt == "date-time":
            return "2026-11-02T10:00:00"
        if fmt == "email":
            return "nobody@example.test"
        if fmt in ("uri", "url"):
            return "https://example.test/x"
        n = max(schema.get("minLength", 1), 1)
        return ("x" * n)[: schema.get("maxLength", n) or n]
    return {}


def operation(path: str, method: str) -> dict | None:
    return openapi().get("paths", {}).get(path, {}).get(method.lower())


def request_kwargs(path: str, method: str) -> dict:
    """Keyword arguments for TestClient.request: a JSON body, form fields or a file, as the operation declares."""
    if method == "GET" or method == "DELETE":
        op = operation(path, method)
        if not op or "requestBody" not in op:
            return {}
    op = operation(path, method)
    if op is None:
        return {"json": {}}
    spec = openapi()
    out: dict = {}
    query = {p["name"]: sample(spec, p.get("schema", {})) for p in op.get("parameters", []) if p.get("in") == "query" and p.get("required")}
    if query:
        out["params"] = query
    body = op.get("requestBody")
    if not body:
        return out | ({"json": {}} if method not in ("GET", "DELETE") else {})
    content = body.get("content", {})
    if "application/json" in content:
        out["json"] = sample(spec, content["application/json"].get("schema", {}))
        if out["json"] is None:
            out["json"] = {}
    elif "multipart/form-data" in content:
        schema = _deref(spec, content["multipart/form-data"].get("schema", {}))
        data, files = {}, {}
        for name, prop in schema.get("properties", {}).items():
            p = _deref(spec, prop)
            is_file = p.get("format") == "binary" or p.get("contentMediaType") == "application/octet-stream" or (
                p.get("type") == "array" and _deref(spec, p.get("items", {})).get("format") == "binary")
            if is_file:
                files[name] = ("probe.csv", b"name\nx\n", "text/csv")
            elif name in schema.get("required", []):
                v = sample(spec, p)
                data[name] = v if isinstance(v, str) else str(v)
        out["data"], out["files"] = data, files or {"file": ("probe.csv", b"name\nx\n", "text/csv")}
    elif "application/x-www-form-urlencoded" in content:
        schema = _deref(spec, content["application/x-www-form-urlencoded"].get("schema", {}))
        out["data"] = {k: str(sample(spec, schema["properties"][k])) for k in schema.get("required", []) if k in schema.get("properties", {})}
    else:
        out["json"] = {}
    return out


def fill_path(path: str, values: dict[str, str] | None = None) -> str:
    values = values or {}
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), uuid.uuid4())), path)
