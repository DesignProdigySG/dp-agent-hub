"""Print the JSON Schema for every server->client message.

Usage: python -m app.events.export_schema > ../frontend/src/types/contract.schema.json
"""

import json

from app.events.schema import ServerMessage


def _strip_property_titles(node):
    """Pydantic titles every field; json2ts would turn each into a named alias type."""
    if isinstance(node, dict):
        for prop in node.get("properties", {}).values():
            prop.pop("title", None)
        for v in node.values():
            _strip_property_titles(v)
    elif isinstance(node, list):
        for v in node:
            _strip_property_titles(v)


def main() -> None:
    schema = ServerMessage.model_json_schema(mode="serialization")
    _strip_property_titles(schema)
    schema["title"] = "ServerMessage"
    print(json.dumps(schema, indent=2))


if __name__ == "__main__":
    main()
