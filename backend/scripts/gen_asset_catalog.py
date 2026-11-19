"""Build app/marketo/asset_api.json from Adobe's Marketo Asset API Swagger spec.

    curl -sLo /tmp/swagger-asset.json \\
      https://raw.githubusercontent.com/AdobeDocs/marketo-apis/main/static/swagger-asset.json
    .venv/bin/python scripts/gen_asset_catalog.py /tmp/swagger-asset.json

Keeps what the hub needs to offer each operation as an agent tool: method, path, group, a
short description, and its parameters (request bodies resolved to JSON Schema, two levels).
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "marketo" / "asset_api.json"
TYPES = {"integer": "integer", "number": "number", "boolean": "boolean", "array": "array",
         "string": "string", "file": "file", "object": "object"}


def short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def resolve(schema: dict, defs: dict, depth: int = 0) -> dict:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        if depth >= 2:
            return {"type": "object", "description": name}
        return resolve(defs.get(name, {"type": "object"}), defs, depth + 1)
    out: dict = {k: schema[k] for k in ("type", "enum", "format") if k in schema}
    if schema.get("description"):
        out["description"] = short(schema["description"], 200)
    if schema.get("type") == "array" and "items" in schema:
        out["items"] = resolve(schema["items"], defs, depth + 1)
    if "properties" in schema:
        out["type"] = "object"
        out["properties"] = {k: resolve(v, defs, depth + 1)
                             for k, v in schema["properties"].items()}
        if schema.get("required"):
            out["required"] = schema["required"]
    return out or {"type": "object"}


def main(src: str) -> None:
    spec = json.loads(Path(src).read_text())
    defs = spec.get("definitions", {})
    ops = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method not in ("get", "post", "put", "delete"):
                continue
            params = []
            for p in op.get("parameters", []):
                entry = {"name": p["name"], "in": p["in"], "required": bool(p.get("required")),
                         "description": short(p.get("description", ""), 240)}
                if p["in"] == "body":
                    entry["schema"] = resolve(p.get("schema", {}), defs)
                else:
                    entry["type"] = TYPES.get(p.get("type", "string"), "string")
                    if "enum" in p:
                        entry["enum"] = p["enum"]
                    if p.get("type") == "array":
                        entry["items"] = {"type": p.get("items", {}).get("type", "string")}
                params.append(entry)
            ops.append({"operation": op["operationId"], "method": method.upper(), "path": path,
                        "group": (op.get("tags") or ["Other"])[0],
                        "summary": short(op.get("summary", ""), 120),
                        "description": short(op.get("description", ""), 400),
                        "consumes": (op.get("consumes") or [""])[0], "params": params})
    ops.sort(key=lambda o: (o["group"], o["path"], o["method"]))
    OUT.write_text(json.dumps({"source": "AdobeDocs/marketo-apis static/swagger-asset.json",
                               "title": spec["info"]["title"], "operations": ops}, indent=0))
    print(f"wrote {len(ops)} operations to {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(sys.argv[1])
