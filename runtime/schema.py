"""Minimal JSON-Schema checker for the subset our schemas use
(type, required, properties, items, enum, minimum, maximum). Avoids a jsonschema dependency."""
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas"
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
          "integer": int, "number": (int, float)}


def load(name):
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text())


def errors(obj, schema, path="$"):
    """Return a list of human-readable violations; empty means valid."""
    out = []
    t = schema.get("type")
    if t:
        ok = isinstance(obj, _TYPES[t]) and not (t in ("integer", "number") and isinstance(obj, bool))
        if not ok:
            return [f"{path}: expected {t}, got {type(obj).__name__}"]
    if "enum" in schema and obj not in schema["enum"]:
        out.append(f"{path}: {obj!r} not one of {schema['enum']}")
    if "minimum" in schema and obj < schema["minimum"]:
        out.append(f"{path}: {obj} < minimum {schema['minimum']}")
    if "maximum" in schema and obj > schema["maximum"]:
        out.append(f"{path}: {obj} > maximum {schema['maximum']}")
    if t == "object":
        out += [f"{path}: missing required key {k!r}" for k in schema.get("required", []) if k not in obj]
        for k, sub in schema.get("properties", {}).items():
            if k in obj:
                out += errors(obj[k], sub, f"{path}.{k}")
    if t == "array" and "items" in schema:
        for i, item in enumerate(obj):
            out += errors(item, schema["items"], f"{path}[{i}]")
    return out
