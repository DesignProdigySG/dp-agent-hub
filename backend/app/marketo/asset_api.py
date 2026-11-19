"""Every Marketo Asset API operation as an agent tool, generated from Adobe's spec.

asset_api.json is built from Adobe's Swagger file by scripts/gen_asset_catalog.py (220
operations: emails, email templates, landing pages and their templates, forms, snippets, files,
programs, smart campaigns, folders, tokens...). Each becomes a tool named `asset_<operation>`
(e.g. `asset_create_email_template`), grouped by Adobe's own grouping in the agent builder.

Arguments are flat: path and query parameters, plus the request body's fields. The hub sends
them the way Marketo expects: form fields with objects (like `folder`) as JSON, `content` as
an uploaded file for multipart operations, JSON bodies as JSON. Reads are "read"; deletes,
approvals and other changes that are hard to undo are "destructive"; everything else "write".
All calls share the rate governor.
"""

import functools
import json
import re
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).parent / "asset_api.json"
DESTRUCTIVE = re.compile(r"^(delete|approve|unapprove|discard|activate|deactivate|unarchive|"
                         r"archive|remove)", re.I)
DESIGN_GROUPS = ("Email", "Landing Page", "Form", "Snippet", "File", "Fragment")


# Fields Adobe's spec leaves out but Marketo needs: a dynamic content update names the segment
# it sets (a segment name, or "Default").
MISSING_FIELDS = {
    "updateEmailDynamicContentUsingPOST": {
        "segment": {"type": "string", "description": "Segment to set: its name, or Default"}},
    "updateLandingPageDynamicContentUsingPOST": {
        "segment": {"type": "string", "description": "Segment to set: its name, or Default"}},
}
# Operations nobody gets, agents or the hub: replacing an email's whole HTML fails on every
# email built from a template (error 709) and would throw away its editable sections. Emails
# are updated by section (asset_update_email_component_content / _dynamic_content).
WITHHELD = {"createEmailFullContentUsingPOST"}


@functools.cache
def operations() -> list[dict[str, Any]]:
    ops = json.loads(CATALOG.read_text())["operations"]
    for op in ops:
        for p in op["params"]:
            if p["in"] == "body" and (extra := MISSING_FIELDS.get(op["operation"])):
                p.setdefault("schema", {}).setdefault("properties", {}).update(extra)
    return [op for op in ops if op["operation"] not in WITHHELD]


SUFFIX = re.compile(r"Using(GET|POST|PUT|DELETE)(_\w+|\d+)?$")


def _snake(text: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", text).lower()


def _base(op: dict[str, Any]) -> str:
    if "/v2/" in op["path"]:  # the "(New)" APIs: generic ids, descriptive summaries
        words = re.findall(r"[A-Za-z]+", op["summary"])
        return "v2" + "".join(w.capitalize() for w in words)
    return SUFFIX.sub("", op["operation"])


def _resource(op: dict[str, Any]) -> str:
    """The asset type in the path, e.g. /rest/asset/v1/email/{id}/... -> "email"."""
    parts = [p for p in op["path"].split("/")[4:] if p and not p.startswith("{")]
    return _snake(re.sub(r"\.json$", "", parts[0])) if parts else "asset"


@functools.cache
def _names() -> dict[str, str]:
    """operationId -> tool name; operations that share a name (e.g. approveDraft for emails
    and snippets) get their asset type appended."""
    ops = operations()
    counts: dict[str, int] = {}
    for op in ops:
        counts[_base(op)] = counts.get(_base(op), 0) + 1
    out: dict[str, str] = {}
    for op in ops:
        name = "asset_" + _snake(_base(op))
        if counts[_base(op)] > 1:
            name += "_" + _resource(op)
        while name in out.values():
            name += "_" + op["method"].lower()
        out[op["operation"]] = name
    return out


def tool_name(op: dict[str, Any]) -> str:
    return _names()[op["operation"]]


READS = ("get", "browse", "filter", "list", "v2_get", "v2_bulk_get", "v2_list")


def risk(op: dict[str, Any]) -> str:
    if op["method"] == "GET" or _snake(_base(op)).startswith(READS):
        return "read"  # incl. POST reads such as "Bulk Get Emails"
    base = _base(op)
    return "destructive" if op["method"] == "DELETE" or DESTRUCTIVE.match(base) else "write"


def is_design(op: dict[str, Any]) -> bool:
    return op["group"].startswith(DESIGN_GROUPS)


def _body_props(op: dict[str, Any]) -> tuple[dict, list[str]]:
    """The request body's fields: a body schema's properties, plus formData parameters."""
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in op["params"]:
        if p["in"] == "body":
            s = p.get("schema", {})
            props.update(s.get("properties", {}))
            required += list(s.get("required", []))
        elif p["in"] == "formData":
            props[p["name"]] = {"type": "string" if p["type"] == "file" else p["type"],
                                "description": p["description"]}
            if p["required"]:
                required.append(p["name"])
    return props, required


def args_schema(op: dict[str, Any]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in op["params"]:
        if p["in"] not in ("path", "query"):  # body / formData below; headers are ours
            continue
        s: dict[str, Any] = {"type": "string" if p["type"] == "file" else p["type"],
                             "description": p["description"]}
        if "enum" in p:
            s["enum"] = p["enum"]
        if p["type"] == "array":
            s["items"] = p.get("items", {"type": "string"})
        props[p["name"]] = s
        if p["required"]:
            required.append(p["name"])
    body, body_required = _body_props(op)
    for name, s in body.items():
        s = dict(s)
        if s.get("type") == "object" and "properties" not in s:
            s["description"] = (s.get("description", "") + " (object, e.g. "
                                '{"id": 123, "type": "Folder"})').strip()
        props.setdefault(name, s)
    required += [r for r in body_required if r not in required]
    return {"type": "object", "properties": props, "required": required}


def describe(op: dict[str, Any]) -> str:
    text = f"Marketo Asset API · {op['group']}: {op['summary']}."
    if op["description"] and op["description"] != op["summary"]:
        text += f" {op['description']}"
    return text + f" ({op['method']} {op['path']})"


def split_args(op: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Arguments → path, query and body for the HTTP call."""
    path, query = op["path"], {}
    body_names = set(_body_props(op)[0])
    for p in op["params"]:
        if p["in"] not in ("path", "query") or p["name"] not in args:
            continue
        v = args[p["name"]]
        if p["in"] == "path":
            path = path.replace("{" + p["name"] + "}", str(v))
        elif p["in"] == "query":
            query[p["name"]] = ",".join(map(str, v)) if isinstance(v, list) else (
                json.dumps(v) if isinstance(v, dict) else v)
    body = {k: v for k, v in args.items() if k in body_names}
    props = _body_props(op)[0]
    files = [k for k in body if k in ("content", "file")
             or "multipart file" in str(props.get(k, {}).get("description", "")).lower()]
    return {"method": op["method"], "path": path, "query": query, "body": body, "files": files,
            "encoding": ("json" if "json" in op["consumes"] else
                         "multipart" if "multipart" in op["consumes"] else "form")}


def by_name() -> dict[str, dict[str, Any]]:
    return {tool_name(op): op for op in operations()}
