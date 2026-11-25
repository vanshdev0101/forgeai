"""The tool registry the factory chooses from. Each tool is a plain function plus an
Ollama/OpenAI-style function schema. The generator picks a subset by name; the runner
only exposes the tools listed in the agent definition."""
import ast
import csv
import datetime as dt
import operator
from pathlib import Path

import requests


def csv_lookup(file, column, value, docs_dir="."):
    """Rows of a CSV in the agent's document folder where `column` contains `value` (case-insensitive)."""
    path = (Path(docs_dir) / file).resolve()
    if path.parent != Path(docs_dir).resolve() or path.suffix.lower() != ".csv":
        return {"error": f"{file!r} is not a CSV in the document folder"}
    if not path.exists():
        return {"error": f"no such file: {file}"}
    with open(path, newline="", errors="replace") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            return {"error": f"no column {column!r}; columns are {reader.fieldnames}"}
        needle = str(value).lower()
        rows = [r for r in reader if needle in str(r.get(column, "")).lower()]
    return {"matches": len(rows), "rows": rows[:20]}


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def calculator(expression):
    """Evaluate an arithmetic expression. Numbers and + - * / // % ** ( ) only; no names, no calls."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("exponent too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        raise ValueError(f"unsupported expression element: {type(node).__name__}")
    try:
        return {"result": ev(ast.parse(str(expression), mode="eval"))}
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as e:
        return {"error": str(e)}


def weather(city):
    """Current weather for a city via open-meteo (keyless): geocode, then forecast."""
    try:
        geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                           params={"name": city, "count": 1}, timeout=15).json()
        if not geo.get("results"):
            return {"error": f"city not found: {city}"}
        place = geo["results"][0]
        wx = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,wind_speed_10m,precipitation,weather_code",
        }, timeout=15).json()
        return {"place": f"{place['name']}, {place.get('country', '')}", "current": wx.get("current")}
    except requests.RequestException as e:
        return {"error": f"weather service unreachable: {e}"}


def current_date():
    """Today's date and weekday in local time."""
    now = dt.datetime.now()
    return {"date": now.date().isoformat(), "weekday": now.strftime("%A"), "time": now.strftime("%H:%M")}


def _fn(name, description, props, required):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required}}}


REGISTRY = {
    "csv_lookup": {
        "fn": csv_lookup,
        "use_when": "the agent must answer from tabular data (catalogues, price lists, inventories) "
                    "that ships as a CSV in its document folder",
        "schema": _fn("csv_lookup", "Find rows in a CSV file from the document folder where a column "
                      "contains a value.", {
                          "file": {"type": "string", "description": "CSV file name, e.g. catalogue.csv"},
                          "column": {"type": "string", "description": "exact column header"},
                          "value": {"type": "string", "description": "text to match (substring, case-insensitive)"},
                      }, ["file", "column", "value"]),
    },
    "calculator": {
        "fn": calculator,
        "use_when": "answers need arithmetic: totals, quantities x prices, pro-rating, percentages",
        "schema": _fn("calculator", "Evaluate an arithmetic expression exactly.", {
            "expression": {"type": "string", "description": "e.g. (12 * 450) * 1.18"},
        }, ["expression"]),
    },
    "weather": {
        "fn": weather,
        "use_when": "the brief explicitly involves live weather or sea/port conditions",
        "schema": _fn("weather", "Current weather for a named city or port.", {
            "city": {"type": "string"},
        }, ["city"]),
    },
    "current_date": {
        "fn": current_date,
        "use_when": "answers depend on today's date: deadlines, eligibility windows, lead times, ages",
        "schema": _fn("current_date", "Get today's date and weekday.", {}, []),
    },
}


def call(name, args, allowed, docs_dir="."):
    """Run a tool the agent is allowed to use. Errors come back as data, never raise."""
    if name not in allowed or name not in REGISTRY:
        return {"error": f"tool {name!r} is not available to this agent"}
    args = dict(args or {})
    if name == "csv_lookup":
        args["docs_dir"] = docs_dir
    try:
        return REGISTRY[name]["fn"](**args)
    except TypeError as e:
        return {"error": f"bad arguments for {name}: {e}"}
